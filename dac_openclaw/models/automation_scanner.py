# -*- coding: utf-8 -*-
"""Automation scanner crons cho dac_openclaw.

Cron methods:
- cron_scan_unassigned_conversations (mỗi 15 phút)
- cron_scan_overdue_tasks (mỗi 30 phút)
- cron_scan_hot_cases (mỗi 10 phút) — chỉ enqueue event nếu chưa enqueue trong N giờ

Mỗi method fire outbound webhook events đến OpenClaw để alert.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


COOLDOWN_HOURS = 4  # không fire lại event cùng entity trong 4h


class DacOpenclawAutomationScanner(models.AbstractModel):
    """Abstract model — chỉ chứa method cron, không lưu data."""
    _name = 'dac_openclaw.automation.scanner'
    _description = 'DAC OpenClaw Automation Scanner'

    @api.model
    def _has_recent_event(self, event_type, _now=None, **filters):
        """Kiểm tra có event cùng type cho cùng entity trong COOLDOWN_HOURS gần đây không."""
        now = _now or fields.Datetime.now()
        threshold = now - timedelta(hours=COOLDOWN_HOURS)
        domain = [
            ('event_type', '=', event_type),
            ('occurred_at', '>=', threshold),
        ]
        for k, v in filters.items():
            domain.append((k, '=', v))
        return bool(self.env['dac_openclaw.outbound.webhook.log'].sudo().search(domain, limit=1))

    @api.model
    def cron_scan_unassigned_conversations(self, _now=None, _age_minutes=30):
        """Scan conversations status='new' không có owner > _age_minutes phút, fire event.

        _now và _age_minutes là test hooks — tests pass explicit value để bypass
        complexity của SQL UPDATE create_date.
        """
        if 'page.fm.conversation' not in self.env.registry.models:
            return
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        now = _now or fields.Datetime.now()
        threshold = now - timedelta(minutes=_age_minutes)
        try:
            convs = self.env['page.fm.conversation'].sudo().search([
                ('status_state', '=', 'new'),
                ('owner_id', '=', False),
                ('create_date', '<', threshold),
            ], limit=200)
        except Exception as exc:
            _logger.exception("scan_unassigned_conversations search failed: %s", exc)
            return
        for conv in convs:
            try:
                if self._has_recent_event('conversation.unassigned',
                                           _now=now,
                                           conversation_id=conv.id):
                    continue
                age_minutes = int((now - conv.create_date).total_seconds() / 60)
                webhook_model.sudo().enqueue_event(
                    event_type='conversation.unassigned',
                    data={
                        'conversation_id': conv.id,
                        'conversation_fm_id': conv.conversation_fm_id or None,
                        'platform': conv.platform_fm or None,
                        'customer_name': conv.customer_name_fm or None,
                        'last_message_snippet': (conv.last_message_snippet or '')[:200],
                        'age_minutes': age_minutes,
                    },
                    conversation_id=conv.id,
                )
            except Exception as exc:
                _logger.warning("scan_unassigned conv %s failed: %s", conv.id, exc)

    @api.model
    def cron_scan_overdue_tasks(self):
        """Scan task có deadline < now, state in (draft, in_progress), fire event."""
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        now = fields.Datetime.now()
        try:
            tasks = self.env['dac.work.task'].sudo().search([
                ('deadline', '!=', False),
                ('deadline', '<', now),
                ('state', 'in', ('draft', 'in_progress')),
            ], limit=200)
        except Exception as exc:
            _logger.exception("scan_overdue_tasks search failed: %s", exc)
            return
        for task in tasks:
            try:
                if self._has_recent_event('task.overdue', task_id=task.id):
                    continue
                hours_overdue = int((now - task.deadline).total_seconds() / 3600)
                webhook_model.sudo().enqueue_event(
                    event_type='task.overdue',
                    data={
                        'task_id': task.id,
                        'name': task.name,
                        'priority': task.priority,
                        'state': task.state,
                        'deadline': task.deadline.isoformat(),
                        'hours_overdue': hours_overdue,
                        'assigned_user_id': task.assigned_user_id.id if task.assigned_user_id else None,
                        'assigned_user_name': task.assigned_user_id.name if task.assigned_user_id else None,
                    },
                    task_id=task.id,
                )
            except Exception as exc:
                _logger.warning("scan_overdue task %s failed: %s", task.id, exc)

    @api.model
    def cron_scan_duplicate_orders(self):
        """Phát hiện đơn trùng (cùng partner_id + cùng tổng tiền trong 24h).

        Output: tạo data_quality_issue type custom nếu tìm thấy candidates.
        """
        from datetime import datetime
        now = fields.Datetime.now()
        threshold = now - timedelta(hours=24)
        try:
            self.env.cr.execute("""
                SELECT array_agg(id ORDER BY id) AS dup_ids, partner_id, amount_total
                FROM sale_order
                WHERE partner_id IS NOT NULL
                  AND amount_total > 0
                  AND create_date >= %s
                  AND order_state_custom NOT IN ('cancel', 'completed')
                GROUP BY partner_id, amount_total
                HAVING count(*) >= 2
                LIMIT 50
            """, [threshold])
            rows = self.env.cr.fetchall()
        except Exception as exc:
            _logger.exception("scan_duplicate_orders SQL failed: %s", exc)
            return
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        for dup_ids, partner_id, amount_total in rows:
            try:
                # Fire event riêng cho từng cặp trùng
                webhook_model.sudo().enqueue_event(
                    event_type='order.created',  # reuse event type, OpenClaw có thể detect via data flag
                    data={
                        'duplicate_warning': True,
                        'partner_id': partner_id,
                        'amount_total': amount_total,
                        'duplicate_order_ids': list(dup_ids),
                        'created_within_hours': 24,
                    },
                )
            except Exception as exc:
                _logger.warning("scan_duplicate enqueue failed: %s", exc)
