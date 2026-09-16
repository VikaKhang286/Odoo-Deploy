from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp_phase1_extension import MCPPhase1ExtensionController


@tagged('post_install', '-at_install')
class TestPhase1OrderCancel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPPhase1ExtensionController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = (
            'page.fm.page' in cls.env.registry.models
            and 'page.fm.conversation' in cls.env.registry.models
        )
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC not loaded")

        cls.partner = cls.env['res.partner'].create({'name': 'Phase1 Cancel Partner'})
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Phase1 Cancel User',
            'login': 'phase1_cancel@example.com',
            'email': 'phase1_cancel@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Phase1 Cancel Product',
            'type': 'service',
            'list_price': 1000.0,
        })

    def _make_order(self, custom_state='quotation'):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': custom_state,
            'fulfillment_method': 'delivery',
            'delivery_address': '123 Test',
            'production_deadline': '2030-12-31',
            'has_deposit': False,
            'deposit_amount': 0.0,
        })
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.product.id,
            'name': self.product.display_name,
            'product_uom_qty': 1.0,
            'price_unit': 1000.0,
        })
        return order

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _base_payload(self, request_id, **extra):
        payload = {'request_id': request_id, 'agent_name': 'OpenClaw', 'model_name': 'gpt-5'}
        payload.update(extra)
        return payload

    def test_cancel_quotation_success(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('cancel-001', reason='customer changed mind'),
        )
        self.assertEqual(status_code, 200, payload)
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'cancel')
        self.assertEqual(payload['data']['action'], 'cancel')
        self.assertEqual(payload['data']['old_stage'], 'quotation')
        self.assertEqual(payload['data']['new_stage'], 'cancel')
        log = self.env['dac_erp.mcp.order.log'].search([('request_id', '=', 'cancel-001')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, 'order_cancel')

    def test_cancel_wrong_stage_blocked(self):
        order = self._make_order(custom_state='deposit')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('cancel-wrong-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_cancel_replay_returns_same_response(self):
        order = self._make_order(custom_state='quotation')
        req_id = 'cancel-replay-001'
        first, code1 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(req_id),
        )
        self.assertEqual(code1, 200)
        second, code2 = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(req_id),
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second['data'].get('idempotent_replay'))
        self.assertEqual(first['data']['order_id'], second['data']['order_id'])

    def test_cancel_missing_api_key(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers={},
            payload=self._base_payload('cancel-noauth-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

    def test_cancel_read_key_rejected(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            order.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._base_payload('cancel-read-001'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

    def test_reopen_from_cancel(self):
        order = self._make_order(custom_state='quotation')
        order.sudo().write({'order_state_custom': 'cancel'})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_reopen,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('reopen-001', reason='restored'),
        )
        self.assertEqual(status_code, 200, payload)
        self.assertEqual(payload['data']['new_stage'], 'quotation', payload)
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'quotation')
        self.assertFalse(order.is_quotation_confirmed)

    def test_reopen_non_cancel_blocked(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_reopen,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('reopen-wrong-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_cancel_order_not_found(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_cancel,
            999999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('cancel-404-001'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')
