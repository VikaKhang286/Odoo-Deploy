from odoo import models, fields, api
from odoo.exceptions import UserError

class DepositConfirmWizard(models.TransientModel):
    _name = 'deposit.confirm.wizard'
    _description = 'Xác nhận không thể thay đổi đặt cọc'

    # === Thông tin hiển thị (readonly) ===
    order_name = fields.Char(string="Đơn hàng", readonly=True)
    partner_name = fields.Char(string="Khách hàng", readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', readonly=True)
    amount_total_order = fields.Monetary(string="Tổng giá trị đơn hàng", currency_field='currency_id', readonly=True)
    deposit_amount = fields.Monetary(string="Số tiền đặt cọc", currency_field='currency_id', readonly=True)

    # === Thông tin thanh toán (user nhập) ===
    journal_id = fields.Many2one('account.journal', string='Phương thức thanh toán', domain=[('type', 'in', ('bank', 'cash'))], required=True)
    payment_date = fields.Date(string="Ngày thanh toán", default=fields.Date.context_today, required=True)

    @api.model
    def default_get(self, fields_list):
        """Auto-fill thông tin đơn hàng từ context"""
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['sale.order'].browse(active_id)
            if order.exists():
                res['order_name'] = order.name
                res['partner_name'] = order.partner_id.name or ''
                res['currency_id'] = order.currency_id.id
                res['amount_total_order'] = order.amount_total
                res['deposit_amount'] = order.deposit_amount
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.journal_id or not self.payment_date:
            raise UserError("Vui lòng chọn phương thức thanh toán và ngày thanh toán.")

        active_id = self.env.context.get('active_id')
        order = self.env['sale.order'].browse(active_id)
        if order.deposit_amount <= 0:
            raise UserError("Vui lòng nhập số tiền đặt cọc hợp lệ trước khi xác nhận!")
        if not order.has_deposit:
            order.has_deposit = True

        # Kiểm tra đã có hóa đơn đặt cọc chưa (tìm theo ref hoặc origin)
        invoice = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', order.name),
            ('dac_deposit_invoice', '=', True)
        ], limit=1)
        
        is_new_invoice = False
        
        if not invoice:
            is_new_invoice = True
            # Lấy account doanh thu (income) đầu tiên
            income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
            if not income_account:
                raise UserError('Không tìm thấy tài khoản doanh thu (income) để tạo hóa đơn đặt cọc!')
            
            # Tạo ref unique để tránh cảnh báo trùng lặp
            existing_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True)
            ])
            
            invoice_ref = f"DEPOSIT-{order.name}"
            if existing_count > 0:
                invoice_ref = f"DEPOSIT-{order.name}-{existing_count + 1}"
            
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': order.partner_id.id,
                'invoice_origin': order.name,
                'ref': invoice_ref,  # Thêm reference unique
                'invoice_date': self.payment_date, # Thêm ngày hóa đơn
                'invoice_line_ids': [
                    (0, 0, {
                        'name': f'Đặt cọc cho đơn hàng {order.name}',
                        'quantity': 1,
                        'price_unit': order.deposit_amount,
                        'account_id': income_account.id,
                    })
                ],
                'dac_deposit_invoice': True,
            }
            invoice = self.env['account.move'].create(invoice_vals)
            
        # Tự động xác nhận (Post) hóa đơn
        if invoice.state == 'draft':
            invoice.action_post()
            
        # Tự động gạch nợ (Payment)
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids
        ).create({
            'amount': order.deposit_amount,
            'journal_id': self.journal_id.id,
            'payment_date': self.payment_date,
        })
        payment_register._create_payments()

        # CHỈ set is_deposit_confirmed, KHÔNG tự động chuyển sang sản xuất
        # Chỉ khi hóa đơn được thanh toán thì mới có thể tiến hành sản xuất
        order.is_deposit_confirmed = True
        
        # Tự động đồng bộ dòng đặt cọc
        order._auto_sync_deposit_line()
        
        # KHÔNG tự động chuyển: order.order_state_custom = 'production'
        
        # Luôn reload lại trang để trải nghiệm liền mạch (không nhảy sang invoice)
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
