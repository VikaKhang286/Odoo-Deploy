from odoo import api, fields, models

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _ensure_cart_product_categories(self):
        """Reuse existing categories and expose stable references for filters."""
        Category = self.env['product.category']
        def ensure(xml_name, name, parent):
            category = self.env.ref('dac_erp.' + xml_name, raise_if_not_found=False)
            if not category:
                category = Category.search([
                    ('name', '=', name), ('parent_id', '=', parent.id or False),
                ], limit=1)
            if not category and xml_name == 'product_category_cart':
                category = Category.search([
                    ('name', '=', 'All / Xe đẩy'), ('parent_id', '=', False),
                ], limit=1)
            if category:
                category.write({'name': name, 'parent_id': parent.id or False})
            else:
                category = Category.create({'name': name, 'parent_id': parent.id or False})
            if not self.env.ref('dac_erp.' + xml_name, raise_if_not_found=False):
                self.env['ir.model.data'].create({
                    'module': 'dac_erp', 'name': xml_name,
                    'model': 'product.category', 'res_id': category.id, 'noupdate': True,
                })
            return category
        root = self.env.ref('product.product_category_all', raise_if_not_found=False)
        if not root:
            root = Category.search([('name', '=', 'All'), ('parent_id', '=', False)], limit=1)
        if not root:
            root = Category.create({'name': 'All'})
        cart = ensure('product_category_cart', 'Xe đẩy', root)
        ensure('product_category_cart_foldable', 'Xe gấp gọn', cart)
        ensure('product_category_cart_accessory', 'Phụ kiện', cart)

    type = fields.Selection(
        selection_add=[
            ('product', 'Product'),
            ('combo', 'Combo'),
            ('cart', 'Xe gấp gọn'),
            ('cart_accessory', 'Phụ kiện'),
        ],
        ondelete={
            'product': 'set default',
            'combo': 'set default',
            'cart': 'set default',
            'cart_accessory': 'set default',
        }
    )

    def _cart_category_for_type(self, product_type):
        xml_name = {
            'cart': 'product_category_cart_foldable',
            'cart_accessory': 'product_category_cart_accessory',
        }.get(product_type)
        return self.env.ref('dac_erp.' + xml_name, raise_if_not_found=False) if xml_name else False

    @api.onchange('type')
    def _onchange_cart_product_category(self):
        for product in self:
            category = product._cart_category_for_type(product.type)
            if category:
                product.categ_id = category

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            values = dict(values)
            category = self._cart_category_for_type(values.get('type'))
            if category:
                values['categ_id'] = category.id
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        values = dict(values)
        category = self._cart_category_for_type(values.get('type'))
        if category:
            values['categ_id'] = category.id
        return super().write(values)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.depends(
        'name',
        'default_code',
        'type',
        'product_tmpl_id',
        'product_template_attribute_value_ids',
        'product_template_attribute_value_ids.name',
    )
    @api.depends_context(
        'display_default_code',
        'seller_id',
        'company_id',
        'partner_id',
        'lang',
        'dac_variant_display',
        'dac_cart_accessory_prefix',
    )
    def _compute_display_name(self):
        super()._compute_display_name()
        if not (self.env.context.get('dac_variant_display')
                or self.env.context.get('dac_cart_accessory_prefix')):
            return

        for product in self:
            attribute_values = product.product_template_attribute_value_ids
            attribute_names = attribute_values.mapped('attribute_id.name')
            variant_values = [
                value
                for value in attribute_values.mapped('name')
                if 'không' not in value.casefold()
            ]
            if (self.env.context.get('dac_variant_display')
                    and any(name.strip() == 'Phụ kiện' for name in attribute_names)):
                product.display_name = ' + '.join([product.name, *variant_values])

            if (self.env.context.get('dac_cart_accessory_prefix')
                    and product.type == 'cart_accessory'):
                product.display_name = '+ ' + product.display_name
