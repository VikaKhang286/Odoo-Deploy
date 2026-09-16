from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestOrderStateSelectQuickChange(TransactionCase):
    """Đổi trạng thái qua dropdown order_state_select trong list view.

    order_state_select là field compute+inverse riêng cho list: khi user đổi
    dropdown, inverse route qua đúng action workflow (giống nút form). Test này
    bảo vệ đường write mới đi qua danger-zone sale.order.write()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env['res.partner'].create({'name': 'Quick State Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Quick State Product',
            'type': 'service',
            'list_price': 1000.0,
        })

    def _make_order(self, custom_state='quotation', with_line=True, **extra):
        vals = {
            'partner_id': self.partner.id,
            'order_state_custom': custom_state,
            'fulfillment_method': 'delivery',
            'has_deposit': False,
            'deposit_amount': 0.0,
        }
        vals.update(extra)
        order = self.env['sale.order'].create(vals)
        if with_line:
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': self.product.id,
                'name': self.product.display_name,
                'product_uom_qty': 1.0,
                'price_unit': 1000.0,
            })
        return order

    def test_compute_mirrors_state(self):
        order = self._make_order(custom_state='quotation')
        self.assertEqual(order.order_state_select, 'quotation')
        order.order_state_custom = 'deposit'
        order.invalidate_recordset()
        self.assertEqual(order.order_state_select, 'deposit')

    def test_quotation_to_deposit_via_select(self):
        """quotation -> deposit qua dropdown chạy action_confirm_info (full action)."""
        order = self._make_order(custom_state='quotation')
        order.write({'order_state_select': 'deposit'})
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'deposit')
        self.assertTrue(order.is_quotation_confirmed)

    def test_quotation_to_deposit_without_line_raises(self):
        """Không có dòng SP -> action_confirm_info chặn (validation y như form)."""
        order = self._make_order(custom_state='quotation', with_line=False)
        with self.assertRaises(UserError):
            order.write({'order_state_select': 'deposit'})

    def test_illegal_jump_raises(self):
        """Nhảy cóc quotation -> payment bị chặn, không đổi state."""
        order = self._make_order(custom_state='quotation')
        with self.assertRaises(UserError):
            order.write({'order_state_select': 'payment'})

    def test_cancel_via_select(self):
        """quotation -> cancel chạy action_cancel_order."""
        order = self._make_order(custom_state='quotation')
        order.write({'order_state_select': 'cancel'})
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'cancel')

    def test_cancelled_order_blocked(self):
        """Đơn đã hủy không cho đổi state qua dropdown."""
        order = self._make_order(custom_state='quotation')
        order.write({'order_state_custom': 'cancel'})
        with self.assertRaises(UserError):
            order.write({'order_state_select': 'deposit'})

    def test_fulfillment_method_guard_blocks_wrong_branch(self):
        """Đơn delivery không được đẩy sang installation (khớp ẩn nút form)."""
        order = self._make_order(
            custom_state='production',
            fulfillment_method='delivery',
            is_production_confirmed=True,
        )
        with self.assertRaises(UserError):
            order.write({'order_state_select': 'installation'})
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'production')

    def test_production_to_delivery_requires_confirmation(self):
        """production -> delivery cần is_production_confirmed."""
        order = self._make_order(
            custom_state='production',
            fulfillment_method='delivery',
            is_production_confirmed=False,
        )
        with self.assertRaises(UserError):
            order.write({'order_state_select': 'delivery'})

    def test_same_state_noop(self):
        """Chọn lại đúng state hiện tại -> không lỗi, không đổi gì."""
        order = self._make_order(custom_state='quotation')
        order.write({'order_state_select': 'quotation'})
        order.invalidate_recordset()
        self.assertEqual(order.order_state_custom, 'quotation')
        self.assertFalse(order.is_quotation_confirmed)
