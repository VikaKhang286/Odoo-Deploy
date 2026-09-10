# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, AccessError


class DacAttendanceAmendment(models.Model):
    _name = 'dac.attendance.amendment'
    _description = 'Đơn điều chỉnh chấm công'
    _order = 'target_date desc'
    _rec_name = 'display_name'

    employee_id = fields.Many2one(
        'hr.employee', string='Nhân viên', required=True,
        default=lambda self: self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1),
        ondelete='cascade',
    )
    target_date = fields.Date(string='Ngày cần điều chỉnh', required=True)
    amendment_type = fields.Selection([
        ('missing_checkin', 'Quên check-in'),
        ('missing_checkout', 'Quên check-out'),
        ('both_missing', 'Quên cả hai'),
        ('wrong_time', 'Sai giờ'),
    ], string='Loại điều chỉnh', required=True, default='missing_checkin')
    actual_check_in = fields.Datetime(string='Giờ vào thực tế', required=True)
    actual_check_out = fields.Datetime(string='Giờ ra thực tế')
    reason = fields.Text(string='Lý do', required=True)
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('refused', 'Từ chối'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='pending', required=True)
    approved_by = fields.Many2one('res.users', string='Người duyệt', readonly=True)
    approved_date = fields.Datetime(string='Ngày duyệt', readonly=True)
    refuse_reason = fields.Text(string='Lý do từ chối', readonly=True)
    attendance_id = fields.Many2one(
        'hr.attendance', string='Bản ghi chấm công', readonly=True,
        help='Bản ghi hr.attendance được tạo/cập nhật sau khi duyệt')

    display_name = fields.Char(compute='_compute_display_name', store=False)

    @api.depends('employee_id', 'target_date', 'amendment_type')
    def _compute_display_name(self):
        type_labels = {
            'missing_checkin': 'Quên check-in',
            'missing_checkout': 'Quên check-out',
            'both_missing': 'Quên cả hai',
            'wrong_time': 'Sai giờ',
        }
        for rec in self:
            label = type_labels.get(rec.amendment_type, '')
            if rec.employee_id and rec.target_date:
                rec.display_name = f"{rec.employee_id.name} – {label} {rec.target_date}"
            else:
                rec.display_name = label or 'Đơn điều chỉnh'

    @api.constrains('actual_check_in', 'actual_check_out')
    def _check_times(self):
        for rec in self:
            if rec.actual_check_in and rec.actual_check_out:
                if rec.actual_check_out <= rec.actual_check_in:
                    raise ValidationError('Giờ ra phải sau giờ vào.')

    def action_approve(self):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            raise AccessError('Chỉ quản lý chấm công mới có thể duyệt đơn.')
        Attendance = self.env['hr.attendance']
        for rec in self:
            if rec.state != 'pending':
                continue
            # Tìm bản ghi attendance hiện có của nhân viên trong ngày đó
            day_start = fields.Datetime.from_string(
                f"{rec.target_date} 00:00:00")
            day_end = fields.Datetime.from_string(
                f"{rec.target_date} 23:59:59")
            existing = Attendance.search([
                ('employee_id', '=', rec.employee_id.id),
                ('check_in', '>=', day_start),
                ('check_in', '<=', day_end),
            ], limit=1)

            att_vals = {
                'employee_id': rec.employee_id.id,
                'check_in': rec.actual_check_in,
            }
            if rec.actual_check_out:
                att_vals['check_out'] = rec.actual_check_out

            # Tính lại is_late dựa trên giờ vào thực tế
            att_vals.update(
                self._compute_late_status(rec.employee_id, rec.actual_check_in))

            if existing:
                existing.write(att_vals)
                attendance = existing
            else:
                attendance = Attendance.sudo().create(att_vals)

            rec.write({
                'state': 'approved',
                'approved_by': self.env.uid,
                'approved_date': fields.Datetime.now(),
                'attendance_id': attendance.id,
            })

    def _compute_late_status(self, employee, check_in_dt):
        """Tính is_late và late_minutes dựa trên lịch làm việc."""
        try:
            att_model = self.env['hr.attendance']
            status = att_model._build_check_in_status(employee, check_in_dt)
            return {
                'is_late': status['is_late'],
                'late_minutes': status['late_minutes'],
            }
        except Exception:
            return {'is_late': False, 'late_minutes': 0}

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
            if rec.state != 'pending':
                raise ValidationError('Chỉ có thể hủy đơn đang chờ duyệt.')
            employee = self.env['hr.employee'].search(
                [('user_id', '=', self.env.uid)], limit=1)
            is_manager = self.env.user.has_group(
                'hr_attendance.group_hr_attendance_manager')
            if not is_manager and rec.employee_id != employee:
                raise AccessError('Bạn chỉ có thể hủy đơn của chính mình.')
            rec.state = 'cancelled'
