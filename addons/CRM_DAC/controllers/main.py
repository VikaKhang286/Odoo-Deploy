# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
# from odoo.addons.web.controllers.main import Home # Bỏ comment nếu bạn cần kế thừa
import logging

_logger = logging.getLogger(__name__)

class PancakeDashboardController(http.Controller):

    @http.route('/pancake/dashboard', type='http', auth='public', website=False)
    def pancake_dashboard(self, **kwargs):
        PancakeOrder = request.env['pancake.order']
        
        total_orders = PancakeOrder.search_count([])
        
        orders_data = PancakeOrder.search_read([], ['pancake_money_to_collect'])
        total_revenue = sum(order.get('pancake_money_to_collect', 0) or 0 for order in orders_data)

        status_counts = PancakeOrder.read_group(
            domain=[],
            fields=['pancake_status_name'],
            groupby=['pancake_status_name']
        )
        
        recent_orders = PancakeOrder.search_read(
            domain=[],
            fields=['name', 'pancake_customer_name', 'pancake_status_name', 'pancake_inserted_at', 'pancake_money_to_collect'],
            limit=5,
            order='pancake_inserted_at desc'
        )
        
        for order in recent_orders:
            if order.get('pancake_inserted_at'):
                order['pancake_inserted_at'] = order['pancake_inserted_at'].strftime('%Y-%m-%d %H:%M:%S')

        values = {
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'status_counts': status_counts,
            'recent_orders': recent_orders,
            'page_title': 'Pancake Dashboard',
        }
        
        # Render template QWeb. 'CRM_DAC.pancake_dashboard_template' là ID của template
        return request.render('CRM_DAC.pancake_dashboard_template', values)

    @http.route('/pancake/trigger_sync_all', type='json', auth='user')
    def trigger_sync_all_orders_json(self):
        try:
            request.env['pancake.order'].action_sync_pancake_all_orders()
            return {'status': 'success', 'message': 'Đồng bộ tất cả đơn hàng Pancake đã được kích hoạt.'}
        except Exception as e:
            _logger.error(f"Lỗi khi kích hoạt đồng bộ từ dashboard: {e}")
            return {'status': 'error', 'message': str(e)}