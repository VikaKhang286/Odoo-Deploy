# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class HrEmployeeAttendanceConfig(models.Model):
    """
    Per-employee attendance check-in method configuration.
    Admin can set different check-in methods for each employee:
    - 'location': Check-in by button click with IP/GPS validation
    - 'photo': Check-in by taking a photo with camera (no gallery upload)
    """
    _name = 'hr.employee.attendance.config'
    _description = 'Employee Attendance Configuration'
    _table = 'hr_employee_attendance_config'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Nhân viên',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )
    check_in_method = fields.Selection(
        [
            ('location', 'Xác thực vị trí (IP/GPS)'),
            ('photo', 'Chụp ảnh xác thực'),
        ],
        string='Phương thức check-in',
        required=True,
        default='location',
        help='Chọn phương thức check-in cho nhân viên này'
    )

    # --- Location validation config ---
    location_validation_type = fields.Selection(
        [
            ('ip', 'Xác thực theo IP'),
            ('gps', 'Xác thực theo GPS'),
            ('ip_or_gps', 'IP hoặc GPS (một trong hai)'),
        ],
        string='Kiểu xác thực vị trí',
        default='ip',
        help='Chọn kiểu xác thực vị trí khi check-in bằng nút bấm'
    )

    # GPS Configuration
    allowed_gps_lat = fields.Float(
        string='Vĩ độ cho phép',
        digits=(10, 7),
        help='Vĩ độ của vị trí cho phép check-in'
    )
    allowed_gps_lng = fields.Float(
        string='Kinh độ cho phép',
        digits=(10, 7),
        help='Kinh độ của vị trí cho phép check-in'
    )
    gps_radius_meters = fields.Integer(
        string='Bán kính GPS (m)',
        default=500,
        help='Bán kính cho phép tính từ vị trí được phép (mét)'
    )

    # IP Configuration
    allowed_ip_range = fields.Char(
        string='IP range cho phép',
        help='Dải IP cho phép check-in (VD: 192.168.1.0/24)'
    )

    # Legacy fields kept for backward compatibility
    allowed_wifi_ssid = fields.Char(
        string='WiFi SSID cho phép',
        help='Tên WiFi SSID cần kết nối để check-in (VD: COMPANY_WIFI)'
    )
    validate_by_ip = fields.Boolean(
        string='Xác thực theo IP',
        default=False,
        help='Bật để yêu cầu IP phải nằm trong dải cho phép'
    )
    validate_by_wifi = fields.Boolean(
        string='Xác thực theo WiFi',
        default=False,
        help='Bật để yêu cầu kết nối đúng WiFi'
    )

    # Photo Configuration
    require_photo_checkin = fields.Boolean(
        string='Yêu cầu chụp ảnh',
        default=False,
        help='Bật để yêu cầu nhân viên chụp ảnh khi check-in'
    )
    photo_mandatory = fields.Boolean(
        string='Ảnh bắt buộc',
        default=True,
        help='Nếu bật, nhân viên phải chụp ảnh mỗi lần check-in/check-out'
    )

    # Leave day quotas (per year, per employee)
    annual_leave_days = fields.Integer(
        string='Số ngày phép năm',
        default=12,
        help='Tổng số ngày phép năm mỗi năm của nhân viên này'
    )
    sick_leave_days = fields.Integer(
        string='Số ngày phép bệnh',
        default=5,
        help='Tổng số ngày phép bệnh mỗi năm'
    )
    unpaid_leave_days = fields.Integer(
        string='Số ngày nghỉ không lương',
        default=3,
        help='Tổng số ngày nghỉ không lương mỗi năm'
    )

    # Active state
    active = fields.Boolean(
        string='Active',
        default=True,
    )

    _sql_constraints = [
        ('employee_unique', 'unique(employee_id)',
         'Mỗi nhân viên chỉ có một cấu hình chấm công!'),
    ]

    @api.onchange('check_in_method')
    def _onchange_check_in_method(self):
        """Update required fields based on check-in method."""
        if self.check_in_method == 'photo':
            self.require_photo_checkin = True
            self.photo_mandatory = True
        elif self.check_in_method == 'location':
            self.require_photo_checkin = False
            self.photo_mandatory = False

    @api.model
    def get_config_for_employee(self, employee_id):
        """Get attendance config for specific employee."""
        config = self.search([
            ('employee_id', '=', employee_id),
            ('active', '=', True),
        ], limit=1)
        if not config:
            # Return empty recordset if not found
            return self.env['hr.employee.attendance.config']
        return config

    @api.model
    def get_config_for_current_user(self):
        """Get attendance config for the current logged-in user's employee."""
        try:
            uid = self.env.uid
            _logger.info("DAC_ATTENDANCE: get_config called for uid=%s", uid)
            
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', uid)], limit=1
            )
            _logger.info("DAC_ATTENDANCE: employee=%s", employee)
            
            if not employee:
                return {
                    'has_employee': False,
                    'has_config': False,
                }

            # Search config with sudo to avoid access issues
            config = self.sudo().search([
                ('employee_id', '=', employee.id),
                ('active', '=', True),
            ], limit=1)
            _logger.info("DAC_ATTENDANCE: config=%s", config)

            result = {
                'has_employee': True,
                'employee_id': employee.id,
                'employee_name': employee.name or '',
                'has_config': bool(config),
                'check_in_method': 'location',
                'checked_in': False,
                'check_in_time': None,
                'check_in_time_display': None,
                'today_hours': 0.0,
            }

            if config:
                result['check_in_method'] = config.check_in_method or 'location'
                if config.check_in_method == 'location':
                    result.update({
                        'location_validation_type': config.location_validation_type or 'ip',
                        'allowed_gps_lat': config.allowed_gps_lat or 0,
                        'allowed_gps_lng': config.allowed_gps_lng or 0,
                        'gps_radius_meters': config.gps_radius_meters or 100,
                        'allowed_ip_range': config.allowed_ip_range or '',
                    })

            # ---- Check current attendance status ----
            Attendance = self.env['hr.attendance'].sudo()
            
            # Find open attendance (checked in but not checked out)
            open_att = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
            ], limit=1, order='check_in desc')
            
            if open_att:
                result['checked_in'] = True
                result['check_in_time'] = open_att.check_in.isoformat() if open_att.check_in else None
                if open_att.check_in:
                    localized_check_in = fields.Datetime.context_timestamp(employee, open_att.check_in)
                    result['check_in_time_display'] = localized_check_in.strftime('%H:%M')
            
            # Calculate today's total worked hours
            today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_attendances = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', today_start),
            ])
            today_hours = sum(att.worked_hours or 0.0 for att in today_attendances)
            result['today_hours'] = round(today_hours, 2)

            _logger.info("DAC_ATTENDANCE: returning result=%s", result)
            return result
        except Exception as e:
            _logger.error("DAC_ATTENDANCE: Error in get_config_for_current_user: %s", e, exc_info=True)
            return {
                'has_employee': False,
                'has_config': False,
                'error': str(e),
            }
