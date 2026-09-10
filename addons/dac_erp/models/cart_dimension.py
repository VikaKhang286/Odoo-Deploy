from odoo import api, fields, models


class CartDimension(models.Model):
    _name = 'dac.cart.dimension'
    _description = 'Kích thước xe đẩy'
    _order = 'sequence, id'

    name = fields.Char(string='Kích thước', compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    length = fields.Float(string='Chiều dài (cm)', required=True)
    width = fields.Float(string='Chiều rộng (cm)', required=True)
    height = fields.Float(string='Chiều cao (cm)', required=True, default=195.0)
    is_standard = fields.Boolean(
        string='Kích thước tiêu chuẩn',
        default=False,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    @api.depends('length', 'width')
    def _compute_name(self):
        """Tạo nhãn dropdown từ ba số đo, người dùng không cần nhập tên."""
        for dimension in self:
            values = (dimension.length, dimension.width)
            dimension.name = ' x '.join(
                f'{value:g} cm' for value in values
            )

    def action_delete_dimension(self):
        """Xóa kích thước nhập sai trực tiếp từ form."""
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def action_delete_dimension_from_list(self):
        """Xóa một kích thước từ popup tìm kiếm và làm mới danh sách."""
        self.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
