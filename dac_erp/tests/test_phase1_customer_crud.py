from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp_phase1_extension import MCPPhase1ExtensionController


@tagged('post_install', '-at_install')
class TestPhase1CustomerCRUD(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPPhase1ExtensionController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _meta(self, request_id, **extra):
        body = {'request_id': request_id, 'agent_name': 'OpenClaw', 'model_name': 'gpt-5'}
        body.update(extra)
        return body

    def test_create_customer_success(self):
        body = self._meta('cust-create-001', name='Nguyễn Văn A', phone='0909123456',
                          email='a@example.com', city='HCM')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200, payload)
        self.assertTrue(payload['data']['partner_id'])
        partner = self.env['res.partner'].sudo().browse(payload['data']['partner_id'])
        self.assertEqual(partner.name, 'Nguyễn Văn A')
        self.assertEqual(partner.phone, '0909123456')
        log = self.env['dac_erp.mcp.customer.log'].search([('request_id', '=', 'cust-create-001')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, 'customer_create')

    def test_create_duplicate_phone_blocked(self):
        # Tạo partner trước
        self.env['res.partner'].sudo().create({
            'name': 'Existing', 'phone': '0911222333',
        })
        body = self._meta('cust-dup-001', name='Khách Mới', phone='0911222333')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 409)
        self.assertEqual(payload['error']['code'], 'duplicate_customer')
        self.assertIn('existing_partner_id', payload['error']['details'])

    def test_create_normalize_phone_dedup(self):
        self.env['res.partner'].sudo().create({
            'name': 'Has Phone', 'phone': '+84 909 333 444',
        })
        # Cùng SĐT, format khác
        body = self._meta('cust-norm-001', name='New', phone='0909333444')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 409)
        self.assertEqual(payload['error']['code'], 'duplicate_customer')

    def test_create_missing_required_fields(self):
        # thiếu phone và email
        body = self._meta('cust-missing-001', name='No Contact')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_create_replay_returns_same(self):
        body = self._meta('cust-replay-001', name='Replay Test', phone='0922111111')
        first, c1 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(c1, 200)
        partner_id_1 = first['data']['partner_id']
        second, c2 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(c2, 200)
        self.assertTrue(second['data']['idempotent_replay'])
        self.assertEqual(second['data']['partner_id'], partner_id_1)

    def test_update_customer_success(self):
        partner = self.env['res.partner'].sudo().create({
            'name': 'Update Me', 'phone': '0933000111', 'city': 'OldCity',
        })
        body = self._meta('cust-update-001', name='Updated Name', city='NewCity')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_update,
            partner.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 200, payload)
        partner.invalidate_recordset()
        self.assertEqual(partner.name, 'Updated Name')
        self.assertEqual(partner.city, 'NewCity')
        self.assertEqual(payload['data']['action'], 'customer_update')

    def test_update_blocked_field(self):
        partner = self.env['res.partner'].sudo().create({
            'name': 'Test Block', 'phone': '0944111222',
        })
        body = self._meta('cust-block-001', is_company=True)
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_update,
            partner.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_update_partner_not_found(self):
        body = self._meta('cust-404-001', name='Whatever')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_update,
            999999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_update_no_fields_provided(self):
        partner = self.env['res.partner'].sudo().create({
            'name': 'Empty Update', 'phone': '0955111222',
        })
        body = self._meta('cust-empty-001')  # chỉ có metadata, không có vals
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_update,
            partner.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_update_phone_conflict(self):
        # 2 partner, update partner_a sang phone của partner_b → 409
        partner_a = self.env['res.partner'].sudo().create({'name': 'A', 'phone': '0966000001'})
        partner_b = self.env['res.partner'].sudo().create({'name': 'B', 'phone': '0966000002'})
        body = self._meta('cust-conflict-001', phone='0966000002')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_update,
            partner_a.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 409)
        self.assertEqual(payload['error']['code'], 'duplicate_customer')
        self.assertEqual(payload['error']['details']['existing_partner_id'], partner_b.id)

    def test_create_missing_request_id(self):
        body = {'agent_name': 'OpenClaw', 'name': 'Foo', 'phone': '0977111111'}
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_create_read_key_rejected(self):
        body = self._meta('cust-readk-001', name='X', phone='0988111111')
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_create,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=body,
        )
        self.assertEqual(code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')
