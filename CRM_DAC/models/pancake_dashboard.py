import logging
from datetime import timedelta
import pytz
from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PancakeSyncDashboard(models.TransientModel):
    _name = 'pancake.sync.dashboard'
    _description = 'Bảng điều khiển đồng bộ liên tục Pancake'

    TOKEN_STATUS_SELECTION = [
        ('valid', 'Hợp lệ'),
        ('expired', 'Hết hạn'),
        ('invalid', 'Không hợp lệ'),
        ('network_error', 'Lỗi mạng'),
        ('unknown_error', 'Lỗi chưa phân loại'),
    ]

    PARAM_ACCESS_TOKEN = 'page_fm.access_token'
    PARAM_ACCESS_TOKEN_COMPAT = 'pages_fm_main_access_token'
    PARAM_WEBHOOK_SECRET = 'pancake.webhook_secret_key'
    PARAM_BATCH_SIZE = 'pancake.sync_batch_size'
    PARAM_SAME_DAY_INTERVAL = 'pancake.same_day_sync_interval_minutes'
    PARAM_NIGHTLY_RUN_TIME = 'pancake.nightly_two_day_sync_time'
    PARAM_CONTINUOUS_TIMEZONE = 'pancake.continuous_sync_timezone'
    PARAM_LOG_RETENTION_DAYS = 'pancake.message_sync_log_retention_days'
    PARAM_SMART_RECENT_DAYS = 'pancake.smart_sync_recent_days'
    PARAM_DEEP_RECENT_DAYS = 'pancake.deep_sync_recent_days'
    PARAM_CIRCUIT_BREAKER_MINUTES = 'pancake.circuit_breaker_pause_minutes'
    PARAM_POINTER = 'pancake.last_conv_id'
    PARAM_CIRCUIT_UNTIL = 'page_fm_circuit_breaker_until'

    CONTINUOUS_CRON_FIELDS = (
        ('quick_sync', 'CRM_DAC.cron_pancake_quick_sync'),
        ('smart_sync', 'CRM_DAC.cron_pancake_smart_message_sync'),
        ('deep_sync', 'CRM_DAC.cron_pancake_deep_sync_continuous'),
    )
    RETIRED_FULL_SYNC_XML_ID = 'CRM_DAC.cron_pancake_full_sync'

    INTERVAL_TYPES = [
        ('minutes', 'Phút'),
        ('hours', 'Giờ'),
        ('days', 'Ngày'),
        ('weeks', 'Tuần'),
        ('months', 'Tháng'),
    ]

    access_token = fields.Char(string='Access Token chính')
    webhook_secret = fields.Char(string='Webhook Secret')
    sync_batch_size = fields.Integer(string='Số hội thoại mỗi batch', default=50)
    same_day_sync_interval_minutes = fields.Integer(string='Quét tin nhắn trong ngày mỗi (phút)', default=10)
    nightly_two_day_sync_time = fields.Char(string='Quét cuối ngày 2 ngày gần nhất lúc', default='23:30')
    continuous_sync_timezone = fields.Char(string='Timezone đồng bộ liên tục', readonly=True)
    sync_log_retention_days = fields.Integer(string='Tự xóa log sau (ngày)', default=30)
    smart_recent_days = fields.Integer(string='Cửa sổ ưu tiên Smart Sync (ngày)', default=3)
    deep_recent_days = fields.Integer(string='Cửa sổ quét Deep Sync (ngày)', default=7)
    circuit_breaker_pause_minutes = fields.Integer(string='Thời gian nghỉ sau lỗi liên tiếp (phút)', default=15)

    token_configured = fields.Boolean(string='Đã cấu hình token', readonly=True)
    webhook_configured = fields.Boolean(string='Đã cấu hình webhook secret', readonly=True)
    token_check_status = fields.Selection(TOKEN_STATUS_SELECTION, string='Trạng thái token', readonly=True)
    token_check_message = fields.Text(string='Thông điệp token gần nhất', readonly=True)
    token_check_at = fields.Datetime(string='Thời điểm kiểm tra token', readonly=True)
    token_check_page_count = fields.Integer(string='Số page từ token', readonly=True)
    cached_page_token_count = fields.Integer(string='Số token page đang cache', readonly=True)
    page_count = fields.Integer(string='Page active', readonly=True)
    selected_page_count = fields.Integer(string='Page đã chọn', readonly=True)
    unselected_page_count = fields.Integer(string='Page chưa chọn', readonly=True)
    conversation_count = fields.Integer(string='Cuộc trò chuyện', readonly=True)
    message_count = fields.Integer(string='Tin nhắn', readonly=True)
    unread_conversation_count = fields.Integer(string='Cuộc trò chuyện chưa đọc', readonly=True)
    require_processing_count = fields.Integer(string='Cuộc trò chuyện cần xử lý', readonly=True)
    never_synced_conversation_count = fields.Integer(string='Cuộc trò chuyện chưa sync tin nhắn', readonly=True)
    last_message_sync_at = fields.Datetime(string='Lần sync tin nhắn gần nhất', readonly=True)
    last_conversation_update_at = fields.Datetime(string='Lần cập nhật cuộc trò chuyện gần nhất', readonly=True)
    circuit_breaker_until = fields.Datetime(string='Circuit breaker đến', readonly=True)
    last_conv_pointer = fields.Integer(string='Pointer hiện tại', readonly=True)

    continuous_sync_active = fields.Boolean(string='Bật đồng bộ liên tục')
    quick_sync_interval_number = fields.Integer(string='Chu kỳ pha 1', default=10)
    quick_sync_interval_type = fields.Selection(INTERVAL_TYPES, string='Đơn vị pha 1', default='minutes')
    quick_sync_nextcall = fields.Datetime(string='Lần chạy tiếp theo của pha 1', readonly=True)
    smart_sync_interval_number = fields.Integer(string='Chu kỳ pha 2', default=10)
    smart_sync_interval_type = fields.Selection(INTERVAL_TYPES, string='Đơn vị pha 2', default='minutes')
    smart_sync_nextcall = fields.Datetime(string='Lần chạy tiếp theo của pha 2', readonly=True)
    deep_sync_interval_number = fields.Integer(string='Chu kỳ pha 3', default=2)
    deep_sync_interval_type = fields.Selection(INTERVAL_TYPES, string='Đơn vị pha 3', default='hours')
    deep_sync_nextcall = fields.Datetime(string='Lần chạy tiếp theo của pha 3', readonly=True)

    active_job_id = fields.Many2one('pancake.message.sync.job', string='Job đồng bộ toàn bộ hiện tại', readonly=True)
    active_job_state = fields.Char(string='Trạng thái job', readonly=True)
    active_job_phase = fields.Char(string='Pha hiện tại của job', readonly=True)
    active_job_progress = fields.Float(string='Tiến độ tổng (%)', readonly=True, digits=(16, 2))
    active_job_phase_progress = fields.Float(string='Tiến độ pha hiện tại (%)', readonly=True, digits=(16, 2))
    active_job_started_at = fields.Datetime(string='Job bắt đầu lúc', readonly=True)
    active_job_finished_at = fields.Datetime(string='Job kết thúc lúc', readonly=True)
    active_job_processed_page_count = fields.Integer(string='Page đã xử lý', readonly=True)
    active_job_current_page_name = fields.Char(string='Page hiện tại của job', readonly=True)
    active_job_synced_conversation_count = fields.Integer(string='Conversation đã sync trong job', readonly=True)
    active_job_total_conversation_count = fields.Integer(string='Tổng conversation mục tiêu của job', readonly=True)
    active_job_total_messages_created = fields.Integer(string='Tin nhắn mới tạo trong job', readonly=True)
    active_job_last_log_message = fields.Text(string='Log cuối của job', readonly=True)
    candidate_refresh_last_run_at = fields.Datetime(string='Lần cập nhật hội thoại mới gần nhất', readonly=True)
    candidate_refresh_conversations_checked = fields.Integer(string='Số hội thoại metadata đã cập nhật', readonly=True)
    candidate_refresh_error_count = fields.Integer(string='Lỗi cập nhật hội thoại mới', readonly=True)
    same_day_last_run_at = fields.Datetime(string='Lần quét tin nhắn trong ngày gần nhất', readonly=True)
    same_day_conversations_checked = fields.Integer(string='Số hội thoại đã quét trong ngày', readonly=True)
    same_day_messages_created = fields.Integer(string='Số tin nhắn mới tạo trong ngày', readonly=True)
    same_day_error_count = fields.Integer(string='Lỗi quét trong ngày', readonly=True)
    nightly_two_day_last_run_at = fields.Datetime(string='Lần quét cuối ngày gần nhất', readonly=True)
    nightly_two_day_conversations_checked = fields.Integer(string='Số hội thoại đã quét cuối ngày', readonly=True)
    nightly_two_day_messages_created = fields.Integer(string='Số tin nhắn mới tạo cuối ngày', readonly=True)
    nightly_two_day_error_count = fields.Integer(string='Lỗi quét cuối ngày', readonly=True)
    recent_sync_error_count = fields.Integer(string='Số lỗi sync 7 ngày gần đây', readonly=True)
    latest_sync_error_at = fields.Datetime(string='Lỗi sync gần nhất lúc', readonly=True)
    latest_sync_error_message = fields.Text(string='Lỗi sync gần nhất', readonly=True)
    conversations_synced_today = fields.Integer(string='Số cuộc hội thoại có tin nhắn mới hôm nay', readonly=True)
    messages_synced_today = fields.Integer(string='Số tin nhắn mới hôm nay', readonly=True)
    latest_successful_sync_at = fields.Datetime(string='Lần đồng bộ thành công gần nhất', readonly=True)
    sync_error_status = fields.Char(string='Trạng thái lỗi đồng bộ', readonly=True)
    today_customer_sync_html = fields.Html(string='Khách hàng hôm nay', readonly=True, sanitize=False)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.update(self._build_dashboard_values())
        return values

    @api.model
    def _get_dashboard_record(self):
        dashboard = self.search([('create_uid', '=', self.env.uid)], order='id desc', limit=1)
        values = self._build_dashboard_values()
        if dashboard:
            dashboard.write(values)
            return dashboard
        return self.create(values)

    @api.model
    def _build_open_dashboard_action(self, dashboard):
        form_view = self.env.ref('CRM_DAC.view_pancake_sync_dashboard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Continuous Sync Pancake'),
            'res_model': self._name,
            'res_id': dashboard.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'current',
        }

    def _refresh_dashboard_record(self):
        self.ensure_one()
        self.write(self._build_dashboard_values())
        return self

    @api.model
    def _build_reload_action(self):
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def action_open_dashboard(self):
        dashboard = self._get_dashboard_record()
        return self._build_open_dashboard_action(dashboard)

    @api.model
    def _get_icp(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _get_int_param(self, key, default):
        raw_value = self._get_icp().get_param(key)
        if raw_value is False or raw_value is None or str(raw_value).strip() == '':
            return default
        try:
            val = int(raw_value)
            if key != self.PARAM_POINTER and val <= 0:
                return default
            return val
        except (TypeError, ValueError):
            return default


    @api.model
    def _get_datetime_param(self, key):
        raw_value = self._get_icp().get_param(key)
        if not raw_value:
            return False
        try:
            return fields.Datetime.to_datetime(raw_value)
        except Exception:
            return False

    @api.model
    def _get_layer_stat_prefix(self, layer_key):
        return f'pancake.{layer_key}'

    @api.model
    def _get_layer_stat_values(self, layer_key):
        prefix = self._get_layer_stat_prefix(layer_key)
        values = {
            f'{layer_key}_last_run_at': self._get_datetime_param(f'{prefix}.last_run_at'),
            f'{layer_key}_conversations_checked': self._get_int_param(f'{prefix}.conversations_checked', 0),
            f'{layer_key}_error_count': self._get_int_param(f'{prefix}.error_count', 0),
        }
        if layer_key in ('same_day', 'nightly_two_day'):
            values[f'{layer_key}_messages_created'] = self._get_int_param(f'{prefix}.messages_created', 0)
        return values

    @api.model
    def _get_cron_record(self, xml_id):
        cron = self.env.ref(xml_id, raise_if_not_found=False)
        return cron.sudo() if cron else cron

    @api.model
    def _build_dashboard_values(self):
        values = {
            'access_token': self._get_icp().get_param(self.PARAM_ACCESS_TOKEN) or '',
            'webhook_secret': self._get_icp().get_param(self.PARAM_WEBHOOK_SECRET) or '',
            'sync_batch_size': self._get_int_param(self.PARAM_BATCH_SIZE, 50),
            'same_day_sync_interval_minutes': self._get_int_param(self.PARAM_SAME_DAY_INTERVAL, 10),
            'nightly_two_day_sync_time': self._get_icp().get_param(self.PARAM_NIGHTLY_RUN_TIME) or '23:30',
            'continuous_sync_timezone': self._get_icp().get_param(self.PARAM_CONTINUOUS_TIMEZONE) or 'Asia/Ho_Chi_Minh',
            'sync_log_retention_days': self._get_int_param(self.PARAM_LOG_RETENTION_DAYS, 30),
            'smart_recent_days': self._get_int_param(self.PARAM_SMART_RECENT_DAYS, 3),
            'deep_recent_days': self._get_int_param(self.PARAM_DEEP_RECENT_DAYS, 7),
            'circuit_breaker_pause_minutes': self._get_int_param(self.PARAM_CIRCUIT_BREAKER_MINUTES, 15),
            'last_conv_pointer': self._get_int_param(self.PARAM_POINTER, 0),
            'circuit_breaker_until': self._get_datetime_param(self.PARAM_CIRCUIT_UNTIL),
        }
        values.update(self._get_health_values())
        values.update(self._get_continuous_values())
        values.update(self._get_full_message_job_values())
        values.update(self._get_log_values())
        values.update(self._get_layer_stat_values('candidate_refresh'))
        values.update(self._get_layer_stat_values('same_day'))
        values.update(self._get_layer_stat_values('nightly_two_day'))
        return values

    @api.model
    def _get_health_values(self):
        page_model = self.env['page.fm.page'].sudo()
        conversation_model = self.env['page.fm.conversation'].sudo()
        message_model = self.env['page.fm.message'].sudo()
        icp = self._get_icp()

        last_sync_conv = conversation_model.search(
            [('last_message_sync_fm', '!=', False)],
            order='last_message_sync_fm desc, id desc',
            limit=1,
        )
        last_update_conv = conversation_model.search(
            [('updated_at_fm', '!=', False)],
            order='updated_at_fm desc, id desc',
            limit=1,
        )
        cached_token_count = icp.search_count([('key', '=like', 'page_token_time_%')])
        page_total = page_model._get_active_page_count()
        selected_page_count = page_model.search_count(page_model._selected_page_domain())

        return {
            'token_configured': bool(icp.get_param(self.PARAM_ACCESS_TOKEN)),
            'webhook_configured': bool(icp.get_param(self.PARAM_WEBHOOK_SECRET)),
            'token_check_status': icp.get_param(page_model.PARAM_TOKEN_CHECK_STATUS) or False,
            'token_check_message': icp.get_param(page_model.PARAM_TOKEN_CHECK_MESSAGE) or False,
            'token_check_at': self._get_datetime_param(page_model.PARAM_TOKEN_CHECK_AT),
            'token_check_page_count': self._get_int_param(page_model.PARAM_TOKEN_CHECK_PAGE_COUNT, 0),
            'cached_page_token_count': cached_token_count,
            'page_count': page_total,
            'selected_page_count': selected_page_count,
            'unselected_page_count': max(page_total - selected_page_count, 0),
            'conversation_count': conversation_model.search_count([('page_fm_page_id.active', '=', True)]),
            'message_count': message_model.search_count([]),
            'unread_conversation_count': conversation_model.search_count([
                ('page_fm_page_id.active', '=', True),
                ('is_unread_fm', '=', True),
            ]),
            'require_processing_count': conversation_model.search_count([
                ('page_fm_page_id.active', '=', True),
                ('require_processing', '=', True),
            ]),
            'never_synced_conversation_count': conversation_model.search_count([
                ('page_fm_page_id.active', '=', True),
                ('last_message_sync_fm', '=', False),
            ]),
            'last_message_sync_at': last_sync_conv.last_message_sync_fm if last_sync_conv else False,
            'last_conversation_update_at': last_update_conv.updated_at_fm if last_update_conv else False,
        }

    @api.model
    def _get_continuous_values(self):
        values = {'continuous_sync_active': True}
        active_flags = []
        for prefix, xml_id in self.CONTINUOUS_CRON_FIELDS:
            cron = self._get_cron_record(xml_id)
            active_flags.append(bool(cron and cron.active))
            values.update({
                f'{prefix}_interval_number': cron.interval_number if cron else 1,
                f'{prefix}_interval_type': cron.interval_type if cron else 'hours',
                f'{prefix}_nextcall': cron.nextcall if cron else False,
            })
        values['continuous_sync_active'] = all(active_flags) if active_flags else False
        return values

    @api.model
    def _build_today_customer_sync_html(self, synced_message_domain, limit=20):
        message_model = self.env['page.fm.message'].sudo()
        conversation_model = self.env['page.fm.conversation'].sudo()
        grouped_rows = message_model.read_group(
            synced_message_domain + [('conversation_id', '!=', False)],
            ['conversation_id'],
            ['conversation_id'],
            lazy=False,
        )
        if not grouped_rows:
            return (
                "<div class='o_pancake_sync_customer_empty'>"
                "Chưa có tin nhắn đồng bộ hôm nay."
                "</div>"
            )

        conversation_ids = [
            row.get('conversation_id')[0]
            for row in grouped_rows
            if row.get('conversation_id')
        ]
        conversation_map = {
            conversation.id: conversation
            for conversation in conversation_model.browse(conversation_ids).exists()
        }
        sorted_rows = sorted(
            grouped_rows,
            key=lambda row: row.get('conversation_id_count') or row.get('__count') or 0,
            reverse=True,
        )[:limit]

        table_rows = []
        for row in sorted_rows:
            conversation_data = row.get('conversation_id')
            if not conversation_data:
                continue
            conversation_id = conversation_data[0]
            conversation = conversation_map.get(conversation_id)
            customer_name = (
                conversation.partner_id.display_name
                if conversation and conversation.partner_id
                else (
                    conversation.customer_name_fm
                    if conversation and conversation.customer_name_fm
                    else f"Conversation #{conversation_id}"
                )
            )
            message_count = row.get('conversation_id_count') or row.get('__count') or 0
            table_rows.append(
                "<tr>"
                f"<td>{escape(customer_name)}</td>"
                f"<td class='text-end'>{int(message_count)}</td>"
                "</tr>"
            )

        if not table_rows:
            return (
                "<div class='o_pancake_sync_customer_empty'>"
                "Chưa có tin nhắn đồng bộ hôm nay."
                "</div>"
            )

        return (
            "<div class='o_pancake_sync_customer_box'>"
            "<table class='table table-sm table-hover o_pancake_sync_customer_table'>"
            "<thead><tr><th>Khách hàng</th><th class='text-end'>Số tin</th></tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody>"
            "</table>"
            "</div>"
        )

    @api.model
    def _get_log_values(self):
        log_model = self.env['pancake.message.sync.log'].sudo()
        conversation_model = self.env['page.fm.conversation'].sudo()
        message_model = self.env['page.fm.message'].sudo()
        recent_cutoff = fields.Datetime.now() - timedelta(days=7)
        recent_error_domain = [('level', '=', 'error'), ('logged_at', '>=', recent_cutoff)]
        latest_error = log_model.search([('level', '=', 'error')], order='logged_at desc, id desc', limit=1)
        today_stats = conversation_model._compute_sync_window_stats('same_day')
        window_end_exclusive = fields.Datetime.to_string(
            (today_stats['window_end'] + timedelta(seconds=1)).replace(tzinfo=None)
        )
        message_today_domain = [
            ('inserted_at_fm', '>=', today_stats['window_start_str']),
            ('inserted_at_fm', '<', window_end_exclusive),
        ]
        conversation_rows = message_model.read_group(
            message_today_domain + [('conversation_id', '!=', False)],
            ['conversation_id'],
            ['conversation_id'],
            lazy=False,
        )
        latest_successful_conversation = conversation_model.search(
            [('last_successful_message_sync_at', '!=', False)],
            order='last_successful_message_sync_at desc, id desc',
            limit=1,
        )
        recent_error_count = log_model.search_count(recent_error_domain)
        return {
            'recent_sync_error_count': recent_error_count,
            'latest_sync_error_at': latest_error.logged_at if latest_error else False,
            'latest_sync_error_message': latest_error.message if latest_error else False,
            'conversations_synced_today': len([row for row in conversation_rows if row.get('conversation_id')]),
            'messages_synced_today': message_model.search_count(message_today_domain),
            'latest_successful_sync_at': latest_successful_conversation.last_successful_message_sync_at if latest_successful_conversation else False,
            'sync_error_status': 'Có lỗi gần đây' if recent_error_count else 'Ổn định',
            'today_customer_sync_html': self._build_today_customer_sync_html(message_today_domain),
        }

    @api.model
    def _get_full_message_job_values(self):
        values = {
            'active_job_id': False,
            'active_job_state': False,
            'active_job_phase': False,
            'active_job_progress': 0.0,
            'active_job_phase_progress': 0.0,
            'active_job_started_at': False,
            'active_job_finished_at': False,
            'active_job_processed_page_count': 0,
            'active_job_current_page_name': False,
            'active_job_synced_conversation_count': 0,
            'active_job_total_conversation_count': 0,
            'active_job_total_messages_created': 0,
            'active_job_last_log_message': False,
        }
        job_model = self.env['pancake.message.sync.job'].sudo()
        job = job_model._get_running_job() or job_model._get_latest_job()
        if not job:
            return values
        values.update({
            'active_job_id': job.id,
            'active_job_state': job._selection_label('state', job.state),
            'active_job_phase': job._selection_label('phase', job.phase),
            'active_job_progress': job.progress_percent,
            'active_job_phase_progress': job.phase_progress_percent,
            'active_job_started_at': job.started_at,
            'active_job_finished_at': job.finished_at,
            'active_job_processed_page_count': job.processed_page_count,
            'active_job_current_page_name': job.current_page_name,
            'active_job_synced_conversation_count': job.synced_conversation_count,
            'active_job_total_conversation_count': job.total_conversation_count,
            'active_job_total_messages_created': job.total_messages_created,
            'active_job_last_log_message': job.last_log_message,
        })
        return values

    def _validate_inputs(self):
        self.ensure_one()
        validations = [
            (self.sync_batch_size, 'Số hội thoại mỗi batch phải lớn hơn hoặc bằng 1.'),
            (self.same_day_sync_interval_minutes, 'Chu kỳ quét tin nhắn trong ngày phải lớn hơn hoặc bằng 1 phút.'),
            (self.sync_log_retention_days, 'Số ngày giữ log phải lớn hơn hoặc bằng 1.'),
            (self.smart_recent_days, 'Số ngày smart sync phải lớn hơn hoặc bằng 1.'),
            (self.deep_recent_days, 'Số ngày deep sync phải lớn hơn hoặc bằng 1.'),
            (self.circuit_breaker_pause_minutes, 'Số phút circuit breaker phải lớn hơn hoặc bằng 1.'),
            (self.quick_sync_interval_number, 'Chu kỳ pha 1 phải lớn hơn hoặc bằng 1.'),
            (self.smart_sync_interval_number, 'Chu kỳ pha 2 phải lớn hơn hoặc bằng 1.'),
            (self.deep_sync_interval_number, 'Chu kỳ pha 3 phải lớn hơn hoặc bằng 1.'),
        ]
        for value, message in validations:
            if value < 1:
                raise ValidationError(message)
        try:
            hours, minutes = [int(part) for part in (self.nightly_two_day_sync_time or '').split(':', 1)]
        except Exception:
            raise ValidationError('Giờ quét cuối ngày phải theo định dạng HH:MM.')
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValidationError('Giờ quét cuối ngày phải nằm trong khoảng 00:00 đến 23:59.')

    def _compute_nightly_nextcall(self):
        self.ensure_one()
        timezone_name = self.continuous_sync_timezone or 'Asia/Ho_Chi_Minh'
        try:
            timezone_obj = pytz.timezone(timezone_name)
        except Exception:
            timezone_obj = pytz.timezone('Asia/Ho_Chi_Minh')
        utc_now = pytz.UTC.localize(fields.Datetime.now())
        local_now = utc_now.astimezone(timezone_obj)
        hours, minutes = [int(part) for part in (self.nightly_two_day_sync_time or '23:30').split(':', 1)]
        local_target = local_now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if local_target <= local_now:
            from datetime import timedelta
            local_target = local_target + timedelta(days=1)
        utc_target = local_target.astimezone(pytz.UTC)
        return utc_target.replace(tzinfo=None)

    def _write_configuration_params(self):
        self.ensure_one()
        icp = self._get_icp()
        token = (self.access_token or '').strip()
        old_token = icp.get_param(self.PARAM_ACCESS_TOKEN) or ''
        icp.set_param(self.PARAM_ACCESS_TOKEN, token)
        icp.set_param(self.PARAM_ACCESS_TOKEN_COMPAT, token)
        icp.set_param(self.PARAM_WEBHOOK_SECRET, (self.webhook_secret or '').strip())
        icp.set_param(self.PARAM_BATCH_SIZE, str(self.sync_batch_size))
        icp.set_param(self.PARAM_SAME_DAY_INTERVAL, str(self.same_day_sync_interval_minutes))
        icp.set_param(self.PARAM_NIGHTLY_RUN_TIME, (self.nightly_two_day_sync_time or '23:30').strip())
        icp.set_param(self.PARAM_CONTINUOUS_TIMEZONE, self.continuous_sync_timezone or 'Asia/Ho_Chi_Minh')
        icp.set_param(self.PARAM_LOG_RETENTION_DAYS, str(self.sync_log_retention_days))
        icp.set_param(self.PARAM_SMART_RECENT_DAYS, str(self.smart_recent_days))
        icp.set_param(self.PARAM_DEEP_RECENT_DAYS, str(self.deep_recent_days))
        icp.set_param(self.PARAM_CIRCUIT_BREAKER_MINUTES, str(self.circuit_breaker_pause_minutes))
        if token != (old_token or '').strip():
            page_model = self.env['page.fm.page'].sudo()
            page_model.clear_all_token_cache()
            icp.set_param(page_model.PARAM_TOKEN_CHECK_STATUS, '')
            icp.set_param(page_model.PARAM_TOKEN_CHECK_MESSAGE, '')
            icp.set_param(page_model.PARAM_TOKEN_CHECK_AT, '')
            icp.set_param(page_model.PARAM_TOKEN_CHECK_PAGE_COUNT, '0')

    def _write_cron_configuration(self):
        self.ensure_one()
        retired_full_sync = self._get_cron_record(self.RETIRED_FULL_SYNC_XML_ID)
        if retired_full_sync:
            retired_full_sync.sudo().write({'active': False})

        for prefix, xml_id in self.CONTINUOUS_CRON_FIELDS:
            cron = self._get_cron_record(xml_id)
            if not cron:
                _logger.warning("Thiếu cron Pancake: %s", xml_id)
                continue
            values = {'active': bool(self.continuous_sync_active)}
            if prefix in ('quick_sync', 'smart_sync'):
                values.update({
                    'interval_number': max(int(self.same_day_sync_interval_minutes or 10), 1),
                    'interval_type': 'minutes',
                })
            else:
                values.update({
                    'interval_number': 1,
                    'interval_type': 'days',
                    'nextcall': self._compute_nightly_nextcall(),
                })
            cron.sudo().write(values)

    def action_save_configuration(self):
        self.ensure_one()
        self._validate_inputs()
        self._write_configuration_params()
        self._write_cron_configuration()
        return self.action_reload_dashboard()

    def action_reload_dashboard(self):
        self._refresh_dashboard_record()
        return self._build_reload_action()

    def action_check_access_token(self):
        self.ensure_one()
        self._write_configuration_params()
        self.env['page.fm.page'].sudo()._check_main_access_token(access_token=(self.access_token or '').strip(), store=True)
        return self.action_reload_dashboard()

    def action_test_connection(self):
        return self.action_check_access_token()

    def action_load_pages_from_token(self):
        self.ensure_one()
        self._write_configuration_params()
        page_model = self.env['page.fm.page'].sudo()
        result = page_model._load_pages_from_token(
            access_token=(self.access_token or '').strip(),
            store=True,
        )
        if result.get('status') != 'valid':
            raise UserError(result.get('message') or 'Không thể tải danh sách page từ Pancake.')
        page_model._prepare_page_tokens_from_main_token(
            main_access_token=(self.access_token or '').strip(),
            pages=result.get('loaded_pages', page_model.browse()),
        )
        return self.action_reload_dashboard()

    def action_clear_all_token_cache(self):
        self.env['page.fm.page'].sudo().clear_all_token_cache()
        return self.action_reload_dashboard()

    def action_reset_sync_pointer(self):
        icp = self._get_icp()
        self.env['page.fm.conversation'].sudo()._reset_conv_pointer()
        icp.set_param(self.PARAM_CIRCUIT_UNTIL, '')
        return self.action_reload_dashboard()

    def action_toggle_continuous_sync(self):
        self.ensure_one()
        self.write({'continuous_sync_active': not self.continuous_sync_active})
        self._write_cron_configuration()
        return self.action_reload_dashboard()

    def action_open_sync_logs(self):
        self.ensure_one()
        action = self.env.ref('CRM_DAC.action_pancake_message_sync_logs').read()[0]
        action['context'] = {}
        return action

    def action_cleanup_sync_logs_now(self):
        self.ensure_one()
        self._write_configuration_params()
        self.env['pancake.message.sync.log'].sudo().cron_cleanup_old_logs()
        return self.action_reload_dashboard()

    def action_run_continuous_sync_now(self):
        self.ensure_one()
        if self.env['pancake.message.sync.job'].sudo().is_manual_sync_in_progress():
            raise UserError(_('Không thể chạy đồng bộ liên tục khi đang có job đồng bộ toàn bộ thủ công.'))

        self._write_configuration_params()
        self.env['page.fm.page'].sudo().cron_quick_sync_conversations()
        self.env['page.fm.conversation'].sudo().cron_smart_message_sync()
        return self.action_reload_dashboard()

    def action_run_same_day_sync_now(self):
        self.ensure_one()
        self._write_configuration_params()
        self.env['page.fm.conversation'].sudo().action_run_same_day_manual_window_sync()
        return self.action_reload_dashboard()

    def action_run_recent_72h_sync_now(self):
        self.ensure_one()
        self._write_configuration_params()
        self.env['page.fm.conversation'].sudo().action_run_recent_72h_manual_window_sync()
        return self.action_reload_dashboard()

    def action_view_pages(self):
        return self.env.ref('CRM_DAC.action_page_fm_page_simplified').read()[0]

    def action_open_page_selection(self):
        return self.action_view_pages()

    def action_view_conversations(self):
        return self.env.ref('CRM_DAC.action_page_fm_conversation_admin').read()[0]

    def action_view_messages(self):
        list_view = self.env.ref('CRM_DAC.view_page_fm_message_list')
        form_view = self.env.ref('CRM_DAC.view_page_fm_message_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tin nhắn Pancake'),
            'res_model': 'page.fm.message',
            'view_mode': 'list,form',
            'views': [(list_view.id, 'list'), (form_view.id, 'form')],
            'target': 'current',
        }

    def action_open_message_sync_monitor(self):
        return self.env['pancake.bulk.sync.dashboard'].action_open_dashboard()

    def action_open_manual_full_sync(self):
        return self.action_open_message_sync_monitor()

    def action_start_full_message_sync(self):
        return self.action_open_message_sync_monitor()

    def action_stop_full_message_sync(self):
        self.env['pancake.message.sync.job'].action_stop_active_job()
        return self.action_reload_dashboard()

    def action_open_active_message_sync_job(self):
        self.ensure_one()
        if not self.active_job_id:
            raise UserError('Chưa có job đồng bộ toàn bộ nào để mở.')
        return self.active_job_id.action_open_form()
