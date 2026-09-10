from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PancakeBulkSyncPreset(models.Model):
    _name = 'pancake.bulk.sync.preset'
    _description = 'Mẫu cấu hình đồng bộ toàn bộ Pancake'
    _order = 'sequence asc, id asc'

    PRESET_TYPE_SELECTION = [
        ('system', 'Mẫu hệ thống'),
        ('custom', 'Mẫu tùy chỉnh'),
    ]

    INTERVAL_TYPES = [
        ('minutes', 'Phút'),
        ('hours', 'Giờ'),
        ('days', 'Ngày'),
        ('weeks', 'Tuần'),
        ('months', 'Tháng'),
    ]

    name = fields.Char(string='Tên mẫu', required=True)
    description = fields.Text(string='Mô tả')
    preset_type = fields.Selection(PRESET_TYPE_SELECTION, string='Loại mẫu', required=True, default='custom', index=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(string='Đang hoạt động', default=True)
    sync_batch_size = fields.Integer(string='Số hội thoại mỗi batch', default=50, required=True)
    smart_recent_days = fields.Integer(string='Cửa sổ Smart Sync (ngày)', default=3, required=True)
    deep_recent_days = fields.Integer(string='Cửa sổ Deep Sync (ngày)', default=7, required=True)
    circuit_breaker_pause_minutes = fields.Integer(string='Thời gian nghỉ sau lỗi liên tiếp (phút)', default=15, required=True)
    runner_interval_number = fields.Integer(string='Chu kỳ runner', default=1, required=True)
    runner_interval_type = fields.Selection(INTERVAL_TYPES, string='Đơn vị runner', default='minutes', required=True)
    stale_timeout_minutes = fields.Integer(string='Ngưỡng coi job gián đoạn (phút)', default=10, required=True)
    is_default_for_bulk_sync = fields.Boolean(string='Mặc định cho đồng bộ toàn bộ')

    _sql_constraints = [
        ('pancake_bulk_sync_preset_name_uniq', 'unique(name)', 'Tên mẫu cấu hình phải là duy nhất.'),
    ]

    @api.constrains(
        'sync_batch_size',
        'smart_recent_days',
        'deep_recent_days',
        'circuit_breaker_pause_minutes',
        'runner_interval_number',
        'stale_timeout_minutes',
    )
    def _check_positive_values(self):
        for record in self:
            validations = [
                (record.sync_batch_size, _('Số hội thoại mỗi batch phải lớn hơn hoặc bằng 1.')),
                (record.smart_recent_days, _('Cửa sổ Smart Sync phải lớn hơn hoặc bằng 1 ngày.')),
                (record.deep_recent_days, _('Cửa sổ Deep Sync phải lớn hơn hoặc bằng 1 ngày.')),
                (record.circuit_breaker_pause_minutes, _('Thời gian nghỉ sau lỗi phải lớn hơn hoặc bằng 1 phút.')),
                (record.runner_interval_number, _('Chu kỳ runner phải lớn hơn hoặc bằng 1.')),
                (record.stale_timeout_minutes, _('Ngưỡng coi job gián đoạn phải lớn hơn hoặc bằng 1 phút.')),
            ]
            for value, message in validations:
                if value < 1:
                    raise ValidationError(message)

    @api.constrains('is_default_for_bulk_sync', 'active')
    def _check_single_default(self):
        defaults = self.search([
            ('id', 'not in', self.ids),
            ('is_default_for_bulk_sync', '=', True),
            ('active', '=', True),
        ], limit=1)
        if defaults and any(record.is_default_for_bulk_sync and record.active for record in self):
            raise ValidationError(_('Chỉ được phép có một mẫu mặc định cho đồng bộ toàn bộ.'))

    @api.model
    def _get_default_preset(self):
        preset = self.search([('is_default_for_bulk_sync', '=', True), ('active', '=', True)], limit=1)
        if preset:
            return preset
        return self.search([('active', '=', True)], order='sequence asc, id asc', limit=1)

    def _to_dashboard_values(self):
        self.ensure_one()
        return {
            'preset_id': self.id,
            'sync_batch_size': self.sync_batch_size,
            'smart_recent_days': self.smart_recent_days,
            'deep_recent_days': self.deep_recent_days,
            'circuit_breaker_pause_minutes': self.circuit_breaker_pause_minutes,
            'runner_interval_number': self.runner_interval_number,
            'runner_interval_type': self.runner_interval_type,
            'stale_timeout_minutes': self.stale_timeout_minutes,
        }

    def write(self, vals):
        if any(record.preset_type == 'system' for record in self):
            protected_fields = {
                'sync_batch_size',
                'smart_recent_days',
                'deep_recent_days',
                'circuit_breaker_pause_minutes',
                'runner_interval_number',
                'runner_interval_type',
                'stale_timeout_minutes',
                'preset_type',
            }
            if protected_fields.intersection(vals.keys()):
                raise UserError(_('Không thể sửa thông số của mẫu hệ thống.'))
        return super().write(vals)

    def unlink(self):
        if any(record.preset_type == 'system' for record in self):
            raise UserError(_('Không thể xóa mẫu hệ thống.'))
        return super().unlink()
