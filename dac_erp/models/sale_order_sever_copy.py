import json
import logging

from collections import defaultdict
from datetime import timedelta
from itertools import groupby

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import (
    AccessError,
    RedirectWarning,
    UserError,
    ValidationError,
)
from odoo.fields import Command
from odoo.http import request
from odoo.osv import expression
from odoo.tools import (
    create_index,
    float_is_zero,
    format_amount,
    format_date,
    is_html_empty,
    SQL,
)
from odoo.tools.mail import html_keep_url

from odoo.addons.payment import utils as payment_utils

import requests # Cần cài đặt thư viện requests: pip install requests
from datetime import datetime
from odoo.exceptions import UserError
import os
import json

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    def _default_name(self):
        return 'Tạo đơn mới'

    #name = fields.Char(string='Số đơn', default='Tạo đơn mới')

    
    #Được copy từ trong code trên sever
    # --- Pancake Integration Fields ---
    pancake_order_id = fields.Char(string='Pancake Order ID', index=True, copy=False, readonly=True)
    pancake_system_id = fields.Char(string='Pancake System ID', copy=False, readonly=True)

    pancake_customer_name = fields.Char(string='Tên KH (Pancake)', copy=False, readonly=True)
    pancake_customer_phone = fields.Char(string='SĐT KH (Pancake)', copy=False, readonly=True)
    pancake_customer_fb_id = fields.Char(string='Facebook ID KH (Pancake)', copy=False, readonly=True)

    pancake_shipping_full_name = fields.Char(string='Tên người nhận (GH - Pancake)', copy=False, readonly=True)
    pancake_shipping_phone = fields.Char(string='SĐT người nhận (GH - Pancake)', copy=False, readonly=True)
    pancake_shipping_address = fields.Text(string='Địa chỉ GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_province = fields.Char(string='Tỉnh/Thành GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_district = fields.Char(string='Quận/Huyện GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_commune = fields.Char(string='Phường/Xã GH (Pancake)', copy=False, readonly=True)

    pancake_status_name = fields.Char(string='Trạng thái (Pancake Name)', copy=False, readonly=True)
    pancake_status_key = fields.Char(string='Trạng thái (Pancake Key)', copy=False, readonly=True)
    create_date_ = fields.Datetime(string='Ngày tạo (Pancake)', copy=False, readonly=True)
    pancake_updated_at = fields.Datetime(string='Ngày cập nhật (Pancake)', copy=False, readonly=True)
    pancake_order_source_name = fields.Char(string='Nguồn đơn (Pancake)', copy=False, readonly=True)
    pancake_page_name = fields.Char(string='Trang bán hàng (Pancake)', copy=False, readonly=True)
    pancake_order_link = fields.Char(string='Link đơn hàng (Pancake)', copy=False, readonly=True)

    pancake_items_length = fields.Integer(string='Số loại SP (Pancake)', copy=False, readonly=True)
    pancake_total_quantity = fields.Float(string='Tổng SL SP (Pancake)', copy=False, readonly=True)
    pancake_total_price = fields.Float(string='Tổng tiền hàng (Pancake)', copy=False, readonly=True)
    pancake_total_discount_amount = fields.Float(string='Tổng giảm giá (Pancake)', copy=False, readonly=True)
    pancake_shipping_fee = fields.Float(string='Phí vận chuyển (Pancake)', copy=False, readonly=True)
    pancake_surcharge = fields.Float(string='Phụ phí (Pancake)', copy=False, readonly=True)
    pancake_money_to_collect = fields.Float(string='Tiền cần thu (Pancake)', copy=False, readonly=True)
    pancake_prepaid = fields.Float(string='Đã trả trước (Pancake)', copy=False, readonly=True)
    pancake_order_currency_code = fields.Char(string='Mã Tiền tệ (Pancake)', copy=False, default='VND', readonly=True)

    pancake_note = fields.Text(string='Ghi chú ĐH (Pancake)', copy=False, readonly=True)
    pancake_note_print = fields.Text(string='Ghi chú in (Pancake)', copy=False, readonly=True)
    pancake_customer_note = fields.Text(string='Ghi chú KH (Pancake)', copy=False, readonly=True)
    
    pancake_creator_name = fields.Char(string='Người tạo ĐH (Pancake)', copy=False, readonly=True)
    pancake_assigning_seller_name = fields.Char(string='NV bán hàng (Pancake)', copy=False, readonly=True)

    last_sync_date = fields.Datetime(string='Ngày đồng bộ cuối', readonly=True, copy=False)
    pancake_raw_data = fields.Text(string="Dữ liệu thô JSON (Pancake)", readonly=True, copy=False)
    
    # Thêm trường boolean mới
    x_is_readonly = fields.Boolean(
        string="Is Form Readonly",
        compute='_compute_x_is_readonly',
        store=False  # Không cần lưu vào database
    )

    @api.depends('state')
    def _compute_x_is_readonly(self):
        """
        Trường này sẽ là True nếu state nằm trong danh sách các trạng thái cuối,
        khiến cho form trở thành chỉ đọc.
        """
        # Danh sách các trạng thái bạn muốn form bị khóa
        readonly_states = ['sale-staked', 'production', 'del-cons', 'debt', 'done']
        for order in self:
            if order.state in readonly_states:
                order.x_is_readonly = True
            else:
                order.x_is_readonly = False

    
    # --- Pancake Functions ---
    def action_open_pancake_link(self):
        self.ensure_one()
        if not self.pancake_order_link:
            raise UserError("Không có link đơn hàng Pancake.")

        return {
            'type': 'ir.actions.act_url',
            'url': self.pancake_order_link,
            'target': 'new',  # <-- Mở trong tab mới
        }

    @api.depends('state')
    def _compute_x_is_readonly(self):
        """
        Trường này sẽ là True nếu state nằm trong danh sách các trạng thái cuối,
        khiến cho form trở thành chỉ đọc.
        """
        # Danh sách các trạng thái bạn muốn form bị khóa
        readonly_states = ['sale-staked', 'production', 'del-cons', 'debt', 'done']
        for order in self:
            if order.state in readonly_states:
                order.x_is_readonly = True
            else:
                order.x_is_readonly = False
                
    
    #=== Pancake ===#

    # --- Helper methods to be implemented by you ---
    def _get_pancake_api_key(self):
        # Ví dụ: return self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        # Đây là placeholder, bạn cần triển khai logic thực tế
        param = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        if not param:
            raise UserError(_("Pancake API Key not configured in System Parameters (pancake.api_key)."))
        return param

    def _get_pancake_shop_id(self):
        # Ví dụ: return self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        # Đây là placeholder, bạn cần triển khai logic thực tế
        param = self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        if not param:
            raise UserError(_("Pancake Shop ID not configured in System Parameters (pancake.shop_id)."))
        return param

    def _get_pancake_status_to_odoo_state_mapping(self):
        # Ánh xạ key trạng thái Pancake (dạng số string) sang state của Odoo
        # Cần điều chỉnh dựa trên các status thực tế của Pancake
        # Ví dụ: '1': 'draft', '7': 'sale', '9': 'cancel', ...
        # pancake_status_key -> state
        return {
            # THÊM CÁC MAPPING CỤ THỂ CỦA BẠN VÀO ĐÂY
            # Ví dụ: 
            # '1': 'draft',  # Trạng thái mới chờ xử lý
            # '2': 'draft',  # Đã xác nhận thông tin
            # '3': 'draft', # Chờ lấy hàng
            # '7': 'sale',   # Hoàn thành (đã giao)
            # '8': 'cancel', # Khách hủy
            # '9': 'cancel', # Shop hủy
            # '10': 'sale', # Đã đối soát (nếu coi như hoàn thành)
            # '11': 'draft', # Đang vận chuyển
            # '12': 'cancel', # Chuyển hoàn
        }

    @api.model
    def action_sync_pancake_all_orders(self, *args, **kwargs):
        _logger.info("Starting Pancake orders synchronization for SaleOrder...")

        # Lấy thời điểm lần chạy cuối từ config
        param_key = 'pancake.last_sync_time'
        config_param = self.env['ir.config_parameter']
        last_sync_str = config_param.sudo().get_param(param_key)

        if last_sync_str:
            last_sync_time = datetime.strptime(last_sync_str, DEFAULT_SERVER_DATETIME_FORMAT)
            now = datetime.now()
            _logger.info(f"Last sync time: {last_sync_time}, Current time: {now}")

            if now - last_sync_time < timedelta(seconds=10):
                _logger.info("Too speed, please wait...")
                return {
                    'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': _('Pancake Sync'), 'message': _('Please wait at least 10 seconds between synchronizations.'), 'sticky': False, 'type': 'warning'}
                }

        # Cập nhật thời điểm chạy hiện tại
        now_str = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        config_param.sudo().set_param(param_key, now_str)

        # Đảm bảo self là một recordset hợp lệ để truy cập env và các phương thức
        if not self:
            self = self.env['sale.order'] # Khởi tạo một recordset rỗng nếu self không có

        api_key = self._get_pancake_api_key()
        shop_id = self._get_pancake_shop_id()

        Partner = self.env['res.partner']
        Product = self.env['product.product']
        CrmTag = self.env['crm.tag']
        ResUsers = self.env['res.users']
        ResCurrency = self.env['res.currency']
        CrmTeam = self.env['crm.team'] # Thêm model CRM Team

        status_mapping = self._get_pancake_status_to_odoo_state_mapping()

        # Cải thiện logic xác định company_id:
        # Lấy company_id từ context (nếu có), nếu không có, lấy từ công ty hiện tại của environment.
        # Nếu vẫn không có (ví dụ: môi trường global hoặc lỗi cấu hình), đặt là False để tìm kiếm các bản ghi không thuộc công ty nào.
        current_company_id = self.env.context.get('company_id')
        if current_company_id is None: # If not explicitly set in context
            if self.env.company: # If there's a company in the environment
                current_company_id = self.env.company.id
            else:
                current_company_id = False # No company, set to False for global records


        if current_company_id is False:
            company_domain_for_search = [('company_id', '=', False)]
        else:
            company_domain_for_search = ['|', ('company_id', '=', False), ('company_id', '=', current_company_id)]
       
        # Construct company_domain safely
        if current_company_id is False:
            # If current_company_id is False, search for records with company_id = False (global)
            company_domain = [('company_id', '=', False)]
        else:
            # If current_company_id is an integer, search for global records OR records of that company
            company_domain = ([ '|',('company_id', '=', False), ('company_id', '=', current_company_id)])

        all_orders_data = []
        current_page = 1
        limit_per_page_param = self.env['ir.config_parameter'].sudo().get_param('pancake.sync.limit_per_page', '50')
        try:
            limit_per_page = int(limit_per_page_param)
        except ValueError:
            limit_per_page = 50

        while True:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/orders?api_key={api_key}&page_size={limit_per_page}&page_number={current_page}"
            _logger.info(f"Calling Pancake API (Page {current_page}): {api_url.replace(api_key, '***REDACTED***')}")

            try:
                response = requests.get(api_url, timeout=120)
                response.raise_for_status()
                page_data = response.json()
            except requests.exceptions.Timeout:
                _logger.error(f"API call timed out for page {current_page}.")
                self.env.cr.commit() # Commit những gì đã xử lý trước đó
                raise UserError(_("Pancake API call timed out for page %s. Processed orders before timeout have been saved.") % current_page)
            except requests.exceptions.RequestException as e:
                _logger.error(f"API call failed for page {current_page}: {e}")
                self.env.cr.commit()
                raise UserError(_("Failed to connect to Pancake API on page %s: %s. Processed orders before error have been saved.") % (current_page, e))
            except ValueError as e: # JSONDecodeError
                _logger.error(f"Failed to decode JSON response for page {current_page}: {e}. Response text: {response.text[:500]}")
                self.env.cr.commit()
                raise UserError(_("Failed to parse response from Pancake API on page %s: %s. Processed orders before error have been saved.") % (current_page, e))

            orders_on_page = page_data.get('data', [])
            if not orders_on_page:
                break
            
            all_orders_data.extend(orders_on_page)
            
            if len(orders_on_page) < limit_per_page:
                break
            current_page += 1
            
        if not all_orders_data:
            _logger.info("No orders found in the API response after checking all pages.")
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Pancake Sync'), 'message': _('No orders found from Pancake API.'), 'sticky': False, 'type': 'warning'}
            }
        
        processed_count = 0
        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0

        # Lấy sản phẩm dịch vụ cho phí vận chuyển và phụ phí (tạo nếu chưa có)
        # Sử dụng domain rõ ràng cho company_id: False (global) hoặc company_id cụ thể
        # company_domain = expression.OR([('company_id', '=', False), ('company_id', '=', company_id)]) if company_id else [('company_id', '=', False)]

                # Lấy sản phẩm dịch vụ cho phí vận chuyển và phụ phí (tạo nếu chưa có)
        # Bạn nên tạo các sản phẩm này trong Odoo trước với default_code cố định
        # shipping_product = Product.search([('default_code', '=', 'DELIV_PANCAKE'), ('type', '=', 'service'), '|', ('company_id', '=', None), ('company_id', '=', company_id)], limit=1)
        # if not shipping_product:
        #     try:
        #         shipping_product = Product.create({
        #             'name': 'Phí vận chuyển (Pancake)', 'default_code': 'DELIV_PANCAKE', 'type': 'service',
        #             'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': company_id,
        #             'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
        #         })
        #         _logger.info("Created 'Phí vận chuyển (Pancake)' service product (DELIV_PANCAKE).")
        #     except Exception as e:
        #         _logger.error(f"Failed to create shipping product: {e}")
        #         shipping_product = False # Không thể tạo, sẽ bỏ qua thêm dòng này

        # domain = [
        #     ('default_code', '=', 'DELIV_PANCAKE'),
        #     ('type', '=', 'service'),
        #     # '|', ('company_id', '=', None), ('company_id', '=', company_id)
        # ]
        
        # # Chỉ thêm company_domain nếu nó không rỗng
        # if company_domain:
        #     domain += company_domain

        # shipping_product = Product.search(domain, limit=1)

        shipping_product = Product.search(([('default_code', '=', 'DELIV_PANCAKE'), ('type', '=', 'service')]+company_domain), limit=1)
        if not shipping_product:
            try:
                shipping_product = Product.create({
                    'name': 'Phí vận chuyển (Pancake)', 'default_code': 'DELIV_PANCAKE', 'type': 'service',
                    'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': current_company_id if current_company_id else False,
                    'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
                })
                _logger.info("Created 'Phí vận chuyển (Pancake)' service product (DELIV_PANCAKE).")
            except Exception as e:
                _logger.error(f"Failed to create shipping product: {e}")
                shipping_product = False

        surcharge_product = Product.search(([('default_code', '=', 'SURCH_PANCAKE'), ('type', '=', 'service')] +company_domain), limit=1)
        if not surcharge_product:
            try:
                surcharge_product = Product.create({
                    'name': 'Phụ phí (Pancake)', 'default_code': 'SURCH_PANCAKE', 'type': 'service',
                    'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': current_company_id if current_company_id else False,
                    'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
                })
                _logger.info("Created 'Phụ phí (Pancake)' service product (SURCH_PANCAKE).")
            except Exception as e:
                _logger.error(f"Failed to create surcharge product: {e}")
                surcharge_product = False

        for order_data in all_orders_data:
            p_order_id = str(order_data.get('id'))
            if not p_order_id:
                _logger.warning(f"Skipping order with missing ID in data: {str(order_data)[:200]}")
                skipped_count += 1
                continue

            if len(order_data.get('status_history', [])) == 0:
                _logger.info(f"Skipping Pancake Order ID {p_order_id} due to empty status history.")
                skipped_count += 1
                continue 

            try:
                # --- Creator ---
                creator_info = order_data.get('creator')
                odoo_creator = False # BẮT ĐẦU TỪ False thay vì self.env.user
                
                if creator_info:    
                    creator_pancake_id = str(creator_info.get('id')) if creator_info.get('id') else None
                    creator_name = creator_info.get('name')
                    creator_email = creator_info.get('email')
                    creator_phone = creator_info.get('phone_number')

                    # ƯU TIÊN 1: Tìm theo pancake_id (CHÍNH XÁC NHẤT)
                    if creator_pancake_id:
                        odoo_creator = ResUsers.sudo().search([('pancake_id', '=', creator_pancake_id)], limit=1)
                        if odoo_creator:
                            _logger.info(f"✅ Found creator by pancake_id: {creator_pancake_id} -> {odoo_creator.name}")
                    
                    # ƯU TIÊN 2: Tìm theo email/login
                    if not odoo_creator and creator_email:
                        odoo_creator = ResUsers.sudo().search([('login', '=', creator_email)], limit=1)
                        if odoo_creator:
                            _logger.info(f"Found creator by email: {creator_email} -> {odoo_creator.name}")
                            # Cập nhật pancake_id nếu chưa có
                            if creator_pancake_id and not odoo_creator.pancake_id:
                                odoo_creator.sudo().write({'pancake_id': creator_pancake_id})
                    
                    # ƯU TIÊN 3: Tìm theo tên
                    if not odoo_creator and creator_name:
                        odoo_creator = ResUsers.sudo().search([('name', '=ilike', creator_name), ('share', '=', False)], limit=1)
                        if odoo_creator:
                            _logger.info(f"Found creator by name: {creator_name} -> {odoo_creator.name}")
                            # Cập nhật pancake_id nếu chưa có
                            if creator_pancake_id and not odoo_creator.pancake_id:
                                odoo_creator.sudo().write({'pancake_id': creator_pancake_id})
                    
                    # CUỐI CÙNG: Tạo user mới nếu không tìm thấy
                    if not odoo_creator and creator_name:
                        _logger.info(f"Creating new Odoo user for Pancake creator: {creator_name} (pancake_id: {creator_pancake_id})")
                        try:
                            internal_group = self.env.ref('base.group_user')
                            odoo_creator = ResUsers.sudo().create({
                                'name': creator_name,
                                'login': creator_email if creator_email else f'pancake_{creator_pancake_id}',
                                'email': creator_email,
                                'phone': creator_phone,
                                'pancake_id': creator_pancake_id,  # LƯU PANCAKE_ID
                                'password': creator_email if creator_email else 'odoo_temp_pass',
                                'active': True,
                                'share': False,
                                'company_id': current_company_id if current_company_id else False,
                                'groups_id': [(6, 0, [internal_group.id])],
                            })
                            _logger.info(f"✅ Created user: {odoo_creator.name} with pancake_id: {creator_pancake_id}")
                        except Exception as e_user:
                            _logger.error(f"❌ Failed to create Odoo user for Pancake creator {creator_name}: {e_user}")
                
                # FALLBACK: Nếu vẫn không có creator, dùng user hiện tại
                if not odoo_creator:
                    odoo_creator = self.env.user
                    _logger.warning(f"⚠️ No creator found, using current user: {odoo_creator.name}")

                # ---- Salesperson (user_id) & Team (team_id) ---
                assigning_seller_info = order_data.get('assigning_seller')
                salesperson = False
                
                if isinstance(assigning_seller_info, dict):
                    p_seller_pancake_id = str(assigning_seller_info.get('id')) if assigning_seller_info.get('id') else None
                    p_assigning_seller_name = assigning_seller_info.get('name')
                    p_assigning_seller_email = assigning_seller_info.get('email')
                    p_assigning_seller_phone = assigning_seller_info.get('phone_number')
                    
                    # ƯU TIÊN 1: Tìm theo pancake_id
                    if p_seller_pancake_id:
                        salesperson = ResUsers.sudo().search([('pancake_id', '=', p_seller_pancake_id)], limit=1)
                        if salesperson:
                            _logger.info(f"✅ Found salesperson by pancake_id: {p_seller_pancake_id} -> {salesperson.name}")
                    
                    # ƯU TIÊN 2: Tìm theo email/login
                    if not salesperson and p_assigning_seller_email:
                        salesperson = ResUsers.sudo().search([('login', '=', p_assigning_seller_email), ('share', '=', False)], limit=1)
                        if salesperson:
                            _logger.info(f"Found salesperson by email: {p_assigning_seller_email} -> {salesperson.name}")
                            # Cập nhật pancake_id nếu chưa có
                            if p_seller_pancake_id and not salesperson.pancake_id:
                                salesperson.sudo().write({'pancake_id': p_seller_pancake_id})
                    
                    # ƯU TIÊN 3: Tìm theo tên
                    if not salesperson and p_assigning_seller_name:
                        salesperson = ResUsers.sudo().search([('name', '=ilike', p_assigning_seller_name), ('share', '=', False)], limit=1)
                        if salesperson:
                            _logger.info(f"Found salesperson by name: {p_assigning_seller_name} -> {salesperson.name}")
                            # Cập nhật pancake_id nếu chưa có
                            if p_seller_pancake_id and not salesperson.pancake_id:
                                salesperson.sudo().write({'pancake_id': p_seller_pancake_id})
                    
                    # CUỐI CÙNG: Tạo user mới
                    if not salesperson and p_assigning_seller_name:
                        _logger.info(f"Creating new Odoo user for Pancake salesperson: {p_assigning_seller_name} (pancake_id: {p_seller_pancake_id})")
                        try:
                            login_val = p_assigning_seller_email if p_assigning_seller_email else f'pancake_{p_seller_pancake_id}'
                            # Đảm bảo login duy nhất
                            existing_user_with_login = ResUsers.sudo().search([('login', '=', login_val)], limit=1)
                            if existing_user_with_login:
                                login_val = f"{login_val}_{p_seller_pancake_id}"

                            internal_group = self.env.ref('base.group_user')
                            salesperson = ResUsers.sudo().create({
                                'name': p_assigning_seller_name,
                                'login': login_val,
                                'email': p_assigning_seller_email,
                                'phone': p_assigning_seller_phone,
                                'pancake_id': p_seller_pancake_id,  # LƯU PANCAKE_ID
                                'password': p_assigning_seller_email if p_assigning_seller_email else 'odoo_temp_pass',
                                'company_id': current_company_id if current_company_id else False,
                                'active': True,
                                'share': False,
                                'groups_id': [(6, 0, [internal_group.id])],
                            })
                            _logger.info(f"✅ Created salesperson: {salesperson.name} with pancake_id: {p_seller_pancake_id}")
                        except Exception as e_saler:
                            _logger.error(f"❌ Failed to create Odoo user for Pancake salesperson {p_assigning_seller_name}: {e_saler}")
                            salesperson = False
                
                # === XÁC ĐỊNH user_id_val (Sale Person cho đơn hàng) ===
                # Ưu tiên 1: Người được gán bán hàng từ Pancake
                # Ưu tiên 2: Người tạo đơn trên Pancake
                # Ưu tiên 3: Người đồng bộ hiện tại
                if salesperson:
                    user_id_val = salesperson.id
                    _logger.info(f"✅ Using salesperson: {salesperson.name} (ID: {user_id_val})")
                elif odoo_creator:
                    user_id_val = odoo_creator.id
                    _logger.info(f"✅ Using creator as salesperson: {odoo_creator.name} (ID: {user_id_val})")
                else:
                    user_id_val = self.env.user.id
                    _logger.warning(f"⚠️ Using sync user as salesperson: {self.env.user.name} (ID: {user_id_val})")

                # TÌM HOẶC TẠO SALES TEAM dựa trên Salesperson nếu có
                final_team_id_val = False
                if user_id_val:
                    # Odoo thường có team mặc định hoặc team tự động tạo cho user
                    # Chúng ta có thể tìm team liên kết với user này hoặc team mặc định
                    sales_team = CrmTeam.search([
                         ('user_id', '=', user_id_val), # Team có user này là trưởng nhóm
                        # ('member_ids', 'in', user_id_val) # Hoặc user này là thành viên
                    ], limit=1)
                    
                    if not sales_team:
                        # Thử lấy team mặc định nếu có
                        sales_team = self.env.ref('sales_team.team_sales_department', raise_if_not_found=False)
                        if not sales_team:
                            # Tạo một sales team mới nếu không có team mặc định và không tìm thấy
                            _logger.info(f"Creating new Sales Team for salesperson ID: {user_id_val}")
                            sales_team = CrmTeam.create({
                                'name': f"Pancake Sales Team - {ResUsers.browse(user_id_val).name}",
                                'user_id': user_id_val, # Gán salesperson làm trưởng nhóm
                                'company_id': current_company_id if current_company_id else False,
                            })
                            _logger.info(f"Created sales team {sales_team.name} (ID: {sales_team.id})")
                    
                    if sales_team:
                        final_team_id_val = sales_team.id


                # --- Customer (partner_id) ---
                customer_info = order_data.get('customer', {})
                partner = False
                customer_id = customer_info.get('id')
                customer_phone_list = customer_info.get('phone_numbers', [])
                customer_phone = customer_phone_list[0] if customer_phone_list else None
                customer_email_list = customer_info.get('emails', [])
                customer_email = customer_email_list[0] if customer_email_list else None
                customer_name = customer_info.get('name')

                # Tìm kiếm partner theo phone (company_id = False hoặc company_id cụ thể)
                partner_domain_phone = ([('phone', '=', customer_phone)])
                if customer_phone:
                    partner = Partner.search(partner_domain_phone, limit=1)
                    # _logger.info(f"Tìm thấy partner theo phone: {customer_phone} cho Pancake order {p_order_id}")

                if not partner:
                    partner_domain_ID = ([('pancake_id', '=', customer_id)])
                    partner = Partner.search(partner_domain_ID, limit=1)

                    

                # Nếu chưa tìm thấy, tìm theo email
                if not partner and customer_email:
                    partner_domain_email = ([('email', '=ilike', customer_email)])
                    partner = Partner.search(partner_domain_email, limit=1)
                    _logger.info(f"Tìm thấy partner theo email: {customer_email} cho Pancake order {p_order_id}")
                
                # Nếu vẫn chưa tìm thấy và có tên & (phone hoặc email), tạo mới partner
                if not partner and customer_name and (customer_phone or customer_email):
                    _logger.info(f"Creating new partner: {customer_name} ({customer_phone or customer_email}) for Pancake order {p_order_id}")
                    partner_vals = {
                        'name': customer_name, 'phone': customer_phone, 'email': customer_email,
                        'company_type': 'person', 'company_id': current_company_id if current_company_id else False,
                    }
                    partner = Partner.create(partner_vals)
                    _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) Company: {partner.company_id} for Pancake order {p_order_id}")
                
                if not partner:
                    _logger.warning(f"Could not find or create customer for Pancake Order ID: {p_order_id}. Skipping order.")
                    skipped_count += 1
                    continue
                else:
                # In thông tin partner
                    _logger.info(f"Found or created partner: ID={partner.id}, Name={partner.name}, Email={partner.email}, Phone={partner.phone}")
                    partner.phone = customer_phone or partner.phone # Cập nhật phone nếu có từ Pancake
                    # Để in thông tin company, bạn cần truy cập nó thông qua partner
                    # Partner có trường company_id. Nếu partner là một công ty (is_company=True),
                    # thì company_id của nó chính là bản thân nó.
                    # Nếu partner là một cá nhân, company_id của nó có thể là công ty mà nó liên kết.
                    # Trong bối cảnh này, nếu bạn muốn biết công ty nào đang xử lý đơn hàng,
                    # đó thường là self.env.company.
                    
                    # In thông tin công ty hiện tại của môi trường (công ty Odoo đang hoạt động)
                    current_company = self.env.company
                    _logger.info(f"Current Odoo Company: ID={current_company.id}, Name={current_company.name}")

                    # Nếu bạn muốn thông tin công ty liên kết với đối tác (nếu có, thường là đối tác loại cá nhân)
                    if partner.company_id:
                        _logger.info(f"Partner's linked company: ID={partner.company_id.id}, Name={partner.company_id.name}")
                    elif partner.is_company: # Nếu đối tác là một công ty
                        _logger.info(f"Partner itself is a company: ID={partner.id}, Name={partner.name}")



                # --- Shipping Address (partner_shipping_id) ---
                shipping_address_info = order_data.get('shipping_address', {})
                partner_shipping_id = partner.id # Default to customer's main address
                
                sfn = shipping_address_info.get('full_name')
                sp = shipping_address_info.get('phone_number')
                s_addr = shipping_address_info.get('full_address')
                s_prov = shipping_address_info.get('province_name')
                s_dist = shipping_address_info.get('district_name')
                s_comm = shipping_address_info.get('commune_name') or shipping_address_info.get('commnue_name') # Fix typo in API data if any

                # Logic để xác định nếu địa chỉ giao hàng khác với địa chỉ chính của đối tác
                # Nếu tên người nhận hoặc số điện thoại hoặc địa chỉ khác, coi là địa chỉ phụ
                if sfn and (sfn != partner.name or (sp and sp != partner.phone) or s_addr and s_addr != partner.street):
                    shipping_contact_domain = [
                        ('parent_id', '=', partner.id), 
                        ('type', '=', 'delivery'),
                        ('name', '=', sfn),
                    ]
                    if sp:
                        shipping_contact_domain.append(('phone', '=', sp))
                    if s_addr:
                        shipping_contact_domain.append(('street', '=', s_addr))

                    shipping_contact = Partner.search(shipping_contact_domain, limit=1)
                    if not shipping_contact:
                        _logger.info(f"Creating new shipping contact for {sfn} for Pancake order {p_order_id}")
                        shipping_contact_vals = {
                            'name': sfn, 'parent_id': partner.id, 'type': 'delivery',
                            'phone': sp or partner.phone, # Ưu tiên SĐT người nhận GH, fallback về SĐT chính của partner
                            'street': s_addr, 
                            'city': s_dist, # Odoo 'city' thường là quận/huyện hoặc tỉnh/thành phố
                            # Có thể map province/district/commune sang các trường địa chỉ chuẩn của Odoo
                            # nếu có các module localization phù hợp, hoặc các trường tùy chỉnh (x_...)
                            # 'x_province': s_prov, # Ví dụ các trường tùy chỉnh nếu có
                            # 'x_district': s_dist,
                            # 'x_commune': s_comm,
                        }
                        shipping_contact = Partner.create(shipping_contact_vals)
                        _logger.info(f"Created shipping contact ID {shipping_contact.id} for Pancake order {p_order_id}")
                    partner_shipping_id = shipping_contact.id
                
                # --- Currency & Pricelist ---
                p_currency_code = order_data.get('order_currency', 'VND')
                currency = ResCurrency.search([('name', '=', p_currency_code)], limit=1)
                currency_id_val = currency.id if currency else self.env.company.currency_id.id
                
                

                pricelist = False
                if partner.company_id and partner.property_product_pricelist and \
                   partner.property_product_pricelist.currency_id.id == currency_id_val:
                    pricelist = partner.property_product_pricelist
                
                if not pricelist:
                    # Tìm pricelist theo currency và company
                    pricelist_domain = ([('currency_id', '=', currency_id_val)] + company_domain)
                    # Sắp xếp để ưu tiên pricelist của công ty hiện tại nếu có
                    pricelist = self.env['product.pricelist'].search(pricelist_domain, order='company_id desc, sequence, id', limit=1) 
                
                pricelist_id_val = pricelist.id if pricelist else False
                if not pricelist_id_val:
                    _logger.error(f"Pricelist not found for currency {p_currency_code} and company {current_company_id} for order {p_order_id}. Skipping order.")
                    try:
                        pricelist = self.env['product.pricelist'].sudo().create({
                            'name': f'Default {p_currency_code} Pricelist - {self.env.company.name if current_company_id else "Global"}',
                            'currency_id': currency_id_val,
                            'company_id': current_company_id if current_company_id else False,
                        })
                        _logger.info(f"Successfully created new pricelist '{pricelist.name}' (ID: {pricelist.id}) for order {p_order_id}.")
                    except Exception as e_pricelist:
                        _logger.error(f"Failed to create a default pricelist for order {p_order_id}: {e_pricelist}")
                        skipped_count += 1
                        continue # Không thể tiếp tục nếu không có bảng giá
                pricelist_id_val = pricelist.id

                # --- Datetimes ---
                p_inserted_at_dt = False
                inserted_at_str_from_api = order_data.get('inserted_at')
                if inserted_at_str_from_api:
                    try:
                        p_inserted_at_dt = datetime.strptime(inserted_at_str_from_api.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                    except Exception: 
                        _logger.warning(f"Could not parse inserted_at: {inserted_at_str_from_api} for order {p_order_id}")

                p_updated_at_dt = False
                updated_at_str_from_api = order_data.get('updated_at')
                if updated_at_str_from_api:
                    try:
                        p_updated_at_dt = datetime.strptime(updated_at_str_from_api.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                    except Exception:
                        _logger.warning(f"Could not parse updated_at: {updated_at_str_from_api} for order {p_order_id}")

                # --- Odoo Tags (crm.tag) ---
                odoo_tag_ids = []
                for tag_data in order_data.get('tags', []):
                    p_tag_name = tag_data.get('name')
                    if p_tag_name:
                        odoo_tag = CrmTag.search([('name', '=', p_tag_name)], limit=1)
                        if not odoo_tag:
                            try:
                                odoo_tag = CrmTag.create({'name': p_tag_name})
                                _logger.info(f"Created CRM Tag: {p_tag_name}")
                            except Exception as e_tag:
                                _logger.error(f"Failed to create CRM tag {p_tag_name}: {e_tag}")
                        if odoo_tag:
                            odoo_tag_ids.append(odoo_tag.id)
                
                # --- Status Mapping ---
                p_status_key = str(order_data.get('status'))
                odoo_state = status_mapping.get(p_status_key, 'draft')

                # --- Creator & Page Name ---
                p_creator_name = (order_data.get('creator').get('name') 
                                  if isinstance(order_data.get('creator'), dict) else None)
                p_page_name = (order_data.get('page').get('name')
                               if isinstance(order_data.get('page'), dict) else None)

                # --- Prepare Sale Order Values ---
                order_vals = {
                    'pancake_order_id': p_order_id,
                    'partner_id': partner.id,
                    'partner_shipping_id': partner_shipping_id,
                    'date_order': p_inserted_at_dt or fields.Datetime.now(), # Sử dụng thời gian hiện tại nếu không có
                    'state': odoo_state, # Initial state
                    'user_id': user_id_val,
                    'creator_id': odoo_creator.id,
                    'team_id': final_team_id_val,
                    'company_id': current_company_id if current_company_id else False,
                    'currency_id': currency_id_val,
                    'pricelist_id': pricelist_id_val,
                    'origin': f"Pancake: {p_order_id} - {order_data.get('order_sources_name', '')}".strip()[:64],
                    'client_order_ref': p_order_id,
                    'note': order_data.get('note'),
                    'tag_ids': [(6, 0, odoo_tag_ids)] if odoo_tag_ids else False,

                    'pancake_system_id': str(order_data.get('system_id')),
                    'pancake_customer_name': customer_name,
                    'pancake_customer_phone': customer_phone,
                    'pancake_customer_fb_id': customer_info.get('fb_id'),
                    'pancake_shipping_full_name': sfn,
                    'pancake_shipping_phone': sp,
                    'pancake_shipping_address': s_addr,
                    'pancake_shipping_province': s_prov,
                    'pancake_shipping_district': s_dist,
                    'pancake_shipping_commune': s_comm,
                    'pancake_status_name': order_data.get('status_name'),
                    'pancake_status_key': p_status_key,
                    'pancake_updated_at': p_updated_at_dt or fields.Datetime.now(),
                    'pancake_order_source_name': order_data.get('order_sources_name'),
                    'pancake_page_name': p_page_name,
                    'pancake_order_link': order_data.get('link_confirm_order'),
                    'pancake_items_length': order_data.get('items_length'),
                    'pancake_total_quantity': order_data.get('total_quantity'),
                    'pancake_total_price': order_data.get('total_price'),
                    'pancake_total_discount_amount': order_data.get('total_discount'),
                    'pancake_shipping_fee': order_data.get('shipping_fee'),
                    'pancake_surcharge': order_data.get('surcharge'),
                    'pancake_money_to_collect': order_data.get('money_to_collect') or order_data.get('cod'),
                    'pancake_prepaid': order_data.get('prepaid'),
                    'pancake_order_currency_code': p_currency_code,
                    'pancake_note': order_data.get('note'),
                    'pancake_note_print': order_data.get('note_print'),
                    'pancake_customer_note': ", ".join(cn_note.get('content', '') for cn_note in customer_info.get('notes', [])) if customer_info.get('notes') else None,
                    'pancake_creator_name': p_creator_name,
                    'pancake_assigning_seller_name': p_assigning_seller_name,
                    'last_sync_date': fields.Datetime.now(),
                    'pancake_raw_data': str(order_data),
                }
                
                existing_order = self.search([('pancake_order_id', '=', p_order_id), ('company_id', '=', current_company_id)], limit=1)
                current_sale_order = False
                order_line_commands = [] # Khởi tạo ở đây để dùng cho cả create và write

                # --- Order Lines (sale.order.line) ---
                for item_data in order_data.get('items', []):
                    p_item_name = item_data.get('variation_info', {}).get('name')
                    p_item_sku = str(item_data.get('variation_info', {}).get('sku')) or \
                                 str(item_data.get('variation_info',{}).get('display_id')) or \
                                 str(item_data.get('variation_id')) # Ưu tiên SKU
                    p_item_qty = item_data.get('quantity', 0.0)
                    p_item_price = item_data.get('variation_info', {}).get('retail_price', 0.0)
                    p_item_discount_val = item_data.get('total_discount', 0.0)

                    # LUÔN TẠO SẢN PHẨM MỚI từ Pancake (không search sản phẩm cũ)
                    product_variant = False
                    if p_item_name:
                        _logger.info(f"Creating new product {p_item_name} (SKU: {p_item_sku}) for Pancake order {p_order_id}")
                        try:
                            product_variant = Product.sudo().create({
                                'name': p_item_name, 
                                'default_code': p_item_sku if (p_item_sku and p_item_sku != 'None' and p_item_sku != '0') else False,
                                'type': 'product', 
                                'categ_id': self.env.ref('product.product_category_all').id,
                                'sale_ok': True, 
                                'purchase_ok': False, 
                                'lst_price': p_item_price,
                                'company_id': current_company_id,  # CRITICAL: Đã đảm bảo luôn có giá trị
                            })
                            _logger.info(f"Created product {product_variant.name} (SKU: {product_variant.default_code}) for order {p_order_id}")
                        except Exception as e_prod:
                            _logger.error(f"Failed to create product {p_item_name} (SKU: {p_item_sku}): {e_prod}")
                            product_variant = False # Set to False if creation failed
                    
                    if not product_variant:
                        _logger.warning(f"Product not found/created for Pancake item '{p_item_name}' (SKU: {p_item_sku}) in order {p_order_id}. Skipping line.")
                        continue

                    line_discount_percentage = 0.0
                    if p_item_price * p_item_qty > 0: # Tránh chia cho 0
                        line_discount_percentage = min(max((p_item_discount_val / (p_item_price * p_item_qty)) * 100, 0.0), 100.0)

                    line_vals = {
                        'product_id': product_variant.id,
                        'name': product_variant.get_product_multiline_description_sale(),
                        'product_uom_qty': p_item_qty,
                        'price_unit': p_item_price,
                        'discount': line_discount_percentage,
                        'product_uom': product_variant.uom_id.id,
                        'company_id': current_company_id,  # Đã đảm bảo current_company_id luôn có giá trị
                    }
                    order_line_commands.append(Command.create(line_vals))

                # --- Add Shipping Fee as Order Line ---
                p_shipping_fee = order_data.get('shipping_fee', 0.0)
                if p_shipping_fee > 0 and shipping_product:
                    order_line_commands.append(Command.create({
                        'product_id': shipping_product.id,
                        'name': shipping_product.name,
                        'product_uom_qty': 1,
                        'price_unit': p_shipping_fee,
                        'is_delivery': True,
                        'company_id': current_company_id,  # Đã đảm bảo current_company_id luôn có giá trị
                    }))

                # --- Add Surcharge as Order Line ---
                p_surcharge_val = order_data.get('surcharge', 0.0)
                if p_surcharge_val > 0 and surcharge_product:
                    order_line_commands.append(Command.create({
                        'product_id': surcharge_product.id,
                        'name': surcharge_product.name,
                        'product_uom_qty': 1,
                        'price_unit': p_surcharge_val,
                        'company_id': current_company_id,  # Đã đảm bảo current_company_id luôn có giá trị
                    }))

                if existing_order:
                    # Cập nhật thông tin chính của đơn hàng
                    existing_order.sudo().write(order_vals) 
                    # Xóa các dòng cũ và thêm các dòng mới
                    existing_order.order_line.sudo().unlink() 
                    if order_line_commands:
                        existing_order.sudo().write({'order_line': order_line_commands})
                    current_sale_order = existing_order
                    updated_count += 1
                    _logger.info(f"Updated SaleOrder Odoo ID: {current_sale_order.id} ({current_sale_order.name}) for Pancake Order ID: {p_order_id}")
                else:
                    order_vals['order_line'] = order_line_commands
                    current_sale_order = self.sudo().create(order_vals) 
                    created_count +=1
                    _logger.info(f"Created SaleOrder Odoo ID: {current_sale_order.id} ({current_sale_order.name}) for Pancake Order ID: {p_order_id}")
                
                # Logic chuyển trạng thái Odoo sau khi đồng bộ
                if current_sale_order:
                    try:
                        if odoo_state == 'sale' and current_sale_order.state == 'draft':
                            current_sale_order.sudo().action_confirm()
                            _logger.info(f"Confirmed SaleOrder {current_sale_order.name} based on Pancake status.")
                        elif odoo_state == 'done' and current_sale_order.state == 'sale':
                            # Nếu Odoo sale.order không có action_done trực tiếp, có thể cần confirm/validate invoice/delivery
                            # Tùy thuộc vào luồng nghiệp vụ của bạn. Ở đây chỉ là ví dụ.
                            # current_sale_order.sudo().action_done() 
                            _logger.info(f"SaleOrder {current_sale_order.name} is in 'sale' state and Pancake status is 'done'. Manual review may be needed to complete.")
                        elif odoo_state == 'cancel' and current_sale_order.state not in ['cancel', 'done']:
                            current_sale_order.sudo().action_cancel()
                            _logger.info(f"Cancelled SaleOrder {current_sale_order.name} based on Pancake status.")
                    except Exception as e_state_change:
                        _logger.error(f"Failed to change state of SaleOrder {current_sale_order.name}: {e_state_change}")

                processed_count += 1
                self.env.cr.commit() # Commit sau khi xử lý thành công một đơn hàng

            except Exception as e_outer:
                _logger.error(f"CRITICAL ERROR processing Pancake Order ID {p_order_id}: {e_outer}", exc_info=True)
                self.env.cr.rollback() # Rollback transaction của đơn hàng hiện tại nếu có lỗi
                error_count += 1
                continue # Chuyển sang đơn hàng tiếp theo

        sync_message = _('Pancake orders sync finished. Processed: %s, Created: %s, Updated: %s, Skipped: %s, Errors: %s') % \
                        (processed_count, created_count, updated_count, skipped_count, error_count)
        _logger.info(sync_message)
        
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Pancake Sync'), 'message': sync_message, 'sticky': False, 'type': 'success' if error_count == 0 else 'warning'}
        }

    @api.model
    def action_sync_single_pancake_order(self, order_data):
        """
        Processes a single order data dictionary from Pancake to create or update a Sale Order in Odoo.
        This method is ideal for webhook integrations.

        :param order_data: A dictionary containing the data for a single Pancake order.
        :return: A recordset of the created or updated 'sale.order'.
                Returns an empty recordset if the order is skipped or an error occurs.
        """
        _logger.info(f"Processing single Pancake order with ID: {order_data.get('id')}")

        # --- Pre-computation and Model Initialization ---
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        CrmTag = self.env['crm.tag']
        ResUsers = self.env['res.users']
        ResCurrency = self.env['res.currency']
        CrmTeam = self.env['crm.team']
        SaleOrder = self.env['sale.order']

        status_mapping = self._get_pancake_status_to_odoo_state_mapping()

        # --- Company Context ---
        # QUAN TRỌNG: LUÔN PHẢI CÓ company_id hợp lệ, không được để False
        if self.env.company:
            current_company_id = self.env.company.id
        elif self.env.user and self.env.user.company_id:
            current_company_id = self.env.user.company_id.id
        else:
            # Fallback: lấy company đầu tiên trong hệ thống
            default_company = self.env['res.company'].sudo().search([], limit=1)
            if not default_company:
                _logger.error(f"❌ [WEBHOOK] No company found in system! Cannot create order {order_data.get('id')}")
                return SaleOrder
            current_company_id = default_company.id
            _logger.warning(f"⚠️ [WEBHOOK] Using fallback company: {default_company.name} (ID: {current_company_id})")
        
        company_domain = ['|', ('company_id', '=', False), ('company_id', '=', current_company_id)]

        p_order_id = str(order_data.get('id'))
        if not p_order_id:
            _logger.warning("Skipping order with missing ID.")
            return SaleOrder
        
        # Bỏ qua đơn hàng nếu không có lịch sử trạng thái (đơn nháp, chưa hoàn chỉnh)
        if not order_data.get('status_history'):
            _logger.info(f"Skipping Pancake Order ID {p_order_id} due to empty status history.")
            return SaleOrder

        try:
            # --- 1. Find or Create Creator (res.users) ---
            creator_info = order_data.get('creator', {})
            odoo_creator = False # BẮT ĐẦU TỪ False
            
            if creator_info:
                creator_pancake_id = str(creator_info.get('id')) if creator_info.get('id') else None
                creator_name = creator_info.get('name')
                creator_email = creator_info.get('email')
                
                # LẤY CẢ UUID VÀ NUMBER ID (nếu API cung cấp)
                creator_uuid = str(creator_info.get('id')) if creator_info.get('id') else None  # UUID chính
                creator_number_id = str(creator_info.get('fb_id')) if creator_info.get('fb_id') else None  # Number ID (nếu có)
                
                # ƯU TIÊN 1: Tìm theo BẤT KỲ pancake ID nào (cả 3 field)
                if creator_pancake_id:
                    odoo_creator = ResUsers.sudo().search([
                        '|', '|',
                        ('pancake_id', '=', creator_pancake_id),
                        ('pancake_uuid', '=', creator_pancake_id),
                        ('pancake_number_id', '=', creator_pancake_id)
                    ], limit=1)
                    
                    if odoo_creator:
                        matched_field = 'pancake_id' if odoo_creator.pancake_id == creator_pancake_id else \
                                       'pancake_uuid' if odoo_creator.pancake_uuid == creator_pancake_id else \
                                       'pancake_number_id'
                        _logger.info(f"✅ [WEBHOOK] Found creator by {matched_field}: {creator_pancake_id} -> {odoo_creator.name}")
                        
                        # ĐỒNG BỘ CÁC FIELD CÒN THIẾU
                        update_vals = {}
                        if creator_uuid and not odoo_creator.pancake_uuid and odoo_creator.pancake_id != creator_uuid:
                            update_vals['pancake_uuid'] = creator_uuid
                        if creator_number_id and not odoo_creator.pancake_number_id:
                            update_vals['pancake_number_id'] = creator_number_id
                        # Nếu tìm được bằng uuid/number_id nhưng chưa có pancake_id chính
                        if creator_uuid and not odoo_creator.pancake_id:
                            update_vals['pancake_id'] = creator_uuid
                        
                        if update_vals:
                            odoo_creator.sudo().write(update_vals)
                            _logger.debug(f"📝 [WEBHOOK] Synced creator fields: {list(update_vals.keys())}")
                
                # ƯU TIÊN 2: Tìm theo email
                if not odoo_creator and creator_email:
                    odoo_creator = ResUsers.sudo().search([('login', '=', creator_email)], limit=1)
                    if not odoo_creator:
                        odoo_creator = ResUsers.sudo().search([('email', '=', creator_email)], limit=1)
                    
                    if odoo_creator:
                        _logger.info(f"✅ [WEBHOOK] Found creator by email: {creator_email} -> {odoo_creator.name}")
                        # Gán pancake_id nếu chưa có
                        update_vals = {}
                        if creator_uuid and not odoo_creator.pancake_id:
                            update_vals['pancake_id'] = creator_uuid
                        if creator_uuid and not odoo_creator.pancake_uuid:
                            update_vals['pancake_uuid'] = creator_uuid
                        if creator_number_id and not odoo_creator.pancake_number_id:
                            update_vals['pancake_number_id'] = creator_number_id
                        
                        if update_vals:
                            odoo_creator.sudo().write(update_vals)
                            _logger.debug(f"📝 [WEBHOOK] Synced creator fields: {list(update_vals.keys())}")
                
                # ƯU TIÊN 3: Tìm theo tên (không khuyến khích - có thể trùng)
                if not odoo_creator and creator_name:
                    odoo_creator = ResUsers.sudo().search([('name', '=ilike', creator_name), ('share', '=', False)], limit=1)
                    if odoo_creator:
                        _logger.warning(f"⚠️ [WEBHOOK] Found creator by NAME only: {creator_name} -> {odoo_creator.name} (unreliable)")
                        # Gán pancake_id
                        update_vals = {}
                        if creator_uuid and not odoo_creator.pancake_id:
                            update_vals['pancake_id'] = creator_uuid
                        if creator_uuid and not odoo_creator.pancake_uuid:
                            update_vals['pancake_uuid'] = creator_uuid
                        if creator_number_id and not odoo_creator.pancake_number_id:
                            update_vals['pancake_number_id'] = creator_number_id
                        
                        if update_vals:
                            odoo_creator.sudo().write(update_vals)
                            _logger.debug(f"📝 [WEBHOOK] Synced creator fields: {list(update_vals.keys())}")
                
                # TẠO USER MỚI nếu không tìm thấy - LƯU CẢ 3 FIELD
                if not odoo_creator and creator_name and creator_email:
                    try:
                        odoo_creator = ResUsers.sudo().create({
                            'name': creator_name,
                            'login': creator_email,
                            'email': creator_email,
                            'pancake_id': creator_uuid,  # UUID chính
                            'pancake_uuid': creator_uuid,  # UUID (trùng)
                            'pancake_number_id': creator_number_id,  # Number ID (nếu có)
                            'company_id': current_company_id,
                            'company_ids': [(4, current_company_id)],
                            'groups_id': [(4, self.env.ref('sales_team.group_sale_salesman').id)],
                        })
                        _logger.info(f"✅ [WEBHOOK] Created new creator: {odoo_creator.name} (UUID: {creator_uuid}, Number: {creator_number_id})")
                    except Exception as e:
                        _logger.warning(f"⚠️ [WEBHOOK] Failed to create creator: {e}")
            
            # FALLBACK: Dùng user hiện tại hoặc tìm admin
            if not odoo_creator:
                if self.env.user and self.env.user.id and self.env.user.company_id:
                    odoo_creator = self.env.user
                    _logger.warning(f"⚠️ [WEBHOOK] Creator not found, using current user: {odoo_creator.name}")
                else:
                    # Webhook context không có user hợp lệ → tìm Admin
                    odoo_creator = ResUsers.sudo().search([
                        ('company_id', '=', current_company_id),
                        ('groups_id', 'in', [self.env.ref('base.group_system').id])
                    ], limit=1)
                    if not odoo_creator:
                        # Fallback cuối: user đầu tiên của company
                        odoo_creator = ResUsers.sudo().search([('company_id', '=', current_company_id)], limit=1)
                    _logger.warning(f"⚠️ [WEBHOOK] No user context, using fallback user: {odoo_creator.name if odoo_creator else 'NONE'}")
            
            if not odoo_creator:
                _logger.error(f"❌ [WEBHOOK] Cannot find any valid user for order {p_order_id}")
                return SaleOrder

            # --- 2. Find or Create Salesperson (user_id) & Sales Team (team_id) ---
            assigning_seller_info = order_data.get('assigning_seller', {})
            salesperson = False
            
            if isinstance(assigning_seller_info, dict):
                # Extract seller IDs
                seller_uuid = str(assigning_seller_info.get('id')) if assigning_seller_info.get('id') else None
                seller_number_id = str(assigning_seller_info.get('fb_id')) if assigning_seller_info.get('fb_id') else None
                seller_name = assigning_seller_info.get('name')
                seller_email = assigning_seller_info.get('email')
                
                # ƯU TIÊN 1: Tìm theo CẢ 3 FIELD (pancake_id | pancake_uuid | pancake_number_id)
                seller_pancake_id = seller_uuid or seller_number_id  # Prefer UUID
                if seller_pancake_id:
                    salesperson = ResUsers.sudo().search([
                        '|', '|',
                        ('pancake_id', '=', seller_pancake_id),
                        ('pancake_uuid', '=', seller_pancake_id),
                        ('pancake_number_id', '=', seller_pancake_id)
                    ], limit=1)
                    
                    if salesperson:
                        # Log which field matched
                        matched_field = 'pancake_id' if salesperson.pancake_id == seller_pancake_id else \
                                      'pancake_uuid' if salesperson.pancake_uuid == seller_pancake_id else \
                                      'pancake_number_id' if salesperson.pancake_number_id == seller_pancake_id else 'unknown'
                        _logger.info(f"✅ [WEBHOOK] Found salesperson by {matched_field}: {seller_pancake_id} -> {salesperson.name}")
                        
                        # Sync missing fields (only if empty)
                        update_vals = {}
                        if seller_uuid and not salesperson.pancake_uuid:
                            update_vals['pancake_uuid'] = seller_uuid
                        if seller_number_id and not salesperson.pancake_number_id:
                            update_vals['pancake_number_id'] = seller_number_id
                        # Sync pancake_id to UUID if currently NUMBER
                        if seller_uuid and salesperson.pancake_id and len(salesperson.pancake_id) < 30:
                            update_vals['pancake_id'] = seller_uuid
                        if update_vals:
                            salesperson.sudo().write(update_vals)
                            _logger.debug(f"📝 [WEBHOOK] Synced salesperson fields: {list(update_vals.keys())}")
                
                # ƯU TIÊN 2: Tìm theo email
                if not salesperson and seller_email:
                    salesperson = ResUsers.sudo().search([('login', '=', seller_email), ('share', '=', False)], limit=1)
                    if salesperson:
                        _logger.info(f"✅ [WEBHOOK] Found salesperson by email: {seller_email} -> {salesperson.name}")
                        # Populate ALL 3 fields
                        update_vals = {}
                        if seller_uuid and not salesperson.pancake_id:
                            update_vals['pancake_id'] = seller_uuid
                        if seller_uuid and not salesperson.pancake_uuid:
                            update_vals['pancake_uuid'] = seller_uuid
                        if seller_number_id and not salesperson.pancake_number_id:
                            update_vals['pancake_number_id'] = seller_number_id
                        if update_vals:
                            salesperson.sudo().write(update_vals)
                            _logger.info(f"📝 [WEBHOOK] Populated salesperson Pancake IDs: {list(update_vals.keys())}")
                
                # ƯU TIÊN 3: Tìm theo tên
                if not salesperson and seller_name:
                    salesperson = ResUsers.sudo().search([('name', '=ilike', seller_name), ('share', '=', False)], limit=1)
                    if salesperson:
                        _logger.info(f"✅ [WEBHOOK] Found salesperson by name: {seller_name}")
                        # Populate ALL 3 fields
                        update_vals = {}
                        if seller_uuid and not salesperson.pancake_id:
                            update_vals['pancake_id'] = seller_uuid
                        if seller_uuid and not salesperson.pancake_uuid:
                            update_vals['pancake_uuid'] = seller_uuid
                        if seller_number_id and not salesperson.pancake_number_id:
                            update_vals['pancake_number_id'] = seller_number_id
                        if update_vals:
                            salesperson.sudo().write(update_vals)
                            _logger.info(f"📝 [WEBHOOK] Populated salesperson Pancake IDs: {list(update_vals.keys())}")
                
                # TẠO USER MỚI - LƯU CẢ 3 FIELD
                if not salesperson and seller_name and seller_email:
                    try:
                        salesperson = ResUsers.sudo().create({
                            'name': seller_name,
                            'login': seller_email,
                            'email': seller_email,
                            'pancake_id': seller_uuid,  # UUID primary
                            'pancake_uuid': seller_uuid,
                            'pancake_number_id': seller_number_id,
                            'company_id': current_company_id,
                            'company_ids': [(4, current_company_id)],
                            'groups_id': [(4, self.env.ref('sales_team.group_sale_salesman').id)],
                        })
                        _logger.info(f"✅ [WEBHOOK] Created new salesperson: {salesperson.name} (UUID: {seller_uuid}, Number: {seller_number_id})")
                    except Exception as e:
                        _logger.warning(f"⚠️ [WEBHOOK] Failed to create salesperson: {e}")
            
            # === XÁC ĐỊNH user_id_val ===
            if salesperson:
                user_id_val = salesperson.id
                _logger.info(f"✅ [WEBHOOK] Using salesperson: {salesperson.name}")
            elif odoo_creator:
                user_id_val = odoo_creator.id
                _logger.info(f"✅ [WEBHOOK] Using creator as salesperson: {odoo_creator.name}")
            else:
                # Không nên đến đây vì odoo_creator đã được bảo đảm ở trên
                _logger.error(f"❌ [WEBHOOK] No valid salesperson for order {p_order_id}")
                return SaleOrder

            final_team_id_val = self.env['crm.team']._get_default_team_id(user_id=user_id_val)

            # --- 3. Find or Create Customer (partner_id) ---
            customer_info = order_data.get('customer', {}) or {}
            partner = False

            p_customer_id = customer_info.get('customer_id') or customer_info.get('id')  # UUID từ Pancake
            customer_phone = (customer_info.get('phone_numbers') or [None])[0]
            customer_email = (customer_info.get('emails') or [None])[0]
            customer_name = customer_info.get('name')

            if not customer_name:
                _logger.error(f"Cannot process order {p_order_id}: Customer name is missing.")
                return SaleOrder

            Partner = self.env['res.partner'].sudo()

            # ƯU TIÊN 1: tìm theo pancake_id
            if p_customer_id:
                partner = Partner.search([('pancake_id', '=', p_customer_id)] + company_domain, limit=1)

            # ƯU TIÊN 2: fallback phone/email + name
            if not partner and customer_phone and customer_name:
                partner = Partner.search([('phone', '=', customer_phone), ('name', '=', customer_name)] + company_domain, limit=1)
            if not partner and customer_email and customer_name:
                partner = Partner.search([('email', '=ilike', customer_email), ('name', '=', customer_name)] + company_domain, limit=1)

            if not partner:
                partner_vals = {
                    'name': customer_name,
                    'phone': customer_phone,
                    'email': customer_email,
                    'company_type': 'person',
                    'company_id': current_company_id,
                    'street': customer_info.get('address') or customer_info.get('street'),
                    'city': customer_info.get('city'),
                    'zip': customer_info.get('zip'),
                    # Gán pancake_id NGAY LÚC TẠO
                    'pancake_id': p_customer_id or False,
                }
                partner = Partner.create(partner_vals)
                _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) for Pancake order {p_order_id}")
            else:
                # Nếu tìm bằng phone/email mà partner CHƯA có pancake_id → ghi bù để chốt liên kết lâu dài
                if p_customer_id and not partner.pancake_id:
                    partner.write({'pancake_id': p_customer_id})
                # Cập nhật địa chỉ nếu có thay đổi
                if customer_info.get('address') or customer_info.get('street'):
                    partner.street = customer_info.get('address') or customer_info.get('street')
                if customer_info.get('city'):
                    partner.city = customer_info.get('city')
                if customer_info.get('zip'):
                    partner.zip = customer_info.get('zip')
            
            # --- 4. Find or Create Shipping Address (partner_shipping_id) ---
            shipping_address_info = order_data.get('shipping_address', {})
            partner_shipping_id = partner.id # Default to customer
            sfn = shipping_address_info.get('full_name')
            sp = shipping_address_info.get('phone_number')
            s_addr = shipping_address_info.get('full_address')

            if sfn and (sfn != partner.name or sp != partner.phone):
                # Tìm địa chỉ giao hàng đã có
                shipping_contact = Partner.search([
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'delivery'),
                    ('name', '=', sfn),
                    ('phone', '=', sp)
                ], limit=1)
                
                if not shipping_contact:
                    shipping_contact = Partner.create({
                        'name': sfn, 'parent_id': partner.id, 'type': 'delivery',
                        'phone': sp, 'street': s_addr,
                        'company_id': current_company_id,
                    })
                partner_shipping_id = shipping_contact.id

            # --- 5. Find or Create Pricelist ---
            p_currency_code = order_data.get('order_currency', 'VND')
            currency = ResCurrency.search([('name', '=', p_currency_code)], limit=1)
            currency_id_val = currency.id if currency else self.env.company.currency_id.id

            pricelist = self.env['product.pricelist'].search(
                [('currency_id', '=', currency_id_val)] + company_domain, 
                order='company_id desc, sequence, id', limit=1
            )
            if not pricelist:
                _logger.warning(f"Pricelist not found for currency {p_currency_code}. Creating a new one.")
                pricelist = self.env['product.pricelist'].sudo().create({
                    'name': f'Default {p_currency_code} Pricelist - {self.env.company.name if current_company_id else "Global"}',
                    'currency_id': currency_id_val,
                    'company_id': current_company_id,
                })
            pricelist_id_val = pricelist.id

            # --- 6. Prepare Order Lines ---
            order_line_commands = []
            for item_data in order_data.get('items', []):
                variation_info = item_data.get('variation_info', {})
                p_item_name = variation_info.get('name')
                p_item_sku = str(variation_info.get('sku') or variation_info.get('display_id')) or None
                
                # LUÔN TẠO SẢN PHẨM MỚI từ Pancake (không search sản phẩm cũ)
                product_variant = False
                if p_item_name:
                    product_variant = Product.sudo().create({
                        'name': p_item_name,
                        'default_code': p_item_sku,
                        'type': 'product',
                        'sale_ok': True, 
                        'purchase_ok': False,
                        'lst_price': variation_info.get('retail_price', 0.0),
                        'company_id': current_company_id,  # CRITICAL: Sản phẩm phải thuộc công ty
                    })
                    _logger.info(f"✅ Created new product from Pancake: {p_item_name} (company_id: {current_company_id})")
                    # Verify product was created with correct company_id
                    _logger.info(f"🔍 Product variant company_id: {product_variant.company_id.id if product_variant.company_id else None}")
                    _logger.info(f"🔍 Product template company_id: {product_variant.product_tmpl_id.company_id.id if product_variant.product_tmpl_id.company_id else None}")
                    if not product_variant.company_id or product_variant.company_id.id != current_company_id:
                        _logger.error(f"❌ Product variant company_id mismatch! Expected: {current_company_id}, Got: {product_variant.company_id.id if product_variant.company_id else None}")
                    if not product_variant.product_tmpl_id.company_id or product_variant.product_tmpl_id.company_id.id != current_company_id:
                        _logger.error(f"❌ Product template company_id mismatch! Expected: {current_company_id}, Got: {product_variant.product_tmpl_id.company_id.id if product_variant.product_tmpl_id.company_id else None}")

                if product_variant:
                    order_line_commands.append((0, 0, {
                        'product_id': product_variant.id,
                        'name': product_variant.name,
                        'product_uom_qty': item_data.get('quantity', 0.0),
                        'price_unit': variation_info.get('retail_price', 0.0),
                        'company_id': current_company_id,  # QUAN TRỌNG: Phải có company_id
                    }))

            # --- 7. Prepare Main Order Values ---
            p_status_key = str(order_data.get('status'))
            odoo_state = status_mapping.get(p_status_key, 'draft')
            inserted_at_str = order_data.get('inserted_at', '').split('.')[0].replace('T', ' ')
            date_order = fields.Datetime.from_string(inserted_at_str) if inserted_at_str else fields.Datetime.now()
            
            customer_notes_list = [note.get('message', '') for note in customer_info.get('notes', [])]
            
            # 🆕 AUTO-ASSIGN Design & Production từ Tags
            user_id_design = False
            user_id_production = False
            
            tags_data = order_data.get('tags', [])
            if tags_data:
                _logger.info(f"📋 [WEBHOOK] Processing {len(tags_data)} tags for order {p_order_id}")
                
                # Mapping tên → User name trong Odoo
                # CHỈ Ái và Quân có thể làm cả thiết kế VÀ sản xuất
                name_to_user_mapping = {
                    'ái': 'Thuy Ai Dang',
                    'phong': 'Phong',
                    'quân': 'Quân',
                    'dao': 'Dao',
                    'duy an': 'Duy An (Bông)',
                    'bông': 'Duy An (Bông)',
                }
                
                for tag in tags_data:
                    tag_name_original = (tag.get('name') or '').strip()
                    tag_name_lower = tag_name_original.lower()
                    
                    if not tag_name_original:
                        continue
                    
                    # QUAN TRỌNG: Chỉ xử lý tag CÓ NGOẶC (có role rõ ràng)
                    if '(' not in tag_name_original:
                        _logger.info(f"ℹ️ [WEBHOOK] Skipping tag without role: '{tag_name_original}' (legacy format)")
                        continue
                    
                    # Kiểm tra role rõ ràng trong tag
                    is_design = 'thiết kế' in tag_name_lower or 'thiet ke' in tag_name_lower
                    is_production = 'sản xuất' in tag_name_lower or 'san xuat' in tag_name_lower
                    
                    if not (is_design or is_production):
                        _logger.warning(f"⚠️ [WEBHOOK] Tag '{tag_name_original}' has parentheses but no valid role")
                        continue
                    
                    # Extract tên người (phần trước dấu ngoặc)
                    person_name = tag_name_original.split('(')[0].strip().lower()
                    
                    # Tìm user match
                    matched_user_name = None
                    for key, user_name in name_to_user_mapping.items():
                        if key in person_name:
                            matched_user_name = user_name
                            break
                    
                    if not matched_user_name:
                        _logger.warning(f"⚠️ [WEBHOOK] Cannot map tag '{tag_name_original}' to any user")
                        continue
                    
                    # Search user trong Odoo
                    user = ResUsers.sudo().search([('name', '=ilike', matched_user_name)], limit=1)
                    
                    if not user:
                        _logger.warning(f"⚠️ [WEBHOOK] User '{matched_user_name}' not found in Odoo for tag '{tag_name_original}'")
                        continue
                    
                    # Gán vào field tương ứng theo role
                    if is_design and not user_id_design:
                        user_id_design = user.id
                        _logger.info(f"✅ [WEBHOOK] Assigned design to: {user.name} (from tag: '{tag_name_original}')")
                    
                    if is_production and not user_id_production:
                        user_id_production = user.id
                        _logger.info(f"✅ [WEBHOOK] Assigned production to: {user.name} (from tag: '{tag_name_original}')")


            
            order_vals = {
                'pancake_order_id': p_order_id,
                'partner_id': partner.id,
                'partner_shipping_id': partner_shipping_id,
                'date_order': date_order,
                'state': odoo_state,
                'user_id': user_id_val,
                'team_id': final_team_id_val.id,
                'company_id': current_company_id,
                'pricelist_id': pricelist_id_val,
                'origin': f"Pancake: {p_order_id}",
                'note': order_data.get('note'),
                'client_order_ref': p_order_id,
                'order_line': order_line_commands,
                'pancake_customer_note': "\n".join(customer_notes_list),
                'pancake_status_name': order_data.get('status_name'),
                'pancake_status_key': p_status_key,
                'pancake_order_link': order_data.get('link_confirm_order'),
                'last_sync_date': fields.Datetime.now(),
                'pancake_raw_data': str(order_data),
            }
            
            # Thêm design & production user nếu có
            if user_id_design:
                order_vals['user_id_design'] = user_id_design
            if user_id_production:
                order_vals['user_id_production'] = user_id_production

            # --- 8. Create or Update Sale Order ---
            existing_order = SaleOrder.search([('pancake_order_id', '=', p_order_id), ('company_id', '=', current_company_id)], limit=1)
            
            if existing_order:
                # Xóa các dòng cũ trước khi thêm dòng mới để tránh trùng lặp
                existing_order.order_line.unlink()
                existing_order.write(order_vals)
                current_sale_order = existing_order
                _logger.info(f"Updated SaleOrder Odoo ID: {current_sale_order.id} for Pancake Order ID: {p_order_id}")
            else:
                # TẮT auto-subscribe và email notification khi tạo từ webhook
                current_sale_order = SaleOrder.with_context(
                    mail_create_nolog=True,          # Không tạo log message
                    mail_create_nosubscribe=True,    # Không auto-subscribe
                    mail_notrack=True,                # Không tracking changes
                    tracking_disable=True             # Disable tracking hoàn toàn
                ).create(order_vals)
                _logger.info(f"✅ Created SaleOrder Odoo ID: {current_sale_order.id} for Pancake Order ID: {p_order_id}")
            
            # --- 9. Final State Transition ---
            if odoo_state == 'sale' and current_sale_order.state == 'draft':
                current_sale_order.action_confirm()
            elif odoo_state == 'cancel' and current_sale_order.state not in ['cancel', 'done']:
                current_sale_order.action_cancel()

            # 🆕 YÊU CẦU #3: Gán creator vào conversation của khách hàng
            if odoo_creator and partner:
                try:
                    # Tìm conversation của khách hàng này
                    conversations = self.env['page.fm.conversation'].sudo().search([
                        ('partner_id', '=', partner.id)
                    ])
                    
                    if conversations:
                        for conv in conversations:
                            current_participants = set(conv.participant_user_ids.ids)
                            if odoo_creator.id not in current_participants:
                                current_participants.add(odoo_creator.id)
                                conv.write({'participant_user_ids': [(6, 0, list(current_participants))]})
                                _logger.info(f"➕ Auto-added order creator {odoo_creator.name} to conversation {conv.conversation_fm_id} of customer {partner.name}")
                            else:
                                _logger.info(f"ℹ️ Creator {odoo_creator.name} already in conversation {conv.conversation_fm_id}")
                        
                        # 🆕 SYNC VÀO PARTNER luôn
                        partner_participants = set(partner.participant_user_ids.ids)
                        if odoo_creator.id not in partner_participants:
                            partner_participants.add(odoo_creator.id)
                            partner.write({'participant_user_ids': [(6, 0, list(partner_participants))]})
                            _logger.info(f"➕ Auto-added order creator {odoo_creator.name} to partner {partner.name} (Nhóm phụ trách)")
                        else:
                            _logger.info(f"ℹ️ Creator {odoo_creator.name} already in partner {partner.name} participants")
                        
                        # Cập nhật người phụ trách hiện tại nếu chưa có
                        if not partner.responsible_user_id:
                            partner.write({'responsible_user_id': odoo_creator.id})
                            _logger.info(f"👤 Set partner {partner.name} responsible_user_id to {odoo_creator.name}")
                    else:
                        _logger.info(f"ℹ️ No conversation found for customer {partner.name} (pancake_id: {partner.pancake_id})")
                except Exception as e:
                    _logger.error(f"❌ Error assigning creator to conversation/partner: {e}", exc_info=True)

            self.env.cr.commit()
            return current_sale_order

        except Exception as e:
            _logger.error(f"CRITICAL ERROR processing Pancake Order ID {p_order_id}: {e}", exc_info=True)
            self.env.cr.rollback()
            return SaleOrder