# -*- coding: utf-8 -*-
"""
dac.design.revision
───────────────────
Lịch sử bản thiết kế của một sale.order.

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 3.3:
- Mỗi sale.order có nhiều revision (One2many).
- Mỗi revision có state machine: draft → submitted → approved/rejected/archived.
- `parent_revision_id` tham chiếu bản trước (nếu là revision sau khi rework).

Phase A (Foundation) chỉ tạo schema. Workflow submit/approve/reject sẽ làm
ở Phase B; UI tab thiết kế làm ở Phase E.
"""

from odoo import api, fields, models


class DacDesignRevision(models.Model):
    _name = 'dac.design.revision'
    _description = 'DAC Design Revision'
    _order = 'order_id, revision_number desc, id desc'
    _inherit = ['mail.thread']

    order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        required=True,
        index=True,
        ondelete='cascade',
    )
    revision_number = fields.Integer(
        string='Số bản',
        compute='_compute_revision_number',
        store=True,
        help='Tự tăng trong phạm vi 1 đơn hàng.',
    )
    name = fields.Char(
        string='Tên bản',
        required=True,
        default=lambda self: 'v1.0',
        help='VD: v1.0, v1.1, v2.0',
    )
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('submitted', 'Đã gửi duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Bị từ chối'),
        ('archived', 'Lưu kho'),
    ], string='Trạng thái', default='draft', required=True, tracking=True, index=True)
    submitted_by_user_id = fields.Many2one(
        'res.users',
        string='Người gửi duyệt',
        domain=lambda self: [('groups_id', 'in', [
            self.env.ref('dac_erp.group_dac_erp_design').id
        ])],
    )
    submitted_at = fields.Datetime(string='Thời điểm gửi duyệt')
    reviewed_by_user_id = fields.Many2one(
        'res.users',
        string='Người duyệt',
        help='Sale hoặc Manager duyệt.',
    )
    reviewed_at = fields.Datetime(string='Thời điểm duyệt')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'dac_design_revision_attachment_rel',
        'revision_id',
        'attachment_id',
        string='File thiết kế',
    )
    note_internal = fields.Html(string='Ghi chú nội bộ designer')
    note_customer = fields.Html(string='Lý do điều chỉnh từ feedback khách')
    parent_revision_id = fields.Many2one(
        'dac.design.revision',
        string='Bản gốc',
        ondelete='set null',
        help='Tham chiếu bản trước nếu đây là rework.',
    )

    _sql_constraints = [
        (
            'uniq_order_revision_number',
            'unique(order_id, revision_number)',
            'Số bản phải duy nhất trong phạm vi 1 đơn hàng.',
        ),
    ]

    @api.depends('order_id')
    def _compute_revision_number(self):
        """
        Tự tăng revision_number trong phạm vi 1 sale.order.
        Phase A: chỉ compute khi tạo mới (record chưa có id). Logic chuẩn
        sẽ được hoàn thiện ở Phase B kèm test idempotent.
        """
        for rec in self:
            if not rec.order_id:
                rec.revision_number = 0
                continue
            domain = [('order_id', '=', rec.order_id.id)]
            if rec.id:
                domain.append(('id', '!=', rec.id))
            existing = self.search_count(domain)
            # Khi tạo mới, lấy số kế tiếp; khi sửa thì giữ giá trị nếu đã có
            if not rec.id or not rec.revision_number:
                rec.revision_number = existing + 1
            else:
                rec.revision_number = rec.revision_number
