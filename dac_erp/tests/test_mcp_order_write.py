from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpOrderWrite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP order write tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Order Owner',
            'login': 'mcp_order_owner@example.com',
            'email': 'mcp_order_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.alt_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Order Alt',
            'login': 'mcp_order_alt@example.com',
            'email': 'mcp_order_alt@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Order Page',
            'page_fm_id_str': 'mcp-order-page-001',
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'MCP Order Partner',
            'phone': '0900000001',
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'MCP VAT 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'MCP Cabinet',
            'list_price': 10000000.0,
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'MCP Table',
            'list_price': 5000000.0,
        })
        cls.protected_product = cls.env['product.product'].create({
            'name': 'Deposit Product',
            'default_code': 'DEPOSIT',
            'list_price': -1000000.0,
        })

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.order.money_change_confirmation_required', 'True')
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp.order.money_change_fields',
            'product_uom_qty,price_unit,discount,tax_id,deposit_amount,has_deposit,order_lines',
        )
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-order-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'MCP Order Customer',
            'owner_id': self.owner_user.id,
            'status_state': 'recontact',
            'require_processing': True,
        })
        self.order = self._make_order(order_state_custom='quotation')
        self.deposit_order = self._make_order(order_state_custom='deposit')
        self.production_order = self._make_order(order_state_custom='production')
        self.payment_order = self._make_order(order_state_custom='payment')
        self.completed_order = self._make_order(order_state_custom='completed')
        self.cancel_order = self._make_order(order_state_custom='cancel')

    def _make_order(self, order_state_custom='quotation'):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.owner_user.id,
            'order_state_custom': order_state_custom,
            'delivery_address': '123 Delivery Street',
            'installation_address': '456 Install Street',
            'production_deadline': '2026-05-02',
            'fulfillment_method': 'delivery',
            'has_deposit': True,
            'deposit_amount': 1000000.0,
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
            'price_unit': 10000000.0,
            'tax_id': [(6, 0, [self.tax.id])],
        })
        return order

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'employee_confirmation': True,
            'confirmation_text': 'Nhan vien da xac nhan thay doi du lieu anh huong tien.',
            'confirmed_by_user_id': self.owner_user.id,
        }
        payload.update(extra)
        return payload

    def _create_payload(self, request_id='create-001', **extra):
        payload = self._base_payload(
            request_id,
            partner_id=self.partner.id,
            conversation_id=self.conversation.id,
            user_id=self.owner_user.id,
            fulfillment_method='delivery',
            delivery_address='789 New Delivery Street',
            production_deadline='2026-05-03',
            has_deposit=True,
            deposit_amount=2000000,
            is_priority=False,
            is_priority_today=False,
            order_lines=[{
                'product_id': self.product.id,
                'description': 'Custom cabinet',
                'height': 10,
                'width': 20,
                'product_uom_qty': 1,
                'price_unit': 10000000,
                'tax_id': [self.tax.id],
            }],
        )
        payload.update(extra)
        return payload

    def _assert_order_log(self, request_id, action_type, status='success'):
        log = self.env['dac_erp.mcp.order.log'].search([('request_id', '=', request_id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, action_type)
        self.assertEqual(log.status, status)
        return log

    def test_missing_key_and_read_key_and_missing_request_fields(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers={},
            payload=self._create_payload(),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._create_payload(),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'agent_name': 'OpenClaw'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'request_id': 'missing-agent-001'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_write_key_create_success_with_conversation_and_audit_log(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._create_payload('create-success-001'),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        order = self.env['sale.order'].browse(payload['data']['order_id'])
        self.assertTrue(order.exists())
        self.assertEqual(order.partner_id.id, self.partner.id)
        self.assertEqual(order.order_line.product_id, self.product)
        self.env.cr.execute("SELECT conversation_id FROM sale_order WHERE id = %s", [order.id])
        self.assertEqual(self.env.cr.fetchone()[0], self.conversation.id)
        log = self._assert_order_log('create-success-001', 'order_create')
        self.assertEqual(payload['data']['log_id'], log.id)
        self.assertTrue(payload['data']['money_change_confirmation']['required'])
        self.assertTrue(payload['data']['money_change_confirmation']['confirmed'])

    def test_create_rejects_bad_partner_product_and_conversation(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._create_payload('bad-partner-001', partner_id=99999999),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._create_payload('bad-conversation-001', conversation_id=99999999),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

        bad_product_payload = self._create_payload('bad-product-001')
        bad_product_payload['order_lines'][0]['product_id'] = 99999999
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=bad_product_payload,
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_create_idempotency_replay_and_conflict(self):
        create_payload = self._create_payload('create-replay-001')
        first_payload, first_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=create_payload,
        )
        self.assertEqual(first_status, 200)

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=create_payload,
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(replay_payload['data']['log_id'], first_payload['data']['log_id'])

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._create_payload('create-replay-001', delivery_address='Different Address'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'conflict')

    def test_update_success_in_quotation_and_deposit(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'update-quotation-001',
                order_number='SO-Q-001',
                phone='0901234567',
                user_id=self.alt_user.id,
                fulfillment_method='delivery',
                delivery_address='Updated Delivery Address',
                production_deadline='2026-05-06',
            ),
        )
        self.assertEqual(status_code, 200)
        self.order.invalidate_recordset()
        self.partner.invalidate_recordset()
        self.assertEqual(self.order.order_number, 'SO-Q-001')
        self.assertEqual(self.order.user_id.id, self.alt_user.id)
        self.assertEqual(self.order.delivery_address, 'Updated Delivery Address')
        self.assertEqual(self.partner.phone, '0901234567')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.deposit_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'update-deposit-001',
                deposit_amount=3333333,
                has_deposit=True,
            ),
        )
        self.assertEqual(status_code, 200)
        self.deposit_order.invalidate_recordset()
        self.assertEqual(self.deposit_order.deposit_amount, 3333333)

    def test_money_change_confirmation_is_required_for_create_and_money_updates(self):
        create_payload = self._create_payload(
            'confirm-required-create-001',
            employee_confirmation=False,
            confirmation_text='',
            confirmed_by_user_id=False,
        )
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=create_payload,
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'confirmation_required')
        self.assertIn('order_lines', payload['error']['details']['money_impact_fields'])

        for request_id, update_fields in (
            ('confirm-price-001', {'order_lines': [{'id': self.order.order_line[:1].id, 'price_unit': 12000000}]}),
            ('confirm-qty-001', {'order_lines': [{'id': self.order.order_line[:1].id, 'product_uom_qty': 2}]}),
            ('confirm-discount-001', {'order_lines': [{'id': self.order.order_line[:1].id, 'discount': 5}]}),
            ('confirm-tax-001', {'order_lines': [{'id': self.order.order_line[:1].id, 'tax_id': [self.tax.id]}]}),
            ('confirm-deposit-001', {'deposit_amount': 4444444}),
        ):
            update_payload = self._base_payload(
                request_id,
                employee_confirmation=False,
                confirmation_text='',
                confirmed_by_user_id=False,
                **update_fields
            )
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_update,
                self.order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=update_payload,
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'confirmation_required')

    def test_non_money_update_does_not_require_confirmation_and_invalid_confirmed_by_user_id_fails(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={
                'request_id': 'non-money-no-confirm-001',
                'agent_name': 'OpenClaw',
                'model_name': 'gpt-5',
                'delivery_address': 'Only address changed',
            },
        )
        self.assertEqual(status_code, 200)
        self.order.invalidate_recordset()
        self.assertEqual(self.order.delivery_address, 'Only address changed')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_create,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._create_payload('invalid-confirm-user-001', confirmed_by_user_id=99999999),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_update_blocked_in_later_states_and_rejects_blocked_fields(self):
        for record in (self.production_order, self.payment_order, self.completed_order, self.cancel_order):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_update,
                record.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload('blocked-%s' % record.id, order_number='NOPE'),
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'validation_error')

        for blocked_field in ('partner_id', 'conversation_id', 'state', 'order_state_custom'):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_order_update,
                self.order.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._base_payload('blocked-field-%s' % blocked_field, **{blocked_field: 1}),
            )
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'validation_error')

    def test_patch_line_mode_updates_and_creates_lines(self):
        line = self.order.order_line.filtered(lambda rec: rec.product_id == self.product)[:1]
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'patch-lines-001',
                line_mode='patch',
                order_lines=[
                    {
                        'id': line.id,
                        'description': 'Updated cabinet',
                        'product_uom_qty': 2,
                        'price_unit': 11000000,
                    },
                    {
                        'product_id': self.product_b.id,
                        'description': 'New table',
                        'height': 5,
                        'width': 6,
                        'product_uom_qty': 1,
                        'price_unit': 5000000,
                        'tax_id': [self.tax.id],
                    },
                ],
            ),
        )
        self.assertEqual(status_code, 200)
        self.order.invalidate_recordset()
        updated_line = self.order.order_line.filtered(lambda rec: rec.id == line.id)
        self.assertEqual(updated_line.product_uom_qty, 2)
        self.assertEqual(updated_line.price_unit, 11000000)
        self.assertTrue(self.order.order_line.filtered(lambda rec: rec.product_id == self.product_b))

    def test_replace_line_mode_preserves_protected_system_lines(self):
        self.env['sale.order.line'].sudo().create({
            'order_id': self.order.id,
            'product_id': self.protected_product.id,
            'name': 'Deposit Keep',
            'product_uom_qty': 1.0,
            'price_unit': -1000000.0,
        })
        protected_ids_before = self.order.order_line.filtered(lambda rec: rec.price_unit < 0).ids
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'replace-lines-001',
                line_mode='replace',
                order_lines=[{
                    'product_id': self.product_b.id,
                    'description': 'Only new editable line',
                    'product_uom_qty': 3,
                    'price_unit': 4000000,
                    'tax_id': [self.tax.id],
                }],
            ),
        )
        self.assertEqual(status_code, 200)
        self.order.invalidate_recordset()
        protected_ids_after = self.order.order_line.filtered(lambda rec: rec.price_unit < 0).ids
        self.assertEqual(protected_ids_before, protected_ids_after)
        editable_products = self.order.order_line.filtered(lambda rec: rec.price_unit >= 0).mapped('product_id')
        self.assertEqual(editable_products, self.product_b)

    def test_order_not_found_and_existing_line_protection(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            99999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('missing-order-001', order_number='NOPE'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

        protected_line = self.env['sale.order.line'].sudo().create({
            'order_id': self.deposit_order.id,
            'product_id': self.protected_product.id,
            'name': 'Deposit Keep',
            'product_uom_qty': 1.0,
            'price_unit': -1000000.0,
        })
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_update,
            self.deposit_order.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'protected-line-001',
                line_mode='patch',
                order_lines=[{'id': protected_line.id, 'product_uom_qty': 2}],
            ),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')
