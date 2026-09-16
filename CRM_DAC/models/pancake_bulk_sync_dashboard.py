from datetime import timedelta
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PancakeBulkSyncDashboard(models.TransientModel):
    _name = 'pancake.bulk.sync.dashboard'
    _description = 'Bảng điều khiển đồng bộ toàn bộ Pancake'

    TOKEN_STATUS_SELECTION = [
        ('valid', 'Hợp lệ'),
        ('expired', 'Hết hạn'),
        ('invalid', 'Không hợp lệ'),
        ('network_error', 'Lỗi mạng'),
        ('unknown_error', 'Lỗi chưa phân loại'),
    ]

    INTERVAL_TYPES = [
        ('minutes', 'Phút'),
        ('hours', 'Giờ'),
        ('days', 'Ngày'),
        ('weeks', 'Tuần'),
        ('months', 'Tháng'),
    ]

    LIVE_CONNECTION_SELECTION = [
        ('idle', 'Chờ cập nhật'),
        ('live', 'Đang cập nhật live'),
        ('retrying', 'Đang thử lại'),
    ]

    PARAM_ACCESS_TOKEN = 'page_fm.access_token'
    PARAM_ACCESS_TOKEN_COMPAT = 'pages_fm_main_access_token'
    PARAM_BATCH_SIZE = 'pancake.sync_batch_size'
    PARAM_SMART_RECENT_DAYS = 'pancake.smart_sync_recent_days'
    PARAM_DEEP_RECENT_DAYS = 'pancake.deep_sync_recent_days'
    PARAM_CIRCUIT_BREAKER_MINUTES = 'pancake.circuit_breaker_pause_minutes'
    PARAM_STALE_TIMEOUT_MINUTES = 'pancake.bulk_sync_stale_timeout_minutes'
    PARAM_PRESET_ID = 'pancake.bulk_sync_preset_id'
    RUNNER_CRON_XML_ID = 'CRM_DAC.cron_pancake_full_message_sync_job_runner'

    access_token = fields.Char(string='Access Token chính')
    preset_id = fields.Many2one('pancake.bulk.sync.preset', string='Preset cấu hình')
    preset_description = fields.Text(string='Mô tả preset', readonly=True)
    custom_preset_name = fields.Char(string='Tên preset tùy chỉnh')
    sync_batch_size = fields.Integer(string='Số hội thoại mỗi batch', default=50)
    smart_recent_days = fields.Integer(string='Cửa sổ ưu tiên Smart Sync (ngày)', default=3)
    deep_recent_days = fields.Integer(string='Cửa sổ quét Deep Sync (ngày)', default=7)
    circuit_breaker_pause_minutes = fields.Integer(string='Thời gian nghỉ sau lỗi liên tiếp (phút)', default=15)
    stale_timeout_minutes = fields.Integer(string='Ngưỡng coi job bị gián đoạn (phút)', default=10)

    runner_active = fields.Boolean(string='Bật runner')
    runner_interval_number = fields.Integer(string='Chu kỳ runner', default=2)
    runner_interval_type = fields.Selection(INTERVAL_TYPES, string='Đơn vị runner', default='minutes')
    runner_nextcall = fields.Datetime(string='Lần chạy runner tiếp theo', readonly=True)

    token_configured = fields.Boolean(string='Đã cấu hình token', readonly=True)
    token_check_status = fields.Selection(TOKEN_STATUS_SELECTION, string='Trạng thái token', readonly=True)
    token_check_message = fields.Text(string='Thông điệp token gần nhất', readonly=True)
    token_check_at = fields.Datetime(string='Lần kiểm tra token gần nhất', readonly=True)
    token_check_page_count = fields.Integer(string='Số page từ token', readonly=True)
    live_connection_state = fields.Selection(LIVE_CONNECTION_SELECTION, string='Trạng thái live', readonly=True)

    active_page_count = fields.Integer(string='Tổng page active', readonly=True)
    selected_page_count = fields.Integer(string='Page đã chọn', readonly=True)
    skipped_page_count = fields.Integer(string='Page bị bỏ qua', readonly=True)
    pages_with_token_count = fields.Integer(string='Page có token', readonly=True)
    conversation_count = fields.Integer(string='Tổng conversation', readonly=True)
    message_count = fields.Integer(string='Tổng tin nhắn', readonly=True)
    unread_conversation_count = fields.Integer(string='Conversation chưa đọc', readonly=True)
    require_processing_count = fields.Integer(string='Conversation cần xử lý', readonly=True)
    started_job_count_24h = fields.Integer(string='Job bắt đầu trong 24 giờ', readonly=True)
    error_count_24h = fields.Integer(string='Lỗi trong 24 giờ', readonly=True)
    speed_per_minute = fields.Float(string='Tốc độ gần nhất', readonly=True, digits=(16, 2))
    last_job_started_at = fields.Datetime(string='Lần chạy gần nhất', readonly=True)

    active_job_id = fields.Many2one('pancake.message.sync.job', string='Job hiện tại', readonly=True)
    active_job_state = fields.Char(string='Trạng thái job', readonly=True)
    active_job_scope = fields.Char(string='Phạm vi job', readonly=True)
    active_job_phase = fields.Char(string='Pha hiện tại', readonly=True)
    active_job_progress = fields.Float(string='Tiến độ tổng (%)', readonly=True, digits=(16, 2))
    active_job_phase_progress = fields.Float(string='Tiến độ pha hiện tại (%)', readonly=True, digits=(16, 2))
    active_job_phase_done_count = fields.Integer(string='Đã xử lý trong pha', readonly=True)
    active_job_phase_total_count = fields.Integer(string='Tổng mục tiêu của pha', readonly=True)
    active_job_started_at = fields.Datetime(string='Bắt đầu lúc', readonly=True)
    active_job_finished_at = fields.Datetime(string='Kết thúc lúc', readonly=True)
    active_job_last_heartbeat_at = fields.Datetime(string='Heartbeat gần nhất', readonly=True)
    active_job_processed_page_count = fields.Integer(string='Page đã xử lý', readonly=True)
    active_job_completed_page_count = fields.Integer(string='Page hoàn thành', readonly=True)
    active_job_current_page_name = fields.Char(string='Page đang chạy', readonly=True)
    active_job_synced_conversation_count = fields.Integer(string='Conversation đã sync', readonly=True)
    active_job_total_conversation_count = fields.Integer(string='Tổng conversation mục tiêu', readonly=True)
    active_job_total_messages_created = fields.Integer(string='Tin nhắn mới tạo', readonly=True)
    active_job_pending_task_count = fields.Integer(string='Task chờ chạy', readonly=True)
    active_job_running_task_count = fields.Integer(string='Task đang chạy', readonly=True)
    active_job_completed_task_count = fields.Integer(string='Task hoàn tất', readonly=True)
    active_job_failed_task_count = fields.Integer(string='Task lỗi', readonly=True)
    active_job_last_log_message = fields.Text(string='Log cuối', readonly=True)
    active_job_error_message = fields.Text(string='Lỗi cuối', readonly=True)
    active_job_resume_count = fields.Integer(string='Số lần tự phục hồi', readonly=True)
    active_job_last_checkpoint_at = fields.Datetime(string='Checkpoint gần nhất', readonly=True)
    active_job_last_recovery_reason = fields.Text(string='Lý do phục hồi gần nhất', readonly=True)

    console_status_html = fields.Html(string='Badge trạng thái', sanitize=False, readonly=True)
    console_overview_html = fields.Html(string='Tổng quan', sanitize=False, readonly=True)
    console_system_html = fields.Html(string='Sức khỏe hệ thống', sanitize=False, readonly=True)
    console_job_html = fields.Html(string='Khối job hiện tại', sanitize=False, readonly=True)
    console_scope_html = fields.Html(string='Phạm vi đồng bộ', sanitize=False, readonly=True)
    console_setup_help_html = fields.Html(string='Giải thích cấu hình', sanitize=False, readonly=True)
    console_live_feed_html = fields.Html(string='Log live', sanitize=False, readonly=True)
    console_report_24h_html = fields.Html(string='Báo cáo 24 giờ', sanitize=False, readonly=True)
    console_report_7d_html = fields.Html(string='Báo cáo 7 ngày', sanitize=False, readonly=True)
    console_history_html = fields.Html(string='Tóm tắt lịch sử', sanitize=False, readonly=True)

    recent_job_ids = fields.Many2many('pancake.message.sync.job', string='Job gần đây', readonly=True)
    page_line_ids = fields.One2many('pancake.bulk.sync.page.line', 'dashboard_id', string='Page active')

    @api.model
    def _get_icp(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _get_datetime_param(self, key):
        value = self._get_icp().get_param(key)
        if not value:
            return False
        try:
            return fields.Datetime.to_datetime(value)
        except Exception:
            return False

    @api.model
    def _get_int_param(self, key, default):
        raw = self._get_icp().get_param(key)
        try:
            return max(int(raw or default), 1)
        except (TypeError, ValueError):
            return default

    @api.model
    def _get_runner_cron(self):
        return self.env.ref(self.RUNNER_CRON_XML_ID, raise_if_not_found=False)

    @api.model
    def _get_current_preset(self):
        preset_model = self.env['pancake.bulk.sync.preset'].sudo()
        preset_id = int(self._get_icp().get_param(self.PARAM_PRESET_ID, '0') or 0)
        preset = preset_model.browse(preset_id).exists()
        if preset:
            return preset
        return preset_model._get_default_preset()

    @api.model
    def _build_page_line_commands(self):
        page_model = self.env['page.fm.page'].sudo()
        commands = [(5, 0, 0)]
        for page in page_model._get_all_pages_for_selection():
            commands.append((0, 0, {
                'page_id': page.id,
                'name': page.name,
                'page_fm_id_str': page.page_fm_id_str,
                'catalog_status': page.catalog_status,
                'page_token_cached': page.page_token_cached,
                'page_token_cached_at': page.page_token_cached_at,
                'conversation_count': page.conversation_count,
                'last_message_sync_at': page.last_message_sync_at,
                'sync_enabled': bool(page.sync_enabled),
            }))
        return commands

    def _sync_page_line_selection_to_pages(self):
        page_lines = self.page_line_ids.filtered('page_id')
        if not page_lines:
            return self.env['page.fm.page']
        updated_pages = self.env['page.fm.page']
        for line in page_lines:
            page = line.page_id.sudo()
            if page.exists() and page.sync_enabled != bool(line.sync_enabled):
                page.write({'sync_enabled': bool(line.sync_enabled)})
                updated_pages |= page
        return updated_pages

    def _set_page_line_selection(self, predicate):
        self.ensure_one()
        for line in self.page_line_ids:
            line.sync_enabled = bool(predicate(line))
        self._sync_page_line_selection_to_pages()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
        form_view = self.env.ref('CRM_DAC.view_pancake_bulk_sync_dashboard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đồng bộ toàn bộ Pancake'),
            'res_model': self._name,
            'res_id': dashboard.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'current',
        }

    @api.model
    def action_open_dashboard(self):
        dashboard = self._get_dashboard_record()
        return self._build_open_dashboard_action(dashboard)

    def action_reload_dashboard(self):
        self.ensure_one()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def _format_datetime_label(self, value):
        if not value:
            return 'Chưa có'
        if isinstance(value, str):
            try:
                value = fields.Datetime.to_datetime(value)
            except Exception:
                return escape(value)
        localized = fields.Datetime.context_timestamp(self, value)
        return localized.strftime('%d/%m/%Y %H:%M:%S')

    @api.model
    def _format_number(self, value, digits=0):
        if value is False or value is None:
            return '0'
        if digits:
            return f"{float(value):,.{digits}f}".replace(',', '.')
        return f"{int(value):,}".replace(',', '.')

    @api.model
    def _format_duration_minutes(self, minutes_value):
        if not minutes_value:
            return '0 phút'
        minutes_value = float(minutes_value)
        hours = int(minutes_value // 60)
        minutes = int(round(minutes_value % 60))
        if hours:
            return f'{hours} giờ {minutes} phút'
        return f'{minutes} phút'

    @api.model
    def _status_tone(self, kind, value=None):
        if kind == 'token':
            if value == 'valid':
                return 'success'
            if value in ('expired', 'invalid', 'network_error', 'unknown_error'):
                return 'danger'
            return 'neutral'
        if kind == 'runner':
            return 'success' if value else 'neutral'
        if kind == 'job':
            if value == 'running':
                return 'info'
            if value == 'stopping':
                return 'warning'
            if value in ('done', 'done_with_warnings'):
                return 'success'
            if value in ('failed', 'cancelled'):
                return 'danger'
            return 'neutral'
        if kind == 'resume':
            return 'warning' if value else 'success'
        return 'neutral'

    @api.model
    def _render_badge(self, title, value, tone='neutral', hint=False):
        hint_html = f'<span class="o_pancake_console_badge_hint">{escape(hint)}</span>' if hint else ''
        return (
            f'<div class="o_pancake_console_badge o_pancake_console_badge--{tone}">'
            f'<span class="o_pancake_console_badge_title">{escape(title)}</span>'
            f'<strong class="o_pancake_console_badge_value">{escape(value or "—")}</strong>'
            f'{hint_html}'
            f'</div>'
        )

    @api.model
    def _render_metric_list(self, metrics):
        rows = []
        for label, value in metrics:
            rows.append(
                '<div class="o_pancake_console_metric">'
                f'<span class="o_pancake_console_metric_label">{escape(label)}</span>'
                f'<strong class="o_pancake_console_metric_value">{escape(value)}</strong>'
                '</div>'
            )
        return ''.join(rows)

    @api.model
    def _render_card(self, title, subtitle, body_html, tone='neutral'):
        subtitle_html = f'<p class="o_pancake_console_card_subtitle">{escape(subtitle)}</p>' if subtitle else ''
        return (
            f'<section class="o_pancake_console_card o_pancake_console_card--{tone}">'
            f'<header class="o_pancake_console_card_header"><h3>{escape(title)}</h3>{subtitle_html}</header>'
            f'<div class="o_pancake_console_card_body">{body_html}</div>'
            '</section>'
        )

    @api.model
    def _collect_report(self, window_hours):
        job_model = self.env['pancake.message.sync.job'].sudo()
        log_model = self.env['pancake.message.sync.log'].sudo()
        cutoff = fields.Datetime.now() - timedelta(hours=window_hours)
        jobs = job_model.search([('started_at', '>=', cutoff)])
        started_count = len(jobs)
        done_count = len(jobs.filtered(lambda rec: rec.state == 'done'))
        warning_count = len(jobs.filtered(lambda rec: rec.state == 'done_with_warnings'))
        failed_count = len(jobs.filtered(lambda rec: rec.state == 'failed'))
        cancelled_count = len(jobs.filtered(lambda rec: rec.state == 'cancelled'))
        resumed_count = log_model.search_count([
            ('logged_at', '>=', cutoff),
            ('event_code', '=', 'job_resumed_after_stale'),
        ])
        total_conversations = sum(jobs.mapped('synced_conversation_count'))
        total_messages = sum(jobs.mapped('total_messages_created'))

        duration_minutes = 0.0
        duration_values = []
        for job in jobs.filtered(lambda rec: rec.started_at and rec.finished_at):
            delta = job.finished_at - job.started_at
            minutes = max(delta.total_seconds() / 60.0, 0.0)
            duration_values.append(minutes)
            duration_minutes += minutes

        avg_duration = sum(duration_values) / len(duration_values) if duration_values else 0.0
        avg_speed = (float(total_conversations) / duration_minutes) if duration_minutes else 0.0
        error_rate = (float(failed_count) / float(started_count) * 100.0) if started_count else 0.0

        error_logs = log_model.search([
            ('logged_at', '>=', cutoff),
            ('level', '=', 'error'),
            ('page_id', '!=', False),
        ])
        page_error_counter = {}
        for log in error_logs:
            key = log.page_id.id
            if key not in page_error_counter:
                page_error_counter[key] = {'name': log.page_id.name, 'count': 0}
            page_error_counter[key]['count'] += 1
        top_error_pages = sorted(page_error_counter.values(), key=lambda item: item['count'], reverse=True)[:5]

        return {
            'window_hours': window_hours,
            'started_count': started_count,
            'done_count': done_count,
            'warning_count': warning_count,
            'failed_count': failed_count,
            'cancelled_count': cancelled_count,
            'resumed_count': resumed_count,
            'total_conversations': total_conversations,
            'total_messages': total_messages,
            'avg_speed': avg_speed,
            'avg_duration': avg_duration,
            'error_rate': error_rate,
            'top_error_pages': top_error_pages,
        }

    @api.model
    def _compute_speed_per_minute(self, job, report_24h):
        if job and job.state in ('running', 'stopping') and job.started_at:
            elapsed_minutes = max((fields.Datetime.now() - job.started_at).total_seconds() / 60.0, 1.0)
            return round(float(job.synced_conversation_count or 0) / elapsed_minutes, 2)
        return round(float(report_24h.get('avg_speed', 0.0) or 0.0), 2)

    @api.model
    def _render_status_sections(self, snapshot):
        token_tone = self._status_tone('token', snapshot['token_check_status'])
        runner_tone = self._status_tone('runner', snapshot['runner_active'])
        job_tone = self._status_tone('job', snapshot['active_job_state_raw'])
        resume_tone = self._status_tone('resume', snapshot['active_job_resume_count'])
        badges_html = ''.join([
            self._render_badge(
                'Token',
                snapshot['token_check_status_label'],
                tone=token_tone,
                hint=snapshot['token_check_message'] or 'Dùng main access token để lấy page và tạo token trang.',
            ),
            self._render_badge(
                'Runner',
                'Đang bật' if snapshot['runner_active'] else 'Đang tắt',
                tone=runner_tone,
                hint=f"Chu kỳ {snapshot['runner_interval_number']} {snapshot['runner_interval_type_label'].lower()}",
            ),
            self._render_badge(
                'Job',
                snapshot['active_job_state'] or 'Chưa có job',
                tone=job_tone,
                hint=snapshot['active_job_phase'] or 'Sẵn sàng khởi chạy',
            ),
            self._render_badge(
                'Phục hồi',
                'Có lần phục hồi gần đây' if snapshot['active_job_resume_count'] else 'Ổn định',
                tone=resume_tone,
                hint=snapshot['active_job_last_recovery_reason'] or 'Không có lần phục hồi gần đây.',
            ),
        ])
        return f'<div class="o_pancake_console_badges">{badges_html}</div>'

    @api.model
    def _render_overview_section(self, snapshot):
        cards = [
            (
                'Page đã chọn',
                f"{self._format_number(snapshot['selected_page_count'])}/{self._format_number(snapshot['active_page_count'])}",
                'Job mới chỉ chụp snapshot từ các page active đang được chọn.',
            ),
            (
                'Page có token',
                self._format_number(snapshot['pages_with_token_count']),
                'Số page active hiện đã có page access token cache.',
            ),
            (
                'Conversation',
                self._format_number(snapshot['conversation_count']),
                'Tổng conversation local đang thuộc các page active.',
            ),
            (
                'Tin nhắn',
                self._format_number(snapshot['message_count']),
                'Tổng tin nhắn đã lưu trong Odoo.',
            ),
            (
                'Lần chạy gần nhất',
                self._format_datetime_label(snapshot['last_job_started_at']),
                'Mốc bắt đầu của job đồng bộ toàn bộ gần nhất.',
            ),
            (
                'Job hiện tại',
                snapshot['active_job_state'] or 'Không có job đang chạy',
                'Theo dõi job thủ công hiện tại mà không lẫn với báo cáo 24 giờ.',
            ),
        ]
        body = ''.join(
            '<article class="o_pancake_console_kpi">'
            f'<span class="o_pancake_console_kpi_label">{escape(label)}</span>'
            f'<strong class="o_pancake_console_kpi_value">{escape(value)}</strong>'
            f'<span class="o_pancake_console_kpi_hint">{escape(hint)}</span>'
            '</article>'
            for label, value, hint in cards
        )
        return f'<div class="o_pancake_console_kpis">{body}</div>'

    @api.model
    def _render_system_section(self, snapshot):
        metrics = self._render_metric_list([
            ('Trạng thái token', snapshot['token_check_status_label']),
            ('Lần kiểm tra token', self._format_datetime_label(snapshot['token_check_at'])),
            ('Số page từ token', self._format_number(snapshot['token_check_page_count'])),
            ('Runner', 'Đang bật' if snapshot['runner_active'] else 'Đang tắt'),
            ('Lần chạy runner tiếp theo', self._format_datetime_label(snapshot['runner_nextcall'])),
            ('Ngưỡng job gián đoạn', f"{self._format_number(snapshot['stale_timeout_minutes'])} phút"),
            ('Tốc độ gần nhất', f"{self._format_number(snapshot['speed_per_minute'], 2)} conv/phút"),
        ])
        return self._render_card(
            'Tình trạng hệ thống',
            'Theo dõi token, runner và các tham số bảo vệ của job đồng bộ toàn bộ.',
            metrics,
        )

    @api.model
    def _render_job_section(self, snapshot):
        job = snapshot['job']
        phase_total = snapshot['active_job_phase_total_count']
        phase_done = snapshot['active_job_phase_done_count']
        phase_hint = 'Chưa có mục tiêu pha hiện tại'
        if phase_total:
            phase_hint = f'{self._format_number(phase_done)}/{self._format_number(phase_total)} mục tiêu trong pha hiện tại'
        metrics = self._render_metric_list([
            ('Trạng thái', snapshot['active_job_state'] or 'Chưa có job'),
            ('Pha', snapshot['active_job_phase'] or '—'),
            ('Tiến độ tổng', f"{self._format_number(snapshot['active_job_progress'], 2)}%"),
            ('Tiến độ pha hiện tại', f"{self._format_number(snapshot['active_job_phase_progress'], 2)}%"),
            ('Chi tiết pha', phase_hint),
            ('Page đang chạy', snapshot['active_job_current_page_name'] or 'Chưa có'),
            ('Page hoàn thành', self._format_number(snapshot['active_job_completed_page_count'])),
            ('Conversation đã sync', self._format_number(snapshot['active_job_synced_conversation_count'])),
            ('Tin nhắn mới tạo', self._format_number(snapshot['active_job_total_messages_created'])),
            ('Heartbeat gần nhất', self._format_datetime_label(snapshot['active_job_last_heartbeat_at'])),
        ])
        completed_rows = ''.join(
            '<li>'
            f"<span>{escape(task.page_id.name or '-')} / {escape(task.conversation_id.display_name or task.task_type)}</span>"
            f"<strong>{escape(task.task_type)}</strong>"
            '</li>'
            for task in snapshot['recent_completed_tasks']
        ) or '<li><span>Chưa có công việc hoàn thành.</span></li>'
        recovery_note = ''
        if snapshot['active_job_last_recovery_reason']:
            recovery_note = (
                '<div class="o_pancake_console_note o_pancake_console_note--warning">'
                f'<strong>Phục hồi gần nhất:</strong> {escape(snapshot["active_job_last_recovery_reason"])}'
                '</div>'
            )
        body = (
            metrics
            + recovery_note
            + '<div class="o_pancake_console_note">'
            + '<strong>20 công việc hoàn thành gần nhất</strong>'
            + f'<ul class="o_pancake_console_list">{completed_rows}</ul>'
            + '</div>'
        )
        subtitle = 'Job đồng bộ toàn bộ chạy tuần tự theo 3 pha: quét conversation, đồng bộ message và hoàn tất.'
        if not job:
            subtitle = 'Chưa có job đồng bộ toàn bộ nào đang chạy.'
        return self._render_card(
            'Job hiện tại',
            subtitle,
            body,
            tone=self._status_tone('job', snapshot['active_job_state_raw']),
        )

    @api.model
    def _render_scope_section(self, snapshot):
        selected_preview = ', '.join(snapshot['selected_pages'].mapped('name')[:8]) or 'Chưa chọn page nào'
        if len(snapshot['selected_pages']) > 8:
            selected_preview = f'{selected_preview}, ...'
        body = (
            '<div class="o_pancake_console_scope">'
            f"<p><strong>{escape(self._format_number(snapshot['selected_page_count']))}</strong> / "
            f"<strong>{escape(self._format_number(snapshot['active_page_count']))}</strong> page active đang được chọn cho lần chạy tiếp theo.</p>"
            f"<p>Page có token cache: <strong>{escape(self._format_number(snapshot['pages_with_token_count']))}</strong>. "
            f"Page bị bỏ qua: <strong>{escape(self._format_number(snapshot['skipped_page_count']))}</strong>.</p>"
            f"<p>Xem nhanh: {escape(selected_preview)}</p>"
            '<p>Dữ liệu Pancake đã đồng bộ vào Odoo trước đó vẫn được giữ lại để tra cứu; job mới chỉ giới hạn phạm vi lấy thêm dữ liệu theo snapshot page đã chọn.</p>'
            '</div>'
        )
        return self._render_card(
            'Phạm vi đồng bộ toàn bộ',
            'Job mới chỉ chạy trên snapshot page active + sync_enabled tại thời điểm bấm bắt đầu.',
            body,
            tone='info',
        )

    @api.model
    def _render_setup_help_section(self, snapshot):
        preset_name = snapshot['preset_name'] or 'Chưa chọn preset'
        body = (
            '<div class="o_pancake_console_help">'
            f'<p><strong>Preset hiện tại:</strong> {escape(preset_name)}</p>'
            f'<p>{escape(snapshot["preset_description"] or "Preset giúp áp dụng nhanh bộ thông số vận hành phù hợp với job đồng bộ toàn bộ.")}</p>'
            '<ul>'
            '<li><strong>Pha 1:</strong> quét toàn bộ conversation của các page đã chọn và upsert về Odoo.</li>'
            '<li><strong>Pha 2:</strong> seed rồi đồng bộ message cho conversation thuộc đúng snapshot page của job.</li>'
            '<li><strong>Pha 3:</strong> hoàn tất job, chốt metrics, heartbeat cuối và trạng thái cuối.</li>'
            '<li><strong>Snapshot page:</strong> đổi cờ chọn page sau khi job đã chạy sẽ không làm nới hoặc thu hẹp phạm vi của job đang chạy.</li>'
            '</ul>'
            '</div>'
        )
        return self._render_card('Giải thích preset và engine', 'Preset chỉ thay đổi thông số chạy, không tự ý mở rộng dữ liệu cần đồng bộ.', body)

    @api.model
    def _render_log_feed_section(self, snapshot):
        job = snapshot['job']
        if not job:
            empty = '<div class="o_pancake_console_empty">Chưa có job để hiển thị log live.</div>'
            return self._render_card('Log live', 'Feed này tự làm mới 2 giây khi job đang chạy và 15 giây khi hệ thống rảnh.', empty)

        logs = self.env['pancake.message.sync.log'].sudo().search([('job_id', '=', job.id)], order='id desc', limit=50)
        rows = []
        for log in logs:
            tone = log.level if log.level in ('info', 'warning', 'error', 'success') else 'info'
            marker = '<span class="o_pancake_console_log_marker">resume</span>' if log.resume_marker else ''
            rows.append(
                f'<article class="o_pancake_console_log o_pancake_console_log--{tone}">'
                f'<div class="o_pancake_console_log_meta">{escape(self._format_datetime_label(log.logged_at))} · {escape(log.phase or "—")} · {escape(log.level.upper())} {marker}</div>'
                f'<div class="o_pancake_console_log_message">{escape(log.message or "")}</div>'
                '</article>'
            )
        body = ''.join(rows) or '<div class="o_pancake_console_empty">Chưa có log.</div>'
        return self._render_card(
            'Log và heartbeat',
            'Runner ghi live log liên tục, gồm retry, timeout, completed task và yêu cầu dừng.',
            f'<div class="o_pancake_console_logs">{body}</div>',
        )

    @api.model
    def _render_report_section(self, report, title):
        top_pages_html = ''.join(
            f'<li><span>{escape(item["name"])}</span><strong>{escape(self._format_number(item["count"]))} lỗi</strong></li>'
            for item in report.get('top_error_pages', [])
        ) or '<li><span>Không có page lỗi trong giai đoạn này.</span></li>'
        metrics = self._render_metric_list([
            ('Job bắt đầu', self._format_number(report['started_count'])),
            ('Job hoàn tất', self._format_number(report['done_count'])),
            ('Hoàn tất có cảnh báo', self._format_number(report.get('warning_count', 0))),
            ('Job lỗi', self._format_number(report['failed_count'])),
            ('Job bị dừng', self._format_number(report['cancelled_count'])),
            ('Số lần phục hồi', self._format_number(report['resumed_count'])),
            ('Conversation đã sync', self._format_number(report['total_conversations'])),
            ('Tin nhắn tạo mới', self._format_number(report['total_messages'])),
            ('Tốc độ trung bình', f"{self._format_number(report['avg_speed'], 2)} conv/phút"),
            ('Thời gian chạy TB', self._format_duration_minutes(report['avg_duration'])),
            ('Tỉ lệ lỗi', f"{self._format_number(report['error_rate'], 2)}%"),
        ])
        body = (
            f'{metrics}'
            '<div class="o_pancake_console_note">'
            '<strong>Top 5 page lỗi nhiều</strong>'
            f'<ul class="o_pancake_console_list">{top_pages_html}</ul>'
            '</div>'
        )
        return self._render_card(title, 'Báo cáo tổng hợp từ job và log hiện có.', body)

    @api.model
    def _render_history_section(self, snapshot):
        recent_jobs = snapshot['recent_jobs']
        if not recent_jobs:
            return self._render_card('Lịch sử gần đây', 'Chưa có job nào.', '<div class="o_pancake_console_empty">Chưa có lịch sử job.</div>')
        rows = []
        for job in recent_jobs:
            rows.append(
                '<tr>'
                f'<td>{escape(job.name)}</td>'
                f'<td>{escape(job._selection_label("state", job.state) or "—")}</td>'
                f'<td>{escape(job._selection_label("phase", job.phase) or "—")}</td>'
                f'<td>{escape(self._format_number(job.progress_percent, 2))}%</td>'
                f'<td>{escape(self._format_number(job.failed_task_count))}</td>'
                f'<td>{escape(self._format_datetime_label(job.started_at))}</td>'
                '</tr>'
            )
        body = (
            '<table class="o_pancake_console_table">'
            '<thead><tr><th>Tên job</th><th>Trạng thái</th><th>Pha</th><th>Tiến độ</th><th>Task lỗi</th><th>Bắt đầu</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table>'
        )
        return self._render_card('Lịch sử gần đây', 'Dùng các nút filter nhanh để mở lịch sử đầy đủ theo trạng thái.', body)

    @api.model
    def _collect_dashboard_snapshot(self):
        icp = self._get_icp()
        page_model = self.env['page.fm.page'].sudo()
        conversation_model = self.env['page.fm.conversation'].sudo()
        message_model = self.env['page.fm.message'].sudo()
        job_model = self.env['pancake.message.sync.job'].sudo()
        log_model = self.env['pancake.message.sync.log'].sudo()
        runner = self._get_runner_cron()
        preset = self._get_current_preset()
        job_model._disable_legacy_crons()
        job = job_model._get_running_job() or job_model._get_latest_job()
        latest_job = job_model._get_latest_job()
        report_24h = self._collect_report(24)
        report_7d = self._collect_report(24 * 7)
        error_cutoff = fields.Datetime.now() - timedelta(hours=24)
        active_pages = page_model._get_all_pages_for_selection()
        selected_pages = active_pages.filtered('sync_enabled')
        recent_completed_tasks = job._get_recent_completed_tasks(limit=20) if job else self.env['pancake.message.sync.task']

        snapshot = {
            'preset': preset,
            'preset_name': preset.name if preset else False,
            'preset_description': preset.description if preset else False,
            'access_token': icp.get_param(self.PARAM_ACCESS_TOKEN) or '',
            'sync_batch_size': self._get_int_param(self.PARAM_BATCH_SIZE, preset.sync_batch_size if preset else 50),
            'smart_recent_days': self._get_int_param(self.PARAM_SMART_RECENT_DAYS, preset.smart_recent_days if preset else 3),
            'deep_recent_days': self._get_int_param(self.PARAM_DEEP_RECENT_DAYS, preset.deep_recent_days if preset else 7),
            'circuit_breaker_pause_minutes': self._get_int_param(self.PARAM_CIRCUIT_BREAKER_MINUTES, preset.circuit_breaker_pause_minutes if preset else 15),
            'stale_timeout_minutes': self._get_int_param(self.PARAM_STALE_TIMEOUT_MINUTES, preset.stale_timeout_minutes if preset else 10),
            'runner_active': bool(runner and runner.active),
            'runner_interval_number': int(runner.interval_number if runner else (preset.runner_interval_number if preset else 2)),
            'runner_interval_type': runner.interval_type if runner else (preset.runner_interval_type if preset else 'minutes'),
            'runner_interval_type_label': dict(self.INTERVAL_TYPES).get(
                runner.interval_type if runner else (preset.runner_interval_type if preset else 'minutes'),
                'Phút',
            ),
            'runner_nextcall': runner.nextcall if runner else False,
            'token_configured': bool(icp.get_param(self.PARAM_ACCESS_TOKEN)),
            'token_check_status': icp.get_param(page_model.PARAM_TOKEN_CHECK_STATUS) or False,
            'token_check_status_label': dict(self.TOKEN_STATUS_SELECTION).get(
                icp.get_param(page_model.PARAM_TOKEN_CHECK_STATUS) or False,
                'Chưa kiểm tra',
            ),
            'token_check_message': icp.get_param(page_model.PARAM_TOKEN_CHECK_MESSAGE) or False,
            'token_check_at': self._get_datetime_param(page_model.PARAM_TOKEN_CHECK_AT),
            'token_check_page_count': self._get_int_param(page_model.PARAM_TOKEN_CHECK_PAGE_COUNT, 0),
            'active_page_count': len(active_pages),
            'selected_page_count': len(selected_pages),
            'skipped_page_count': max(len(active_pages) - len(selected_pages), 0),
            'pages_with_token_count': len(active_pages.filtered('page_token_cached')),
            'selected_pages': selected_pages,
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
            'started_job_count_24h': report_24h['started_count'],
            'error_count_24h': log_model.search_count([('logged_at', '>=', error_cutoff), ('level', '=', 'error')]),
            'job': job,
            'last_job_started_at': latest_job.started_at if latest_job else False,
            'active_job_id': job.id if job else False,
            'active_job_state_raw': job.state if job else False,
            'active_job_state': job._selection_label('state', job.state) if job else False,
            'active_job_scope': job._selection_label('sync_scope', job.sync_scope) if job else False,
            'active_job_phase': job._selection_label('phase', job.phase) if job else False,
            'active_job_progress': job.progress_percent if job else 0.0,
            'active_job_phase_progress': job.phase_progress_percent if job else 0.0,
            'active_job_phase_done_count': job.phase_done_count if job else 0,
            'active_job_phase_total_count': job.phase_total_count if job else 0,
            'active_job_started_at': job.started_at if job else False,
            'active_job_finished_at': job.finished_at if job else False,
            'active_job_last_heartbeat_at': job.last_heartbeat_at if job else False,
            'active_job_processed_page_count': job.processed_page_count if job else 0,
            'active_job_completed_page_count': job.completed_page_count if job else 0,
            'active_job_current_page_name': job.current_page_name if job else False,
            'active_job_synced_conversation_count': job.synced_conversation_count if job else 0,
            'active_job_total_conversation_count': job.total_conversation_count if job else 0,
            'active_job_total_messages_created': job.total_messages_created if job else 0,
            'active_job_pending_task_count': job.pending_task_count if job else 0,
            'active_job_running_task_count': job.running_task_count if job else 0,
            'active_job_completed_task_count': job.completed_task_count if job else 0,
            'active_job_failed_task_count': job.failed_task_count if job else 0,
            'active_job_last_log_message': job.last_log_message if job else False,
            'active_job_error_message': job.error_message if job else False,
            'active_job_resume_count': job.resume_count if job else 0,
            'active_job_last_checkpoint_at': job.last_checkpoint_at if job else False,
            'active_job_last_recovery_reason': job.last_recovery_reason if job else False,
            'recent_completed_tasks': recent_completed_tasks,
            'recent_jobs': job_model._get_recent_jobs(limit=8),
            'report_24h': report_24h,
            'report_7d': report_7d,
        }
        snapshot['speed_per_minute'] = self._compute_speed_per_minute(job, report_24h)
        return snapshot

    @api.model
    def _build_dashboard_values(self):
        snapshot = self._collect_dashboard_snapshot()
        return {
            'access_token': snapshot['access_token'],
            'preset_id': snapshot['preset'].id if snapshot['preset'] else False,
            'preset_description': snapshot['preset_description'] or False,
            'sync_batch_size': snapshot['sync_batch_size'],
            'smart_recent_days': snapshot['smart_recent_days'],
            'deep_recent_days': snapshot['deep_recent_days'],
            'circuit_breaker_pause_minutes': snapshot['circuit_breaker_pause_minutes'],
            'stale_timeout_minutes': snapshot['stale_timeout_minutes'],
            'runner_active': snapshot['runner_active'],
            'runner_interval_number': snapshot['runner_interval_number'],
            'runner_interval_type': snapshot['runner_interval_type'],
            'runner_nextcall': snapshot['runner_nextcall'],
            'token_configured': snapshot['token_configured'],
            'token_check_status': snapshot['token_check_status'] or False,
            'token_check_message': snapshot['token_check_message'] or False,
            'token_check_at': snapshot['token_check_at'],
            'token_check_page_count': snapshot['token_check_page_count'],
            'live_connection_state': 'idle',
            'active_page_count': snapshot['active_page_count'],
            'selected_page_count': snapshot['selected_page_count'],
            'skipped_page_count': snapshot['skipped_page_count'],
            'pages_with_token_count': snapshot['pages_with_token_count'],
            'conversation_count': snapshot['conversation_count'],
            'message_count': snapshot['message_count'],
            'unread_conversation_count': snapshot['unread_conversation_count'],
            'require_processing_count': snapshot['require_processing_count'],
            'started_job_count_24h': snapshot['started_job_count_24h'],
            'error_count_24h': snapshot['error_count_24h'],
            'speed_per_minute': snapshot['speed_per_minute'],
            'last_job_started_at': snapshot['last_job_started_at'],
            'active_job_id': snapshot['active_job_id'],
            'active_job_state': snapshot['active_job_state'] or False,
            'active_job_scope': snapshot['active_job_scope'] or False,
            'active_job_phase': snapshot['active_job_phase'] or False,
            'active_job_progress': snapshot['active_job_progress'],
            'active_job_phase_progress': snapshot['active_job_phase_progress'],
            'active_job_phase_done_count': snapshot['active_job_phase_done_count'],
            'active_job_phase_total_count': snapshot['active_job_phase_total_count'],
            'active_job_started_at': snapshot['active_job_started_at'],
            'active_job_finished_at': snapshot['active_job_finished_at'],
            'active_job_last_heartbeat_at': snapshot['active_job_last_heartbeat_at'],
            'active_job_processed_page_count': snapshot['active_job_processed_page_count'],
            'active_job_completed_page_count': snapshot['active_job_completed_page_count'],
            'active_job_current_page_name': snapshot['active_job_current_page_name'] or False,
            'active_job_synced_conversation_count': snapshot['active_job_synced_conversation_count'],
            'active_job_total_conversation_count': snapshot['active_job_total_conversation_count'],
            'active_job_total_messages_created': snapshot['active_job_total_messages_created'],
            'active_job_pending_task_count': snapshot['active_job_pending_task_count'],
            'active_job_running_task_count': snapshot['active_job_running_task_count'],
            'active_job_completed_task_count': snapshot['active_job_completed_task_count'],
            'active_job_failed_task_count': snapshot['active_job_failed_task_count'],
            'active_job_last_log_message': snapshot['active_job_last_log_message'] or False,
            'active_job_error_message': snapshot['active_job_error_message'] or False,
            'active_job_resume_count': snapshot['active_job_resume_count'],
            'active_job_last_checkpoint_at': snapshot['active_job_last_checkpoint_at'],
            'active_job_last_recovery_reason': snapshot['active_job_last_recovery_reason'] or False,
            'console_status_html': self._render_status_sections(snapshot),
            'console_overview_html': self._render_overview_section(snapshot),
            'console_system_html': self._render_system_section(snapshot),
            'console_job_html': self._render_job_section(snapshot),
            'console_scope_html': self._render_scope_section(snapshot),
            'console_setup_help_html': self._render_setup_help_section(snapshot),
            'console_live_feed_html': self._render_log_feed_section(snapshot),
            'console_report_24h_html': self._render_report_section(snapshot['report_24h'], 'Báo cáo 24 giờ qua'),
            'console_report_7d_html': self._render_report_section(snapshot['report_7d'], 'Báo cáo 7 ngày qua'),
            'console_history_html': self._render_history_section(snapshot),
            'recent_job_ids': [(6, 0, snapshot['recent_jobs'].ids)],
            'page_line_ids': self._build_page_line_commands(),
        }

    def _validate_configuration(self):
        validations = [
            (self.sync_batch_size, 'Số hội thoại mỗi batch phải lớn hơn hoặc bằng 1.'),
            (self.smart_recent_days, 'Cửa sổ Smart Sync phải lớn hơn hoặc bằng 1 ngày.'),
            (self.deep_recent_days, 'Cửa sổ Deep Sync phải lớn hơn hoặc bằng 1 ngày.'),
            (self.circuit_breaker_pause_minutes, 'Thời gian nghỉ sau lỗi phải lớn hơn hoặc bằng 1 phút.'),
            (self.stale_timeout_minutes, 'Ngưỡng coi job gián đoạn phải lớn hơn hoặc bằng 1 phút.'),
            (self.runner_interval_number, 'Chu kỳ cron runner phải lớn hơn hoặc bằng 1.'),
        ]
        for value, message in validations:
            if value < 1:
                raise ValidationError(message)

    def _write_configuration_params(self):
        self.ensure_one()
        icp = self._get_icp()
        old_token = (icp.get_param(self.PARAM_ACCESS_TOKEN) or '').strip()
        new_token = (self.access_token or '').strip()
        icp.set_param(self.PARAM_ACCESS_TOKEN, new_token)
        icp.set_param(self.PARAM_ACCESS_TOKEN_COMPAT, new_token)
        icp.set_param(self.PARAM_BATCH_SIZE, str(self.sync_batch_size))
        icp.set_param(self.PARAM_SMART_RECENT_DAYS, str(self.smart_recent_days))
        icp.set_param(self.PARAM_DEEP_RECENT_DAYS, str(self.deep_recent_days))
        icp.set_param(self.PARAM_CIRCUIT_BREAKER_MINUTES, str(self.circuit_breaker_pause_minutes))
        icp.set_param(self.PARAM_STALE_TIMEOUT_MINUTES, str(self.stale_timeout_minutes))
        icp.set_param(self.PARAM_PRESET_ID, str(self.preset_id.id if self.preset_id else 0))
        if old_token != new_token:
            self.env['page.fm.page'].sudo().clear_all_token_cache()

    def _write_runner_configuration(self):
        self.ensure_one()
        runner = self._get_runner_cron()
        if not runner:
            raise UserError(_('Không tìm thấy cron runner của đồng bộ toàn bộ Pancake.'))
        runner.sudo().write({
            'active': self.runner_active,
            'interval_number': self.runner_interval_number,
            'interval_type': self.runner_interval_type,
        })

    def action_save_configuration(self):
        self.ensure_one()
        self._validate_configuration()
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self._write_runner_configuration()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_apply_preset(self):
        self.ensure_one()
        preset = self.preset_id or self._get_current_preset()
        if not preset:
            raise UserError(_('Không tìm thấy preset để áp dụng.'))
        self.write({
            **preset._to_dashboard_values(),
            'preset_description': preset.description or False,
        })
        self._validate_configuration()
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self._write_runner_configuration()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_save_custom_preset(self):
        self.ensure_one()
        self._validate_configuration()
        name = (self.custom_preset_name or '').strip()
        if not name:
            raise UserError(_('Nhập tên preset tùy chỉnh trước khi lưu.'))
        preset_model = self.env['pancake.bulk.sync.preset'].sudo()
        preset = preset_model.create({
            'name': name,
            'description': 'Preset tùy chỉnh được lưu từ màn Đồng bộ toàn bộ Pancake.',
            'preset_type': 'custom',
            'sequence': 1000 + preset_model.search_count([]),
            'sync_batch_size': self.sync_batch_size,
            'smart_recent_days': self.smart_recent_days,
            'deep_recent_days': self.deep_recent_days,
            'circuit_breaker_pause_minutes': self.circuit_breaker_pause_minutes,
            'runner_interval_number': self.runner_interval_number,
            'runner_interval_type': self.runner_interval_type,
            'stale_timeout_minutes': self.stale_timeout_minutes,
            'is_default_for_bulk_sync': False,
        })
        self.write({
            'preset_id': preset.id,
            'preset_description': preset.description or False,
            'custom_preset_name': False,
        })
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self._write_runner_configuration()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_update_custom_preset(self):
        self.ensure_one()
        self._validate_configuration()
        if not self.preset_id or self.preset_id.preset_type != 'custom':
            raise UserError(_('Chỉ preset tùy chỉnh mới được cập nhật trực tiếp.'))
        self.preset_id.sudo().write({
            'sync_batch_size': self.sync_batch_size,
            'smart_recent_days': self.smart_recent_days,
            'deep_recent_days': self.deep_recent_days,
            'circuit_breaker_pause_minutes': self.circuit_breaker_pause_minutes,
            'runner_interval_number': self.runner_interval_number,
            'runner_interval_type': self.runner_interval_type,
            'stale_timeout_minutes': self.stale_timeout_minutes,
        })
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self._write_runner_configuration()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_check_access_token(self):
        self.ensure_one()
        self._validate_configuration()
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self.env['page.fm.page'].sudo()._check_main_access_token(access_token=self.access_token or None, store=True)
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_load_pages_from_token(self):
        self.ensure_one()
        self._validate_configuration()
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        page_model = self.env['page.fm.page'].sudo()
        result = page_model._load_pages_from_token(access_token=self.access_token or None, store=True)
        if result.get('status') != 'valid':
            raise UserError(result.get('message') or _('Không thể tải page từ Pancake.'))
        page_model._prepare_page_tokens_from_main_token(
            main_access_token=self.access_token or None,
            pages=result.get('loaded_pages', page_model.browse()),
        )
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_select_all_pages(self):
        return self._set_page_line_selection(lambda line: True)

    def action_clear_all_pages(self):
        return self._set_page_line_selection(lambda line: False)

    def action_select_pages_with_token(self):
        return self._set_page_line_selection(lambda line: line.page_token_cached)

    def action_start_bulk_sync(self):
        self.ensure_one()
        self._validate_configuration()
        self._sync_page_line_selection_to_pages()
        self._write_configuration_params()
        self._write_runner_configuration()
        selected_pages = self.page_line_ids.filtered(lambda line: line.page_id and line.sync_enabled).mapped('page_id').filtered('active')
        self.env['pancake.message.sync.job'].action_start_manual_full_sync(page_ids=selected_pages.ids)
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_stop_bulk_sync(self):
        self.ensure_one()
        self.env['pancake.message.sync.job'].action_stop_active_job()
        self.write(self._build_dashboard_values())
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_active_job(self):
        self.ensure_one()
        if not self.active_job_id:
            raise UserError(_('Chưa có job đồng bộ toàn bộ nào để mở.'))
        return self.active_job_id.action_open_form()

    def _history_action_with_domain(self, domain, title):
        action = self.env.ref('CRM_DAC.action_pancake_message_sync_jobs').read()[0]
        action['name'] = title
        action['domain'] = domain
        return action

    def action_open_job_history(self):
        return self._history_action_with_domain([], 'Lịch sử job đồng bộ toàn bộ Pancake')

    def action_open_running_jobs(self):
        return self._history_action_with_domain([('state', 'in', ['running', 'stopping'])], 'Job đang chạy')

    def action_open_done_jobs(self):
        return self._history_action_with_domain([('state', 'in', ['done', 'done_with_warnings'])], 'Job hoàn tất')

    def action_open_done_with_warning_jobs(self):
        return self._history_action_with_domain([('state', '=', 'done_with_warnings')], 'Job hoàn tất có cảnh báo')

    def action_open_failed_jobs(self):
        return self._history_action_with_domain([('state', 'in', ['failed', 'cancelled'])], 'Job lỗi hoặc bị dừng')

    def action_open_recovered_jobs(self):
        return self._history_action_with_domain([('resume_count', '>', 0)], 'Job đã tự phục hồi')

    def action_open_page_selection(self):
        return self.env.ref('CRM_DAC.action_page_fm_page_simplified').read()[0]

    def get_live_bulk_sync_snapshot(self):
        self.ensure_one()
        snapshot = self._collect_dashboard_snapshot()
        poll_seconds = 2 if snapshot['active_job_state_raw'] in ('running', 'stopping') else 15
        return {
            'poll_seconds': poll_seconds,
            'connection_state': 'live',
            'sections': {
                'status': self._render_status_sections(snapshot),
                'overview': self._render_overview_section(snapshot),
                'system': self._render_system_section(snapshot),
                'job': self._render_job_section(snapshot),
                'scope': self._render_scope_section(snapshot),
                'live_feed': self._render_log_feed_section(snapshot),
            },
        }

    @api.model
    def get_live_bulk_sync_snapshot_for_current_user(self):
        dashboard = self._get_dashboard_record()
        payload = dashboard.get_live_bulk_sync_snapshot()
        payload['record_id'] = dashboard.id
        return payload

    def get_bulk_sync_report_snapshot(self):
        self.ensure_one()
        snapshot = self._collect_dashboard_snapshot()
        poll_seconds = 10 if snapshot['active_job_state_raw'] in ('running', 'stopping') else 30
        return {
            'poll_seconds': poll_seconds,
            'connection_state': 'live',
            'sections': {
                'report_24h': self._render_report_section(snapshot['report_24h'], 'Báo cáo 24 giờ qua'),
                'report_7d': self._render_report_section(snapshot['report_7d'], 'Báo cáo 7 ngày qua'),
                'history': self._render_history_section(snapshot),
            },
        }

    @api.model
    def get_bulk_sync_report_snapshot_for_current_user(self):
        dashboard = self._get_dashboard_record()
        payload = dashboard.get_bulk_sync_report_snapshot()
        payload['record_id'] = dashboard.id
        return payload
