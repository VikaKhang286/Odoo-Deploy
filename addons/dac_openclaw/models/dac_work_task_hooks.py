# -*- coding: utf-8 -*-
"""Hooks vào dac.work.task để fire outbound webhook events.

Events:
- task.created: khi create()
- task.assigned: khi assigned_user_id thay đổi
- task.completed: khi state chuyển sang 'done'
"""
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


def _build_task_payload(task):
    """Payload an toàn — bao gồm snap_* fields, KHÔNG chứa monetary từ order."""
    return {
        'task_id': task.id,
        'name': task.name,
        'state': task.state,
        'priority': task.priority,
        'task_type': task.task_type,
        'deadline': task.deadline.isoformat() if task.deadline else None,
        'remind_at': task.remind_at.isoformat() if task.remind_at else None,
        'assigned_user_id': task.assigned_user_id.id if task.assigned_user_id else None,
        'assigned_user_name': task.assigned_user_id.name if task.assigned_user_id else None,
        'order_id': task.order_id.id if task.order_id else None,
        'order_name': task.order_id.name if task.order_id else None,
        'conversation_id': task.conversation_id.id if task.conversation_id else None,
        'is_personal_reminder': bool(task.is_personal_reminder),
        'created_by_agent': task.created_by_agent or None,
        'is_blocked': bool(task.is_blocked),
        'blocker_reason': task.blocker_reason or None,
        # Snapshot fields (safe — no monetary data)
        'snap_order_title': task.snap_order_title or None,
        'snap_order_summary': task.snap_order_summary or None,
        'snap_order_number': task.snap_order_number or None,
        'snap_design_deadline': str(task.snap_design_deadline) if task.snap_design_deadline else None,
        'snap_design_link': task.snap_design_link or None,
        'snap_production_deadline': str(task.snap_production_deadline) if task.snap_production_deadline else None,
        'snap_delivery_address': task.snap_delivery_address or None,
        'snap_is_priority': bool(task.snap_is_priority),
        'snap_fulfillment_method': task.snap_fulfillment_method or None,
        'days_left_display': task.days_left_display or None,
    }


class DacWorkTaskOpenclawHook(models.Model):
    _inherit = 'dac.work.task'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        for task in records:
            try:
                payload = _build_task_payload(task)
                webhook_model.sudo().enqueue_event(
                    event_type='task.created',
                    data=payload,
                    task_id=task.id,
                )
                # Type-specific events
                if task.task_type == 'design':
                    webhook_model.sudo().enqueue_event(
                        event_type='design.task.created',
                        data=payload,
                        task_id=task.id,
                    )
                elif task.task_type == 'production':
                    webhook_model.sudo().enqueue_event(
                        event_type='production.task.created',
                        data=payload,
                        task_id=task.id,
                    )
                if task.assigned_user_id:
                    webhook_model.sudo().enqueue_event(
                        event_type='task.assigned',
                        data=payload,
                        task_id=task.id,
                    )
            except Exception as exc:
                _logger.warning("Failed to enqueue task.created for %s: %s", task.id, exc)
        return records

    def write(self, vals):
        before_assigned = {rec.id: rec.assigned_user_id.id for rec in self}
        before_state = {rec.id: rec.state for rec in self}
        before_blocked = {rec.id: rec.is_blocked for rec in self}
        result = super().write(vals)
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']

        if 'assigned_user_id' in vals:
            for task in self:
                old = before_assigned.get(task.id)
                new = task.assigned_user_id.id if task.assigned_user_id else None
                if old == new:
                    continue
                try:
                    data = _build_task_payload(task)
                    data['old_assigned_user_id'] = old
                    data['new_assigned_user_id'] = new
                    webhook_model.sudo().enqueue_event(
                        event_type='task.assigned',
                        data=data,
                        task_id=task.id,
                    )
                except Exception as exc:
                    _logger.warning("Failed to enqueue task.assigned for %s: %s",
                                    task.id, exc)

        if 'state' in vals:
            for task in self:
                old = before_state.get(task.id)
                if old != 'done' and task.state == 'done':
                    try:
                        payload = _build_task_payload(task)
                        webhook_model.sudo().enqueue_event(
                            event_type='task.completed',
                            data=payload,
                            task_id=task.id,
                        )
                        # Type-specific done events
                        if task.task_type == 'design':
                            webhook_model.sudo().enqueue_event(
                                event_type='design.task.done',
                                data=payload,
                                task_id=task.id,
                            )
                        elif task.task_type == 'production':
                            webhook_model.sudo().enqueue_event(
                                event_type='production.task.done',
                                data=payload,
                                task_id=task.id,
                            )
                    except Exception as exc:
                        _logger.warning("Failed to enqueue task.completed for %s: %s",
                                        task.id, exc)

        # task.blocked: is_blocked False → True
        if 'is_blocked' in vals and vals.get('is_blocked'):
            for task in self:
                if not before_blocked.get(task.id) and task.is_blocked:
                    try:
                        data = _build_task_payload(task)
                        data['blocker_reported_at'] = (
                            task.blocker_reported_at.isoformat()
                            if task.blocker_reported_at else None
                        )
                        data['blocker_reported_by'] = (
                            task.blocker_reported_by.id if task.blocker_reported_by else None
                        )
                        data['blocker_reported_by_name'] = (
                            task.blocker_reported_by.name if task.blocker_reported_by else None
                        )
                        webhook_model.sudo().enqueue_event(
                            event_type='task.blocked',
                            data=data,
                            task_id=task.id,
                        )
                    except Exception as exc:
                        _logger.warning("Failed to enqueue task.blocked for %s: %s",
                                        task.id, exc)

        return result
