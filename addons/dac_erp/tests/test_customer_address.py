from odoo.tests.common import TransactionCase


class TestCustomerAddress(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Khách hàng kiểm thử địa chỉ',
            'street': '12 Nguyễn Huệ',
            'street2': 'Phường Bến Nghé',
            'city': 'Hồ Chí Minh',
        })

    def test_selecting_customer_loads_only_street(self):
        order = self.env['sale.order'].new({})
        order.partner_id = self.partner
        order._onchange_partner_id_address()
        order._onchange_partner_id_customer_address()

        self.assertEqual(order.customer_address, '12 Nguyễn Huệ')
        self.assertEqual(order.delivery_address, '12 Nguyễn Huệ')
        self.assertFalse(order.customer_address_manual_set)

    def test_free_text_address_is_preserved_verbatim(self):
        order = self.env['sale.order'].new({'partner_id': self.partner.id})
        address = '  Tầng 2, hẻm 12/3\nGọi trước khi đến  '

        order.customer_address = address
        order._onchange_customer_address_draft()
        order._compute_customer_address()

        self.assertEqual(order.customer_address, address)
        self.assertEqual(order.delivery_address, address)
        self.assertTrue(order.customer_address_manual_set)

    def test_cleared_address_is_not_restored(self):
        order = self.env['sale.order'].new({'partner_id': self.partner.id})
        self.assertTrue(order.customer_address)

        order.customer_address = False
        order._onchange_customer_address_draft()
        order._compute_customer_address()

        self.assertFalse(order.customer_address)
        self.assertFalse(order.delivery_address)
        self.assertTrue(order.customer_address_manual_set)

    def test_selecting_another_customer_reloads_its_address(self):
        other_partner = self.env['res.partner'].create({
            'name': 'Khách hàng khác',
            'street': '99 Pasteur',
            'city': 'Đà Nẵng',
        })
        order = self.env['sale.order'].new({'partner_id': self.partner.id})
        order.customer_address = False
        order._onchange_customer_address_draft()

        order.partner_id = other_partner
        order._onchange_partner_id_address()
        order._onchange_partner_id_customer_address()

        self.assertEqual(order.customer_address, '99 Pasteur')
        self.assertEqual(order.delivery_address, '99 Pasteur')
        self.assertFalse(order.customer_address_manual_set)

    def test_import_create_syncs_delivery_address_to_customer(self):
        address = '25 Đường số 7, Quận 7'

        order = self.env['sale.order'].with_context(import_file=True).create({
            'partner_id': self.partner.id,
            'delivery_address': address,
        })

        self.assertEqual(order.delivery_address, address)
        self.assertEqual(self.partner.street, address)
        self.assertEqual(order.customer_address, address)

    def test_import_update_syncs_delivery_address_to_customer(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        address = '88 Trần Hưng Đạo, Quận 1'

        order.with_context(import_file=True).write({
            'delivery_address': address,
        })

        self.assertEqual(order.delivery_address, address)
        self.assertEqual(self.partner.street, address)
        self.assertEqual(order.customer_address, address)

    def test_regular_delivery_update_does_not_change_customer(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })

        order.write({'delivery_address': 'Địa chỉ giao hàng tạm thời'})

        self.assertEqual(self.partner.street, '12 Nguyễn Huệ')
