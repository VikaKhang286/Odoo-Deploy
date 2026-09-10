from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    dac_deposit_invoice = fields.Boolean(string='Hóa đơn đặt cọc', default=False)

    def read(self, fields=None, load='_classic_read'):
        """Override read để chặn Design/Production users truy cập hóa đơn"""
        user = self.env.user
        
        # Chặn Design và Production (không phải Manager/Admin/Sale)
        if (user.has_group('dac_erp.group_dac_erp_design') or 
            user.has_group('dac_erp.group_dac_erp_production')) and \
           not (user.has_group('dac_erp.group_dac_erp_manager') or 
                user.has_group('dac_erp.group_dac_erp_sale') or
                user.has_group('base.group_system')):
            
            _logger.warning(f"BLOCKED READ: User {user.name} (ID: {user.id}) tried to read account.move {self.ids}")
            
            raise AccessError(
                "Bạn không có quyền xem hóa đơn!\n\n"
                "Nếu cần xem thông tin hóa đơn, vui lòng liên hệ:\n"
                "- Sale phụ trách đơn hàng\n"
                "- Quản lý bộ phận kế toán\n\n"
                "Cảm ơn bạn!"
            )
        
        return super().read(fields, load)
    
    def web_read(self, specification):
        """Override web_read để chặn JSON-RPC calls từ Design/Production users"""
        user = self.env.user
        
        # Chặn Design và Production (không phải Manager/Admin/Sale)
        if (user.has_group('dac_erp.group_dac_erp_design') or 
            user.has_group('dac_erp.group_dac_erp_production')) and \
           not (user.has_group('dac_erp.group_dac_erp_manager') or 
                user.has_group('dac_erp.group_dac_erp_sale') or
                user.has_group('base.group_system')):
            
            _logger.warning(f"BLOCKED WEB_READ: User {user.name} (ID: {user.id}) tried to web_read account.move {self.ids}")
            
            raise AccessError(
                "Bạn không có quyền xem hóa đơn!\n\n"
                "Nếu cần xem thông tin hóa đơn, vui lòng liên hệ:\n"
                "- Sale phụ trách đơn hàng\n"
                "- Quản lý bộ phận kế toán\n\n"
                "Cảm ơn bạn!"
            )
        
        return super().web_read(specification)

    def unlink(self):
        """Kiểm tra quyền xóa hóa đơn - CHỈ ÁP DỤNG CHO SALES USERS"""
        for move in self:
            # Nếu user là DAC sale (không phải manager hoặc admin) -> không cho xóa
            if (self.env.user.has_group('dac_erp.group_dac_erp_sale') and 
                not self.env.user.has_group('dac_erp.group_dac_erp_manager') and
                not self.env.user.has_group('base.group_system')):
                raise AccessError(
                    f"Bạn không có quyền xóa hóa đơn {move.name}!\n"
                    "Liên hệ quản lý để được hỗ trợ."
                )
        
        # Lưu thông tin đơn hàng liên quan trước khi xóa
        order_names = self.filtered(
            lambda m: m.move_type == 'out_invoice' and m.invoice_origin
        ).mapped('invoice_origin')
        sale_orders = self.env['sale.order'].search([('name', 'in', order_names)])
        res = super().unlink()
        # Invalidate cache cho các đơn hàng liên quan sau khi xóa
        if sale_orders:
            # Nếu KHÔNG còn bất kỳ hóa đơn cuối (không cọc) đã vào sổ -> hạ is_payment_confirmed
            for order in sale_orders:
                has_posted_final = self.env['account.move'].search_count([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', order.name),
                    ('dac_deposit_invoice', '=', False),
                    ('state', '=', 'posted'),
                ]) > 0
                if not has_posted_final and order.is_payment_confirmed:
                    order.is_payment_confirmed = False  # mở lại bước "payment"
            
            # refresh lại view đơn hàng
            sale_orders.invalidate_recordset()
        return res

    # Thêm field người phụ trách để phân quyền
    dac_user_id = fields.Many2one('res.users', string='Người phụ trách', default=lambda self: self.env.user)
    
    # Computed fields để hiển thị thông tin payments
    payment_count = fields.Integer(string='Số phiếu thu', compute='_compute_payment_count')
    has_existing_payments = fields.Boolean(string='Có phiếu thu', compute='_compute_has_existing_payments')
    
    @api.depends('name', 'payment_state')
    def _compute_payment_count(self):
        """Tính số lượng payments liên quan đến hóa đơn này (bao gồm cả draft)"""
        for move in self:
            if move.move_type == 'out_invoice' and move.name:
                # Cách 1: Tìm qua reconciled payments (chính xác nhất)
                reconciled_payments = move._get_reconciled_payments()
                
                # Cách 2: Tìm qua name field (bao gồm cả draft và posted)
                payments_by_name = self.env['account.payment'].search([
                    ('name', 'like', move.name),
                    ('state', 'in', ['draft', 'posted'])
                ])
                
                # Combine và đếm unique payments
                all_payment_ids = set(reconciled_payments.ids + payments_by_name.ids)
                move.payment_count = len(all_payment_ids)
            else:
                move.payment_count = 0
    
    @api.depends('payment_count')
    def _compute_has_existing_payments(self):
        """Kiểm tra xem có phiếu thu không"""
        for move in self:
            move.has_existing_payments = move.payment_count > 0
    
    def action_view_payments(self):
        """Xem tất cả phiếu thu liên quan (bao gồm draft)"""
        self.ensure_one()
        
        # Tìm payments liên quan (bao gồm cả draft và posted)
        payments = self.env['account.payment'].search([
            ('name', 'like', self.name),
            ('state', 'in', ['draft', 'posted'])
        ])
        payments_reconcile = self.env['account.payment'].search([
            ('reconciled_invoice_ids', 'in', self.ids),
            ('state', 'in', ['draft', 'posted'])
        ])
        all_payments = payments | payments_reconcile
        
        if not all_payments:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không tìm thấy phiếu thu liên quan.',
                    'type': 'warning',
                }
            }
        
        # Mở danh sách payments
        action = {
            'type': 'ir.actions.act_window',
            'name': f'Phiếu thu - {self.name}',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_payments.ids)],
            'context': {'create': False},
        }
        
        if len(all_payments) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = all_payments.id
            
        return action

    @api.model_create_multi
    def create(self, vals_list):
        """Override create để gán người tạo hóa đơn làm người phụ trách"""
        for vals in vals_list:
            if not vals.get('dac_user_id'):
                vals['dac_user_id'] = self.env.user.id
        return super().create(vals_list)


    @api.model
    def _update_missing_dac_user_id(self):
        """Method để update các hóa đơn cũ chưa có dac_user_id"""
        moves_without_user = self.search([('dac_user_id', '=', False), ('move_type', '=', 'out_invoice')])
        if moves_without_user:
            _logger.info(f"Found {len(moves_without_user)} invoices without dac_user_id, updating...")
            # Set to admin user or first user found
            default_user = self.env.ref('base.user_admin', raise_if_not_found=False)
            if not default_user:
                default_user = self.env['res.users'].search([('active', '=', True)], limit=1)
            
            if default_user:
                moves_without_user.write({'dac_user_id': default_user.id})
                _logger.info(f"Updated {len(moves_without_user)} invoices with default user: {default_user.name}")
                # Commit ngay để đảm bảo data được lưu
                self.env.cr.commit()
            
        return len(moves_without_user)
    
    @api.model 
    def action_update_missing_dac_user_manual(self):
        """Action để chạy update manual từ UI"""
        result = self._update_missing_dac_user_id()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Cập nhật thành công',
                'message': f'Đã cập nhật {result} hóa đơn thiếu người phụ trách.',
                'type': 'success',
            }
        }

    def write(self, vals):
        """Override write để hook vào khi payment_state thay đổi"""
        result = super().write(vals)
        
        # CHỈ XỬ LÝ KHI payment_state THAY ĐỔI THÀNH 'paid' - tối ưu performance
        if vals.get('payment_state') == 'paid':
            # BATCH PROCESSING: Xử lý tất cả invoices cùng lúc
            paid_invoices = self.filtered(lambda m: m.move_type == 'out_invoice' and m.invoice_origin)
            
            if paid_invoices:
                # GROUP BY order để giảm số lần search database
                order_groups = {}
                for move in paid_invoices:
                    if move.invoice_origin not in order_groups:
                        order_groups[move.invoice_origin] = []
                    order_groups[move.invoice_origin].append(move)
                
                # BULK SEARCH: Tìm tất cả orders cùng lúc
                order_names = list(order_groups.keys())
                sale_orders = self.env['sale.order'].search([('name', 'in', order_names)])
                order_dict = {order.name: order for order in sale_orders}
                
                # Process từng order group
                for order_name, invoices in order_groups.items():
                    sale_order = order_dict.get(order_name)
                    if not sale_order:
                        continue
                        
                    _logger.info(f"WRITE HOOK OPTIMIZED: Processing {len(invoices)} invoices for order {order_name}")
                    
                    # Phân loại invoices
                    deposit_invoices = [inv for inv in invoices if inv.dac_deposit_invoice]
                    final_invoices = [inv for inv in invoices if not inv.dac_deposit_invoice]
                    
                    order_updated = False
                    
                    # Xử lý deposit invoices
                    if deposit_invoices:
                        existing_deposit_line = sale_order.order_line.filtered(
                            lambda l: not l.display_type and l.price_unit < 0
                        )
                        
                        if not existing_deposit_line:
                            # Chỉ thêm từ invoice đầu tiên
                            deposit_inv = deposit_invoices[0]
                            _logger.info(f"WRITE HOOK OPTIMIZED: Adding deposit line for order {order_name}")
                            deposit_amount = abs(deposit_inv.amount_total)
                            sale_order.add_deposit_order_line(deposit_amount, invoice=deposit_inv)
                            order_updated = True
                    
                    # Xử lý final invoices - CHỈ GỌI KHI THỰC SỰ CÓ HÓA ĐƠN CUỐI
                    if final_invoices:
                        # KIỂM TRA THÊM: Đảm bảo không phải chỉ có deposit invoice
                        all_invoices = self.env['account.move'].search([
                            ('move_type', '=', 'out_invoice'),
                            ('invoice_origin', '=', order_name),
                            ('state', '=', 'posted')
                        ])
                        non_deposit_invoices = all_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
                        
                        if non_deposit_invoices:
                            _logger.info(f"WRITE HOOK OPTIMIZED: Final invoice paid for order {order_name}")
                            sale_order.check_and_update_completion_status()
                            order_updated = True
                        else:
                            _logger.info(f"WRITE HOOK OPTIMIZED: Only deposit invoice paid for order {order_name}, not calling completion check")
                            sale_order.check_and_update_completion_status()   # NEW
                            order_updated = True                              # NEW
                    
                    # CHỈ INVALIDATE MỘT LẦN cho mỗi order
                    if order_updated:
                        sale_order.invalidate_recordset()
                
                # CHỈ COMMIT MỘT LẦN sau khi xử lý tất cả
                self.env.cr.commit()
                _logger.info(f"WRITE HOOK OPTIMIZED: Committed all changes for {len(order_groups)} orders")
        
        return result

    def action_register_payment(self):
        """Override để hook vào payment process và refresh view đơn hàng"""
        _logger.info(f"action_register_payment được gọi cho invoice {self.name}")
        
        # Lưu thông tin đơn hàng liên quan trước khi thanh toán
        related_order = None
        if self.invoice_origin:
            related_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
            if related_order:
                _logger.info(f"Tìm thấy đơn hàng liên quan: {related_order.name}")
        
        # Gọi phương thức gốc để hiển thị wizard thanh toán
        result = super().action_register_payment()
        
        # Sau khi wizard payment hiển thị, lên lịch kiểm tra để refresh view khi payment hoàn tất
        if related_order:
            # Trigger cron job để kiểm tra và cập nhật trạng thái
            self.env.ref('dac_erp.ir_cron_check_all_orders_payment').sudo().method_direct_trigger()
            
            # Thêm callback để refresh view sau khi payment hoàn tất
            if isinstance(result, dict) and result.get('type') == 'ir.actions.act_window':
                # Thêm context để biết cần refresh view sau khi thanh toán
                result.setdefault('context', {})
                result['context']['refresh_order_view'] = True
                result['context']['order_id'] = related_order.id
                result['context']['order_name'] = related_order.name
                _logger.info(f"Đã thêm context refresh_order_view cho đơn hàng {related_order.name}")
            
        return result

    def _register_payment(self, payment_line, writeoff_line=False):
        """Override payment registration để bắt được thời điểm thanh toán"""
        result = super()._register_payment(payment_line, writeoff_line)
        
        _logger.info(f"_register_payment được gọi cho invoice {self.name}")
        
        # Kiểm tra ngay sau khi register payment cho cả hóa đơn cọc và hóa đơn thanh toán cuối
        if self.invoice_origin:
            _logger.info(f"Payment registered cho invoice {self.name}, checking auto-add deposit line hoặc complete order")
            
            # COMMIT trước để đảm bảo payment được save
            self.env.cr.commit()
            
            # IMMEDIATE CHECK thay vì delayed check
            try:
                # INVALIDATE CACHE và re-browse để lấy payment_state mới nhất
                self.invalidate_recordset(['payment_state'])
                invoice_fresh = self.env['account.move'].browse(self.id)
                _logger.info(f"IMMEDIATE CHECK: payment_state của {invoice_fresh.name} = {invoice_fresh.payment_state}")
                invoice_fresh._check_and_add_deposit_after_payment()
            except Exception as e:
                _logger.error(f"Lỗi trong immediate check cho {self.name}: {e}")
            
        return result

    def _check_and_add_deposit_after_payment(self):
        """Kiểm tra và thêm dòng đặt cọc ngay sau khi thanh toán - OPTIMIZED"""
        self.ensure_one()
        
        # CHỈ XỬ LÝ KHI THỰC SỰ CẦN - tối ưu performance
        if self.payment_state != 'paid' or not self.invoice_origin:
            return
            
        # Tìm order một lần duy nhất
        sale_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
        if not sale_order:
            return
            
        _logger.info(f"OPTIMIZED CHECK: Processing invoice {self.name} for order {sale_order.name}")
        
        if self.dac_deposit_invoice:
            # Hóa đơn cọc - kiểm tra nhanh đã có dòng cọc chưa
            existing_deposit_line = sale_order.order_line.filtered(
                lambda l: not l.display_type and l.price_unit < 0
            )
            
            if not existing_deposit_line:
                _logger.info(f"OPTIMIZED CHECK: Adding deposit line for order {sale_order.name}")
                deposit_amount = abs(self.amount_total)
                sale_order.add_deposit_order_line(deposit_amount, invoice=self)
                # CHỈ INVALIDATE MỘT LẦN
                sale_order.invalidate_recordset()
                self.env.cr.commit()
        else:
            # Hóa đơn cuối - CHỈ GỌI KHI THỰC SỰ CÓ HÓA ĐƠN CUỐI (không chỉ deposit)
            _logger.info(f"OPTIMIZED CHECK: Final invoice paid for order {sale_order.name}")
            # KIỂM TRA THÊM: Đảm bảo thực sự có hóa đơn cuối
            all_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', self.invoice_origin),
                ('state', '=', 'posted')
            ])
            non_deposit_invoices = all_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
            
            if non_deposit_invoices:
                try:
                    sale_order.check_and_update_completion_status()
                    self.env.cr.commit()
                except Exception as e:
                    _logger.error(f"OPTIMIZED CHECK: Error updating completion: {e}")
            else:
                _logger.info(f"OPTIMIZED CHECK: Only deposit invoice exists for order {sale_order.name}, not calling completion check")

    @api.model
    def _cron_check_deposit_payments(self):
        """OPTIMIZED Cron job - Batch processing để tối ưu performance"""
        _logger.info("=== OPTIMIZED CRON: Batch checking deposit payments ===")
        
        # STEP 1: BULK SEARCH - Tìm tất cả paid deposit invoices cùng lúc
        paid_deposit_invoices = self.search([
            ('dac_deposit_invoice', '=', True),
            ('payment_state', '=', 'paid'),
            ('invoice_origin', '!=', False)
        ])
        
        if not paid_deposit_invoices:
            _logger.info("OPTIMIZED CRON: No paid deposit invoices found")
            return {'refreshed_orders': [], 'total_deposit_invoices': 0, 'total_orders_checked': 0}
        
        # STEP 2: BULK SEARCH orders - Tìm tất cả orders cùng lúc
        order_names = paid_deposit_invoices.mapped('invoice_origin')
        sale_orders = self.env['sale.order'].search([('name', 'in', order_names)])
        order_dict = {order.name: order for order in sale_orders}
        
        # STEP 3: BATCH PROCESSING - Xử lý theo batch
        orders_updated = []
        orders_to_update = []
        
        for invoice in paid_deposit_invoices:
            sale_order = order_dict.get(invoice.invoice_origin)
            if not sale_order:
                continue
                
            # Kiểm tra đã có dòng đặt cọc chưa
            existing_deposit_line = sale_order.order_line.filtered(
                lambda l: not l.display_type and l.price_unit < 0
            )
            
            if not existing_deposit_line:
                _logger.info(f"OPTIMIZED CRON: Adding deposit line for order {sale_order.name}")
                deposit_amount = abs(invoice.amount_total)
                sale_order.add_deposit_order_line(deposit_amount, invoice=invoice)
                orders_to_update.append(sale_order)
        
        # STEP 4: BULK UPDATE completion status cho orders có final invoices paid
        final_paid_invoices = self.search([
            ('dac_deposit_invoice', '=', False),
            ('payment_state', '=', 'paid'),
            ('invoice_origin', 'in', order_names),
            ('move_type', '=', 'out_invoice')
        ])
        
        final_order_names = final_paid_invoices.mapped('invoice_origin')
        final_orders = [order_dict[name] for name in final_order_names if name in order_dict]
        
        for order in final_orders:
            if not order.is_order_completed:
                # Kiểm tra nhanh có final invoice paid không
                if any(inv.invoice_origin == order.name and not inv.dac_deposit_invoice 
                       and inv.payment_state == 'paid' for inv in final_paid_invoices):
                    order.is_order_completed = True
                    orders_updated.append(order.name)
                    orders_to_update.append(order)
        
        # STEP 5: BULK INVALIDATE và COMMIT một lần duy nhất
        if orders_to_update:
            # Remove duplicates
            unique_orders = list(set(orders_to_update))
            for order in unique_orders:
                order.invalidate_recordset()
            
            # Single commit for all changes
            self.env.cr.commit()
            _logger.info(f"OPTIMIZED CRON: Bulk updated {len(unique_orders)} orders")
        
        _logger.info(f"=== OPTIMIZED CRON COMPLETED: {len(orders_updated)} orders updated ===")
        
        return {
            'refreshed_orders': orders_updated,
            'total_deposit_invoices': len(paid_deposit_invoices),
            'total_orders_checked': len(sale_orders)
        }

    def action_post(self):
        """Override để set is_payment_confirmed khi hóa đơn thanh toán cuối được confirm"""
        result = super().action_post()
        
        # Chỉ set is_payment_confirmed khi hóa đơn được confirm - hoàn thành đơn hàng chờ thanh toán
        for move in self:
            if move.move_type == 'out_invoice' and move.invoice_origin and not move.dac_deposit_invoice:
                # Đây là hóa đơn thanh toán cuối (không phải cọc)
                sale_orders = self.env['sale.order'].search([
                    ('name', '=', move.invoice_origin)
                ])
                for order in sale_orders:
                    # Set is_payment_confirmed khi hóa đơn được confirm (để kích hoạt tiến trình thanh toán)
                    if not order.is_payment_confirmed:
                        order.is_payment_confirmed = True
                        _logger.info(f"Đơn hàng {order.name} được đánh dấu đã xác nhận thanh toán khi confirm hóa đơn {move.name}")
                    
                    # KHÔNG set is_order_completed ở đây - chờ thanh toán thực tế
        
        return result

    @api.model
    def action_refresh_order_after_payment(self, order_id):
        """Action để refresh view đơn hàng sau khi thanh toán"""
        try:
            sale_order = self.env['sale.order'].browse(order_id)
            if sale_order.exists():
                # Force refresh tất cả computed fields
                sale_order._compute_all_invoices_paid()
                sale_order._compute_has_paid_final_invoice()
                sale_order._compute_remaining_amount_display()
                sale_order._compute_total_deposit_paid()
                sale_order.invalidate_recordset()
                
                # Kiểm tra và cập nhật trạng thái hoàn thành
                sale_order.check_and_update_completion_status()
                
                _logger.info(f"Đã refresh view cho đơn hàng {sale_order.name}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                _logger.warning(f"Không tìm thấy đơn hàng với ID {order_id}")
                
        except Exception as e:
            _logger.error(f"Lỗi khi refresh view đơn hàng {order_id}: {e}")
            
        return {'type': 'ir.actions.act_window_close'}

    def action_back_to_sale_order(self):
        """Quay về đơn hàng - smart redirect với access check"""
        self.ensure_one()
        if self.invoice_origin:
            sale_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
            if sale_order:
                user = self.env.user
                
                # KIỂM TRA QUYỀN TRUY CẬP TRƯỚC KHI REDIRECT
                if (user.has_group('dac_erp.group_dac_erp_design') or 
                    user.has_group('dac_erp.group_dac_erp_production')) and \
                   not (user.has_group('dac_erp.group_dac_erp_manager') or 
                        user.has_group('dac_erp.group_dac_erp_sale') or
                        user.has_group('base.group_system')):
                    
                    # Check xem user có quyền truy cập đơn hàng này không
                    can_access = False
                    if user.has_group('dac_erp.group_dac_erp_design'):
                        can_access = (sale_order.user_id_design == user)
                    elif user.has_group('dac_erp.group_dac_erp_production'):
                        can_access = (sale_order.user_id_production == user or user in sale_order.production_group_ids)
                    
                    if not can_access:
                        # User không có quyền → redirect về menu action với URL trực tiếp
                        _logger.warning(f"ACCESS DENIED: User {user.name} (ID: {user.id}) tried to access order {sale_order.name} but not assigned")
                        
                        # Hiển thị thông báo qua bus
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'type': 'warning',
                                'title': '⛔ Không có quyền truy cập',
                                'message': f'Đơn hàng {sale_order.name} không được phân công cho bạn.\n\nVui lòng liên hệ Sale phụ trách.',
                                'sticky': False,
                            }
                        )
                        
                        # Redirect về menu phù hợp theo group
                        if user.has_group('dac_erp.group_dac_erp_design'):
                            menu = self.env.ref('dac_erp.dac_sale_order_menu_design_only')
                        elif user.has_group('dac_erp.group_dac_erp_production'):
                            menu = self.env.ref('dac_erp.dac_sale_order_menu_production_only')
                        else:
                            # Fallback: redirect về root menu "Đang sản xuất"
                            menu = self.env.ref('dac_erp.dac_design_root_menu')
                        
                        return {
                            'type': 'ir.actions.act_url',
                            'url': f'/web#menu_id={menu.id}',
                            'target': 'self',
                        }
                    
                    # User có quyền → redirect về form view với action context đúng theo group
                    if user.has_group('dac_erp.group_dac_erp_design'):
                        action = self.env.ref('dac_erp.dac_sale_order_action_design_only')
                    elif user.has_group('dac_erp.group_dac_erp_production'):
                        action = self.env.ref('dac_erp.dac_sale_order_action_production_only')
                    else:
                        # Manager/Sale/Admin - dùng action manager
                        action = self.env.ref('dac_erp.dac_sale_order_manager_action')
                    
                    form_view = self.env.ref('dac_erp.dac_sale_order_custom_view_form')
                    
                    return {
                        'type': 'ir.actions.act_window',
                        'name': 'Đơn hàng',
                        'res_model': 'sale.order',
                        'view_mode': 'form',
                        'views': [(form_view.id, 'form')],
                        'res_id': sale_order.id,
                        'target': 'current',
                        'context': dict(action.context or {}, **{
                            'form_view_initial_mode': 'edit',
                        }),
                    }
                else:
                    # Manager/Sale/Admin → normal form view
                    form_view = self.env.ref('dac_erp.dac_sale_order_custom_view_form')
                    return {
                        'type': 'ir.actions.act_window',
                        'name': 'Đơn hàng',
                        'res_model': 'sale.order',
                        'view_mode': 'form',
                        'views': [(form_view.id, 'form')],
                        'res_id': sale_order.id,
                        'target': 'current',
                    }
        return {'type': 'ir.actions.act_window_close'}