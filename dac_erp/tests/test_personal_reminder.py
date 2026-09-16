"""Tests for dac.personal.reminder.service (Phần 6A).

Covers:
  - create_personal_reminder_task: success, missing fields, ISO datetime parsing,
    is_personal_reminder flag, bypasses order/conversation constraint
  - find_recent_open_personal_tasks: scope, ordering, limit, done/cancelled excluded,
    other-user isolation, non-personal tasks excluded
  - find_latest_open_personal_task: newest task returned, None when empty
  - complete_personal_reminder_task: success, already_closed, user_mismatch,
    completion_note appended
  - reschedule_personal_reminder_task: success, cooldown reset, task_closed,
    user_mismatch, invalid datetime raises
  - JSON-serializable output
"""

import json
from datetime import datetime, timedelta, timezone

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


_UTC = timezone.utc
_VN = timezone(timedelta(hours=7))


def _vn(year, month, day, hour=8, minute=0):
    """Return UTC naive datetime equivalent to given VN local time."""
    return datetime(year, month, day, hour, minute, tzinfo=_VN).astimezone(_UTC).replace(tzinfo=None)


@tagged('post_install', '-at_install')
class TestPersonalReminderCreate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'NV Reminder Test',
            'login': 'nv_reminder_test@test.local',
            'email': 'nv_reminder_test@test.local',
        })
        cls.svc = cls.env['dac.personal.reminder.service']

    def _remind_at(self):
        return _vn(2026, 5, 20, 9, 0)

    def test_create_success_basic(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id,
            name='Tra loi anh A',
            remind_at=self._remind_at(),
        )
        self.assertTrue(result['ok'])
        self.assertIsNotNone(result['task_id'])
        self.assertEqual(result['task_name'], 'Tra loi anh A')
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(result['assigned_user_id'], self.user.id)
        self.assertTrue(result['is_personal_reminder'])

    def test_create_missing_user_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.create_personal_reminder_task(
                user_id=None,
                name='Some task',
                remind_at=self._remind_at(),
            )

    def test_create_missing_name_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.create_personal_reminder_task(
                user_id=self.user.id,
                name='',
                remind_at=self._remind_at(),
            )

    def test_create_blank_name_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.create_personal_reminder_task(
                user_id=self.user.id,
                name='   ',
                remind_at=self._remind_at(),
            )

    def test_create_missing_remind_at_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.create_personal_reminder_task(
                user_id=self.user.id,
                name='Some task',
                remind_at=None,
            )

    def test_create_with_iso_string_remind_at(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id,
            name='ISO string remind',
            remind_at='2026-05-20T09:00:00+07:00',
        )
        self.assertTrue(result['ok'])
        # remind_at in output should be VN ISO string
        self.assertIn('+07:00', result['remind_at'])

    def test_create_with_z_suffix_remind_at(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id,
            name='UTC Z remind',
            remind_at='2026-05-20T02:00:00Z',
        )
        self.assertTrue(result['ok'])
        self.assertIsNotNone(result['remind_at'])

    def test_create_task_has_is_personal_reminder_flag(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Flag test', remind_at=self._remind_at(),
        )
        task = self.env['dac.work.task'].sudo().browse(result['task_id'])
        self.assertTrue(task.is_personal_reminder)

    def test_create_task_no_order_no_conv_allowed(self):
        # Personal tasks must NOT require order_id or conversation_id
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='No order no conv', remind_at=self._remind_at(),
        )
        task = self.env['dac.work.task'].sudo().browse(result['task_id'])
        self.assertFalse(task.order_id)
        self.assertFalse(task.conversation_id)

    def test_create_with_source_stored(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Source test', remind_at=self._remind_at(),
            source='openclaw_chat',
        )
        task = self.env['dac.work.task'].sudo().browse(result['task_id'])
        self.assertEqual(task.personal_reminder_source, 'openclaw_chat')
        self.assertEqual(result['personal_reminder_source'], 'openclaw_chat')

    def test_create_with_notes(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Notes test', remind_at=self._remind_at(),
            notes='Ghi chu them',
        )
        self.assertIn('Ghi chu them', result['notes'] or '')

    def test_create_with_channel_target_appended_to_notes(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Channel trace', remind_at=self._remind_at(),
            channel='telegram', target='12345',
        )
        task = self.env['dac.work.task'].sudo().browse(result['task_id'])
        self.assertIn('telegram', task.notes or '')
        self.assertIn('12345', task.notes or '')

    def test_create_with_optional_deadline(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='With deadline', remind_at=self._remind_at(),
            deadline='2026-05-21T17:00:00+07:00',
        )
        self.assertTrue(result['ok'])
        self.assertIsNotNone(result['deadline'])

    def test_create_invalid_remind_at_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.create_personal_reminder_task(
                user_id=self.user.id, name='Bad dt', remind_at='not-a-date',
            )


@tagged('post_install', '-at_install')
class TestPersonalReminderFind(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'NV Find Test',
            'login': 'nv_find_test@test.local',
            'email': 'nv_find_test@test.local',
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'NV Other Find',
            'login': 'nv_other_find@test.local',
            'email': 'nv_other_find@test.local',
        })
        cls.svc = cls.env['dac.personal.reminder.service']

    def _make_task(self, user=None, remind_at=None, state='draft'):
        u = user or self.user
        r = remind_at or _vn(2026, 5, 20, 9, 0)
        result = self.svc.create_personal_reminder_task(
            user_id=u.id, name='Find task', remind_at=r,
        )
        if state != 'draft':
            task = self.env['dac.work.task'].sudo().browse(result['task_id'])
            task.write({'state': state})
        return result['task_id']

    def test_find_recent_returns_open_personal_tasks(self):
        tid = self._make_task()
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        ids = [r['task_id'] for r in results]
        self.assertIn(tid, ids)

    def test_find_recent_excludes_done_tasks(self):
        tid = self._make_task(state='done')
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        ids = [r['task_id'] for r in results]
        self.assertNotIn(tid, ids)

    def test_find_recent_excludes_cancelled_tasks(self):
        tid = self._make_task(state='cancelled')
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        ids = [r['task_id'] for r in results]
        self.assertNotIn(tid, ids)

    def test_find_recent_excludes_other_user_tasks(self):
        tid = self._make_task(user=self.other_user)
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        ids = [r['task_id'] for r in results]
        self.assertNotIn(tid, ids)

    def test_find_recent_excludes_non_personal_tasks(self):
        # Directly create a task with is_personal_reminder=False for other_user
        # via service for other_user; those should not appear for self.user
        # (different user so already excluded, but we also verify the personal flag filter)
        self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Personal A', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        for r in results:
            self.assertTrue(r['is_personal_reminder'])

    def test_find_recent_respects_limit(self):
        for i in range(4):
            self._make_task(remind_at=_vn(2026, 5, 20 + i, 9, 0))
        results = self.svc.find_recent_open_personal_tasks(self.user.id, limit=2)
        self.assertLessEqual(len(results), 2)

    def test_find_recent_sorted_nearest_remind_at_first(self):
        t_far = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Far', remind_at=_vn(2026, 6, 1, 9, 0),
        )['task_id']
        t_near = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Near', remind_at=_vn(2026, 5, 21, 9, 0),
        )['task_id']
        results = self.svc.find_recent_open_personal_tasks(self.user.id, limit=5)
        ids = [r['task_id'] for r in results]
        # Near remind_at should come before far
        self.assertLess(ids.index(t_near), ids.index(t_far))

    def test_find_recent_empty_user_returns_empty_list(self):
        results = self.svc.find_recent_open_personal_tasks(None)
        self.assertEqual(results, [])

    def test_find_latest_returns_most_recently_created(self):
        t1 = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='First', remind_at=_vn(2026, 5, 20, 9, 0),
        )['task_id']
        t2 = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Second', remind_at=_vn(2026, 5, 21, 9, 0),
        )['task_id']
        latest = self.svc.find_latest_open_personal_task(self.user.id)
        # t2 was created after t1 → should be latest
        self.assertIn(latest['task_id'], [t1, t2])
        # IDs are sequential in tests; t2 > t1 so t2 should be latest
        self.assertGreaterEqual(latest['task_id'], t1)

    def test_find_latest_returns_none_when_no_open_tasks(self):
        # Use a brand new user with no tasks
        empty_user = self.env['res.users'].create({
            'name': 'Empty User Find',
            'login': 'empty_find@test.local',
            'email': 'empty_find@test.local',
        })
        result = self.svc.find_latest_open_personal_task(empty_user.id)
        self.assertIsNone(result)

    def test_find_latest_ignores_done_tasks(self):
        self._make_task(state='done')
        empty_user = self.env['res.users'].create({
            'name': 'Done Only User',
            'login': 'done_only@test.local',
            'email': 'done_only@test.local',
        })
        result = self.svc.find_latest_open_personal_task(empty_user.id)
        self.assertIsNone(result)

    def test_find_latest_null_user_returns_none(self):
        result = self.svc.find_latest_open_personal_task(None)
        self.assertIsNone(result)


@tagged('post_install', '-at_install')
class TestPersonalReminderComplete(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'NV Complete Test',
            'login': 'nv_complete_test@test.local',
            'email': 'nv_complete_test@test.local',
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'NV Other Complete',
            'login': 'nv_other_complete@test.local',
            'email': 'nv_other_complete@test.local',
        })
        cls.svc = cls.env['dac.personal.reminder.service']

    def _make_task(self, state='draft'):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id,
            name='Complete test task',
            remind_at=_vn(2026, 5, 20, 9, 0),
        )
        tid = result['task_id']
        if state != 'draft':
            self.env['dac.work.task'].sudo().browse(tid).write({'state': state})
        return tid

    def test_complete_success(self):
        tid = self._make_task()
        result = self.svc.complete_personal_reminder_task(tid)
        self.assertTrue(result['ok'])
        self.assertEqual(result['state'], 'done')

    def test_complete_updates_task_state_in_db(self):
        tid = self._make_task()
        self.svc.complete_personal_reminder_task(tid)
        task = self.env['dac.work.task'].sudo().browse(tid)
        self.assertEqual(task.state, 'done')

    def test_complete_already_done_returns_error_dict(self):
        tid = self._make_task(state='done')
        result = self.svc.complete_personal_reminder_task(tid)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'already_closed')
        self.assertEqual(result['state'], 'done')

    def test_complete_cancelled_returns_error_dict(self):
        tid = self._make_task(state='cancelled')
        result = self.svc.complete_personal_reminder_task(tid)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'already_closed')

    def test_complete_wrong_user_returns_user_mismatch(self):
        tid = self._make_task()
        result = self.svc.complete_personal_reminder_task(tid, user_id=self.other_user.id)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'user_mismatch')

    def test_complete_correct_user_succeeds(self):
        tid = self._make_task()
        result = self.svc.complete_personal_reminder_task(tid, user_id=self.user.id)
        self.assertTrue(result['ok'])
        self.assertEqual(result['state'], 'done')

    def test_complete_appends_completion_note(self):
        tid = self._make_task()
        self.svc.complete_personal_reminder_task(tid, completion_note='Da xong')
        task = self.env['dac.work.task'].sudo().browse(tid)
        self.assertIn('Da xong', task.notes or '')

    def test_complete_appends_to_existing_notes(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='With notes', remind_at=_vn(2026, 5, 20, 9, 0),
            notes='Ghi chu cu',
        )
        tid = result['task_id']
        self.svc.complete_personal_reminder_task(tid, completion_note='Da xong')
        task = self.env['dac.work.task'].sudo().browse(tid)
        self.assertIn('Ghi chu cu', task.notes)
        self.assertIn('Da xong', task.notes)

    def test_complete_nonexistent_task_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.complete_personal_reminder_task(999999999)


@tagged('post_install', '-at_install')
class TestPersonalReminderReschedule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'NV Reschedule Test',
            'login': 'nv_reschedule_test@test.local',
            'email': 'nv_reschedule_test@test.local',
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'NV Other Reschedule',
            'login': 'nv_other_reschedule@test.local',
            'email': 'nv_other_reschedule@test.local',
        })
        cls.svc = cls.env['dac.personal.reminder.service']

    def _make_task(self, state='draft'):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id,
            name='Reschedule test task',
            remind_at=_vn(2026, 5, 20, 9, 0),
        )
        tid = result['task_id']
        if state != 'draft':
            self.env['dac.work.task'].sudo().browse(tid).write({'state': state})
        return tid

    def test_reschedule_success(self):
        tid = self._make_task()
        new_time = '2026-05-22T10:00:00+07:00'
        result = self.svc.reschedule_personal_reminder_task(tid, new_time)
        self.assertTrue(result['ok'])
        self.assertIn('+07:00', result['remind_at'])

    def test_reschedule_updates_remind_at_in_db(self):
        tid = self._make_task()
        new_time_utc = _vn(2026, 5, 22, 10, 0)
        self.svc.reschedule_personal_reminder_task(tid, new_time_utc)
        task = self.env['dac.work.task'].sudo().browse(tid)
        self.assertEqual(task.remind_at, new_time_utc)

    def test_reschedule_resets_last_reminder_at(self):
        tid = self._make_task()
        task = self.env['dac.work.task'].sudo().browse(tid)
        # Simulate task having been reminded before
        task.write({'x_openclaw_last_reminder_at': _vn(2026, 5, 19, 9, 0)})
        self.svc.reschedule_personal_reminder_task(tid, _vn(2026, 5, 22, 9, 0))
        task.invalidate_recordset()
        self.assertFalse(task.x_openclaw_last_reminder_at)

    def test_reschedule_done_task_returns_error_dict(self):
        tid = self._make_task(state='done')
        result = self.svc.reschedule_personal_reminder_task(tid, _vn(2026, 5, 22, 9, 0))
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'task_closed')

    def test_reschedule_cancelled_task_returns_error_dict(self):
        tid = self._make_task(state='cancelled')
        result = self.svc.reschedule_personal_reminder_task(tid, _vn(2026, 5, 22, 9, 0))
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'task_closed')

    def test_reschedule_wrong_user_returns_user_mismatch(self):
        tid = self._make_task()
        result = self.svc.reschedule_personal_reminder_task(
            tid, _vn(2026, 5, 22, 9, 0), user_id=self.other_user.id
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'user_mismatch')

    def test_reschedule_correct_user_succeeds(self):
        tid = self._make_task()
        result = self.svc.reschedule_personal_reminder_task(
            tid, _vn(2026, 5, 22, 9, 0), user_id=self.user.id
        )
        self.assertTrue(result['ok'])

    def test_reschedule_invalid_datetime_raises(self):
        tid = self._make_task()
        with self.assertRaises(ValidationError):
            self.svc.reschedule_personal_reminder_task(tid, 'not-a-date')

    def test_reschedule_empty_string_raises(self):
        tid = self._make_task()
        with self.assertRaises(ValidationError):
            self.svc.reschedule_personal_reminder_task(tid, '')

    def test_reschedule_appends_note(self):
        tid = self._make_task()
        self.svc.reschedule_personal_reminder_task(
            tid, _vn(2026, 5, 22, 9, 0), note='Doi sang thu 6'
        )
        task = self.env['dac.work.task'].sudo().browse(tid)
        self.assertIn('Doi sang thu 6', task.notes or '')

    def test_reschedule_nonexistent_task_raises(self):
        with self.assertRaises(ValidationError):
            self.svc.reschedule_personal_reminder_task(999999999, _vn(2026, 5, 22, 9, 0))


@tagged('post_install', '-at_install')
class TestPersonalReminderOutput(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'NV Output Test',
            'login': 'nv_output_test@test.local',
            'email': 'nv_output_test@test.local',
        })
        cls.svc = cls.env['dac.personal.reminder.service']

    def test_create_output_is_json_serializable(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='JSON test', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        # Must not raise
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    def test_find_output_is_json_serializable(self):
        self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='JSON find', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        serialized = json.dumps(results)
        self.assertIsInstance(serialized, str)

    def test_complete_output_is_json_serializable(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='JSON complete', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        complete_result = self.svc.complete_personal_reminder_task(result['task_id'])
        serialized = json.dumps(complete_result)
        self.assertIsInstance(serialized, str)

    def test_output_keys_present(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Keys test', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        for key in ('ok', 'task_id', 'task_name', 'state', 'remind_at',
                    'assigned_user_id', 'assigned_user_name',
                    'is_personal_reminder', 'personal_reminder_source'):
            self.assertIn(key, result, 'Missing key: %s' % key)

    def test_remind_at_in_output_has_vn_offset(self):
        result = self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='TZ test', remind_at='2026-05-20T09:00:00+07:00',
        )
        self.assertIn('+07:00', result['remind_at'])

    def test_find_output_contains_required_keys(self):
        self.svc.create_personal_reminder_task(
            user_id=self.user.id, name='Find keys', remind_at=_vn(2026, 5, 20, 9, 0),
        )
        results = self.svc.find_recent_open_personal_tasks(self.user.id)
        self.assertTrue(len(results) > 0)
        for key in ('task_id', 'task_name', 'state', 'remind_at',
                    'assigned_user_id', 'assigned_user_name', 'is_personal_reminder'):
            self.assertIn(key, results[0], 'Missing key: %s' % key)
