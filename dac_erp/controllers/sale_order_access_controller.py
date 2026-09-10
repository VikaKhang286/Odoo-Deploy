# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


class SaleOrderAccessController(http.Controller):
    """
    Controller để intercept URL truy cập action và redirect đúng menu/action
    dựa trên quyền của user
    
    Pattern URL hỗ trợ:
    - /odoo/action-XXX (any action ID)
    - /odoo/action-371/10041 (with sale order ID)
    - /odoo/action-371/10041/invoicing/53/account.payment/27/sale.order/10041
    
    QUAN TRỌNG:
    - Intercept TẤT CẢ /odoo/action-* URLs
    - Kiểm tra quyền user và redirect về menu phù hợp
    """
    
    def _get_debug_param(self, kwargs):
        """Helper method để lấy debug parameter từ URL - CHỈ cho ADMIN"""
        user = request.env.user
        
        # 🔒 CHỈ admin mới được dùng debug mode
        if not user.has_group('base.group_system'):
            return ''
        
        debug = kwargs.get('debug', '') or request.httprequest.args.get('debug', '')
        return f'?debug={debug}' if debug else ''
    
    def _build_url_with_debug(self, base_url, kwargs):
        """Helper method để build URL kèm debug parameter đúng cách"""
        debug_query = self._get_debug_param(kwargs)
        # Format: /web?debug=1#action=xxx (query TRƯỚC hash)
        if '#' in base_url:
            parts = base_url.split('#', 1)
            return f'{parts[0]}{debug_query}#{parts[1]}'
        return f'{base_url}{debug_query}'
    
    @http.route([
        '/odoo/action-<int:action_id>',
        '/odoo/action-<int:action_id>/<int:sale_order_id>',
        '/odoo/action-<int:action_id>/<int:sale_order_id>/<path:breadcrumb>'
    ], type='http', auth='user', website=False)
    def intercept_sale_order_url(self, action_id, sale_order_id=None, breadcrumb=None, **kwargs):
        """
        Intercept URL dạng /odoo/action-xxx hoặc /odoo/action-xxx/[SALE_ORDER_ID]/...
        
        Parameters:
        - action_id: ID của action (từ URL)
        - sale_order_id: ID của sale order (từ URL, optional)
        - breadcrumb: Phần còn lại của URL (optional)
        - kwargs: Query parameters (?debug=1, etc.)
        """
        _logger.info(f"[INTERCEPT] Action {action_id}, Sale Order ID: {sale_order_id}, Breadcrumb: {breadcrumb}, kwargs: {kwargs}")
        
        # Kiểm tra quyền user TRƯỚC
        user = request.env.user
        
        # ===== ADMIN BYPASS: Admin có full access, không cần kiểm tra gì =====
        if user.has_group('base.group_system'):
            _logger.info(f"[INTERCEPT] Admin user {user.name} - full access, no restrictions")
            
            # Build URL đúng format: /web?debug=1#action=xxx
            if sale_order_id:
                base_url = f'/web#id={sale_order_id}&model=sale.order&view_type=form&action={action_id}'
            else:
                base_url = f'/web#action={action_id}'
            
            full_url = self._build_url_with_debug(base_url, kwargs)
            _logger.info(f"[INTERCEPT] Admin redirect to: {full_url}")
            return request.redirect(full_url)
        
        # Nếu user KHÔNG có bất kỳ DAC group nào → redirect về home menu
        if not (user.has_group('dac_erp.group_dac_erp_manager') or 
                user.has_group('dac_erp.group_dac_erp_sale') or
                user.has_group('dac_erp.group_dac_erp_design') or
                user.has_group('dac_erp.group_dac_erp_production')):
            
            _logger.warning(f"[INTERCEPT] User {user.name} has no DAC groups - redirecting to home menu")
            redirect_url = self._build_url_with_debug('/web#action=home_menu.home_menu_action', kwargs)
            return request.redirect(redirect_url)
        
        # Nếu có sale_order_id → kiểm tra quyền truy cập đơn hàng
        if sale_order_id:
            return self._check_access_and_redirect(sale_order_id, kwargs)
        
        # Nếu không có sale_order_id → cho phép truy cập action bình thường
        _logger.info(f"[INTERCEPT] User {user.name} accessing action {action_id} (no order ID) - allowing")
        redirect_url = self._build_url_with_debug(f'/web#action={action_id}', kwargs)
        return request.redirect(redirect_url)
    
    def _check_access_and_redirect(self, sale_order_id, url_params):
        """
        Kiểm tra quyền truy cập đơn hàng và redirect đến action phù hợp
        """
        try:
            # Tìm đơn hàng
            sale_order = request.env['sale.order'].sudo().browse(sale_order_id)
            
            if not sale_order.exists():
                _logger.warning(f"[INTERCEPT] Sale order {sale_order_id} not found")
                
                # Redirect về đúng DASHBOARD theo group của user
                user = request.env.user
                
                if user.has_group('dac_erp.group_dac_erp_design'):
                    # Design → về Design Dashboard
                    redirect_url = self._build_url_with_debug('/web#action=dac_erp.dac_design_dashboard_action', url_params)
                    return request.redirect(redirect_url)
                elif user.has_group('dac_erp.group_dac_erp_production'):
                    # Production → về Production Dashboard
                    redirect_url = self._build_url_with_debug('/web#action=dac_erp.dac_production_dashboard_action', url_params)
                    return request.redirect(redirect_url)
                elif (user.has_group('dac_erp.group_dac_erp_manager') or 
                      user.has_group('dac_erp.group_dac_erp_sale')):
                    # Manager/Sale → về Dashboard chính của họ (từ dac_report module)
                    redirect_url = self._build_url_with_debug('/web#action=dac_report.dac_sale_dashboard_action', url_params)
                    return request.redirect(redirect_url)
                elif user.has_group('base.group_system'):
                    # Admin → về trang chủ Odoo
                    redirect_url = self._build_url_with_debug('/web', url_params)
                    return request.redirect(redirect_url)
                else:
                    # User không có quyền gì → redirect về Home menu
                    redirect_url = self._build_url_with_debug('/web#action=home_menu.home_menu_action', url_params)
                    return request.redirect(redirect_url)
            
            user = request.env.user
            _logger.info(f"[INTERCEPT] User: {user.name} (ID: {user.id}) accessing order {sale_order.name}")
            
            # CASE 1: Manager/Sale → Full access
            if (user.has_group('dac_erp.group_dac_erp_manager') or 
                user.has_group('dac_erp.group_dac_erp_sale')):
                
                _logger.info(f"[INTERCEPT] Manager/Sale user - full access granted")
                return self._redirect_to_form(sale_order_id, is_design_production=False, url_params=url_params)
            
            # CASE 2: Design/Production user → Check assignment
            if (user.has_group('dac_erp.group_dac_erp_design') or 
                user.has_group('dac_erp.group_dac_erp_production')):
                
                # Check quyền truy cập
                can_access = False
                
                if user.has_group('dac_erp.group_dac_erp_design'):
                    can_access = (sale_order.user_id_design == user)
                    _logger.info(f"[INTERCEPT] Design user check: assigned={sale_order.user_id_design.name}, current={user.name}, access={can_access}")
                
                elif user.has_group('dac_erp.group_dac_erp_production'):
                    can_access = (sale_order.user_id_production == user or user in sale_order.production_group_ids)
                    _logger.info(f"[INTERCEPT] Production user check: access={can_access}")
                
                if can_access:
                    # Có quyền → redirect đến form view
                    _logger.info(f"[INTERCEPT] Access granted - redirecting to form view")
                    return self._redirect_to_form(sale_order_id, is_design_production=True, url_params=url_params)
                else:
                    # KHÔNG có quyền → hiển thị notification và redirect về list view
                    _logger.warning(f"[INTERCEPT] Access DENIED - order {sale_order.name} not assigned to user {user.name}")
                    
                    # Gửi notification qua bus
                    request.env['bus.bus']._sendone(
                        user.partner_id,
                        'simple_notification',
                        {
                            'type': 'warning',
                            'title': '⛔ Không có quyền truy cập',
                            'message': f'Đơn hàng {sale_order.name} không được phân công cho bạn.\n\nVui lòng liên hệ Sale phụ trách.',
                            'sticky': False,
                        }
                    )
                    
                    # Redirect về DASHBOARD phù hợp theo group (KHÔNG phải menu!)
                    if user.has_group('dac_erp.group_dac_erp_design'):
                        # Design → về Design Dashboard
                        redirect_url = self._build_url_with_debug('/web#action=dac_erp.dac_design_dashboard_action', url_params)
                        return request.redirect(redirect_url)
                    elif user.has_group('dac_erp.group_dac_erp_production'):
                        # Production → về Production Dashboard
                        redirect_url = self._build_url_with_debug('/web#action=dac_erp.dac_production_dashboard_action', url_params)
                        return request.redirect(redirect_url)
                    else:
                        # Fallback: redirect về Home menu
                        redirect_url = self._build_url_with_debug('/web#action=home_menu.home_menu_action', url_params)
                        return request.redirect(redirect_url)
            
            # CASE 3: User không thuộc nhóm nào → Redirect về Home menu
            _logger.warning(f"[INTERCEPT] User {user.name} has no relevant groups - redirecting to home menu")
            redirect_url = self._build_url_with_debug('/web#action=home_menu.home_menu_action', url_params)
            return request.redirect(redirect_url)
            
        except Exception as e:
            _logger.error(f"[INTERCEPT] Error checking access: {e}", exc_info=True)
            return request.redirect('/web')
    
    def _redirect_to_form(self, sale_order_id, is_design_production=False, url_params=None):
        """
        Redirect đến form view của đơn hàng với action phù hợp
        """
        if url_params is None:
            url_params = {}
            
        if is_design_production:
            # Xác định action cụ thể dựa vào user group
            user = request.env.user
            
            if user.has_group('dac_erp.group_dac_erp_design'):
                # Người thiết kế → action thiết kế
                action = request.env.ref('dac_erp.dac_sale_order_action_design_only')
                _logger.info(f"[INTERCEPT] Using Design action for user {user.name}")
            elif user.has_group('dac_erp.group_dac_erp_production'):
                # Người sản xuất → action sản xuất
                action = request.env.ref('dac_erp.dac_sale_order_action_production_only')
                _logger.info(f"[INTERCEPT] Using Production action for user {user.name}")
            else:
                # Fallback - dùng action Design (mặc định)
                action = request.env.ref('dac_erp.dac_sale_order_action_design_only')
                _logger.info(f"[INTERCEPT] Using fallback Design action for user {user.name}")
            
            # Build URL với action, view_id, và id
            base_url = f'/web#id={sale_order_id}&model=sale.order&view_type=form&action={action.id}'
            url = self._build_url_with_debug(base_url, url_params)
            _logger.info(f"[INTERCEPT] Redirecting Design/Production to: {url}")
            return request.redirect(url)
        else:
            # Manager/Sale → dùng action bình thường
            action = request.env.ref('dac_erp.dac_sale_order_manager_action')
            form_view = request.env.ref('dac_erp.dac_sale_order_custom_view_form')
            
            base_url = f'/web#id={sale_order_id}&model=sale.order&view_type=form&action={action.id}'
            url = self._build_url_with_debug(base_url, url_params)
            _logger.info(f"[INTERCEPT] Redirecting Manager/Sale to: {url}")
            return request.redirect(url)