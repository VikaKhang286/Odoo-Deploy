from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
from datetime import date, timedelta


_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):

    _inherit = 'sale.order'

    # Trạng thái đơn hàng tùy chỉnh
    order_state_custom = fields.Selection([
        ('quotation', 'Báo giá'),
        ('deposit', 'Đặt cọc'),
        ('production', 'Sản xuất'),
        ('installation', 'Thi công - lắp đặt'),
        ('delivery', 'Giao hàng'),
        ('payment', 'Thu tiền'),
        ('completed', 'Hoàn thành'),
        ('cancel', 'Hủy'),
    ], string='Trạng thái đơn hàng', default='quotation', tracking=True)

    date = fields.Datetime(string='Ngày đơn hàng', default=fields.Datetime.now)

    # Sale phụ trách
    user_id = fields.Many2one(
        'res.users',
        string='Sale phụ trách',
        domain=[],
        default=lambda self: self.env.user,
        copy=True,
        tracking=True,
    )

    # Thiết kế
    user_id_design = fields.Many2one(
        'res.users',
        string='Người thiết kế',
        domain=lambda self: self.env['res.users']._dac_exact_role_domain('design'),
        tracking=True,
    )

    # Sản xuất
    user_id_production = fields.Many2one(
        'res.users',
        string='Người sản xuất',
        domain=lambda self: self.env['res.users']._dac_exact_role_domain('production'),
        tracking=True,
    )

    # Nhóm sản xuất (nhiều người)
    production_group_ids = fields.Many2many(
        'res.users',
        'sale_order_production_user_rel',   # tên bảng quan hệ M2M
        'order_id',                         # cột FK về sale.order
        'user_id',                          # cột FK về res.users
        string='Nhóm sản xuất',
        domain=lambda self: self.env['res.users']._dac_exact_role_domain('production'),
        tracking=True,
        help='Những người tham gia sản xuất, Có thể bao gồm người phụ trách sản xuất.',
    )

    # Trường so sánh với file số đơn excel
    order_number = fields.Char(string="Số đặt hàng",
                                     default=False,
                                     copy=False,
                                     help="Số phiếu ĐH",
                                     tracking=True)

    # Tiêu đề và mô tả ngắn gọn do AI tóm tắt
    order_title = fields.Char(string='Tiêu đề đơn hàng', copy=False)
    order_summary = fields.Text(string='Mô tả ngắn gọn', copy=False)

    # Trạng thái xác nhận
    is_quotation_confirmed = fields.Boolean(string="Đã xác nhận báo giá", default=False)
    is_deposit_confirmed = fields.Boolean(string="Đã xác nhận đặt cọc", default=False)
    is_production_confirmed = fields.Boolean(string="Đã xác nhận sản xuất", default=False)
    is_delivery_confirmed = fields.Boolean(string="Đã xác nhận giao hàng", default=False)
    is_installation_confirmed = fields.Boolean(string="Đã xác nhận thi công/lắp đặt", default=False)
    is_payment_confirmed = fields.Boolean(string="Đã xác nhận thanh toán", default=False)

    # Đặt cọc
    has_deposit = fields.Boolean(string="Có đặt cọc?", default=True, tracking=True)
    deposit_amount = fields.Float(string="Tiền cọc", default=0.0)

    # Tiến trình sản xuất
    production_deadline = fields.Date(string="Deadline sản xuất", tracking=True)

    # --- flags đánh dấu đã chạm các mốc quy trình ---
    reached_production = fields.Boolean(default=False, copy=False)
    left_production_date = fields.Datetime(string="Ngày rời SX", tracking=True)
    started_delivery   = fields.Boolean(default=False, copy=False)
    started_installation = fields.Boolean(default=False, copy=False)

    # --- Sản xuất trễ ---
    production_is_delayed = fields.Boolean(
        string="Sản xuất bị trễ?", tracking=True, default=False,
    )
    production_delay_date = fields.Date(
        string="Ngày trễ", tracking=True,
    )
    production_delay_reason = fields.Text(
        string="Lý do trễ", tracking=True,
    )

    @api.constrains('promotion_amount')
    def _check_promotion_amount(self):
        for order in self:
            if order.promotion_amount < 0:
                raise ValidationError("Số tiền khuyến mãi không được âm!")

    @api.onchange('production_is_delayed')
    def _onchange_production_is_delayed(self):
        for o in self:
            if not o.production_is_delayed:
                o.production_delay_date = False
                o.production_delay_reason = False

    @api.constrains('production_is_delayed',
                'production_delay_date',
                'production_delay_reason',
                'production_deadline')
    def _check_production_delay(self):
        """
        - KHÔNG ép người dùng phải nhập ngay khi bật công tắc.
        - Chỉ validate nếu đã nhập MỘT TRONG HAI trường (date/reason),
        còn thiếu thì yêu cầu đủ cặp.
        - Các ràng buộc so sánh ngày vẫn giữ.
        """
        for o in self:
            if not o.production_is_delayed:
                continue

            # Nếu chưa nhập gì -> cho phép lưu tạm, không raise ở đây
            if not o.production_delay_date and not (o.production_delay_reason or '').strip():
                continue

            # Đã nhập 1 trong 2 thì bắt buộc đủ cặp
            if not o.production_delay_date or not (o.production_delay_reason or '').strip():
                raise ValidationError(_("Khi nhập thông tin trễ, phải điền cả 'Ngày trễ' và 'Lý do trễ'."))

            # Ngày trễ PHẢI LỚN HƠN deadline (không được bằng/nhỏ hơn)
            if o.production_deadline and o.production_delay_date <= o.production_deadline:
                raise ValidationError(_("Ngày trễ phải sau 'Ngày hoàn tất'."))

            # Nếu chưa có deadline thì ngày trễ phải lớn hơn hôm nay
            if not o.production_deadline and o.production_delay_date <= date.today():
                raise ValidationError(_("Ngày trễ phải sau ngày hiện tại."))

    # Tiến trình giao hàng
    delivery_address = fields.Text(string="Địa chỉ giao hàng", tracking=True)

    # Tiến trình thi công - lắp đặt
    installation_address = fields.Text(string="Địa chỉ thi công/lắp đặt", tracking=True)

    # Trạng thái hoàn thành đơn hàng
    is_order_completed = fields.Boolean(string="Đơn hàng đã hoàn thành", default=False)

    # Thông tin báo giá mới nhất để hiển thị ở đầu list
    latest_quotation_info = fields.Char(
        string="Báo giá mới nhất",
        compute="_compute_latest_quotation_info",
        store=False
    )

    # Kiểm tra tất cả hóa đơn đã thanh toán
    all_invoices_paid = fields.Boolean(
        string="Tất cả hóa đơn đã thanh toán",
        compute="_compute_all_invoices_paid",
        store=False
    )

    # Số tiền còn lại cần thu (hiển thị cho user)
    remaining_amount_display = fields.Monetary(
        string="Số tiền còn lại",
        compute="_compute_remaining_amount_display",
        currency_field='currency_id',
        store=False
    )

    # Tổng tiền cọc đã thanh toán
    total_deposit_paid = fields.Monetary(
        string="Cọc đã thanh toán",
        compute="_compute_total_deposit_paid",
        currency_field='currency_id',
        store=False
    )

    # Số tiền sản phẩm gốc (chưa trừ cọc)
    amount_untaxed_original = fields.Monetary(
        string="Thành tiền",
        compute="_compute_amount_untaxed_original",
        currency_field='currency_id',
        store=False
    )

    # Override amount_tax để chỉ tính từ dòng có giá dương
    amount_tax = fields.Monetary(
        string="Thuế",
        compute="_compute_amount_tax_positive_lines",
        currency_field='currency_id',
        store=False
    )

    # Override amount_total để tính đúng từ dòng có giá dương
    amount_total = fields.Monetary(
        string="Tổng",
        compute="_compute_amount_total_positive_lines",
        currency_field='currency_id',
        store=False
    )

    # Khuyến mãi toàn đơn (số tiền giảm cố định)
    promotion_amount = fields.Monetary(
        string="Khuyến mãi",
        currency_field='currency_id',
        default=0.0,
        tracking=True,
        help="Số tiền giảm cố định áp dụng cho toàn bộ đơn hàng.",
    )
    promotion_note = fields.Char(
        string="Nội dung khuyến mãi",
        tracking=True,
        help="Ghi chú nội dung khuyến mãi (VD: Khách VIP, giới thiệu...).",
    )

    shipping_fee = fields.Monetary(
        string="Phí vận chuyển",
        currency_field='currency_id',
        default=0.0,
        tracking=True,
    )

    # Field đánh dấu đơn 0đ (cơ hội) - STORED để dùng trong domain filter
    is_zero_amount = fields.Boolean(
        string="Đơn 0đ (Cơ hội)",
        compute="_compute_is_zero_amount",
        store=True,
        help="Đánh dấu đơn hàng có giá trị = 0 (đơn cơ hội từ Pancake tự tạo)"
    )

    # Computed field để tự động kiểm tra và thêm dòng đặt cọc
    auto_check_deposit = fields.Boolean(string="Auto Check Deposit", compute="_compute_auto_check_deposit", store=False)

    # Field để kiểm tra có được phép xóa sản phẩm không (cho sale user)
    can_delete_products = fields.Boolean(string="Can Delete Products", compute="_compute_can_delete_products", store=False)

    @api.onchange('partner_id')
    def _onchange_partner_id_address(self):
        """Tự động điền địa chỉ giao hàng từ khách hàng"""
        if self.partner_id and not self.delivery_address:
            # Tìm địa chỉ delivery của partner
            delivery_partner = self.partner_id.child_ids.filtered(lambda c: c.type == 'delivery')
            if delivery_partner:
                # Sử dụng địa chỉ delivery đầu tiên
                partner = delivery_partner[0]
            else:
                # Fallback: sử dụng địa chỉ chính của partner
                partner = self.partner_id

            # Tạo địa chỉ đầy đủ
            address_parts = []
            if partner.street:
                address_parts.append(partner.street)
            if partner.street2:
                address_parts.append(partner.street2)
            if partner.city:
                address_parts.append(partner.city)
            if partner.state_id:
                address_parts.append(partner.state_id.name)
            if partner.country_id:
                address_parts.append(partner.country_id.name)

            if address_parts:
                self.delivery_address = ', '.join(address_parts)

    @api.onchange('order_type')
    def _onchange_order_type_cart(self):
        """Điền sẵn xe bán hàng khi chọn đơn xe đẩy."""
        if self.order_type == 'cart':
            self.fulfillment_method = 'delivery'
            product = self._get_default_cart_product()
            if product and not self.order_line.filtered(
                lambda line: not line.display_type
                and line.product_id.product_tmpl_id == product.product_tmpl_id
            ):
                self.order_line = [fields.Command.create(
                    self._prepare_default_cart_line(product)
                )]

    @api.model
    def _get_default_cart_product(self):
        return self.env['product.product'].search([
            ('product_tmpl_id.name', '=', 'Xe bán hàng gấp gọn'),
            ('type', '=', 'cart'),
            ('sale_ok', '=', True),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)

    def _prepare_default_cart_line(self, product):
        dimension = self.env.ref('dac_erp.cart_dimension_80x40', raise_if_not_found=False)
        values = {
            'product_id': product.id,
            'name': product.get_product_multiline_description_sale(),
            'product_uom': product.uom_id.id,
            'product_uom_qty': 1.0,
            'material': 'hiflex_silver',
            'cart_dimension_id': dimension.id if dimension else False,
            'sequence': min(self.order_line.mapped('sequence') or [10]) - 1,
        }
        line = self.env['sale.order.line'].new(values)
        line._onchange_cart_dimension()
        values.update({'length': line.length, 'width': line.width, 'height': line.height})
        price = line._get_cart_unit_price()
        if price is not False:
            values['price_unit'] = price
        return values

    def read(self, fields=None, load='_classic_read'):
        """Override read để kiểm tra và thêm dòng đặt cọc khi cần thiết"""
        result = super().read(fields, load)

        # Chỉ kiểm tra khi đọc toàn bộ hoặc đọc order_line
        if not fields or 'order_line' in fields or any('order_line' in str(f) for f in fields):
            for record in self:
                # Kiểm tra có hóa đơn cọc đã thanh toán không
                deposit_invoices = self.env['account.move'].search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', record.name),
                    ('dac_deposit_invoice', '=', True),
                    ('payment_state', '=', 'paid')
                ])
                if deposit_invoices:
                    # Kiểm tra đã có dòng đặt cọc chưa
                    deposit_line = record.order_line.filtered(lambda l: not l.display_type and l.price_unit < 0)
                    if not deposit_line:
                        #_logger.info(f"Auto-sync: Thêm dòng đặt cọc cho order {record.name} khi đọc dữ liệu")
                        deposit_amount = abs(deposit_invoices[0].amount_total)
                        record.add_deposit_order_line(deposit_amount, invoice=deposit_invoices[0])

                        # Force reload để đảm bảo UI cập nhật (Odoo 18 compatible)
                        record.invalidate_recordset()

        return result

    def write(self, vals):
        """Override write để trigger kiểm tra deposit khi cần"""
        # 0) ĐƠN ĐÃ HỦY
        # Cho phép bypass khi context có 'allow_reopen_cancelled' = True
        # (dùng cho MCP reopen action, đã có audit log + guard riêng)
        if not self.env.context.get('allow_reopen_cancelled'):
            if any(rec.order_state_custom == 'cancel' for rec in self):
                raise UserError(_("Đơn hàng đã hủy! không thể thay đổi!"))

        # Nếu bỏ chọn ưu tiên, tự động bỏ chọn ưu tiên trong ngày
        if 'is_priority' in vals and not vals['is_priority']:
            vals['is_priority_today'] = False
        # 1) Bảo vệ các trường trễ
        protected_keys = {'production_is_delayed', 'production_delay_date', 'production_delay_reason'}
        if protected_keys.intersection(vals.keys()):
            for rec in self:
                if rec.is_delivery_confirmed or rec.is_installation_confirmed \
                    or rec.order_state_custom in ('delivery', 'installation', 'payment', 'completed'):
                        raise UserError(_("Không thể sửa thông tin trễ sau khi đơn đã chuyển sang Giao hàng."))

        # 2) Ghi nhận xem có chạm đến ảnh hay không (áp dụng cho nhiều record)
        image_key_present = 'production_image' in vals
        image_removed = image_key_present and not vals.get('production_image')   # None/False → xoá

        # 3) Gọi super() viết dữ liệu
        result = super().write(vals)

        # 4) Nếu có thay đổi ảnh, log vào chatter
        if image_key_present:
            for rec in self:
                rec._post_production_image_log('remove' if image_removed else 'upload')

        # 5) Nếu thay đổi order_line, đồng bộ lại dòng cọc
        if 'order_line' in vals:
            for record in self:
                record._auto_sync_deposit_line()

        if 'is_priority_today' in vals:
            today = fields.Date.context_today(self)
            for rec in self:
                if rec.order_state_custom == 'deposit' and not rec.design_done:
                    base_date = rec.design_assigned_date or today
                    vals2 = {}
                    # Bảo đảm có ngày phân công
                    if not rec.design_assigned_date:
                        vals2['design_assigned_date'] = base_date
                    # Luôn cập nhật lại deadline theo rule ưu tiên/ngày thường
                    vals2['design_deadline'] = base_date if rec.is_priority_today else (base_date + timedelta(days=3))
                    if vals2:
                        super(SaleOrder, rec.with_context(skip_design_autoset=True)).write(vals2)

        if 'user_id_design' in vals:
            today = fields.Date.context_today(self)
            for rec in self:
                # chỉ set khi đang gán designer (không phải bỏ gán) và chưa có ngày phân công
                if vals.get('user_id_design') and not rec.design_assigned_date:
                    # tránh đệ quy sang block autoset phía dưới
                    super(SaleOrder, rec.with_context(skip_design_autoset=True)).write({
                        'design_assigned_date': today
                    })

        if "order_state_custom" in vals:
            new_state = vals["order_state_custom"]
            now = fields.Datetime.now()
            for rec in self:
                # Lần đầu vào pha sản xuất
                if new_state == "production" and not rec.reached_production:
                    rec.reached_production = True
                # Từ production rời sang pha khác → đóng dấu rời SX
                if rec.order_state_custom == "production" and new_state != "production":
                    rec.left_production_date = now

        # 6) === Auto set ngày giao & deadline thiết kế khi vào Đặt cọc / Sản xuất ===
        if not self.env.context.get('skip_design_autoset'):
            today = fields.Date.context_today(self)
            for rec in self:
                # Chạy khi đang ở deposit và chưa hoàn tất thiết kế
                if rec.order_state_custom == 'deposit' and not rec.design_done:
                    base_date = rec.design_assigned_date or today  # CHỈ dựa vào ngày phân công

                    vals2 = {}
                    # Nếu chưa có ngày phân công mà đã vào luồng thiết kế → gán hôm nay
                    if not rec.design_assigned_date:
                        vals2['design_assigned_date'] = base_date
                    # Nếu chưa có deadline → dựa trên base_date và ưu tiên trong ngày
                    if not rec.design_deadline:
                        vals2['design_deadline'] = (
                            base_date if rec.is_priority_today else (base_date + timedelta(days=3))
                        )
                    if vals2:
                        super(SaleOrder, rec.with_context(skip_design_autoset=True)).write(vals2)

        # Nếu đổi lead hoặc đổi nhóm → dọn cho chắc
        if 'user_id_production' in vals or 'production_group_ids' in vals:
            for rec in self:
                if rec.user_id_production and rec.user_id_production in rec.production_group_ids:
                    rec.production_group_ids = [(3, rec.user_id_production.id)]

        # Đồng bộ task khi phân công thiết kế hoặc cập nhật deadline
        # Bỏ qua khi sync ngược (task → order) đang chạy, tránh vòng lặp.
        _DESIGN_TRIGGER = frozenset(['user_id_design', 'design_deadline'])
        _PROD_TRIGGER = frozenset(['user_id_production', 'production_deadline'])
        if not self.env.context.get('dac_skip_task_sync'):
            if _DESIGN_TRIGGER & vals.keys():
                for rec in self:
                    rec._sync_design_task()
            if _PROD_TRIGGER & vals.keys():
                for rec in self:
                    rec._sync_production_task()

        return result

    @api.model
    def default_get(self, fields_list):
        """Override để trigger kiểm tra deposit khi tạo mới hoặc load form và gán người phụ trách"""
        result = super().default_get(fields_list)

        # Đảm bảo người tạo đơn hàng sẽ là người phụ trách (user_id)
        if 'user_id' in fields_list and not result.get('user_id'):
            result['user_id'] = self.env.user.id

        if ('order_line' in fields_list and not result.get('order_line')
                and result.get('order_type', self.env.context.get('default_order_type')) == 'cart'):
            product = self._get_default_cart_product()
            if product:
                result['order_line'] = [fields.Command.create(
                    self._prepare_default_cart_line(product)
                )]

        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Override create để đảm bảo người tạo đơn hàng sẽ là người phụ trách và set đúng giờ cho trường date"""
        for vals in vals_list:
            # Nếu không có user_id được set, gán người tạo làm người phụ trách
            if not vals.get('user_id'):
                vals['user_id'] = self.env.user.id
            # Nếu chưa có date, set date đúng giờ hiện tại
            if not vals.get('date'):
                vals['date'] = fields.Datetime.now()
            if not vals.get('is_priority'):
                vals['is_priority_today'] = False
        records = super().create(vals_list)
        for rec in records:
            if rec.user_id_production and rec.user_id_production in rec.production_group_ids:
                rec.production_group_ids = [(3, rec.user_id_production.id)]
        return records

    # Cho nút mở hội thoại
    conversation_id = fields.Many2one(
        'page.fm.conversation', string='Conversation', index=True
    )
    conversation_count = fields.Integer(
        string='Conversations', compute='_compute_conversation_count'
    )

    # Danh sách conversations chi tiết để hiển thị buttons
    conversation_buttons_html = fields.Html(
        string='Conversation Buttons HTML', compute='_compute_conversation_buttons_html', store=False
    )

    # Thông tin bổ sung
    # Số điện thoại đơn hàng
    customer_address = fields.Char(
        string='Địa chỉ', compute='_compute_customer_address',
        inverse='_inverse_customer_address', readonly=False,
        help='Nhập theo dạng: Đường, Phường, Thành phố (Tỉnh), Quốc gia.',
    )
    customer_address_manual = fields.Char(copy=True)
    phone = fields.Char(string="Số điện thoại", related='partner_id.phone', store=True, readonly=False, tracking=True)

    @api.depends(
        'partner_id', 'partner_id.street', 'partner_id.street2', 'partner_id.city',
        'partner_id.state_id.name', 'partner_id.country_id.name', 'customer_address_manual',
    )
    def _compute_customer_address(self):
        """Hiển thị địa chỉ theo định dạng: Đường, Phường, Thành phố (Tỉnh), Quốc gia."""
        for order in self:
            partner = order.partner_id
            if order.customer_address_manual:
                order.customer_address = order.customer_address_manual
                continue
            if not partner:
                order.customer_address = False
                continue

            address_parts = [
                partner.street,
                partner.street2,
                partner.city,
                partner.state_id.name,
                partner.country_id.name,
            ]
            order.customer_address = ', '.join(part for part in address_parts if part)

    @api.onchange('customer_address')
    def _onchange_customer_address_draft(self):
        """Giữ địa chỉ người dùng nhập trước khi họ chọn khách hàng."""
        for order in self:
            order.customer_address_manual = order.customer_address or False

    def _inverse_customer_address(self):
        """Lưu địa chỉ nhập ở đơn hàng vào đúng các cột của hồ sơ khách hàng."""
        for order in self:
            address = (order.customer_address or '').strip()
            order.customer_address_manual = address or False
            if not order.partner_id or not address:
                continue

            parts = [part.strip() for part in address.split(',') if part.strip()]
            if len(parts) < 4:
                raise UserError(
                    'Địa chỉ phải có dạng: Đường, Thành phố, Tên Trạng thái, Quốc gia.'
                )

            street = ', '.join(parts[:-3])
            city, state_name, country_name = parts[-3:]
            country = self.env['res.country'].search([
                ('name', '=ilike', country_name),
            ], limit=1)
            if not country:
                raise UserError('Không tìm thấy quốc gia: %s.' % country_name)

            state = self.env['res.country.state'].search([
                ('name', '=ilike', state_name),
                ('country_id', '=', country.id),
            ], limit=1)
            if not state:
                # Dữ liệu chuẩn dùng "TP Hồ Chí Minh", còn người dùng thường
                # nhập "TP. Hồ Chí Minh". Bỏ dấu chấm để đối chiếu linh hoạt.
                normalized_state_name = ' '.join(state_name.replace('.', ' ').split())
                state = self.env['res.country.state'].search([
                    ('name', '=ilike', normalized_state_name),
                    ('country_id', '=', country.id),
                ], limit=1)
            if not state:
                raise UserError(
                    'Không tìm thấy trạng thái "%s" thuộc quốc gia "%s".'
                    % (state_name, country_name)
                )

            order.partner_id.write({
                'street': street,
                'street2': False,
                'city': city,
                'state_id': state.id,
                'country_id': country.id,
            })

    # Đơn hàng ưu tiên và ưu tiên trong ngày
    is_priority = fields.Boolean(string="Đơn hàng ưu tiên", default=False, tracking=True)
    is_priority_today = fields.Boolean(string="Ưu tiên trong ngày", default=False, tracking=True)

    # Nếu tắt 'Ưu tiên' thì tự động tắt 'Ưu tiên trong ngày'
    @api.onchange('is_priority')
    def _onchange_is_priority(self):
        for rec in self:
            if not getattr(rec, 'is_priority', False):
                rec.is_priority_today = False

    # Field nhập link thiết kế
    design_link = fields.Char(string="Link thiết kế",
                              help="Nhập đường link thiết kế (Google Drive, Figma, v.v.)",
                              tracking=True)

    # Hình ảnh cho sản xuất
    production_image = fields.Binary(string="Ảnh sản xuất",
                                     attachment=True,
                                     help="Tải lên hình ảnh liên quan đến sản xuất (bản vẽ, mẫu, v.v.)")

    # ==== HOÀN TẤT THIẾT KẾ & DEADLINE ====
    design_assigned_date = fields.Date(string="Ngày giao thiết kế", tracking=True)
    design_deadline = fields.Date(string="Deadline thiết kế",
                                  tracking=True,
                                  help="Hạn chót hoàn tất thiết kế")

    design_done = fields.Boolean(
        string="Đã hoàn tất thiết kế", default=False, copy=False, tracking=True
    )
    design_done_date = fields.Datetime(
        string="Thời điểm hoàn tất", readonly=True, copy=False
    )
    design_done_user_id = fields.Many2one(
        'res.users', string="Người xác nhận hoàn tất", readonly=True, copy=False
    )

    # Deadline mặc định 3 ngày sau khi tạo đơn
    @api.onchange('user_id_design', 'design_assigned_date', 'is_priority_today')
    def _onchange_default_design_deadline(self):
        """Khi gán designer hoặc set ngày phân công mà chưa có deadline → tự set:
        - 'Trong ngày' → hôm nay
        - bình thường → +3 ngày
        """
        for order in self:
            # Nếu có designer mà chưa có ngày phân công → lấy hôm nay
            if order.user_id_design and not order.design_assigned_date:
                order.design_assigned_date = fields.Date.context_today(order)
            if order.design_assigned_date and not order.design_deadline:
                base = order.design_assigned_date
                order.design_deadline = base if order.is_priority_today else base + timedelta(days=3)

    # --- Cờ hoàn tất sản xuất ---
    production_done = fields.Boolean(string="Đã hoàn tất sản xuất", default=False, copy=False, tracking=True)
    production_done_date = fields.Datetime(string="Thời điểm hoàn tất", readonly=True, copy=False)
    production_done_user_id = fields.Many2one('res.users', string="Người xác nhận hoàn tất", readonly=True, copy=False)

    @api.onchange('user_id_production')
    def _onchange_user_id_production(self):
        for rec in self:
            if rec.user_id_production:
                # loại bỏ lead khỏi nhóm ngay trên form
                rec.production_group_ids -= rec.user_id_production

    # --- Chặn tracking tổng khi được yêu cầu (từ unlink order line) ---
    def _message_track(self, tracked_fields, initial):
        """
        Odoo 18: mail.thread sẽ gọi hook này để tạo log thay đổi.
        Khi context có 'dac_skip_total_log', loại bỏ amount_untaxed/amount_total
        để không bắn 2 dòng 'Tổng' và 'Số tiền trước thuế'.
        """
        if self.env.context.get('dac_skip_total_log'):
            tracked_fields = {
                k: v for k, v in tracked_fields.items()
                if k not in ('amount_untaxed', 'amount_total')
            }
        return super(SaleOrder, self)._message_track(tracked_fields, initial)

    def _mail_track(self, tracked_fields, initial):
        """
        Một số luồng trong 18 vẫn đi qua _mail_track; lọc giống hệt để chắc ăn.
        """
        if self.env.context.get('dac_skip_total_log'):
            tracked_fields = {
                k: v for k, v in tracked_fields.items()
                if k not in ('amount_untaxed', 'amount_total')
            }
        return super(SaleOrder, self)._mail_track(tracked_fields, initial)

    # Override field amount_untaxed để dùng compute mới
    amount_untaxed = fields.Monetary(
        string="Số tiền trước thuế",
        compute="_compute_amount_untaxed_positive_lines",
        currency_field='currency_id',
        store=False,
        tracking=True,      # muốn hiện 2 bullet đúng số → để True
        # tracking=False     # nếu muốn ẩn hẳn 2 bullet → dùng dòng này thay cho tracking=True
    )

    deposit_invoice_count = fields.Integer(string="Số hóa đơn đặt cọc", compute="_compute_deposit_invoice_count")
    total_invoice_count = fields.Integer(string="Tổng số hóa đơn", compute="_compute_total_invoice_count")
    has_paid_deposit_invoice = fields.Boolean(string="Có hóa đơn cọc đã thanh toán", compute="_compute_has_paid_deposit_invoice")
    has_final_invoice = fields.Boolean(string="Có hóa đơn thanh toán cuối", compute="_compute_has_final_invoice")
    has_paid_final_invoice = fields.Boolean(string="Có hóa đơn cuối đã thanh toán", compute="_compute_has_paid_final_invoice")

    #========== Phân loại đơn hàng: đơn chung / đơn xe đẩy ===========
    order_type = fields.Selection([
        ('general', 'Đơn hàng chung'),
        ('cart', 'Đơn hàng xe đẩy'),
    ], string='Loại đơn hàng', default='general', tracking=True,
       help="Đơn xe đẩy không cần thi công, mặc định hình thức là Giao hàng.")

    # ===== Trường riêng cho đơn hàng xe đẩy =====
    cart_sample_image = fields.Binary(
        string="Hình ảnh mẫu xe", attachment=True,
        help="Hình ảnh mẫu xe đẩy của khách hàng",
    )
    cart_design_approval_image = fields.Binary(
        string="Hình ảnh duyệt thiết kế", attachment=True,
        help="Hình ảnh thiết kế xe đẩy đã được khách duyệt",
    )
    cart_design_link = fields.Char(
        string="Link file thiết kế",
        help="Đường link file thiết kế xe đẩy (Google Drive, Figma, v.v.)",
        tracking=True,
    )
    cart_design_description = fields.Text(
        string="Thông tin thiết kế chữ (Nội dung, Font, Màu sắc...)",
        help="Mô tả chi tiết yêu cầu hoặc nội dung thiết kế của đơn hàng xe đẩy",
        tracking=True,
    )

    cart_design_image_description = fields.Text(
        string="Thông tin thiết kế hình ảnh (Logo, Hình minh họa, Phong cách...)",
        help="Mô tả hình ảnh, logo hoặc phong cách thiết kế mong muốn cho xe đẩy.",
        tracking=True,
    )

    #========== Lựa chọn 2 nhánh sau sản xuất: giao hàng hoặc lắp đặt ===========
    fulfillment_method = fields.Selection([
        ('installation', 'Thi công - lắp đặt'),
        ('delivery', 'Giao hàng'),
    ], string='Hình thức thực hiện', default='delivery', tracking=True)

    # Badges màu riêng cho DAC
    # NEW: field HTML để render badge
    order_state_badge = fields.Html(
        string='Trạng thái',
        compute='_compute_order_state_badge',
        sanitize=False,  # giữ nguyên class span
        store=False,
    )

    # Cờ sản xuất trễ hạn (tính toán, không lưu)
    is_production_overdue = fields.Boolean(
        compute='_compute_is_production_overdue', store=False
    )

    # ===== UI flags for view visibility =====
    is_admin_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_manager_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_design_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_production_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_sale_user = fields.Boolean(compute="_compute_user_flags", store=False)

    # ===== Internal Notes (Sale → Design / Production) =====
    note_for_design = fields.Text(
        string='Ghi chú cho Thiết kế',
        help='Sale ghi chú hướng dẫn / yêu cầu cho nhóm Thiết kế',
    )
    note_for_production = fields.Text(
        string='Ghi chú cho Sản xuất',
        help='Sale ghi chú hướng dẫn / yêu cầu cho nhóm Sản xuất',
    )

    # ===== Work Tasks =====
    task_ids = fields.One2many(
        'dac.work.task', 'order_id', string='Tasks',
    )
    task_count = fields.Integer(
        string='Số task', compute='_compute_task_count', store=False,
    )

    # ===== VIP Customer Class for styling =====
    partner_vip_class = fields.Char(
        string='VIP Class',
        compute='_compute_partner_vip_class',
        store=False,
        help='CSS class cho khách hàng VIP/Loyal'
    )
