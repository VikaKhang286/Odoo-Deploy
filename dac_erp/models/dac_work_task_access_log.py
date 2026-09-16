# -*- coding: utf-8 -*-
"""
dac.work.task.access.log
────────────────────────
Audit log mỗi lần Manager mở/xem một task cá nhân (`is_personal_reminder=True`).

Theo `docs/system_evaluation/12_solution_plan_workflow.md` mục 5.5 + 6.1
+ quyết định Q2: Manager có thể xem personal task nhưng phải bấm vào view
riêng cho từng cá nhân, mỗi lần xem ghi log + push event
`personal_task.inspected_by_manager` qua OpenClaw.

Phase A chỉ tạo schema. Hook ghi log + push event làm ở Phase C khi tách
record rule personal vs business.
"""

from odoo import fields, models


class DacWorkTaskAccessLog(models.Model):
    _name = 'dac.work.task.access.log'
    _description = 'DAC Work Task Access Log'
    _order = 'accessed_at desc, id desc'

    task_id = fields.Many2one(
        'dac.work.task',
        string='Task',
        required=True,
        index=True,
        ondelete='cascade',
    )
    accessed_by_user_id = fields.Many2one(
        'res.users',
        string='Người truy cập',
        required=True,
        index=True,
        default=lambda self: self.env.user,
    )
    accessed_at = fields.Datetime(
        string='Thời điểm truy cập',
        default=fields.Datetime.now,
        required=True,
    )
    access_kind = fields.Selection([
        ('manager_inspect', 'Manager xem việc cá nhân'),
        ('owner_view', 'Owner xem'),
        ('shared_team_view', 'Đồng đội xem (shared_team)'),
        ('public_view', 'Công khai xem'),
        ('other', 'Khác'),
    ], string='Loại truy cập', default='manager_inspect', required=True, index=True)
    note = fields.Text(string='Ghi chú', help='Ví dụ: lý do Manager mở.')
    task_owner_user_id = fields.Many2one(
        'res.users',
        string='Owner của task (snapshot)',
        index=True,
        help='Snapshot personal_owner_user_id tại thời điểm log để bảo toàn audit '
             'kể cả khi task bị reassign sau đó.',
    )
