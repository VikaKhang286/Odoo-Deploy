import logging
from datetime import timedelta, timezone as _dt_timezone

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_VN_TZ = _dt_timezone(timedelta(hours=7))


class OpenclawManagerDigestService(models.AbstractModel):
    """Manager digest service: tổng hợp tiến độ nhóm và gửi qua OpenClaw.

    Callers:
        svc = env['dac.openclaw.manager.digest.service']
        svc._send_manager_digest(manager_mapping)   # single mapping
        svc.cron_send_openclaw_manager_digest()      # all active managers
    """

    _name = 'dac.openclaw.manager.digest.service'
    _description = 'OpenClaw Manager Digest Service'

    # ══════════════════════════════════════════════════════════════════
    # Config helpers
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_digest_top_n(self):
        """Số lượng nhân viên nổi bật hiển thị trong digest. Default 3."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_manager_digest_top_n', '3'
        )
        try:
            return max(1, int(raw))
        except Exception:
            return 3

    @api.model
    def _get_digest_enabled(self):
        """Bật/tắt toàn bộ tính năng manager digest. Default True."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_manager_digest_enabled', 'True'
        )
        return str(raw).lower() not in ('false', '0', 'off', 'no')

    @api.model
    def _get_digest_skip_if_empty(self):
        """Bỏ qua digest nếu nhóm không có task nào. Default True."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_manager_digest_skip_if_empty', 'True'
        )
        return str(raw).lower() not in ('false', '0', 'off', 'no')

    # ══════════════════════════════════════════════════════════════════
    # Core business logic
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_manager_scope_users(self, manager_mapping):
        """Trả về list user_ids trong scope của manager (không gồm manager).

        Chỉ hoạt động với role='manager'. Admin và employee trả về [].
        Nếu manager_user_ids rỗng → trả [] (caller sẽ skip).
        """
        if not manager_mapping or manager_mapping.role != 'manager':
            return []
        return list(manager_mapping.manager_user_ids.ids)

    @api.model
    def _get_digest_event_id(self, mapping_id, now):
        """Tạo event_id ổn định cho một period (AM/PM theo giờ VN).

        Format: manager_digest-{mapping_id}-{yyyymmdd}-{am|pm}
        Đảm bảo anti-spam: cùng period → cùng event_id → không gửi lại.
        """
        vn_now = now.replace(tzinfo=_dt_timezone.utc).astimezone(_VN_TZ)
        period = 'am' if vn_now.hour < 12 else 'pm'
        return 'manager_digest-%d-%s-%s' % (mapping_id, vn_now.strftime('%Y%m%d'), period)

    @api.model
    def _get_manager_task_summary(self, manager_mapping, now=None):
        """Lấy summary tổng hợp task của tất cả nhân viên trong scope.

        Delegates sang dac.openclaw.summary.service (không N+1).
        Trả về None nếu scope rỗng.
        """
        now = now or fields.Datetime.now()
        scope_user_ids = self._get_manager_scope_users(manager_mapping)
        if not scope_user_ids:
            return None
        return self.env['dac.openclaw.summary.service']._get_task_progress_summary(
            now=now, user_ids=scope_user_ids, include_unassigned=False,
        )

    @api.model
    def _user_urgency_score(self, user_entry):
        """Tính điểm ưu tiên của một nhân viên để xếp hạng trong digest.

        Score = overdue*100 + due_soon*10 + reminder_due*5 + in_progress
        """
        m = user_entry.get('metrics', {})
        return (
            m.get('overdue_tasks', 0) * 100
            + m.get('due_soon_tasks', 0) * 10
            + m.get('reminder_due_tasks', 0) * 5
            + m.get('in_progress_tasks', 0)
        )

    @api.model
    def _build_manager_digest_message(self, summary, manager_mapping):
        """Tạo nội dung digest văn bản ngắn gọn bằng tiếng Việt.

        Top N nhân viên được chọn theo urgency score (cao nhất trước).
        Nội dung plain-text; OpenClaw tự xử lý rendering cho từng channel.
        """
        top_n = self._get_digest_top_n()
        totals = summary.get('totals', {})
        users = summary.get('users', [])
        generated_at = summary.get('generated_at', '')

        ranked = sorted(users, key=self._user_urgency_score, reverse=True)
        top_users = ranked[:top_n]

        manager_name = (
            manager_mapping.user_id.name if manager_mapping.user_id else 'Manager'
        )

        # "07:30 15/05/2026" từ ISO "2026-05-15T07:30:00+07:00"
        if len(generated_at) >= 10:
            time_label = (
                generated_at[11:16] + ' '
                + generated_at[8:10] + '/'
                + generated_at[5:7] + '/'
                + generated_at[:4]
            )
        else:
            time_label = generated_at

        lines = [
            '[Digest] Bao cao tien do nhom %s' % manager_name,
            'Thoi gian: %s' % time_label,
            'Tong: %d task | %d dang lam | %d qua han | %d sap het han' % (
                totals.get('total_tasks', 0),
                totals.get('in_progress_tasks', 0),
                totals.get('overdue_tasks', 0),
                totals.get('due_soon_tasks', 0),
            ),
            '',
            'Top %d thanh vien can chu y:' % min(top_n, len(top_users)) if top_users else 'Nhan vien:',
        ]

        for i, u in enumerate(top_users, 1):
            m = u.get('metrics', {})
            overdue = m.get('overdue_tasks', 0)
            due_soon = m.get('due_soon_tasks', 0)
            in_progress = m.get('in_progress_tasks', 0)
            status_parts = []
            if overdue:
                status_parts.append('%d qua han' % overdue)
            if due_soon:
                status_parts.append('%d sap het' % due_soon)
            if in_progress and not overdue and not due_soon:
                status_parts.append('%d dang lam' % in_progress)
            status_str = ', '.join(status_parts) if status_parts else 'binh thuong'
            lines.append(
                '%d. %s: %d task (%s)' % (
                    i, u.get('user_name', '?'), m.get('total_tasks', 0), status_str
                )
            )

        if not top_users:
            lines.append('(khong co du lieu)')

        return '\n'.join(lines)

    @api.model
    def _send_manager_digest(self, manager_mapping, now=None):
        """Gửi digest cho một manager mapping.

        Luồng:
          1. Kiểm tra digest_enabled trên mapping.
          2. Lấy scope users — nếu rỗng → skip.
          3. Kiểm tra anti-spam theo event_id period (AM/PM).
          4. Lấy summary; nếu không có task đáng chú ý → skip (configurable).
          5. Build message + payload, gửi qua notification service.

        :param manager_mapping: dac.openclaw.user.mapping (role='manager')
        :param now: datetime UTC naive (inject trong tests)
        :return: 'sent' | 'skipped' | 'failed' | 'no_scope' | 'already_sent'
        """
        now = now or fields.Datetime.now()

        if not manager_mapping.digest_enabled:
            return 'skipped'

        scope_user_ids = self._get_manager_scope_users(manager_mapping)
        if not scope_user_ids:
            _logger.info(
                'openclaw manager_digest: mapping %d không có scope users, bỏ qua',
                manager_mapping.id,
            )
            return 'no_scope'

        event_id = self._get_digest_event_id(manager_mapping.id, now)

        # Anti-spam: đã gửi trong period này chưa?
        Log = self.env['dac.openclaw.notification.log'].sudo()
        if Log.search_count([('event_id', '=', event_id)]) > 0:
            _logger.info(
                'openclaw manager_digest: event_id=%s đã tồn tại, bỏ qua', event_id
            )
            return 'already_sent'

        summary = self._get_manager_task_summary(manager_mapping, now=now)
        if summary is None:
            return 'no_scope'

        if self._get_digest_skip_if_empty():
            totals = summary.get('totals', {})
            if totals.get('total_tasks', 0) == 0:
                _logger.info(
                    'openclaw manager_digest: mapping %d không có task nào, bỏ qua',
                    manager_mapping.id,
                )
                return 'skipped'

        message = self._build_manager_digest_message(summary, manager_mapping)

        vn_now = now.replace(tzinfo=_dt_timezone.utc).astimezone(_VN_TZ)
        period = 'am' if vn_now.hour < 12 else 'pm'

        top_n = self._get_digest_top_n()
        ranked_users = sorted(
            summary.get('users', []), key=self._user_urgency_score, reverse=True
        )
        payload = {
            'delivery': {
                'channel': manager_mapping.channel,
                'target': manager_mapping.target,
            },
            'digest': {
                'period': period,
                'generated_at': summary.get('generated_at'),
                'message': message,
                'totals': summary.get('totals', {}),
                'top_users': [
                    {
                        'user_id': u['user_id'],
                        'user_name': u['user_name'],
                        'metrics': u['metrics'],
                        'score': self._user_urgency_score(u),
                    }
                    for u in ranked_users[:top_n]
                ],
            },
        }

        notif_svc = self.env['dac.openclaw.notification.service']
        success = notif_svc._send_openclaw_webhook(
            'manager_digest', payload, mapping=manager_mapping, event_id=event_id,
        )
        return 'sent' if success else 'failed'

    @api.model
    def cron_send_openclaw_manager_digest(self):
        """Cron 2x/ngày: gửi manager digest cho tất cả manager mappings active."""
        if not self._get_digest_enabled():
            _logger.info('openclaw manager_digest: tính năng đã tắt bởi config')
            return

        now = fields.Datetime.now()
        manager_mappings = self.env['dac.openclaw.user.mapping'].sudo().search([
            ('role', '=', 'manager'),
            ('active', '=', True),
            ('digest_enabled', '=', True),
        ])

        stats = {'sent': 0, 'skipped': 0, 'failed': 0, 'no_scope': 0, 'already_sent': 0}
        for mapping in manager_mappings:
            try:
                result = self._send_manager_digest(mapping, now=now)
                stats[result] = stats.get(result, 0) + 1
            except Exception as exc:
                stats['failed'] += 1
                _logger.error(
                    'openclaw manager_digest: lỗi mapping %d: %s', mapping.id, exc
                )

        _logger.info(
            'openclaw manager_digest cron done: sent=%d skipped=%d failed=%d '
            'no_scope=%d already_sent=%d',
            stats['sent'], stats['skipped'], stats['failed'],
            stats['no_scope'], stats['already_sent'],
        )
