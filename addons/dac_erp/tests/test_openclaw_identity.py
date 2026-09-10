"""Tests for Phần 6D:
  A. resolve_internal_recipient (model method + HTTP endpoint)
  B. reply_context in _build_openclaw_payload
  C. _inject_reply_context_tracking (event_type + event_id injected by _send_openclaw_webhook)
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.openclaw_identity_controller import OpenclawIdentityController

WRITE_KEY = 'identity-write-test-key'


@tagged('post_install', '-at_install')
class TestResolveInternalRecipientModel(TransactionCase):
    """Unit tests for dac.openclaw.user.mapping.resolve_internal_recipient()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Mapping = cls.env['dac.openclaw.user.mapping']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Identity Test User',
            'login': 'identity_test@test.com',
            'email': 'identity_test@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def setUp(self):
        super().setUp()
        self.mapping = self.Mapping.create({
            'user_id': self.user.id,
            'channel': 'zalouser',
            'target': 'test-zalo-identity-001',
            'active': True,
        })

    # ── Success ───────────────────────────────────────────────────────────

    def test_resolve_success_returns_user(self):
        result = self.Mapping.resolve_internal_recipient('zalouser', 'test-zalo-identity-001')
        self.assertTrue(result['found'])
        self.assertEqual(result['user_id'], self.user.id)
        self.assertEqual(result['user_name'], self.user.name)
        self.assertEqual(result['channel'], 'zalouser')
        self.assertEqual(result['target'], 'test-zalo-identity-001')
        self.assertIsNotNone(result['mapping_id'])
        self.assertEqual(result['role'], 'employee')

    def test_resolve_result_is_json_serializable(self):
        import json
        result = self.Mapping.resolve_internal_recipient('zalouser', 'test-zalo-identity-001')
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    # ── Not found ─────────────────────────────────────────────────────────

    def test_resolve_not_found_returns_found_false(self):
        result = self.Mapping.resolve_internal_recipient('zalouser', 'nonexistent-target-xyz')
        self.assertFalse(result['found'])
        self.assertIsNone(result['user_id'])
        self.assertIsNone(result['user_name'])
        self.assertIsNone(result['role'])
        self.assertIsNone(result['mapping_id'])

    def test_resolve_wrong_channel_not_found(self):
        result = self.Mapping.resolve_internal_recipient('telegram', 'test-zalo-identity-001')
        self.assertFalse(result['found'])

    # ── Inactive mapping ──────────────────────────────────────────────────

    def test_resolve_inactive_mapping_returns_not_found(self):
        self.mapping.write({'active': False})
        result = self.Mapping.resolve_internal_recipient('zalouser', 'test-zalo-identity-001')
        self.assertFalse(result['found'])
        self.assertIsNone(result['user_id'])

    # ── Validation ────────────────────────────────────────────────────────

    def test_resolve_missing_channel_raises(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Mapping.resolve_internal_recipient('', 'some-target')

    def test_resolve_missing_target_raises(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Mapping.resolve_internal_recipient('zalouser', '')

    def test_resolve_none_channel_raises(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Mapping.resolve_internal_recipient(None, 'some-target')

    # ── Role forwarded ────────────────────────────────────────────────────

    def test_resolve_manager_role_returned(self):
        mgr_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Manager Identity',
            'login': 'mgr_identity@test.com',
            'email': 'mgr_identity@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.Mapping.create({
            'user_id': mgr_user.id,
            'channel': 'telegram',
            'target': 'test-tg-mgr-001',
            'role': 'manager',
            'active': True,
        })
        result = self.Mapping.resolve_internal_recipient('telegram', 'test-tg-mgr-001')
        self.assertTrue(result['found'])
        self.assertEqual(result['role'], 'manager')


@tagged('post_install', '-at_install')
class TestResolveInternalRecipientEndpoint(TransactionCase):
    """HTTP endpoint tests for POST /dac_erp/mcp/v1/openclaw/resolve-internal-recipient."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.ctrl = OpenclawIdentityController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', WRITE_KEY)
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'identity-read-test-key')
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Endpoint Identity User',
            'login': 'ep_identity@test.com',
            'email': 'ep_identity@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.env['dac.openclaw.user.mapping'].create({
            'user_id': cls.user.id,
            'channel': 'zalouser',
            'target': 'ep-test-zalo-002',
            'active': True,
        })

    def _run(self, payload, headers=None):
        if headers is None:
            headers = {'X-MCP-API-KEY': WRITE_KEY}
        return self.ctrl._run_mcp_handler(
            self.ctrl._dispatch_resolve_internal_recipient,
            payload=payload,
            env=self.env,
            headers=headers,
        )

    # ── Success ───────────────────────────────────────────────────────────

    def test_endpoint_resolve_success(self):
        payload, code = self._run({'channel': 'zalouser', 'target': 'ep-test-zalo-002'})
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        data = payload['data']
        self.assertTrue(data['found'])
        self.assertEqual(data['user_id'], self.user.id)
        self.assertEqual(data['user_name'], self.user.name)

    def test_endpoint_response_shape(self):
        payload, code = self._run({'channel': 'zalouser', 'target': 'ep-test-zalo-002'})
        data = payload['data']
        for key in ('found', 'user_id', 'user_name', 'role', 'mapping_id', 'channel', 'target'):
            self.assertIn(key, data, msg='Missing key: %s' % key)

    # ── Not found ─────────────────────────────────────────────────────────

    def test_endpoint_not_found_returns_200_with_found_false(self):
        payload, code = self._run({'channel': 'zalouser', 'target': 'nobody-here'})
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertFalse(payload['data']['found'])
        self.assertIsNone(payload['data']['user_id'])

    # ── Auth ──────────────────────────────────────────────────────────────

    def test_endpoint_missing_key_returns_401(self):
        payload, code = self._run(
            {'channel': 'zalouser', 'target': 'ep-test-zalo-002'},
            headers={},
        )
        self.assertEqual(code, 401)
        self.assertFalse(payload['ok'])

    def test_endpoint_invalid_key_returns_403(self):
        payload, code = self._run(
            {'channel': 'zalouser', 'target': 'ep-test-zalo-002'},
            headers={'X-MCP-API-KEY': 'wrong-key'},
        )
        self.assertEqual(code, 403)

    def test_endpoint_read_key_rejected(self):
        payload, code = self._run(
            {'channel': 'zalouser', 'target': 'ep-test-zalo-002'},
            headers={'X-MCP-API-KEY': 'identity-read-test-key'},
        )
        self.assertEqual(code, 403)

    # ── Validation ────────────────────────────────────────────────────────

    def test_endpoint_missing_channel_returns_400(self):
        payload, code = self._run({'target': 'some-target'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_endpoint_missing_target_returns_400(self):
        payload, code = self._run({'channel': 'zalouser'})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    def test_endpoint_empty_target_returns_400(self):
        payload, code = self._run({'channel': 'zalouser', 'target': '   '})
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'missing_field')

    # ── Inactive skip ─────────────────────────────────────────────────────

    def test_endpoint_inactive_mapping_returns_not_found(self):
        inactive_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Inactive Map User',
            'login': 'inactive_map@test.com',
            'email': 'inactive_map@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.env['dac.openclaw.user.mapping'].create({
            'user_id': inactive_user.id,
            'channel': 'webchat',
            'target': 'inactive-webchat-003',
            'active': False,
        })
        payload, code = self._run({'channel': 'webchat', 'target': 'inactive-webchat-003'})
        self.assertEqual(code, 200)
        self.assertFalse(payload['data']['found'])


@tagged('post_install', '-at_install')
class TestReminderReplyContext(TransactionCase):
    """Tests for reply_context in _build_openclaw_payload."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.openclaw.notification.service']
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reply Context User',
            'login': 'reply_ctx@test.com',
            'email': 'reply_ctx@test.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.mapping = cls.env['dac.openclaw.user.mapping'].create({
            'user_id': cls.user.id,
            'channel': 'zalouser',
            'target': 'rc-test-zalo-004',
            'active': True,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'RC Partner'})

    def _make_personal_task(self, name='Personal reminder test'):
        return self.env['dac.work.task'].create({
            'name': name,
            'assigned_user_id': self.user.id,
            'is_personal_reminder': True,
            'personal_reminder_source': 'openclaw_chat',
            'state': 'draft',
        })

    def _make_regular_task(self, name='Regular task test'):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': 'quotation',
        })
        return self.env['dac.work.task'].create({
            'name': name,
            'assigned_user_id': self.user.id,
            'order_id': order.id,
            'state': 'draft',
        })

    # ── Personal reminder → kind=personal_reminder ────────────────────────

    def test_personal_task_has_reply_context(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertIn('reply_context', payload)

    def test_personal_task_reply_context_kind(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['kind'], 'personal_reminder')

    def test_personal_task_reply_context_task_id(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['task_id'], task.id)

    def test_personal_task_reply_context_task_name(self):
        task = self._make_personal_task('Gọi anh Nam')
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['task_name'], 'Gọi anh Nam')

    def test_personal_task_reply_context_assigned_user_id(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['assigned_user_id'], self.user.id)

    def test_personal_task_reply_context_has_remind_at_key(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertIn('remind_at', payload['reply_context'])

    # ── Regular task → kind=task_reminder ────────────────────────────────

    def test_regular_task_has_reply_context(self):
        task = self._make_regular_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertIn('reply_context', payload)

    def test_regular_task_reply_context_kind(self):
        task = self._make_regular_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['kind'], 'task_reminder')

    def test_regular_task_reply_context_task_id(self):
        task = self._make_regular_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertEqual(payload['reply_context']['task_id'], task.id)

    def test_regular_task_reply_context_no_remind_at(self):
        task = self._make_regular_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertNotIn('remind_at', payload['reply_context'])

    # ── Backward compatibility — existing fields intact ───────────────────

    def test_payload_task_field_intact(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertIn('task', payload)
        task_data = payload['task']
        for key in ('id', 'name', 'state', 'priority', 'deadline', 'remind_at',
                    'description', 'notes', 'assigned_user_name', 'order_name'):
            self.assertIn(key, task_data, msg='Missing task key: %s' % key)

    def test_payload_delivery_field_intact(self):
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        self.assertIn('delivery', payload)
        self.assertEqual(payload['delivery']['channel'], 'zalouser')
        self.assertEqual(payload['delivery']['target'], 'rc-test-zalo-004')

    def test_payload_is_json_serializable(self):
        import json
        task = self._make_personal_task()
        payload = self.svc._build_openclaw_payload(task, self.mapping)
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        self.assertIsInstance(serialized, str)
        parsed = json.loads(serialized)
        self.assertIn('reply_context', parsed)


@tagged('post_install', '-at_install')
class TestInjectReplyContextTracking(TransactionCase):
    """Unit tests for _inject_reply_context_tracking helper."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.svc = cls.env['dac.openclaw.notification.service']

    def _base_payload(self, kind='personal_reminder', task_id=42):
        return {
            'task': {'id': task_id, 'name': 'Test Task'},
            'delivery': {'channel': 'zalouser', 'target': 'tgt-001'},
            'reply_context': {
                'kind': kind,
                'task_id': task_id,
                'task_name': 'Test Task',
                'assigned_user_id': 7,
            },
        }

    # ── event_type injected ───────────────────────────────────────────────

    def test_inject_adds_event_type(self):
        payload = self._base_payload()
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-001')
        self.assertEqual(result['reply_context']['event_type'], 'task_reminder')

    def test_inject_adds_event_id(self):
        payload = self._base_payload()
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-001')
        self.assertEqual(result['reply_context']['event_id'], 'evt-001')

    def test_inject_preserves_existing_reply_context_fields(self):
        payload = self._base_payload(kind='personal_reminder', task_id=99)
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-abc')
        rc = result['reply_context']
        self.assertEqual(rc['kind'], 'personal_reminder')
        self.assertEqual(rc['task_id'], 99)
        self.assertEqual(rc['task_name'], 'Test Task')
        self.assertEqual(rc['assigned_user_id'], 7)

    def test_inject_preserves_task_and_delivery(self):
        payload = self._base_payload()
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-001')
        self.assertIn('task', result)
        self.assertIn('delivery', result)

    # ── Immutability — original not mutated ───────────────────────────────

    def test_inject_does_not_mutate_original_payload(self):
        payload = self._base_payload()
        original_rc_keys = set(payload['reply_context'].keys())
        self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-001')
        self.assertEqual(set(payload['reply_context'].keys()), original_rc_keys)
        self.assertNotIn('event_type', payload['reply_context'])
        self.assertNotIn('event_id', payload['reply_context'])

    def test_inject_does_not_mutate_original_reply_context(self):
        rc = {'kind': 'task_reminder', 'task_id': 1, 'task_name': 'X', 'assigned_user_id': 2}
        payload = {'task': {}, 'delivery': {}, 'reply_context': rc}
        self.svc._inject_reply_context_tracking(payload, 'task_assigned', 'evt-xyz')
        self.assertNotIn('event_type', rc)

    # ── No-op when reply_context absent ──────────────────────────────────

    def test_inject_noop_when_no_reply_context(self):
        payload = {'task': {'id': 1}, 'delivery': {'channel': 'telegram', 'target': 'tgt'}}
        result = self.svc._inject_reply_context_tracking(payload, 'task_assigned', 'evt-001')
        self.assertNotIn('reply_context', result)
        self.assertIn('task', result)

    def test_inject_noop_when_reply_context_is_none(self):
        payload = {'task': {}, 'delivery': {}, 'reply_context': None}
        result = self.svc._inject_reply_context_tracking(payload, 'task_assigned', 'evt-001')
        self.assertIsNone(result['reply_context'])

    # ── Result is JSON-serializable ───────────────────────────────────────

    def test_inject_result_is_json_serializable(self):
        import json
        payload = self._base_payload()
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'evt-001')
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        parsed = json.loads(serialized)
        self.assertEqual(parsed['reply_context']['event_type'], 'task_reminder')
        self.assertEqual(parsed['reply_context']['event_id'], 'evt-001')

    # ── Works for both task kinds ─────────────────────────────────────────

    def test_inject_personal_reminder_kind(self):
        payload = self._base_payload(kind='personal_reminder')
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'pr-evt-001')
        self.assertEqual(result['reply_context']['kind'], 'personal_reminder')
        self.assertEqual(result['reply_context']['event_id'], 'pr-evt-001')

    def test_inject_task_reminder_kind(self):
        payload = self._base_payload(kind='task_reminder')
        result = self.svc._inject_reply_context_tracking(payload, 'task_reminder', 'tr-evt-001')
        self.assertEqual(result['reply_context']['kind'], 'task_reminder')
        self.assertEqual(result['reply_context']['event_id'], 'tr-evt-001')
