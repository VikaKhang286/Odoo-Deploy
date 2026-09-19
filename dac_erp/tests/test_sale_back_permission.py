from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestSaleBackPermission(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale = new_test_user(cls.env, login='test_sale_back',
                                 groups='base.group_user,dac_erp.group_dac_erp_sale')
        cls.worker = new_test_user(cls.env, login='test_worker_back',
                                   groups='base.group_user,dac_erp.group_dac_erp_design')
        cls.partner = cls.env['res.partner'].create({'name': 'Back permission test'})

    def _order(self, state='deposit'):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id, 'user_id': self.sale.id,
            'order_state_custom': state,
        })

    def test_sale_can_return_to_quotation(self):
        self.assertFalse(self.sale.has_group('dac_erp.group_dac_erp_manager'))
        self.assertFalse(self.sale.has_group('base.group_system'))
        order = self._order()
        order.with_user(self.sale).action_back_custom_step()
        self.assertEqual(order.order_state_custom, 'quotation')

    def test_sale_cannot_return_from_later_steps(self):
        for state in ('production', 'delivery', 'installation', 'payment'):
            order = self._order(state)
            with self.assertRaises(UserError):
                order.with_user(self.sale).action_back_custom_step()
            self.assertEqual(order.order_state_custom, state)

    def test_worker_cannot_return_to_quotation(self):
        order = self._order()
        order.user_id_design = self.worker
        with self.assertRaises(UserError):
            order.with_user(self.worker).action_back_custom_step()
        self.assertEqual(order.order_state_custom, 'deposit')

    def test_mixed_selection_does_not_partially_change(self):
        deposit = self._order()
        production = self._order('production')
        with self.assertRaises(UserError):
            (deposit + production).with_user(self.sale).action_back_custom_step()
        self.assertEqual(deposit.order_state_custom, 'deposit')
        self.assertEqual(production.order_state_custom, 'production')
