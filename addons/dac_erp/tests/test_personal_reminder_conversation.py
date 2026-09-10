"""Tests for personal reminder conversation service (Phần 6C).

Covers all intents, state transitions, multi-turn disambiguation, and error
handling.  Uses the service directly (no HTTP) for speed and clarity.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.services.personal_reminder_conversation_service import (
    INTENT_CLARIFY,
    INTENT_COMPLETE,
    INTENT_CREATE,
    INTENT_LIST,
    INTENT_PROVIDE_TIME,
    INTENT_RESCHEDULE,
    KIND_PENDING_COMPLETE,
    KIND_PENDING_CREATE,
    KIND_PENDING_RESCHEDULE_SELECT,
    KIND_PENDING_RESCHEDULE_TIME,
)


@tagged('post_install', '-at_install')
class TestPrConversationCreate(TransactionCase):
    """Flow 1: create_personal_reminder intent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Conv Test User',
            'login': 'conv_test@test.com',
            'email': 'conv_test@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(
            user_id=self.user.id,
            intent=intent,
            params=params or {},
            session_state=state,
        )

    # ── create with full info ─────────────────────────────────────────────

    def test_create_full_info_returns_created(self):
        result = self._turn(INTENT_CREATE, {
            'name': 'Gọi anh Nam',
            'remind_at': '2026-05-20T09:00:00+07:00',
        })
        self.assertTrue(result['ok'])
        self.assertEqual(result['action_taken'], 'created')
        self.assertIsNone(result['new_session_state'])
        self.assertIsNotNone(result['task'])
        self.assertIn('Gọi anh Nam', result['reply'])

    def test_create_task_persisted_in_db(self):
        result = self._turn(INTENT_CREATE, {
            'name': 'Gửi báo giá',
            'remind_at': '2026-05-21T14:00:00+07:00',
        })
        task_id = result['task']['task_id']
        task = self.env['dac.work.task'].browse(task_id)
        self.assertTrue(task.exists())
        self.assertTrue(task.is_personal_reminder)
        self.assertEqual(task.name, 'Gửi báo giá')

    def test_create_missing_time_asks_followup(self):
        result = self._turn(INTENT_CREATE, {
            'name': 'Trả lời anh A',
            'date_hint': '2026-05-20',
        })
        self.assertTrue(result['ok'])
        self.assertEqual(result['action_taken'], 'asked')
        state = result['new_session_state']
        self.assertIsNotNone(state)
        self.assertEqual(state['kind'], KIND_PENDING_CREATE)
        self.assertEqual(state['draft']['name'], 'Trả lời anh A')
        self.assertEqual(state['draft']['date_hint'], '2026-05-20')
        self.assertIn('mấy giờ', result['reply'])

    def test_create_missing_date_and_time_asks_followup(self):
        result = self._turn(INTENT_CREATE, {'name': 'Trả lời anh A'})
        self.assertEqual(result['action_taken'], 'asked')
        self.assertIn(KIND_PENDING_CREATE, result['new_session_state']['kind'])
        self.assertIn('ngày giờ', result['reply'])

    def test_create_missing_name_asks_for_name(self):
        result = self._turn(INTENT_CREATE, {'remind_at': '2026-05-20T09:00:00+07:00'})
        self.assertEqual(result['action_taken'], 'asked')
        self.assertIsNone(result['new_session_state'])

    def test_create_state_cleared_after_success(self):
        result = self._turn(INTENT_CREATE, {
            'name': 'Test clear state',
            'remind_at': '2026-05-22T08:00:00+07:00',
        })
        self.assertIsNone(result['new_session_state'])

    def test_create_with_source(self):
        result = self._turn(INTENT_CREATE, {
            'name': 'Test source',
            'remind_at': '2026-05-22T09:00:00+07:00',
            'source': 'openclaw_chat',
        })
        self.assertEqual(result['task']['personal_reminder_source'], 'openclaw_chat')


@tagged('post_install', '-at_install')
class TestPrConversationProvideTime(TransactionCase):
    """Flow 2: provide_missing_reminder_time — ask-then-answer multi-turn."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PT User',
            'login': 'pt_user@test.com',
            'email': 'pt_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(self.user.id, intent, params or {}, state)

    def test_provide_time_after_pending_create(self):
        pending = {
            'kind': KIND_PENDING_CREATE,
            'draft': {'name': 'Trả lời anh A', 'date_hint': '2026-05-20', 'source': 'openclaw_chat'},
            'missing_fields': ['remind_at_time'],
        }
        result = self._turn(
            INTENT_PROVIDE_TIME,
            {'remind_at': '2026-05-20T09:00:00+07:00'},
            state=pending,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['action_taken'], 'created')
        self.assertIsNone(result['new_session_state'])
        self.assertIn('Trả lời anh A', result['reply'])

    def test_provide_time_creates_db_record(self):
        pending = {
            'kind': KIND_PENDING_CREATE,
            'draft': {'name': 'DB check task', 'source': 'openclaw_chat'},
            'missing_fields': ['remind_at_time'],
        }
        result = self._turn(
            INTENT_PROVIDE_TIME,
            {'remind_at': '2026-05-21T10:00:00+07:00'},
            state=pending,
        )
        task = self.env['dac.work.task'].browse(result['task']['task_id'])
        self.assertEqual(task.name, 'DB check task')

    def test_provide_time_without_state_returns_error(self):
        result = self._turn(INTENT_PROVIDE_TIME, {'remind_at': '2026-05-20T09:00:00+07:00'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['action_taken'], 'error')

    def test_provide_time_with_missing_remind_at_asks_again(self):
        pending = {
            'kind': KIND_PENDING_CREATE,
            'draft': {'name': 'Test re-ask', 'source': 'openclaw_chat'},
            'missing_fields': ['remind_at_time'],
        }
        result = self._turn(INTENT_PROVIDE_TIME, {'remind_at': None}, state=pending)
        self.assertEqual(result['action_taken'], 'asked')
        self.assertEqual(result['new_session_state']['kind'], KIND_PENDING_CREATE)

    def test_provide_time_for_reschedule_state(self):
        task = self.env['dac.work.task'].create({
            'name': 'Reschedule test task',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        pending = {
            'kind': KIND_PENDING_RESCHEDULE_TIME,
            'task_id': task.id,
            'task_name': 'Reschedule test task',
        }
        result = self._turn(
            INTENT_PROVIDE_TIME,
            {'remind_at': '2026-06-01T08:00:00+07:00'},
            state=pending,
        )
        self.assertEqual(result['action_taken'], 'rescheduled')
        self.assertIsNone(result['new_session_state'])


@tagged('post_install', '-at_install')
class TestPrConversationComplete(TransactionCase):
    """Flow 3: complete_personal_reminder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Complete User',
            'login': 'complete_user@test.com',
            'email': 'complete_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(self.user.id, intent, params or {}, state)

    def _make_task(self, name='Test task', state='in_progress'):
        return self.env['dac.work.task'].create({
            'name': name,
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': state,
        })

    def test_complete_single_open_task(self):
        task = self._make_task('Xong việc test')
        result = self._turn(INTENT_COMPLETE)
        self.assertEqual(result['action_taken'], 'completed')
        self.assertIsNone(result['new_session_state'])
        self.assertIn('xong', result['reply'].lower())
        task.invalidate_recordset()
        self.assertEqual(task.state, 'done')

    def test_complete_explicit_task_id(self):
        task = self._make_task('Explicit task')
        result = self._turn(INTENT_COMPLETE, {'task_id': task.id})
        self.assertEqual(result['action_taken'], 'completed')
        task.invalidate_recordset()
        self.assertEqual(task.state, 'done')

    def test_complete_no_open_tasks(self):
        empty_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Empty Complete',
            'login': 'empty_complete@test.com',
            'email': 'empty_complete@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        result = self.svc.handle_turn(empty_user.id, INTENT_COMPLETE, {}, None)
        self.assertEqual(result['action_taken'], 'no_op')
        self.assertIsNone(result['new_session_state'])

    def test_complete_multiple_tasks_asks_disambiguation(self):
        self._make_task('Task A')
        self._make_task('Task B')
        result = self._turn(INTENT_COMPLETE)
        self.assertEqual(result['action_taken'], 'asked')
        state = result['new_session_state']
        self.assertEqual(state['kind'], KIND_PENDING_COMPLETE)
        self.assertGreaterEqual(len(state['candidates']), 2)

    def test_complete_already_done_returns_no_op(self):
        task = self._make_task('Already done', state='done')
        result = self._turn(INTENT_COMPLETE, {'task_id': task.id})
        self.assertEqual(result['action_taken'], 'no_op')

    def test_complete_state_cleared_after_success(self):
        task = self._make_task('Clear state')
        result = self._turn(INTENT_COMPLETE, {'task_id': task.id})
        self.assertIsNone(result['new_session_state'])


@tagged('post_install', '-at_install')
class TestPrConversationReschedule(TransactionCase):
    """Flow 4: reschedule_personal_reminder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reschedule User',
            'login': 'reschedule_user@test.com',
            'email': 'reschedule_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(self.user.id, intent, params or {}, state)

    def _make_task(self, name='Reschedule task', state='draft'):
        return self.env['dac.work.task'].create({
            'name': name,
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': state,
        })

    def test_reschedule_with_task_and_time(self):
        task = self._make_task('Full reschedule')
        result = self._turn(INTENT_RESCHEDULE, {
            'task_id': task.id,
            'new_remind_at': '2026-06-01T09:00:00+07:00',
        })
        self.assertEqual(result['action_taken'], 'rescheduled')
        self.assertIsNone(result['new_session_state'])

    def test_reschedule_single_task_no_time_asks_time(self):
        task = self._make_task('Ask time task')
        result = self._turn(INTENT_RESCHEDULE, {'task_id': task.id})
        self.assertEqual(result['action_taken'], 'asked')
        state = result['new_session_state']
        self.assertEqual(state['kind'], KIND_PENDING_RESCHEDULE_TIME)
        self.assertEqual(state['task_id'], task.id)

    def test_reschedule_no_task_single_open_with_time(self):
        task = self._make_task('One task reschedule')
        result = self._turn(INTENT_RESCHEDULE, {'new_remind_at': '2026-06-02T10:00:00+07:00'})
        self.assertEqual(result['action_taken'], 'rescheduled')

    def test_reschedule_no_task_single_open_no_time_asks(self):
        task = self._make_task('One task no time')
        result = self._turn(INTENT_RESCHEDULE)
        self.assertEqual(result['action_taken'], 'asked')
        self.assertEqual(result['new_session_state']['kind'], KIND_PENDING_RESCHEDULE_TIME)

    def test_reschedule_multiple_tasks_asks_which(self):
        self._make_task('Task R1')
        self._make_task('Task R2')
        result = self._turn(INTENT_RESCHEDULE, {'new_remind_at': '2026-06-03T11:00:00+07:00'})
        self.assertEqual(result['action_taken'], 'asked')
        state = result['new_session_state']
        self.assertEqual(state['kind'], KIND_PENDING_RESCHEDULE_SELECT)
        self.assertEqual(state['new_remind_at'], '2026-06-03T11:00:00+07:00')

    def test_reschedule_closed_task_returns_no_op(self):
        task = self._make_task('Closed task', state='cancelled')
        result = self._turn(INTENT_RESCHEDULE, {
            'task_id': task.id,
            'new_remind_at': '2026-06-01T09:00:00+07:00',
        })
        self.assertEqual(result['action_taken'], 'no_op')

    def test_reschedule_no_open_tasks(self):
        empty_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Empty Reschedule',
            'login': 'empty_reschedule@test.com',
            'email': 'empty_reschedule@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        result = self.svc.handle_turn(empty_user.id, INTENT_RESCHEDULE, {}, None)
        self.assertEqual(result['action_taken'], 'no_op')


@tagged('post_install', '-at_install')
class TestPrConversationDisambiguation(TransactionCase):
    """Flow 5: clarify_task_selection — disambiguation after pending state."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Disambig User',
            'login': 'disambig_user@test.com',
            'email': 'disambig_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(self.user.id, intent, params or {}, state)

    def _make_task(self, name, state='in_progress'):
        return self.env['dac.work.task'].create({
            'name': name,
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': state,
        })

    def test_clarify_complete_selects_correct_task(self):
        t1 = self._make_task('Task Clarify 1')
        t2 = self._make_task('Task Clarify 2')
        pending = {
            'kind': KIND_PENDING_COMPLETE,
            'candidates': [
                {'task_id': t1.id, 'task_name': t1.name, 'remind_at': None},
                {'task_id': t2.id, 'task_name': t2.name, 'remind_at': None},
            ],
        }
        result = self._turn(INTENT_CLARIFY, {'task_id': t1.id}, state=pending)
        self.assertEqual(result['action_taken'], 'completed')
        self.assertIsNone(result['new_session_state'])
        t1.invalidate_recordset()
        self.assertEqual(t1.state, 'done')
        t2.invalidate_recordset()
        self.assertNotEqual(t2.state, 'done')

    def test_clarify_reschedule_select_with_time(self):
        t1 = self._make_task('Reschedule Clarify')
        pending = {
            'kind': KIND_PENDING_RESCHEDULE_SELECT,
            'new_remind_at': '2026-06-10T08:00:00+07:00',
            'candidates': [
                {'task_id': t1.id, 'task_name': t1.name, 'remind_at': None},
            ],
        }
        result = self._turn(INTENT_CLARIFY, {'task_id': t1.id}, state=pending)
        self.assertEqual(result['action_taken'], 'rescheduled')
        self.assertIsNone(result['new_session_state'])

    def test_clarify_reschedule_select_without_time_asks_time(self):
        t1 = self._make_task('No time clarify')
        pending = {
            'kind': KIND_PENDING_RESCHEDULE_SELECT,
            'new_remind_at': None,
            'candidates': [{'task_id': t1.id, 'task_name': t1.name, 'remind_at': None}],
        }
        result = self._turn(INTENT_CLARIFY, {'task_id': t1.id}, state=pending)
        self.assertEqual(result['action_taken'], 'asked')
        state = result['new_session_state']
        self.assertEqual(state['kind'], KIND_PENDING_RESCHEDULE_TIME)
        self.assertEqual(state['task_id'], t1.id)

    def test_clarify_without_task_id_asks_again(self):
        pending = {'kind': KIND_PENDING_COMPLETE, 'candidates': []}
        result = self._turn(INTENT_CLARIFY, {}, state=pending)
        self.assertEqual(result['action_taken'], 'asked')
        self.assertEqual(result['new_session_state']['kind'], KIND_PENDING_COMPLETE)

    def test_clarify_unknown_state_returns_error(self):
        result = self._turn(INTENT_CLARIFY, {'task_id': 1}, state={'kind': 'unknown_state'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['action_taken'], 'error')


@tagged('post_install', '-at_install')
class TestPrConversationList(TransactionCase):
    """Flow: list_open_personal_reminders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.personal.reminder.conversation.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'List User',
            'login': 'list_user@test.com',
            'email': 'list_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _turn(self, intent, params=None, state=None):
        return self.svc.handle_turn(self.user.id, intent, params or {}, state)

    def test_list_empty(self):
        result = self._turn(INTENT_LIST)
        self.assertTrue(result['ok'])
        self.assertEqual(result['action_taken'], 'listed')
        self.assertIsNone(result['new_session_state'])

    def test_list_with_tasks(self):
        self.env['dac.work.task'].create([
            {'name': 'List task 1', 'assigned_user_id': self.user.id,
             'is_personal_reminder': True, 'state': 'draft'},
            {'name': 'List task 2', 'assigned_user_id': self.user.id,
             'is_personal_reminder': True, 'state': 'in_progress'},
        ])
        result = self._turn(INTENT_LIST)
        self.assertEqual(result['action_taken'], 'listed')
        self.assertIn('List task 1', result['reply'])


@tagged('post_install', '-at_install')
class TestPrConversationChatApiEndpoint(TransactionCase):
    """HTTP chat endpoint tests via _run_mcp_handler."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        from odoo.addons.dac_erp.controllers.personal_reminder_controller import PersonalReminderController
        cls.ctrl = PersonalReminderController()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_write_key', 'chat-write-key')
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Chat API User',
            'login': 'chat_api_user@test.com',
            'email': 'chat_api_user@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _run(self, payload, headers=None):
        if headers is None:
            headers = {'X-MCP-API-KEY': 'chat-write-key'}
        return self.ctrl._run_mcp_handler(
            self.ctrl._dispatch_personal_reminders_chat,
            payload=payload,
            env=self.env,
            headers=headers,
        )

    def test_chat_create_full(self):
        payload, code = self._run({
            'user_id': self.user.id,
            'intent': 'create_personal_reminder',
            'params': {'name': 'Chat create task', 'remind_at': '2026-05-25T09:00:00+07:00'},
        })
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['action_taken'], 'created')

    def test_chat_create_missing_time_returns_state(self):
        payload, code = self._run({
            'user_id': self.user.id,
            'intent': 'create_personal_reminder',
            'params': {'name': 'Ask time via chat', 'date_hint': '2026-05-25'},
        })
        self.assertEqual(code, 200)
        self.assertEqual(payload['action_taken'], 'asked')
        self.assertIsNotNone(payload['new_session_state'])

    def test_chat_list_open(self):
        payload, code = self._run({
            'user_id': self.user.id,
            'intent': 'list_open_personal_reminders',
            'params': {},
        })
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])

    def test_chat_missing_user_id(self):
        payload, code = self._run({'intent': 'list_open_personal_reminders', 'params': {}})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_chat_missing_intent(self):
        payload, code = self._run({'user_id': self.user.id, 'params': {}})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_chat_unknown_intent(self):
        payload, code = self._run({
            'user_id': self.user.id,
            'intent': 'destroy_all_tasks',
            'params': {},
        })
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'unknown_intent')

    def test_chat_auth_missing_key(self):
        payload, code = self._run(
            {'user_id': self.user.id, 'intent': 'list_open_personal_reminders', 'params': {}},
            headers={},
        )
        self.assertEqual(code, 401)

    def test_chat_multi_turn_create_then_provide_time(self):
        # Turn 1: create without time → get pending state
        r1, _ = self._run({
            'user_id': self.user.id,
            'intent': 'create_personal_reminder',
            'params': {'name': 'Multi-turn task', 'date_hint': '2026-05-26'},
        })
        state = r1['new_session_state']
        self.assertEqual(state['kind'], 'pending_personal_reminder_create')

        # Turn 2: provide time using stored state → task created
        r2, code2 = self._run({
            'user_id': self.user.id,
            'intent': 'provide_missing_reminder_time',
            'params': {'remind_at': '2026-05-26T09:00:00+07:00'},
            'session_state': state,
        })
        self.assertEqual(code2, 200)
        self.assertEqual(r2['action_taken'], 'created')
        self.assertIsNone(r2['new_session_state'])
        self.assertIn('Multi-turn task', r2['reply'])

    def test_chat_reply_field_always_present(self):
        payload, code = self._run({
            'user_id': self.user.id,
            'intent': 'list_open_personal_reminders',
            'params': {},
        })
        self.assertIn('reply', payload)
        self.assertIsInstance(payload['reply'], str)
        self.assertGreater(len(payload['reply']), 0)
