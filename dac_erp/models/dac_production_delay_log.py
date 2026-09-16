# -*- coding: utf-8 -*-
"""
dac.production.delay.log
────────────────────────
Mỗi lần `dac.production.order.is_delayed` chuyển từ False → True ghi 1 log.

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 4.3.
Log này phục vụ audit + reporting trễ tiến độ thi công.

Phase A chỉ tạo schema. Phase B sẽ implement cron + tự tạo log.
"""

from odoo import fields, models


class DacProductionDelayLog(models.Model):
    _name = 'dac.production.delay.log'
    _description = 'DAC Production Delay Log'
    _order = 'detected_at desc, id desc'

    production_order_id = fields.Many2one(
        'dac.production.order',
        string='Lệnh thi công',
        required=True,
        index=True,
        ondelete='cascade',
    )
    detected_at = fields.Datetime(
        string='Phát hiện lúc',
        default=fields.Datetime.now,
        required=True,
    )
    expected_end_date = fields.Date(
        string='Hạn hoàn thành (snapshot)',
        help='Giá trị target_end_date của lệnh thi công tại thời điểm detect.',
    )
    reason = fields.Text(string='Lý do trễ')
    created_by_user_id = fields.Many2one(
        'res.users',
        string='Người ghi log',
        default=lambda self: self.env.user,
    )
