from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('standard', 'at_install')
class TestProductionWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.SaleOrder = cls.env['sale.order']
        cls.Partner = cls.env['res.partner']
        cls.Product = cls.env['product.product']

        cls.partner = cls.Partner.create({'name': 'Test Partner No Deposit'})
        cls.product = cls.Product.create({
            'name': 'Test Production Service',
            'type': 'service',
            'list_price': 1000.0,
        })

    def setUp(self):
        super().setUp()
        self.order = self.SaleOrder.create({
            'partner_id': self.partner.id,
            'order_state_custom': 'deposit',
        })
        self.env['sale.order.line'].create({
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 1000.0,
        })

    def test_proceed_to_production_without_deadline_opens_wizard(self):
        self.order.production_deadline = False
        action = self.order.with_context(from_ui_button=True).action_proceed_to_production()

        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'production.deadline.wizard')

    def test_production_deadline_wizard_uses_default_days(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.production_default_deadline_days', '5')
        self.order.production_deadline = False

        wizard = self.env['production.deadline.wizard'].with_context(
            active_id=self.order.id,
            active_model='sale.order',
        ).create({})

        action = wizard.action_use_default_deadline()

        self.assertEqual(action.get('res_model'), 'no.deposit.confirm.wizard')
        self.assertEqual(
            self.order.production_deadline,
            fields.Date.context_today(self.order) + timedelta(days=5),
        )

    def test_no_deposit_wizard_confirm(self):
        self.order.production_deadline = '2030-12-31'
        wizard = self.env['no.deposit.confirm.wizard'].with_context(active_id=self.order.id).create({})
        wizard.action_confirm_no_deposit()

        self.assertFalse(self.order.has_deposit)
        self.assertEqual(self.order.order_state_custom, 'production')
        self.assertTrue(self.order.is_production_confirmed)
        self.assertTrue(self.order.reached_production)

    def test_delivery_confirm_without_address_opens_wizard(self):
        self.order.write({
            'order_state_custom': 'delivery',
            'delivery_address': False,
        })

        action = self.order.action_confirm_delivery_info()

        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'delivery.address.wizard')

    def test_delivery_address_wizard_confirms_delivery_with_address(self):
        self.order.write({
            'order_state_custom': 'delivery',
            'delivery_address': False,
        })
        wizard = self.env['delivery.address.wizard'].with_context(
            active_id=self.order.id,
            active_model='sale.order',
        ).create({
            'delivery_address': '123 Test Street',
        })

        action = wizard.action_confirm_delivery()
        self.order.invalidate_recordset()

        self.assertEqual(action.get('tag'), 'reload')
        self.assertEqual(self.order.delivery_address, '123 Test Street')
        self.assertTrue(self.order.is_delivery_confirmed)
        self.assertEqual(self.order.order_state_custom, 'payment')

    def test_delivery_address_wizard_allows_customer_pickup(self):
        self.order.write({
            'order_state_custom': 'delivery',
            'delivery_address': False,
        })
        wizard = self.env['delivery.address.wizard'].with_context(
            active_id=self.order.id,
            active_model='sale.order',
        ).create({})

        action = wizard.action_mark_customer_pickup()
        self.order.invalidate_recordset()

        self.assertEqual(action.get('tag'), 'reload')
        self.assertEqual(self.order.delivery_address, 'Khách đến nhận hàng')
        self.assertTrue(self.order.is_delivery_confirmed)
        self.assertEqual(self.order.order_state_custom, 'payment')
