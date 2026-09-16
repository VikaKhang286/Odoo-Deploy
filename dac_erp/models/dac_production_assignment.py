# -*- coding: utf-8 -*-
"""
dac.production.assignment
─────────────────────────
Model trung gian lưu lịch sử thành viên thi công của một sale.order
hoặc một dac.production.order.

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 2.3 + 4.3:
- Mỗi sale.order có nhiều assignment (One2many).
- Mỗi assignment có thể gắn thêm `production_order_id` (cấp lệnh thi công)
  hoặc bỏ trống (cấp đơn hàng — toàn bộ).

Phase A (Foundation) chỉ tạo schema. Workflow state transition + cron đóng
inactive assignment sẽ làm ở Phase B/C.
"""

from odoo import api, fields, models


class DacProductionAssignment(models.Model):
    _name = 'dac.production.assignment'
    _description = 'DAC Production Assignment'
    _order = 'joined_date desc, id desc'

    order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        required=True,
        index=True,
        ondelete='cascade',
        help='Đơn hàng cha mà assignment này thuộc về.',
    )
    production_order_id = fields.Many2one(
        'dac.production.order',
        string='Lệnh thi công',
        index=True,
        ondelete='cascade',
        help='Tùy chọn — chỉ set khi assignment ở cấp lệnh thi công. '
             'Bỏ trống nếu assignment ở cấp đơn hàng (toàn bộ).',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Người thi công',
        required=True,
        index=True,
        domain=lambda self: [('groups_id', 'in', [
            self.env.ref('dac_erp.group_dac_erp_production').id
        ])],
        help='Phải thuộc nhóm DAC Production.',
    )
    role = fields.Selection([
        ('lead', 'Tổ trưởng'),
        ('member', 'Thành viên'),
        ('helper', 'Phụ việc'),
    ], string='Vai trò', default='member', required=True)
    joined_date = fields.Datetime(
        string='Ngày gia nhập',
        default=fields.Datetime.now,
        required=True,
    )
    left_date = fields.Datetime(
        string='Ngày rời',
        help='Khi đơn hoàn thành/hủy hoặc tổ trưởng tách thành viên.',
    )
    is_active = fields.Boolean(
        string='Đang làm',
        compute='_compute_is_active',
        store=True,
        index=True,
    )
    note = fields.Text(string='Ghi chú giao việc')

    _sql_constraints = [
        (
            'uniq_order_user_joined',
            'unique(order_id, user_id, joined_date)',
            'Một thành viên không thể có 2 assignment cùng thời điểm trên cùng đơn hàng.',
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
