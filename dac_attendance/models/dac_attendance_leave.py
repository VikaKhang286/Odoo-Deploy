# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, AccessError


class DacAttendanceLeave(models.Model):
    _name = 'dac.attendance.leave'
    _description = 'Đơn xin nghỉ phép'
    _order = 'date_from desc'
    _rec_name = 'display_name'

    employee_id = fields.Many2one(
        'hr.employee', string='Nhân viên', required=True,
        default=lambda self: self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1),
        ondelete='cascade',
    )
    leave_type = fields.Selection([
        ('annual', 'Phép năm'),
        ('sick', 'Phép bệnh'),
        ('unpaid', 'Không lương'),
        ('other', 'Khác'),
    ], string='Loại phép', required=True, default='annual')
    date_from = fields.Date(string='Từ ngày', required=True)
    date_to = fields.Date(string='Đến ngày', required=True)
    number_of_days = fields.Float(
        string='Số ngày', compute='_compute_days', store=True, digits=(6, 1))
    reason = fields.Text(string='Lý do', required=True)
    state = fields.Selection([
        ('draft', 'Mới'),
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('refused', 'Từ chối'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='pending', required=True)
    approved_by = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    approved_date = fields.Datetime(string='Ngày duyệt', readonly=True)
    refuse_reason = fields.Text(string='Lý do từ chối', readonly=True)
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True)

    display_name = fields.Char(compute='_compute_display_name', store=False)

    @api.depends('employee_id', 'date_from', 'date_to', 'leave_type')
    def _compute_display_name(self):
        type_labels = {'annual': 'Phép năm', 'sick': 'Phép bệnh',
                       'unpaid': 'Không lương', 'other': 'Khác'}
        for rec in self:
            label = type_labels.get(rec.leave_type, '')
            if rec.employee_id and rec.date_from:
                rec.display_name = f"{rec.employee_id.name} – {label} {rec.date_from}"
            else:
                rec.display_name = label or 'Đơn nghỉ phép'

    @api.depends('date_from', 'date_to')
    def _compute_days(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                delta = (rec.date_to - rec.date_from).days + 1
                rec.number_of_days = max(0.0, float(delta))
            else:
                rec.number_of_days = 0.0

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError('Ngày kết thúc phải sau ngày bắt đầu.')

    def action_approve(self):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            raise AccessError('Chỉ quản lý chấm công mới có thể duyệt đơn.')
        for rec in self:
            if rec.state != 'pending':
                continue
            rec.write({
                'state': 'approved',
                'approved_by': self.env.uid,
                'approved_date': fields.Datetime.now(),
            })

    def action_refuse(self, reason=''):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            raise AccessError('Chỉ quản lý chấm công mới có thể từ chối đơn.')
        for rec in self:
            if rec.state != 'pending':
                continue
            rec.write({
                'state': 'refused',
                'approved_by': self.env.uid,
                'refuse_reason': reason,
            })

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'pending'):
                raise ValidationError('Chỉ có thể hủy đơn ở trạng thái Mới hoặc Chờ duyệt.')
            employee = self.env['hr.employee'].search(
                [('user_id', '=', self.env.uid)], limit=1)
            is_manager = self.env.user.has_group(
                'hr_attendance.group_hr_attendance_manager')
            if not is_manager and rec.employee_id != employee:
                raise AccessError('Bạn chỉ có thể hủy đơn của chính mình.')
            rec.state = 'cancelled'
