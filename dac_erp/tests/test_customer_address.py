from odoo.tests.common import TransactionCase


class TestCustomerAddress(TransactionCase):

    def test_order_displays_partner_full_inline_address(self):
        country = self.env['res.country'].create({'name': 'Quốc gia kiểm thử'})
        state = self.env['res.country.state'].create({
            'name': 'Tên trạng thái kiểm thử',
            'code': 'TTKT',
            'country_id': country.id,
        })
        partner = self.env['res.partner'].create({
            'name': 'Khách hàng kiểm thử địa chỉ',
            'street': '12 Nguyễn Huệ',
            'street2': 'Phường Bến Nghé',
            'city': 'Hồ Chí Minh',
            'state_id': state.id,
            'country_id': country.id,
        })
        order = self.env['sale.order'].new({'partner_id': partner.id})

        self.assertEqual(
            order.customer_address,
            '12 Nguyễn Huệ, Phường Bến Nghé, Hồ Chí Minh, '
            'Tên trạng thái kiểm thử, Quốc gia kiểm thử',
        )
        self.assertNotIn('TTKT', order.customer_address)

    def test_entered_address_updates_partner_address_columns(self):
        country = self.env['res.country'].create({'name': 'Quốc gia nhập địa chỉ'})
        state = self.env['res.country.state'].create({
            'name': 'Trạng thái nhập địa chỉ',
            'code': 'TNDC',
            'country_id': country.id,
        })
        partner = self.env['res.partner'].create({
            'name': 'Khách hàng nhập địa chỉ',
        })
        order = self.env['sale.order'].new({'partner_id': partner.id})

        order.customer_address = (
            '45 Lê Lợi, Thành phố kiểm thử, Trạng thái nhập địa chỉ, '
            'Quốc gia nhập địa chỉ'
        )
        order._inverse_customer_address()

        self.assertEqual(partner.street, '45 Lê Lợi')
        self.assertEqual(partner.city, 'Thành phố kiểm thử')
        self.assertEqual(partner.state_id, state)
        self.assertEqual(partner.country_id, country)

    def test_entered_address_accepts_state_name_with_common_dot_abbreviation(self):
        country = self.env['res.country'].create({'name': 'Việt Nam kiểm thử'})
        state = self.env['res.country.state'].create({
            'name': 'TP Hồ Chí Minh',
            'code': 'VN-SG-TEST',
            'country_id': country.id,
        })
        partner = self.env['res.partner'].create({
            'name': 'Khách hàng địa chỉ TP HCM',
        })
        order = self.env['sale.order'].new({'partner_id': partner.id})

        order.customer_address = (
            '591 Trần Hưng Đạo, Phường Cầu Ông Lãnh, TP. Hồ Chí Minh, '
            'Việt Nam kiểm thử'
        )
        order._inverse_customer_address()

        self.assertEqual(partner.city, 'Phường Cầu Ông Lãnh')
        self.assertEqual(partner.state_id, state)

    def test_address_entered_before_customer_selection_is_preserved_and_saved(self):
        country = self.env['res.country'].create({'name': 'Quốc gia nhập trước'})
        state = self.env['res.country.state'].create({
            'name': 'Trạng thái nhập trước',
            'code': 'TNTR',
            'country_id': country.id,
        })
        partner = self.env['res.partner'].create({
            'name': 'Khách hàng chọn sau',
        })
        address = '10 Lý Tự Trọng, Thành phố kiểm thử, Trạng thái nhập trước, Quốc gia nhập trước'
        order = self.env['sale.order'].new({})

        order.customer_address = address
        order._onchange_customer_address_draft()
        order.partner_id = partner
        order._compute_customer_address()
        order._inverse_customer_address()

        self.assertEqual(order.customer_address, address)
        self.assertEqual(partner.street, '10 Lý Tự Trọng')
        self.assertEqual(partner.city, 'Thành phố kiểm thử')
        self.assertEqual(partner.state_id, state)
