from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp_phase1_extension import MCPPhase1ExtensionController


@tagged('post_install', '-at_install')
class TestPhase1ConversationAssign(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPPhase1ExtensionController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')

        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")

        group_user = cls.env.ref('base.group_user')
        cls.user_a = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assign User A', 'login': 'assign_a@example.com',
            'email': 'assign_a@example.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.user_b = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assign User B', 'login': 'assign_b@example.com',
            'email': 'assign_b@example.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Assign Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Assign Page', 'page_fm_id_str': 'assign-page-001',
        })

    def setUp(self):
        super().setUp()
        self.conv = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'assign-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Test Customer',
        })

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _meta(self, request_id, **extra):
        body = {'request_id': request_id, 'agent_name': 'OpenClaw'}
        body.update(extra)
        return body

    def test_assign_owner_success(self):
        body = self._meta('assign-001', owner_user_id=self.user_a.id)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200, payload)
        self.conv.invalidate_recordset()
        self.assertEqual(self.conv.owner_id.id, self.user_a.id)
        log = self.env['dac_erp.mcp.conversation.assign.log'].search(
            [('request_id', '=', 'assign-001')], limit=1)
        self.assertTrue(log)

    def test_assign_participants_success(self):
        body = self._meta('assign-part-001', participant_user_ids=[self.user_a.id, self.user_b.id])
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200)
        self.conv.invalidate_recordset()
        self.assertEqual(set(self.conv.participant_user_ids.ids), {self.user_a.id, self.user_b.id})

    def test_assign_owner_and_participants(self):
        body = self._meta(
            'assign-both-001',
            owner_user_id=self.user_a.id,
            participant_user_ids=[self.user_a.id, self.user_b.id],
        )
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200)
        self.conv.invalidate_recordset()
        self.assertEqual(self.conv.owner_id.id, self.user_a.id)
        self.assertEqual(set(self.conv.participant_user_ids.ids), {self.user_a.id, self.user_b.id})

    def test_assign_clear_owner(self):
        # Set trước rồi clear
        self.conv.sudo().write({'owner_id': self.user_a.id})
        body = self._meta('assign-clear-001', owner_user_id=0)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200, payload)
        self.conv.invalidate_recordset()
        self.assertFalse(self.conv.owner_id)

    def test_assign_invalid_user(self):
        body = self._meta('assign-baduser-001', owner_user_id=999999999)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_assign_no_fields(self):
        body = self._meta('assign-empty-001')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_assign_conversation_not_found(self):
        body = self._meta('assign-404-001', owner_user_id=self.user_a.id)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            999999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_assign_replay(self):
        body = self._meta('assign-replay-001', owner_user_id=self.user_a.id)
        first, c1 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(c1, 200)
        second, c2 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(c2, 200)
        self.assertTrue(second['data'].get('idempotent_replay'))

    def test_assign_read_key_rejected(self):
        body = self._meta('assign-readk-001', owner_user_id=self.user_a.id)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_assign,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=body,
        )
        self.assertEqual(code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')
