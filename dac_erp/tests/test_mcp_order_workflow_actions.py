from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpOrderWorkflowActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP workflow tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Workflow User',
            'login': 'mcp_workflow_user@example.com',
            'email': 'mcp_workflow_user@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Workflow Page',
            'page_fm_id_str': 'mcp-workflow-page-001',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'MCP Workflow Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'MCP Workflow Product',
            'type': 'service',
            'list_price': 1000.0,
        })

    def setUp(self):
        super().setUp()
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-workflow-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'MCP Workflow Customer',
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

    def _make_order(self, custom_state='quotation', fulfillment_method='delivery', has_deposit=False, production_deadline='2030-12-31'):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': custom_state,
            'fulfillment_method': fulfillment_method,
            'delivery_address': '123 Delivery Street',
            'installation_address': '456 Install Street',
            'production_deadline': production_deadline,
            'has_deposit': has_deposit,
            'deposit_amount': 0.0,
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

    def test_missing_key_read_key_and_missing_request_fields(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            order.id,
            env=self.env,
            headers={},
            payload=self._base_payload('missing-key-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            order.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._base_payload('read-key-001'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'agent_name': 'OpenClaw'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'request_id': 'missing-agent-001'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_order_not_found(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            99999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('missing-order-001'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_confirm_info_success_and_wrong_stage_block(self):
        order = self._make_order(custom_state='quotation')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('confirm-001', reason='employee_requested_stage_transition'),
        )
        self.assertEqual(status_code, 200)
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'deposit')
        self.assertTrue(order.is_quotation_confirmed)
        log = self._assert_log('confirm-001', 'order_confirm_info')
        self.assertEqual(payload['data']['log_id'], log.id)
        self.assertEqual(payload['data']['old_stage'], 'quotation')
        self.assertEqual(payload['data']['new_stage'], 'deposit')

        wrong_stage_order = self._make_order(custom_state='deposit')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_info,
            wrong_stage_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('confirm-wrong-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_proceed_to_production_success_and_replay_conflict(self):
        order = self._make_order(custom_state='deposit', has_deposit=False)
        base_payload = self._base_payload('prod-001', reason='employee_requested_stage_transition')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_production,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=base_payload,
        )
        self.assertEqual(status_code, 200)
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'production')
        self.assertTrue(order.is_production_confirmed)
        self.assertEqual(payload['data']['action'], 'proceed_to_production')
        self._assert_log('prod-001', 'order_proceed_to_production')

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_production,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=base_payload,
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_production,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('prod-001', reason='different'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'conflict')

    def test_proceed_to_delivery_and_installation_fulfillment_guards(self):
        delivery_order = self._make_order(custom_state='production', fulfillment_method='delivery')
        delivery_order.write({'is_production_confirmed': True, 'production_done': True})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_delivery,
            delivery_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('delivery-001'),
        )
        self.assertEqual(status_code, 200)
        delivery_order.invalidate_recordset()
        self.assertEqual(delivery_order.order_state_custom, 'delivery')
        self.assertTrue(delivery_order.started_delivery)
        self._assert_log('delivery-001', 'order_proceed_to_delivery')

        wrong_delivery_order = self._make_order(custom_state='production', fulfillment_method='installation')
        wrong_delivery_order.write({'is_production_confirmed': True})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_delivery,
            wrong_delivery_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('delivery-wrong-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

        installation_order = self._make_order(custom_state='production', fulfillment_method='installation')
        installation_order.write({'is_production_confirmed': True, 'production_done': True})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_installation,
            installation_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('install-001'),
        )
        self.assertEqual(status_code, 200)
        installation_order.invalidate_recordset()
        self.assertEqual(installation_order.order_state_custom, 'installation')
        self.assertTrue(installation_order.started_installation)
        self._assert_log('install-001', 'order_proceed_to_installation')

        wrong_install_order = self._make_order(custom_state='production', fulfillment_method='delivery')
        wrong_install_order.write({'is_production_confirmed': True})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_proceed_to_installation,
            wrong_install_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('install-wrong-001'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_completed_and_cancel_are_blocked(self):
        for stage, request_id in (('completed', 'completed-001'), ('cancel', 'cancel-001')):
            order = self._make_order(custom_state=stage)
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_confirm_info,
                order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload(request_id),
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'business_rule_violation')
