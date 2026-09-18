# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class AttendanceReport(models.Model):
    """
    Custom attendance reporting model with extended fields.
    """
    _name = 'dac.attendance.report'
    _description = 'Attendance Report'
    _auto = False
    _table = 'dac_attendance_report'
    _order = 'check_in_date desc, employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    check_in_date = fields.Date(string='Check-in Date', readonly=True)
    check_in = fields.Datetime(string='Check-in Time', readonly=True)
    check_out = fields.Datetime(string='Check-out Time', readonly=True)
    worked_hours = fields.Float(string='Worked Hours', readonly=True)
    
    # Extended fields
    check_in_latitude = fields.Float(string='Check-in Latitude', readonly=True, digits=(10, 7))
    check_in_longitude = fields.Float(string='Check-in Longitude', readonly=True, digits=(10, 7))
    gps_validated = fields.Boolean(string='GPS Validated', readonly=True)
    wifi_validated = fields.Boolean(string='WiFi Validated', readonly=True)
    ip_validated = fields.Boolean(string='IP Validated', readonly=True)
    photo_validated = fields.Boolean(string='Photo Validated', readonly=True)
    
    is_late = fields.Boolean(string='Late', readonly=True)
    is_early_leave = fields.Boolean(string='Early Leave', readonly=True)
    late_minutes = fields.Integer(string='Late Minutes', readonly=True)
    
    # Employee info for reporting
    employee_barcode = fields.Char(string='Badge ID', related='employee_id.barcode', readonly=True)
    employee_work_email = fields.Char(string='Work Email', related='employee_id.work_email', readonly=True)

    def init(self):
        """Create the view for attendance report."""
        self._cr.execute(f"DROP VIEW IF EXISTS {self._table}")
        
        # Create view for attendance with geolocation data
        self._cr.execute(f'''
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    a.id,
                    a.employee_id,
                    e.department_id,
                    DATE(a.check_in) as check_in_date,
                    a.check_in,
                    a.check_out,
                    a.worked_hours,
                    a.check_in_latitude,
                    a.check_in_longitude,
                    a.gps_validated,
                    a.wifi_validated,
                    a.ip_validated,
                    a.photo_validated,
                    a.is_late,
                    a.is_early_leave,
                    a.late_minutes
                FROM hr_attendance a
                LEFT JOIN hr_employee e ON a.employee_id = e.id
            )
        ''')

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, order=False, lazy=True):
        """
        Extended read_group with computed late/early statistics.
        """
        result = super().read_group(domain, fields, groupby, offset, limit, order, lazy)
        
        # Add summary statistics if grouping by date
        if 'check_in_date' in groupby:
            for line in result:
                if '__domain' in line:
                    records = self.search(line['__domain'])
                    late_count = sum(1 for r in records if r.is_late)
                    early_count = sum(1 for r in records if r.is_early_leave)
                    line['late_count'] = late_count
                    line['early_count'] = early_count
        
        return result


class AttendanceSummaryWizard(models.TransientModel):
    """
    Wizard to generate attendance summary report.
    """
    _name = 'dac.attendance.summary.wizard'
    _description = 'Attendance Summary Wizard'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Leave empty for all employees'
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=lambda self: fields.Date.today(),
    )
    include_late = fields.Boolean(
        string='Include Late Employees',
        default=True,
    )
    include_early = fields.Boolean(
        string='Include Early Leave',
        default=True,
    )
    group_by = fields.Selection([
        ('employee', 'Employee'),
        ('department', 'Department'),
        ('date', 'Date'),
    ], string='Group By', default='employee')

    def action_generate_report(self):
        """
        Generate attendance summary report.
        """
        self.ensure_one()
        
        domain = [
            ('check_in_date', '>=', self.date_from),
            ('check_in_date', '<=', self.date_to),
        ]
        
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        
        if self.include_late:
            domain.append(('is_late', '=', True))
        
        if self.include_early:
            domain.append(('is_early_leave', '=', True))
        
        # Return action to open report
        return {
            'name': 'Attendance Summary',
            'type': 'ir.actions.act_window',
            'res_model': 'dac.attendance.report',
            'view_mode': 'pivot,tree',
            'domain': domain,
            'context': {
                'search_default_group_by_employee': 1 if self.group_by == 'employee' else 0,
                'search_default_group_by_department': 1 if self.group_by == 'department' else 0,
                'search_default_group_by_check_in_date': 1 if self.group_by == 'date' else 0,
            },
        }
