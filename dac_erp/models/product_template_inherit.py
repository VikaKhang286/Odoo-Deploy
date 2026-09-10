from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    type = fields.Selection(
        selection_add=[('product', 'Product'), ('combo', 'Combo')],
        ondelete={'product': 'set default', 'combo': 'set default'}
    )