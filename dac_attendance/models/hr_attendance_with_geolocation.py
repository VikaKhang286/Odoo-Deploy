# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo
from odoo import models, fields, api
from odoo.exceptions import ValidationError


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two GPS coordinates using Haversine formula.
    Returns distance in meters.
    """
    R = 6371000  # Earth's radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


class HrAttendanceWithGeolocation(models.Model):
    """
    Extended hr.attendance model with geolocation and photo capture support.
    """
    _inherit = 'hr.attendance'
    _table = 'hr_attendance'

    check_in_date = fields.Date(
        string='Ngày check-in',
        compute='_compute_check_in_date',
        store=True
    )

    @api.depends('check_in')
    def _compute_check_in_date(self):
        for record in self:
            if record.check_in:
                record.check_in_date = record.check_in.date()
            else:
                record.check_in_date = False

    # GPS/Location fields
    check_in_latitude = fields.Float(
        string='Vĩ độ check-in',
        digits=(10, 7),
        readonly=True,
        help='Vĩ độ khi check-in'
    )
    check_in_longitude = fields.Float(
        string='Kinh độ check-in',
        digits=(10, 7),
        readonly=True,
        help='Kinh độ khi check-in'
    )
    check_in_gps_accuracy = fields.Float(
        string='Độ chính xác GPS check-in',
        digits=(6, 2),
        readonly=True,
        help='Độ chính xác GPS khi check-in (mét)'
    )
    check_out_latitude = fields.Float(
        string='Vĩ độ check-out',
        digits=(10, 7),
        readonly=True,
        help='Vĩ độ khi check-out'
    )
    check_out_longitude = fields.Float(
        string='Kinh độ check-out',
        digits=(10, 7),
        readonly=True,
        help='Kinh độ khi check-out'
    )
    check_out_gps_accuracy = fields.Float(
        string='Độ chính xác GPS check-out',
        digits=(6, 2),
        readonly=True,
        help='Độ chính xác GPS khi check-out (mét)'
    )
    
    # Network/Location info
    check_in_ip_address = fields.Char(
        string='IP check-in',
        readonly=True,
        help='Địa chỉ IP khi check-in'
    )
    check_in_wifi_ssid = fields.Char(
        string='WiFi SSID check-in',
        readonly=True,
        help='Tên WiFi khi check-in'
    )
    check_out_ip_address = fields.Char(
        string='IP check-out',
        readonly=True,
        help='Địa chỉ IP khi check-out'
    )
    check_out_wifi_ssid = fields.Char(
        string='WiFi SSID check-out',
        readonly=True,
        help='Tên WiFi khi check-out'
    )
    
    # Photo fields
    check_in_photo = fields.Binary(
        string='Ảnh check-in',
        readonly=True,
        attachment=False,
        help='Ảnh chụp khi check-in'
    )
    check_out_photo = fields.Binary(
        string='Ảnh check-out',
        readonly=True,
        attachment=False,
        help='Ảnh chụp khi check-out'
    )
    check_in_photo_timestamp = fields.Datetime(
        string='Thời gian chụp check-in',
        readonly=True,
        help='Thời gian chụp ảnh check-in'
    )
    check_out_photo_timestamp = fields.Datetime(
        string='Thời gian chụp check-out',
        readonly=True,
        help='Thời gian chụp ảnh check-out'
    )
    
    # Photo metadata (JSON: timestamp, GPS)
    check_in_photo_metadata = fields.Text(
        string='Metadata ảnh check-in',
        readonly=True,
        help='Metadata JSON của ảnh check-in (thời gian, vị trí GPS)'
    )
    check_out_photo_metadata = fields.Text(
        string='Metadata ảnh check-out',
        readonly=True,
        help='Metadata JSON của ảnh check-out (thời gian, vị trí GPS)'
    )
    
    # Validation status
    gps_validated = fields.Boolean(
        string='GPS đã xác thực',
        default=False,
        readonly=True,
        help='GPS đã được xác thực nằm trong phạm vi cho phép'
    )
    wifi_validated = fields.Boolean(
        string='WiFi đã xác thực',
        default=False,
        readonly=True,
        help='WiFi đã được xác thực'
    )
    ip_validated = fields.Boolean(
        string='IP đã xác thực',
        default=False,
        readonly=True,
        help='IP đã được xác thực nằm trong dải cho phép'
    )
    photo_validated = fields.Boolean(
        string='Ảnh đã xác thực',
        default=False,
        readonly=True,
        help='Ảnh đã được chụp và xác thực'
    )
    
    # Custom computed fields
    worked_hours_display = fields.Float(
        string='Số giờ làm việc',
        compute='_compute_worked_hours_display',
        store=True,
        digits=(6, 2),
    )
    is_late = fields.Boolean(
        string='Đi muộn',
        default=False,
        help='Đánh dấu nếu check-in muộn hơn giờ làm việc'
    )
    is_early_leave = fields.Boolean(
        string='Về sớm',
        default=False,
        help='Đánh dấu nếu check-out sớm hơn giờ tan làm'
    )
    late_minutes = fields.Integer(
        string='Phút đi muộn',
        default=0,
        help='Số phút check-in muộn so với giờ làm việc'
    )

    @api.depends('worked_hours')
    def _compute_worked_hours_display(self):
        """Display worked hours with 2 decimal places."""
        for record in self:
            record.worked_hours_display = round(record.worked_hours, 2)

    def _get_employee_calendar(self, employee=None):
        # employee=None: called by Odoo base without arg (uses self.employee_id)
        emp = employee or self.employee_id
        return emp.resource_calendar_id or emp.company_id.resource_calendar_id

    def _get_employee_timezone(self, employee):
        calendar = self._get_employee_calendar(employee)
        return (
            getattr(calendar, 'tz', None)
            or employee.tz
            or employee.user_id.tz
            or employee.company_id.partner_id.tz
            or 'Asia/Ho_Chi_Minh'
        )

    def _get_workday_bounds(self, employee, target_dt=None):
        target_dt = target_dt or fields.Datetime.now()
        if isinstance(target_dt, str):
            target_dt = fields.Datetime.from_string(target_dt)
        tz_name = self._get_employee_timezone(employee)
        tz = ZoneInfo(tz_name)
        localized_dt = target_dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz)
        calendar = self._get_employee_calendar(employee)
        if not calendar:
            return {
                'tz': tz_name,
                'start': None,
                'end': None,
            }

        weekday = str(localized_dt.weekday())
        attendances = calendar.attendance_ids.filtered(lambda a: a.dayofweek == weekday and not a.display_type)
        if not attendances:
            return {
                'tz': tz_name,
                'start': None,
                'end': None,
            }

        start_hour = min(attendances.mapped('hour_from'))
        end_hour = max(attendances.mapped('hour_to'))

        start_dt_local = localized_dt.replace(
            hour=int(start_hour),
            minute=int(round((start_hour % 1) * 60)),
            second=0,
            microsecond=0,
        )
        end_dt_local = localized_dt.replace(
            hour=int(end_hour),
            minute=int(round((end_hour % 1) * 60)),
            second=0,
            microsecond=0,
        )

        return {
            'tz': tz_name,
            'start': start_dt_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None),
            'end': end_dt_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None),
        }

    def _build_check_in_status(self, employee, check_in_dt):
        bounds = self._get_workday_bounds(employee, check_in_dt)
        planned_start = bounds.get('start')
        if not planned_start or check_in_dt <= planned_start:
            return {
                'is_late': False,
                'late_minutes': 0,
            }

        late_minutes = max(0, int((check_in_dt - planned_start).total_seconds() // 60))
        return {
            'is_late': late_minutes > 0,
            'late_minutes': late_minutes,
        }

    def _build_check_out_status(self, employee, check_out_dt):
        bounds = self._get_workday_bounds(employee, check_out_dt)
        planned_end = bounds.get('end')
        is_early_leave = bool(planned_end and check_out_dt < planned_end)
        early_minutes = 0
        if is_early_leave:
            early_minutes = max(0, int((planned_end - check_out_dt).total_seconds() // 60))
        return {
            'is_early_leave': is_early_leave,
            'early_minutes': early_minutes,
            'planned_end': planned_end,
        }

    def _validate_gps_location(self, employee_id, latitude, longitude, accuracy=None):
        """
        Validate if GPS location is within allowed radius.
        Returns: (is_valid, distance_meters, error_message)
        """
        Config = self.env['hr.employee.attendance.config']
        config = Config.get_config_for_employee(employee_id)
        
        if not config or not config.allowed_gps_lat:
            # No config = no GPS validation required
            return True, 0, None
        
        distance = haversine_distance(
            config.allowed_gps_lat, config.allowed_gps_lng,
            latitude, longitude
        )
        
        max_distance = config.gps_radius_meters
        if distance > max_distance:
            return False, distance, f'Vị trí cách xa {distance:.0f}m (tối đa {max_distance}m)'
        
        return True, distance, None

    def _validate_ip_address(self, employee_id, ip_address):
        """
        Validate if IP address is within allowed range.
        Returns: (is_valid, error_message)
        """
        Config = self.env['hr.employee.attendance.config']
        config = Config.get_config_for_employee(employee_id)
        
        if not config or not config.validate_by_ip:
            return True, None
        
        if not config.allowed_ip_range:
            return True, None
        
        # Simple IP range validation (CIDR notation)
        import ipaddress
        try:
            allowed_network = ipaddress.ip_network(config.allowed_ip_range, strict=False)
            if ipaddress.ip_address(ip_address) not in allowed_network:
                return False, f'IP {ip_address} không nằm trong dải cho phép {config.allowed_ip_range}'
        except ValueError:
            # If CIDR is invalid, just allow any IP
            pass
        
        return True, None

    def _validate_wifi_ssid(self, employee_id, wifi_ssid):
        """
        Validate if WiFi SSID matches allowed SSID.
        Returns: (is_valid, error_message)
        """
        Config = self.env['hr.employee.attendance.config']
        config = Config.get_config_for_employee(employee_id)
        
        if not config or not config.validate_by_wifi:
            return True, None
        
        if not config.allowed_wifi_ssid:
            return True, None
        
        if wifi_ssid != config.allowed_wifi_ssid:
            return False, f'SSID "{wifi_ssid}" không được phép. Cần kết nối: {config.allowed_wifi_ssid}'
        
        return True, None

    @api.model
    def _create_attendance_with_geolocation(self, employee_id, action_time=None, values=None):
        """
        Create attendance record with geolocation validation.
        This is called by the kiosk/mobile check-in process.
        """
        values = values or {}
        
        # Validate GPS if provided
        if values.get('check_in_latitude') and values.get('check_in_longitude'):
            is_valid, distance, error = self._validate_gps_location(
                employee_id,
                values['check_in_latitude'],
                values['check_in_longitude'],
                values.get('check_in_gps_accuracy')
            )
            if not is_valid:
                raise ValidationError(f'Lỗi GPS: {error}')
            values['gps_validated'] = is_valid
        
        # Validate IP if provided
        if values.get('check_in_ip_address'):
            is_valid, error = self._validate_ip_address(
                employee_id,
                values['check_in_ip_address']
            )
            if not is_valid:
                raise ValidationError(f'Lỗi IP: {error}')
            values['ip_validated'] = is_valid
        
        # Validate WiFi if provided
        if values.get('check_in_wifi_ssid'):
            is_valid, error = self._validate_wifi_ssid(
                employee_id,
                values['check_in_wifi_ssid']
            )
            if not is_valid:
                raise ValidationError(f'Lỗi WiFi: {error}')
            values['wifi_validated'] = is_valid
        
        # Check if photo is required
        Config = self.env['hr.employee.attendance.config']
        config = Config.get_config_for_employee(employee_id)
        if config and config.photo_mandatory and not values.get('check_in_photo'):
            raise ValidationError('Yêu cầu chụp ảnh khi check-in')
        
        if values.get('check_in_photo'):
            values['photo_validated'] = True
            values['check_in_photo_timestamp'] = fields.Datetime.now()
        
        return self.create(values)

    @api.model
    def dac_check_in(self, data=None):
        """
        Check-in method callable from frontend via orm.call().
        Returns dict with success status and message.
        """
        import base64
        import json
        data = data or {}
        try:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
            if not employee:
                return {'success': False, 'message': 'Không tìm thấy nhân viên cho user hiện tại'}

            # Check if already checked in
            open_att = self.search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
            ], limit=1)
            if open_att:
                return {'success': False, 'message': 'Bạn đã check-in rồi. Hãy check-out trước.'}

            Config = self.env['hr.employee.attendance.config']
            config = Config.get_config_for_employee(employee.id)
            method = config.check_in_method if config else 'location'

            check_in_time = fields.Datetime.now()
            timing_status = self._build_check_in_status(employee, check_in_time)
            success_message = (
                f"Bạn đã đi làm trễ {timing_status['late_minutes']} phút, hãy chú ý thời gian làm việc nhé!"
                if timing_status['is_late']
                else 'Chúc mừng bạn đã đi làm đúng giờ, hãy tiếp tục phát huy nhé'
            )
            vals = {
                'employee_id': employee.id,
                'check_in': check_in_time,
                'is_late': timing_status['is_late'],
                'late_minutes': timing_status['late_minutes'],
            }

            if method == 'location':
                validation_type = config.location_validation_type if config else 'ip'
                ip_valid, gps_valid = True, True
                ip_error, gps_error = None, None

                if validation_type in ('ip', 'ip_or_gps') and config and config.allowed_ip_range:
                    ip_addr = data.get('ip_address', '')
                    vals['check_in_ip_address'] = ip_addr
                    if ip_addr:
                        ip_valid, ip_error = self._validate_ip_simple(ip_addr, config.allowed_ip_range)
                        vals['ip_validated'] = ip_valid

                if validation_type in ('gps', 'ip_or_gps'):
                    lat = data.get('latitude')
                    lng = data.get('longitude')
                    if lat and lng:
                        vals['check_in_latitude'] = lat
                        vals['check_in_longitude'] = lng
                        vals['check_in_gps_accuracy'] = data.get('accuracy', 0)
                        if config and config.allowed_gps_lat:
                            gps_valid, gps_error = self._validate_gps_simple(
                                lat, lng, config.allowed_gps_lat,
                                config.allowed_gps_lng, config.gps_radius_meters)
                            vals['gps_validated'] = gps_valid
                    elif validation_type == 'gps':
                        gps_valid = False
                        gps_error = 'Không lấy được vị trí GPS'

                if validation_type == 'ip' and not ip_valid:
                    return {'success': False, 'message': f'Lỗi IP: {ip_error}'}
                elif validation_type == 'gps' and not gps_valid:
                    return {'success': False, 'message': f'Lỗi GPS: {gps_error}'}
                elif validation_type == 'ip_or_gps' and not ip_valid and not gps_valid:
                    return {'success': False, 'message': f'IP: {ip_error}. GPS: {gps_error}'}

            elif method == 'photo':
                photo_b64 = data.get('photo_base64')
                if not photo_b64:
                    return {'success': False, 'message': 'Vui lòng chụp ảnh để check-in'}
                vals['check_in_photo'] = photo_b64
                vals['check_in_photo_timestamp'] = fields.Datetime.now()
                vals['photo_validated'] = True
                metadata = data.get('photo_metadata', {})
                if metadata:
                    import json as json_mod
                    vals['check_in_photo_metadata'] = json_mod.dumps(metadata)
                    if metadata.get('latitude') and metadata.get('longitude'):
                        vals['check_in_latitude'] = metadata['latitude']
                        vals['check_in_longitude'] = metadata['longitude']

            attendance = self.create(vals)
            return {
                'success': True,
                'message': success_message,
                'attendance_id': attendance.id,
                'check_in_time': str(attendance.check_in),
                'is_late': attendance.is_late,
                'late_minutes': attendance.late_minutes,
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_check_out(self, data=None):
        """Check-out method callable from frontend via orm.call()."""
        import json
        data = data or {}
        try:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
            if not employee:
                return {'success': False, 'message': 'Không tìm thấy nhân viên'}

            attendance = self.search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
            ], limit=1, order='check_in desc')

            if not attendance:
                return {'success': False, 'message': 'Không tìm thấy bản ghi check-in'}

            Config = self.env['hr.employee.attendance.config']
            config = Config.get_config_for_employee(employee.id)
            method = config.check_in_method if config else 'location'

            check_out_time = fields.Datetime.now()
            checkout_status = self._build_check_out_status(employee, check_out_time)
            success_message = f"Check-out thành công! Số giờ làm: {round(attendance.worked_hours or 0, 2)}h"
            if checkout_status['is_early_leave']:
                success_message += ' Bạn đã check-out sớm, hệ thống đã ghi nhận lại.'
            vals = {
                'check_out': check_out_time,
                'is_early_leave': checkout_status['is_early_leave'],
            }

            if method == 'photo':
                photo_b64 = data.get('photo_base64')
                if not photo_b64:
                    return {'success': False, 'message': 'Vui lòng chụp ảnh để check-out'}
                vals['check_out_photo'] = photo_b64
                vals['check_out_photo_timestamp'] = fields.Datetime.now()
                metadata = data.get('photo_metadata', {})
                if metadata:
                    vals['check_out_photo_metadata'] = json.dumps(metadata)

            if data.get('latitude') and data.get('longitude'):
                vals['check_out_latitude'] = data['latitude']
                vals['check_out_longitude'] = data['longitude']

            attendance.write(vals)
            worked_hours = round(attendance.worked_hours or 0, 2)
            success_message = f"Check-out thành công! Số giờ làm: {worked_hours}h"
            if checkout_status['is_early_leave']:
                success_message += ' Bạn đã check-out sớm, hệ thống đã ghi nhận lại.'
            return {
                'success': True,
                'message': success_message,
                'attendance_id': attendance.id,
                'worked_hours': worked_hours,
                'is_early_leave': attendance.is_early_leave,
                'early_minutes': checkout_status['early_minutes'],
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @api.model
    def dac_get_checkout_confirmation_info(self):
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if not employee:
            return {
                'needs_confirmation': False,
            }

        now_dt = fields.Datetime.now()
        status = self._build_check_out_status(employee, now_dt)
        if not status['is_early_leave']:
            return {
                'needs_confirmation': False,
            }

        return {
            'needs_confirmation': True,
            'early_minutes': status['early_minutes'],
            'message': f'Bạn có muốn check-out sớm không? Hệ thống ghi nhận bạn về sớm {status["early_minutes"]} phút.',
        }

    def _validate_ip_simple(self, ip_address, allowed_range):
        """Simple IP validation. Returns (is_valid, error_msg)."""
        import ipaddress
        try:
            network = ipaddress.ip_network(allowed_range, strict=False)
            if ipaddress.ip_address(ip_address) not in network:
                return False, f'IP {ip_address} không trong dải {allowed_range}'
            return True, None
        except ValueError:
            return True, None

    def _validate_gps_simple(self, lat, lng, allowed_lat, allowed_lng, radius):
        """Simple GPS validation. Returns (is_valid, error_msg)."""
        distance = haversine_distance(allowed_lat, allowed_lng, lat, lng)
        if distance > radius:
            return False, f'Cách {distance:.0f}m (tối đa {radius}m)'
        return True, None
