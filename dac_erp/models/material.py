from odoo import fields, models


class SaleMaterial(models.Model):
    _name = 'dac.sale.material'
    _description = 'Chất liệu'
    _order = 'sequence, id'

    name = fields.Char(string='Chất liệu', required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    _sql_constraints = [('code_unique', 'unique(code)', 'Mã chất liệu phải duy nhất.')]
