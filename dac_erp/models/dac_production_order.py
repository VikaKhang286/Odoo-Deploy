# -*- coding: utf-8 -*-
"""
dac.production.order
────────────────────
Lệnh thi công cấp dưới `sale.order`.

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 4.3:
- Quan hệ 1-1 với `sale.order` (ràng buộc qua SQL UNIQUE(order_id)).
- KHÔNG dùng module `mrp` core — chỉ dùng workflow nội bộ qua field state.
- Task phụ (bảo hành, sửa chữa) KHÔNG link vào lệnh thi công này; quản lý
  qua `dac.work.task` với `task_type in ('warranty', 'repair')`.

Phase A (Foundation) chỉ tạo schema, default value, computed field cơ bản.
Workflow state machine (draft → ready → in_progress → done) + cron detect
delay sẽ implement ở Phase B.
"""

from odoo import api, fields, models


class DacProductionOrder(models.Model):
    _name = 'dac.production.order'
    _description = 'DAC Production Order'
    _order = 'create_date desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Mã lệnh thi công',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: 'New',
        index=True,
    )
    order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        required=True,
        index=True,
        ondelete='cascade',
        tracking=True,
        help='Mỗi sale.order chỉ có ĐÚNG 1 dac.production.order (quan hệ 1-1).',
    )
    description = fields.Text(string='Mô tả công đoạn')
    lead_user_id = fields.Many2one(
        'res.users',
        string='Tổ trưởng',
        index=True,
        domain=lambda self: [('groups_id', 'in', [
            self.env.ref('dac_erp.group_dac_erp_production').id
        ])],
        tracking=True,
    )
    assignment_ids = fields.One2many(
        'dac.production.assignment',
        'production_order_id',
        string='Thành viên thi công',
    )
    target_start_date = fields.Date(string='Bắt đầu kế hoạch', tracking=True)
    target_end_date = fields.Date(string='Hoàn thành kế hoạch', tracking=True)
    actual_start_date = fields.Datetime(string='Bắt đầu thực tế', tracking=True)
    actual_end_date = fields.Datetime(string='Hoàn thành thực tế', tracking=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('ready', 'Sẵn sàng'),
        ('in_progress', 'Đang thi công'),
        ('paused', 'Tạm dừng'),
        ('done', 'Hoàn thành'),
        ('cancelled', 'Hủy'),
    ], string='Trạng thái', default='draft', required=True, tracking=True, index=True)
    progress_percent = fields.Float(
        string='Tiến độ (%)',
        default=0.0,
        help='Tính từ task con (loại trừ warranty/repair). Phase B sẽ tự compute.',
    )
    # NOTE Phase A.1: field One2many `task_ids` được thêm ở Phase A.2
    # cùng commit với việc bổ sung `production_order_id` (Many2one) vào
    # `dac.work.task`. Tách như vậy để commit A.1 upgrade clean độc lập.
    is_delayed = fields.Boolean(
        string='Trễ?',
        default=False,
        index=True,
        help='Tự bật khi target_end_date < today và state != done. '
             'Phase B sẽ implement cron + computed.',
    )
    delay_reason_ids = fields.One2many(
        'dac.production.delay.log',
        'production_order_id',
        string='Nhật ký trễ',
    )

    _sql_constraints = [
        (
            'uniq_production_order_id',
            'unique(order_id)',
            'Mỗi đơn hàng chỉ có ĐÚNG 1 lệnh thi công duy nhất.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'New':
                seq = self.env['ir.sequence'].next_by_code('dac.production.order')
                if not seq:
                    # Fallback nếu sequence chưa được seed (Phase A chưa thêm seed)
                    order = self.env['sale.order'].browse(vals.get('order_id'))
                    base = (order.name or 'SO') if order else 'SO'
                    seq = f'{base}-PROD'
                vals['name'] = seq
        return super().create(vals_list)
