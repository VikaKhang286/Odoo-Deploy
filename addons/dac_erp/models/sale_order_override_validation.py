# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class SaleOrderOverrideValidation(models.Model):
    _inherit = 'sale.order'

    @api.constrains('order_line', 'company_id')
    def _check_order_line_company_id(self):
        """
        Override validation để cho phép tạo đơn hàng từ Pancake webhook
        ngay cả khi có sản phẩm cũ với company_id = None trong database.
        
        QUAN TRỌNG: Chỉ skip validation cho đơn hàng từ Pancake (có pancake_order_id)
        """
        for order in self:
            # Skip validation nếu đơn hàng từ Pancake
            if order.pancake_order_id:
                _logger.info(f"⚠️ Skipping company_id validation for Pancake order: {order.pancake_order_id}")
                continue
            
            # Gọi validation gốc cho các đơn hàng thông thường
            super(SaleOrderOverrideValidation, order)._check_order_line_company_id()
