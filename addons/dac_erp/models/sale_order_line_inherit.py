from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging
import re

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Bảng giá xe bán hàng theo (dài, rộng) cm và mã chất liệu.  Giá được
    # áp dụng ở onchange để nhân viên vẫn có thể nhập đơn giá riêng cho các
    # kích thước/chất liệu không nằm trong bảng này.
    _CART_UNIT_PRICES = {
        (80.0, 38.0): {
            'hiflex_silver': 950000.0,
            'formex': 1260000.0,
            'alu': 1760000.0,
        },
        (100.0, 48.0): {
            'hiflex_silver': 1135000.0,
            'formex': 1395000.0,
            'alu': 1890000.0,
        },
        (120.0, 58.0): {
            'hiflex_silver': 1460000.0,
            'formex': 1760000.0,
            'alu': 2290000.0,
        },
    }

    @api.model
    def _is_cart_order_from_context(self):
        order_id = self.env.context.get('default_order_id')
        if order_id:
            return self.env['sale.order'].browse(order_id).order_type == 'cart'
        return self.env.context.get('default_order_type') == 'cart'

    @api.model
    def _default_cart_material(self):
        return 'hiflex_silver' if self._is_cart_order_from_context() else False

    @api.model
    def _default_cart_dimension(self):
        if not self._is_cart_order_from_context():
            return False
        return self.env.ref('dac_erp.cart_dimension_80x40', raise_if_not_found=False)
    
    description = fields.Text(string='Nội dung')
    material = fields.Selection(
        selection=[
            ('hiflex_silver', 'Bạc Hiflex'),
            ('formex', 'Formex'),
            ('alu', 'Alu'),
        ],
        string='Chất liệu',
        default=_default_cart_material,
    )
    material_id = fields.Many2one(
        'dac.sale.material',
        string='Chất liệu',
        compute='_compute_material_id',
        inverse='_inverse_material_id',
        store=True,
        ondelete='set null',
    )
    accessory_ids = fields.Many2many(
        'dac.sale.order.accessory',
        'sale_order_line_accessory_rel',
        'sale_order_line_id',
        'accessory_id',
        string='Phụ kiện',
    )
    order_type = fields.Selection(related='order_id.order_type')
    product_type = fields.Selection(related='product_id.type')
    accessory_price_applied = fields.Float(
        string='Giá phụ kiện đã cộng', default=0.0, copy=True,
    )
    height = fields.Float(string='Chiều cao')
    width = fields.Float(string='Chiều ngang')
    length = fields.Float(string='Chiều dài')
    dimension = fields.Char(
        string='Kích thước',
        compute='_compute_dimension',
        inverse='_inverse_dimension',
        store=True,
    )
    dimension_constant = fields.Selection(
        selection=[
            ('80x38x195', '80 cm x 38 cm'),
            ('100x48x195', '1 m x 48 cm'),
            ('120x58x195', '1,2 m x 58 cm'),
        ],
        string='Kích thước',
        default='',
    )
    cart_dimension_id = fields.Many2one(
        'dac.cart.dimension',
        string='Kích thước',
        default=_default_cart_dimension,
        ondelete='restrict',
        help='Kích thước xe đẩy theo định dạng Chiều dài x Chiều rộng. Chiều cao luôn là 195 cm.',
    )

    def _get_cart_unit_price(self):
        """Trả giá xe theo bảng, cộng phần phụ thu của biến thể (nếu có)."""
        self.ensure_one()
        if not self.cart_dimension_id:
            return False

        material_code = self.material_id.code or self.material
        dimensions = (self.cart_dimension_id.length, self.cart_dimension_id.width)
        base_price = self._CART_UNIT_PRICES.get(dimensions, {}).get(material_code, False)
        if base_price is False:
            return False

        variant_surcharge = sum(
            self.product_id.product_template_attribute_value_ids.mapped('price_extra')
        )
        return base_price + variant_surcharge

    @api.depends('material')
    def _compute_material_id(self):
        materials_by_code = {
            material.code: material.id
            for material in self.env['dac.sale.material'].search([])
        }
        for line in self:
            line.material_id = materials_by_code.get(line.material, False)

    def _inverse_material_id(self):
        for line in self:
            line.material = line.material_id.code or False

    @api.depends('height', 'width', 'length')
    def _compute_dimension(self):
        for line in self:
            values = (line.height, line.width, line.length)
            line.dimension = ' x '.join(f'{value:g}' for value in values) if any(values) else ''

    def _inverse_dimension(self):
        for line in self:
            value = (line.dimension or '').strip()
            if not value:
                line.height = line.width = line.length = 0.0
                continue

            parts = re.split(r'\s*[xX]\s*', value)
            if len(parts) != 3:
                raise UserError("Kích thước phải có dạng: cao x ngang x dài")
            try:
                height, width, length = (float(part) for part in parts)
            except ValueError as error:
                raise UserError("Kích thước chỉ được chứa số, theo dạng: cao x ngang x dài") from error
            line.height = height
            line.width = width
            line.length = length

    @api.onchange('dimension_constant')
    def _onchange_dimension_constant(self):
        """Áp dụng bộ thông số cố định đã chọn cho xe đẩy."""
        dimensions = {
            '80x38x195': (80.0, 38.0, 195.0),
            '100x48x195': (100.0, 48.0, 195.0),
            '120x58x195': (120.0, 58.0, 195.0),
        }
        for line in self:
            if line.dimension_constant:
                line.length, line.width, line.height = dimensions[line.dimension_constant]

    @api.onchange('cart_dimension_id')
    def _onchange_cart_dimension(self):
        """Đồng bộ kích thước ngay khi chọn một bản ghi trong dropdown."""
        for line in self:
            if line.cart_dimension_id:
                line.length = line.cart_dimension_id.length
                line.width = line.cart_dimension_id.width
                line.height = line.cart_dimension_id.height

    @api.onchange('product_id', 'material', 'material_id', 'cart_dimension_id')
    def _onchange_cart_material_or_dimension(self):
        """Tự điền giá xe và phụ thu biến thể khi người dùng chọn dữ liệu."""
        for line in self:
            price = line._get_cart_unit_price()
            if price is not False:
                line.price_unit = price + sum(line.accessory_ids.mapped('price'))
                line.accessory_price_applied = sum(line.accessory_ids.mapped('price'))

    @api.onchange('accessory_ids')
    def _onchange_accessory_ids(self):
        for line in self:
            if line.display_type:
                continue
            total = sum(line.accessory_ids.mapped('price'))
            line.price_unit += total - line.accessory_price_applied
            line.accessory_price_applied = total

    def _sync_accessory_unit_price(self):
        """Apply only the difference, including writes from imports/API calls."""
        for line in self.filtered(lambda record: not record.display_type):
            total = sum(line.accessory_ids.mapped('price'))
            if total != line.accessory_price_applied:
                super(SaleOrderLine, line).write({
                    'price_unit': line.price_unit + total - line.accessory_price_applied,
                    'accessory_price_applied': total,
                })

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
        is_admin = user._dac_is_admin()
        is_manager = user._dac_is_manager()
        is_sale = user._dac_is_sale()

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
                # cấm xóa dòng cọc chỉ khi đã xác nhận cọc (is_deposit_confirmed)
                if any(l._is_deposit_related() for l in lines) and order.is_deposit_confirmed:
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
        uom_unit = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
        for vals in vals_list:
            # Đảm bảo name không bị rỗng nếu là ghi chú/section
            if vals.get('display_type') and not vals.get('name'):
                vals['name'] = 'Đầu mục' if vals['display_type'] == 'line_section' else 'Ghi chú'
            # A new editable line can be autosaved before a product is selected.
            # sale.order.line.name is required, so keep a temporary label until
            # the standard product onchange supplies the product description.
            if not vals.get('display_type') and not vals.get('name'):
                vals['name'] = 'Sản phẩm'
            # Dòng tự do (không product_id, không section/note): gán UOM mặc định để tránh lỗi ORM
            if (not vals.get('product_id') and not vals.get('display_type')
                    and not vals.get('product_uom') and uom_unit):
                vals['product_uom'] = uom_unit.id
        lines = super().create(vals_list)
        lines._sync_accessory_unit_price()
        return lines

    def write(self, vals):
        # Ngăn việc xóa display_type
        if 'display_type' in vals and not vals['display_type']:
            current_display_type = self.display_type
            if current_display_type in ('line_section', 'line_note'):
                vals.pop('display_type')
        result = super().write(vals)
        if 'accessory_ids' in vals:
            self._sync_accessory_unit_price()
        return result

    @api.onchange('display_type')
    def _onchange_display_type(self):
        if self.display_type:
            self.product_id = False
            self.product_uom_qty = 0.0
            self.price_unit = 0.0
            self.product_uom = False
