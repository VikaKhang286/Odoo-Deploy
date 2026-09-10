# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)

class PancakeSyncHelper(models.TransientModel):
    """Helper model to sync pancake_id for existing users and partners"""
    _name = 'pancake.sync.helper'
    _description = 'Pancake Sync Helper'

    @api.model
    def sync_staff_from_messages(self):
        """
        Đồng bộ pancake_id cho res.users từ page.fm.message
        Tìm tất cả tin nhắn có staff_id_fm nhưng chưa có staff
        """
        _logger.info("🔄 Starting staff sync from messages...")
        Message = self.env['page.fm.message'].sudo()
        ResUsers = self.env['res.users'].sudo()
        
        # Tìm tin nhắn có staff_id_fm nhưng chưa gán staff
        messages = Message.search([
            ('staff_id_fm', '!=', False),
            ('staff', '=', False)
        ])
        
        updated_count = 0
        created_count = 0
        
        for msg in messages:
            staff_pancake_id = str(msg.staff_id_fm)
            
            # Tìm user theo pancake_id
            user = ResUsers.search([('pancake_id', '=', staff_pancake_id)], limit=1)
            
            if user:
                msg.write({'staff': user.id})
                updated_count += 1
            elif msg.staff_name_fm:
                # Tạo user mới
                try:
                    # Lấy company từ conversation
                    company_id = msg.conversation_id.page_fm_page_id.company_id.id if msg.conversation_id and msg.conversation_id.page_fm_page_id and msg.conversation_id.page_fm_page_id.company_id else self.env.company.id
                    
                    login = f"staff_{staff_pancake_id[:8]}"
                    user = ResUsers.create({
                        'name': msg.staff_name_fm,
                        'login': login,
                        'pancake_id': staff_pancake_id,
                        'company_id': company_id,
                        'company_ids': [(4, company_id)],
                        'groups_id': [(4, self.env.ref('sales_team.group_sale_salesman').id)],
                    })
                    msg.write({'staff': user.id})
                    created_count += 1
                    _logger.info(f"✅ Created user: {user.name} (pancake_id: {staff_pancake_id}, company: {company_id})")
                except Exception as e:
                    _logger.warning(f"⚠️ Failed to create user for message {msg.id}: {e}")
        
        _logger.info(f"✅ Staff sync complete: {updated_count} updated, {created_count} created")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': f'Updated {updated_count} messages, created {created_count} users',
                'type': 'success',
            }
        }

    @api.model
    def fix_missing_pancake_ids(self):
        """
        Fix users và partners thiếu pancake_id từ:
        - page.fm.message (staff_id_fm)
        - sale.order (pancake_order_id)
        """
        _logger.info("🔧 Fixing missing pancake_ids...")
        
        # Fix users from messages
        self.sync_staff_from_messages()
        
        # Fix partners from orders (pancake_customer_name, pancake_customer_phone)
        SaleOrder = self.env['sale.order'].sudo()
        Partner = self.env['res.partner'].sudo()
        
        orders = SaleOrder.search([
            ('pancake_order_id', '!=', False),
            ('partner_id', '!=', False)
        ])
        
        updated_partners = 0
        for order in orders:
            # Nếu partner chưa có pancake_id nhưng order có pancake_customer_fb_id
            if order.pancake_customer_fb_id and not order.partner_id.pancake_id:
                order.partner_id.write({'pancake_id': order.pancake_customer_fb_id})
                updated_partners += 1
        
        _logger.info(f"✅ Updated {updated_partners} partners with pancake_id from orders")
        
        return True
