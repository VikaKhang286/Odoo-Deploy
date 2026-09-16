import json
import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PancakeMessageSyncJob(models.Model):
    _name = 'pancake.message.sync.job'
    _description = 'Pancake Manual Full Sync Job'
    _order = 'id desc'

    LEGACY_CRON_XML_IDS = (
        'CRM_DAC.cron_pancake_full_sync',
    )

    TOKEN_STATUS_SELECTION = [
        ('valid', 'Hợp lệ'),
        ('expired', 'Hết hạn'),
        ('invalid', 'Không hợp lệ'),
        ('network_error', 'Lỗi mạng'),
        ('unknown_error', 'Lỗi chưa phân loại'),
    ]
    STATE_SELECTION = [
        ('draft', 'Nháp'),
        ('running', 'Đang chạy'),
        ('stopping', 'Đang dừng'),
        ('done', 'Hoàn tất'),
        ('done_with_warnings', 'Hoàn tất có cảnh báo'),
        ('failed', 'Lỗi'),
        ('cancelled', 'Đã dừng'),
    ]
    PHASE_SELECTION = [
        ('queued', 'Đã xếp hàng'),
        ('page_scan', 'Pha 1 - Quét conversation'),
        ('message_sync', 'Pha 2 - Đồng bộ tin nhắn'),
        ('finalize', 'Pha 3 - Hoàn tất'),
        ('done', 'Hoàn tất'),
    ]
    ENGINE_MODE_SELECTION = [
        ('api_queue', 'API Queue'),
    ]
    SYNC_SCOPE_SELECTION = [
        ('selected_pages', 'Page đã chọn'),
        ('all_active_pages', 'Tất cả page active (legacy)'),
    ]

    name = fields.Char(string='Tên job', required=True, copy=False, default=lambda self: self._default_name())
    requested_by_id = fields.Many2one('res.users', string='Người yêu cầu', required=True, default=lambda self: self.env.user, readonly=True)
    state = fields.Selection(STATE_SELECTION, string='Trạng thái', default='draft', required=True, readonly=True)
    phase = fields.Selection(PHASE_SELECTION, string='Pha hiện tại', default='queued', required=True, readonly=True)
    engine_mode = fields.Selection(ENGINE_MODE_SELECTION, string='Engine', default='api_queue', required=True, readonly=True)
    started_at = fields.Datetime(string='Bắt đầu lúc', readonly=True)
    finished_at = fields.Datetime(string='Kết thúc lúc', readonly=True)
    last_heartbeat_at = fields.Datetime(string='Heartbeat gần nhất', readonly=True)
    last_live_log_at = fields.Datetime(string='Mốc live log gần nhất', readonly=True)
    sync_scope = fields.Selection(SYNC_SCOPE_SELECTION, string='Phạm vi đồng bộ', default='selected_pages', required=True, readonly=True)

    batch_size = fields.Integer(string='Số hội thoại mỗi batch', readonly=True, default=50)
    smart_recent_days = fields.Integer(string='Cửa sổ Smart Sync', readonly=True, default=3)
    deep_recent_days = fields.Integer(string='Cửa sổ Deep Sync', readonly=True, default=7)
    circuit_breaker_pause_minutes = fields.Integer(string='Thời gian nghỉ circuit breaker', readonly=True, default=15)
    stale_timeout_minutes = fields.Integer(string='Ngưỡng coi job gián đoạn (phút)', readonly=True, default=10)
    token_status = fields.Selection(TOKEN_STATUS_SELECTION, string='Trạng thái token', readonly=True)
    token_message = fields.Text(string='Thông điệp token', readonly=True)
    catalog_page_count = fields.Integer(string='Tổng page từ token', readonly=True)
    selected_page_count = fields.Integer(string='Page trong phạm vi', readonly=True)
    skipped_page_count = fields.Integer(string='Page ngoài phạm vi', readonly=True)
    selected_page_snapshot = fields.Text(string='Snapshot page trong phạm vi', readonly=True)
    selected_page_ids_json = fields.Text(string='Selected Page IDs', readonly=True)

    total_page_count = fields.Integer(string='Tổng page', readonly=True)
    processed_page_count = fields.Integer(string='Page đã xong', readonly=True)
    completed_page_count = fields.Integer(string='Page hoàn thành', readonly=True)
    total_conversation_count = fields.Integer(string='Tổng conversation mục tiêu', readonly=True)
    synced_conversation_count = fields.Integer(string='Conversation đã sync', readonly=True)
    failed_conversation_count = fields.Integer(string='Conversation lỗi', readonly=True)
    processed_batch_count = fields.Integer(string='Số task đã chạy', readonly=True)
    tier3_batch_count = fields.Integer(string='Số page scan hoàn tất', readonly=True)
    tier4_batch_count = fields.Integer(string='Số message task hoàn tất', readonly=True)
    total_messages_created = fields.Integer(string='Tin nhắn mới đã tạo', readonly=True)
    total_messages_seen = fields.Integer(string='Tin nhắn đọc từ API', readonly=True)
    total_existing_messages = fields.Integer(string='Tin nhắn đã tồn tại', readonly=True)
    progress_percent = fields.Float(string='Tiến độ (%)', readonly=True, digits=(16, 2))
    phase_total_count = fields.Integer(string='Tổng mục tiêu của pha', readonly=True)
    phase_done_count = fields.Integer(string='Đã xử lý trong pha', readonly=True)
    phase_progress_percent = fields.Float(string='Tiến độ pha (%)', readonly=True, digits=(16, 2))
    current_page_name = fields.Char(string='Page hiện tại', readonly=True)
    current_priority = fields.Char(string='Nhóm ưu tiên hiện tại', readonly=True)
    current_pointer = fields.Integer(string='Pointer của job', readonly=True)
    stop_requested = fields.Boolean(string='Yêu cầu dừng', readonly=True)
    error_message = fields.Text(string='Lỗi cuối', readonly=True)
    last_log_message = fields.Text(string='Log cuối', readonly=True)
    log_line_count = fields.Integer(string='Số dòng log', readonly=True)

    phase_cursor_page_id = fields.Many2one('page.fm.page', string='Checkpoint page', readonly=True)
    phase_cursor_page_index = fields.Integer(string='Checkpoint vị trí page', readonly=True)
    last_checkpoint_at = fields.Datetime(string='Checkpoint gần nhất', readonly=True)
    resume_count = fields.Integer(string='Số lần tự phục hồi', readonly=True)
    last_recovery_reason = fields.Text(string='Lý do phục hồi gần nhất', readonly=True)
    runner_claim_token = fields.Char(string='Token claim runner', readonly=True)
    runner_claimed_at = fields.Datetime(string='Lần runner claim', readonly=True)

    pending_task_count = fields.Integer(string='Task chờ chạy', readonly=True)
    running_task_count = fields.Integer(string='Task đang chạy', readonly=True)
    completed_task_count = fields.Integer(string='Task hoàn tất', readonly=True)
    failed_task_count = fields.Integer(string='Task lỗi', readonly=True)

    task_ids = fields.One2many('pancake.message.sync.task', 'job_id', string='Tasks', readonly=True)
    log_ids = fields.One2many('pancake.message.sync.log', 'job_id', string='Logs', readonly=True)

    @api.model
    def _default_name(self):
        return _("Đồng bộ toàn bộ Pancake %s") % fields.Datetime.now()

    @api.model
    def _selection_label(self, field_name, value):
        if not value:
            return False
        selection = dict(self._fields[field_name].selection)
        return selection.get(value, value)

    @api.model
    def _json_dumps(self, payload):
        if not payload:
            return False
        return json.dumps(payload, ensure_ascii=False, default=str)

    @api.model
    def _json_loads(self, payload):
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except Exception:
            return {}

    def _selected_page_ids(self):
        self.ensure_one()
        payload = self._json_loads(self.selected_page_ids_json)
        if isinstance(payload, list):
            return [int(page_id) for page_id in payload if page_id]
        return []

    def _selected_pages(self):
        self.ensure_one()
        page_ids = self._selected_page_ids()
        return self.env['page.fm.page'].sudo().browse(page_ids).exists()

    @api.model
    def _get_running_job(self):
        return self.search([('state', 'in', ['running', 'stopping'])], order='id desc', limit=1)

    @api.model
    def _get_latest_job(self):
        return self.search([], order='id desc', limit=1)

    @api.model
    def _get_recent_jobs(self, limit=8):
        return self.search([], order='id desc', limit=limit)

    def action_open_monitor(self):
        return self.env['pancake.bulk.sync.dashboard'].action_open_dashboard()

    def action_open_form(self):
        self.ensure_one()
        form_view = self.env.ref('CRM_DAC.view_pancake_message_sync_job_form')
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'current',
        }

    def action_request_stop(self):
        for job in self.filtered(lambda rec: rec.state in ('running', 'stopping')):
            if job.state != 'stopping':
                job.sudo().write({'state': 'stopping', 'stop_requested': True})
                job._append_log(
                    'warning',
                    'Đã nhận yêu cầu dừng job. Task hiện tại sẽ kết thúc rồi dừng.',
                    event_code='job_stop_requested',
                )
        return True

    @api.model
    def action_stop_active_job(self):
        job = self._get_running_job()
        if not job:
            return {'status': 'idle'}
        job.action_request_stop()
        return {'status': 'stopping', 'job_id': job.id}

    @api.model
    def action_start_full_sync_from_monitor(self, page_ids=None):
        return self.action_start_manual_full_sync(page_ids=page_ids)

    @api.model
    def action_start_bulk_sync(self, page_ids=None):
        return self.action_start_manual_full_sync(page_ids=page_ids)

    @api.model
    def action_start_manual_full_sync(self, page_ids=None):
        return self._start_sync_job(sync_scope='selected_pages', page_ids=page_ids)

    @api.model
    def _disable_legacy_crons(self):
        changed = False
        for xml_id in self.LEGACY_CRON_XML_IDS:
            cron = self.env.ref(xml_id, raise_if_not_found=False)
            if cron and cron.active:
                cron.sudo().write({'active': False})
                changed = True
        return changed

    @api.model
    def _nudge_runner_cron(self):
        cron = self.env.ref('CRM_DAC.cron_pancake_full_message_sync_job_runner', raise_if_not_found=False)
        if cron:
            cron.sudo().write({'nextcall': fields.Datetime.now()})

    @api.model
    def is_manual_sync_in_progress(self):
        return bool(self._get_running_job())

    @api.model
    def _prepare_target_pages(self, sync_scope='selected_pages', page_ids=None):
        self._disable_legacy_crons()
        page_model = self.env['page.fm.page'].sudo()
        if page_ids is not None:
            pages = page_model.browse(page_ids).exists().filtered(lambda page: page.active)
        else:
            pages = page_model._get_pages_for_sync_scope(sync_scope)
        return pages.sorted(lambda page: (page.name or '', page.id))

    @api.model
    def _start_sync_job(self, sync_scope='selected_pages', page_ids=None):
        running = self._get_running_job()
        if running:
            return {'status': 'running', 'job_id': running.id, 'message': 'Đã có job đang chạy.'}

        page_model = self.env['page.fm.page'].sudo()
        conversation_model = self.env['page.fm.conversation'].sudo()
        token_check = page_model._check_main_access_token(store=True)
        if token_check.get('status') != 'valid':
            raise UserError(token_check.get('message') or _('Main access token không hợp lệ.'))

        pages = self._prepare_target_pages(sync_scope=sync_scope, page_ids=page_ids)
        if not pages:
            raise UserError(_('Chưa có page active nào được chọn để đồng bộ toàn bộ.'))

        active_page_count = page_model._get_active_page_count()
        page_ids_payload = pages.ids
        job = self.create({
            'state': 'running',
            'phase': 'queued',
            'engine_mode': 'api_queue',
            'requested_by_id': self.env.user.id,
            'started_at': fields.Datetime.now(),
            'last_heartbeat_at': fields.Datetime.now(),
            'sync_scope': sync_scope or 'selected_pages',
            'batch_size': conversation_model._get_batch_size(),
            'smart_recent_days': conversation_model._get_recent_activity_days(),
            'deep_recent_days': conversation_model._get_deep_sync_recent_days(),
            'circuit_breaker_pause_minutes': conversation_model._get_circuit_breaker_pause_minutes(),
            'stale_timeout_minutes': conversation_model._get_stale_timeout_minutes(),
            'catalog_page_count': int(token_check.get('page_count', 0) or 0),
            'selected_page_count': len(pages),
            'skipped_page_count': max(active_page_count - len(pages), 0),
            'selected_page_snapshot': ', '.join(pages.mapped('page_fm_id_str')),
            'selected_page_ids_json': self._json_dumps(page_ids_payload),
            'total_page_count': len(pages),
            'token_status': token_check.get('status'),
            'token_message': token_check.get('message'),
        })
        task_values = []
        for page in pages:
            task_values.append({
                'job_id': job.id,
                'task_type': 'page_scan',
                'page_id': page.id,
                'state': 'pending',
                'priority': 300,
                'next_run_at': fields.Datetime.now(),
                'max_attempts': 3,
            })
        self.env['pancake.message.sync.task'].sudo().create(task_values)
        job._append_log(
            'info',
            f'Khởi tạo job API queue cho {len(pages)} page đã chọn. Runner sẽ quét conversation trước rồi seed task đồng bộ tin nhắn.',
            event_code='job_started',
            stats={'selected_page_ids': page_ids_payload},
        )
        job._refresh_runtime_metrics()
        self._nudge_runner_cron()
        return {
            'status': 'started',
            'job_id': job.id,
            'message': f'Đã xếp hàng job đồng bộ toàn bộ cho {len(pages)} page đã chọn.',
        }

    @api.model
    def cron_run_active_jobs(self):
        job, claim_token = self._claim_next_runnable_job()
        if not job:
            return False
        try:
            job._process_next_slice()
            return True
        finally:
            try:
                job._release_claim(claim_token=claim_token)
                self.env.cr.commit()
            except Exception:
                _logger.exception("Pancake job runner failed while releasing claim.")
                self.env.cr.rollback()

    def _append_log(self, level, message, event_code=False, page=False, conversation=False, stats=None, resume_marker=False):
        self.ensure_one()
        values = {
            'job_id': self.id,
            'level': level,
            'phase': self.phase,
            'message': message,
            'event_code': event_code or False,
            'page_id': page.id if page else False,
            'conversation_id': conversation.id if conversation else False,
            'stats_json': self._json_dumps(stats),
            'resume_marker': bool(resume_marker),
        }
        self.env['pancake.message.sync.log'].sudo().create(values)
        write_vals = {
            'last_log_message': message,
            'log_line_count': int(self.log_line_count or 0) + 1,
        }
        if level == 'error':
            write_vals['error_message'] = message
        self.sudo().write(write_vals)

    def _append_live_log(self, force=False, message=False):
        self.ensure_one()
        now = fields.Datetime.now()
        if (
            not force
            and self.last_live_log_at
            and (now - self.last_live_log_at).total_seconds() < 2.0
        ):
            self.sudo().write({'last_heartbeat_at': now})
            return False
        live_message = message or (
            f'Heartbeat: page {self.processed_page_count}/{self.total_page_count}, '
            f'task done {self.completed_task_count}, pending {self.pending_task_count}, '
            f'running {self.running_task_count}, failed {self.failed_task_count}.'
        )
        self._append_log('info', live_message, event_code='job_heartbeat')
        self.sudo().write({
            'last_live_log_at': now,
            'last_heartbeat_at': now,
        })
        return True

    @api.model
    def _weighted_phase_progress(self, phase, page_done, page_total, message_done, message_total, state):
        def _fraction(done, total, completed_if_empty=False):
            if total:
                return min(float(done) / float(total), 1.0)
            return 1.0 if completed_if_empty else 0.0

        final_state = state in ('done', 'done_with_warnings')
        page_phase_complete = final_state or phase in ('message_sync', 'finalize', 'done')
        message_phase_complete = final_state or phase in ('finalize', 'done')
        page_progress = _fraction(page_done, page_total, completed_if_empty=page_phase_complete)
        message_progress = _fraction(message_done, message_total, completed_if_empty=message_phase_complete)
        finalize_progress = 1.0 if final_state else 0.0
        return round((page_progress * 30.0) + (message_progress * 65.0) + (finalize_progress * 5.0), 2)

    def _refresh_runtime_metrics(self):
        for job in self:
            task_model = self.env['pancake.message.sync.task'].sudo()
            domain = [('job_id', '=', job.id)]
            pending_count = task_model.search_count(domain + [('state', 'in', ['pending', 'retry'])])
            running_count = task_model.search_count(domain + [('state', '=', 'running')])
            completed_count = task_model.search_count(domain + [('state', '=', 'done')])
            failed_count = task_model.search_count(domain + [('state', '=', 'failed')])
            page_total_count = task_model.search_count(domain + [('task_type', '=', 'page_scan')])
            page_done_count = task_model.search_count(domain + [('task_type', '=', 'page_scan'), ('state', 'in', ['done', 'failed'])])
            message_total_count = task_model.search_count(domain + [('task_type', '=', 'message_sync')])
            message_done_count = task_model.search_count(domain + [('task_type', '=', 'message_sync'), ('state', 'in', ['done', 'failed'])])

            current_task = task_model.search(domain + [('state', '=', 'running')], order='priority desc, id asc', limit=1)
            if not current_task:
                current_task = task_model.search(domain + [('state', 'in', ['pending', 'retry'])], order='priority desc, id asc', limit=1)
            phase = job.phase
            current_page_name = job.current_page_name
            current_priority = job.current_priority
            if current_task:
                phase = current_task.task_type
                current_page_name = current_task.page_id.name if current_task.page_id else current_page_name
                current_priority = current_task.task_type
            elif page_total_count and page_done_count < page_total_count:
                phase = 'page_scan'
            elif message_total_count and message_done_count < message_total_count:
                phase = 'message_sync'
            elif job.state in ('running', 'stopping'):
                phase = 'finalize'
                current_page_name = False
                current_priority = 'finalize'
            elif job.state in ('done', 'done_with_warnings', 'failed', 'cancelled'):
                phase = 'done'
                current_page_name = False
                current_priority = False

            if phase == 'page_scan':
                phase_total_count_value = page_total_count
                phase_done_count_value = page_done_count
            elif phase == 'message_sync':
                phase_total_count_value = message_total_count
                phase_done_count_value = message_done_count
            elif phase in ('finalize', 'done'):
                phase_total_count_value = 1
                phase_done_count_value = 1 if job.state in ('done', 'done_with_warnings') else 0
            else:
                phase_total_count_value = 0
                phase_done_count_value = 0

            phase_progress = 0.0
            if phase_total_count_value:
                phase_progress = min(float(phase_done_count_value) / float(phase_total_count_value) * 100.0, 100.0)
            progress = self._weighted_phase_progress(
                phase=phase,
                page_done=page_done_count,
                page_total=page_total_count,
                message_done=message_done_count,
                message_total=message_total_count,
                state=job.state,
            )
            if job.state in ('done', 'done_with_warnings'):
                progress = 100.0
                phase_progress = 100.0

            job.sudo().write({
                'pending_task_count': pending_count,
                'running_task_count': running_count,
                'completed_task_count': completed_count,
                'failed_task_count': failed_count,
                'progress_percent': round(progress, 2),
                'phase_total_count': phase_total_count_value,
                'phase_done_count': phase_done_count_value,
                'phase_progress_percent': round(phase_progress, 2),
                'phase': phase,
                'current_page_name': current_page_name or False,
                'current_priority': current_priority or False,
                'last_heartbeat_at': fields.Datetime.now(),
            })

    def _mark_done(self, message):
        self.ensure_one()
        state = 'done_with_warnings' if int(self.failed_task_count or 0) else 'done'
        self._append_log('success', message, event_code='job_done')
        self.sudo().write({
            'state': state,
            'phase': 'done',
            'finished_at': fields.Datetime.now(),
            'progress_percent': 100.0,
            'phase_total_count': 1,
            'phase_done_count': 1,
            'phase_progress_percent': 100.0,
            'stop_requested': False,
            'current_page_name': False,
            'current_priority': False,
            'runner_claim_token': False,
            'runner_claimed_at': False,
        })
        self._refresh_runtime_metrics()

    def _mark_failed(self, message):
        self.ensure_one()
        self._append_log('error', message, event_code='job_failed')
        self.sudo().write({
            'state': 'failed',
            'phase': 'finalize',
            'finished_at': fields.Datetime.now(),
            'error_message': message,
            'current_page_name': False,
            'current_priority': False,
            'runner_claim_token': False,
            'runner_claimed_at': False,
        })
        self._refresh_runtime_metrics()

    def _finish_if_stop_requested(self):
        self.ensure_one()
        if self.state == 'stopping' or self.stop_requested:
            self._append_log('warning', 'Job đã dừng theo yêu cầu người dùng.', event_code='job_cancelled')
            self.sudo().write({
                'state': 'cancelled',
                'phase': 'finalize',
                'finished_at': fields.Datetime.now(),
                'stop_requested': False,
                'current_page_name': False,
                'current_priority': False,
                'runner_claim_token': False,
                'runner_claimed_at': False,
            })
            self._refresh_runtime_metrics()
            return True
        return False

    def _is_stale(self, now=None):
        self.ensure_one()
        reference = self.last_heartbeat_at or self.started_at
        if not reference:
            return False
        now = now or fields.Datetime.now()
        timeout_minutes = max(int(self.stale_timeout_minutes or 10), 1)
        return reference + timedelta(minutes=timeout_minutes) < now

    def _recover_stale_job(self):
        self.ensure_one()
        if self.stop_requested or self.state == 'stopping':
            return False
        stale_tasks = self.task_ids.filtered(
            lambda task: task.state == 'running'
            and task.claimed_at
            and task.claimed_at + timedelta(minutes=2) < fields.Datetime.now()
        )
        for task in stale_tasks:
            task.sudo().write({
                'state': 'retry',
                'next_run_at': fields.Datetime.now(),
                'last_error': _('Task bị reclaim sau khi runner stale.'),
            })
        reason = _(
            'Runner nhận lại job đang gián đoạn vì heartbeat quá hạn ở pha `%s`. Tiếp tục từ task queue hiện tại.'
        ) % (self.phase or 'unknown')
        self.sudo().write({
            'resume_count': int(self.resume_count or 0) + 1,
            'last_recovery_reason': reason,
            'last_heartbeat_at': fields.Datetime.now(),
        })
        self._append_log('warning', reason, event_code='stale_detected', resume_marker=True)
        self._append_log(
            'info',
            'Đã tự động tiếp tục job cũ từ task queue đã lưu.',
            event_code='job_resumed_after_stale',
            resume_marker=True,
        )
        return True

    @api.model
    def _claim_next_runnable_job(self):
        self.env.cr.execute(
            """
            SELECT id
              FROM pancake_message_sync_job
             WHERE state IN ('running', 'stopping')
               AND (
                    runner_claim_token IS NULL
                    OR runner_claimed_at IS NULL
                    OR runner_claimed_at < ((NOW() AT TIME ZONE 'UTC') - INTERVAL '2 minutes')
                    OR COALESCE(last_heartbeat_at, started_at, (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day')
                        < ((NOW() AT TIME ZONE 'UTC') - (COALESCE(stale_timeout_minutes, 10)::text || ' minutes')::interval)
               )
             ORDER BY id ASC
             FOR UPDATE SKIP LOCKED
             LIMIT 1
            """
        )
        row = self.env.cr.fetchone()
        if not row:
            return False, False

        job = self.browse(row[0]).exists()
        if not job:
            return False, False

        claim_token = uuid.uuid4().hex
        was_stale = job._is_stale()
        job.sudo().write({
            'runner_claim_token': claim_token,
            'runner_claimed_at': fields.Datetime.now(),
        })
        if was_stale:
            job._recover_stale_job()
        return job, claim_token

    def _release_claim(self, claim_token=None):
        self.ensure_one()
        if claim_token and self.runner_claim_token and self.runner_claim_token != claim_token:
            return False
        self.sudo().write({
            'runner_claim_token': False,
            'runner_claimed_at': False,
        })
        return True

    def _handle_task_success(self, task, payload):
        self.ensure_one()
        write_vals = {
            'processed_batch_count': int(self.processed_batch_count or 0) + 1,
            'last_checkpoint_at': fields.Datetime.now(),
        }
        if task.task_type == 'page_scan':
            write_vals.update({
                'processed_page_count': int(self.processed_page_count or 0) + 1,
                'completed_page_count': int(self.completed_page_count or 0) + 1,
                'tier3_batch_count': int(self.tier3_batch_count or 0) + 1,
                'current_page_name': task.page_id.name if task.page_id else False,
                'current_priority': 'page_scan',
            })
            if payload.get('conversation_seed_count'):
                write_vals['total_conversation_count'] = int(self.total_conversation_count or 0) + int(payload.get('conversation_seed_count', 0) or 0)
            self.sudo().write(write_vals)
            self._append_log(
                'success',
                f"Page `{payload.get('page_name')}`: quét {payload.get('conversation_seed_count', 0)} conversation, tạo {payload.get('created_message_tasks', 0)} task đồng bộ messages.",
                event_code='page_completed',
                page=task.page_id,
                stats=payload,
            )
        elif task.task_type == 'message_sync':
            write_vals.update({
                'synced_conversation_count': int(self.synced_conversation_count or 0) + 1,
                'tier4_batch_count': int(self.tier4_batch_count or 0) + 1,
                'current_page_name': task.page_id.name if task.page_id else False,
                'current_priority': 'message_sync',
                'total_messages_created': int(self.total_messages_created or 0) + int(payload.get('created_messages', 0) or 0),
                'total_messages_seen': int(self.total_messages_seen or 0) + int(payload.get('fetched_messages', 0) or 0),
                'total_existing_messages': int(self.total_existing_messages or 0) + int(payload.get('existing_messages', 0) or 0),
            })
            self.sudo().write(write_vals)
            self._append_log(
                'success',
                f"[Message] {payload.get('conversation_name')}: tạo {payload.get('created_messages', 0)} tin nhắn mới, đọc {payload.get('fetched_messages', 0)} bản ghi.",
                event_code='task_completed',
                page=task.page_id,
                conversation=task.conversation_id,
                stats=payload,
            )
        else:
            self.sudo().write(write_vals)
            self._append_log('success', 'Finalize task đã hoàn tất.', event_code='task_completed', stats=payload)
        self._refresh_runtime_metrics()

    def _handle_task_retry(self, task, error_message, delay_seconds):
        self.ensure_one()
        self.sudo().write({
            'last_checkpoint_at': fields.Datetime.now(),
            'current_page_name': task.page_id.name if task.page_id else self.current_page_name,
            'current_priority': task.task_type,
        })
        self._append_log(
            'warning',
            f"Task `{task.task_type}` sẽ retry sau {delay_seconds}s: {error_message}",
            event_code='task_retry_scheduled',
            page=task.page_id,
            conversation=task.conversation_id,
            stats={'delay_seconds': delay_seconds, 'attempt_count': task.attempt_count},
        )
        self._refresh_runtime_metrics()

    def _handle_task_failure(self, task, error_message):
        self.ensure_one()
        write_vals = {
            'last_checkpoint_at': fields.Datetime.now(),
            'current_page_name': task.page_id.name if task.page_id else self.current_page_name,
            'current_priority': task.task_type,
        }
        if task.task_type == 'page_scan':
            write_vals['processed_page_count'] = int(self.processed_page_count or 0) + 1
        if task.task_type == 'message_sync':
            write_vals['failed_conversation_count'] = int(self.failed_conversation_count or 0) + 1
        self.sudo().write(write_vals)
        self._append_log(
            'error',
            f"Task `{task.task_type}` thất bại: {error_message}",
            event_code='task_failed',
            page=task.page_id,
            conversation=task.conversation_id,
            stats={'attempt_count': task.attempt_count},
        )
        self._refresh_runtime_metrics()

    def _has_incomplete_tasks(self):
        self.ensure_one()
        return bool(self.task_ids.filtered(lambda task: task.state in ('pending', 'retry', 'running')))

    def _get_recent_completed_tasks(self, limit=20):
        self.ensure_one()
        return self.task_ids.filtered(lambda task: task.state == 'done').sorted(
            key=lambda task: (
                task.finished_at or fields.Datetime.to_datetime('1970-01-01 00:00:00'),
                task.id,
            ),
            reverse=True,
        )[:limit]

    def _process_next_slice(self):
        task_model = self.env['pancake.message.sync.task'].sudo()
        for job in self:
            if job.state not in ('running', 'stopping'):
                continue
            try:
                deadline = fields.Datetime.now() + timedelta(seconds=52)
                job._append_live_log(force=True, message='Runner đã claim job và bắt đầu xử lý task queue.')
                processed_any = False
                while fields.Datetime.now() < deadline:
                    if job._finish_if_stop_requested():
                        break

                    task, claim_token = task_model._claim_next_runnable_task(job)
                    if not task:
                        job._refresh_runtime_metrics()
                        if not job._has_incomplete_tasks():
                            job.sudo().write({
                                'phase': 'finalize',
                                'phase_total_count': 1,
                                'phase_done_count': 0,
                                'phase_progress_percent': 0.0,
                            })
                            final_message = (
                                f'Hoàn tất đồng bộ API queue: {job.synced_conversation_count}/{job.total_conversation_count} conversation đã sync, '
                                f'page hoàn thành {job.completed_page_count}/{job.total_page_count}.'
                            )
                            job._mark_done(final_message)
                        elif not processed_any:
                            job._append_live_log(force=False, message='Runner đang chờ task retry đến hạn hoặc task mới được seed.')
                        break

                    processed_any = True
                    try:
                        job.sudo().write({
                            'phase': task.task_type,
                            'current_page_name': task.page_id.name if task.page_id else job.current_page_name,
                            'current_priority': task.task_type,
                        })
                        task.run_claimed_task()
                        self.env.cr.commit()
                    finally:
                        task._release_claim(claim_token=claim_token)
                        self.env.cr.commit()

                    job._append_live_log(force=False)
                    if job.state not in ('running', 'stopping'):
                        break

                if job.state in ('running', 'stopping'):
                    job._refresh_runtime_metrics()
            except Exception as exc:
                _logger.exception("Pancake API queue job failed: %s", exc)
                job._mark_failed(f'Job lỗi: {exc}')


class PancakeMessageSyncLog(models.Model):
    _name = 'pancake.message.sync.log'
    _description = 'Pancake Message Sync Log'
    _order = 'id desc'

    PARAM_RETENTION_DAYS = 'pancake.message_sync_log_retention_days'
    SOURCE_SELECTION = [
        ('full_sync', 'Đồng bộ toàn bộ'),
        ('continuous', 'Đồng bộ liên tục'),
        ('manual_window', 'Đồng bộ cửa sổ'),
    ]
    CONTINUOUS_LAYER_SELECTION = [
        ('candidate_refresh', 'Cập nhật hội thoại mới'),
        ('same_day', 'Quét tin nhắn trong ngày'),
        ('nightly_two_day', 'Quét cuối ngày 2 ngày gần nhất'),
        ('manual_same_day', 'Quét lại trong ngày'),
        ('manual_recent_72h', 'Quét lại 72 giờ gần nhất'),
    ]

    job_id = fields.Many2one('pancake.message.sync.job', string='Job', required=False, ondelete='cascade', index=True)
    source_type = fields.Selection(
        SOURCE_SELECTION,
        string='Nguồn đồng bộ',
        required=True,
        default='full_sync',
        readonly=True,
    )
    continuous_layer = fields.Selection(
        CONTINUOUS_LAYER_SELECTION,
        string='Lớp continuous',
        readonly=True,
    )
    logged_at = fields.Datetime(string='Thời điểm', required=True, default=lambda self: fields.Datetime.now(), readonly=True)
    level = fields.Selection(
        [('info', 'Info'), ('warning', 'Warning'), ('error', 'Error'), ('success', 'Success')],
        string='Mức log',
        required=True,
        default='info',
        readonly=True,
    )
    phase = fields.Selection(PancakeMessageSyncJob.PHASE_SELECTION, string='Pha', readonly=True)
    event_code = fields.Char(string='Mã sự kiện', readonly=True)
    page_id = fields.Many2one('page.fm.page', string='Page liên quan', readonly=True)
    conversation_id = fields.Many2one('page.fm.conversation', string='Conversation liên quan', readonly=True)
    stats_json = fields.Text(string='Payload thống kê', readonly=True)
    resume_marker = fields.Boolean(string='Đánh dấu phục hồi', readonly=True)
    message = fields.Text(string='Nội dung', required=True, readonly=True)

    @api.model
    def create_continuous_log(
        self,
        layer_key,
        level,
        message,
        event_code=None,
        page_id=None,
        conversation_id=None,
        stats_json=None,
        resume_marker=False,
        source_type='continuous',
    ):
        values = {
            'job_id': False,
            'source_type': source_type or 'continuous',
            'continuous_layer': layer_key,
            'level': level,
            'event_code': event_code,
            'page_id': page_id,
            'conversation_id': conversation_id,
            'stats_json': stats_json,
            'resume_marker': resume_marker,
            'message': message,
        }
        return self.create(values)

    @api.model
    def _get_retention_days(self, retention_days=None):
        if retention_days is not None:
            try:
                return max(int(retention_days), 1)
            except (TypeError, ValueError):
                return 30
        raw_value = self.env['ir.config_parameter'].sudo().get_param(self.PARAM_RETENTION_DAYS, '30')
        try:
            return max(int(raw_value or 30), 1)
        except (TypeError, ValueError):
            return 30

    @api.model
    def cron_cleanup_old_logs(self, retention_days=None):
        retention_days = self._get_retention_days(retention_days)
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        logs = self.search([('logged_at', '<', cutoff)])
        count = len(logs)
        if logs:
            logs.unlink()
        return count
