from odoo.tests.common import TransactionCase


class TestCartPricing(TransactionCase):

    def test_cart_product_tax_is_cleared_before_and_after_save(self):
        tax = self.env['account.tax'].create({
            'name': 'Cart regression VAT 10%', 'amount': 10,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        product = self.env['product.product'].create({
            'name': 'Cart tax regression product', 'type': 'cart',
            'taxes_id': [(6, 0, tax.ids)],
        })
        partner = self.env['res.partner'].create({'name': 'Cart tax customer'})
        values = {
            'partner_id': partner.id, 'order_type': 'cart',
            'order_line': [(0, 0, {
                'product_id': product.id, 'product_uom_qty': 1,
                'price_unit': 100000,
            })],
        }
        draft = self.env['sale.order'].new(values)
        self.assertFalse(draft.order_line.tax_id)
        order = self.env['sale.order'].create(values)
        line = order.order_line.filtered(lambda item: item.product_id == product)
        self.assertFalse(line.tax_id)
        self.assertEqual(line.price_tax, 0)
        self.assertEqual(line.price_total, line.price_subtotal)
        order.order_type = 'general'
        self.assertEqual(line.tax_id, tax)
        self.assertEqual(line.price_tax, line.price_subtotal * 0.1)
        order.order_type = 'cart'
        self.assertFalse(line.tax_id)
        self.assertEqual(line.price_tax, 0)
        self.assertEqual(product.taxes_id, tax)

    def test_cart_quick_create_product_type_and_accessory_name(self):
        products = self.env['product.product'].with_context(dac_cart_product_create=True)
        for entered, name, kind in [
            ('Xe mới kiểm thử', 'Xe mới kiểm thử', 'cart'),
            ('+ Kệ kiểm thử', 'Kệ kiểm thử', 'cart_accessory'),
            ('  +Dù kiểm thử  ', 'Dù kiểm thử', 'cart_accessory'),
        ]:
            product_id, _label = products.name_create(entered)
            product = products.browse(product_id)
            self.assertEqual(product.name, name)
            self.assertEqual(product.type, kind)
            self.assertEqual(product.categ_id, product.product_tmpl_id._cart_category_for_type(kind))
        ordinary = self.env['product.product'].create({'name': '+ Ordinary', 'type': 'service'})
        self.assertEqual(ordinary.name, '+ Ordinary')
        self.assertEqual(ordinary.type, 'service')

    def test_cart_create_dialog_normalizes_template_and_variant(self):
        for model in ['product.product', 'product.template']:
            product = self.env[model].with_context(dac_cart_product_create=True).create({
                'name': '+ Kệ tạo chi tiết', 'type': 'consu',
            })
            self.assertEqual(product.name, 'Kệ tạo chi tiết')
            self.assertEqual(product.type, 'cart_accessory')

    def _default_cart_product(self):
        product = self.env['sale.order']._get_default_cart_product()
        return product or self.env['product.product'].create({
            'name': 'Xe bán hàng gấp gọn',
            'type': 'cart',
            'sale_ok': True,
        })

    def test_cart_order_prefills_product_before_save(self):
        product = self._default_cart_product()
        defaults = self.env['sale.order'].with_context(
            default_order_type='cart',
        ).default_get(['order_type', 'order_line'])
        values = defaults['order_line'][0][2]
        self.assertEqual(values['product_id'], product.id)
        self.assertEqual(values['product_uom_qty'], 1)
        self.assertEqual(values['material'], 'hiflex_silver')
        self.assertEqual((values['length'], values['width']), (80, 38))
        self.assertEqual(values['price_unit'], 950000 + sum(
            product.product_template_attribute_value_ids.mapped('price_extra')
        ))

    def test_switching_to_cart_preserves_lines_without_duplicate(self):
        product = self._default_cart_product()
        order = self.env['sale.order'].new({
            'order_type': 'cart',
            'order_line': [(0, 0, {
                'display_type': 'line_note', 'name': 'Giữ ghi chú', 'sequence': 5,
            })],
        })
        order._onchange_order_type_cart()
        order.order_type = 'general'
        order._onchange_order_type_cart()
        order.order_type = 'cart'
        order._onchange_order_type_cart()
        self.assertEqual(len(order.order_line), 2)
        self.assertEqual(order.fulfillment_method, 'delivery')
        self.assertEqual(order.order_line.sorted('sequence')[0].product_id, product)
        self.assertEqual(order.order_line.filtered('display_type').name, 'Giữ ghi chú')

    def test_general_order_does_not_prefill_cart(self):
        self._default_cart_product()
        defaults = self.env['sale.order'].with_context(
            default_order_type='general',
        ).default_get(['order_type', 'order_line'])
        self.assertFalse(defaults.get('order_line'))

    def test_cart_line_defaults_to_hiflex_and_80x38(self):
        defaults = self.env['sale.order.line'].with_context(
            default_order_type='cart',
        ).default_get(['material', 'cart_dimension_id'])

        self.assertEqual(defaults['material'], 'hiflex_silver')
        self.assertEqual(
            defaults['cart_dimension_id'],
            self.env.ref('dac_erp.cart_dimension_80x40').id,
        )

    def test_duplicate_dimensions_are_merged_without_losing_line_links(self):
        canonical = self.env.ref('dac_erp.cart_dimension_80x40')
        duplicate = self.env['dac.cart.dimension'].create({
            'length': canonical.length,
            'width': canonical.width,
            'height': canonical.height,
        })
        partner = self.env['res.partner'].create({'name': 'Khách kiểm thử migration'})
        order = self.env['sale.order'].create({'partner_id': partner.id})
        line = self.env['sale.order.line'].create({
            'name': 'Xe kiểm thử migration kích thước',
            'order_id': order.id,
            'cart_dimension_id': duplicate.id,
        })

        self.env['dac.cart.dimension']._merge_duplicate_dimensions()

        self.assertFalse(duplicate.exists())
        self.assertEqual(line.cart_dimension_id, canonical)

    def test_unit_price_follows_selected_dimension_and_material(self):
        dimensions = {
            (80.0, 38.0): (950000.0, 1260000.0, 1760000.0),
            (100.0, 48.0): (1135000.0, 1395000.0, 1890000.0),
            (120.0, 58.0): (1460000.0, 1760000.0, 2290000.0),
        }
        material_codes = ('hiflex_silver', 'formex', 'alu')
        for (length, width), expected_prices in dimensions.items():
            dimension = self.env['dac.cart.dimension'].create({
                'length': length,
                'width': width,
                'height': 195.0,
            })
            for material_code, expected_price in zip(material_codes, expected_prices):
                line = self.env['sale.order.line'].new({
                    'cart_dimension_id': dimension.id,
                    'material': material_code,
                })
                line._onchange_cart_material_or_dimension()
                self.assertEqual(line.price_unit, expected_price)

    def test_unit_price_keeps_variant_accessory_surcharge(self):
        attribute = self.env['product.attribute'].create({
            'name': 'Phụ kiện kiểm thử bảng giá xe',
            'display_type': 'radio',
            'create_variant': 'always',
        })
        value = self.env['product.attribute.value'].create({
            'name': 'Dù kiểm thử',
            'attribute_id': attribute.id,
        })
        template = self.env['product.template'].create({
            'name': 'Xe kiểm thử giá phụ kiện',
            'list_price': 950000.0,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, [value.id])],
            })],
        })
        template.attribute_line_ids.product_template_value_ids.price_extra = 220000.0
        dimension = self.env['dac.cart.dimension'].create({
            'length': 120.0,
            'width': 58.0,
            'height': 195.0,
        })
        line = self.env['sale.order.line'].new({
            'product_id': template.product_variant_id.id,
            'cart_dimension_id': dimension.id,
            'material': 'alu',
        })

        line._onchange_cart_material_or_dimension()

        self.assertEqual(line.price_unit, 2510000.0)

    def test_multiple_accessories_update_unit_price_without_accumulating(self):
        accessories = self.env['dac.sale.order.accessory'].create([
            {'name': 'Test umbrella', 'price': 220000},
            {'name': 'Test wing', 'price': 180000},
        ])
        line = self.env['sale.order.line'].new({
            'price_unit': 950000,
            'product_uom_qty': 2,
            'discount': 10,
            'tax_id': [(5, 0, 0)],
            'company_id': self.env.company.id,
            'currency_id': self.env.company.currency_id.id,
        })
        line.accessory_ids = accessories
        line._onchange_accessory_ids()
        self.assertEqual(line.price_unit, 1350000)
        line._onchange_accessory_ids()
        self.assertEqual(line.price_unit, 1350000)
        line._compute_amount()
        self.assertEqual(line.price_subtotal, 2430000)
        line.accessory_ids = accessories[:1]
        line._onchange_accessory_ids()
        self.assertEqual(line.price_unit, 1170000)
        line.accessory_ids = False
        line._onchange_accessory_ids()
        self.assertEqual(line.price_unit, 950000)

    def test_cart_repricing_preserves_selected_accessories(self):
        accessory = self.env['dac.sale.order.accessory'].create({
            'name': 'Test umbrella', 'price': 220000,
        })
        line = self.env['sale.order.line'].new({
            'material': 'hiflex_silver',
            'cart_dimension_id': self.env.ref('dac_erp.cart_dimension_80x40').id,
            'accessory_ids': [(6, 0, accessory.ids)],
        })
        line._onchange_cart_material_or_dimension()
        line._onchange_accessory_ids()
        self.assertEqual(line.price_unit, 1170000)
        line.material_id = self.env['dac.sale.material'].search([('code', '=', 'alu')], limit=1)
        line._onchange_cart_material_or_dimension()
        self.assertEqual(line.price_unit, 1980000)
