from odoo import api, fields, models


class SaleOrderAccessory(models.Model):
    _name = 'dac.sale.order.accessory'
    _description = 'Phụ kiện'
    _order = 'sequence, name'

    name = fields.Char(string='Tên phụ kiện', required=True, translate=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    price = fields.Monetary(string='Giá tiền', required=True, currency_field='currency_id')

    @api.model
    def _ensure_default_accessory_prices(self):
        """Đồng bộ giá cho danh mục đã được tạo ở các lần nâng cấp trước."""
        prices = {
            'Dù 1m6': 220000,
            'Dù 1m8': 300000,
            '1 cánh gà': 180000,
            '2 cánh gà': 360000,
            '1 mái che trên': 200000,
            '1 hộc tủ trong': 180000,
            '1 kệ đá': 120000,
            '1 kệ trưng bày': 240000,
            '2 kệ trưng bày': 480000,
            'Mẫu bo tròn': 50000,
        }
        for name, price in prices.items():
            accessory = self.search([('name', '=', name)], limit=1)
            if accessory:
                accessory.write({
                    'price': price,
                    'currency_id': self.env.company.currency_id.id,
                })
