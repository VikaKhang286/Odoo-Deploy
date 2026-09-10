"""Tests for POST /dac_erp/mcp/v1/personal-reminders controller.

Uses _run_mcp_handler to invoke dispatch methods directly, bypassing HTTP
transport, identical to the pattern in test_mcp_task_api.py.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.personal_reminder_controller import PersonalReminderController

READ_KEY = 'pr-read-test-key'
WRITE_KEY = 'pr-write-test-key'


@tagged('post_install', '-at_install')
class TestPersonalReminderApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = PersonalReminderController()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_read_key', READ_KEY)
        icp.set_param('dac_erp.mcp_write_key', WRITE_KEY)

        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PR API Test User',
            'login': 'pr_api_test@test.com',
            'email': 'pr_api_test@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _headers(self, key=WRITE_KEY):
        return {'X-MCP-API-KEY': key}

    def _run(self, payload, headers=None):
        """Invoke the dispatch method via _run_mcp_handler, returns (payload, code)."""
        if headers is None:
            headers = self._headers()
        return self.controller._run_mcp_handler(
            self.controller._dispatch_personal_reminders,
            payload=payload,
            env=self.env,
            headers=headers,
        )

    # ── Auth ─────────────────────────────────────────────────────────────

    def test_auth_missing_key(self):
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id}, headers={})
        self.assertEqual(code, 401)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'missing_api_key')

    def test_auth_invalid_key(self):
        payload, code = self._run(
            {'action': 'list_open', 'user_id': self.user.id},
            headers=self._headers('bad-key'),
        )
        self.assertEqual(code, 403)
        self.assertFalse(payload['ok'])

    def test_auth_read_key_rejected(self):
        payload, code = self._run(
            {'action': 'list_open', 'user_id': self.user.id},
            headers=self._headers(READ_KEY),
        )
        self.assertEqual(code, 403)
        self.assertFalse(payload['ok'])

    # ── Action validation ─────────────────────────────────────────────────

    def test_missing_action_field(self):
        payload, code = self._run({'user_id': self.user.id})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_action')

    def test_unknown_action(self):
        payload, code = self._run({'action': 'destroy_everything', 'user_id': self.user.id})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'unknown_action')

    # ── create ───────────────────────────────────────────────────────────

    def test_create_success(self):
        payload, code = self._run({
            'action': 'create',
            'user_id': self.user.id,
            'name': 'Gọi lại khách',
            'remind_at': '2026-05-20T09:00:00+07:00',
        })
        self.assertEqual(code, 200, msg=payload)
        self.assertTrue(payload['ok'])
        data = payload['data']
        self.assertTrue(data['ok'])
        self.assertIsNotNone(data['task_id'])
        self.assertEqual(data['task_name'], 'Gọi lại khách')
        self.assertTrue(data['is_personal_reminder'])

    def test_create_missing_user_id(self):
        payload, code = self._run({
            'action': 'create',
            'name': 'Test',
            'remind_at': '2026-05-20T09:00:00+07:00',
        })
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_create_missing_name(self):
        payload, code = self._run({
            'action': 'create',
            'user_id': self.user.id,
            'remind_at': '2026-05-20T09:00:00+07:00',
        })
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_create_missing_remind_at(self):
        payload, code = self._run({
            'action': 'create',
            'user_id': self.user.id,
            'name': 'Test',
        })
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_create_invalid_datetime(self):
        payload, code = self._run({
            'action': 'create',
            'user_id': self.user.id,
            'name': 'Test',
            'remind_at': 'not-a-date',
        })
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_create_with_source(self):
        payload, code = self._run({
            'action': 'create',
            'user_id': self.user.id,
            'name': 'Nhắc họp',
            'remind_at': '2026-05-20T10:00:00+07:00',
            'source': 'openclaw_chat',
        })
        self.assertEqual(code, 200)
        self.assertEqual(payload['data']['personal_reminder_source'], 'openclaw_chat')

    # ── list_open ─────────────────────────────────────────────────────────

    def test_list_open_returns_empty(self):
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id})
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertIn('items', payload)
        self.assertIsInstance(payload['items'], list)

    def test_list_open_missing_user_id(self):
        payload, code = self._run({'action': 'list_open'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_list_open_returns_created_task(self):
        self.env['dac.work.task'].create({
            'name': 'Nhắc việc list test',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'personal_reminder_source': 'openclaw_chat',
            'state': 'draft',
        })
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id})
        self.assertEqual(code, 200)
        names = [item['task_name'] for item in payload['items']]
        self.assertIn('Nhắc việc list test', names)

    def test_list_open_respects_limit(self):
        for i in range(4):
            self.env['dac.work.task'].create({
                'name': 'Limit test %d' % i,
                'assigned_user_id': self.user.id,
                'is_personal_reminder': True,
                'state': 'draft',
            })
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id, 'limit': 2})
        self.assertEqual(code, 200)
        self.assertLessEqual(len(payload['items']), 2)

    def test_list_open_invalid_limit(self):
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id, 'limit': 'abc'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'invalid_field')

    # ── get_latest_open ───────────────────────────────────────────────────

    def test_get_latest_open_no_tasks(self):
        new_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PR Empty User',
            'login': 'pr_empty_user@test.com',
            'email': 'pr_empty_user@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        payload, code = self._run({'action': 'get_latest_open', 'user_id': new_user.id})
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['data'])

    def test_get_latest_open_returns_task(self):
        task = self.env['dac.work.task'].create({
            'name': 'Latest open test',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        payload, code = self._run({'action': 'get_latest_open', 'user_id': self.user.id})
        self.assertEqual(code, 200)
        self.assertIsNotNone(payload['data'])
        self.assertEqual(payload['data']['task_id'], task.id)

    def test_get_latest_open_missing_user_id(self):
        payload, code = self._run({'action': 'get_latest_open'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    # ── complete ──────────────────────────────────────────────────────────

    def test_complete_success(self):
        task = self.env['dac.work.task'].create({
            'name': 'Hoàn thành test',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'in_progress',
        })
        payload, code = self._run({
            'action': 'complete',
            'task_id': task.id,
            'user_id': self.user.id,
        })
        self.assertEqual(code, 200)
        self.assertTrue(payload['data']['ok'])
        self.assertEqual(payload['data']['state'], 'done')
        task.invalidate_recordset()
        self.assertEqual(task.state, 'done')

    def test_complete_already_closed_returns_409(self):
        task = self.env['dac.work.task'].create({
            'name': 'Done task',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'done',
        })
        payload, code = self._run({'action': 'complete', 'task_id': task.id})
        self.assertEqual(code, 409)
        self.assertFalse(payload['data']['ok'])
        self.assertEqual(payload['data']['error'], 'already_closed')

    def test_complete_user_mismatch_returns_409(self):
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PR Other User',
            'login': 'pr_other@test.com',
            'email': 'pr_other@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        task = self.env['dac.work.task'].create({
            'name': 'Mismatch task',
            'assigned_user_id': other.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        payload, code = self._run({'action': 'complete', 'task_id': task.id, 'user_id': self.user.id})
        self.assertEqual(code, 409)
        self.assertEqual(payload['data']['error'], 'user_mismatch')

    def test_complete_missing_task_id(self):
        payload, code = self._run({'action': 'complete'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    # ── reschedule ────────────────────────────────────────────────────────

    def test_reschedule_success(self):
        task = self.env['dac.work.task'].create({
            'name': 'Reschedule test',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        payload, code = self._run({
            'action': 'reschedule',
            'task_id': task.id,
            'new_remind_at': '2026-06-01T08:00:00+07:00',
            'user_id': self.user.id,
        })
        self.assertEqual(code, 200)
        self.assertTrue(payload['data']['ok'])
        self.assertIsNotNone(payload['data']['remind_at'])

    def test_reschedule_already_closed_returns_409(self):
        task = self.env['dac.work.task'].create({
            'name': 'Closed reschedule',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'cancelled',
        })
        payload, code = self._run({
            'action': 'reschedule',
            'task_id': task.id,
            'new_remind_at': '2026-06-01T08:00:00+07:00',
        })
        self.assertEqual(code, 409)
        self.assertFalse(payload['data']['ok'])
        self.assertEqual(payload['data']['error'], 'task_closed')

    def test_reschedule_invalid_datetime(self):
        task = self.env['dac.work.task'].create({
            'name': 'Invalid dt reschedule',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        payload, code = self._run({
            'action': 'reschedule',
            'task_id': task.id,
            'new_remind_at': 'not-a-date',
        })
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_reschedule_missing_task_id(self):
        payload, code = self._run({'action': 'reschedule', 'new_remind_at': '2026-06-01T08:00:00+07:00'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_reschedule_missing_new_remind_at(self):
        task = self.env['dac.work.task'].create({
            'name': 'Missing remind_at',
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'state': 'draft',
        })
        payload, code = self._run({'action': 'reschedule', 'task_id': task.id})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    # ── Response shape ────────────────────────────────────────────────────

    def test_response_ok_field_present(self):
        payload, code = self._run({'action': 'list_open', 'user_id': self.user.id})
        self.assertIn('ok', payload)

    def test_error_response_shape(self):
        payload, code = self._run({'action': 'bad_action', 'user_id': self.user.id})
        self.assertFalse(payload['ok'])
        self.assertIn('error', payload)
        self.assertIn('code', payload['error'])
        self.assertIn('message', payload['error'])
