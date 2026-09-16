# -*- coding: utf-8 -*-
"""MCP Phase 1 extension routes — cancel/reopen order, customer CRUD, conversation assign.

Tách riêng khỏi mcp.py để dễ review và rollback. Inherit từ MCPReadController,
thừa hưởng toàn bộ helpers: auth, idempotency, audit log, error handling.

Routes mới:
  POST   /dac_erp/mcp/v1/orders/<int:order_id>/actions/cancel
  POST   /dac_erp/mcp/v1/orders/<int:order_id>/actions/reopen
  POST   /dac_erp/mcp/v1/customers
  PATCH  /dac_erp/mcp/v1/customers/<int:partner_id>
  PATCH  /dac_erp/mcp/v1/conversations/<int:conversation_id>/assign
"""
import json
import logging
import re

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError

from .mcp import McpHttpError, MCPReadController


_logger = logging.getLogger(__name__)


# Regex SDT VN — chấp nhận: 10-11 số, có thể +84 ở đầu, có thể có dấu cách
_PHONE_NORMALIZE_RE = re.compile(r'[\s\-\(\)\.]+')


def _normalize_phone(value):
    """Chuẩn hoá SĐT để dedup: bỏ khoảng trắng/dấu, chuyển +84 → 0."""
    if not value:
        return ''
    cleaned = _PHONE_NORMALIZE_RE.sub('', str(value).strip())
    if cleaned.startswith('+84'):
        cleaned = '0' + cleaned[3:]
    elif cleaned.startswith('84') and len(cleaned) == 11:
        cleaned = '0' + cleaned[2:]
    return cleaned


class MCPPhase1ExtensionController(MCPReadController):
    """Phase 1 extension — adds cancel/reopen/customer/assign routes."""

    MCP_CUSTOMER_LOG_MODEL = 'dac_erp.mcp.customer.log'
    MCP_CONV_ASSIGN_LOG_MODEL = 'dac_erp.mcp.conversation.assign.log'

    # Whitelist fields cho customer create
    MCP_CUSTOMER_CREATE_FIELDS = {
        'name', 'phone', 'mobile', 'email', 'street', 'street2', 'city',
        'comment', 'vat', 'user_id', 'customer_fm_id',
        'request_id', 'agent_name', 'model_name', 'reason',
    }
    # Whitelist fields cho customer update
    MCP_CUSTOMER_UPDATE_FIELDS = {
        'name', 'phone', 'mobile', 'email', 'street', 'street2', 'city',
        'comment', 'vat', 'user_id',
        'request_id', 'agent_name', 'model_name', 'reason',
    }
    # Blocked fields cho update (cấu trúc, external key)
    MCP_CUSTOMER_UPDATE_BLOCKED_FIELDS = {
        'parent_id', 'company_id', 'is_company', 'customer_fm_id',
    }

    # Whitelist fields cho conversation assign
    MCP_CONV_ASSIGN_FIELDS = {
        'owner_user_id', 'participant_user_ids',
        'request_id', 'agent_name', 'model_name', 'reason',
    }

    # Window check dedup customer (giờ)
    MCP_CUSTOMER_DEDUP_WINDOW_PARAM = 'dac_erp.mcp_customer_dedup_window_hours'
    MCP_CUSTOMER_DEDUP_WINDOW_DEFAULT = 720  # 30 ngày

    # ─────────────────────────────────────────────────────────────────
    # Section: Override class constant để add cancel/reopen action types
    # ─────────────────────────────────────────────────────────────────

    @property
    def _mcp_order_write_actions(self):
        # Sử dụng property thay vì override constant để tránh thay đổi static
        return MCPReadController.MCP_ORDER_WRITE_ACTIONS | {'order_cancel', 'order_reopen'}

    # ═════════════════════════════════════════════════════════════════
    # ORDER CANCEL / REOPEN
    # ═════════════════════════════════════════════════════════════════

    def _guard_mcp_order_cancel_action(self, order):
        """Kiểm tra điều kiện cancel — chỉ cho phép từ quotation, không có hóa đơn."""
        current_stage = self._get_mcp_order_stage(order)
        if current_stage == 'cancel':
            self._raise_order_workflow_business_violation("Order is already cancelled")
        if current_stage != 'quotation':
            self._raise_order_workflow_business_violation(
                "cancel is only allowed from quotation stage (current: %s)" % current_stage
            )
        # Logic chi tiết deposit/invoice check đã có trong order.action_cancel_order()
        return current_stage

    def _guard_mcp_order_reopen_action(self, order):
        """Kiểm tra điều kiện reopen — chỉ từ cancel về quotation."""
        current_stage = self._get_mcp_order_stage(order)
        if current_stage != 'cancel':
            self._raise_order_workflow_business_violation(
                "reopen is only allowed from cancel stage (current: %s)" % current_stage
            )
        return current_stage

    def _run_mcp_order_cancel_action(self, order_id, payload=None, env=None):
        return self._run_mcp_order_cancel_or_reopen(
            order_id=order_id,
            action_type='order_cancel',
            payload=payload,
            env=env,
        )

    def _run_mcp_order_reopen_action(self, order_id, payload=None, env=None):
        return self._run_mcp_order_cancel_or_reopen(
            order_id=order_id,
            action_type='order_reopen',
            payload=payload,
            env=env,
        )

    def _run_mcp_order_cancel_or_reopen(self, order_id, action_type, payload=None, env=None):
        env = self._get_mcp_order_write_env(env)
        order = self._get_mcp_order_record(order_id, env=env)
        try:
            normalized_payload = self._normalize_mcp_order_action_payload(payload=payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(existing_log, env=env)

        if action_type == 'order_cancel':
            current_stage = self._guard_mcp_order_cancel_action(order)
        else:
            current_stage = self._guard_mcp_order_reopen_action(order)

        before_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        try:
            if action_type == 'order_cancel':
                # Method hiện có trong sale.order — raise UserError nếu fail
                order.sudo().action_cancel_order()
            else:
                # Reopen: cancel → quotation. sale.order.write() có guard raise
                # UserError nếu state='cancel'. Dùng context flag để bypass —
                # an toàn vì đã guard trong _guard_mcp_order_reopen_action và có
                # audit log dac_erp.mcp.order.log lưu trace đầy đủ.
                order.sudo().with_context(allow_reopen_cancelled=True).write({
                    'order_state_custom': 'quotation',
                    'is_quotation_confirmed': False,
                })
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'insufficient_permission', str(exc))

        order.invalidate_recordset()
        after_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        new_stage = self._get_mcp_order_stage(order)

        response_data = {
            'order_id': order.id,
            'action': 'cancel' if action_type == 'order_cancel' else 'reopen',
            'old_stage': current_stage,
            'new_stage': new_stage,
            'order': after_snapshot,
            'idempotent_replay': False,
        }
        conversation_id_map = self._get_order_conversation_id_map(order_ids=[order.id], env=env)
        log_record = self._create_mcp_order_log_phase1(
            env=env,
            order=order,
            action_type=action_type,
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=before_snapshot,
            new_value=after_snapshot,
            response_data=response_data,
            status='success',
            conversation_id=conversation_id_map.get(order.id) or False,
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _create_mcp_order_log_phase1(self, **kwargs):
        """Wrapper bypass check `action_type in MCP_ORDER_WRITE_ACTIONS` của parent.

        Parent's _create_mcp_order_log raise ValueError nếu action_type ngoài whitelist.
        Phase 1 thêm 'order_cancel', 'order_reopen' — model đã có Selection nhưng
        constant Python chưa update. Workaround: tạo log thẳng qua ORM.
        """
        env = self._get_mcp_order_write_env(kwargs.get('env'))
        order = kwargs.get('order')
        conversation_id = kwargs.get('conversation_id')
        action_type = kwargs['action_type']
        normalized_payload = kwargs.get('normalized_payload') or {}
        payload_fingerprint = kwargs.get('payload_fingerprint')
        old_value = kwargs.get('old_value') or {}
        new_value = kwargs.get('new_value') or {}
        response_data = kwargs.get('response_data') or {}
        status = kwargs.get('status', 'success')
        error_code = kwargs.get('error_code')
        error_message = kwargs.get('error_message')

        create_vals = {
            'order_id': order.id if order else False,
            'conversation_id': conversation_id or False,
            'action_type': action_type,
            'request_id': normalized_payload.get('request_id'),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'payload_fingerprint': payload_fingerprint,
            'old_value_json': self._dump_json_text(old_value),
            'new_value_json': self._dump_json_text(new_value),
            'response_snapshot_json': self._dump_json_text(response_data),
            'agent_name': normalized_payload.get('agent_name'),
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'status': status,
            'error_code': error_code or False,
            'error_message': error_message or False,
        }
        return env[self.MCP_ORDER_LOG_MODEL].sudo().create(create_vals)

    def _dispatch_mcp_order_cancel(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_cancel_action(order_id=order_id, payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_reopen(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_reopen_action(order_id=order_id, payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/cancel',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_cancel(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_cancel,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/reopen',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_reopen(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_reopen,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    # ═════════════════════════════════════════════════════════════════
    # CUSTOMER CREATE / UPDATE
    # ═════════════════════════════════════════════════════════════════

    def _normalize_mcp_customer_payload(self, payload, is_update=False):
        """Validate + normalize customer payload. Trả về (partner_vals, metadata)."""
        payload = self._get_v3_json_payload(payload=payload)
        allowed = self.MCP_CUSTOMER_UPDATE_FIELDS if is_update else self.MCP_CUSTOMER_CREATE_FIELDS
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("Trường không được phép: %s" % ', '.join(unknown))

        if is_update:
            blocked = self.MCP_CUSTOMER_UPDATE_BLOCKED_FIELDS & set(payload)
            if blocked:
                raise ValueError("Không cho phép cập nhật trường: %s" % ', '.join(sorted(blocked)))

        # Validate required metadata (request_id, agent_name)
        if 'request_id' not in payload or not isinstance(payload.get('request_id'), str) \
                or not payload.get('request_id').strip():
            raise ValueError("request_id is required")
        if 'agent_name' not in payload or not isinstance(payload.get('agent_name'), str) \
                or not payload.get('agent_name').strip():
            raise ValueError("agent_name is required")

        model_name = payload.get('model_name')
        if model_name not in (None, False):
            if not isinstance(model_name, str):
                raise ValueError("model_name must be a string")
            model_name = model_name.strip() or False
        reason = payload.get('reason')
        if reason not in (None, False):
            if not isinstance(reason, str):
                raise ValueError("reason must be a string")
            reason = reason.strip() or False
        else:
            reason = False

        metadata = {
            'request_id': payload['request_id'].strip(),
            'agent_name': payload['agent_name'].strip(),
            'model_name': model_name or False,
            'reason': reason,
        }

        # Build partner vals
        vals = {}
        if not is_update:
            name = payload.get('name')
            if not name or not isinstance(name, str) or not name.strip():
                raise ValueError("'name' là bắt buộc")
            vals['name'] = name.strip()
            # phone OR email bắt buộc khi create
            phone = payload.get('phone')
            email = payload.get('email')
            if (not phone or not str(phone).strip()) and (not email or not str(email).strip()):
                raise ValueError("Phải cung cấp ít nhất 'phone' hoặc 'email'")
        else:
            if 'name' in payload:
                name = payload.get('name')
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("'name' không được để trống")
                vals['name'] = name.strip()

        for field_name in ('phone', 'mobile', 'email', 'street', 'street2', 'city', 'comment', 'vat'):
            if field_name in payload:
                value = payload.get(field_name)
                if value in (None, False):
                    vals[field_name] = False
                elif not isinstance(value, str):
                    raise ValueError("%s must be a string" % field_name)
                else:
                    vals[field_name] = value.strip() or False

        if 'user_id' in payload:
            user_id = self._coerce_nullable_int(payload.get('user_id'), 'user_id')
            vals['user_id'] = user_id or False

        if not is_update and 'customer_fm_id' in payload:
            fm_id = payload.get('customer_fm_id')
            if fm_id not in (None, False):
                if not isinstance(fm_id, str) or not fm_id.strip():
                    raise ValueError("customer_fm_id must be a non-empty string")
                vals['customer_fm_id'] = fm_id.strip()

        return vals, metadata

    def _check_customer_log_replay(self, env, request_id, payload_fingerprint):
        """Idempotency check riêng cho customer log."""
        log_record = env[self.MCP_CUSTOMER_LOG_MODEL].sudo().search(
            [('request_id', '=', request_id)], limit=1
        )
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                'conflict',
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _build_customer_replayed_response(self, log_record):
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        if log_record.partner_id:
            data['partner_id'] = log_record.partner_id.id
        data['log_id'] = log_record.id
        data['idempotent_replay'] = True
        return data

    def _find_duplicate_customer(self, env, vals, exclude_partner_id=None):
        """Tìm partner trùng dựa trên phone hoặc customer_fm_id. Trả về partner record hoặc None."""
        # Ưu tiên customer_fm_id
        fm_id = vals.get('customer_fm_id')
        if fm_id:
            # Kiểm tra field tồn tại — res.partner có thể chưa có customer_fm_id
            partner_model = env['res.partner']
            if 'customer_fm_id' in partner_model._fields:
                domain = [('customer_fm_id', '=', fm_id)]
                if exclude_partner_id:
                    domain.append(('id', '!=', exclude_partner_id))
                existing = partner_model.sudo().search(domain, limit=1)
                if existing:
                    return existing
        # Theo phone normalized — match cross-format (+84 / 84 / 0, có/không khoảng trắng)
        phone = vals.get('phone')
        if phone:
            normalized = _normalize_phone(phone)
            if normalized and len(normalized) >= 9:
                last9 = normalized[-9:]
                # Dùng SQL với regexp_replace để strip mọi ký tự không-số trước khi
                # so sánh. Cách này match được +84 909 333 444 với 0909333444.
                exclude_clause = ''
                args = [last9, last9]
                if exclude_partner_id:
                    exclude_clause = ' AND id != %s'
                    args.append(exclude_partner_id)
                env.cr.execute(
                    "SELECT id FROM res_partner "
                    "WHERE ("
                    "  regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g') LIKE '%%' || %s "
                    "  OR regexp_replace(coalesce(mobile, ''), '[^0-9]', '', 'g') LIKE '%%' || %s "
                    ")" + exclude_clause + " LIMIT 50",
                    args,
                )
                candidate_ids = [row[0] for row in env.cr.fetchall()]
                if candidate_ids:
                    candidates = env['res.partner'].sudo().browse(candidate_ids)
                    for cand in candidates:
                        if (_normalize_phone(cand.phone) == normalized
                                or _normalize_phone(cand.mobile) == normalized):
                            return cand
        return None

    def _serialize_partner_snapshot(self, partner):
        return {
            'id': partner.id,
            'name': partner.name,
            'phone': partner.phone or None,
            'mobile': partner.mobile or None,
            'email': partner.email or None,
            'street': partner.street or None,
            'street2': partner.street2 or None,
            'city': partner.city or None,
            'comment': partner.comment or None,
            'vat': partner.vat or None,
            'user_id': partner.user_id.id if partner.user_id else None,
            'user_name': partner.user_id.name if partner.user_id else None,
            'customer_fm_id': getattr(partner, 'customer_fm_id', None) or None,
            'create_date': partner.create_date.isoformat() if partner.create_date else None,
            'write_date': partner.write_date.isoformat() if partner.write_date else None,
        }

    def _create_mcp_customer_log(self, env, action_type, normalized_payload, payload_fingerprint,
                                  partner=None, old_value=None, new_value=None, response_data=None,
                                  status='success', error_code=None, error_message=None):
        create_vals = {
            'partner_id': partner.id if partner else False,
            'action_type': action_type,
            'request_id': normalized_payload.get('request_id'),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'payload_fingerprint': payload_fingerprint,
            'old_value_json': self._dump_json_text(old_value or {}),
            'new_value_json': self._dump_json_text(new_value or {}),
            'response_snapshot_json': self._dump_json_text(response_data or {}),
            'agent_name': normalized_payload.get('agent_name') or '',
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'status': status,
            'error_code': error_code or False,
            'error_message': error_message or False,
        }
        return env[self.MCP_CUSTOMER_LOG_MODEL].sudo().create(create_vals)

    def _run_mcp_customer_create_action(self, payload=None, env=None):
        env = self._get_env(env)
        try:
            vals, metadata = self._normalize_mcp_customer_payload(payload, is_update=False)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        normalized = dict(metadata, partner_vals=vals)
        payload_fingerprint = self._compute_payload_fingerprint(normalized)

        existing_log = self._check_customer_log_replay(
            env=env,
            request_id=metadata['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_customer_replayed_response(existing_log)

        # Dedup check
        duplicate = self._find_duplicate_customer(env, vals)
        if duplicate:
            raise McpHttpError(
                409,
                'duplicate_customer',
                'Customer matching phone/customer_fm_id already exists',
                details={'existing_partner_id': duplicate.id, 'existing_name': duplicate.name},
            )

        try:
            # Chỉ cho phép field tồn tại
            partner_model = env['res.partner'].sudo()
            create_vals = {k: v for k, v in vals.items() if k in partner_model._fields}
            partner = partner_model.create(create_vals)
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        new_snapshot = self._serialize_partner_snapshot(partner)
        response_data = {
            'partner_id': partner.id,
            'action': 'customer_create',
            'partner': new_snapshot,
            'idempotent_replay': False,
        }
        log_record = self._create_mcp_customer_log(
            env=env,
            action_type='customer_create',
            normalized_payload=normalized,
            payload_fingerprint=payload_fingerprint,
            partner=partner,
            old_value={},
            new_value=new_snapshot,
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _run_mcp_customer_update_action(self, partner_id, payload=None, env=None):
        env = self._get_env(env)
        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            raise McpHttpError(404, 'not_found', 'Partner not found')

        try:
            vals, metadata = self._normalize_mcp_customer_payload(payload, is_update=True)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        if not vals:
            raise McpHttpError(400, 'validation_error', 'No updateable field provided')

        normalized = dict(metadata, partner_vals=vals, partner_id=partner.id)
        payload_fingerprint = self._compute_payload_fingerprint(normalized)

        existing_log = self._check_customer_log_replay(
            env=env,
            request_id=metadata['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_customer_replayed_response(existing_log)

        # Phone conflict check (nếu update phone, không được trùng khách khác)
        if 'phone' in vals and vals['phone']:
            dup = self._find_duplicate_customer(env, {'phone': vals['phone']}, exclude_partner_id=partner.id)
            if dup:
                raise McpHttpError(
                    409,
                    'duplicate_customer',
                    'Phone đã được dùng bởi customer khác',
                    details={'existing_partner_id': dup.id, 'existing_name': dup.name},
                )

        before_snapshot = self._serialize_partner_snapshot(partner)
        try:
            partner_model = env['res.partner'].sudo()
            write_vals = {k: v for k, v in vals.items() if k in partner_model._fields}
            partner.write(write_vals)
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        partner.invalidate_recordset()
        after_snapshot = self._serialize_partner_snapshot(partner)
        response_data = {
            'partner_id': partner.id,
            'action': 'customer_update',
            'partner': after_snapshot,
            'changed_fields': {k: v for k, v in vals.items()},
            'idempotent_replay': False,
        }
        log_record = self._create_mcp_customer_log(
            env=env,
            action_type='customer_update',
            normalized_payload=normalized,
            payload_fingerprint=payload_fingerprint,
            partner=partner,
            old_value=before_snapshot,
            new_value=after_snapshot,
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _dispatch_mcp_customer_create(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_customer_create_action(payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_update(self, partner_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_customer_update_action(partner_id=partner_id, payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    @http.route('/dac_erp/mcp/v1/customers',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customer_create(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_create,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customers/<int:partner_id>',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_customer_update(self, partner_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_update,
            partner_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    # ═════════════════════════════════════════════════════════════════
    # CONVERSATION ASSIGN
    # ═════════════════════════════════════════════════════════════════

    def _normalize_mcp_conv_assign_payload(self, payload):
        payload = self._get_v3_json_payload(payload=payload)
        unknown = sorted(set(payload) - self.MCP_CONV_ASSIGN_FIELDS)
        if unknown:
            raise ValueError("Trường không được phép: %s" % ', '.join(unknown))

        if 'request_id' not in payload or not isinstance(payload.get('request_id'), str) \
                or not payload.get('request_id').strip():
            raise ValueError("request_id is required")
        if 'agent_name' not in payload or not isinstance(payload.get('agent_name'), str) \
                or not payload.get('agent_name').strip():
            raise ValueError("agent_name is required")

        # Phải có ít nhất một trong owner_user_id hoặc participant_user_ids
        has_owner = 'owner_user_id' in payload
        has_participants = 'participant_user_ids' in payload
        if not has_owner and not has_participants:
            raise ValueError("Phải cung cấp 'owner_user_id' hoặc 'participant_user_ids'")

        model_name = payload.get('model_name')
        if model_name not in (None, False):
            if not isinstance(model_name, str):
                raise ValueError("model_name must be a string")
            model_name = model_name.strip() or False
        reason = payload.get('reason')
        if reason not in (None, False):
            if not isinstance(reason, str):
                raise ValueError("reason must be a string")
            reason = reason.strip() or False
        else:
            reason = False

        metadata = {
            'request_id': payload['request_id'].strip(),
            'agent_name': payload['agent_name'].strip(),
            'model_name': model_name or False,
            'reason': reason,
        }

        vals = {}
        if has_owner:
            owner_id = payload.get('owner_user_id')
            if owner_id in (None, False, 0):
                vals['owner_user_id'] = False
            else:
                vals['owner_user_id'] = self._coerce_nullable_int(owner_id, 'owner_user_id')

        if has_participants:
            participants = payload.get('participant_user_ids')
            if not isinstance(participants, list):
                raise ValueError("participant_user_ids must be a list of int")
            normalized_ids = []
            for idx, uid in enumerate(participants):
                normalized_ids.append(self._coerce_nullable_int(uid, 'participant_user_ids[%s]' % idx))
            vals['participant_user_ids'] = [uid for uid in normalized_ids if uid]

        return vals, metadata

    def _check_conv_assign_log_replay(self, env, request_id, payload_fingerprint):
        log_record = env[self.MCP_CONV_ASSIGN_LOG_MODEL].sudo().search(
            [('request_id', '=', request_id)], limit=1
        )
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                'conflict',
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _build_conv_assign_replayed_response(self, log_record):
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        # conversation_id already in stored JSON; skip Many2one access to avoid _unknown comodel error
        data['log_id'] = log_record.id
        data['idempotent_replay'] = True
        return data

    def _serialize_conv_assign_snapshot(self, conversation):
        owner = conversation.owner_id
        participants = conversation.participant_user_ids
        return {
            'conversation_id': conversation.id,
            'owner_user_id': owner.id if owner else None,
            'owner_user_name': owner.name if owner else None,
            'participant_user_ids': [
                {'id': u.id, 'name': u.name} for u in participants
            ],
        }

    def _run_mcp_conversation_assign_action(self, conversation_id, payload=None, env=None):
        env = self._get_env(env)
        conversation = env['page.fm.conversation'].sudo().browse(int(conversation_id))
        if not conversation.exists():
            raise McpHttpError(404, 'not_found', 'Conversation not found')

        try:
            vals, metadata = self._normalize_mcp_conv_assign_payload(payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        # Verify users exist
        if 'owner_user_id' in vals and vals['owner_user_id']:
            if not env['res.users'].sudo().browse(vals['owner_user_id']).exists():
                raise McpHttpError(400, 'validation_error',
                                   "owner_user_id=%s does not exist" % vals['owner_user_id'])
        if 'participant_user_ids' in vals and vals['participant_user_ids']:
            existing_ids = env['res.users'].sudo().browse(vals['participant_user_ids']).filtered(lambda r: r.exists()).ids
            missing = set(vals['participant_user_ids']) - set(existing_ids)
            if missing:
                raise McpHttpError(400, 'validation_error',
                                   "participant user_ids do not exist: %s" % sorted(missing))

        normalized = dict(metadata, conversation_id=conversation.id, vals=vals)
        payload_fingerprint = self._compute_payload_fingerprint(normalized)

        existing_log = self._check_conv_assign_log_replay(
            env=env,
            request_id=metadata['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_conv_assign_replayed_response(existing_log)

        before_snapshot = self._serialize_conv_assign_snapshot(conversation)

        write_vals = {}
        if 'owner_user_id' in vals:
            write_vals['owner_id'] = vals['owner_user_id'] or False
        if 'participant_user_ids' in vals:
            write_vals['participant_user_ids'] = [(6, 0, vals['participant_user_ids'])]

        try:
            conversation.sudo().write(write_vals)
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))

        conversation.invalidate_recordset()
        after_snapshot = self._serialize_conv_assign_snapshot(conversation)
        response_data = {
            'conversation_id': conversation.id,
            'action': 'conversation_assign',
            'changed_fields': vals,
            'conversation': after_snapshot,
            'idempotent_replay': False,
        }
        log_record = env[self.MCP_CONV_ASSIGN_LOG_MODEL].sudo().create({
            'conversation_id': conversation.id,
            'action_type': 'conversation_assign',
            'request_id': metadata['request_id'],
            'request_payload_json': self._dump_json_text(normalized),
            'payload_fingerprint': payload_fingerprint,
            'old_value_json': self._dump_json_text(before_snapshot),
            'new_value_json': self._dump_json_text(after_snapshot),
            'response_snapshot_json': self._dump_json_text(response_data),
            'agent_name': metadata['agent_name'],
            'model_name': metadata['model_name'] or False,
            'reason': metadata['reason'] or False,
            'status': 'success',
        })
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _dispatch_mcp_conversation_assign(self, conversation_id, env=None, headers=None, provided_key=None,
                                          payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_conversation_assign_action(
            conversation_id=conversation_id, payload=payload, env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/assign',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_conversation_assign(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_assign,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )
