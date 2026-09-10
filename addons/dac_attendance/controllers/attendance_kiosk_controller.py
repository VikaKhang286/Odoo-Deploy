# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import json
from datetime import datetime
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class AttendanceKioskController(http.Controller):
    """
    Controller for DAC attendance check-in/check-out.
    Supports two methods:
    1. Location-based (IP/GPS) - one-click check-in via systray
    2. Photo-based - camera capture with metadata overlay
    """

    @http.route('/api/attendance/my-config', type='json', auth='user', methods=['POST'], csrf=False)
    def api_get_my_config(self, **kwargs):
        """Get attendance configuration for the current logged-in user."""
        try:
            Config = request.env['hr.employee.attendance.config']
            config_data = Config.get_config_for_current_user()

            # Also get current attendance status
            employee = request.env.user.employee_id
            if employee:
                today = fields.Date.today()
                attendance = request.env['hr.attendance'].search([
                    ('employee_id', '=', employee.id),
                    ('check_out', '=', False),
                ], limit=1, order='check_in desc')

                config_data['checked_in'] = bool(attendance)
                if attendance:
                    config_data['check_in_time'] = str(attendance.check_in)
                    config_data['attendance_id'] = attendance.id
                else:
                    config_data['check_in_time'] = False
                    config_data['attendance_id'] = False

                # Get today's total hours
                today_attendances = request.env['hr.attendance'].search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '>=', datetime.combine(today, datetime.min.time())),
                ])
                total_hours = sum(a.worked_hours for a in today_attendances if a.worked_hours)
                config_data['today_hours'] = round(total_hours, 2)
            else:
                config_data['checked_in'] = False
                config_data['today_hours'] = 0

            return {'success': True, 'data': config_data}
        except Exception as e:
            _logger.error("Error getting attendance config: %s", e, exc_info=True)
            return {'success': False, 'message': str(e)}

    @http.route('/api/attendance/check-in', type='json', auth='user', methods=['POST'], csrf=False)
    def api_check_in(self, **post):
        """
        API endpoint for check-in.
        For location method: validates IP and/or GPS based on config.
        For photo method: requires photo_base64 with metadata.
        """
        try:
            data = request.jsonrequest.get('params', {}) if 'params' in request.jsonrequest else request.jsonrequest
            employee = request.env.user.employee_id
            if not employee:
                return {'success': False, 'message': 'Không tìm thấy nhân viên cho user hiện tại'}

            # Check if already checked in
            open_attendance = request.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
            ], limit=1)
            if open_attendance:
                return {'success': False, 'message': 'Bạn đã check-in rồi. Hãy check-out trước.'}

            Config = request.env['hr.employee.attendance.config']
            config = Config.get_config_for_employee(employee.id)
            method = config.check_in_method if config else 'location'

            vals = {
                'employee_id': employee.id,
                'check_in': fields.Datetime.now(),
            }

            if method == 'location':
                # Validate location (IP and/or GPS)
                validation_type = config.location_validation_type if config else 'ip'
                ip_valid = True
                gps_valid = True
                ip_error = None
                gps_error = None

                if validation_type in ('ip', 'ip_or_gps'):
                    ip_address = data.get('ip_address') or request.httprequest.remote_addr
                    vals['check_in_ip_address'] = ip_address
                    if config and config.allowed_ip_range:
                        ip_valid, ip_error = self._validate_ip(ip_address, config.allowed_ip_range)
                        vals['ip_validated'] = ip_valid

                if validation_type in ('gps', 'ip_or_gps'):
                    lat = data.get('latitude')
                    lng = data.get('longitude')
                    if lat and lng:
                        vals['check_in_latitude'] = lat
                        vals['check_in_longitude'] = lng
                        vals['check_in_gps_accuracy'] = data.get('accuracy', 0)
                        if config and config.allowed_gps_lat:
                            gps_valid, gps_error = self._validate_gps(
                                lat, lng, config.allowed_gps_lat,
                                config.allowed_gps_lng, config.gps_radius_meters
                            )
                            vals['gps_validated'] = gps_valid
                    elif validation_type == 'gps':
                        gps_valid = False
                        gps_error = 'Không lấy được vị trí GPS. Vui lòng cho phép truy cập vị trí.'

                # Check validation result
                if validation_type == 'ip' and not ip_valid:
                    return {'success': False, 'message': f'Lỗi IP: {ip_error}'}
                elif validation_type == 'gps' and not gps_valid:
                    return {'success': False, 'message': f'Lỗi GPS: {gps_error}'}
                elif validation_type == 'ip_or_gps' and not ip_valid and not gps_valid:
                    return {'success': False, 'message': f'Không thể xác thực vị trí. IP: {ip_error}. GPS: {gps_error}'}

            elif method == 'photo':
                # Validate photo
                photo_b64 = data.get('photo_base64')
                if not photo_b64:
                    return {'success': False, 'message': 'Vui lòng chụp ảnh để check-in'}

                try:
                    photo_data = base64.b64decode(photo_b64)
                    vals['check_in_photo'] = base64.b64encode(photo_data).decode('utf-8')
                    vals['check_in_photo_timestamp'] = fields.Datetime.now()
                    vals['photo_validated'] = True
                except Exception:
                    return {'success': False, 'message': 'Ảnh không hợp lệ'}

                # Store photo metadata (GPS from photo)
                metadata = data.get('photo_metadata', {})
                if metadata:
                    vals['check_in_photo_metadata'] = json.dumps(metadata)
                    if metadata.get('latitude') and metadata.get('longitude'):
                        vals['check_in_latitude'] = metadata['latitude']
                        vals['check_in_longitude'] = metadata['longitude']

            attendance = request.env['hr.attendance'].create(vals)

            return {
                'success': True,
                'message': 'Check-in thành công!',
                'attendance_id': attendance.id,
                'check_in_time': str(attendance.check_in),
            }

        except ValidationError as e:
            return {'success': False, 'message': str(e.name or e)}
        except Exception as e:
            _logger.error("Check-in error: %s", e, exc_info=True)
            return {'success': False, 'message': f'Lỗi: {str(e)}'}

    @http.route('/api/attendance/check-out', type='json', auth='user', methods=['POST'], csrf=False)
    def api_check_out(self, **post):
        """API endpoint for check-out."""
        try:
            data = request.jsonrequest.get('params', {}) if 'params' in request.jsonrequest else request.jsonrequest
            employee = request.env.user.employee_id
            if not employee:
                return {'success': False, 'message': 'Không tìm thấy nhân viên'}

            attendance = request.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
            ], limit=1, order='check_in desc')

            if not attendance:
                return {'success': False, 'message': 'Không tìm thấy bản ghi check-in'}

            Config = request.env['hr.employee.attendance.config']
            config = Config.get_config_for_employee(employee.id)
            method = config.check_in_method if config else 'location'

            vals = {
                'check_out': fields.Datetime.now(),
            }

            if method == 'photo':
                photo_b64 = data.get('photo_base64')
                if not photo_b64:
                    return {'success': False, 'message': 'Vui lòng chụp ảnh để check-out'}
                try:
                    photo_data = base64.b64decode(photo_b64)
                    vals['check_out_photo'] = base64.b64encode(photo_data).decode('utf-8')
                    vals['check_out_photo_timestamp'] = fields.Datetime.now()
                except Exception:
                    return {'success': False, 'message': 'Ảnh không hợp lệ'}

                metadata = data.get('photo_metadata', {})
                if metadata:
                    vals['check_out_photo_metadata'] = json.dumps(metadata)
                    if metadata.get('latitude') and metadata.get('longitude'):
                        vals['check_out_latitude'] = metadata['latitude']
                        vals['check_out_longitude'] = metadata['longitude']

            # Store IP for location method
            if method == 'location':
                vals['check_out_ip_address'] = data.get('ip_address') or request.httprequest.remote_addr
                if data.get('latitude') and data.get('longitude'):
                    vals['check_out_latitude'] = data['latitude']
                    vals['check_out_longitude'] = data['longitude']

            attendance.write(vals)

            return {
                'success': True,
                'message': 'Check-out thành công!',
                'attendance_id': attendance.id,
                'worked_hours': round(attendance.worked_hours or 0, 2),
            }

        except Exception as e:
            _logger.error("Check-out error: %s", e, exc_info=True)
            return {'success': False, 'message': f'Lỗi: {str(e)}'}

    def _validate_ip(self, ip_address, allowed_range):
        """Validate IP address against allowed range. Returns (is_valid, error_message)."""
        import ipaddress
        try:
            network = ipaddress.ip_network(allowed_range, strict=False)
            if ipaddress.ip_address(ip_address) not in network:
                return False, f'IP {ip_address} không nằm trong dải cho phép {allowed_range}'
            return True, None
        except ValueError as e:
            _logger.warning("Invalid IP range config: %s", e)
            return True, None  # Allow if config is invalid

    def _validate_gps(self, lat, lng, allowed_lat, allowed_lng, radius_meters):
        """Validate GPS coordinates against allowed location. Returns (is_valid, error_message)."""
        import math
        R = 6371000  # Earth radius in meters
        phi1, phi2 = math.radians(allowed_lat), math.radians(lat)
        dphi = math.radians(lat - allowed_lat)
        dlambda = math.radians(lng - allowed_lng)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        if distance > radius_meters:
            return False, f'Vị trí cách xa {distance:.0f}m (tối đa {radius_meters}m)'
        return True, None
