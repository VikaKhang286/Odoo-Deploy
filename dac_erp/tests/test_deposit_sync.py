from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDepositSynchronization(AccountTestInvoicingCommon):
    def setUp(self):
        super().setUp()
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_state_custom': 'deposit',
            'deposit_amount': 200,
            'order_line': [Command.create({
                'name': 'Test item', 'product_id': self.product_a.id,
                'product_uom_qty': 1, 'price_unit': 1000,
                'tax_id': [Command.clear()],
            })],
        })
        self.invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner_a.id,
            'invoice_origin': self.order.name, 'dac_deposit_invoice': True,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'name': 'Đặt cọc', 'quantity': 1, 'price_unit': 200,
                'account_id': self.company_data['default_account_revenue'].id,
                'tax_ids': [Command.clear()],
            })],
        })
        self.invoice.action_post()
        journal = self.company_data['default_journal_bank']
        self.inbound_payment_method_line.payment_account_id = journal.default_account_id
        self.payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=self.invoice.ids,
        ).create({'journal_id': journal.id, 'amount': 200})._create_payments()
        self.order.is_deposit_confirmed = True
        self.order.add_deposit_order_line(200, invoice=self.invoice)

    def test_edit_paid_deposit_in_both_directions(self):
        invoice_id, payment_id = self.invoice.id, self.payment.id
        line = self.order._editable_deposit_lines()
        for amount in (350, 100):
            self.order.write({'deposit_amount': amount})
            self.env.flush_all()
            self.env.invalidate_all()
            self.assertEqual(self.invoice.id, invoice_id)
            self.assertEqual(self.payment.id, payment_id)
            self.assertEqual(self.invoice.amount_total, amount)
            self.assertEqual(self.payment.amount, amount)
            self.assertEqual(self.invoice.amount_residual, 0)
            self.assertEqual(self.invoice.payment_state, 'paid')
            self.assertEqual(self.invoice.state, 'posted')
            self.assertEqual(line.price_subtotal, -amount)
            self.assertEqual(self.order.total_deposit_paid, amount)
            self.assertEqual(self.order.deposit_paid_display, amount)
            self.assertEqual(self.order.remaining_amount_display, 1000 - amount)
            self.assertEqual(self.order._editable_deposit_lines(), line)

    def test_onchange_updates_deposit_line(self):
        virtual_order = self.env['sale.order'].new({}, origin=self.order)
        virtual_order.deposit_amount = 350
        virtual_order._onchange_confirmed_deposit_amount()
        self.assertEqual(virtual_order._editable_deposit_lines().price_unit, -350)
        self.assertEqual(self.invoice.amount_total, 200)

    def test_invalid_amount_rolls_back(self):
        for amount in (-1, 0, 1001):
            with self.assertRaises(UserError):
                self.order.write({'deposit_amount': amount})
            self.assertEqual(self.order.deposit_amount, 200)
            self.assertEqual(self.invoice.amount_total, 200)
            self.assertEqual(self.payment.amount, 200)

    def test_multiple_deposit_invoices_roll_back(self):
        self.invoice.copy({'invoice_origin': self.order.name})
        with self.assertRaises(UserError):
            self.order.write({'deposit_amount': 350})
        self.assertEqual(self.order.deposit_amount, 200)
        self.assertEqual(self.invoice.amount_total, 200)

    def test_same_amount_repairs_previous_display_only_edit(self):
        # Simulate data saved before accounting synchronization was implemented.
        self.env.cr.execute('UPDATE sale_order SET deposit_amount = 350 WHERE id = %s', [self.order.id])
        self.order.invalidate_recordset(['deposit_amount'])
        self.order.write({'deposit_amount': 350})
        self.assertEqual(self.invoice.amount_total, 350)
        self.assertEqual(self.payment.amount, 350)
        self.assertEqual(self.order._editable_deposit_lines().price_unit, -350)

    def test_accounting_error_rolls_back_all_amounts(self):
        from unittest.mock import patch
        with patch.object(type(self.invoice), 'action_post', side_effect=UserError('Locked invoice')):
            with self.assertRaises(UserError):
                self.order.write({'deposit_amount': 350})
        self.assertEqual(self.order.deposit_amount, 200)
        self.assertEqual(self.invoice.amount_total, 200)
        self.assertEqual(self.payment.amount, 200)
        self.assertEqual(self.invoice.state, 'posted')
        self.assertEqual(self.invoice.amount_residual, 0)
        self.assertEqual(self.order._editable_deposit_lines().price_unit, -200)

    def test_final_invoice_blocks_deposit_rewrite(self):
        self.invoice.copy({'invoice_origin': self.order.name, 'dac_deposit_invoice': False})
        with self.assertRaises(UserError):
            self.order.write({'deposit_amount': 350})
        self.assertEqual(self.order.deposit_amount, 200)
        self.assertEqual(self.invoice.amount_total, 200)
