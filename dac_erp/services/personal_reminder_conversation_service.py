"""Conversation turn handler for OpenClaw personal reminder chat flow.

Stateless design: the caller (OpenClaw) holds session_state and passes it
with every request.  This service applies state transitions, calls
personal_reminder_service for CRUD, and returns a plain-text Vietnamese reply
plus the updated state.

State schema (JSON-serializable dict or None):

  None  — no pending action

  {kind: "pending_personal_reminder_create",
   draft: {name, date_hint, notes, source},
   missing_fields: ["remind_at_time"]}

  {kind: "pending_task_selection_complete",
   candidates: [{task_id, task_name, remind_at}, ...]}

  {kind: "pending_task_selection_reschedule",
   new_remind_at: str | null,
   candidates: [{task_id, task_name, remind_at}, ...]}

  {kind: "pending_reschedule_time",
   task_id: int,
   task_name: str}

Return value of handle_turn():
  {
    ok: bool,
    reply: str,
    new_session_state: dict | None,
    action_taken: "created"|"completed"|"rescheduled"|"listed"|"asked"|"no_op"|"error",
    task: dict | None,
  }
"""
import logging
from datetime import datetime

from odoo import api, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ── Intent constants ────────────────────────────────────────────────────────

INTENT_CREATE = 'create_personal_reminder'
INTENT_PROVIDE_TIME = 'provide_missing_reminder_time'
INTENT_COMPLETE = 'complete_personal_reminder'
INTENT_RESCHEDULE = 'reschedule_personal_reminder'
INTENT_LIST = 'list_open_personal_reminders'
INTENT_CLARIFY = 'clarify_task_selection'

KNOWN_INTENTS = frozenset({
    INTENT_CREATE,
    INTENT_PROVIDE_TIME,
    INTENT_COMPLETE,
    INTENT_RESCHEDULE,
    INTENT_LIST,
    INTENT_CLARIFY,
})

# ── State kind constants ─────────────────────────────────────────────────────

KIND_PENDING_CREATE = 'pending_personal_reminder_create'
KIND_PENDING_COMPLETE = 'pending_task_selection_complete'
KIND_PENDING_RESCHEDULE_SELECT = 'pending_task_selection_reschedule'
KIND_PENDING_RESCHEDULE_TIME = 'pending_reschedule_time'


# ── Module-level helpers ─────────────────────────────────────────────────────

def _format_task_short(task):
    """One-line description of a task for disambiguation lists."""
    name = task.get('task_name') or '(không tên)'
    remind_at = task.get('remind_at')
    if remind_at:
        try:
            dt = datetime.fromisoformat(remind_at)
            remind_at_str = dt.strftime('%H:%M %d/%m')
        except Exception:
            remind_at_str = remind_at
        return '• **%s** (nhắc lúc %s)' % (name, remind_at_str)
    return '• **%s**' % name


def _task_name_from_candidates(candidates, task_id):
    """Look up task_name from a candidates list by task_id."""
    for c in (candidates or []):
        if c.get('task_id') == int(task_id):
            return c.get('task_name') or 'việc nhắc'
    return 'việc nhắc'


def _fmt_remind_at(remind_at_str):
    """Format an ISO remind_at string for display."""
    if not remind_at_str:
        return None
    try:
        dt = datetime.fromisoformat(remind_at_str)
        return dt.strftime('%H:%M %d/%m/%Y')
    except Exception:
        return remind_at_str


# ── Service ──────────────────────────────────────────────────────────────────

class DacPersonalReminderConversationService(models.AbstractModel):
    """Stateless conversation turn handler for personal reminder chat flow.

    Caller pattern:
        svc = env['dac.personal.reminder.conversation.service']
        result = svc.handle_turn(user_id=10, intent='create_personal_reminder',
                                 params={'name': 'Gọi anh A', 'remind_at': None,
                                         'date_hint': 'tomorrow'},
                                 session_state=None)
    """

    _name = 'dac.personal.reminder.conversation.service'
    _description = 'DAC Personal Reminder Conversation Service'

    # ── Public ───────────────────────────────────────────────────────────────

    @api.model
    def handle_turn(self, user_id, intent, params, session_state=None):
        """Process one conversation turn and return a reply + new state.

        :param user_id:       int         — res.users ID
        :param intent:        str         — one of KNOWN_INTENTS
        :param params:        dict        — extracted intent parameters
        :param session_state: dict | None — current pending state
        :return: dict with keys: ok, reply, new_session_state, action_taken, task
        """
        if not user_id:
            return self._error_reply('user_id là bắt buộc.')

        params = dict(params or {})
        state = dict(session_state or {})

        try:
            if intent == INTENT_CREATE:
                return self._handle_create(user_id, params, state)
            if intent == INTENT_PROVIDE_TIME:
                return self._handle_provide_time(user_id, params, state)
            if intent == INTENT_COMPLETE:
                return self._handle_complete(user_id, params, state)
            if intent == INTENT_RESCHEDULE:
                return self._handle_reschedule(user_id, params, state)
            if intent == INTENT_LIST:
                return self._handle_list(user_id, params, state)
            if intent == INTENT_CLARIFY:
                return self._handle_clarify(user_id, params, state)
        except ValidationError as exc:
            _logger.warning('pr_conversation: ValidationError intent=%s: %s', intent, exc)
            return self._error_reply(
                'Xin lỗi anh, em gặp lỗi khi xử lý. Anh vui lòng thử lại nhé.',
                state=state,
            )
        except Exception as exc:
            _logger.error('pr_conversation: unexpected error intent=%s: %s', intent, exc, exc_info=True)
            return self._error_reply(
                'Xin lỗi anh, hệ thống đang gặp sự cố. Anh thử lại sau nhé ạ.',
            )

        return self._error_reply('Em chưa hiểu yêu cầu này. Anh có thể nói rõ hơn không ạ?')

    # ── Intent handlers ───────────────────────────────────────────────────────

    @api.model
    def _handle_create(self, user_id, params, state):
        name = (params.get('name') or '').strip()
        remind_at = params.get('remind_at')
        date_hint = (params.get('date_hint') or '').strip() or None
        notes = params.get('notes') or None
        source = params.get('source') or 'openclaw_chat'

        if not name:
            return self._ask_reply(
                'Anh muốn nhắc việc gì ạ? Anh cho em biết tên việc cần nhắc nhé.',
                new_state=None,
            )

        if not remind_at:
            draft = {'name': name, 'source': source}
            if notes:
                draft['notes'] = notes
            if date_hint:
                draft['date_hint'] = date_hint
            new_state = {
                'kind': KIND_PENDING_CREATE,
                'draft': draft,
                'missing_fields': ['remind_at_time'],
            }
            if date_hint:
                return self._ask_reply(
                    'Vâng ạ! Anh muốn em nhắc việc **%s** vào lúc mấy giờ ạ?' % name,
                    new_state=new_state,
                )
            return self._ask_reply(
                'Vâng ạ! Anh muốn em nhắc việc **%s** vào ngày giờ nào ạ?' % name,
                new_state=new_state,
            )

        svc = self.env['dac.personal.reminder.service']
        result = svc.create_personal_reminder_task(
            user_id=user_id,
            name=name,
            remind_at=remind_at,
            notes=notes,
            source=source,
        )
        if not result.get('ok'):
            return self._error_reply('Xin lỗi anh, em chưa lưu được nhắc việc. Anh thử lại nhé.')

        return self._result_created(result)

    @api.model
    def _handle_provide_time(self, user_id, params, state):
        remind_at = params.get('remind_at')
        state_kind = state.get('kind')

        if state_kind == KIND_PENDING_CREATE:
            if not remind_at:
                return self._ask_reply(
                    'Em chưa hiểu rõ giờ ạ. Anh cho em biết cụ thể mấy giờ ạ?',
                    new_state=state,
                )
            draft = state.get('draft') or {}
            svc = self.env['dac.personal.reminder.service']
            result = svc.create_personal_reminder_task(
                user_id=user_id,
                name=draft.get('name', ''),
                remind_at=remind_at,
                notes=draft.get('notes'),
                source=draft.get('source', 'openclaw_chat'),
            )
            if not result.get('ok'):
                return self._error_reply(
                    'Xin lỗi anh, em chưa lưu được. Anh thử lại nhé.',
                    state=state,
                )
            return self._result_created(result)

        if state_kind == KIND_PENDING_RESCHEDULE_TIME:
            if not remind_at:
                return self._ask_reply(
                    'Em chưa hiểu rõ giờ ạ. Anh cho em biết cụ thể mấy giờ nào ạ?',
                    new_state=state,
                )
            task_id = state.get('task_id')
            task_name = state.get('task_name', '')
            svc = self.env['dac.personal.reminder.service']
            result = svc.reschedule_personal_reminder_task(
                task_id=task_id,
                new_remind_at=remind_at,
                user_id=user_id,
            )
            if not result.get('ok'):
                return self._handle_reschedule_error(result, task_name)
            return self._result_rescheduled(result)

        return self._error_reply(
            'Em không rõ anh đang nhắc đến việc gì. Anh nhắc lại giúp em nhé ạ.',
        )

    @api.model
    def _handle_complete(self, user_id, params, state):
        task_id = params.get('task_id')
        completion_note = params.get('completion_note')
        svc = self.env['dac.personal.reminder.service']

        if task_id:
            result = svc.complete_personal_reminder_task(
                task_id=int(task_id),
                user_id=user_id,
                completion_note=completion_note,
            )
            if not result.get('ok'):
                return self._handle_complete_error(result)
            return self._result_completed(result)

        all_open = svc.find_recent_open_personal_tasks(user_id=user_id, limit=5)
        if not all_open:
            return self._ok_reply(
                'Anh không có việc nhắc nào đang mở ạ.',
                action_taken='no_op',
            )

        if len(all_open) == 1:
            result = svc.complete_personal_reminder_task(
                task_id=all_open[0]['task_id'],
                user_id=user_id,
                completion_note=completion_note,
            )
            if not result.get('ok'):
                return self._handle_complete_error(result)
            return self._result_completed(result)

        candidates = [
            {'task_id': t['task_id'], 'task_name': t['task_name'], 'remind_at': t['remind_at']}
            for t in all_open
        ]
        new_state = {'kind': KIND_PENDING_COMPLETE, 'candidates': candidates}
        lines = '\n'.join(_format_task_short(c) for c in candidates)
        return self._ask_reply(
            'Anh đang có %d việc nhắc đang mở. Anh muốn đánh dấu hoàn thành việc nào ạ?\n%s'
            % (len(candidates), lines),
            new_state=new_state,
        )

    @api.model
    def _handle_reschedule(self, user_id, params, state):
        task_id = params.get('task_id')
        new_remind_at = params.get('new_remind_at')
        svc = self.env['dac.personal.reminder.service']

        if task_id and new_remind_at:
            result = svc.reschedule_personal_reminder_task(
                task_id=int(task_id),
                new_remind_at=new_remind_at,
                user_id=user_id,
            )
            if not result.get('ok'):
                return self._handle_reschedule_error(result, '')
            return self._result_rescheduled(result)

        if task_id and not new_remind_at:
            open_tasks = svc.find_recent_open_personal_tasks(user_id=user_id, limit=20)
            task_name = _task_name_from_candidates(open_tasks, task_id)
            new_state = {
                'kind': KIND_PENDING_RESCHEDULE_TIME,
                'task_id': int(task_id),
                'task_name': task_name,
            }
            return self._ask_reply(
                'Anh muốn dời nhắc **%s** sang lúc mấy giờ ạ?' % task_name,
                new_state=new_state,
            )

        all_open = svc.find_recent_open_personal_tasks(user_id=user_id, limit=5)
        if not all_open:
            return self._ok_reply(
                'Anh không có việc nhắc nào đang mở để dời ạ.',
                action_taken='no_op',
            )

        if len(all_open) == 1:
            if new_remind_at:
                result = svc.reschedule_personal_reminder_task(
                    task_id=all_open[0]['task_id'],
                    new_remind_at=new_remind_at,
                    user_id=user_id,
                )
                if not result.get('ok'):
                    return self._handle_reschedule_error(result, all_open[0]['task_name'])
                return self._result_rescheduled(result)
            new_state = {
                'kind': KIND_PENDING_RESCHEDULE_TIME,
                'task_id': all_open[0]['task_id'],
                'task_name': all_open[0]['task_name'],
            }
            return self._ask_reply(
                'Anh muốn dời nhắc **%s** sang lúc mấy giờ ạ?' % all_open[0]['task_name'],
                new_state=new_state,
            )

        candidates = [
            {'task_id': t['task_id'], 'task_name': t['task_name'], 'remind_at': t['remind_at']}
            for t in all_open
        ]
        new_state = {
            'kind': KIND_PENDING_RESCHEDULE_SELECT,
            'new_remind_at': new_remind_at,
            'candidates': candidates,
        }
        lines = '\n'.join(_format_task_short(c) for c in candidates)
        return self._ask_reply(
            'Anh đang có %d việc nhắc. Anh muốn dời việc nào ạ?\n%s' % (len(candidates), lines),
            new_state=new_state,
        )

    @api.model
    def _handle_list(self, user_id, params, state):
        limit = max(1, int(params.get('limit') or 5))
        svc = self.env['dac.personal.reminder.service']
        tasks = svc.find_recent_open_personal_tasks(user_id=user_id, limit=limit)
        if not tasks:
            return self._ok_reply('Anh hiện không có việc nhắc nào đang mở ạ.', action_taken='listed')
        lines = '\n'.join(_format_task_short(t) for t in tasks)
        return {
            'ok': True,
            'reply': 'Anh đang có %d việc nhắc:\n%s' % (len(tasks), lines),
            'new_session_state': None,
            'action_taken': 'listed',
            'task': None,
        }

    @api.model
    def _handle_clarify(self, user_id, params, state):
        task_id = params.get('task_id')
        state_kind = state.get('kind')
        svc = self.env['dac.personal.reminder.service']

        if not task_id:
            return self._ask_reply(
                'Anh chọn việc nào ạ? Anh cho em biết số thứ tự hoặc tên việc nhé.',
                new_state=state,
            )

        if state_kind == KIND_PENDING_COMPLETE:
            result = svc.complete_personal_reminder_task(
                task_id=int(task_id),
                user_id=user_id,
            )
            if not result.get('ok'):
                return self._handle_complete_error(result)
            return self._result_completed(result)

        if state_kind == KIND_PENDING_RESCHEDULE_SELECT:
            new_remind_at = state.get('new_remind_at')
            if not new_remind_at:
                task_name = _task_name_from_candidates(state.get('candidates', []), task_id)
                new_state = {
                    'kind': KIND_PENDING_RESCHEDULE_TIME,
                    'task_id': int(task_id),
                    'task_name': task_name,
                }
                return self._ask_reply(
                    'Anh muốn dời **%s** sang lúc mấy giờ ạ?' % task_name,
                    new_state=new_state,
                )
            result = svc.reschedule_personal_reminder_task(
                task_id=int(task_id),
                new_remind_at=new_remind_at,
                user_id=user_id,
            )
            if not result.get('ok'):
                return self._handle_reschedule_error(result, '')
            return self._result_rescheduled(result)

        return self._error_reply(
            'Em không rõ đang chờ anh xác nhận điều gì. Anh nhắc lại giúp em nhé ạ.',
        )

    # ── Error handlers ────────────────────────────────────────────────────────

    @api.model
    def _handle_complete_error(self, result):
        error = result.get('error', '')
        task_name = result.get('task_name') or 'việc này'
        if error == 'already_closed':
            return self._ok_reply(
                'Việc **%s** đã được đánh dấu hoàn thành trước đó rồi ạ.' % task_name,
                action_taken='no_op',
            )
        if error == 'user_mismatch':
            return self._error_reply(
                'Xin lỗi anh, việc này không thuộc danh sách nhắc của anh ạ.',
            )
        return self._error_reply('Xin lỗi anh, em chưa cập nhật được. Anh thử lại nhé.')

    @api.model
    def _handle_reschedule_error(self, result, task_name_fallback):
        error = result.get('error', '')
        name = result.get('task_name') or task_name_fallback or 'việc này'
        if error in ('task_closed', 'already_closed'):
            return self._ok_reply(
                'Việc **%s** đã đóng rồi, không thể dời được ạ.' % name,
                action_taken='no_op',
            )
        if error == 'user_mismatch':
            return self._error_reply(
                'Xin lỗi anh, việc này không thuộc danh sách nhắc của anh ạ.',
            )
        return self._error_reply('Xin lỗi anh, em chưa dời được. Anh thử lại nhé.')

    # ── Result builders ───────────────────────────────────────────────────────

    @api.model
    def _result_created(self, task):
        name = task.get('task_name', '')
        time_str = _fmt_remind_at(task.get('remind_at'))
        if time_str:
            reply = 'Được ạ! Em đã đặt nhắc cho anh: **%s** vào lúc **%s** ạ.' % (name, time_str)
        else:
            reply = 'Được ạ! Em đã tạo nhắc việc **%s** cho anh ạ.' % name
        return {
            'ok': True,
            'reply': reply,
            'new_session_state': None,
            'action_taken': 'created',
            'task': task,
        }

    @api.model
    def _result_completed(self, task):
        name = task.get('task_name', '')
        return {
            'ok': True,
            'reply': 'Đã xong rồi ạ! Em đánh dấu hoàn thành việc **%s** nhé anh.' % name,
            'new_session_state': None,
            'action_taken': 'completed',
            'task': task,
        }

    @api.model
    def _result_rescheduled(self, task):
        name = task.get('task_name', '')
        time_str = _fmt_remind_at(task.get('remind_at'))
        if time_str:
            reply = 'Đã dời rồi ạ! Em sẽ nhắc anh việc **%s** lúc **%s** nhé.' % (name, time_str)
        else:
            reply = 'Đã cập nhật giờ nhắc cho việc **%s** rồi ạ.' % name
        return {
            'ok': True,
            'reply': reply,
            'new_session_state': None,
            'action_taken': 'rescheduled',
            'task': task,
        }

    # ── Reply helpers ─────────────────────────────────────────────────────────

    @api.model
    def _ask_reply(self, reply, new_state):
        return {
            'ok': True,
            'reply': reply,
            'new_session_state': new_state,
            'action_taken': 'asked',
            'task': None,
        }

    @api.model
    def _ok_reply(self, reply, action_taken=None):
        return {
            'ok': True,
            'reply': reply,
            'new_session_state': None,
            'action_taken': action_taken,
            'task': None,
        }

    @api.model
    def _error_reply(self, reply, state=None):
        return {
            'ok': False,
            'reply': reply,
            'new_session_state': state,
            'action_taken': 'error',
            'task': None,
        }
