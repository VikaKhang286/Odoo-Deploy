from datetime import date
from unittest import SkipTest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpOrderPaymentActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP payment action tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Payment User',
            'login': 'mcp_payment_user@example.com',
            'email': 'mcp_payment_user@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Payment Page',
            'page_fm_id_str': 'mcp-payment-page-001',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'MCP Payment Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'MCP Payment Product',
            'type': 'service',
            'list_price': 5000.0,
        })
        cls.journal = cls.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)
        if not cls.journal:
            raise SkipTest("A bank/cash journal is required for MCP payment action tests.")

    def setUp(self):
        super().setUp()
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-payment-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'MCP Payment Customer',
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _payload(self, request_id, **extra):
        payload = {
            'journal_id': self.journal.id,
            'payment_date': str(date.today()),
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'reason': 'employee_confirmed_payment',
        }
        payload.update(extra)
        return payload

    def _make_order(self, custom_state='deposit', has_deposit=True, deposit_amount=2000.0, price_unit=10000.0):
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
            'price_unit': price_unit,
        })
        return order

    def _deposit_invoices(self, order):
        return self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', order.name),
            ('dac_deposit_invoice', '=', True),
        ], order='id asc')

    def _final_invoices(self, order):
        return self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', order.name),
            ('dac_deposit_invoice', '=', False),
        ], order='id asc')

    def _payments_for_invoice(self, invoice):
        payments = self.env['account.payment']
        if hasattr(invoice, '_get_reconciled_payments'):
            payments = invoice._get_reconciled_payments()
        if not payments and 'reconciled_invoice_ids' in self.env['account.payment']._fields:
            payments = self.env['account.payment'].search([('reconciled_invoice_ids', 'in', invoice.ids)], order='id asc')
        return payments

    def _assert_log(self, request_id, action_type):
        log = self.env['dac_erp.mcp.order.log'].search([('request_id', '=', request_id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, action_type)
        return log

    def test_confirm_deposit_invoice_auth_and_validation(self):
        order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=2000.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers={},
            payload=self._payload('deposit-missing-key-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._payload('deposit-read-key-001'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        for invalid_payload in (
            {'payment_date': str(date.today()), 'request_id': 'deposit-missing-journal-001', 'agent_name': 'OpenClaw', 'reason': 'r'},
            {'journal_id': self.journal.id, 'request_id': 'deposit-missing-date-001', 'agent_name': 'OpenClaw', 'reason': 'r'},
            {'journal_id': self.journal.id, 'payment_date': str(date.today()), 'agent_name': 'OpenClaw', 'reason': 'r'},
        ):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_confirm_deposit_invoice,
                order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=invalid_payload,
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'validation_error')

    def test_confirm_deposit_invoice_success_replay_and_already_confirmed(self):
        order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=2000.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-success-001', reason='employee_confirmed_deposit_payment'),
        )
        self.assertEqual(status_code, 200)
        data = payload['data']
        self.assertEqual(data['action_type'], 'confirm_deposit_invoice')
        self.assertEqual(data['request_id'], 'deposit-success-001')
        self.assertTrue(data['invoice'])
        self.assertTrue(data['payment'])
        self.assertTrue(data['order']['is_deposit_confirmed'])
        self.assertEqual(data['invoice']['state'], 'posted')
        self.assertEqual(data['invoice']['payment_state'], 'paid')
        self.assertEqual(data['payment']['journal_id'], self.journal.id)
        log = self._assert_log('deposit-success-001', 'order_confirm_deposit_invoice')
        self.assertEqual(data['log_id'], log.id)

        invoices = self._deposit_invoices(order)
        self.assertEqual(len(invoices), 1)
        payments = self._payments_for_invoice(invoices[0])
        self.assertEqual(len(payments), 1)

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-success-001', reason='employee_confirmed_deposit_payment'),
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(len(self._deposit_invoices(order)), 1)
        self.assertEqual(len(self._payments_for_invoice(invoices[0])), 1)

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-success-001', reason='different-reason'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'idempotency_conflict')

        second_payload, second_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-success-002', reason='employee_rechecked_deposit_payment'),
        )
        self.assertEqual(second_status, 200)
        self.assertTrue(second_payload['data']['details']['already_confirmed'])
        self.assertEqual(len(self._deposit_invoices(order)), 1)
        self.assertEqual(len(self._payments_for_invoice(invoices[0])), 1)

    def test_confirm_deposit_invoice_business_rules(self):
        wrong_stage_order = self._make_order(custom_state='quotation', has_deposit=True, deposit_amount=2000.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            wrong_stage_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-wrong-stage-001'),
        )
        self.assertEqual(status_code, 422)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

        zero_amount_order = self._make_order(custom_state='deposit', has_deposit=True, deposit_amount=0.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_deposit_invoice,
            zero_amount_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('deposit-zero-001'),
        )
        self.assertEqual(status_code, 422)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')

    def test_confirm_final_payment_validation_and_success(self):
        order = self._make_order(custom_state='payment', has_deposit=False, deposit_amount=0.0, price_unit=5000.0)
        for invalid_payload in (
            {'payment_date': str(date.today()), 'request_id': 'final-missing-journal-001', 'agent_name': 'OpenClaw', 'reason': 'r'},
            {'journal_id': self.journal.id, 'request_id': 'final-missing-date-001', 'agent_name': 'OpenClaw', 'reason': 'r'},
            {'journal_id': self.journal.id, 'payment_date': str(date.today()), 'agent_name': 'OpenClaw', 'reason': 'r'},
        ):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_confirm_final_payment,
                order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=invalid_payload,
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_final_payment,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('final-success-001', reason='employee_confirmed_final_payment'),
        )
        self.assertEqual(status_code, 200)
        data = payload['data']
        self.assertEqual(data['action_type'], 'confirm_final_payment')
        self.assertTrue(data['invoice'])
        self.assertTrue(data['payment'])
        self.assertTrue(data['order']['is_payment_confirmed'])
        self.assertTrue(data['order']['is_order_completed'])
        self.assertEqual(data['invoice']['payment_state'], 'paid')
        self._assert_log('final-success-001', 'order_confirm_final_payment')

        final_invoices = self._final_invoices(order)
        self.assertEqual(len(final_invoices), 1)
        payments = self._payments_for_invoice(final_invoices[0])
        self.assertEqual(len(payments), 1)

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_final_payment,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('final-success-001', reason='employee_confirmed_final_payment'),
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(len(self._final_invoices(order)), 1)

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_final_payment,
            order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('final-success-001', reason='different-reason'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'idempotency_conflict')

    def test_confirm_final_payment_zero_remaining_and_wrong_stage(self):
        order = self._make_order(custom_state='payment', has_deposit=True, deposit_amount=5000.0, price_unit=5000.0)

        original_snapshot_builder = self.controller._get_mcp_payment_action_order_snapshot

        def fake_snapshot_builder(current_order):
            snapshot = original_snapshot_builder(current_order)
            if current_order.id == order.id and not current_order.is_order_completed:
                snapshot = dict(snapshot)
                snapshot['amount_residual'] = 0.0
            return snapshot

        def fake_action_create_final_invoice():
            order.write({
                'is_payment_confirmed': True,
                'is_order_completed': True,
                'order_state_custom': 'completed',
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Hoàn thành!',
                    'message': 'Đơn hàng đã hoàn thành.',
                    'type': 'success',
                }
            }

        with patch.object(self.controller, '_get_mcp_payment_action_order_snapshot', side_effect=fake_snapshot_builder):
            with patch.object(type(order), 'action_create_final_invoice', autospec=True, side_effect=lambda self_order: fake_action_create_final_invoice()):
                payload, status_code = self.controller._run_mcp_handler(
                    self.controller._dispatch_mcp_order_confirm_final_payment,
                    order.id,
                    env=self.env,
                    headers=self._headers('mcp-write-test-key'),
                    payload=self._payload('final-zero-remaining-001', reason='employee_confirmed_final_payment'),
                )
        self.assertEqual(status_code, 200)
        self.assertIsNone(payload['data']['invoice'])
        self.assertIsNone(payload['data']['payment'])
        self.assertTrue(payload['data']['order']['is_order_completed'])
        self.assertEqual(payload['data']['details']['remaining_amount_before'], 0.0)

        wrong_stage_order = self._make_order(custom_state='deposit', has_deposit=False, deposit_amount=0.0, price_unit=5000.0)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_confirm_final_payment,
            wrong_stage_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('final-wrong-stage-001'),
        )
        self.assertEqual(status_code, 422)
        self.assertEqual(payload['error']['code'], 'business_rule_violation')
