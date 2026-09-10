from unittest import SkipTest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpOrderInvoiceActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP invoice action tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Invoice User',
            'login': 'mcp_invoice_user@example.com',
            'email': 'mcp_invoice_user@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Invoice Page',
            'page_fm_id_str': 'mcp-invoice-page-001',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'MCP Invoice Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'MCP Invoice Product',
            'type': 'service',
            'list_price': 1000.0,
        })

    def setUp(self):
        super().setUp()
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-invoice-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'MCP Invoice Customer',
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
        }
        payload.update(extra)
        return payload

    def _make_order(
        self,
        custom_state='deposit',
        has_deposit=True,
        deposit_amount=500.0,
    ):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': custom_state,
            'fulfillment_method': 'delivery',
            'delivery_address': '123 Delivery Street',
            'installation_address': '456 Install Street',
            'production_deadline': '2030-12-31',
            'has_deposit': has_deposit,
            'deposit_amount': deposit_amount,
        })
        self.env.cr.execute(
            "UPDATE sale_order SET conversation_id = %s WHERE id = %s",
            [self.conversation.id, order.id],
        )
        order.invalidate_recordset(['conversation_id'])
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.product.id,
            'name': self.product.display_name,
            'product_uom_qty': 1.0,
            'price_unit': 1000.0,
        })
        return order

    def _assert_log(self, request_id, action_type):
        log = self.env['dac_erp.mcp.order.log'].search([('request_id', '=', request_id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, action_type)
        return log

    def test_missing_key_read_key_missing_fields_and_not_found(self):
        order = self._make_order(custom_state='deposit')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers={},
            payload=self._base_payload('missing-key-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._base_payload('read-key-001'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'agent_name': 'OpenClaw'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'request_id': 'missing-agent-001'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            99999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('missing-order-001'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_deposit_invoice_success_replay_and_conflict(self):
        order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=500.0)
        with patch.object(type(order), 'action_deposit_invoice', autospec=True, return_value=True):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_create_deposit_invoice,
                order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload('deposit-success-001', reason='employee_requested_invoice_action'),
            )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['action'], 'create_deposit_invoice')
        self.assertEqual(payload['data']['old_stage'], 'deposit')
        self.assertEqual(payload['data']['new_stage'], 'deposit')
        self.assertIsNone(payload['data']['invoice'])
        log = self._assert_log('deposit-success-001', 'order_create_deposit_invoice')
        self.assertEqual(payload['data']['log_id'], log.id)

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-success-001', reason='employee_requested_invoice_action'),
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-success-001', reason='different'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'conflict')

    def test_deposit_invoice_stage_and_amount_guards(self):
        wrong_stage_order = self._make_order(custom_state='quotation', has_deposit=True, deposit_amount=500.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            wrong_stage_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-wrong-stage-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

        no_deposit_flag_order = self._make_order(custom_state='deposit', has_deposit=False, deposit_amount=500.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            no_deposit_flag_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-no-flag-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

        zero_amount_order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=0.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            zero_amount_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-zero-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_deposit_invoice_interactive_action_is_rejected_safely(self):
        order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=500.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('deposit-wizard-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'unsupported_interactive_action')

    def test_final_invoice_success_and_interactive_action_handling(self):
        success_order = self._make_order(custom_state='payment', has_deposit=True, deposit_amount=500.0)
        with patch.object(type(success_order), 'action_create_final_invoice', autospec=True, return_value=True):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_create_final_invoice,
                success_order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload('final-success-001', reason='employee_requested_invoice_action'),
            )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['action'], 'create_final_invoice')
        self.assertEqual(payload['data']['old_stage'], 'payment')
        self.assertEqual(payload['data']['new_stage'], 'payment')
        self.assertIsNone(payload['data']['invoice'])
        self._assert_log('final-success-001', 'order_create_final_invoice')

        wizard_order = self._make_order(custom_state='payment', has_deposit=True, deposit_amount=500.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_final_invoice,
            wizard_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('final-wizard-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'unsupported_interactive_action')

    def test_final_invoice_stage_and_terminal_guards(self):
        wrong_stage_order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=500.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create_final_invoice,
            wrong_stage_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('final-wrong-stage-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

        for stage, request_id in (('completed', 'final-completed-001'), ('cancel', 'final-cancel-001')):
            order = self._make_order(custom_state=stage, has_deposit=True, deposit_amount=500.0)
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_create_final_invoice,
                order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload(request_id),
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'business_rule_violation')
