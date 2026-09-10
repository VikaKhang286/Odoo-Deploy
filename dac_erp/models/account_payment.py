# -*- coding: utf-8 -*-

from odoo import models, fields, api

class AccountPayment(models.Model):
    _inherit = 'account.payment'
    
    # Computed fields để hiển thị thông tin liên quan
    related_invoice_count = fields.Integer(string='Số hóa đơn', compute='_compute_related_invoice_count')
    has_sale_order = fields.Boolean(string='Có đơn hàng', compute='_compute_has_sale_order')
    is_fully_reconciled = fields.Boolean(string='Đã reconcile', compute='_compute_is_fully_reconciled')
    has_unreconciled_invoices = fields.Boolean(string='Có hóa đơn chưa reconcile', compute='_compute_has_unreconciled_invoices')
    
    @api.depends('name', 'reconciled_invoice_ids')
    def _compute_related_invoice_count(self):
        """Tính số hóa đơn liên quan"""
        for payment in self:
            count = len(payment.reconciled_invoice_ids)
            if not count and payment.name:
                # Tìm theo name field
                invoices = self.env['account.move'].search([
                    ('name', 'like', payment.name),
                    ('move_type', '=', 'out_invoice')
                ])
                count = len(invoices)
            payment.related_invoice_count = count
    
    @api.depends('name', 'reconciled_invoice_ids')
    def _compute_has_sale_order(self):
        """Kiểm tra xem có đơn hàng liên quan không"""
        for payment in self:
            has_order = False
            
            # Kiểm tra qua reconciled_invoice_ids trước
            for invoice in payment.reconciled_invoice_ids:
                if invoice.invoice_origin:
                    sale_order = self.env['sale.order'].search([
                        ('name', '=', invoice.invoice_origin)
                    ], limit=1)
                    if sale_order:
                        has_order = True
                        break
            
            # Nếu chưa có, kiểm tra qua name field
            if not has_order and payment.name:
                invoices = self.env['account.move'].search([
                    ('name', 'like', payment.name),
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '!=', False)
                ])
                for invoice in invoices:
                    sale_order = self.env['sale.order'].search([
                        ('name', '=', invoice.invoice_origin)
                    ], limit=1)
                    if sale_order:
                        has_order = True
                        break
            
            payment.has_sale_order = has_order
    
    @api.depends('state', 'is_matched')
    def _compute_is_fully_reconciled(self):
        """Kiểm tra xem payment đã được reconcile hoàn toàn chưa"""
        for payment in self:
            # Payment được coi là reconciled nếu nó đã matched hoặc có reconciled_invoice_ids
            payment.is_fully_reconciled = payment.is_matched or bool(payment.reconciled_invoice_ids)
    
    @api.depends('name', 'state')
    def _compute_has_unreconciled_invoices(self):
        """Kiểm tra xem có hóa đơn chưa reconcile không"""
        for payment in self:
            if payment.state == 'posted' and payment.name:
                # Tìm các hóa đơn liên quan chưa thanh toán hoàn toàn
                unreconciled_invoices = self.env['account.move'].search([
                    ('name', 'like', payment.name),
                    ('move_type', '=', 'out_invoice'),
                    ('payment_state', 'in', ['not_paid', 'partial'])
                ])
                payment.has_unreconciled_invoices = bool(unreconciled_invoices)
            else:
                payment.has_unreconciled_invoices = False
    
    def debug_payment_reconcile_info(self):
        """Debug method để kiểm tra thông tin reconcile"""
        self.ensure_one()
        
        info = {
            'payment_name': self.name,
            'payment_state': self.state,
            'is_fully_reconciled': self.is_fully_reconciled,
            'has_unreconciled_invoices': self.has_unreconciled_invoices,
            'reconciled_invoice_ids': self.reconciled_invoice_ids.mapped('name'),
        }
        
        # Tìm invoices liên quan
        related_invoices = self.env['account.move'].search([
            ('name', 'like', self.name),
            ('move_type', '=', 'out_invoice')
        ])
        
        info['related_invoices'] = [(inv.name, inv.payment_state) for inv in related_invoices]
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug Payment Info',
                'message': f'{info}',
                'type': 'info',
                'sticky': True
            }
        }
    
    def action_reconcile_payments(self):
        """Reconcile payment với invoices liên quan"""
        self.ensure_one()
        
        if self.state != 'posted':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Chỉ có thể reconcile payments đã được xác nhận.',
                    'type': 'warning',
                }
            }
        
        # Tìm invoices liên quan qua name field
        related_invoices = self.env['account.move'].search([
            ('name', 'like', self.name),
            ('move_type', '=', 'out_invoice'),
            ('payment_state', '!=', 'paid')
        ])
        
        if not related_invoices:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không tìm thấy hóa đơn chưa thanh toán để liên kết.',
                    'type': 'warning',
                }
            }
        
        # Nếu chỉ có 1 invoice, tự động reconcile
        if len(related_invoices) == 1:
            invoice = related_invoices[0]
            return self._auto_reconcile_with_invoice(invoice)
        
        # Nếu có nhiều invoices, hiển thị wizard để chọn
        return {
            'type': 'ir.actions.act_window',
            'name': f'Chọn hóa đơn để liên kết - {self.name}',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', related_invoices.ids)],
            'target': 'new',
            'context': {
                'payment_to_reconcile': self.id,
                'create': False
            }
        }
    
    def _auto_reconcile_with_invoice(self, invoice):
        """Tự động reconcile payment với invoice"""
        try:
            # Tìm receivable line của invoice
            invoice_line = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )
            
            # Tìm receivable line của payment thông qua move_id
            if self.move_id:
                payment_line = self.move_id.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                )
            else:
                payment_line = self.env['account.move.line']
            
            if invoice_line and payment_line:
                # Thực hiện reconcile
                (invoice_line + payment_line).reconcile()
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thành công',
                        'message': f'Đã liên kết thanh toán {self.name} với hóa đơn {invoice.name}',
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Lỗi',
                        'message': 'Không thể tìm thấy dòng để reconcile. Vui lòng kiểm tra lại.',
                        'type': 'warning',
                    }
                }
                
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': f'Lỗi khi reconcile: {str(e)}',
                    'type': 'danger',
                }
            }
    
    def action_view_related_invoices(self):
        """Xem tất cả hóa đơn liên quan"""
        self.ensure_one()
        
        # Tìm invoices liên quan
        invoices = self.reconciled_invoice_ids
        if not invoices and self.name:
            invoices = self.env['account.move'].search([
                ('name', 'like', self.name),
                ('move_type', '=', 'out_invoice')
            ])
        
        if not invoices:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không tìm thấy hóa đơn liên quan.',
                    'type': 'warning',
                }
            }
        
        action = {
            'type': 'ir.actions.act_window',
            'name': f'Hóa đơn liên quan - {self.name}',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'context': {'create': False},
        }
        
        if len(invoices) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = invoices.id
            
        return action

    def action_back_to_sale_order(self):
        """
        Quay về đơn hàng liên quan - smart redirect với access check
        """
        self.ensure_one()
        
        # Cách 1: Tìm qua reconciled_invoice_ids (chính xác nhất)
        for invoice in self.reconciled_invoice_ids:
            if invoice.invoice_origin:
                sale_order = self.env['sale.order'].search([
                    ('name', '=', invoice.invoice_origin)
                ], limit=1)
                if sale_order:
                    user = self.env.user
                    
                    # KIỂM TRA QUYỀN TRUY CẬP
                    if (user.has_group('dac_erp.group_dac_erp_design') or 
                        user.has_group('dac_erp.group_dac_erp_production')) and \
                       not (user.has_group('dac_erp.group_dac_erp_manager') or 
                            user.has_group('dac_erp.group_dac_erp_sale') or
                            user.has_group('base.group_system')):
                        
                        # Check access rights
                        can_access = False
                        if user.has_group('dac_erp.group_dac_erp_design'):
                            can_access = (sale_order.user_id_design == user)
                        elif user.has_group('dac_erp.group_dac_erp_production'):
                            can_access = (sale_order.user_id_production == user or user in sale_order.production_group_ids)
                        
                        if not can_access:
                            # User không có quyền → redirect về menu action với URL trực tiếp
                            import logging
                            _logger = logging.getLogger(__name__)
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
                        
                        # Có quyền → redirect về form view với action đúng theo group
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
                            'name': f'Đơn hàng - {sale_order.name}',
                            'view_mode': 'form',
                            'views': [(form_view.id, 'form')],
                            'res_model': 'sale.order',
                            'res_id': sale_order.id,
                            'target': 'current',
                        }
        
        # Cách 2: Tìm qua name field (fallback)
        if self.name:
            invoices = self.env['account.move'].search([
                ('name', 'like', self.name),
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '!=', False)
            ])
            
            for invoice in invoices:
                sale_order = self.env['sale.order'].search([
                    ('name', '=', invoice.invoice_origin)
                ], limit=1)
                if sale_order:
                    return {
                        'type': 'ir.actions.act_window',
                        'name': f'Đơn hàng - {sale_order.name}',
                        'view_mode': 'form',
                        'res_model': 'sale.order',
                        'res_id': sale_order.id,
                        'target': 'current',
                    }
        
        # Cách 3: Tìm qua memo field (fallback cuối)
        if self.memo:
            invoice_parts = self.memo.split('/')
            if len(invoice_parts) >= 3 and invoice_parts[0] == 'INV':
                invoice_name = self.memo
                
                invoice = self.env['account.move'].search([
                    ('name', '=', invoice_name),
                    ('move_type', 'in', ['out_invoice', 'out_refund'])
                ], limit=1)
                
                if invoice and invoice.invoice_origin:
                    sale_order = self.env['sale.order'].search([
                        ('name', '=', invoice.invoice_origin)
                    ], limit=1)
                    
                    if sale_order:
                        return {
                            'type': 'ir.actions.act_window',
                            'name': f'Đơn hàng - {sale_order.name}',
                            'view_mode': 'form',
                            'res_model': 'sale.order',
                            'res_id': sale_order.id,
                            'target': 'current',
                        }
        
        # Nếu không tìm thấy, hiển thị thông báo
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thông báo',
                'message': 'Không tìm thấy đơn hàng liên quan.',
                'type': 'warning',
            }
        }
