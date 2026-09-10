# -*- coding: utf-8 -*-
"""Hooks vào sale.order để fire outbound webhook events.

Events:
- order.created: ngay sau create()
- order.stage_changed: khi order_state_custom thay đổi
- order.cancelled: khi vào state='cancel' (subset của stage_changed nhưng tách riêng cho rõ)
- order.reopened: khi từ cancel → quotation
- order.payment_confirmed: khi all_invoices_paid hoặc is_order_completed = True
"""
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


# Fields on sale.order that affect task snapshot — phải sync với _SNAPSHOT_CONTEXT_FIELDS trong dac_work_task.py
_SNAPSHOT_CONTEXT_FIELDS = frozenset({
    'order_title', 'order_summary', 'design_deadline', 'production_deadline',
    'design_link', 'delivery_address', 'installation_address',
    'is_priority', 'is_priority_today', 'fulfillment_method',
})

# Stages where design work is expected
_DESIGN_ACTIVE_STAGES = frozenset({
    'deposit', 'production', 'delivery', 'installation', 'payment',
})


def _build_order_payload(order):
    """Build snapshot dùng cho event payload."""
    return {
        'order_id': order.id,
        'name': order.name,
        'order_number': order.order_number or None,
        'order_state_custom': order.order_state_custom,
        'state': order.state,
        'partner_id': order.partner_id.id if order.partner_id else None,
        'partner_name': order.partner_id.name if order.partner_id else None,
        'partner_phone': order.partner_id.phone if order.partner_id else None,
        'user_id': order.user_id.id if order.user_id else None,
        'user_name': order.user_id.name if order.user_id else None,
        'amount_total': order.amount_total,
        'fulfillment_method': order.fulfillment_method or None,
        'has_deposit': order.has_deposit,
        'deposit_amount': order.deposit_amount,
    }


def _build_design_payload(order):
    """Payload an toàn cho design/production events — KHÔNG chứa monetary fields."""
    return {
        'order_id': order.id,
        'order_name': order.name,
        'order_number': getattr(order, 'order_number', None) or order.name,
        'order_state_custom': order.order_state_custom,
        'order_title': order.order_title or '',
        'order_summary': getattr(order, 'order_summary', '') or '',
        'design_link': getattr(order, 'design_link', None) or '',
        'design_deadline': str(order.design_deadline) if order.design_deadline else None,
        'production_deadline': str(order.production_deadline) if order.production_deadline else None,
        'delivery_address': getattr(order, 'delivery_address', '') or '',
        'installation_address': getattr(order, 'installation_address', '') or '',
        'is_priority': bool(getattr(order, 'is_priority', False)),
        'is_priority_today': bool(getattr(order, 'is_priority_today', False)),
        'fulfillment_method': getattr(order, 'fulfillment_method', '') or '',
        'user_id_design': order.user_id_design.id if order.user_id_design else None,
        'user_id_design_name': order.user_id_design.name if order.user_id_design else None,
        'user_id_production': order.user_id_production.id if order.user_id_production else None,
        'user_id_production_name': order.user_id_production.name if order.user_id_production else None,
        'design_done': bool(getattr(order, 'design_done', False)),
        'production_done': bool(getattr(order, 'production_done', False)),
        'partner_name': order.partner_id.name if order.partner_id else None,
    }


class SaleOrderOpenclawHook(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Fire event order.created cho mỗi record
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        for order in records:
            try:
                webhook_model.sudo().enqueue_event(
                    event_type='order.created',
                    data=_build_order_payload(order),
                    sale_order_id=order.id,
                )
            except Exception as exc:
                # Không raise — sinh event không được phép phá nghiệp vụ create order
                _logger.warning("Failed to enqueue order.created webhook for order %s: %s",
                                order.id, exc)
        return records

    def write(self, vals):
        # Snapshot trước khi write
        before_stages = {rec.id: rec.order_state_custom for rec in self}
        before_designer = {rec.id: rec.user_id_design.id for rec in self}
        before_production = {rec.id: rec.user_id_production.id for rec in self}
        before_design_done = {rec.id: getattr(rec, 'design_done', False) for rec in self}

        # Snapshot old values cho CONTEXT_FIELDS nếu bất kỳ field nào trong đó thay đổi
        tracking_context = any(f in vals for f in _SNAPSHOT_CONTEXT_FIELDS)
        before_context = {}
        if tracking_context:
            for rec in self:
                before_context[rec.id] = {
                    f: getattr(rec, f, None) for f in _SNAPSHOT_CONTEXT_FIELDS if f in vals
                }

        result = super().write(vals)
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']

        # ── Design/Production assignment events ─────────────────────────
        if 'user_id_design' in vals or 'order_state_custom' in vals:
            for order in self:
                # order.design_assigned: user_id_design None → value
                if 'user_id_design' in vals:
                    old_uid = before_designer.get(order.id)
                    new_uid = order.user_id_design.id if order.user_id_design else None
                    if old_uid != new_uid and new_uid:
                        try:
                            data = _build_design_payload(order)
                            webhook_model.sudo().enqueue_event(
                                event_type='order.design_assigned',
                                data=data,
                                sale_order_id=order.id,
                            )
                        except Exception as exc:
                            _logger.warning("Failed to enqueue order.design_assigned for %s: %s",
                                            order.id, exc)

                # order.ready_for_design: stage → design-active AND still no designer
                if 'order_state_custom' in vals:
                    old_stage = before_stages.get(order.id)
                    new_stage = order.order_state_custom
                    if (old_stage != new_stage
                            and new_stage in _DESIGN_ACTIVE_STAGES
                            and not order.user_id_design):
                        try:
                            webhook_model.sudo().enqueue_event(
                                event_type='order.ready_for_design',
                                data=_build_design_payload(order),
                                sale_order_id=order.id,
                            )
                        except Exception as exc:
                            _logger.warning("Failed to enqueue order.ready_for_design for %s: %s",
                                            order.id, exc)

        if 'user_id_production' in vals or 'design_done' in vals:
            for order in self:
                # order.production_assigned: user_id_production None → value
                if 'user_id_production' in vals:
                    old_uid = before_production.get(order.id)
                    new_uid = order.user_id_production.id if order.user_id_production else None
                    if old_uid != new_uid and new_uid:
                        try:
                            webhook_model.sudo().enqueue_event(
                                event_type='order.production_assigned',
                                data=_build_design_payload(order),
                                sale_order_id=order.id,
                            )
                        except Exception as exc:
                            _logger.warning("Failed to enqueue order.production_assigned for %s: %s",
                                            order.id, exc)

                # order.ready_for_production: design_done → True AND no production user yet
                if 'design_done' in vals:
                    old_done = before_design_done.get(order.id)
                    if (not old_done and getattr(order, 'design_done', False)
                            and not order.user_id_production):
                        try:
                            webhook_model.sudo().enqueue_event(
                                event_type='order.ready_for_production',
                                data=_build_design_payload(order),
                                sale_order_id=order.id,
                            )
                        except Exception as exc:
                            _logger.warning("Failed to enqueue order.ready_for_production for %s: %s",
                                            order.id, exc)

        # ── task.context_updated: refresh snapshot + notify ─────────────
        if tracking_context:
            for order in self:
                old_vals = before_context.get(order.id, {})
                changed = {
                    f: {'old': str(old_vals.get(f)) if old_vals.get(f) is not None else None,
                        'new': str(getattr(order, f, None)) if getattr(order, f, None) is not None else None}
                    for f in old_vals
                    if old_vals.get(f) != getattr(order, f, None)
                }
                if not changed:
                    continue
                try:
                    # Tìm active tasks và refresh snapshot
                    active_tasks = self.env['dac.work.task'].sudo().search([
                        ('order_id', '=', order.id),
                        ('state', 'not in', ('done', 'cancelled')),
                    ])
                    if active_tasks:
                        active_tasks._refresh_snapshot()
                        affected = [
                            {
                                'task_id': t.id,
                                'task_type': t.task_type,
                                'assignee_id': t.assigned_user_id.id if t.assigned_user_id else None,
                                'assignee_name': t.assigned_user_id.name if t.assigned_user_id else None,
                            }
                            for t in active_tasks
                        ]
                        ctx_data = {
                            'order_id': order.id,
                            'order_name': order.name,
                            'changed_fields': list(changed.keys()),
                            'changes': changed,
                            'affected_tasks': affected,
                        }
                        webhook_model.sudo().enqueue_event(
                            event_type='task.context_updated',
                            data=ctx_data,
                            sale_order_id=order.id,
                        )
                except Exception as exc:
                    _logger.warning("Failed to process task.context_updated for order %s: %s",
                                    order.id, exc)

        # ── Stage changed events ─────────────────────────────────────────
        if 'order_state_custom' in vals:
            for order in self:
                old_stage = before_stages.get(order.id)
                new_stage = order.order_state_custom
                if old_stage == new_stage:
                    continue
                try:
                    data = _build_order_payload(order)
                    data['old_stage'] = old_stage
                    data['new_stage'] = new_stage
                    webhook_model.sudo().enqueue_event(
                        event_type='order.stage_changed',
                        data=data,
                        sale_order_id=order.id,
                    )
                    # Sub-events cho cancel/reopen
                    if new_stage == 'cancel':
                        webhook_model.sudo().enqueue_event(
                            event_type='order.cancelled',
                            data=data,
                            sale_order_id=order.id,
                        )
                    elif old_stage == 'cancel' and new_stage == 'quotation':
                        webhook_model.sudo().enqueue_event(
                            event_type='order.reopened',
                            data=data,
                            sale_order_id=order.id,
                        )
                except Exception as exc:
                    _logger.warning("Failed to enqueue order.stage_changed for %s: %s",
                                    order.id, exc)

        # Payment confirmed → kiểm tra all_invoices_paid hoặc is_order_completed
        # (chỉ fire khi vừa chuyển sang True)
        if 'all_invoices_paid' in vals or 'is_order_completed' in vals:
            for order in self:
                try:
                    if order.is_order_completed or order.all_invoices_paid:
                        webhook_model.sudo().enqueue_event(
                            event_type='order.payment_confirmed',
                            data=_build_order_payload(order),
                            sale_order_id=order.id,
                        )
                except Exception as exc:
                    _logger.warning("Failed to enqueue order.payment_confirmed for %s: %s",
                                    order.id, exc)

        return result
