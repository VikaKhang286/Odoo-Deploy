from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError
from datetime import date

@tagged('standard', 'at_install')
class TestPaymentWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        
        cls.partner = cls.env['res.partner'].create({'name': 'Test Partner Final Payment'})
        cls.product = cls.env['product.product'].create({
            'name': 'Test Payment Item',
            'type': 'service',
            'list_price': 5000.0,
        })
        cls.journal = cls.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)

    def setUp(self):
        super().setUp()
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_state_custom': 'payment',
        })
        self.env['sale.order.line'].create({
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 5000.0,
        })

    def test_final_payment_wizard_confirm(self):
        """Test finalizing payment with 1-click wizard"""
        # Set up the wizard the way a user would via UI
        wizard = self.env['final.payment.confirm.wizard'].with_context(
            active_id=self.order.id, 
            active_model='sale.order'
        ).create({
            'journal_id': self.journal.id,
            'payment_date': date.today()
        })
        wizard.action_confirm()

        # The system creates invoice, posts it, and registers payment automatically
        invoices = self.env['account.move'].search([('invoice_origin', '=', self.order.name)])
        self.assertTrue(len(invoices) >= 1, "Expected an invoice to be created")
        
        # Invoices should be paid
        for inv in invoices:
            self.assertEqual(inv.state, 'posted', "Invoice should be posted")
            self.assertEqual(inv.payment_state, 'paid', "Invoice should be marked as paid")
        
        # Test completion logic hook
        self.assertEqual(self.order.order_state_custom, 'completed', "Order state custom should change to completed after full payment")
