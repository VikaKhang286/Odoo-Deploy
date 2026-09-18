# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta
from odoo import models, fields, api
from odoo.exceptions import AccessError, ValidationError


class DacAttendanceDashboard(models.AbstractModel):
    """Service model — không có table, chỉ chứa @api.model methods cho OWL dashboard."""
    _name = 'dac.attendance.dashboard'
    _description = 'DAC Attendance Dashboard Service'

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_current_employee(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1)
        return employee or self.env['hr.employee']

    def _format_time(self, dt):
        if not dt:
            return ''
        tz = self.env.user.tz or 'Asia/Ho_Chi_Minh'
        from zoneinfo import ZoneInfo
        local = dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo(tz))
        return local.strftime('%H:%M')

    def _format_date(self, d):
        if not d:
            return ''
        if hasattr(d, 'strftime'):
            return d.strftime('%d/%m/%Y')
        return str(d)

    # ── Employee Dashboard ────────────────────────────────────────────────────

    @api.model
    def dac_get_employee_dashboard(self):
        employee = self._get_current_employee()
        if not employee:
            return {'error': 'Không tìm thấy nhân viên cho tài khoản này'}

        today = date.today()
        month_start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        month_end = today.replace(day=last_day)

        # ── Today status ──
        open_att = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
        ], limit=1)
        today_atts = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in_date', '=', today),
        ])
        today_hours = sum(a.worked_hours or 0 for a in today_atts)
        if open_att:
            from datetime import datetime
            elapsed = (datetime.utcnow() - open_att.check_in).total_seconds() / 3600
            today_hours += elapsed

        today_status = {
            'checked_in': bool(open_att),
            'check_in_time': self._format_time(open_att.check_in) if open_att else '',
            'today_hours': round(today_hours, 2),
            'is_late': open_att.is_late if open_att else False,
            'late_minutes': open_att.late_minutes if open_att else 0,
        }

        # ── Month calendar ──
        month_atts = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in_date', '>=', month_start),
            ('check_in_date', '<=', month_end),
        ])
        att_by_date = {}
        for att in month_atts:
            d = att.check_in_date
            if d not in att_by_date:
                att_by_date[d] = att
            elif att.is_late and not att_by_date[d].is_late:
                pass  # keep first (earliest)

        approved_leaves = self.env['dac.attendance.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', month_end),
            ('date_to', '>=', month_start),
        ])
        leave_dates = set()
        for leave in approved_leaves:
            d = leave.date_from
            while d <= leave.date_to:
                leave_dates.add(d)
                d += timedelta(days=1)

        month_calendar = []
        d = month_start
        while d <= month_end:
            if d > today:
                status = 'future'
            elif d.weekday() >= 5:
                status = 'weekend'
            elif d in leave_dates:
                status = 'leave'
            elif d in att_by_date:
                status = 'late' if att_by_date[d].is_late else 'on_time'
            else:
                status = 'absent'
            month_calendar.append({
                'date': str(d),
                'day': d.day,
                'weekday': d.weekday(),
                'status': status,
            })
            d += timedelta(days=1)

        # ── Leave balance ──
        config = self.env['hr.employee.attendance.config'].get_config_for_employee(
            employee.id)
        annual_total = config.annual_leave_days if config else 12
        sick_total = config.sick_leave_days if config else 5
        unpaid_total = config.unpaid_leave_days if config else 3

        year_start = today.replace(month=1, day=1)
        year_end = today.replace(month=12, day=31)

        def _used_days(leave_type):
            leaves = self.env['dac.attendance.leave'].search([
                ('employee_id', '=', employee.id),
                ('leave_type', '=', leave_type),
                ('state', '=', 'approved'),
                ('date_from', '>=', year_start),
                ('date_to', '<=', year_end),
            ])
            return sum(l.number_of_days for l in leaves)

        leave_balance = {
            'annual': {'used': _used_days('annual'), 'total': annual_total},
            'sick': {'used': _used_days('sick'), 'total': sick_total},
            'unpaid': {'used': _used_days('unpaid'), 'total': unpaid_total},
        }

        # ── Pending requests ──
        pending_leaves = self.env['dac.attendance.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('pending', 'draft')),
        ], order='date_from desc')
        pending_amendments = self.env['dac.attendance.amendment'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'pending'),
        ], order='target_date desc')

        type_labels = {'annual': 'Phép năm', 'sick': 'Phép bệnh',
                       'unpaid': 'Không lương', 'other': 'Khác'}
        amend_labels = {
            'missing_checkin': 'Quên check-in',
            'missing_checkout': 'Quên check-out',
            'both_missing': 'Quên cả hai',
            'wrong_time': 'Sai giờ',
        }

        pending_requests = []
        for leave in pending_leaves:
            pending_requests.append({
                'type': 'leave',
                'id': leave.id,
                'summary': f"{type_labels.get(leave.leave_type, '')} "
                           f"{self._format_date(leave.date_from)} → "
                           f"{self._format_date(leave.date_to)} "
                           f"({leave.number_of_days:.0f} ngày)",
                'state': leave.state,
            })
        for amend in pending_amendments:
            pending_requests.append({
                'type': 'amendment',
                'id': amend.id,
                'summary': f"{amend_labels.get(amend.amendment_type, '')} "
                           f"{self._format_date(amend.target_date)} "
                           f"{self._format_time(amend.actual_check_in)}→"
                           f"{self._format_time(amend.actual_check_out)}",
                'state': amend.state,
            })

        # ── History (current month, last 15 records) ──
        history_atts = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in_date', '>=', month_start),
        ], order='check_in desc', limit=15)

        history = []
        for att in history_atts:
            d = att.check_in_date
            status = 'working' if not att.check_out else (
                'late' if att.is_late else 'on_time')
            history.append({
                'date': self._format_date(d),
                'check_in': self._format_time(att.check_in),
                'check_out': self._format_time(att.check_out) if att.check_out else '',
                'worked_hours': round(att.worked_hours or 0, 2),
                'is_late': att.is_late,
                'late_minutes': att.late_minutes or 0,
                'is_early_leave': att.is_early_leave,
                'status': status,
            })

        # Điền ngày vắng mặt trong tháng vào history (chỉ ngày làm việc không có attendance)
        history_dates = {att.check_in_date for att in history_atts}
        for cal_day in reversed(month_calendar):
            d_obj = date.fromisoformat(cal_day['date'])
            if cal_day['status'] == 'absent' and d_obj not in history_dates and d_obj <= today:
                history.append({
                    'date': self._format_date(d_obj),
                    'check_in': '',
                    'check_out': '',
                    'worked_hours': 0,
                    'is_late': False,
                    'late_minutes': 0,
                    'is_early_leave': False,
                    'status': 'absent',
                })
            elif cal_day['status'] == 'leave' and d_obj not in history_dates:
                leave_match = next(
                    (l for l in approved_leaves
                     if l.date_from <= d_obj <= l.date_to), None)
                history.append({
                    'date': self._format_date(d_obj),
                    'check_in': '',
                    'check_out': '',
                    'worked_hours': 0,
                    'is_late': False,
                    'late_minutes': 0,
                    'is_early_leave': False,
                    'status': 'leave',
                    'leave_type': type_labels.get(
                        leave_match.leave_type, 'Nghỉ phép') if leave_match else 'Nghỉ phép',
                })

        # Sort by date desc
        def _date_key(h):
            try:
                parts = h['date'].split('/')
                return date(int(parts[2]), int(parts[1]), int(parts[0]))
            except Exception:
                return date.min

        history.sort(key=_date_key, reverse=True)
        history = history[:20]

        return {
            'employee_name': employee.name,
            'today_status': today_status,
            'month_calendar': month_calendar,
            'month_label': today.strftime('%m/%Y'),
            'leave_balance': leave_balance,
            'pending_requests': pending_requests,
            'history': history,
        }

    # ── Manager Dashboard ─────────────────────────────────────────────────────

    @api.model
    def dac_get_manager_dashboard(self):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            raise AccessError('Chỉ quản lý chấm công mới có thể xem trang này.')

        today = date.today()
        from datetime import datetime
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        all_employees = self.env['hr.employee'].search([('active', '=', True)])

        today_atts = self.env['hr.attendance'].search([
            ('check_in', '>=', today_start),
            ('check_in', '<=', today_end),
        ])

        checked_in_ids = {a.employee_id.id for a in today_atts}
        late_ids = {a.employee_id.id for a in today_atts if a.is_late}
        absent_ids = {e.id for e in all_employees if e.id not in checked_in_ids}

        # Build present list (currently working = no check_out yet)
        open_atts = {a.employee_id.id: a for a in today_atts if not a.check_out}

        present_list = []
        for att in today_atts:
            emp = att.employee_id
            present_list.append({
                'employee_id': emp.id,
                'name': emp.name,
                'check_in': self._format_time(att.check_in),
                'check_out': self._format_time(att.check_out) if att.check_out else '',
                'is_late': att.is_late,
                'late_minutes': att.late_minutes or 0,
                'still_working': not att.check_out,
            })
        # Deduplicate by employee (keep latest)
        seen = {}
        for p in present_list:
            seen[p['employee_id']] = p
        present_list = sorted(seen.values(), key=lambda x: x['name'])

        absent_list = [
            {'employee_id': e.id, 'name': e.name}
            for e in all_employees if e.id in absent_ids
        ]

        # Pending approvals
        pending_leaves = self.env['dac.attendance.leave'].search(
            [('state', '=', 'pending')], order='date_from')
        pending_amendments = self.env['dac.attendance.amendment'].search(
            [('state', '=', 'pending')], order='target_date')

        type_labels = {'annual': 'Phép năm', 'sick': 'Phép bệnh',
                       'unpaid': 'Không lương', 'other': 'Khác'}
        amend_labels = {
            'missing_checkin': 'Quên check-in',
            'missing_checkout': 'Quên check-out',
            'both_missing': 'Quên cả hai',
            'wrong_time': 'Sai giờ',
        }

        leaves_data = [{
            'id': l.id,
            'employee_name': l.employee_id.name,
            'leave_type': type_labels.get(l.leave_type, l.leave_type),
            'date_from': self._format_date(l.date_from),
            'date_to': self._format_date(l.date_to),
            'days': l.number_of_days,
            'reason': l.reason or '',
        } for l in pending_leaves]

        amendments_data = [{
            'id': a.id,
            'employee_name': a.employee_id.name,
            'target_date': self._format_date(a.target_date),
            'amendment_type': amend_labels.get(a.amendment_type, a.amendment_type),
            'actual_check_in': self._format_time(a.actual_check_in),
            'actual_check_out': self._format_time(a.actual_check_out),
            'reason': a.reason or '',
        } for a in pending_amendments]

        total_pending = len(leaves_data) + len(amendments_data)

        return {
            'today_stats': {
                'present': len(present_list),
                'absent': len(absent_list),
                'late': len(late_ids),
                'pending_approvals': total_pending,
            },
            'present_list': present_list,
            'absent_list': absent_list,
            'pending_approvals': {
                'leaves': leaves_data,
                'amendments': amendments_data,
            },
        }

    # ── Submit / Cancel ───────────────────────────────────────────────────────

    @api.model
    def dac_submit_leave(self, vals):
        employee = self._get_current_employee()
        if not employee:
            return {'success': False, 'message': 'Không tìm thấy nhân viên'}
        try:
            leave = self.env['dac.attendance.leave'].create({
                'employee_id': employee.id,
                'leave_type': vals.get('leave_type', 'annual'),
                'date_from': vals['date_from'],
                'date_to': vals['date_to'],
                'reason': vals.get('reason', ''),
                'state': 'pending',
            })
            return {'success': True, 'id': leave.id}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_submit_amendment(self, vals):
        employee = self._get_current_employee()
        if not employee:
            return {'success': False, 'message': 'Không tìm thấy nhân viên'}
        try:
            amendment = self.env['dac.attendance.amendment'].create({
                'employee_id': employee.id,
                'target_date': vals['target_date'],
                'amendment_type': vals.get('amendment_type', 'missing_checkin'),
                'actual_check_in': vals['actual_check_in'],
                'actual_check_out': vals.get('actual_check_out') or False,
                'reason': vals.get('reason', ''),
                'state': 'pending',
            })
            return {'success': True, 'id': amendment.id}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_cancel_request(self, model_name, record_id):
        try:
            if model_name == 'leave':
                record = self.env['dac.attendance.leave'].browse(record_id)
            elif model_name == 'amendment':
                record = self.env['dac.attendance.amendment'].browse(record_id)
            else:
                return {'success': False, 'message': 'Model không hợp lệ'}
            record.action_cancel()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ── Manager Approve / Refuse ──────────────────────────────────────────────

    @api.model
    def dac_approve_leave(self, leave_id):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return {'success': False, 'message': 'Không có quyền duyệt'}
        try:
            self.env['dac.attendance.leave'].browse(leave_id).action_approve()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_refuse_leave(self, leave_id, reason=''):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return {'success': False, 'message': 'Không có quyền từ chối'}
        try:
            self.env['dac.attendance.leave'].browse(leave_id).action_refuse(reason)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_approve_amendment(self, amendment_id):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return {'success': False, 'message': 'Không có quyền duyệt'}
        try:
            self.env['dac.attendance.amendment'].browse(
                amendment_id).action_approve()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_refuse_amendment(self, amendment_id, reason=''):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return {'success': False, 'message': 'Không có quyền từ chối'}
        try:
            self.env['dac.attendance.amendment'].browse(
                amendment_id).action_refuse(reason)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}
