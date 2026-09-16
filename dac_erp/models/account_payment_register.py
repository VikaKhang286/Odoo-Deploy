from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # Thêm field người phụ trách để phân quyền
    dac_user_id = fields.Many2one('res.users', string='Người phụ trách', default=lambda self: self.env.user)

    def read(self, fields=None, load='_classic_read'):
        """Override read để chặn Design/Production users truy cập phiếu thu"""
        user = self.env.user
        
        # Chặn Design và Production thuần (không phải Manager/Admin/Sale)
        if user._dac_is_worker_only():

            _logger.warning(f"BLOCKED READ: User {user.name} (ID: {user.id}) tried to read account.payment {self.ids}")
            
            raise AccessError(
                "Bạn không có quyền xem phiếu thu!\n\n"
                "Nếu cần xem thông tin thanh toán, vui lòng liên hệ:\n"
                "- Sale phụ trách đơn hàng\n"
                "- Quản lý bộ phận kế toán\n\n"
                "Cảm ơn bạn!"
            )
        
        return super().read(fields, load)
    
    def web_read(self, specification):
        """Override web_read để chặn JSON-RPC calls từ Design/Production users"""
        user = self.env.user
        
        # Chặn Design và Production thuần (không phải Manager/Admin/Sale)
        if user._dac_is_worker_only():

            _logger.warning(f"BLOCKED WEB_READ: User {user.name} (ID: {user.id}) tried to web_read account.payment {self.ids}")
            
            raise AccessError(
                "⛔ Bạn không có quyền xem phiếu thu!\n\n"
                "Nếu cần xem thông tin thanh toán, vui lòng liên hệ:\n"
                "- Sale phụ trách đơn hàng\n"
                "- Quản lý bộ phận kế toán\n\n"
                "Cảm ơn bạn!"
            )
        
        return super().web_read(specification)

    def action_confirm_payment_custom(self):
        """Custom method để xác nhận thanh toán - từ draft sang posted"""
        self.ensure_one()
        _logger.info(f"action_confirm_payment_custom called for payment {self.name}, current state: {self.state}")
        
        try:
            # Gọi method action_post gốc của Odoo (draft -> posted)
            result = super(AccountPayment, self).action_post()
            _logger.info(f"action_post completed for payment {self.name}, new state: {self.state}")
            
            # Force refresh view bằng cách reload record
            return {
                'type': 'ir.actions.act_window',
                'name': f'Thanh toán - {self.name}',
                'res_model': 'account.payment',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'current',
                'context': {'force_refresh': True}
            }
        except Exception as e:
            _logger.error(f"Error confirming payment {self.name}: {e}")
            raise UserError(f"Lỗi khi xác nhận thanh toán: {str(e)}")

    def action_back_to_draft_custom(self):
        """Custom method để quay về trạng thái nháp"""
        self.ensure_one()
        _logger.info(f"action_back_to_draft_custom called for payment {self.name}, current state: {self.state}")
        
        try:
            # Gọi method action_draft gốc của Odoo để reset về draft
            result = self.action_draft()
            _logger.info(f"action_draft completed for payment {self.name}, new state: {self.state}")
            
            # Force refresh view
            return {
                'type': 'ir.actions.act_window',
                'name': f'Thanh toán - {self.name}',
                'res_model': 'account.payment',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'current',
                'context': {'force_refresh': True}
            }
        except Exception as e:
            _logger.error(f"Error resetting payment to draft {self.name}: {e}")
            raise UserError(f"Lỗi khi quay về nháp: {str(e)}")

    def action_mark_as_paid_custom(self):
        """Custom method để đánh dấu thanh toán hoàn tất - từ posted sang paid thông qua reconcile"""
        self.ensure_one()
        _logger.info(f"action_mark_as_paid_custom called for payment {self.name}, current state: {self.state}")
        
        try:
            # Kiểm tra payment đã có move_id chưa
            if not self.move_id:
                _logger.error(f"Payment {self.name} has no move_id - cannot reconcile")
                raise UserError("Payment chưa có journal entry. Vui lòng xác nhận payment trước.")
            
            # Debug: In ra thông tin move lines
            _logger.info(f"Payment {self.name} move_id: {self.move_id.id}, line count: {len(self.move_id.line_ids)}")
            for line in self.move_id.line_ids:
                _logger.info(f"Move line: {line.account_id.code} - {line.account_id.name}, debit: {line.debit}, credit: {line.credit}, account_type: {line.account_id.account_type}")
            
            # Tìm invoice liên quan theo memo field
            related_invoices = self.env['account.move']
            
            # Cách 1: Tìm theo memo field
            if self.memo:
                related_invoices = self.env['account.move'].search([
                    ('name', '=', self.memo),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted')
                ])
                _logger.info(f"Search by memo '{self.memo}': {related_invoices.mapped('name')}")
            
            # Cách 2: Tìm theo name replacement nếu memo không có
            if not related_invoices and self.name:
                invoice_name = self.name.replace('PCSH1', 'INV')
                related_invoices = self.env['account.move'].search([
                    ('name', '=', invoice_name),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted')
                ])
                _logger.info(f"Search by name replacement '{invoice_name}': {related_invoices.mapped('name')}")
            
            _logger.info(f"Found {len(related_invoices)} related invoices for payment {self.name}")
            
            if related_invoices:
                # Thực hiện reconcile với invoice thông qua move_line_ids của payment
                for invoice in related_invoices:
                    # Tìm receivable line của invoice
                    invoice_receivable_lines = invoice.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                    )
                    
                    # Tìm receivable line của payment thông qua move_id
                    if self.move_id:
                        payment_receivable_lines = self.move_id.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                    else:
                        payment_receivable_lines = self.env['account.move.line']
                    
                    _logger.info(f"Invoice receivable lines: {len(invoice_receivable_lines)}, Payment receivable lines: {len(payment_receivable_lines)}")
                    
                    if invoice_receivable_lines and payment_receivable_lines:
                        # Thực hiện reconcile
                        lines_to_reconcile = invoice_receivable_lines + payment_receivable_lines
                        lines_to_reconcile.reconcile()
                        _logger.info(f"Successfully reconciled payment {self.name} with invoice {invoice.name}")
                        break  # Chỉ reconcile với invoice đầu tiên
            else:
                _logger.info("No invoices found for reconciliation")
            
            # Force refresh view
            return {
                'type': 'ir.actions.act_window',
                'name': f'Thanh toán - {self.name}',
                'res_model': 'account.payment',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'current',
                'context': {'force_refresh': True}
            }
        except Exception as e:
            _logger.error(f"Error marking payment as paid {self.name}: {e}")
            raise UserError(f"Lỗi khi hoàn tất thanh toán: {str(e)}")

    @api.model_create_multi
    def create(self, vals_list):
        """Override create để gán người tạo phiếu thu làm người phụ trách"""
        for vals in vals_list:
            if not vals.get('dac_user_id'):
                vals['dac_user_id'] = self.env.user.id
        return super().create(vals_list)

    def unlink(self):
        """Kiểm tra quyền xóa phiếu thu - CHỈ ÁP DỤNG CHO SALES USERS"""
        for payment in self:
            # Nếu user là DAC sale (không phải manager hoặc admin) -> không cho xóa
            if (self.env.user._dac_is_sale() and
                not self.env.user._dac_is_manager() and
                not self.env.user._dac_is_admin()):
                raise AccessError(
                    f"Bạn không có quyền xóa phiếu thu {payment.name}!\n"
                    "Liên hệ quản lý để được hỗ trợ."
                )
        
        return super().unlink()


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        """Override để ưu tiên reuse existing payments thay vì tạo mới"""
        _logger.info("=== ENHANCED HOOK - CHECK EXISTING PAYMENTS FIRST ===")
        
        # STEP 1: Kiểm tra có existing payments cho invoice này không
        if self.env.context.get('active_model') == 'account.move':
            active_ids = self.env.context.get('active_ids', [])
            _logger.info(f"ENHANCED: Checking existing payments for active_ids: {active_ids}")
            
            for move_id in active_ids:
                move = self.env['account.move'].browse(move_id)
                if move.exists() and move.move_type == 'out_invoice':
                    # Tìm DRAFT payments cho invoice này
                    existing_draft_payments = self.env['account.payment'].search([
                        ('name', 'like', move.name),
                        ('state', '=', 'draft'),
                        ('payment_type', '=', 'inbound'),
                        ('partner_id', '=', move.partner_id.id)
                    ])
                    
                    # Tìm POSTED payments chưa reconcile cho invoice này
                    potential_payments = self.env['account.payment'].search([
                        ('name', 'like', move.name),
                        ('state', '=', 'posted'),
                        ('payment_type', '=', 'inbound'),
                        ('partner_id', '=', move.partner_id.id),
                        ('is_reconciled', '=', False)
                    ])
                    # Lọc trong Python để tránh lỗi ORM 'NotImplementedType' 
                    existing_posted_payments = potential_payments.filtered(
                        lambda p: hasattr(p, 'reconciled_invoice_ids') and move.id not in p.reconciled_invoice_ids.ids
                    )
                    
                    # Ưu tiên DRAFT payments
                    if existing_draft_payments:
                        _logger.info(f"ENHANCED: Found {len(existing_draft_payments)} DRAFT payments for {move.name}")
                        return self._handle_existing_payments(existing_draft_payments, move, 'draft')
                    
                    # Nếu không có draft, kiểm tra posted payments chưa reconcile
                    elif existing_posted_payments:
                        _logger.info(f"ENHANCED: Found {len(existing_posted_payments)} POSTED unreconciled payments for {move.name}")
                        return self._handle_existing_payments(existing_posted_payments, move, 'posted')
        
        # STEP 2: Nếu không có existing payment, tiếp tục flow bình thường
        _logger.info("ENHANCED: No existing payments found, proceeding with normal flow...")
        return super().action_create_payments()
    
    def _handle_existing_payments(self, payments, invoice, payment_state):
        """Xử lý existing payments dựa trên trạng thái"""
        if len(payments) == 1:
            payment = payments[0]
            
            if payment_state == 'draft':
                # Nếu là draft payment, mở để confirm
                return {
                    'type': 'ir.actions.act_window',
                    'name': f'Xác nhận thanh toán - {payment.name}',
                    'res_model': 'account.payment',
                    'view_mode': 'form',
                    'res_id': payment.id,
                    'target': 'current',
                    'context': {
                        'default_state': 'draft',
                        'show_confirm_button': True
                    }
                }
            else:
                # Nếu là posted payment, thực hiện reconcile luôn
                return self._auto_reconcile_payment(payment, invoice)
        else:
            # Nhiều payments, hiển thị list để chọn
            return {
                'type': 'ir.actions.act_window',
                'name': f'Chọn thanh toán để xác nhận - {invoice.name}',
                'res_model': 'account.payment',
                'view_mode': 'list,form',
                'domain': [('id', 'in', payments.ids)],
                'target': 'current',
                'context': {'create': False}
            }
    
    def _auto_reconcile_payment(self, payment, invoice):
        """Tự động reconcile payment với invoice"""
        try:
            # Tìm receivable line của invoice
            invoice_line = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )
            
            # Tìm receivable line của payment
            payment_line = payment.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )
            
            if invoice_line and payment_line:
                # Thực hiện reconcile
                (invoice_line + payment_line).reconcile()
                
                _logger.info(f"ENHANCED: Successfully reconciled payment {payment.name} with invoice {invoice.name}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thành công',
                        'message': f'Thanh toán {payment.name} đã được liên kết với hóa đơn {invoice.name}',
                        'type': 'success',
                        'next': {
                            'type': 'ir.actions.act_window_close'
                        }
                    }
                }
            else:
                # Không tìm thấy line để reconcile, mở payment form
                return {
                    'type': 'ir.actions.act_window',
                    'name': f'Hoàn tất thanh toán - {payment.name}',
                    'res_model': 'account.payment',
                    'view_mode': 'form',
                    'res_id': payment.id,
                    'target': 'current'
                }
                
        except Exception as e:
            _logger.error(f"ENHANCED: Error reconciling payment {payment.name}: {e}")
            
            # Lỗi reconcile, mở payment form để xử lý thủ công
            return {
                'type': 'ir.actions.act_window',
                'name': f'Hoàn tất thanh toán - {payment.name}',
                'res_model': 'account.payment',
                'view_mode': 'form',
                'res_id': payment.id,
                'target': 'current'
            }
