from datetime import date, datetime
import requests
from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

PAYMENT_STATES = ['payment', 'completed']  # trạng thái thu tiền / đã xong

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    
    def action_push_gs_both(self):
        _logger.info("[GS] manual push SO ids=%s", self.ids)

        self.with_context(push_only_ids=self.ids).sudo().push_gs_flat()
        self.with_context(push_only_ids=self.ids).sudo().push_gs_two_sheet()
        return {'type': 'ir.actions.client','tag':'display_notification',
                'params':{'title':'Google Sheet','message':'Đã đồng bộ dữ liệu','sticky':False}}


    @staticmethod
    def _iso_date(val):
        if not val:
            return ""
        if isinstance(val, datetime):
            return val.date().isoformat()
        if isinstance(val, date):
            return val.isoformat()
        try:
            return fields.Datetime.to_datetime(val).date().isoformat()
        except Exception:
            try:
                return fields.Date.to_date(val).isoformat()
            except Exception:
                return str(val)



    @api.model
    def push_gs_two_sheet(self, limit=None):
        """Đẩy Orders & OrderLines (append-only)."""
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('gs.webapp.url.twosheet') or ICP.get_param('gs.webapp.url.two')
        if not url:
            return False

        push_ids = self.env.context.get('push_only_ids')
        if push_ids:
            orders = self.sudo().browse(push_ids)
        else:
            now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            if not (8 <= now_local.hour < 18):
                return True
            limit = int(limit or ICP.get_param('gs.push.limit', '200'))
            domain = [('order_state_custom', 'in', PAYMENT_STATES)]
            orders = self.sudo().search(domain, order='date desc, id desc', limit=limit)

        orders_payload, lines_payload = [], []
        for o in orders:
            sodh   = o.order_number or o.name
            ngay_o = (o.date or o.create_date or o.date_order)

            # --- ORDERS (khóa: order_number)
            orders_payload.append({
                # core
                "order_id": o.id,
                "name": o.name or "",
                "order_number": sodh or "",
                "date_order": self._iso_date(getattr(o, "date_order", False) or getattr(o, "date", False) or o.create_date),
                "order_state_custom": getattr(o, "order_state_custom", "") or "",
                "state": o.state or "",
                # partner & users
                "partner_name": o.partner_id.name or "",
                "partner_phone": (o.partner_id.mobile or o.partner_id.phone or ""),
                "user_sales": o.user_id.name or "",
                "user_design": (getattr(o, "user_id_design", False) and o.user_id_design.name) or "",
                "user_production": (getattr(o, "user_id_production", False) and o.user_id_production.name) or "",
                "production_group": ", ".join(o.production_group_ids.mapped("name")) if getattr(o, "production_group_ids", False) else "",
                # deposit & totals
                "has_deposit": bool(getattr(o, "has_deposit", False)),
                "deposit_amount": getattr(o, "deposit_amount", 0.0) or 0.0,
                "total_deposit_paid": getattr(o, "total_deposit_paid", 0.0) or 0.0,
                "amount_untaxed_original": getattr(o, "amount_untaxed_original", 0.0) or 0.0,
                "amount_tax": getattr(o, "amount_tax", 0.0) or 0.0,
                "amount_total": getattr(o, "amount_total", 0.0) or 0.0,
                "remaining_amount_display": getattr(o, "remaining_amount_display", 0.0) or 0.0,
                # design & production dates/flags
                "design_link": getattr(o, "design_link", "") or "",
                "design_done": bool(getattr(o, "design_done", False)),
                "design_assigned_date": self._iso_date(getattr(o, "design_assigned_date", False)),
                "design_deadline": self._iso_date(getattr(o, "design_deadline", False)),
                "production_deadline": self._iso_date(getattr(o, "production_deadline", False)),
                "production_is_delayed": bool(getattr(o, "production_is_delayed", False)),
                "production_delay_date": self._iso_date(getattr(o, "production_delay_date", False)),
                "production_delay_reason": getattr(o, "production_delay_reason", "") or "",
                # logistics
                "delivery_address": getattr(o, "delivery_address", "") or "",
                "installation_address": getattr(o, "installation_address", "") or "",
                # completion/invoice
                "is_order_completed": bool(getattr(o, "is_order_completed", False)),
                "all_invoices_paid": bool(getattr(o, "all_invoices_paid", False)),
                # các cột pancake_* & last_sync_date không có trong model thì để rỗng hoặc 0
                "pancake_order_id": getattr(o, "pancake_order_id", "") or "",
                "pancake_status_name": getattr(o, "pancake_status_name", "") or "",
                "pancake_status_key": getattr(o, "pancake_status_key", "") or "",
                "pancake_order_source_name": getattr(o, "pancake_order_source_name", "") or "",
                "pancake_page_name": getattr(o, "pancake_page_name", "") or "",
                "pancake_order_link": getattr(o, "pancake_order_link", "") or "",
                "pancake_customer_name": getattr(o, "pancake_customer_name", "") or "",
                "pancake_customer_phone": getattr(o, "pancake_customer_phone", "") or "",
                "pancake_shipping_full_name": getattr(o, "pancake_shipping_full_name", "") or "",
                "pancake_shipping_phone": getattr(o, "pancake_shipping_phone", "") or "",
                "pancake_shipping_address": getattr(o, "pancake_shipping_address", "") or "",
                "pancake_shipping_province": getattr(o, "pancake_shipping_province", "") or "",
                "pancake_shipping_district": getattr(o, "pancake_shipping_district", "") or "",
                "pancake_shipping_commune": getattr(o, "pancake_shipping_commune", "") or "",
                "pancake_items_length": getattr(o, "pancake_items_length", 0) or 0,
                "pancake_total_quantity": getattr(o, "pancake_total_quantity", 0) or 0,
                "pancake_total_price": getattr(o, "pancake_total_price", 0.0) or 0.0,
                "pancake_total_discount_amount": getattr(o, "pancake_total_discount_amount", 0.0) or 0.0,
                "pancake_shipping_fee": getattr(o, "pancake_shipping_fee", 0.0) or 0.0,
                "pancake_surcharge": getattr(o, "pancake_surcharge", 0.0) or 0.0,
                "pancake_money_to_collect": getattr(o, "pancake_money_to_collect", 0.0) or 0.0,
                "pancake_prepaid": getattr(o, "pancake_prepaid", 0.0) or 0.0,
                "pancake_order_currency_code": getattr(o, "pancake_order_currency_code", "") or "",
                "create_date_pancake": self._iso_date(getattr(o, "create_date_pancake", False)),
                "pancake_updated_at": self._iso_date(getattr(o, "pancake_updated_at", False)),
                "last_sync_date": self._iso_date(fields.Datetime.now()),
            })

            # --- ORDER LINES (khóa: line_id)
            for l in o.order_line:
                lines_payload.append({
                    "order_name": sodh or "",
                    "line_id": l.id,
                    "sequence": l.sequence or 0,
                    "product_default_code": (l.product_id and (l.product_id.default_code or "")) or "",
                    "product_name": l.name or (l.product_id and l.product_id.display_name) or "",
                    "product_uom": (l.product_uom and l.product_uom.name) or "",
                    "product_uom_qty": l.product_uom_qty or 0,
                    "price_unit": l.price_unit or 0.0,
                    "discount": l.discount or 0.0,
                    "display_type": l.display_type or "",
                    "is_deposit_line": bool(l.price_unit < 0) if not l.display_type else False,
                    "price_subtotal": l.price_subtotal or 0.0,
                    "price_tax": l.price_tax or 0.0,
                    "price_total": l.price_total or 0.0,
                })

        if not (orders_payload or lines_payload):
            return True

        r = requests.post(url, json={"orders": orders_payload, "order_lines": lines_payload}, timeout=30)
        r.raise_for_status()
        return True
    

    @api.model
    def push_gs_flat(self, limit=None):
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('gs.webapp.url.flat')
        if not url:
            return False

        push_ids = self.env.context.get('push_only_ids')
        if push_ids:
            orders = self.sudo().browse(push_ids)
        else:
            now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            if not (8 <= now_local.hour < 18):
                return True
            limit = int(limit or ICP.get_param('gs.push.limit', '200'))
            domain = [('order_state_custom', 'in', PAYMENT_STATES)]
            orders = self.sudo().search(domain, order='date desc, id desc', limit=limit)

        rows = []
        for o in orders:
            sodh = o.order_number or o.name
            ngay = (o.date or o.create_date or o.date_order)
            for l in o.order_line.filtered(lambda x: not x.display_type):
                rows.append({
                    "SoDH": sodh or "",
                    "Ngay": self._iso_date(ngay),
                    "KhachHang": o.partner_id.name or "",
                    "SDT": (o.partner_id.mobile or o.partner_id.phone or ""),
                    "DiaChiGiao": getattr(o, "delivery_address", "") or "",
                    "DiaChiThiCong": getattr(o, "installation_address", "") or "",
                    "TrangThai": getattr(o, "order_state_custom", o.state) or "",
                    "GiaoThiCong": getattr(o, "started_installation", False) or False,     # nếu cần đổi kiểu (Y/N) thì thay ở đây
                    "DeadlineSX": self._iso_date(getattr(o, "production_deadline", False)),
                    "Sale": o.user_id.name or "",
                    "ThietKe": (getattr(o, "user_id_design", False) and o.user_id_design.name) or "",
                    "SanXuat": (getattr(o, "user_id_production", False) and o.user_id_production.name) or "",
                    "NhomSX": ", ".join(o.production_group_ids.mapped("name")) if getattr(o, "production_group_ids", False) else "",
                    "Tong": o.amount_total or 0.0,
                    "CocDaThu": getattr(o, "total_deposit_paid", 0.0) or 0.0,
                    "ConLai": getattr(o, "remaining_amount_display", 0.0) or 0.0,
                    "HoanThanh": bool(getattr(o, "is_order_completed", False)),
                    "GhiChu": getattr(o, "note", "") or "",
                    "HangMuc": l.name or (l.product_id and l.product_id.display_name) or "",
                    "MaSP": (l.product_id and (l.product_id.default_code or "")) or "",
                    "SL": l.product_uom_qty or 0,
                    "DonGia": l.price_unit or 0.0,
                    "ChietKhau%": l.discount or 0.0,
                    "ThanhTien": l.price_total or 0.0,
                    # Khóa duy nhất:
                    "composite_id": f"{sodh}#{(l.product_id and (l.product_id.default_code or ''))}#{l.sequence or l.id}",
                })

        if not rows:
            return True

        CHUNK = 400
        for i in range(0, len(rows), CHUNK):
            r = requests.post(url, json={"rows": rows[i:i+CHUNK]}, timeout=20)
            r.raise_for_status()
        return True