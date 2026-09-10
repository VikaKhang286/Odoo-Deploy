# -*- coding: utf-8 -*-
"""Sprint 1 MCP endpoints — design/production task workflow.

New v1 routes:
  GET   /dac_erp/mcp/v1/orders/<id>/task-context
  POST  /dac_erp/mcp/v1/orders/<id>/assign-designer
  POST  /dac_erp/mcp/v1/orders/<id>/ensure-design-task
  POST  /dac_erp/mcp/v1/orders/<id>/ensure-production-task
  PATCH /dac_erp/mcp/v1/tasks/<id>/status
  POST  /dac_erp/mcp/v1/tasks/<id>/note
  POST  /dac_erp/mcp/v1/tasks/<id>/blocker

All v1 routes are also exposed via v2 wrapper in mcp_v2_wrapper.py.

Serializer: _serialize_mcp_task() is overridden to include snap_* + blocker fields.
MONETARY FIELDS ARE NEVER INCLUDED in task responses.
"""
import json
import logging

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError

from .mcp import McpHttpError, MCPReadController

_logger = logging.getLogger(__name__)

# Monetary fields that must NEVER appear in task context responses
_MONETARY_BLACKLIST = frozenset({
    'amount_total', 'amount_untaxed', 'amount_tax',
    'deposit_amount', 'total_deposit_paid', 'remaining_amount_display',
    'promotion_amount', 'price_unit', 'price_subtotal',
})

_ALLOWED_TASK_STATES = {'draft', 'in_progress', 'done', 'cancelled'}
_TERMINAL_STATES = {'done', 'cancelled'}
_BLOCKABLE_STATES = {'draft', 'in_progress'}

MCP_TASK_LOG = 'dac.erp.mcp.task.log'


class MCPSprint1Controller(MCPReadController):
    """Sprint 1 — design/production task workflow endpoints.

    Extends MCPReadController with:
    - Enhanced _serialize_mcp_task (snap_* fields, blocker, task_type)
    - New order task-context and task workflow endpoints
    """

    # ══════════════════════════════════════════════════════════════════
    # Serializer override — adds snap_* fields. NEVER includes monetary.
    # ══════════════════════════════════════════════════════════════════

    def _serialize_mcp_task(self, task):
        base = super()._serialize_mcp_task(task)
        base.update({
            'task_type': task.task_type,
            'description_plain': task.description_plain or None,
            'days_left_display': task.days_left_display or None,
            'is_personal_reminder': bool(task.is_personal_reminder),
            'is_blocked': bool(task.is_blocked),
            'blocker_reason': task.blocker_reason or None,
            'blocker_reported_at': (
                task.blocker_reported_at.isoformat()
                if task.blocker_reported_at else None
            ),
            # Snapshot fields (safe — no monetary data)
            'snap_order_title':         task.snap_order_title or None,
            'snap_order_summary':       task.snap_order_summary or None,
            'snap_order_number':        task.snap_order_number or None,
            'snap_design_deadline':     str(task.snap_design_deadline) if task.snap_design_deadline else None,
            'snap_design_link':         task.snap_design_link or None,
            'snap_production_deadline': str(task.snap_production_deadline) if task.snap_production_deadline else None,
            'snap_delivery_address':    task.snap_delivery_address or None,
            'snap_installation_address': task.snap_installation_address or None,
            'snap_is_priority':         bool(task.snap_is_priority),
            'snap_is_priority_today':   bool(task.snap_is_priority_today),
            'snap_fulfillment_method':  task.snap_fulfillment_method or None,
            'snap_contact_phone':       task.snap_contact_phone or None,
            'snap_updated_at':          (
                task.snap_updated_at.isoformat()
                if task.snap_updated_at else None
            ),
        })
        return base

    # ══════════════════════════════════════════════════════════════════
    # Idempotency helpers (task log)
    # ══════════════════════════════════════════════════════════════════

    def _s1_check_replay(self, env, request_id):
        """Return (cached_response_dict, True) if replay, else (None, False)."""
        if not request_id:
            return None, False
        existing = env[MCP_TASK_LOG].sudo().search(
            [('request_id', '=', request_id)], limit=1
        )
        if existing:
            try:
                return json.loads(existing.response_json or '{}'), True
            except Exception:
                return {}, True
        return None, False

    def _s1_write_log(self, env, action_type, request_id, agent_name,
                      payload, response_data, task=None, status='success'):
        vals = {
            'action_type': action_type,
            'request_id': request_id or '',
            'agent_name': agent_name or '',
            'payload_json': json.dumps(payload, ensure_ascii=False, default=str),
            'response_json': json.dumps(response_data, ensure_ascii=False, default=str),
            'status': status,
        }
        if task:
            vals['task_id'] = task.id
        try:
            env[MCP_TASK_LOG].sudo().create(vals)
        except Exception as exc:
            _logger.warning("Sprint1: failed to write task log: %s", exc)

    def _s1_require_payload_fields(self, payload, *required):
        """Raise 400 if any required field is missing from payload."""
        missing = [f for f in required if not payload.get(f)]
        if missing:
            raise McpHttpError(
                400, 'validation_error',
                'Thiếu field bắt buộc: ' + ', '.join(missing)
            )

    # ══════════════════════════════════════════════════════════════════
    # Dispatchers
    # ══════════════════════════════════════════════════════════════════

    def _dispatch_s1_order_task_context(self, order_id,
                                         env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)

        order = env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            raise McpHttpError(404, 'not_found', f'Order {order_id} not found')

        tasks = env['dac.work.task'].sudo().search([
            ('order_id', '=', order_id),
            ('state', 'not in', ['cancelled']),
        ])

        data = {
            'order_id': order.id,
            'order_name': order.name,
            'order_number': getattr(order, 'order_number', None) or order.name,
            'order_state_custom': order.order_state_custom,
            'user_id_design': order.user_id_design.id if order.user_id_design else None,
            'user_id_design_name': order.user_id_design.name if order.user_id_design else None,
            'user_id_production': order.user_id_production.id if order.user_id_production else None,
            'user_id_production_name': order.user_id_production.name if order.user_id_production else None,
            'design_done': bool(getattr(order, 'design_done', False)),
            'production_done': bool(getattr(order, 'production_done', False)),
            'design_deadline': str(order.design_deadline) if order.design_deadline else None,
            'production_deadline': str(order.production_deadline) if order.production_deadline else None,
            'tasks': [self._serialize_mcp_task(t) for t in tasks],
        }
        return self._mcp_detail_payload(data), 200

    def _dispatch_s1_order_assign_designer(self, order_id, payload=None,
                                            env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)

        payload = payload or {}
        self._s1_require_payload_fields(payload, 'request_id', 'agent_name', 'user_id_design')

        request_id = payload['request_id']
        agent_name = payload['agent_name']
        cached, is_replay = self._s1_check_replay(env, request_id)
        if is_replay:
            cached['idempotent_replay'] = True
            return self._mcp_detail_payload(cached), 200

        order = env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            raise McpHttpError(404, 'not_found', f'Order {order_id} not found')

        user_id = payload.get('user_id_design')
        design_deadline = payload.get('design_deadline')
        note = payload.get('note', '')

        designer = env['res.users'].sudo().browse(user_id)
        if not designer.exists():
            raise McpHttpError(400, 'validation_error', f'User {user_id} not found')

        try:
            write_vals = {'user_id_design': user_id}
            if design_deadline:
                write_vals['design_deadline'] = design_deadline
            # _sync_design_task() fires automatically from sale.order.write() DANGER ZONE
            order.sudo().write(write_vals)
            if note:
                order.sudo().message_post(body=f'[OpenClaw] {note}', subtype_xmlid='mail.mt_note')
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        # Find the design task created by _sync_design_task
        design_task = env['dac.work.task'].sudo().search([
            ('order_id', '=', order_id),
            ('task_type', '=', 'design'),
            ('state', 'not in', ['cancelled']),
        ], limit=1)

        response_data = {
            'order_id': order.id,
            'user_id_design': user_id,
            'user_id_design_name': designer.name,
            'design_deadline': str(order.design_deadline) if order.design_deadline else None,
            'design_task_id': design_task.id if design_task else None,
            'action': 'assign_designer',
            'idempotent_replay': False,
        }
        self._s1_write_log(env, 'order_assign_designer', request_id, agent_name, payload, response_data)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_s1_order_ensure_task(self, order_id, task_type, payload=None,
                                        env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)

        payload = payload or {}
        self._s1_require_payload_fields(payload, 'request_id', 'agent_name')

        request_id = payload['request_id']
        agent_name = payload['agent_name']
        cached, is_replay = self._s1_check_replay(env, request_id)
        if is_replay:
            cached['idempotent_replay'] = True
            return self._mcp_detail_payload(cached), 200

        order = env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            raise McpHttpError(404, 'not_found', f'Order {order_id} not found')

        assigned_user_id = payload.get('assigned_user_id')
        deadline = payload.get('deadline')
        priority = payload.get('priority', 'normal')
        notes = payload.get('notes', '')

        try:
            task, was_created = env['dac.work.task'].sudo()._create_from_order(
                order,
                task_type=task_type,
                assigned_user_id=assigned_user_id,
                deadline=deadline,
                priority=priority,
                notes=notes,
                created_by_agent=agent_name or 'sale_assignment',
            )
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        response_data = self._serialize_mcp_task(task)
        response_data['was_created'] = was_created
        response_data['idempotent_replay'] = False

        self._s1_write_log(env, 'order_ensure_task', request_id, agent_name, payload,
                           response_data, task=task)
        return self._mcp_detail_payload(response_data), 200 if was_created else 200

    def _dispatch_s1_task_status(self, task_id, payload=None,
                                   env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)

        payload = payload or {}
        self._s1_require_payload_fields(payload, 'request_id', 'agent_name', 'state')

        request_id = payload['request_id']
        agent_name = payload['agent_name']
        new_state = payload['state']
        note = payload.get('note', '')

        if new_state not in _ALLOWED_TASK_STATES:
            raise McpHttpError(
                400, 'validation_error',
                f'Invalid state: {new_state}. Allowed: {sorted(_ALLOWED_TASK_STATES)}'
            )

        cached, is_replay = self._s1_check_replay(env, request_id)
        if is_replay:
            cached['idempotent_replay'] = True
            return self._mcp_detail_payload(cached), 200

        task = env['dac.work.task'].sudo().browse(task_id)
        if not task.exists():
            raise McpHttpError(404, 'not_found', f'Task {task_id} not found')

        if new_state == 'done' and task.is_blocked:
            raise McpHttpError(
                409, 'blocker_not_cleared',
                'Task đang bị block — xoá blocker trước khi đánh dấu hoàn thành'
            )

        old_state = task.state
        try:
            # _sync_to_sale_order fires automatically via write() DANGER ZONE dac_work_task.py:168
            task.write({'state': new_state})
            if note:
                task.message_post(body=f'[OpenClaw] {note}', subtype_xmlid='mail.mt_note')
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        response_data = self._serialize_mcp_task(task)
        response_data['old_state'] = old_state
        response_data['idempotent_replay'] = False

        self._s1_write_log(env, 'task_status', request_id, agent_name, payload,
                           response_data, task=task)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_s1_task_note(self, task_id, payload=None,
                                env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)

        payload = payload or {}
        self._s1_require_payload_fields(payload, 'request_id', 'agent_name', 'note')

        request_id = payload['request_id']
        agent_name = payload['agent_name']
        note_text = payload['note']

        cached, is_replay = self._s1_check_replay(env, request_id)
        if is_replay:
            cached['idempotent_replay'] = True
            return self._mcp_detail_payload(cached), 200

        task = env['dac.work.task'].sudo().browse(task_id)
        if not task.exists():
            raise McpHttpError(404, 'not_found', f'Task {task_id} not found')

        task.message_post(body=f'[OpenClaw/{agent_name}] {note_text}',
                          subtype_xmlid='mail.mt_note')

        response_data = {'task_id': task_id, 'note_posted': True, 'idempotent_replay': False}
        self._s1_write_log(env, 'task_note', request_id, agent_name, payload, response_data, task=task)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_s1_task_blocker(self, task_id, payload=None,
                                   env=None, headers=None, provided_key=None, **_):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)

        payload = payload or {}
        self._s1_require_payload_fields(payload, 'request_id', 'agent_name')

        request_id = payload['request_id']
        agent_name = payload['agent_name']
        clear = bool(payload.get('clear', False))
        reason = payload.get('reason', '')

        if not clear and not reason:
            raise McpHttpError(400, 'validation_error',
                               'Field "reason" bắt buộc khi set blocker (clear=false)')

        cached, is_replay = self._s1_check_replay(env, request_id)
        if is_replay:
            cached['idempotent_replay'] = True
            return self._mcp_detail_payload(cached), 200

        task = env['dac.work.task'].sudo().browse(task_id)
        if not task.exists():
            raise McpHttpError(404, 'not_found', f'Task {task_id} not found')

        if not clear and task.state in _TERMINAL_STATES:
            raise McpHttpError(
                400, 'cannot_block_terminal',
                f'Không thể block task ở trạng thái {task.state}'
            )

        try:
            if clear:
                task.write({
                    'is_blocked': False,
                    'blocker_reason': False,
                    'blocker_reported_at': False,
                    'blocker_reported_by': False,
                })
            else:
                task.write({
                    'is_blocked': True,
                    'blocker_reason': reason,
                    'blocker_reported_at': fields.Datetime.now(),
                    'blocker_reported_by': env.user.id,
                })
                task.message_post(
                    body=f'[OpenClaw/{agent_name}] BLOCKED: {reason}',
                    subtype_xmlid='mail.mt_note',
                )
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        response_data = self._serialize_mcp_task(task)
        response_data['idempotent_replay'] = False
        self._s1_write_log(env, 'task_blocker', request_id, agent_name, payload,
                           response_data, task=task)
        return self._mcp_detail_payload(response_data), 200

    # ══════════════════════════════════════════════════════════════════
    # V1 Routes
    # ══════════════════════════════════════════════════════════════════

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/task-context',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_s1_order_task_context(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_order_task_context, order_id, **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/assign-designer',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_s1_order_assign_designer(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_order_assign_designer,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/ensure-design-task',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_s1_order_ensure_design_task(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_order_ensure_task,
            order_id,
            'design',
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/ensure-production-task',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_s1_order_ensure_production_task(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_order_ensure_task,
            order_id,
            'production',
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v1/tasks/<int:task_id>/status',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_s1_task_status(self, task_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_task_status,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v1/tasks/<int:task_id>/note',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_s1_task_note(self, task_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_task_note,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v1/tasks/<int:task_id>/blocker',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_s1_task_blocker(self, task_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_s1_task_blocker,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )
