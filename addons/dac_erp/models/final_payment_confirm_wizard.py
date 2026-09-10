from odoo import models, fields, api
from odoo.exceptions import UserError

class FinalPaymentConfirmWizard(models.TransientModel):
    _name = 'final.payment.confirm.wizard'
    _description = 'Xác nhận thanh toán cuối cùng'

    # === Thông tin hiển thị (readonly) ===
    order_name = fields.Char(string="Đơn hàng", readonly=True)
    partner_name = fields.Char(string="Khách hàng", readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', readonly=True)
    amount_total_order = fields.Monetary(string="Tổng giá trị đơn hàng", currency_field='currency_id', readonly=True)
    deposit_paid = fields.Monetary(string="Tiền cọc đã thu", currency_field='currency_id', readonly=True)
    
    # Số tiền cần thu (readonly, tính từ context)
    amount = fields.Monetary(string="Số tiền phải thu", currency_field='currency_id', readonly=True)

    # === Thông tin thanh toán (user nhập) ===
    journal_id = fields.Many2one('account.journal', string='Phương thức thanh toán', domain=[('type', 'in', ('bank', 'cash'))], required=True)
    payment_date = fields.Date(string="Ngày thanh toán", default=fields.Date.context_today, required=True)

    @api.model
    def default_get(self, fields_list):
        """Auto-fill thông tin đơn hàng từ context"""
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'sale.order':
            order = self.env['sale.order'].browse(active_id)
            if order.exists():
                res['order_name'] = order.name
                res['partner_name'] = order.partner_id.name or ''
                res['currency_id'] = order.currency_id.id
                res['amount_total_order'] = order.amount_total

                # Tính tiền cọc đã thu
                deposit_invoices = self.env['account.move'].search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', order.name),
                    ('dac_deposit_invoice', '=', True),
                    ('payment_state', '=', 'paid')
                ])
                deposit_paid = sum(deposit_invoices.mapped('amount_total'))
                res['deposit_paid'] = deposit_paid

                # Số tiền phải thu (từ context hoặc tính lại)
                if self.env.context.get('default_amount'):
                    res['amount'] = self.env.context['default_amount']
                else:
                    # Tính lại nếu không có trong context
                    product_lines = order.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
                    total_original = sum(line.price_unit * line.product_uom_qty for line in product_lines)
                    res['amount'] = max(total_original - deposit_paid, 0.0)
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.journal_id or not self.payment_date:
            raise UserError("Vui lòng chọn phương thức thanh toán và ngày thanh toán.")

        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
        
        if active_model == 'sale.order' and active_id:
            order = self.env['sale.order'].browse(active_id)
            if order.exists():
                return order._create_final_invoice_and_payment(self.journal_id, self.payment_date)
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}
