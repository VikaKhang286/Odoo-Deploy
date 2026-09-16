from odoo import fields, models

class DacErpAiModel(models.Model):
    _name = 'dac_erp.ai_model'
    _description = 'DAC ERP AI Model'
    _order = 'sequence, id'

    name = fields.Char(string='Tên Model', required=True)
    is_active = fields.Boolean(string='Hoạt động', default=True)
    sequence = fields.Integer(string='Độ ưu tiên', default=10)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tên model phải là duy nhất!'),
    ]
