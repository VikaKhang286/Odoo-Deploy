# -*- coding: utf-8 -*-
"""Data Quality Report cho dac_openclaw.

Cron `cron_data_quality_scan` chạy hàng ngày, quét các vấn đề:
- Task mồ côi (không có order/conversation/customer)
- Task draft quá 24h chưa có assigned_user_id
- Conversation status='new' quá 30 phút không có owner
- Order quotation quá 7 ngày không cập nhật
- Conversation không có partner_id (mặc dù có customer_fm_id)

Mỗi issue tạo 1 record `dac_openclaw.data.quality.issue` với severity + recommended_action.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class DacOpenclawDataQualityIssue(models.Model):
    _name = 'dac_openclaw.data.quality.issue'
    _description = 'DAC OpenClaw Data Quality Issue'
    _order = 'id desc'

    issue_type = fields.Selection(
        [
            ('task_orphan', 'Task không có entity link'),
            ('task_unassigned_too_long', 'Task draft chưa assign quá 24h'),
            ('conversation_no_owner', 'Conversation mới chưa có owner > 30 phút'),
            ('conversation_no_partner', 'Conversation thiếu partner_id'),
            ('order_stale_quotation', 'Order quotation > 7 ngày chưa update'),
        ],
        required=True,
        index=True,
    )
    severity = fields.Selection(
        [('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
        required=True,
        default='medium',
        index=True,
    )
    detected_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True, readonly=True)
    resolved = fields.Boolean(default=False, index=True)
    resolved_at = fields.Datetime()

    # FK references — set 1 trong 3 tuỳ issue_type
    task_id = fields.Many2one('dac.work.task', index=True, ondelete='cascade')
    conversation_id = fields.Many2one('page.fm.conversation', index=True, ondelete='cascade')
    order_id = fields.Many2one('sale.order', index=True, ondelete='cascade')

    description = fields.Text()
    recommended_action = fields.Text()

    def action_mark_resolved(self):
        for rec in self:
            rec.write({'resolved': True, 'resolved_at': fields.Datetime.now()})

    @api.model
    def _create_issue_if_not_exists(self, issue_type, severity, **kwargs):
        """Tạo issue mới nếu chưa có issue active cùng type cho cùng entity."""
        domain = [
            ('issue_type', '=', issue_type),
            ('resolved', '=', False),
        ]
        for key in ('task_id', 'conversation_id', 'order_id'):
            if key in kwargs and kwargs[key]:
                domain.append((key, '=', kwargs[key]))
                break
        existing = self.sudo().search(domain, limit=1)
        if existing:
            return existing
        vals = {
            'issue_type': issue_type,
            'severity': severity,
        }
        vals.update(kwargs)
        return self.sudo().create(vals)

    @api.model
    def cron_data_quality_scan(self, _now=None, _age_30m=30, _age_24h=24, _age_7d=7):
        """Cron chạy hàng ngày 06:00, quét tất cả data quality issues.

        Test hooks: _now, _age_30m (phút), _age_24h (giờ), _age_7d (ngày) — pass
        nhỏ để bypass ngưỡng thời gian khi cần.
        """
        now = _now or fields.Datetime.now()
        threshold_30m = now - timedelta(minutes=_age_30m)
        threshold_24h = now - timedelta(hours=_age_24h)
        threshold_7d = now - timedelta(days=_age_7d)

        # 1. Task mồ côi (không có order_id, conversation_id, hoặc cả 2)
        try:
            tasks = self.env['dac.work.task'].sudo().search([
                ('order_id', '=', False),
                ('conversation_id', '=', False),
                ('state', 'in', ('draft', 'in_progress')),
            ])
            for task in tasks:
                self._create_issue_if_not_exists(
                    issue_type='task_orphan',
                    severity='medium',
                    task_id=task.id,
                    description=f"Task '{task.name}' (id={task.id}) không liên kết với order/conversation",
                    recommended_action="Gắn task với order_id hoặc conversation_id, hoặc xoá",
                )
        except Exception as exc:
            _logger.exception("data_quality task_orphan scan failed: %s", exc)

        # 2. Task draft > 24h chưa assign
        try:
            tasks = self.env['dac.work.task'].sudo().search([
                ('state', '=', 'draft'),
                ('assigned_user_id', '=', False),
                ('create_date', '<', threshold_24h),
            ])
            for task in tasks:
                self._create_issue_if_not_exists(
                    issue_type='task_unassigned_too_long',
                    severity='high',
                    task_id=task.id,
                    description=f"Task '{task.name}' draft > 24h, chưa có người phụ trách",
                    recommended_action="Assign manager hoặc nhân viên ngay",
                )
        except Exception as exc:
            _logger.exception("data_quality task_unassigned scan failed: %s", exc)

        # 3. Conversation status='new' > 30 phút, chưa có owner
        if 'page.fm.conversation' in self.env.registry.models:
            try:
                convs = self.env['page.fm.conversation'].sudo().search([
                    ('status_state', '=', 'new'),
                    ('owner_id', '=', False),
                    ('create_date', '<', threshold_30m),
                ])
                for conv in convs:
                    self._create_issue_if_not_exists(
                        issue_type='conversation_no_owner',
                        severity='high',
                        conversation_id=conv.id,
                        description=f"Conversation {conv.id} (status=new) > 30 phút chưa có owner",
                        recommended_action="Assign owner qua MCP /conversations/<id>/assign",
                    )
            except Exception as exc:
                _logger.exception("data_quality conversation_no_owner scan failed: %s", exc)

            # 4. Conversation thiếu partner_id
            try:
                convs = self.env['page.fm.conversation'].sudo().search([
                    ('partner_id', '=', False),
                    ('customer_fm_id', '!=', False),
                ], limit=200)
                for conv in convs:
                    self._create_issue_if_not_exists(
                        issue_type='conversation_no_partner',
                        severity='low',
                        conversation_id=conv.id,
                        description=f"Conversation {conv.id} có customer_fm_id nhưng chưa link partner",
                        recommended_action="Tạo partner hoặc resolve customer qua MCP",
                    )
            except Exception as exc:
                _logger.exception("data_quality conversation_no_partner scan failed: %s", exc)

        # 5. Order quotation > 7 ngày chưa cập nhật
        try:
            orders = self.env['sale.order'].sudo().search([
                ('order_state_custom', '=', 'quotation'),
                ('write_date', '<', threshold_7d),
            ])
            for order in orders:
                self._create_issue_if_not_exists(
                    issue_type='order_stale_quotation',
                    severity='medium',
                    order_id=order.id,
                    description=f"Order {order.name} ở quotation > 7 ngày",
                    recommended_action="Liên hệ khách hoặc cancel nếu không có response",
                )
        except Exception as exc:
            _logger.exception("data_quality order_stale_quotation scan failed: %s", exc)

        # Auto-resolve issues đã hết điều kiện
        try:
            self._auto_resolve_obsolete_issues()
        except Exception as exc:
            _logger.exception("data_quality auto-resolve failed: %s", exc)

    @api.model
    def _auto_resolve_obsolete_issues(self):
        """Đóng tự động issue nào không còn áp dụng."""
        # task_orphan: nếu task đã có order_id hoặc conversation_id
        orphan_issues = self.sudo().search([
            ('issue_type', '=', 'task_orphan'),
            ('resolved', '=', False),
            ('task_id', '!=', False),
        ])
        for issue in orphan_issues:
            if issue.task_id.order_id or issue.task_id.conversation_id:
                issue.action_mark_resolved()
        # task_unassigned_too_long: nếu đã có assigned_user_id
        unassigned_issues = self.sudo().search([
            ('issue_type', '=', 'task_unassigned_too_long'),
            ('resolved', '=', False),
            ('task_id', '!=', False),
        ])
        for issue in unassigned_issues:
            if issue.task_id.assigned_user_id:
                issue.action_mark_resolved()
        # conversation_no_owner: nếu đã có owner_id
        if 'page.fm.conversation' in self.env.registry.models:
            no_owner_issues = self.sudo().search([
                ('issue_type', '=', 'conversation_no_owner'),
                ('resolved', '=', False),
                ('conversation_id', '!=', False),
            ])
            for issue in no_owner_issues:
                if issue.conversation_id.owner_id:
                    issue.action_mark_resolved()
            no_partner_issues = self.sudo().search([
                ('issue_type', '=', 'conversation_no_partner'),
                ('resolved', '=', False),
                ('conversation_id', '!=', False),
            ])
            for issue in no_partner_issues:
                if issue.conversation_id.partner_id:
                    issue.action_mark_resolved()
        # order_stale_quotation: nếu order không còn quotation
        stale_issues = self.sudo().search([
            ('issue_type', '=', 'order_stale_quotation'),
            ('resolved', '=', False),
            ('order_id', '!=', False),
        ])
        for issue in stale_issues:
            if issue.order_id.order_state_custom != 'quotation':
                issue.action_mark_resolved()
