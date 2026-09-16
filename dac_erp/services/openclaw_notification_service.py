import json
import logging
import time
import uuid
from datetime import timedelta as _dt_timedelta, timezone as _dt_timezone

import requests

from odoo import fields, models


_logger = logging.getLogger(__name__)

# Vietnam UTC+7 — dùng cho tất cả datetime serialization sang OpenClaw
_VN_TZ = _dt_timezone(_dt_timedelta(hours=7))


class OpenclawNotificationService(models.AbstractModel):
    _name = 'dac.openclaw.notification.service'
    _description = 'OpenClaw Notification Service'

    # ── Mapping event_type → route và config param chứa secret ─────────
    _WEBHOOK_ROUTES = {
        'task_assigned': '/hooks/odoo-task-assigned',
        'task_reminder': '/hooks/odoo-reminder',
        'manager_digest': '/hooks/odoo-manager-digest',
    }
    _WEBHOOK_SECRET_PARAMS = {
        'task_assigned': 'dac_erp.openclaw_secret_task_assigned',
        'task_reminder': 'dac_erp.openclaw_secret_task_reminder',
        'manager_digest': 'dac_erp.openclaw_secret_manager_digest',
    }
    # HTTP status codes đủ điều kiện retry (transient server errors)
    _RETRY_HTTP_CODES = frozenset({502, 503, 504})

    # ══════════════════════════════════════════════════════════════════
    # Legacy helpers — được dùng bởi cron daily_digest và escalation
    # Giữ nguyên để không break cron hiện có.
    # ══════════════════════════════════════════════════════════════════

    def _get_base_url(self):
        return (
            self.env['ir.config_parameter'].sudo()
            .get_param('dac_erp.openclaw_base_url') or ''
        ).strip().rstrip('/')

    def _get_timeout(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_timeout_seconds', '15'
        )
        try:
            return max(1, int(raw))
        except Exception:
            return 15

    def _get_headers(self):
        headers = {'Content-Type': 'application/json'}
        webhook_key = (
            self.env['ir.config_parameter'].sudo()
            .get_param('dac_erp.openclaw_webhook_key') or ''
        ).strip()
        if webhook_key:
            headers['X-OpenClaw-Webhook-Key'] = webhook_key
        return headers

    def _build_url(self, route_path):
        base_url = self._get_base_url()
        if not base_url:
            return ''
        return '%s/%s' % (base_url, route_path.lstrip('/'))

    def build_event_id(self, event_type, mapping, task=None, suffix=None):
        task_part = str(task.id) if task else 'na'
        suffix_part = suffix or fields.Datetime.now().strftime('%Y%m%d%H%M%S')
        return '%s-%s-%s-%s' % (event_type, mapping.id, task_part, suffix_part)

    def task_to_payload(self, task):
        return {
            'id': task.id,
            'name': task.name,
            'description': task.description or None,
            'state': task.state,
            'priority': task.priority,
            'deadline': task.deadline.isoformat() if task.deadline else None,
            'order_id': task.order_id.id if task.order_id else None,
            'order_name': task.order_id.name if task.order_id else None,
            'assigned_user_id': task.assigned_user_id.id if task.assigned_user_id else None,
            'assigned_user_name': task.assigned_user_id.name if task.assigned_user_id else None,
            'created_by_agent': task.created_by_agent or None,
            'notes': task.notes or None,
            'create_date': task.create_date.isoformat() if task.create_date else None,
            'write_date': task.write_date.isoformat() if task.write_date else None,
        }

    def build_payload(self, event_type, mapping, tasks=None, summary=None, event_id=None):
        tasks = tasks or self.env['dac.work.task']
        task_payloads = [self.task_to_payload(task) for task in tasks]
        return {
            'event_type': event_type,
            'event_id': event_id or str(uuid.uuid4()),
            'occurred_at': fields.Datetime.now().isoformat(),
            'recipient': {
                'odoo_user_id': mapping.user_id.id,
                'role': mapping.role,
                'notification': {
                    'channel': mapping.channel,
                    'target': mapping.target,
                },
            },
            'task': task_payloads[0] if len(task_payloads) == 1 else None,
            'tasks': task_payloads if len(task_payloads) != 1 else None,
            'summary': summary or None,
            'meta': {
                'source': 'odoo',
                'source_version': 'mcp/v1',
            },
        }

    def send_payload(self, route_path, payload, mapping=None, task=None):
        event_id = payload.get('event_id') or str(uuid.uuid4())
        Log = self.env['dac.openclaw.notification.log'].sudo()
        existing = Log.search([('event_id', '=', event_id)], limit=1)
        if existing:
            return existing

        log_vals = {
            'event_id': event_id,
            'event_type': payload.get('event_type'),
            'mapping_id': mapping.id if mapping else False,
            'user_id': mapping.user_id.id if mapping and mapping.user_id else False,
            'task_id': task.id if task else False,
            'payload_json': json.dumps(payload, ensure_ascii=False, default=str),
            'status': 'pending',
        }
        log = Log.create(log_vals)

        url = self._build_url(route_path)
        if not url:
            log.write({'status': 'failed', 'error_message': 'Thiếu cấu hình dac_erp.openclaw_base_url'})
            return log

        try:
            response = requests.post(
                url,
                data=json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'),
                headers=self._get_headers(),
                timeout=self._get_timeout(),
            )
            response_text = response.text
            response.raise_for_status()
            log.write({
                'status': 'sent',
                'response_json': response_text,
                'sent_at': fields.Datetime.now(),
            })
        except Exception as exc:
            _logger.warning('OpenClaw webhook send failed: %s', exc)
            log.write({'status': 'failed', 'error_message': str(exc)})
        return log

    # ══════════════════════════════════════════════════════════════════
    # Phần 2: Webhook sender theo OpenClaw contract
    # ══════════════════════════════════════════════════════════════════

    def _to_vn_iso(self, dt):
        """Chuyển datetime UTC của Odoo sang ISO 8601 +07:00 (Vietnam timezone).

        Odoo lưu tất cả datetime dưới dạng UTC naive. Hàm này attach UTC
        rồi astimezone sang +07:00 để OpenClaw hiển thị giờ đúng cho user VN.
        """
        if not dt:
            return None
        return dt.replace(tzinfo=_dt_timezone.utc).astimezone(_VN_TZ).isoformat()

    def _build_openclaw_payload(self, task, mapping):
        """Build payload theo contract bắt buộc của OpenClaw:

        {
          "task": { id, name, state, priority, order_name, deadline,
                    remind_at, description, notes, assigned_user_name },
          "delivery": { "channel": ..., "target": ... },
          "reply_context": {          # always present — new field, backward compat
            "kind": "personal_reminder" | "task_reminder",
            "task_id": int,
            "task_name": str,
            "assigned_user_id": int | null,
            "remind_at": str | null   # only for personal_reminder
          }
        }

        reply_context.kind:
          "personal_reminder" — task.is_personal_reminder=True; OpenClaw can
            wire "xong rồi" reply directly to complete_personal_reminder with
            the embedded task_id, skipping latest_open disambiguation.
          "task_reminder" — regular (non-personal) task; OpenClaw uses for
            informational context only, no auto-complete flow.

        deadline và remind_at được serialize với timezone +07:00.
        """
        assigned_user_id = task.assigned_user_id.id if task.assigned_user_id else None
        is_personal = bool(getattr(task, 'is_personal_reminder', False))

        if is_personal:
            reply_context = {
                'kind': 'personal_reminder',
                'task_id': task.id,
                'task_name': task.name,
                'assigned_user_id': assigned_user_id,
                'remind_at': self._to_vn_iso(task.remind_at),
            }
        else:
            reply_context = {
                'kind': 'task_reminder',
                'task_id': task.id,
                'task_name': task.name,
                'assigned_user_id': assigned_user_id,
            }

        return {
            'task': {
                'id': task.id,
                'name': task.name,
                'state': task.state,
                'priority': task.priority,
                'order_name': task.order_id.name if task.order_id else None,
                'deadline': self._to_vn_iso(task.deadline),
                'remind_at': self._to_vn_iso(task.remind_at),
                'description': task.description or None,
                'notes': task.notes or None,
                'assigned_user_name': (
                    task.assigned_user_id.name if task.assigned_user_id else None
                ),
            },
            'delivery': {
                'channel': mapping.channel,
                'target': mapping.target,
            },
            'reply_context': reply_context,
        }

    def _inject_reply_context_tracking(self, payload, event_type, event_id):
        """Inject event_type + event_id into reply_context (immutable — returns new dict).

        Only acts when reply_context is already a dict (backward compat: no-op otherwise).
        Called in _send_openclaw_webhook after event_id is finalized so OpenClaw can
        correlate replies back to the exact notification event.
        """
        if not isinstance(payload.get('reply_context'), dict):
            return payload
        new_rc = dict(payload['reply_context'])
        new_rc['event_type'] = event_type
        new_rc['event_id'] = event_id
        return dict(payload, reply_context=new_rc)

    def _get_openclaw_webhook_config(self, event_type):
        """Trả về (url, headers) cho event_type cụ thể.

        Mỗi event_type có route riêng và secret Bearer riêng được đọc từ
        ir.config_parameter để không hardcode vào code.

        :raises ValueError: nếu event_type không nằm trong _WEBHOOK_ROUTES.
        :return: (url, headers) — cả hai là None nếu openclaw_base_url chưa có.
        """
        if event_type not in self._WEBHOOK_ROUTES:
            raise ValueError(
                'event_type không hợp lệ: %r. Hợp lệ: %s'
                % (event_type, ', '.join(sorted(self._WEBHOOK_ROUTES)))
            )
        ICP = self.env['ir.config_parameter'].sudo()
        base_url = (ICP.get_param('dac_erp.openclaw_base_url') or '').strip().rstrip('/')
        if not base_url:
            return None, None

        url = base_url + self._WEBHOOK_ROUTES[event_type]
        secret = (ICP.get_param(self._WEBHOOK_SECRET_PARAMS[event_type]) or '').strip()
        headers = {'Content-Type': 'application/json'}
        if secret:
            headers['Authorization'] = 'Bearer %s' % secret
        return url, headers

    def _send_openclaw_webhook(self, event_type, payload, task=None, mapping=None, event_id=None):
        """Gửi payload đến OpenClaw với retry và log.

        - Kiểm tra idempotency qua event_id trước khi gửi.
        - Retry tối đa 2 lần (3 lần total) với delay 2s / 4s cho:
            HTTP 502/503/504, Timeout, ConnectionError.
        - Không retry cho các HTTP error khác (4xx, 5xx ngoài list retry).
        - Secret không được log — chỉ log URL, event_type, task id, user.

        :param event_type: 'task_assigned' | 'task_reminder' | 'manager_digest'
        :param payload: dict đã build bởi _build_openclaw_payload() hoặc digest builder
        :param task: dac.work.task record (optional, dùng cho log)
        :param mapping: dac.openclaw.user.mapping record (optional, dùng cho log + event_id)
        :param event_id: stable event_id do caller cung cấp (dùng cho digest anti-spam).
               Nếu None, tự sinh từ build_event_id.
        :return: True nếu gửi thành công, False nếu thất bại hoặc bỏ qua.
        """
        url, headers = self._get_openclaw_webhook_config(event_type)
        if not url:
            _logger.warning(
                'openclaw: openclaw_base_url chưa cấu hình, bỏ qua %s task=%s',
                event_type, task.id if task else None,
            )
            return False

        # Caller có thể truyền event_id ổn định (digest) hoặc để tự sinh
        if event_id is None:
            event_id = (
                self.build_event_id(event_type, mapping, task=task)
                if mapping else str(uuid.uuid4())
            )
        Log = self.env['dac.openclaw.notification.log'].sudo()
        if Log.search_count([('event_id', '=', event_id)]) > 0:
            _logger.info(
                'openclaw: %s event_id=%s đã tồn tại, bỏ qua', event_type, event_id
            )
            return False

        payload = self._inject_reply_context_tracking(payload, event_type, event_id)
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        log = Log.create({
            'event_id': event_id,
            'event_type': event_type,
            'mapping_id': mapping.id if mapping else False,
            'user_id': mapping.user_id.id if mapping and mapping.user_id else False,
            'task_id': task.id if task else False,
            'payload_json': payload_json,
            'status': 'pending',
        })

        payload_bytes = payload_json.encode('utf-8')
        timeout = self._get_timeout()
        last_error = None

        for attempt in range(3):
            if attempt:
                time.sleep(attempt * 2)  # 2s sau attempt 1, 4s sau attempt 2
            try:
                resp = requests.post(
                    url, data=payload_bytes, headers=headers, timeout=timeout
                )
                if resp.status_code in self._RETRY_HTTP_CODES:
                    last_error = 'HTTP %d' % resp.status_code
                    _logger.warning(
                        'openclaw: %s attempt %d/3 → %d, retrying...',
                        event_type, attempt + 1, resp.status_code,
                    )
                    continue

                resp.raise_for_status()

                # ── Gửi thành công ──────────────────────────────────
                _logger.info(
                    'openclaw %s: sent task=%s user=%s channel=%s status=%s',
                    event_type,
                    task.id if task else '-',
                    mapping.user_id.name if mapping and mapping.user_id else '-',
                    mapping.channel if mapping else '-',
                    resp.status_code,
                )
                log.write({
                    'status': 'sent',
                    'response_json': (resp.text or '')[:500],
                    'sent_at': fields.Datetime.now(),
                })
                return True

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = '%s: %s' % (type(exc).__name__, exc)
                _logger.warning(
                    'openclaw: %s attempt %d/3 %s, retrying...',
                    event_type, attempt + 1, type(exc).__name__,
                )
            except requests.exceptions.RequestException as exc:
                # Non-retriable (e.g. 401, 403, 400) — không retry
                last_error = str(exc)
                break

        log.write({'status': 'failed', 'error_message': last_error})
        _logger.warning(
            'openclaw %s: failed after retries task=%s error=%s',
            event_type, task.id if task else None, last_error,
        )
        return False
