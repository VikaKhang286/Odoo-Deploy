from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    access_token = fields.Char(string='Access Token Chính')
    webhook_secret = fields.Char(string='Webhook Secret')
    token_check_status = fields.Selection(
        selection=lambda self: self.env['pancake.sync.dashboard'].TOKEN_STATUS_SELECTION,
        string='Trạng thái token',
        readonly=True,
    )
    token_check_message = fields.Text(string='Thông điệp token gần nhất', readonly=True)
    token_check_at = fields.Datetime(string='Lần kiểm tra token gần nhất', readonly=True)
    token_check_page_count = fields.Integer(string='Số page từ token', readonly=True)
    bulk_sync_preset_id = fields.Many2one('pancake.bulk.sync.preset', string='Preset đồng bộ toàn bộ')
    sync_batch_size = fields.Integer(string='Batch Size', default=50)
    smart_recent_days = fields.Integer(string='Số ngày smart sync', default=3)
    deep_recent_days = fields.Integer(string='Số ngày deep sync', default=7)
    circuit_breaker_pause_minutes = fields.Integer(string='Số phút circuit breaker', default=15)
    stale_timeout_minutes = fields.Integer(string='Ngưỡng coi job gián đoạn', default=10)
    continuous_sync_active = fields.Boolean(string='Bật đồng bộ liên tục')
    runner_active = fields.Boolean(string='Bật cron runner')
    runner_interval_number = fields.Integer(string='Chu kỳ cron runner', default=1)
    runner_interval_type = fields.Selection(
        selection=lambda self: self.env['pancake.bulk.sync.dashboard'].INTERVAL_TYPES,
        string='Đơn vị cron runner',
        default='minutes',
    )

    @api.model
    def _dashboard_service(self):
        return self.env['pancake.sync.dashboard']

    @api.model
    def _bulk_dashboard_service(self):
        return self.env['pancake.bulk.sync.dashboard']

    @api.model
    def get_values(self):
        res = super().get_values()
        values = self._dashboard_service()._build_dashboard_values()
        bulk_values = self._bulk_dashboard_service()._build_dashboard_values()
        res.update({
            'access_token': values.get('access_token', ''),
            'webhook_secret': values.get('webhook_secret', ''),
            'token_check_status': values.get('token_check_status', False),
            'token_check_message': values.get('token_check_message', False),
            'token_check_at': values.get('token_check_at', False),
            'token_check_page_count': values.get('token_check_page_count', 0),
            'bulk_sync_preset_id': bulk_values.get('preset_id', False),
            'sync_batch_size': values.get('sync_batch_size', 50),
            'smart_recent_days': values.get('smart_recent_days', 3),
            'deep_recent_days': values.get('deep_recent_days', 7),
            'circuit_breaker_pause_minutes': values.get('circuit_breaker_pause_minutes', 15),
            'continuous_sync_active': values.get('continuous_sync_active', False),
            'stale_timeout_minutes': bulk_values.get('stale_timeout_minutes', 10),
            'runner_active': bulk_values.get('runner_active', True),
            'runner_interval_number': bulk_values.get('runner_interval_number', 1),
            'runner_interval_type': bulk_values.get('runner_interval_type', 'minutes'),
        })
        return res

    def set_values(self):
        super().set_values()
        for rec in self:
            rec._validate_pancake_settings()
            dashboard = rec.env['pancake.sync.dashboard']._get_dashboard_record()
            dashboard.write({
                'access_token': rec.access_token or '',
                'webhook_secret': rec.webhook_secret or '',
                'sync_batch_size': rec.sync_batch_size,
                'smart_recent_days': rec.smart_recent_days,
                'deep_recent_days': rec.deep_recent_days,
                'circuit_breaker_pause_minutes': rec.circuit_breaker_pause_minutes,
                'continuous_sync_active': rec.continuous_sync_active,
            })
            dashboard._write_configuration_params()
            dashboard._write_cron_configuration()
            bulk_dashboard = rec.env['pancake.bulk.sync.dashboard']._get_dashboard_record()
            bulk_dashboard.write({
                'access_token': rec.access_token or '',
                'sync_batch_size': rec.sync_batch_size,
                'smart_recent_days': rec.smart_recent_days,
                'deep_recent_days': rec.deep_recent_days,
                'circuit_breaker_pause_minutes': rec.circuit_breaker_pause_minutes,
                'preset_id': rec.bulk_sync_preset_id.id if rec.bulk_sync_preset_id else False,
                'preset_description': rec.bulk_sync_preset_id.description if rec.bulk_sync_preset_id else False,
                'stale_timeout_minutes': rec.stale_timeout_minutes,
                'runner_active': rec.runner_active,
                'runner_interval_number': rec.runner_interval_number,
                'runner_interval_type': rec.runner_interval_type,
            })
            bulk_dashboard._write_configuration_params()
            bulk_dashboard._write_runner_configuration()

    def _validate_pancake_settings(self):
        validations = [
            (self.sync_batch_size, 'Batch size phải lớn hơn hoặc bằng 1.'),
            (self.smart_recent_days, 'Số ngày smart sync phải lớn hơn hoặc bằng 1.'),
            (self.deep_recent_days, 'Số ngày deep sync phải lớn hơn hoặc bằng 1.'),
            (self.circuit_breaker_pause_minutes, 'Số phút circuit breaker phải lớn hơn hoặc bằng 1.'),
            (self.stale_timeout_minutes, 'Ngưỡng coi job gián đoạn phải lớn hơn hoặc bằng 1.'),
            (self.runner_interval_number, 'Chu kỳ cron runner phải lớn hơn hoặc bằng 1.'),
        ]
        for value, message in validations:
            if value < 1:
                raise ValidationError(message)

    def action_open_pancake_dashboard(self):
        return self.env['pancake.sync.dashboard'].action_open_dashboard()
