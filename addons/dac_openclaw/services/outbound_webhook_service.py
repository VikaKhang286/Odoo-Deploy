# -*- coding: utf-8 -*-
"""Outbound webhook dispatcher cho OpenClaw integration.

Pattern sử dụng:
    env['dac_openclaw.outbound.webhook.log'].sudo().enqueue_event(
        event_type='order.stage_changed',
        data={'order_id': 123, 'old_stage': 'quotation', 'new_stage': 'deposit'},
        sale_order_id=order.id,
    )

Sau khi enqueue, log row được tạo với state='pending'. Cron `cron_dispatch_pending_webhooks`
chạy mỗi 1 phút (config trong data/cron_data.xml) sẽ pick up và gửi HTTP POST với HMAC.

Cấu hình:
- ICP `dac_openclaw.webhook_url`     : URL của OpenClaw nhận events
- ICP `dac_openclaw.webhook_secret`  : HMAC secret (chia sẻ với OpenClaw)
- ICP `dac_openclaw.webhook_enabled` : 'true'/'false' (default 'false')
- ICP `dac_openclaw.webhook_max_retry` : số lần retry tối đa (default 3)
- ICP `dac_openclaw.webhook_timeout` : timeout giây (default 10)

Retry backoff:
- Attempt 1: 0s
- Attempt 2: 30s
- Attempt 3: 5 phút
- Attempt 4: 30 phút
- > max_retry → state='giveup'
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta

import requests

from odoo import api, fields, models, tools


_logger = logging.getLogger(__name__)


# Backoff bảng theo retry count (giây)
RETRY_BACKOFF_SECONDS = [0, 30, 300, 1800]


class DacOpenclawOutboundWebhookLog(models.Model):
    _inherit = 'dac_openclaw.outbound.webhook.log'

    # ICP keys
    ICP_WEBHOOK_URL = 'dac_openclaw.webhook_url'
    ICP_WEBHOOK_SECRET = 'dac_openclaw.webhook_secret'
    ICP_WEBHOOK_ENABLED = 'dac_openclaw.webhook_enabled'
    ICP_WEBHOOK_MAX_RETRY = 'dac_openclaw.webhook_max_retry'
    ICP_WEBHOOK_TIMEOUT = 'dac_openclaw.webhook_timeout'

    @api.model
    def _is_webhook_enabled(self):
        icp = self.env['ir.config_parameter'].sudo()
        value = (icp.get_param(self.ICP_WEBHOOK_ENABLED) or '').strip().lower()
        return value in ('1', 'true', 'yes', 'on')

    @api.model
    def _get_webhook_url(self):
        icp = self.env['ir.config_parameter'].sudo()
        return (icp.get_param(self.ICP_WEBHOOK_URL) or '').strip()

    @api.model
    def _get_webhook_secret(self):
        icp = self.env['ir.config_parameter'].sudo()
        return (icp.get_param(self.ICP_WEBHOOK_SECRET) or '').strip()

    @api.model
    def _get_max_retry(self):
        icp = self.env['ir.config_parameter'].sudo()
        raw = (icp.get_param(self.ICP_WEBHOOK_MAX_RETRY) or '').strip()
        try:
            value = int(raw)
            if value < 0:
                return 3
            return value
        except (ValueError, TypeError):
            return 3

    @api.model
    def _get_timeout_seconds(self):
        icp = self.env['ir.config_parameter'].sudo()
        raw = (icp.get_param(self.ICP_WEBHOOK_TIMEOUT) or '').strip()
        try:
            value = int(raw)
            if value < 1:
                return 10
            return value
        except (ValueError, TypeError):
            return 10

    @api.model
    def enqueue_event(self, event_type, data, sale_order_id=None,
                       conversation_id=None, task_id=None, partner_id=None,
                       event_id=None):
        """Tạo log entry với state='pending' để cron pick up.

        Trả về log record. Nếu webhook bị disable, log state='skipped' nhưng vẫn lưu để audit.
        """
        if not event_id:
            event_id = str(uuid.uuid4())

        # Build full payload theo schema chuẩn
        payload = {
            'event': event_type,
            'event_id': event_id,
            'occurred_at': fields.Datetime.now().isoformat(),
            'data': data or {},
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

        # Tính signature ngay khi enqueue (lưu vào log để debug/replay)
        secret = self._get_webhook_secret()
        signature = ''
        if secret:
            signature = hmac.new(
                secret.encode('utf-8'),
                payload_json.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()

        state = 'pending' if self._is_webhook_enabled() else 'skipped'

        vals = {
            'event_id': event_id,
            'event_type': event_type,
            'occurred_at': fields.Datetime.now(),
            'payload_json': payload_json,
            'signature': signature,
            'state': state,
        }
        if sale_order_id:
            vals['sale_order_id'] = sale_order_id
        if conversation_id:
            vals['conversation_id'] = conversation_id
        if task_id:
            vals['task_id'] = task_id
        if partner_id:
            vals['partner_id'] = partner_id

        log = self.sudo().create(vals)
        if state == 'skipped':
            _logger.info("Outbound webhook %s skipped (disabled). event_id=%s",
                         event_type, event_id)
        return log

    def _send_one(self):
        """Gửi 1 event qua HTTP POST với HMAC. Self phải là single record."""
        self.ensure_one()
        url = self._get_webhook_url()
        if not url:
            self.write({
                'state': 'failed',
                'error_message': 'webhook URL not configured',
                'last_attempt_at': fields.Datetime.now(),
            })
            return False

        self.write({'state': 'sending', 'last_attempt_at': fields.Datetime.now()})

        headers = {
            'Content-Type': 'application/json',
            'X-OpenClaw-Signature': 'sha256=' + (self.signature or ''),
            'X-OpenClaw-Event-Id': self.event_id,
            'X-OpenClaw-Event-Type': self.event_type,
        }
        timeout = self._get_timeout_seconds()

        try:
            response = requests.post(
                url,
                data=self.payload_json.encode('utf-8'),
                headers=headers,
                timeout=(timeout, timeout),
            )
            status_code = response.status_code
            body = (response.text or '')[:4000]  # cap to 4KB
            if 200 <= status_code < 300:
                self.write({
                    'state': 'sent',
                    'http_status_code': status_code,
                    'response_body': body,
                    'target_url': url,
                    'next_retry_at': False,
                })
                return True
            # Non-2xx → fail with retry
            self._schedule_retry(
                error=f"HTTP {status_code}: {body[:500]}",
                http_status_code=status_code,
                response_body=body,
                target_url=url,
            )
            return False
        except requests.exceptions.RequestException as exc:
            self._schedule_retry(
                error="RequestException: %s" % str(exc),
                http_status_code=None,
                response_body=None,
                target_url=url,
            )
            return False
        except Exception as exc:
            _logger.exception("Outbound webhook unexpected error event_id=%s", self.event_id)
            self._schedule_retry(
                error="Unexpected: %s" % str(exc),
                http_status_code=None,
                response_body=None,
                target_url=url,
            )
            return False

    def _schedule_retry(self, error, http_status_code=None, response_body=None, target_url=None):
        """Cập nhật log và schedule retry hoặc giveup nếu hết retry."""
        self.ensure_one()
        max_retry = self._get_max_retry()
        new_retry_count = self.retry_count + 1
        if new_retry_count > max_retry:
            self.write({
                'state': 'giveup',
                'retry_count': new_retry_count,
                'error_message': error,
                'http_status_code': http_status_code or False,
                'response_body': response_body or False,
                'target_url': target_url or False,
                'next_retry_at': False,
            })
            _logger.error("Outbound webhook giveup after %s tries. event_id=%s err=%s",
                          new_retry_count, self.event_id, error)
            return

        # Schedule next retry
        backoff_index = min(new_retry_count, len(RETRY_BACKOFF_SECONDS) - 1)
        backoff = RETRY_BACKOFF_SECONDS[backoff_index]
        next_retry = fields.Datetime.now() + timedelta(seconds=backoff)
        self.write({
            'state': 'failed',
            'retry_count': new_retry_count,
            'error_message': error,
            'http_status_code': http_status_code or False,
            'response_body': response_body or False,
            'target_url': target_url or False,
            'next_retry_at': next_retry,
        })

    @api.model
    def cron_dispatch_pending_webhooks(self):
        """Cron pick up pending + failed-due-for-retry events và gửi. Chạy mỗi 1 phút.

        Không raise — log error rồi continue. Mỗi run xử lý tối đa 50 events.
        """
        if not self._is_webhook_enabled():
            return
        now = fields.Datetime.now()
        domain = [
            '|',
            ('state', '=', 'pending'),
            '&', ('state', '=', 'failed'), ('next_retry_at', '<=', now),
        ]
        batch = self.sudo().search(domain, order='id asc', limit=50)
        # Trong test mode, không gọi commit/rollback trên cursor (Odoo cấm)
        test_mode = tools.config.get('test_enable') or bool(self.env.registry.in_test_mode())
        for rec in batch:
            try:
                rec._send_one()
                if not test_mode:
                    self.env.cr.commit()
            except Exception as exc:
                _logger.exception("cron_dispatch_pending_webhooks failure event_id=%s",
                                  rec.event_id)
                # Đảm bảo log entry không bị stuck ở 'sending'
                try:
                    rec.write({'state': 'failed',
                               'error_message': "cron error: %s" % exc,
                               'next_retry_at': now + timedelta(minutes=5)})
                    if not test_mode:
                        self.env.cr.commit()
                except Exception:
                    if not test_mode:
                        self.env.cr.rollback()
