from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    description = fields.Text(string='Nội dung')
    height = fields.Float(string='Chiều cao')
    width = fields.Float(string='Chiều ngang')

    # --- Helpers ---
    def _is_deposit_related(self):
        """Nhận diện 3 dòng thuộc 'khoản cọc' của anh."""
        self.ensure_one()
        name = (self.name or '').lower()
        is_section_note_coc = (
            self.display_type in ('line_section', 'line_note')
            and any(k in name for k in ['khoản cọc', 'tiền cọc', 'deposit', 'đặt cọc'])
        )
        is_deposit_product = (
            not self.display_type and (
                self.price_unit < 0 or
                (self.product_id and self.product_id.default_code == 'DEPOSIT')
            )
        )
        return is_section_note_coc or is_deposit_product

    def unlink(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        is_manager = user.has_group('dac_erp.group_dac_erp_manager')
        is_sale = user.has_group('dac_erp.group_dac_erp_sale')

        # III) Quyền xóa
        if not (is_admin or is_manager or is_sale):
            raise AccessError("Bạn không thể thực hiện thao tác này!\nLiên hệ quản lý hoặc quản trị viên để được trợ giúp!")

        # Gom line theo đơn
        lines_by_order = {}
        for l in self:
            lines_by_order.setdefault(l.order_id, self.env['sale.order.line'])
            lines_by_order[l.order_id] |= l

        # Helper định dạng tiền (1.234.567 ₫, không phần thập phân)
        def _vnd(order, amt):
            return f"{amt:,.0f}".replace(",", ".") + " ₫"

        # I) Kiểm soát cho SALE + snapshot để LOG
        per_order_log = {}
        EPS = 1e-6
        for order, lines in lines_by_order.items():
            if is_sale and not (is_admin or is_manager):
                # cấm xóa 3 dòng "khoản cọc"
                if any(l._is_deposit_related() for l in lines):
                    raise AccessError("Bạn không thể thực hiện thao tác này!\nLiên hệ quản lý hoặc quản trị viên để được trợ giúp!")
                # không xóa vượt tiền cọc đã thanh toán
                positive_delete_total = sum(l.price_total for l in lines if not l.display_type and l.price_total > 0)
                remaining_after = order.amount_total - positive_delete_total
                if remaining_after + EPS < order.total_deposit_paid:
                    raise UserError("Không thể xóa: Tổng tiền hàng còn lại sẽ thấp hơn TIỀN CỌC đã thanh toán.")

            # Chuẩn bị list chi tiết từng dòng theo yêu cầu
            items = []
            for l in lines:
                if l.display_type == 'line_section':
                    loai = 'đầu mục'
                elif l.display_type == 'line_note':
                    loai = 'ghi chú'
                else:
                    loai = 'sản phẩm'
                name = l.product_id.display_name if l.product_id else (l.name or '')
                thue = ", ".join(l.tax_id.mapped('name')) if l.tax_id else "Không"
                items.append(
                    f"{loai} {name}\n"
                    f"(nội dung: {l.description or ''}, chiều cao: {l.height or 0}, "
                    f"chiều ngang: {l.width or 0}, số lượng: {l.product_uom_qty}, "
                    f"đơn giá: {_vnd(order, l.price_unit)}, Thuế: {thue}, "
                    f"Thành tiền: {_vnd(order, l.price_total)})"
                )

            per_order_log[order] = {
                "items": items,
                "count": len(lines),
                "before_total": order.amount_total,
            }

        # Thực xóa: tắt tracking/notify + gắn cờ để write() không log "Tổng"
        ctx = dict(self._context,
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_post_autofollow=False,
                mail_notify_force_send=False,
                mail_notify_noemail=True,
                dac_skip_total_log=True)  # dùng ở sale_order.py
        res = super(SaleOrderLine, self.with_context(ctx)).unlink()

        # II) Ghi 1 dòng log duy nhất / đơn (note nội bộ, không email, không HTML)
        for order, data in per_order_log.items():
            before = data["before_total"]
            order.invalidate_recordset()
            body = (
                f"{user.display_name} đã xoá {data['count']} dòng:\n"
                + "\n".join(f"- {s}" for s in data["items"])
                + f"\nTổng: {_vnd(order, before)} → {_vnd(order, order.amount_total)}"
            )
            order._message_log(body=body)

        return res
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Nếu là dòng ghi chú (không sản phẩm, giá = 0, có tên, không display_type) thì gán là line_note
            if (not vals.get('product_id') and vals.get('name') and 
                not vals.get('display_type') and vals.get('price_unit', 0) == 0):
                vals['display_type'] = 'line_note'
                vals['product_uom_qty'] = 0
            # Nếu là dòng section (tùy ý, nếu bạn muốn giữ logic cũ)
            elif (not vals.get('product_id') and vals.get('name') and 
                  not vals.get('display_type') and vals.get('price_unit', 0) == 0 and 
                  ('mục' in vals.get('name', '').lower() or 'section' in vals.get('name', '').lower())):
                vals['display_type'] = 'line_section'
                vals['product_uom_qty'] = 0
            # Đảm bảo name không bị rỗng nếu là ghi chú/section
            if vals.get('display_type') and not vals.get('name'):
                vals['name'] = vals.get('display_type') == 'line_section' and 'Đầu mục' or 'Ghi chú'
        return super().create(vals_list)

    def write(self, vals):
        # Ngăn việc xóa display_type
        if 'display_type' in vals and not vals['display_type']:
            current_display_type = self.display_type
            if current_display_type in ('line_section', 'line_note'):
                vals.pop('display_type')
        return super().write(vals)

    @api.onchange('display_type')
    def _onchange_display_type(self):
        if self.display_type:
            self.product_id = False
            self.product_uom_qty = 0.0
            self.price_unit = 0.0
            self.product_uom = False


