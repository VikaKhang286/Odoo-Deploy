"""Personal reminder backend service for OpenClaw chat flow.

Provides JSON-serializable methods callable from MCP controllers or Odoo shell:
  svc = env['dac.personal.reminder.service']
  svc.create_personal_reminder_task(user_id=10, name='...', remind_at='...')
  svc.find_recent_open_personal_tasks(user_id=10)
  svc.find_latest_open_personal_task(user_id=10)
  svc.complete_personal_reminder_task(task_id=42)
  svc.reschedule_personal_reminder_task(task_id=42, new_remind_at='...')
"""

import logging
from datetime import datetime, timedelta, timezone as _dt_timezone

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_VN_TZ = _dt_timezone(timedelta(hours=7))
_STATES_TERMINAL = frozenset({'done', 'cancelled'})
_DEFAULT_FIND_LIMIT = 5


def _parse_dt(val):
    """Parse ISO 8601 string or datetime → UTC naive datetime for Odoo storage.

    Handles:
      - Python datetime with tzinfo  → convert to UTC naive
      - Python datetime without tzinfo → treat as UTC naive, return as-is
      - ISO 8601 with offset: "2026-05-16T09:00:00+07:00"
      - ISO 8601 UTC Z suffix:  "2026-05-16T02:00:00Z"
      - ISO 8601 naive string:  "2026-05-16 09:00:00"
    Raises ValidationError if the string is not parseable.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(_dt_timezone.utc).replace(tzinfo=None)
        return val
    s = str(val).strip()
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValidationError(
            'Giá trị datetime không hợp lệ: %r — %s' % (val, exc)
        ) from exc
    if dt.tzinfo is not None:
        return dt.astimezone(_dt_timezone.utc).replace(tzinfo=None)
    return dt


def _to_vn_iso(dt):
    """Convert Odoo UTC naive datetime → ISO 8601 string in +07:00."""
    if not dt:
        return None
    return dt.replace(tzinfo=_dt_timezone.utc).astimezone(_VN_TZ).isoformat()


class DacPersonalReminderService(models.AbstractModel):
    """Backend service for OpenClaw personal reminder chat flow.

    All public methods return JSON-serializable dicts so callers never need
    to touch ORM records directly.  Business rules:

    - Personal reminder tasks are identified by is_personal_reminder=True.
    - They do not require order_id or conversation_id (bypass constraint).
    - Source is traced in personal_reminder_source (e.g. 'openclaw_chat').
    - complete/reschedule return {'ok': False, 'error': '...'} for business
      state errors (already closed, user mismatch) rather than raising, so
      callers can handle gracefully without try/except.
    - Programming errors (missing required args, invalid datetime) raise
      ValidationError so callers get a clear stack trace.
    """

    _name = 'dac.personal.reminder.service'
    _description = 'DAC Personal Reminder Service'

    # ══════════════════════════════════════════════════════════════════
    # Serialization
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _task_to_dict(self, task):
        """Convert a dac.work.task record → JSON-serializable dict."""
        return {
            'task_id': task.id,
            'task_name': task.name,
            'state': task.state,
            'priority': task.priority,
            'remind_at': _to_vn_iso(task.remind_at),
            'deadline': _to_vn_iso(task.deadline),
            'assigned_user_id': task.assigned_user_id.id if task.assigned_user_id else None,
            'assigned_user_name': task.assigned_user_id.name if task.assigned_user_id else None,
            'notes': task.notes or None,
            'is_personal_reminder': task.is_personal_reminder,
            'personal_reminder_source': task.personal_reminder_source or None,
            'order_id': task.order_id.id if task.order_id else None,
            'create_date': _to_vn_iso(task.create_date),
        }

    # ══════════════════════════════════════════════════════════════════
    # Public methods
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def create_personal_reminder_task(
        self,
        user_id,
        name,
        remind_at,
        deadline=None,
        notes=None,
        source='openclaw_chat',
        channel=None,
        target=None,
        order_id=None,
    ):
        """Create a personal reminder task for a user.

        The task is marked is_personal_reminder=True so it does not need an
        order or conversation link.  The assigned user's task_assigned webhook
        fires automatically via the existing create() ORM hook.

        :param user_id:  int  — res.users ID (required)
        :param name:     str  — task title (required, non-blank)
        :param remind_at: str|datetime — ISO 8601 with timezone (required)
        :param deadline: str|datetime|None — hard deadline (optional)
        :param notes:    str|None — internal notes
        :param source:   str  — origin trace, default 'openclaw_chat'
        :param channel:  str|None — delivery channel for trace (stored in notes)
        :param target:   str|None — delivery target for trace (stored in notes)
        :param order_id: int|None — optional link to sale.order
        :return: {'ok': True, ...task fields...}
        :raises ValidationError: if required fields missing or datetime invalid
        """
        if not user_id:
            raise ValidationError('user_id là bắt buộc để tạo personal reminder task.')
        if not name or not str(name).strip():
            raise ValidationError('Tiêu đề task (name) là bắt buộc.')
        if remind_at is None:
            raise ValidationError('remind_at là bắt buộc cho personal reminder task.')

        remind_at_utc = _parse_dt(remind_at)
        deadline_utc = _parse_dt(deadline) if deadline is not None else False

        note_parts = []
        if notes:
            note_parts.append(str(notes))
        if channel and target:
            note_parts.append('[nguon: %s → %s]' % (channel, target))

        vals = {
            'name': str(name).strip(),
            'assigned_user_id': int(user_id),
            'remind_at': remind_at_utc,
            'state': 'draft',
            'is_personal_reminder': True,
            'personal_reminder_source': source or 'openclaw_chat',
        }
        if note_parts:
            vals['notes'] = '\n'.join(note_parts)
        if deadline_utc:
            vals['deadline'] = deadline_utc
        if order_id:
            vals['order_id'] = int(order_id)

        task = self.env['dac.work.task'].sudo().create(vals)
        _logger.info(
            'personal_reminder: created task %d "%s" for user %d remind_at=%s source=%s',
            task.id, task.name, user_id, remind_at, source,
        )
        result = self._task_to_dict(task)
        result['ok'] = True
        return result

    @api.model
    def find_recent_open_personal_tasks(self, user_id, limit=_DEFAULT_FIND_LIMIT):
        """Return open personal reminder tasks for a user, sorted for disambiguation.

        Tasks with remind_at are returned nearest-first (soonest reminder first).
        Tasks without remind_at are appended, newest-first.
        This ordering gives OpenClaw enough context to ask the user which task
        they mean when there are multiple open tasks.

        :param user_id: int — res.users ID
        :param limit:   int — max results (default 5)
        :return: list[dict] — empty list if no open personal tasks
        """
        if not user_id:
            return []

        limit = max(1, int(limit))
        Task = self.env['dac.work.task'].sudo()
        base = [
            ('is_personal_reminder', '=', True),
            ('state', 'not in', list(_STATES_TERMINAL)),
            ('assigned_user_id', '=', int(user_id)),
        ]

        with_remind = Task.search(
            base + [('remind_at', '!=', False)],
            order='remind_at asc, id desc',
            limit=limit,
        )
        without_remind = Task.search(
            base + [('remind_at', '=', False)],
            order='create_date desc, id desc',
            limit=limit,
        )
        combined = (with_remind + without_remind)[:limit]
        return [self._task_to_dict(t) for t in combined]

    @api.model
    def find_latest_open_personal_task(self, user_id):
        """Return the most recently created open personal reminder task for user.

        Used when the user says "xong rồi" without specifying which task.
        Returns None if no open personal tasks exist — caller should then ask
        the user to clarify rather than guessing.

        :param user_id: int — res.users ID
        :return: dict | None
        """
        if not user_id:
            return None

        task = self.env['dac.work.task'].sudo().search([
            ('is_personal_reminder', '=', True),
            ('state', 'not in', list(_STATES_TERMINAL)),
            ('assigned_user_id', '=', int(user_id)),
        ], order='create_date desc, id desc', limit=1)

        if not task:
            return None
        return self._task_to_dict(task)

    @api.model
    def complete_personal_reminder_task(self, task_id, user_id=None, completion_note=None):
        """Mark a personal reminder task as done.

        :param task_id:         int      — dac.work.task ID
        :param user_id:         int|None — if given, must match assigned_user_id
        :param completion_note: str|None — appended to task notes on completion
        :return: {'ok': True, ...} on success
                 {'ok': False, 'error': 'already_closed'|'user_mismatch', ...} otherwise
        :raises ValidationError: if task_id not found
        """
        task = self.env['dac.work.task'].sudo().browse(int(task_id))
        if not task.exists():
            raise ValidationError('Không tìm thấy task id=%d.' % task_id)

        if task.state in _STATES_TERMINAL:
            result = self._task_to_dict(task)
            result['ok'] = False
            result['error'] = 'already_closed'
            return result

        if user_id and task.assigned_user_id.id != int(user_id):
            result = self._task_to_dict(task)
            result['ok'] = False
            result['error'] = 'user_mismatch'
            return result

        write_vals = {'state': 'done'}
        if completion_note:
            existing = task.notes or ''
            sep = '\n' if existing else ''
            write_vals['notes'] = existing + sep + str(completion_note)

        task.write(write_vals)
        _logger.info('personal_reminder: completed task %d', task_id)
        result = self._task_to_dict(task)
        result['ok'] = True
        return result

    @api.model
    def reschedule_personal_reminder_task(
        self, task_id, new_remind_at, user_id=None, note=None
    ):
        """Update remind_at for an open personal reminder task.

        Also resets x_openclaw_last_reminder_at so the cron fires again at the
        new time without waiting for the cooldown period to expire.

        :param task_id:       int          — dac.work.task ID
        :param new_remind_at: str|datetime — new remind time (ISO 8601 with TZ)
        :param user_id:       int|None     — if given, must match assigned_user_id
        :param note:          str|None     — appended to task notes on reschedule
        :return: {'ok': True, ...} on success
                 {'ok': False, 'error': 'task_closed'|'user_mismatch', ...} otherwise
        :raises ValidationError: if task not found, or new_remind_at is invalid/empty
        """
        task = self.env['dac.work.task'].sudo().browse(int(task_id))
        if not task.exists():
            raise ValidationError('Không tìm thấy task id=%d.' % task_id)

        if task.state in _STATES_TERMINAL:
            result = self._task_to_dict(task)
            result['ok'] = False
            result['error'] = 'task_closed'
            return result

        if user_id and task.assigned_user_id.id != int(user_id):
            result = self._task_to_dict(task)
            result['ok'] = False
            result['error'] = 'user_mismatch'
            return result

        new_remind_at_utc = _parse_dt(new_remind_at)
        if not new_remind_at_utc:
            raise ValidationError('new_remind_at là bắt buộc và không được để trống.')

        write_vals = {
            'remind_at': new_remind_at_utc,
            'x_openclaw_last_reminder_at': False,  # reset cooldown → cron can fire at new time
        }
        if note:
            existing = task.notes or ''
            sep = '\n' if existing else ''
            write_vals['notes'] = existing + sep + str(note)

        task.write(write_vals)
        _logger.info(
            'personal_reminder: rescheduled task %d to remind_at=%s', task_id, new_remind_at
        )
        result = self._task_to_dict(task)
        result['ok'] = True
        return result
