from odoo import models, fields, api
from odoo.exceptions import UserError

class DepositConfirmWizard(models.TransientModel):
    _name = 'deposit.confirm.wizard'
    _description = 'Xác nhận không thể thay đổi đặt cọc'

    confirm_read = fields.Boolean(string="Tôi đã đọc kỹ và đồng ý", required=True)

    def action_confirm(self):
        active_id = self.env.context.get('active_id')
        order = self.env['sale.order'].browse(active_id)
        if not order.has_deposit or order.deposit_amount <= 0:
            raise UserError("Vui lòng nhập số tiền đặt cọc hợp lệ trước khi xác nhận!")

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
            
        # CHỈ set is_deposit_confirmed, KHÔNG tự động chuyển sang sản xuất
        # Chỉ khi hóa đơn được thanh toán thì mới có thể tiến hành sản xuất
        order.is_deposit_confirmed = True
        # KHÔNG tự động chuyển: order.order_state_custom = 'production'
        
        # Luôn chuyển đến view hóa đơn mặc định (không dùng popup)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn đặt cọc',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_move_type': 'out_invoice',
                'create': False,
            }
        }