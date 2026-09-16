import json
import logging
import uuid
from datetime import timedelta

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PancakeMessageSyncTask(models.Model):
    _name = 'pancake.message.sync.task'
    _description = 'Pancake Message Sync Task'
    _order = 'priority desc, id asc'

    TASK_TYPE_SELECTION = [
        ('page_scan', 'Pha 1 - Quét conversation'),
        ('message_sync', 'Pha 2 - Đồng bộ tin nhắn'),
        ('finalize', 'Pha 3 - Hoàn tất'),
    ]
    STATE_SELECTION = [
        ('pending', 'Chờ chạy'),
        ('running', 'Đang chạy'),
        ('retry', 'Chờ thử lại'),
        ('done', 'Hoàn tất'),
        ('failed', 'Lỗi'),
    ]

    job_id = fields.Many2one('pancake.message.sync.job', string='Job', required=True, ondelete='cascade', index=True)
    task_type = fields.Selection(TASK_TYPE_SELECTION, string='Task Type', required=True, index=True)
    page_id = fields.Many2one('page.fm.page', string='Page', index=True)
    conversation_id = fields.Many2one('page.fm.conversation', string='Conversation', index=True)
    state = fields.Selection(STATE_SELECTION, string='State', required=True, default='pending', index=True)
    priority = fields.Integer(string='Priority', default=100, index=True)
    payload_json = fields.Text(string='Payload')
    attempt_count = fields.Integer(string='Attempts', default=0)
    max_attempts = fields.Integer(string='Max Attempts', default=3)
    next_run_at = fields.Datetime(string='Next Run At', default=lambda self: fields.Datetime.now(), index=True)
    claimed_at = fields.Datetime(string='Claimed At')
    claim_token = fields.Char(string='Claim Token')
    last_error = fields.Text(string='Last Error')
    started_at = fields.Datetime(string='Started At')
    finished_at = fields.Datetime(string='Finished At')
    duration_ms = fields.Integer(string='Duration (ms)')

    _sql_constraints = [
        (
            'pancake_task_unique_message_sync',
            "unique(job_id, task_type, page_id, conversation_id)",
            'Task message sync đã tồn tại cho conversation này trong cùng job.',
        ),
    ]

    @api.model
    def _json_dumps(self, payload):
        if not payload:
            return False
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _json_loads(self):
        self.ensure_one()
        if not self.payload_json:
            return {}
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    @api.model
    def _task_deadline(self):
        return fields.Datetime.now() - timedelta(minutes=2)

    @api.model
    def _claim_next_runnable_task(self, job):
        self.env.cr.execute(
            """
            SELECT id
              FROM pancake_message_sync_task
             WHERE job_id = %s
               AND (
                    (state IN ('pending', 'retry') AND COALESCE(next_run_at, (NOW() AT TIME ZONE 'UTC')) <= (NOW() AT TIME ZONE 'UTC'))
                    OR
                    (state = 'running' AND COALESCE(claimed_at, (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day') < ((NOW() AT TIME ZONE 'UTC') - INTERVAL '2 minutes'))
               )
             ORDER BY priority DESC, id ASC
             FOR UPDATE SKIP LOCKED
             LIMIT 1
            """,
            [job.id],
        )
        row = self.env.cr.fetchone()
        if not row:
            return False, False

        task = self.browse(row[0]).exists()
        if not task:
            return False, False

        claim_token = uuid.uuid4().hex
        now = fields.Datetime.now()
        values = {
            'state': 'running',
            'claim_token': claim_token,
            'claimed_at': now,
            'attempt_count': int(task.attempt_count or 0) + 1,
        }
        if not task.started_at:
            values['started_at'] = now
        task.sudo().write(values)
        return task, claim_token

    def _release_claim(self, claim_token=None):
        self.ensure_one()
        if claim_token and self.claim_token and claim_token != self.claim_token:
            return False
        self.sudo().write({
            'claim_token': False,
            'claimed_at': False,
        })
        return True

    @api.model
    def _classify_error(self, error_message, response_status=None):
        message = (error_message or '').strip().lower()
        if response_status in (429, 500, 502, 503, 504):
            return 'retry'
        if any(
            keyword in message
            for keyword in ('timeout', 'timed out', 'connection', 'rate limit', 'too many requests', 'temporarily unavailable')
        ):
            return 'retry'
        if 'http 5' in message:
            return 'retry'
        return 'failed'

    def _retry_delay_seconds(self):
        self.ensure_one()
        return min(2 ** max(int(self.attempt_count or 1), 1), 300)

    def _mark_retry(self, error_message):
        self.ensure_one()
        delay_seconds = self._retry_delay_seconds()
        next_run_at = fields.Datetime.now() + timedelta(seconds=delay_seconds)
        self.sudo().write({
            'state': 'retry',
            'next_run_at': next_run_at,
            'last_error': error_message,
            'duration_ms': int(max((fields.Datetime.now() - (self.started_at or fields.Datetime.now())).total_seconds(), 0.0) * 1000),
        })
        return delay_seconds

    def _mark_failed(self, error_message):
        self.ensure_one()
        started_at = self.started_at or fields.Datetime.now()
        self.sudo().write({
            'state': 'failed',
            'last_error': error_message,
            'finished_at': fields.Datetime.now(),
            'duration_ms': int(max((fields.Datetime.now() - started_at).total_seconds(), 0.0) * 1000),
        })

    def _mark_done(self, payload=None):
        self.ensure_one()
        started_at = self.started_at or fields.Datetime.now()
        self.sudo().write({
            'state': 'done',
            'payload_json': self._json_dumps(payload),
            'finished_at': fields.Datetime.now(),
            'last_error': False,
            'duration_ms': int(max((fields.Datetime.now() - started_at).total_seconds(), 0.0) * 1000),
        })

    def _ensure_page(self):
        self.ensure_one()
        page = self.page_id.exists()
        if not page:
            raise ValueError(_('Task không còn page hợp lệ để xử lý.'))
        return page

    def _ensure_conversation(self):
        self.ensure_one()
        conversation = self.conversation_id.exists()
        if not conversation:
            raise ValueError(_('Task không còn conversation hợp lệ để xử lý.'))
        return conversation

    def _run_page_scan(self):
        self.ensure_one()
        job = self.job_id
        page = self._ensure_page()
        page_model = self.env['page.fm.page'].sudo()
        token_result = page_model._check_main_access_token(store=True)
        if token_result.get('status') != 'valid':
            raise ValueError(token_result.get('message') or _('Main access token không hợp lệ.'))

        main_access_token = page_model._get_main_access_token()
        conversations = page._fetch_conversations_for_page_record(
            main_access_token,
            job=job,
            phase_label='page_scan',
            raise_on_error=True,
        )
        if conversations:
            page._create_or_update_conversations(conversations)

        conversation_model = self.env['page.fm.conversation'].sudo()
        pending_domain = [
            ('page_fm_page_id', '=', page.id),
            '|',
            ('last_message_sync_fm', '=', False),
            ('last_message_sync_fm', '<', job.started_at),
        ]
        target_conversations = conversation_model.search(pending_domain, order='updated_at_fm desc, id desc')
        existing_task_convs = set(
            self.search([
                ('job_id', '=', job.id),
                ('task_type', '=', 'message_sync'),
                ('conversation_id', 'in', target_conversations.ids),
            ]).mapped('conversation_id').ids
        )
        task_values = []
        for conversation in target_conversations:
            if conversation.id in existing_task_convs:
                continue
            priority = 200
            if not conversation.partner_id:
                priority = 260
            elif conversation.require_processing:
                priority = 240
            elif conversation.is_unread_fm:
                priority = 220
            task_values.append({
                'job_id': job.id,
                'task_type': 'message_sync',
                'page_id': page.id,
                'conversation_id': conversation.id,
                'state': 'pending',
                'priority': priority,
                'next_run_at': fields.Datetime.now(),
                'max_attempts': 4,
            })
        if task_values:
            self.create(task_values)

        return {
            'task_type': 'page_scan',
            'page_id': page.id,
            'page_name': page.name,
            'conversation_seed_count': len(target_conversations),
            'created_message_tasks': len(task_values),
        }

    def _run_message_sync(self):
        self.ensure_one()
        conversation = self._ensure_conversation()
        result = conversation.action_sync_messages(
            return_stats=True,
            allowed_page_ids=self.job_id._selected_page_ids(),
            sync_scope='selected_pages',
            sync_origin='manual_full',
        )
        if result.get('status') == 'error':
            error_message = result.get('error') or _('Không đồng bộ được messages.')
            raise ValueError(error_message)
        payload = {
            'task_type': 'message_sync',
            'conversation_id': conversation.id,
            'page_id': conversation.page_fm_page_id.id,
            'conversation_name': conversation.display_name,
            'created_messages': int(result.get('created_messages', 0) or 0),
            'existing_messages': int(result.get('existing_messages', 0) or 0),
            'fetched_messages': int(result.get('fetched_messages', 0) or 0),
        }
        return payload

    def _run_finalize(self):
        self.ensure_one()
        return {'task_type': 'finalize'}

    def run_claimed_task(self):
        self.ensure_one()
        job = self.job_id
        try:
            if self.task_type == 'page_scan':
                payload = self._run_page_scan()
            elif self.task_type == 'message_sync':
                payload = self._run_message_sync()
            else:
                payload = self._run_finalize()
            self._mark_done(payload=payload)
            job._handle_task_success(self, payload)
            return {'status': 'done', 'payload': payload}
        except requests.exceptions.RequestException as exc:
            message = str(exc)
            policy = self._classify_error(message, getattr(getattr(exc, 'response', None), 'status_code', None))
            if policy == 'retry' and int(self.attempt_count or 0) < int(self.max_attempts or 1):
                delay_seconds = self._mark_retry(message)
                job._handle_task_retry(self, message, delay_seconds)
                return {'status': 'retry', 'error': message, 'delay_seconds': delay_seconds}
            self._mark_failed(message)
            job._handle_task_failure(self, message)
            return {'status': 'failed', 'error': message}
        except Exception as exc:
            message = str(exc)
            policy = self._classify_error(message)
            if policy == 'retry' and int(self.attempt_count or 0) < int(self.max_attempts or 1):
                delay_seconds = self._mark_retry(message)
                job._handle_task_retry(self, message, delay_seconds)
                return {'status': 'retry', 'error': message, 'delay_seconds': delay_seconds}
            self._mark_failed(message)
            job._handle_task_failure(self, message)
            return {'status': 'failed', 'error': message}
