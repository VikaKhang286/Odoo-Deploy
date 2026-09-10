# -*- coding: utf-8 -*-
"""
dac.design.assignment
─────────────────────
Model trung gian lưu đội thiết kế của một sale.order.

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 2.3 + 3.3.
Cấu trúc tương tự `dac.production.assignment` nhưng `user_id` thuộc nhóm
DAC Design và `role` có giá trị riêng (lead/reviewer/contributor).

Phase A (Foundation) chỉ tạo schema. Workflow approve/reject + revision
sẽ làm ở Phase B.
"""

from odoo import api, fields, models


class DacDesignAssignment(models.Model):
    _name = 'dac.design.assignment'
    _description = 'DAC Design Assignment'
    _order = 'joined_date desc, id desc'

    order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        required=True,
        index=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Designer',
        required=True,
        index=True,
        domain=lambda self: [('groups_id', 'in', [
            self.env.ref('dac_erp.group_dac_erp_design').id
        ])],
        help='Phải thuộc nhóm DAC Design.',
    )
    role = fields.Selection([
        ('lead', 'Trưởng nhóm thiết kế'),
        ('reviewer', 'Reviewer'),
        ('contributor', 'Cộng tác'),
    ], string='Vai trò', default='contributor', required=True)
    joined_date = fields.Datetime(
        string='Ngày tham gia',
        default=fields.Datetime.now,
        required=True,
    )
    left_date = fields.Datetime(string='Ngày rời')
    is_active = fields.Boolean(
        string='Đang làm',
        compute='_compute_is_active',
        store=True,
        index=True,
    )
    note = fields.Text(string='Ghi chú')

    _sql_constraints = [
        (
            'uniq_design_order_user_joined',
            'unique(order_id, user_id, joined_date)',
            'Một designer không thể có 2 assignment cùng thời điểm trên cùng đơn hàng.',
        ),
    ]

    @api.depends('left_date')
    def _compute_is_active(self):
        for rec in self:
            rec.is_active = not rec.left_date

    def name_get(self):
        result = []
        for rec in self:
            order_name = rec.order_id.name or ''
            user_name = rec.user_id.name or ''
            result.append((rec.id, f'{order_name} - {user_name} ({rec.role or ""})'))
        return result
