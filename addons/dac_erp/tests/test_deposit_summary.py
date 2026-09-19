from odoo.tests.common import TransactionCase


class TestDepositSummary(TransactionCase):
    def test_confirmed_deposit_edits_update_summary(self):
        order = self.env['sale.order'].new({
            'order_state_custom': 'deposit',
            'is_deposit_confirmed': True,
            'deposit_amount': 200,
            'amount_total': 1000,
        })
        self.assertEqual(order.deposit_paid_display, 200)
        self.assertEqual(order.remaining_amount_display, 800)
        for amount, remaining in [(350, 650), (100, 900), (0, 1000), (1200, 0)]:
            order.deposit_amount = amount
            self.assertEqual(order.deposit_paid_display, amount)
            self.assertEqual(order.remaining_amount_display, remaining)

    def test_unconfirmed_deposit_is_not_collected(self):
        order = self.env['sale.order'].new({
            'deposit_amount': 200,
            'amount_total': 1000,
            'total_deposit_paid': 0,
        })
        self.assertEqual(order.deposit_paid_display, 0)
        self.assertEqual(order.remaining_amount_display, 1000)
        order.total_deposit_paid = 150
        self.assertEqual(order.deposit_paid_display, 150)
        self.assertEqual(order.remaining_amount_display, 850)
