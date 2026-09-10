from odoo import api, fields, models
from odoo.exceptions import UserError


class DeliveryAddressWizard(models.TransientModel):
    _name = 'delivery.address.wizard'
    _description = 'Confirm Delivery Address Before Delivery'

    order_name = fields.Char(string='Đơn hàng', readonly=True)
    delivery_address = fields.Text(string='Địa chỉ giao hàng')
    has_delivery_address = fields.Boolean(
        string='Đã nhập địa chỉ',
        compute='_compute_has_delivery_address',
    )

    @api.depends('delivery_address')
    def _compute_has_delivery_address(self):
        for wizard in self:
            wizard.has_delivery_address = bool((wizard.delivery_address or '').strip())

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if not active_id:
            return res

        order = self.env['sale.order'].browse(active_id)
        if not order.exists():
            return res

        res.update({
            'order_name': order.name,
            'delivery_address': order.delivery_address,
        })
        return res

    def _get_active_order(self):
        self.ensure_one()
        order = self.env['sale.order'].browse(self.env.context.get('active_id'))
        if not order.exists():
            raise UserError('Không tìm thấy đơn hàng để cập nhật thông tin giao hàng.')
        return order

    def action_confirm_delivery(self):
        self.ensure_one()
        if not (self.delivery_address or '').strip():
            raise UserError('Vui lòng nhập địa chỉ giao hàng hoặc chọn khách đến nhận hàng.')

        order = self._get_active_order()
        result = order._confirm_delivery_step(delivery_address=self.delivery_address)
        if result is True:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return result

    def action_mark_customer_pickup(self):
        self.ensure_one()
        order = self._get_active_order()
        result = order._confirm_delivery_step(
            delivery_address=self.delivery_address,
            customer_pickup=True,
        )
        if result is True:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return result
