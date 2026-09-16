from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController

READ_KEY = 'task-read-test-key'
WRITE_KEY = 'task-write-test-key'


@tagged('post_install', '-at_install')
class TestMcpTaskApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', READ_KEY)
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', WRITE_KEY)

        cls.has_pancake_models = (
            'page.fm.page' in cls.env.registry.models
            and 'page.fm.conversation' in cls.env.registry.models
        )

        cls.group_user = cls.env.ref('base.group_user')
        cls.sale_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Task Sale User',
            'login': 'task_sale_user@test.com',
            'email': 'task_sale_user@test.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Task Test Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Task Test Product',
            'type': 'service',
            'list_price': 500000.0,
        })

        if cls.has_pancake_models:
            cls.page = cls.env['page.fm.page'].create({
                'name': 'Task Test Page',
                'page_fm_id_str': 'task-test-page-001',
            })

    def setUp(self):
        super().setUp()
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.sale_user.id,
            'order_state_custom': 'quotation',
        })
        if self.has_pancake_models:
            self.conversation = self.env['page.fm.conversation'].create({
                'conversation_fm_id': 'task-conv-%s' % self._testMethodName,
                'page_fm_page_id': self.page.id,
                'partner_id': self.partner.id,
                'owner_id': self.sale_user.id,
            })

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _payload(self, request_id, **extra):
        d = {'request_id': request_id, 'agent_name': 'OpenClaw'}
        d.update(extra)
        return d

    def _run(self, method, *args, **kwargs):
        return self.controller._run_mcp_handler(method, *args, **kwargs)

    # ── Auth tests ────────────────────────────────────────────────────

    def test_auth_missing_key_list(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_list,
            env=self.env, headers={},
        )
        self.assertEqual(code, 401)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'missing_api_key')

    def test_auth_invalid_key_list(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_list,
            env=self.env, headers=self._headers('wrong-key'),
        )
        self.assertEqual(code, 403)
        self.assertFalse(payload['ok'])

    def test_auth_read_key_cannot_create(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload=self._payload('auth-read-create', name='Test', order_id=self.order.id),
        )
        self.assertEqual(code, 403)
        self.assertFalse(payload['ok'])

    # ── Create tests ──────────────────────────────────────────────────

    def test_create_task_with_order_success(self):
        request_id = 'task-create-001-%s' % self._testMethodName
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                request_id,
                name='Thiết kế banner',
                order_id=self.order.id,
                priority='high',
            ),
        )
        self.assertEqual(code, 200, msg=payload)
        self.assertTrue(payload['ok'])
        data = payload['data']
        self.assertEqual(data['name'], 'Thiết kế banner')
        self.assertEqual(data['priority'], 'high')
        self.assertEqual(data['state'], 'draft')
        self.assertEqual(data['order_id'], self.order.id)
        self.assertEqual(data['created_by_agent'], 'OpenClaw')

        # Log được tạo
        log = self.env['dac.erp.mcp.task.log'].sudo().search(
            [('request_id', '=', request_id)], limit=1
        )
        self.assertTrue(log, "Phải có task log sau khi tạo")
        self.assertEqual(log.action_type, 'task_create')
        self.assertEqual(log.status, 'success')

    def test_create_task_idempotency(self):
        request_id = 'task-idem-001-%s' % self._testMethodName
        base = self._payload(request_id, name='Duplicate Task', order_id=self.order.id)

        # Lần 1 — tạo
        payload1, code1 = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env, headers=self._headers(WRITE_KEY), payload=base,
        )
        self.assertEqual(code1, 200)
        task_id_first = payload1['data']['id']

        # Lần 2 — replay
        payload2, code2 = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env, headers=self._headers(WRITE_KEY), payload=base,
        )
        self.assertEqual(code2, 200)
        self.assertTrue(payload2['data'].get('_replayed'))

        # Chỉ một task được tạo
        count = self.env['dac.work.task'].sudo().search_count(
            [('id', '=', task_id_first)]
        )
        self.assertEqual(count, 1)

    def test_create_task_missing_link_fails(self):
        """Thiếu cả order_id lẫn conversation_id → 400."""
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload('task-no-link-%s' % self._testMethodName, name='Task tangled'),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_create_task_invalid_order_fails(self):
        """order_id không tồn tại → 400 ValueError."""
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                'task-bad-order-%s' % self._testMethodName,
                name='Bad Order Task',
                order_id=999999999,
            ),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_create_task_missing_name_fails(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                'task-no-name-%s' % self._testMethodName,
                order_id=self.order.id,
            ),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_create_task_unknown_field_fails(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                'task-unknown-%s' % self._testMethodName,
                name='Task X',
                order_id=self.order.id,
                unknown_field='oops',
            ),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])

    def test_create_task_with_conversation(self):
        if not self.has_pancake_models:
            self.skipTest("CRM_DAC not loaded")
        request_id = 'task-conv-create-%s' % self._testMethodName
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                request_id,
                name='Trả lời khách',
                conversation_id=self.conversation.id,
            ),
        )
        self.assertEqual(code, 200, msg=payload)
        self.assertEqual(payload['data']['conversation_id'], self.conversation.id)

    # ── Get tests ─────────────────────────────────────────────────────

    def test_get_task_success(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Get Task Test',
            'order_id': self.order.id,
        })
        payload, code = self._run(
            self.controller._dispatch_mcp_task_get,
            task.id,
            env=self.env,
            headers=self._headers(READ_KEY),
        )
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['id'], task.id)

    def test_get_task_not_found(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_get,
            999999999,
            env=self.env,
            headers=self._headers(READ_KEY),
        )
        self.assertEqual(code, 404)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'task_not_found')

    # ── List tests ────────────────────────────────────────────────────

    def test_list_tasks_filter_by_order(self):
        other_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.sale_user.id,
            'order_state_custom': 'quotation',
        })
        self.env['dac.work.task'].sudo().create([
            {'name': 'Task A', 'order_id': self.order.id},
            {'name': 'Task B', 'order_id': self.order.id},
            {'name': 'Task C', 'order_id': other_order.id},
        ])
        payload, code = self._run(
            self.controller._dispatch_mcp_task_list,
            env=self.env,
            headers=self._headers(READ_KEY),
            order_id=str(self.order.id),
        )
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        ids_returned = [item['order_id'] for item in payload['items']]
        self.assertTrue(all(i == self.order.id for i in ids_returned))

    # ── Update tests ──────────────────────────────────────────────────

    def test_update_task_state_success(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Update Test Task',
            'order_id': self.order.id,
        })
        request_id = 'task-update-001-%s' % self._testMethodName
        payload, code = self._run(
            self.controller._dispatch_mcp_task_update,
            task.id,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(request_id, state='in_progress'),
        )
        self.assertEqual(code, 200, msg=payload)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['state'], 'in_progress')
        self.assertEqual(task.state, 'in_progress')

    def test_update_task_blocked_state(self):
        """Không được phép update task đã done."""
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Done Task',
            'order_id': self.order.id,
            'state': 'done',
        })
        payload, code = self._run(
            self.controller._dispatch_mcp_task_update,
            task.id,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload('task-blocked-%s' % self._testMethodName, name='Try to modify'),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'task_state_blocked')

    def test_update_task_blocked_state_cancelled(self):
        """Không được phép update task đã cancelled."""
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Cancelled Task',
            'order_id': self.order.id,
            'state': 'cancelled',
        })
        payload, code = self._run(
            self.controller._dispatch_mcp_task_update,
            task.id,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload('task-cancelled-%s' % self._testMethodName, name='Try to modify'),
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'task_state_blocked')

    def test_update_task_not_found(self):
        payload, code = self._run(
            self.controller._dispatch_mcp_task_update,
            999999999,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload('task-upd-nf-%s' % self._testMethodName, state='done'),
        )
        self.assertEqual(code, 404)
        self.assertFalse(payload['ok'])

    # ── remind_at tests ───────────────────────────────────────────────

    def test_create_task_with_remind_at(self):
        request_id = 'task-remind-create-%s' % self._testMethodName
        payload, code = self._run(
            self.controller._dispatch_mcp_task_create,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(
                request_id,
                name='Task có nhắc nhở',
                order_id=self.order.id,
                remind_at='2026-05-15 09:00:00',
            ),
        )
        self.assertEqual(code, 200, msg=payload)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['remind_at'], '2026-05-15T09:00:00')

    def test_update_task_remind_at(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Update remind_at Test',
            'order_id': self.order.id,
        })
        request_id = 'task-remind-update-%s' % self._testMethodName
        payload, code = self._run(
            self.controller._dispatch_mcp_task_update,
            task.id,
            env=self.env,
            headers=self._headers(WRITE_KEY),
            payload=self._payload(request_id, remind_at='2026-05-16 08:00:00'),
        )
        self.assertEqual(code, 200, msg=payload)
        self.assertEqual(payload['data']['remind_at'], '2026-05-16T08:00:00')
        self.assertTrue(task.remind_at)

    def test_serialize_task_includes_remind_at_null_when_not_set(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'No remind Task',
            'order_id': self.order.id,
        })
        payload, code = self._run(
            self.controller._dispatch_mcp_task_get,
            task.id,
            env=self.env,
            headers=self._headers(READ_KEY),
        )
        self.assertEqual(code, 200)
        self.assertIn('remind_at', payload['data'])
        self.assertIsNone(payload['data']['remind_at'])
