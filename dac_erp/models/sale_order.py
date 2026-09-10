from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError
import logging
from datetime import date, datetime, timedelta
from odoo.tools import html_escape

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
        domain=[],
        tracking=True,
    )

    # Sản xuất
    user_id_production = fields.Many2one(
        'res.users',
        string='Người sản xuất',
        domain=[],
        tracking=True,
    )
    
    # Nhóm sản xuất (nhiều người)
    production_group_ids = fields.Many2many(
        'res.users',
        'sale_order_production_user_rel',   # tên bảng quan hệ M2M
        'order_id',                         # cột FK về sale.order
        'user_id',                          # cột FK về res.users
        string='Nhóm sản xuất',
        domain=[],                          # cho chọn TẤT CẢ users
        tracking=True,
        help='Những người tham gia sản xuất, Có thể bao gồm người phụ trách sản xuất.',
    )
    
    # Trường so sánh với file số đơn excel
    order_number = fields.Char(string="Số đặt hàng", 
                                     default=False, 
                                     copy=False, 
                                     help="Số phiếu ĐH", 
                                     tracking=True)

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
    production_deadline = fields.Date(string="Deadline sản xuất", tracking = True)
    
    # --- flags đánh dấu đã chạm các mốc quy trình ---
    reached_production = fields.Boolean(default=False, copy=False)
    left_production_date = fields.Datetime(string="Ngày rời SX", tracking=True)
    started_delivery   = fields.Boolean(default=False, copy=False)
    started_installation = fields.Boolean(default=False, copy=False)
    
    # --- Sản xuất trễ ---
    production_is_delayed = fields.Boolean(
        string="Sản xuất bị trễ?", tracking=True,  default=False,
    )
    production_delay_date = fields.Date(
        string="Ngày trễ" , tracking=True ,
    )
    production_delay_reason = fields.Text(
        string="Lý do trễ" , tracking=True ,
    )


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

    @api.depends('invoice_ids', 'invoice_ids.payment_state', 'invoice_ids.amount_total', 'invoice_ids.dac_deposit_invoice')
    def _compute_total_deposit_paid(self):
        """Tính tổng tiền cọc đã thanh toán từ relationship invoice_ids"""
        for order in self:
            total_paid = 0.0
            
            # Sử dụng invoice_ids relationship thay vì search
            paid_deposit_invoices = order.invoice_ids.filtered(
                lambda inv: inv.move_type == 'out_invoice' 
                and inv.dac_deposit_invoice 
                and inv.payment_state == 'paid'
                and inv.state != 'cancel'
            )
            
            # Nếu không tìm thấy qua relationship, fallback sang search (để tương thích)
            if not paid_deposit_invoices and order.name:
                paid_deposit_invoices = self.env['account.move'].search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', order.name),
                    ('dac_deposit_invoice', '=', True),
                    ('payment_state', '=', 'paid'),
                    ('state', '!=', 'cancel')
                ])
            
            total_paid = sum(paid_deposit_invoices.mapped('amount_total'))
            order.total_deposit_paid = total_paid

    @api.depends('order_line', 'order_line.price_unit', 'order_line.product_uom_qty')
    def _compute_amount_untaxed_original(self):
        """Tính số tiền sản phẩm gốc (Thành tiền - chỉ dòng dương, bỏ qua dòng cọc âm)"""
        for order in self:
            # Chỉ lấy dòng sản phẩm có giá dương (bỏ qua dòng cọc âm)
            product_lines = order.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
            # Tính rõ ràng: price_unit * quantity (chưa tính thuế, chưa trừ cọc)
            total = 0.0
            for line in product_lines:
                line_total = line.price_unit * line.product_uom_qty
                if line.discount:
                    line_total = line_total * (1 - line.discount / 100)
                total += line_total
            order.amount_untaxed_original = total

    @api.depends('order_line', 'order_line.price_tax')
    def _compute_amount_tax_positive_lines(self):
        """Tính thuế chỉ từ dòng có giá dương (bỏ qua dòng cọc âm)"""
        for order in self:
            # Chỉ lấy dòng sản phẩm có giá dương (bỏ qua dòng cọc âm)
            product_lines = order.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
            order.amount_tax = sum(product_lines.mapped('price_tax'))

    @api.depends('amount_untaxed_original', 'amount_tax')
    def _compute_amount_total_positive_lines(self):
        """Tính tổng tiền từ dòng có giá dương (Thành tiền + Thuế)"""
        for order in self:
            order.amount_total = order.amount_untaxed_original + order.amount_tax

    @api.depends('amount_total', 'total_deposit_paid', 'is_order_completed', 'order_state_custom')
    def _compute_remaining_amount_display(self):
        """Tính số tiền còn lại cần thu để hiển thị cho user - Logic cải tiến"""
        for order in self:
            # Nếu đơn hàng đã hoàn thành -> luôn hiển thị 0
            if order.is_order_completed:
                order.remaining_amount_display = 0.0
            # Nếu đơn hàng bị hủy -> không tính toán (sẽ ẩn ở view)
            elif order.order_state_custom == 'cancel':
                order.remaining_amount_display = 0.0
            else:
                # Tính số tiền còn lại = Tổng - Cọc đã thanh toán
                remaining = order.amount_total - order.total_deposit_paid
                order.remaining_amount_display = max(remaining, 0.0)  # Không để âm

    @api.depends('name', 'create_date', 'order_state_custom', 'partner_id')
    def _compute_latest_quotation_info(self):
        """Tính thông tin báo giá mới nhất để hiển thị ở đầu list"""
        for order in self:
            if order.create_date:
                create_date_str = order.create_date.strftime('%d/%m/%Y')
                order.latest_quotation_info = f"{order.name} - {create_date_str}"
            else:
                order.latest_quotation_info = order.name or "Chưa có tên"

    @api.depends('order_line', 'order_line.product_id', 'order_line.price_unit')
    def _compute_auto_check_deposit(self):
        """Kiểm tra và tự động thêm dòng đặt cọc nếu có hóa đơn cọc đã thanh toán"""
        for order in self:
            # Tìm hóa đơn đặt cọc đã thanh toán
            deposit_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True),
                ('payment_state', '=', 'paid')
            ])
            
            if deposit_invoices:
                # Kiểm tra đã có dòng đặt cọc trong order_line chưa
                product = self.env['product.product'].search([('default_code', '=', 'DEPOSIT')], limit=1)
                if product:
                    deposit_line = order.order_line.filtered(lambda l: l.product_id == product and l.price_unit < 0)
                    if not deposit_line:
                        # Tự động thêm dòng đặt cọc
                        deposit_amount = abs(deposit_invoices[0].amount_total)
                        order.add_deposit_order_line(deposit_amount, invoice=deposit_invoices[0])
            
            order.auto_check_deposit = True

    @api.depends('order_line', 'order_line.price_unit', 'order_line.product_uom_qty', 'order_line.display_type')
    def _compute_is_zero_amount(self):
        """Đánh dấu đơn 0đ - tính từ product lines dương (bỏ qua section/note/dòng cọc âm)"""
        for order in self:
            product_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.price_unit >= 0
            )
            total = sum(line.price_unit * line.product_uom_qty for line in product_lines)
            order.is_zero_amount = (total == 0)

    @api.depends('is_deposit_confirmed')
    def _compute_can_delete_products(self):
        """Chỉ Admin/Manager/Sale nhìn thấy nút xoá trên UI; Design/Production thì không."""
        user = self.env.user
        for order in self:
            if user.has_group('base.group_system') or user.has_group('dac_erp.group_dac_erp_manager'):
                order.can_delete_products = True
            elif user.has_group('dac_erp.group_dac_erp_sale'):
                order.can_delete_products = True
            else:
                order.can_delete_products = False

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
                    
        return result

    def _auto_sync_deposit_line(self):
        """Tự động đồng bộ dòng đặt cọc"""
        deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True),
            ('payment_state', '=', 'paid')
        ])
        
        if deposit_invoices:
            existing_deposit_line = self.order_line.filtered(lambda l: not l.display_type and l.price_unit < 0)
            if not existing_deposit_line:
                #_logger.info(f"Auto-sync: Thêm dòng đặt cọc cho order {self.name}")
                deposit_amount = abs(deposit_invoices[0].amount_total)
                self.add_deposit_order_line(deposit_amount, invoice=deposit_invoices[0])

    @api.model
    def default_get(self, fields_list):
        """Override để trigger kiểm tra deposit khi tạo mới hoặc load form và gán người phụ trách"""
        result = super().default_get(fields_list)
        
        # Đảm bảo người tạo đơn hàng sẽ là người phụ trách (user_id)
        if 'user_id' in fields_list and not result.get('user_id'):
            result['user_id'] = self.env.user.id
            
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

    def _check_auto_deposit_on_load(self):
        """Kiểm tra tự động khi load record"""
        self.check_and_add_deposit_line()

    def action_save_custom(self):
        return True
    
    def action_cancel_order(self):
        """Hủy đơn hàng - chỉ cho phép ở trạng thái báo giá và chưa có hóa đơn cọc"""
        for order in self:
            if order.order_state_custom != 'quotation':
                raise UserError("Chỉ có thể hủy đơn hàng ở trạng thái báo giá!")
            
            # Kiểm tra đã có hóa đơn cọc nào được tạo chưa
            if order.deposit_invoice_count > 0:
                raise UserError("Không thể hủy đơn hàng đã có hóa đơn cọc!")
            
            # Kiểm tra đã có hóa đơn nào khác được tạo chưa
            existing_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '!=', True)  # Loại trừ hóa đơn cọc vì đã check ở trên
            ])
            
            if existing_invoices:
                raise UserError("Không thể hủy đơn hàng đã có hóa đơn!")
            
            # Hủy đơn hàng
            order.order_state_custom = 'cancel'
            
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
    
    
    def action_back_custom_step(self):
        """Quay lại tiến trình trước đó - reset cờ confirm khi về production để cho phép chỉnh sửa"""
        state_order = ['quotation', 'deposit', 'production', 'delivery', 'installation' , 'payment']
        allowed_groups = [self.env.ref('dac_erp.group_dac_erp_manager'), 
                          self.env.ref('base.group_system')]
        for order in self:
            if not any(g in self.env.user.groups_id for g in allowed_groups):
                raise UserError("Bạn không thể quay lại tiến trình trước!\n"
                                "Vui lòng liên hệ quản lý để được hỗ trợ!")
            if order.order_state_custom in state_order:
                idx = state_order.index(order.order_state_custom)
            
            # --- Collapse 2 nhánh song song về production và RESET CỜ ---
            if order.order_state_custom in ('installation', 'delivery'):
                order.write({
                    'order_state_custom': 'production',
                    'is_delivery_confirmed': False,
                    'is_installation_confirmed': False,
                })
                #_logger.info(f"[BACK] Order {order.name}: Reset is_delivery_confirmed & is_installation_confirmed")
                continue
            
            # --- Từ payment lùi về đúng nhánh đã đi (dựa vào fulfillment_method) và RESET CỜ ---
            if order.order_state_custom == 'payment':
                vals = {}
                # Dựa vào fulfillment_method đã chọn, KHÔNG dựa vào flag started_*
                if order.fulfillment_method == 'installation':
                    vals['order_state_custom'] = 'installation'
                    vals['is_installation_confirmed'] = False
                    #_logger.info(f"[BACK] Order {order.name}: Payment -> Installation (fulfillment_method=installation)")
                else:  # delivery hoặc mặc định
                    vals['order_state_custom'] = 'delivery'
                    vals['is_delivery_confirmed'] = False
                    #_logger.info(f"[BACK] Order {order.name}: Payment -> Delivery (fulfillment_method={order.fulfillment_method})")
                
                order.write(vals)
                continue
            
            # --- Tuyến tính cho các bước còn lại ---
            if idx > 0:
                order.order_state_custom = state_order[idx - 1]

        return True
    

    def action_next_step(self):
        state_order = ['quotation', 'deposit', 'production', 'delivery', 'installation' ,'payment']
        for order in self:
            idx = state_order.index(order.order_state_custom) 
            # Kiểm tra xác nhận tiến trình hiện tại
            confirmed_field = {
                'quotation': 'is_quotation_confirmed',
                'deposit': 'is_deposit_confirmed',
                'production': 'is_production_confirmed',
                'delivery': 'is_delivery_confirmed',
                'installation': 'is_installation_confirmed',
                'payment': 'is_payment_confirmed',
            }[order.order_state_custom]
            if not getattr(order, confirmed_field):
                raise UserError("Vui lòng xác nhận tiến trình hiện tại trước khi chuyển sang tiến trình tiếp theo!")
            if order.order_state_custom == 'production':
                order.order_state_custom = (order.fulfillment_method or 'delivery')
            elif idx < len(state_order) - 1:
                order.order_state_custom = state_order[idx + 1]
        return True
    
    def action_confirm_info(self):
        state_order = ['quotation', 'deposit', 'production', 'delivery', 'installation', 'payment']
        for order in self:
            idx = state_order.index(order.order_state_custom)
            # Kiểm tra ở tiến trình đầu tiên (báo giá)
            if order.order_state_custom == 'quotation':
                # Chỉ tính dòng sản phẩm, không tính section/note
                product_lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
                if not product_lines:
                    raise UserError("Yêu cầu nhập sản phẩm trước khi xác nhận!")
                order.is_quotation_confirmed = True
            elif order.order_state_custom == 'production':
                # Kiểm tra deadline sản xuất trước khi xác nhận
                if not order.production_deadline:
                    raise UserError("Vui lòng nhập 'Ngày hoàn tất' trước khi xác nhận sản xuất!")
                # Nếu bật trễ thì yêu cầu đủ và đúng ngày
                if order.production_is_delayed:
                    if not order.production_delay_date or not (order.production_delay_reason or '').strip():
                        raise UserError(_("Bật 'Có trễ' thì phải nhập 'Ngày trễ' và 'Lý do trễ'."))
                    if order.production_deadline and order.production_delay_date <= order.production_deadline:
                        raise UserError(_("Ngày trễ phải sau 'Ngày hoàn tất'."))
                    if not order.production_deadline and order.production_delay_date <= date.today():
                        raise UserError(_("Ngày trễ phải sau ngày hiện tại."))
                order.is_production_confirmed = True
            elif order.order_state_custom == 'delivery':
                # Kiểm tra địa chỉ giao hàng trước khi xác nhận
                if not order.delivery_address or not order.delivery_address.strip():
                    raise UserError("Vui lòng nhập địa chỉ giao hàng trước khi xác nhận!")
                order.is_delivery_confirmed = True
                # Chạy lại kiểm tra hoàn tất: nếu chỉ có hóa đơn cọc và tổng cọc >= tổng đơn
                order.check_and_update_completion_status()
                # Nếu chưa completed, nhảy trực tiếp sang payment (KHÔNG qua installation)
                if order.order_state_custom != 'completed':
                    order.order_state_custom = 'payment'
                    _logger.info(f"[CONFIRM] Order {order.name}: Delivery confirmed -> Payment")
            elif order.order_state_custom == 'payment':
                order.is_payment_confirmed = True
            
            elif order.order_state_custom == 'installation':
                # Kiểm tra địa chỉ thi công/lắp đặt riêng
                if not order.installation_address or not order.installation_address.strip():
                    raise UserError("Vui lòng nhập địa chỉ thi công/lắp đặt trước khi xác nhận!")
                order.is_installation_confirmed = True
                order.check_and_update_completion_status()
                # Nếu chưa completed, nhảy trực tiếp sang payment
                if order.order_state_custom != 'completed':
                    order.order_state_custom = 'payment'
                    _logger.info(f"[CONFIRM] Order {order.name}: Installation confirmed -> Payment")
            
            # CHỈ tự động chuyển tiến trình cho quotation và production
            # KHÔNG áp dụng cho delivery/installation (đã xử lý riêng ở trên)
            if order.order_state_custom in ['quotation', 'production'] and idx < len(state_order) - 1:
                order.order_state_custom = state_order[idx + 1]
        return True

    def action_proceed_to_production(self):
        """Tiến hành sản xuất:
        - Không cọc: chỉ cần 'production_deadline'
        - Có cọc: phải xác nhận cọc + đã thanh toán hóa đơn cọc + 'production_deadline'
        """
        # SAFETY CHECK: Ngăn chặn tự động trigger khi không có context UI
        if not self.env.context.get('from_ui_button'):
            return False
            
        for order in self:
            if order.order_state_custom != 'deposit':
                raise UserError("Chỉ có thể tiến hành sản xuất từ trạng thái đặt cọc!")
            
            # KHÔNG CỌC
            if not order.has_deposit:
                if not order.production_deadline:
                    raise UserError("Vui lòng nhập 'Ngày hoàn tất' trước khi tiến hành sản xuất!")
                order.order_state_custom = 'production'
                order.is_production_confirmed = True
                order.reached_production = True          # <— thêm dòng này
                return True

            # CÓ CỌC
            if not order.is_deposit_confirmed:
                raise UserError("Vui lòng xác nhận đặt cọc trước khi tiến hành sản xuất!")

            if not order.has_paid_deposit_invoice:
                raise UserError("Vui lòng thanh toán hóa đơn đặt cọc trước khi tiến hành sản xuất!")

            if not order.production_deadline:
                raise UserError("Vui lòng nhập 'Ngày hoàn tất' trước khi tiến hành sản xuất!")

            deposit_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True),
                ('payment_state', '=', 'paid')
            ])
            if not deposit_invoices:
                raise UserError("Không tìm thấy hóa đơn cọc đã thanh toán!")

            order.order_state_custom = 'production'
            order.is_production_confirmed = True
            order.reached_production = True              # <— thêm dòng này
        return True

    def action_proceed_to_delivery(self):
        """Tiến hành giao hàng từ trạng thái sản xuất"""
        for order in self:
            if order.order_state_custom != 'production':
                raise UserError(_("Chỉ có thể tiến hành giao hàng từ trạng thái sản xuất!"))

            # Đã xác nhận sản xuất (được set khi bấm “Tiến hành sản xuất”)
            if not order.is_production_confirmed:
                raise UserError(_("Vui lòng xác nhận sản xuất trước khi tiến hành giao hàng!"))

            # Nếu có trễ -> bắt buộc đủ & ngày trễ phải LỚN HƠN
            if order.production_is_delayed:
                if not order.production_delay_date or not (order.production_delay_reason or '').strip():
                    raise UserError(_("Vui lòng chọn ngày trễ và lý do trễ."))

                if order.production_deadline:
                    if order.production_delay_date <= order.production_deadline:
                        raise UserError(_("Ngày trễ phải sau 'Ngày hoàn tất'."))
                else:
                    if order.production_delay_date <= date.today():
                        raise UserError(_("Ngày trễ phải sau ngày hiện tại."))

            # Cho phép chuyển bước
            order.started_delivery = True                  # <— thêm dòng này
            order.order_state_custom = 'delivery'
        return True

    def action_proceed_to_installation(self):
        """Tiến hành thi công - lắp đặt từ trạng thái sản xuất"""
        for order in self:
            if order.order_state_custom != 'production':
                raise UserError(_("Chỉ có thể tiến hành từ trạng thái sản xuất!"))
            if not order.is_production_confirmed:
                raise UserError(_("Vui lòng xác nhận sản xuất trước!"))

            # Nếu có trễ sản xuất → ràng buộc giống delivery
            if order.production_is_delayed:
                if not order.production_delay_date or not (order.production_delay_reason or '').strip():
                    raise UserError(_("Vui lòng chọn ngày trễ và lý do trễ."))
                if order.production_deadline:
                    if order.production_delay_date <= order.production_deadline:
                        raise UserError(_("Ngày trễ phải sau 'Ngày hoàn tất'."))
                else:
                    if order.production_delay_date <= date.today():
                        raise UserError(_("Ngày trễ phải sau ngày hiện tại."))

            order.started_installation = True
            order.order_state_custom = 'installation'
        return True


    def action_proceed_to_fulfillment(self):
        for order in self:
            if order.fulfillment_method == 'installation':
                order.action_proceed_to_installation()
            else:
                order.action_proceed_to_delivery()
        return True


    def action_deposit_invoice(self):
        for order in self:
            if not (self.env.user.has_group('dac_erp.group_dac_erp_sale')
                    or self.env.user.has_group('dac_erp.group_dac_erp_manager')
                    or self.env.user.has_group('base.group_system')):
                raise AccessError(_("Bạn không có quyền tạo/xem hóa đơn cọc."))
            if order.is_deposit_confirmed:
                raise UserError("Đặt cọc đã được xác nhận, không thể xác nhận lại!")
            if order.deposit_amount <= 0:
                raise UserError("Vui lòng nhập số tiền đặt cọc!")
            if order.deposit_amount > order.amount_total:
                raise UserError(f"Số tiền đặt cọc ({order.deposit_amount:,.0f} đ) không được lớn hơn tổng tiền đơn hàng ({order.amount_total:,.0f} đ)!")
            
            # KIỂM TRA HÓA ĐƠN CỌC ĐÃ TỒN TẠI TRƯỚC KHI TẠO MỚI
            existing_deposit_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True)
            ])
            
            if existing_deposit_invoices:
                # Phân loại hóa đơn theo trạng thái
                draft_invoices = existing_deposit_invoices.filtered(lambda inv: inv.state == 'draft')
                posted_unpaid_invoices = existing_deposit_invoices.filtered(lambda inv: inv.state == 'posted' and inv.payment_state != 'paid')
                paid_invoices = existing_deposit_invoices.filtered(lambda inv: inv.payment_state == 'paid')
                
                if draft_invoices:
                    # Có hóa đơn draft chưa xác nhận
                    draft_names = [inv.name or f"Draft-{inv.id}" for inv in draft_invoices]
                    raise UserError(f"Đã có hóa đơn cọc chưa xác nhận!\n"
                                   f"Vui lòng xác nhận và thanh toán hóa đơn sau trước khi tạo mới:\n"
                                   f"{', '.join(draft_names)}")
                
                elif posted_unpaid_invoices:
                    # Có hóa đơn đã confirm nhưng chưa thanh toán
                    unpaid_names = [inv.name or f"Invoice-{inv.id}" for inv in posted_unpaid_invoices]
                    raise UserError(f"Đã có hóa đơn cọc chưa thanh toán!\n"
                                   f"Vui lòng thanh toán hóa đơn sau trước khi tạo mới:\n"
                                   f"{', '.join(unpaid_names)}")
                
                elif paid_invoices:
                    # Có hóa đơn đã thanh toán -> không cho tạo thêm
                    paid_names = [inv.name or f"Invoice-{inv.id}" for inv in paid_invoices]
                    raise UserError(f"Đã có hóa đơn cọc đã thanh toán!\n"
                                   f"Không thể tạo thêm hóa đơn cọc mới:\n"
                                   f"{', '.join(paid_names)}")
            
            # Mở popup xác nhận (wizard)
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'deposit.confirm.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'active_id': order.id},
            }

    def action_view_all_invoices(self):
        """Xem tất cả hóa đơn liên quan đến đơn hàng (cọc + thanh toán)"""
        if not (self.env.user.has_group('dac_erp.group_dac_erp_sale')
                or self.env.user.has_group('dac_erp.group_dac_erp_manager')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_("Bạn không có quyền xem hóa đơn."))
        self.ensure_one()
        action = self.env.ref('account.action_move_out_invoice_type').read()[0]
        all_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name)
        ])
        action['domain'] = [('id', 'in', all_invoices.ids)]
        action['context'] = {'create': False}
        if len(all_invoices) == 1:
            action['views'] = [(self.env.ref('account.view_move_form').id, 'form')]
            action['res_id'] = all_invoices.id
        else:
            action['name'] = f'Hóa đơn - {self.name}'
        return action
    
    def add_deposit_order_line(self, deposit_amount, invoice=None):
        """
        Thêm section 'Khoản cọc', note chi tiết hóa đơn, và dòng sản phẩm đặt cọc âm đúng chuẩn Odoo.
        """
        self.ensure_one()
        #_logger.info(f"=== BẮT ĐẦU THÊM DÒNG ĐẶT CỌC cho order {self.name} ===")
        #_logger.info(f"Số tiền cọc: {deposit_amount}")
        #_logger.info(f"Hóa đơn: {invoice.name if invoice else 'Không có'}")
        
        # Tìm hoặc tạo product đặt cọc
        product = None
        if invoice:
            # Ưu tiên lấy sản phẩm từ hóa đơn đặt cọc
            invoice_lines = invoice.invoice_line_ids.filtered(lambda l: not l.display_type and l.product_id)
            if invoice_lines:
                product = invoice_lines[0].product_id
                #_logger.info(f"Sử dụng sản phẩm từ hóa đơn: {product.name} (ID: {product.id})")
        
        if not product:
            # Fallback: tìm hoặc tạo sản phẩm DEPOSIT
            product = self.env['product.product'].search([('default_code', '=', 'DEPOSIT')], limit=1)
            if not product:
                #_logger.info("Tạo sản phẩm DEPOSIT mới")
                product = self.env['product.product'].create({
                    'name': 'Đặt cọc',
                    'default_code': 'DEPOSIT',
                    'type': 'service',
                    'sale_ok': True,
                    'purchase_ok': False,
                    'list_price': 0.0,
                    'taxes_id': [(6, 0, [])],
                })
            else:
                pass  # Sử dụng sản phẩm DEPOSIT có sẵn
        
        # Kiểm tra đã có dòng đặt cọc chưa (linh hoạt - kiểm tra tất cả dòng có giá âm)
        existing_deposit_line = self.order_line.filtered(
            lambda l: not l.display_type and l.price_unit < 0
        )
        if existing_deposit_line:
            #_logger.info(f"Đã có dòng đặt cọc trong order {self.name}, không thêm nữa")
            for line in existing_deposit_line:
                _logger.info(f"  - Dòng hiện có: {line.name}, Sản phẩm: {line.product_id.name}, Giá: {line.price_unit}")
            return True
        
        #_logger.info("Bắt đầu tạo các dòng order_line...")
        
        # Kiểm tra đã có section 'Khoản cọc' chưa
        section_line = self.order_line.filtered(
            lambda l: l.display_type == 'line_section' and 'cọc' in (l.name or '').lower()
        )
        if not section_line:
            #_logger.info("Tạo section 'Khoản cọc'")
            section_line = self.order_line.create({
                'order_id': self.id,
                'display_type': 'line_section',
                'name': 'Khoản cọc',
                'sequence': 9999,  # Đặt cuối, Odoo sẽ tự sắp xếp lại
            })
            #_logger.info(f"Đã tạo section: {section_line.id}")
        else:
            _logger.info("Section 'Khoản cọc' đã tồn tại")
        
        # Thêm dòng note chi tiết hóa đơn cọc
        note_content = 'Tiền cọc'
        if invoice:
            note_content += f" (hóa đơn: {invoice.name} ngày {invoice.invoice_date.strftime('%d/%m/%Y') if invoice.invoice_date else ''})"
        
        #_logger.info(f"Nội dung note: {note_content}")
        
        note_line = self.order_line.filtered(
            lambda l: l.display_type == 'line_note' and note_content in (l.name or '')
        )
        if not note_line:
            #_logger.info("Tạo dòng note")
            note_line = self.order_line.create({
                'order_id': self.id,
                'display_type': 'line_note',
                'name': note_content,
                'sequence': 10000,
            })
            #_logger.info(f"Đã tạo note: {note_line.id}")
        else:
            _logger.info("Dòng note đã tồn tại")
        
        # Thêm dòng sản phẩm đặt cọc âm
        #_logger.info(f"Tạo dòng sản phẩm đặt cọc với giá: -{abs(deposit_amount)}")
        deposit_line = self.order_line.create({
            'order_id': self.id,
            'product_id': product.id,
            'name': 'Đặt cọc',
            'product_uom_qty': 1,
            'price_unit': -abs(deposit_amount),
            'tax_id': [(6, 0, [])],
            'display_type': False,
            'sequence': 10001,
        })
        
        #_logger.info(f"Đã tạo dòng sản phẩm đặt cọc: {deposit_line.id}")
        #_logger.info(f"=== HOÀN THÀNH THÊM DÒNG ĐẶT CỌC {deposit_amount} vào order {self.name} ===")
        return True
    
    
    deposit_invoice_count = fields.Integer(string="Số hóa đơn đặt cọc", compute="_compute_deposit_invoice_count")
    total_invoice_count = fields.Integer(string="Tổng số hóa đơn", compute="_compute_total_invoice_count")
    has_paid_deposit_invoice = fields.Boolean(string="Có hóa đơn cọc đã thanh toán", compute="_compute_has_paid_deposit_invoice")
    has_final_invoice = fields.Boolean(string="Có hóa đơn thanh toán cuối", compute="_compute_has_final_invoice")
    has_paid_final_invoice = fields.Boolean(string="Có hóa đơn cuối đã thanh toán", compute="_compute_has_paid_final_invoice")

    def _compute_deposit_invoice_count(self):
        for order in self:
            order.deposit_invoice_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True)
            ])

    def _compute_total_invoice_count(self):
        for order in self:
            order.total_invoice_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name)
            ])

    def _compute_has_paid_deposit_invoice(self):
        for order in self:
            paid_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True),
                ('payment_state', '=', 'paid')
            ])
            order.has_paid_deposit_invoice = paid_count > 0
            #_logger.info(f"Order {order.name}: has_paid_deposit_invoice = {order.has_paid_deposit_invoice} (paid_count = {paid_count})")
            
            # BỎ LOGIC TỰ ĐỘNG SET is_order_completed TẠI ĐÂY - đã chuyển vào action_post của account.move

    def _compute_has_final_invoice(self):
        """Kiểm tra xem đã có hóa đơn thanh toán cuối chưa (hóa đơn không phải cọc)"""
        for order in self:
            final_invoice_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', False),  # Không phải hóa đơn cọc
                ('state', '!=', 'cancel'),  # Không phải hóa đơn đã hủy
            ])
            order.has_final_invoice = final_invoice_count > 0

    def _compute_has_paid_final_invoice(self):
        """Kiểm tra xem đã có hóa đơn thanh toán cuối đã thanh toán chưa"""
        for order in self:
            paid_final_invoice_count = self.env['account.move'].search_count([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', False),  # Không phải hóa đơn cọc
                ('payment_state', '=', 'paid')
            ])
            order.has_paid_final_invoice = paid_final_invoice_count > 0
            #_logger.info(f"Order {order.name}: has_paid_final_invoice = {order.has_paid_final_invoice} (count = {paid_final_invoice_count})")

    @api.depends('invoice_ids', 'invoice_ids.payment_state', 'name')
    def _compute_all_invoices_paid(self):
        """Kiểm tra xem tất cả hóa đơn của đơn hàng đã được thanh toán chưa"""
        for order in self:
            # SỬA: Search trực tiếp thay vì dựa vào relation để đảm bảo dữ liệu chính xác
            order_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('state', '=', 'posted')
            ])
            
            if not order_invoices:
                # Nếu chưa có hóa đơn nào -> chưa hoàn thành
                order.all_invoices_paid = False
                unpaid_invoices = self.env['account.move']  # Empty recordset for logging
            else:
                # Kiểm tra tất cả hóa đơn đã thanh toán (paid) hay chưa
                unpaid_invoices = order_invoices.filtered(lambda inv: inv.payment_state != 'paid')
                order.all_invoices_paid = len(unpaid_invoices) == 0
            
            _logger.info(f"Order {order.name}: all_invoices_paid = {order.all_invoices_paid} "
                        f"(invoices: {len(order_invoices)}, unpaid: {len(unpaid_invoices)})")
            
            # In chi tiết từng hóa đơn để debug
            for inv in order_invoices:
                _logger.info(f"  - Invoice {inv.name}: payment_state = {inv.payment_state}")
            
            # CHỈ TỰ ĐỘNG set is_order_completed khi có hóa đơn cuối đã thanh toán (không phải chỉ hóa đơn cọc)
            if order.all_invoices_paid and order_invoices and not order.is_order_completed:
                # Kiểm tra xem có hóa đơn cuối đã thanh toán không (không phải chỉ hóa đơn cọc)
                final_invoices = order_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
                if final_invoices:
                    # Có hóa đơn cuối -> có thể set hoàn thành
                    order.is_order_completed = True
                    # TỰ ĐỘNG CHUYỂN SANG TRẠNG THÁI COMPLETED
                    if order.order_state_custom != 'completed':
                        order.order_state_custom = 'completed'
                        order.is_payment_confirmed = True
                    #_logger.info(f"Tự động set is_order_completed = True và chuyển sang completed cho order {order.name}")
                else:
                    # Chỉ có hóa đơn cọc -> KHÔNG set hoàn thành
                    _logger.info(f"Order {order.name}: Chỉ có hóa đơn cọc đã thanh toán, chưa set hoàn thành")

    def check_and_update_completion_status(self):
        """OPTIMIZED: Kiểm tra và cập nhật trạng thái hoàn thành với minimal compute calls"""
        for order in self:
            #_logger.info(f"OPTIMIZED CHECK: Processing order {order.name}")
            
            # SINGLE SEARCH: Tìm tất cả invoices của order cùng lúc
            order_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('state', '=', 'posted')
            ])
            
            if not order_invoices:
                continue
                
            # EFFICIENT CHECK: Kiểm tra paid invoices một lần
            paid_invoices = order_invoices.filtered(lambda inv: inv.payment_state == 'paid')
            unpaid_invoices = order_invoices - paid_invoices
            
            # LOGIC: Kiểm tra có final invoice paid không (CHẮC CHẮN KHÔNG PHẢI CỌC)
            final_paid_invoices = paid_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
            
            # CHỈ UPDATE KHI THỰC SỰ CÓ HÓA ĐƠN CUỐI ĐÃ THANH TOÁN (không phải cọc)
            if final_paid_invoices and not order.is_order_completed:
                # KIỂM TRA THÊM: Đảm bảo có ít nhất 1 hóa đơn không phải cọc
                non_deposit_invoices = order_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
                if non_deposit_invoices:
                    order.is_order_completed = True
                    # TỰ ĐỘNG CHUYỂN SANG TRẠNG THÁI COMPLETED CHỈ KHI CÓ HÓA ĐƠN CUỐI
                    if order.order_state_custom != 'completed':
                        order.order_state_custom = 'completed'
                        order.is_payment_confirmed = True
                    #_logger.info(f"OPTIMIZED CHECK: Set completed cho order {order.name} - có final invoice")

            # NEW: Nếu CHỈ có hóa đơn đặt cọc, nhưng tổng cọc đã trả >= tổng đơn => cũng hoàn thành
            # (Không có hóa đơn cuối nào)
            # ⚠️ ĐIỀU KIỆN BỔ SUNG: Phải đã xác nhận delivery HOẶC installation
            if not order_invoices.filtered(lambda inv: not inv.dac_deposit_invoice):
                # Tổng tiền của các invoice đã 'paid' (deposit)
                paid_total = sum(inv.amount_total for inv in paid_invoices)
                # Epsilon nhỏ để tránh sai số làm tròn
                if order.currency_id.compare_amounts(paid_total, order.amount_total) >= 0:
                    # ✅ CHỈ CHUYỂN COMPLETED NẾU ĐÃ XÁC NHẬN DELIVERY HOẶC INSTALLATION
                    if order.is_delivery_confirmed or order.is_installation_confirmed:
                        order.is_order_completed = True
                        order.is_payment_confirmed = True
                        if order.order_state_custom != 'completed':
                            order.order_state_custom = 'completed'

            # CHỈ INVALIDATE MỘT LẦN
            order.invalidate_recordset()
            
        # Trả về action reload
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_reset_completion_status_if_only_deposit(self):
        """Method để reset trạng thái đơn hàng bị set sai khi chỉ thanh toán cọc"""
        for order in self:
            # Tìm tất cả invoices của order
            order_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('state', '=', 'posted')
            ])
            
            # Kiểm tra có final invoice không
            non_deposit_invoices = order_invoices.filtered(lambda inv: not inv.dac_deposit_invoice)
            final_paid_invoices = order_invoices.filtered(lambda inv: not inv.dac_deposit_invoice and inv.payment_state == 'paid')
            
            # Nếu KHÔNG CÓ final invoice đã thanh toán nhưng đơn đã bị set completed
            if not final_paid_invoices and order.order_state_custom == 'completed':
                # Reset về trạng thái deposit (vì chỉ có cọc)
                if order_invoices.filtered(lambda inv: inv.dac_deposit_invoice and inv.payment_state == 'paid'):
                    order.order_state_custom = 'deposit'
                    order.is_order_completed = False
                    order.is_payment_confirmed = False
                    _logger.info(f"RESET: Order {order.name} from completed back to deposit (only deposit paid)")
                else:
                    # Không có invoice nào được thanh toán
                    order.order_state_custom = 'quotation'
                    order.is_order_completed = False
                    order.is_payment_confirmed = False
                    _logger.info(f"RESET: Order {order.name} from completed back to quotation (no payment)")
        
        return True


    def check_and_add_deposit_line(self):
        """Phương thức thủ công để kiểm tra và thêm dòng đặt cọc"""
        #_logger.info("=== BẮT ĐẦU KIỂM TRA VÀ THÊM DÒNG ĐẶT CỌC ===")
        
        for order in self:
            #_logger.info(f"Đang kiểm tra order: {order.name}")
            
            # Tìm hóa đơn đặt cọc
            deposit_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('invoice_origin', '=', order.name),
                ('dac_deposit_invoice', '=', True),
                ('payment_state', '=', 'paid')
            ])
            
            #_logger.info(f"Tìm thấy {len(deposit_invoices)} hóa đơn cọc đã thanh toán cho order {order.name}")
            
            if deposit_invoices:
                for invoice in deposit_invoices:
                    _logger.info(f"  - Hóa đơn: {invoice.name}, Số tiền: {invoice.amount_total}, Trạng thái thanh toán: {invoice.payment_state}")
                
                # Lấy sản phẩm từ hóa đơn đặt cọc đã có thay vì tạo mới
                invoice_lines = deposit_invoices[0].invoice_line_ids.filtered(lambda l: not l.display_type and l.product_id)
                if invoice_lines:
                    product = invoice_lines[0].product_id
                    #_logger.info(f"Sử dụng sản phẩm từ hóa đơn cọc: {product.name} (ID: {product.id})")
                else:
                    # Fallback: tìm hoặc tạo sản phẩm DEPOSIT
                    product = self.env['product.product'].search([('default_code', '=', 'DEPOSIT')], limit=1)
                    if not product:
                        #_logger.info("Tạo sản phẩm DEPOSIT mới làm fallback")
                        product = self.env['product.product'].create({
                            'name': 'Đặt cọc',
                            'default_code': 'DEPOSIT',
                            'type': 'service',
                            'sale_ok': True,
                            'purchase_ok': False,
                            'list_price': 0.0,
                            'taxes_id': [(6, 0, [])],
                        })
                    else:
                        pass  # Sử dụng sản phẩm DEPOSIT có sẵn
                
                #_logger.info(f"Sản phẩm sử dụng: {product.name} (ID: {product.id})")
                
                # Kiểm tra đã có dòng đặt cọc chưa (linh hoạt với bất kỳ sản phẩm nào có giá âm)
                deposit_line = order.order_line.filtered(lambda l: not l.display_type and l.price_unit < 0)
                #_logger.info(f"Dòng đặt cọc hiện có: {len(deposit_line)} dòng")
                
                if deposit_line:
                    for line in deposit_line:
                        _logger.info(f"  - Dòng cọc: {line.name}, Sản phẩm: {line.product_id.name}, Giá: {line.price_unit}")
                
                if not deposit_line:
                    deposit_amount = abs(deposit_invoices[0].amount_total)
                    #_logger.info(f"SẼ THÊM dòng đặt cọc với số tiền: {deposit_amount}")
                    
                    # Gọi hàm thêm dòng đặt cọc
                    result = order.add_deposit_order_line(deposit_amount, invoice=deposit_invoices[0])
                    #_logger.info(f"Kết quả thêm dòng đặt cọc: {result}")
                    
                    # Hiển thị thông báo cho user
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Thành công!',
                            'message': f'Đã thêm dòng đặt cọc {deposit_amount:,.0f} đ vào đơn hàng {order.name}',
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    #_logger.info("KHÔNG THÊM - Đã có dòng đặt cọc")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Thông báo',
                            'message': f'Đơn hàng {order.name} đã đặt cọc',
                            'type': 'info',
                            'sticky': False,
                        }
                    }
            else:
                #_logger.info("KHÔNG CÓ hóa đơn cọc đã thanh toán")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thông báo',
                        'message': f'Đơn hàng {order.name} chưa có hóa đơn cọc đã thanh toán',
                        'type': 'info',
                        'sticky': False,
                    }
                }
        
        #_logger.info("=== KẾT THÚC KIỂM TRA ===")
        return True

    def action_create_final_invoice(self):
        """Tạo hóa đơn thanh toán cuối cùng (đã trừ tiền cọc)"""
        self.ensure_one()
        #_logger.info(f"=== TẠO HÓA ĐƠN THANH TOÁN CUỐI CHO ORDER {self.name} ===")
        
        # KIỂM TRA TIỀN CỌC TRƯỚC: Đảm bảo double-check (defense in depth)
        # Logic chính đã được kiểm tra ở nút "Lên cọc", đây chỉ là backup check
        
        # 1. Kiểm tra hóa đơn cọc draft (chưa confirm) - Backup check
        draft_deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True),
            ('state', '=', 'draft')
        ])
        
        if draft_deposit_invoices:
            # Lấy tên hóa đơn, với fallback cho draft chưa có name
            draft_names = [inv.name or f"Draft-{inv.id}" for inv in draft_deposit_invoices]
            _logger.warning(f"Phát hiện {len(draft_deposit_invoices)} hóa đơn cọc draft trong backup check: {draft_names}")
            raise UserError(f"Phát hiện hóa đơn cọc chưa xác nhận!\n"
                           f"Vui lòng xác nhận và thanh toán hóa đơn cọc:\n"
                           f"{', '.join(draft_names)}")
        
        # 2. Kiểm tra hóa đơn cọc đã confirm nhưng chưa thanh toán - Backup check
        unpaid_deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True),
            ('payment_state', '!=', 'paid'),
            ('state', '=', 'posted')
        ])
        
        if unpaid_deposit_invoices:
            unpaid_names = [inv.name or f"Invoice-{inv.id}" for inv in unpaid_deposit_invoices]
            _logger.warning(f"Phát hiện {len(unpaid_deposit_invoices)} hóa đơn cọc chưa thanh toán trong backup check: {unpaid_names}")
            raise UserError(f"Phát hiện hóa đơn cọc chưa thanh toán!\n"
                           f"Vui lòng thanh toán hóa đơn cọc:\n"
                           f"{', '.join(unpaid_names)}")
        
        # Kiểm tra đã có hóa đơn cuối chưa
        existing_final_invoice = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', False),  # Không phải hóa đơn cọc
            ('state', '!=', 'cancel'),  # Không phải hóa đơn đã hủy
        ])
        
        if existing_final_invoice:
            #_logger.info(f"Đã có hóa đơn thanh toán cuối: {existing_final_invoice.mapped('name')}")
            raise UserError(f"Đơn hàng {self.name} đã có hóa đơn thanh toán!")
        
        # Tính toán số tiền cần thu - TÍNH ĐÚNG: chỉ lấy dòng sản phẩm dương (bỏ qua dòng cọc âm)
        product_lines = self.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
        total_amount_original = sum(line.price_unit * line.product_uom_qty for line in product_lines)
        #_logger.info(f"Tổng giá trị sản phẩm gốc (không tính cọc âm): {total_amount_original}")
        #_logger.info(f"Tổng amount_total đơn hàng hiện tại: {self.amount_total}")
        
        # Tìm số tiền cọc đã thanh toán
        deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True),
            ('payment_state', '=', 'paid')
        ])
        
        deposit_paid = sum(deposit_invoices.mapped('amount_total'))
        #_logger.info(f"Tổng tiền cọc đã thanh toán: {deposit_paid}")
        
        # SỬA LỖI: Tính remaining_amount từ giá trị gốc, không phải amount_total đã trừ cọc
        remaining_amount = total_amount_original - deposit_paid
        #_logger.info(f"Số tiền còn lại cần thu: {remaining_amount} = {total_amount_original} - {deposit_paid}")
        
        if remaining_amount <= 0:
            #_logger.info("Không cần tạo hóa đơn - đã thu đủ tiền cọc")
            # Đánh dấu đã xác nhận thanh toán và hoàn thành đơn hàng
            self.is_payment_confirmed = True
            self.is_order_completed = True
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Hoàn thành!',
                    'message': f'Đơn hàng {self.name} đã được thanh toán đủ qua tiền cọc và hoàn thành.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        
        # Tạo hóa đơn thanh toán cuối
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'invoice_date': fields.Date.context_today(self),
            'dac_deposit_invoice': False,  # Không phải hóa đơn cọc
            'invoice_line_ids': [],
        }
        
        # Thêm dòng sản phẩm từ order (CHỈ LẤY DÒNG DƯƠNG - bỏ qua dòng cọc âm để tránh trừ 2 lần)
        for line in self.order_line:
            if line.display_type:
                # Bỏ qua section/note liên quan đến cọc
                if 'cọc' in (line.name or '').lower():
                    continue
                # Thêm section/note khác
                invoice_vals['invoice_line_ids'].append((0, 0, {
                    'display_type': line.display_type,
                    'name': line.name,
                    'sequence': line.sequence,
                }))
            elif line.product_id and line.price_unit >= 0:  # CHỈ LẤY DÒNG SẢN PHẨM DƯƠNG
                invoice_vals['invoice_line_ids'].append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'quantity': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'tax_ids': [(6, 0, line.tax_id.ids)],
                    'sequence': line.sequence,
                }))
        
        # Nếu có tiền cọc đã thanh toán, thêm dòng trừ tiền cọc đơn giản
        if deposit_paid > 0:
            # Tìm hoặc tạo sản phẩm "Trừ tiền cọc"
            deduct_product = self.env['product.product'].search([('default_code', '=', 'DEDUCT_DEPOSIT')], limit=1)
            if not deduct_product:
                deduct_product = self.env['product.product'].create({
                    'name': 'Tiền cọc',
                    'default_code': 'DEDUCT_DEPOSIT',
                    'type': 'service',
                    'sale_ok': True,
                    'purchase_ok': False,
                    'list_price': 0.0,
                    'taxes_id': [(6, 0, [])],
                })
            
            # Thêm dòng trừ tiền cọc đơn giản (không có section, không có note)
            invoice_vals['invoice_line_ids'].append((0, 0, {
                'product_id': deduct_product.id,
                'name': 'Tiền cọc',
                'quantity': 1,
                'price_unit': -deposit_paid,
                'tax_ids': [(6, 0, [])],
                'sequence': 9999,
            }))
        
        # Tạo hóa đơn
        invoice = self.env['account.move'].create(invoice_vals)
        #_logger.info(f"Đã tạo hóa đơn thanh toán cuối: {invoice.name}")
        #_logger.info("=== HOÀN THÀNH TẠO HÓA ĐƠN THANH TOÁN CUỐI ===")
        #_logger.info(f"Hóa đơn {invoice.name} đã được tạo, chờ user xác nhận để kích hoạt tiến trình thanh toán")
        
        # QUAN TRỌNG: Refresh computed fields để UI cập nhật ngay
        self._compute_total_invoice_count()
        self._compute_has_final_invoice()
        
        # Mở hóa đơn vừa tạo để user xác nhận
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
            'target': 'current',
        }


    

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

    @api.depends('partner_id')
    def _compute_conversation_count(self):
        for order in self:
            try:
                if order.partner_id and hasattr(order.partner_id, 'commercial_partner_id'):
                    commercial_partner_id = order.partner_id.commercial_partner_id.id
                    count = self.env['page.fm.conversation'].search_count([
                        ('partner_id', 'child_of', commercial_partner_id)
                    ])
                    order.conversation_count = count
                else:
                    order.conversation_count = 0
            except Exception as e:
                _logger.warning(f"Error computing conversation count for order {order.name}: {str(e)}")
                order.conversation_count = 0

    @api.depends('partner_id')
    def _compute_conversation_buttons_html(self):
        """Tạo HTML chứa các buttons cho conversations"""
        for order in self:
            try:
                if order.partner_id and hasattr(order.partner_id, 'commercial_partner_id'):
                    commercial_partner_id = order.partner_id.commercial_partner_id.id
                    all_conversations = self.env['page.fm.conversation'].search([
                        ('partner_id', 'child_of', commercial_partner_id)
                    ])
                    
                    if all_conversations:
                        total_count = len(all_conversations)
                        # Hiển thị tối đa 5 conversations đầu tiên
                        conversations = all_conversations[:5]
                        
                        # Container gọn gàng cho layout mới
                        buttons_html = '<div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center;">'
                        
                        for conv in conversations:
                            # Màu button theo trạng thái
                            btn_class = 'btn-outline-primary'
                            if hasattr(conv, 'status_state'):
                                if conv.status_state == 'done':
                                    btn_class = 'btn-outline-success'
                                elif conv.status_state == 'waiting':
                                    btn_class = 'btn-outline-warning'
                            
                            if hasattr(conv, 'is_unread_fm') and conv.is_unread_fm:
                                btn_class = 'btn-outline-danger'
                            
                            # Tạo button HTML
                            conv_name = conv.name or f'Conversation {conv.id}'
                            # Rút ngắn tên nếu quá dài
                            if len(conv_name) > 12:
                                conv_name = conv_name[:9] + '...'
                            
                            external_url = conv.external_url or '#'
                            
                            buttons_html += f'''
                                <a href="{external_url}" target="_blank" 
                                   class="conversation-btn btn btn-xs {btn_class}" 
                                   style="white-space: nowrap; text-decoration: none; font-size: 10px; padding: 3px 8px; margin: 1px;"
                                   title="{conv.name or f'Conversation {conv.id}'}">
                                    <i class="fa fa-external-link" style="font-size: 9px; margin-right: 3px;"></i>{conv_name}
                                </a>
                            '''
                        
                        # Nếu có nhiều hơn 5 conversations, thêm nút "Xem thêm"
                        if total_count > 5:
                            remaining_count = total_count - 5
                            buttons_html += f'''
                                <button class="btn btn-xs btn-outline-info" 
                                        style="font-size: 10px; padding: 3px 8px; margin: 1px; cursor: pointer;"
                                        onclick="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                                        title="Hiển thị {remaining_count} cuộc hội thoại khác">
                                    +{remaining_count}
                                </button>
                                <div style="display: none; gap: 6px; flex-wrap: wrap;">
                            '''
                            
                            # Hiển thị các conversations còn lại
                            for conv in all_conversations[5:]:
                                btn_class = 'btn-outline-primary'
                                if hasattr(conv, 'status_state'):
                                    if conv.status_state == 'done':
                                        btn_class = 'btn-outline-success'
                                    elif conv.status_state == 'waiting':
                                        btn_class = 'btn-outline-warning'
                                
                                if hasattr(conv, 'is_unread_fm') and conv.is_unread_fm:
                                    btn_class = 'btn-outline-danger'
                                
                                conv_name = conv.name or f'Conversation {conv.id}'
                                if len(conv_name) > 12:
                                    conv_name = conv_name[:9] + '...'
                                
                                external_url = conv.external_url or '#'
                                
                                buttons_html += f'''
                                    <a href="{external_url}" target="_blank" 
                                       class="conversation-btn btn btn-xs {btn_class}" 
                                       style="white-space: nowrap; text-decoration: none; font-size: 10px; padding: 3px 8px; margin: 1px;"
                                       title="{conv.name or f'Conversation {conv.id}'}">
                                        <i class="fa fa-external-link" style="font-size: 9px; margin-right: 3px;"></i>{conv_name}
                                    </a>
                                '''
                            
                            buttons_html += '</div>'
                        
                        buttons_html += '</div>'
                        order.conversation_buttons_html = buttons_html
                    else:
                        order.conversation_buttons_html = '<div style="color: #6c757d; font-size: 11px; font-style: italic;">Không có cuộc hội thoại</div>'
                else:
                    order.conversation_buttons_html = '<div style="color: #6c757d; font-size: 11px; font-style: italic;">Không có cuộc hội thoại</div>'
            except Exception as e:
                _logger.warning(f"Error computing conversation buttons for order {order.name}: {str(e)}")
                order.conversation_buttons_html = '<div style="color: #dc3545; font-size: 11px; font-style: italic;">Lỗi tải cuộc hội thoại</div>'

    def action_open_pancake_conversation(self, conversation_id):
        """Mở trực tiếp cuộc hội thoại trên Pancake"""
        self.ensure_one()
        try:
            conversation = self.env['page.fm.conversation'].browse(int(conversation_id))
            if conversation.exists():
                url = conversation.external_url or '#'
                return {
                    'type': 'ir.actions.act_url',
                    'url': url,
                    'target': 'new',
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Lỗi'),
                        'message': _('Không tìm thấy cuộc hội thoại.'),
                        'type': 'danger',
                        'sticky': False,
                    }
                }
        except Exception as e:
            _logger.error(f"Error opening Pancake conversation {conversation_id}: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Lỗi'),
                    'message': f'Lỗi khi mở cuộc hội thoại: {str(e)}',
                    'type': 'danger',
                    'sticky': False,
                }
            }

    def action_view_conversations(self):
        """Xem tất cả conversations của khách hàng - tương tự như trong res.partner"""
        self.ensure_one()
        
        # Safe access partner information
        partner_id = None
        commercial_partner_id = None
        
        try:
            if self.partner_id:
                partner_id = self.partner_id.id
                # Safe access to commercial_partner_id
                try:
                    if hasattr(self.partner_id, 'commercial_partner_id') and self.partner_id.commercial_partner_id:
                        commercial_partner_id = self.partner_id.commercial_partner_id.id
                    else:
                        commercial_partner_id = partner_id
                except:
                    commercial_partner_id = partner_id
        except Exception as e:
            _logger.warning(f"Error accessing partner info for order {self.name}: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Lỗi'),
                    'message': _('Không thể truy cập thông tin khách hàng.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        if not commercial_partner_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Chưa có khách hàng'),
                    'message': _('Đơn hàng này chưa có khách hàng được gắn.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Check if any conversations exist for this partner
        conv_count = self.env['page.fm.conversation'].search_count([
            ('partner_id', 'child_of', commercial_partner_id)
        ])
        
        if not conv_count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Chưa có hội thoại'),
                    'message': _('Khách hàng này chưa có cuộc hội thoại Pancake nào.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Return action similar to res.partner's action_view_conversations
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Conversations - %s') % (self.partner_id.name or 'Unknown'),
            'res_model': 'page.fm.conversation',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('partner_id', 'child_of', commercial_partner_id)],
            'context': {'search_default_partner_id': partner_id},
        }
        return action
    
    
    # Thông tin bổ sung
    # Số điện thoại đơn hàng
    phone = fields.Char(string="Số điện thoại", related='partner_id.phone', store=True, readonly=False, tracking=True)

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
    
    def _post_production_image_log(self, action):
        """action: 'upload' | 'remove' — chỉ log câu chữ, không preview ảnh."""
        Att = self.env['ir.attachment']
        for rec in self:
            if action == 'upload':
                att = Att.search([
                    ('res_model', '=', 'sale.order'),
                    ('res_id', '=', rec.id),
                    ('res_field', '=', 'production_image'),
                ], order='id desc', limit=1)

                actor = (att.write_uid or att.create_uid) if att else self.env.user
                actor_name = actor.name if actor else self.env.user.name
                filename = (att.name or 'tệp') if att else 'tệp'

                # Chỉ chữ, không gắn attachment -> không có preview ảnh
                body = f"{actor_name} đã tải ảnh sản xuất: {filename}"
                rec.message_post(body=body, subtype_xmlid='mail.mt_note')

            else:
                body = f"{self.env.user.name} đã xoá ảnh sản xuất"
                rec.message_post(body=body, subtype_xmlid='mail.mt_note')
                
    def _production_image_url(self, download=False):
        self.ensure_one()
        if not self.production_image:
            raise UserError("Chưa có hình sản xuất để xem/tải.")
        # /web/content: route chuẩn để tải file/binary
        url = f"/web/content?model=sale.order&id={self.id}&field=production_image&filename=production_image.jpg"
        if download:
            url += "&download=1"
        return url

    def action_view_production_image(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self._production_image_url(download=False),
            "target": "new",  # mở tab mới, xem full-size
        }

    def action_download_production_image(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self._production_image_url(download=True),
            "target": "new",  # hoặc "self" nếu muốn tải trong tab hiện tại
        }
        
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
    
    
    # ==== NÚT 'Hoàn thành' CHO THIẾT KẾ ====
    def action_submit_design_link(self):
        self.ensure_one()

        # Quyền: Design / Production / Manager / Admin
        allowed = (
            self.env.user.has_group('dac_erp.group_dac_erp_design')
            or self.env.user.has_group('dac_erp.group_dac_erp_production')
            or self.env.user.has_group('dac_erp.group_dac_erp_manager')
            or self.env.user.has_group('base.group_system')
        )
        if not allowed:
            raise UserError(_("Bạn không có quyền xác nhận hoàn thành thiết kế!"))

        # Chỉ cho phép ở Đặt cọc hoặc Sản xuất
        if self.order_state_custom not in ('deposit', 'production'):
            raise UserError(_("Chỉ xác nhận khi đơn đang ở Đặt cọc hoặc Sản xuất."))

        # Phải có link
        if not self.design_link:
            raise UserError(_("Vui lòng nhập link thiết kế trước khi hoàn thành."))

        # Đã hoàn tất trước đó?
        if self.design_done:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Đã hoàn tất"),
                    'message': _("Thiết kế đã được xác nhận trước đó."),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # Bổ sung ngày giao & deadline nếu còn trống 
        today = fields.Date.context_today(self)
        vals_done = {
            'design_done': True,
            'design_done_date': fields.Datetime.now(),
            'design_done_user_id': self.env.user.id,
        }
        base = self.design_assigned_date or today
        if not self.design_assigned_date:
            vals_done['design_assigned_date'] = base
        if not self.design_deadline:
            vals_done['design_deadline'] = base if self.is_priority_today else (base + timedelta(days=3))
        self.write(vals_done)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

        
       
    # --- Cờ hoàn tất sản xuất ---
    production_done = fields.Boolean(string="Đã hoàn tất sản xuất", default=False, copy=False, tracking=True)
    production_done_date = fields.Datetime(string="Thời điểm hoàn tất", readonly=True, copy=False)
    production_done_user_id = fields.Many2one('res.users', string="Người xác nhận hoàn tất", readonly=True, copy=False)

    def action_mark_production_done(self):
        """Chỉ Production/Manager/Admin bấm được, trạng thái đang ở 'production' và đã xác nhận sản xuất."""
        allowed = (
            self.env.user.has_group('dac_erp.group_dac_erp_production')
            or self.env.user.has_group('dac_erp.group_dac_erp_manager')
            or self.env.user.has_group('base.group_system')
        )
        if not allowed:
            raise UserError(_("Bạn không thể xác nhận hoàn tất sản xuất!\n"
                              "Vui lòng liên hệ quản lý hoặc bộ phận sản xuất để được hỗ trợ!"))

        for o in self:
            if o.order_state_custom != 'production':
                raise UserError(_("Chỉ xác nhận khi đơn đang ở trạng thái Sản xuất."))
            if not o.is_production_confirmed:
                raise UserError(_("Vui lòng xác nhận sản xuất trước khi hoàn tất."))
            if o.production_done:
                continue  # idempotent

            o.write({
                'production_done': True,
                'production_done_date': fields.Datetime.now(),
                'production_done_user_id': self.env.user.id,
            })
            # Log chữ, không preview ảnh/file
            o.message_post(
                body=f"{self.env.user.name} đã xác nhận hoàn tất sản xuất.",
                subtype_xmlid='mail.mt_note',
            )
        return {
        'type': 'ir.actions.client',
        'tag': 'reload',
    }
    
    
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
    
    # === ONLY POSITIVE LINES: Untaxed amount (bỏ qua dòng cọc âm / section / note) ===
    @api.depends('order_line', 'order_line.display_type', 'order_line.price_subtotal', 'order_line.price_unit')
    def _compute_amount_untaxed_positive_lines(self):
        for order in self:
            # chỉ lấy dòng sản phẩm thực (không display_type) và giá dương
            positive_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.price_unit >= 0
            )
            # price_subtotal: đã trừ chiết khấu, chưa có thuế
            order.amount_untaxed = sum(positive_lines.mapped('price_subtotal'))

    # Override field amount_untaxed để dùng compute mới
    amount_untaxed = fields.Monetary(
        string="Số tiền trước thuế",
        compute="_compute_amount_untaxed_positive_lines",
        currency_field='currency_id',
        store=False,
        tracking=True,      # muốn hiện 2 bullet đúng số → để True
        # tracking=False     # nếu muốn ẩn hẳn 2 bullet → dùng dòng này thay cho tracking=True
    )

    # === RESET PAYMENT STATUS METHODS ===
    def action_reset_payment_status(self):
        """Reset trạng thái thanh toán khi người dùng nhấn nhầm"""
        self.ensure_one()
        
        if not self.env.user.has_group('dac_erp.group_dac_erp_manager'):
            raise AccessError("Chỉ Manager mới có quyền reset trạng thái thanh toán!")
        
        # Kiểm tra đơn hàng có đang ở trạng thái completed không
        if self.order_state_custom != 'completed':
            raise UserError(f"Đơn hàng {self.name} không ở trạng thái 'Hoàn thành', không cần reset!")
        
        # Tìm tất cả hóa đơn liên quan
        invoices = self.env['account.move'].search([
            ('invoice_origin', '=', self.name),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted')
        ])
        
        if not invoices:
            raise UserError(f"Không tìm thấy hóa đơn nào cho đơn hàng {self.name}!")
        
        reset_count = 0
        messages = []
        
        # Reset từng hóa đơn và payments
        for invoice in invoices:
            # Tìm các payments liên quan đến hóa đơn này - NHIỀU CÁCH KHÁC NHAU
            payments = set()
            
            # Cách 1: Tìm qua name field (thường có invoice name)  
            payment_by_memo = self.env['account.payment'].search([
                ('name', 'like', invoice.name),
                ('state', '=', 'posted')
            ])
            payments.update(payment_by_memo.ids)
            
            # Cách 2: Tìm qua reconciled_invoice_ids
            payment_by_reconcile = self.env['account.payment'].search([
                ('reconciled_invoice_ids', 'in', invoice.ids),
                ('state', '=', 'posted')
            ])
            payments.update(payment_by_reconcile.ids)
            
            # Cách 3: Tìm qua account.move.line reconciliation
            invoice_receivable_lines = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and l.balance > 0
            )
            for line in invoice_receivable_lines:
                reconciled_lines = line.matched_debit_ids + line.matched_credit_ids
                for reconcile in reconciled_lines:
                    payment_line = reconcile.debit_move_id if reconcile.debit_move_id != line else reconcile.credit_move_id
                    if payment_line.payment_id:
                        payments.add(payment_line.payment_id.id)
            
            # Convert set to recordset
            payment_records = self.env['account.payment'].browse(list(payments))
            
            # Reset payments
            for payment in payment_records:
                try:
                    # Unreconcile payment trước khi reset
                    if payment.move_id and payment.move_id.line_ids:
                        # Tìm tất cả reconciliations liên quan
                        reconciles_to_remove = payment.move_id.line_ids.mapped('matched_debit_ids') + payment.move_id.line_ids.mapped('matched_credit_ids')
                        if reconciles_to_remove:
                            reconciles_to_remove.unlink()
                    
                    # Reset payment về draft
                    payment.action_draft()
                    reset_count += 1
                    messages.append(f"• Reset payment {payment.name} (Số tiền: {payment.amount:,.0f}đ)")
                    _logger.info(f"Reset payment {payment.name} to draft")
                except Exception as e:
                    messages.append(f"• Lỗi reset payment {payment.name}: {str(e)}")
                    _logger.error(f"Error resetting payment {payment.name}: {str(e)}")
            
            # Reset invoice payment_state về not_paid
            try:
                # Force update payment_state bằng SQL để bypass mọi constraints
                self.env.cr.execute("""
                    UPDATE account_move 
                    SET payment_state = 'not_paid'
                    WHERE id = %s
                """, (invoice.id,))
                
                # Invalidate cache để đảm bảo giá trị mới được load
                invoice.invalidate_recordset(['payment_state'])
                messages.append(f"• Reset hóa đơn {invoice.name} về 'Chưa thanh toán'")
                _logger.info(f"Reset invoice {invoice.name} payment_state to not_paid")
            except Exception as e:
                messages.append(f"• Lỗi reset hóa đơn {invoice.name}: {str(e)}")
                _logger.error(f"Error resetting invoice {invoice.name}: {str(e)}")
        
        # Reset đơn hàng về trạng thái thu tiền
        try:
            self.write({
                'order_state_custom': 'payment',
                'is_payment_confirmed': False,
                'is_order_completed': False
            })
            messages.append(f"• Reset đơn hàng {self.name} về trạng thái 'Thu tiền'")
            _logger.info(f"Reset order {self.name} to payment state")
        except Exception as e:
            messages.append(f"• Lỗi reset đơn hàng {self.name}: {str(e)}")
            _logger.error(f"Error resetting order {self.name}: {str(e)}")
        
        # Commit changes
        self.env.cr.commit()
        
        # Trả về thông báo
        message = f"✅ Reset thành công!\n\n" + "\n".join(messages)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reset Trạng Thái Thanh Toán',
                'message': message,
                'type': 'success',
                'sticky': True
            }
        }

  
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

    # NEW: helper chung để tạo badge DAC
    def _dac_make_badge(self, key: str, label: str) -> str:
        key = (key or '').strip()
        label = (label or key or '').strip()
        return (
            f'<span class="badge rounded-pill dac-badge dac-badge--{html_escape(key)}">'
            f'{html_escape(label)}</span>'
        )

    @api.depends('order_state_custom')
    def _compute_order_state_badge(self):
        selection = dict(self._fields['order_state_custom'].selection)
        for rec in self:
            key = rec.order_state_custom or ''
            label = selection.get(key, key)
            rec.order_state_badge = rec._dac_make_badge(key, label)
                    
    # ===== UI flags for view visibility =====
    is_admin_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_manager_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_design_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_production_user = fields.Boolean(compute="_compute_user_flags", store=False)
    is_sale_user = fields.Boolean(compute="_compute_user_flags", store=False)
    
    # ===== VIP Customer Class for styling =====
    partner_vip_class = fields.Char(
        string='VIP Class',
        compute='_compute_partner_vip_class',
        store=False,
        help='CSS class cho khách hàng VIP/Loyal'
    )

    @api.depends('partner_id')
    def _compute_partner_vip_class(self):
        """
        Tính toán VIP class từ partner tags (nếu có)
        Trả về:
        - 'vip' nếu chỉ có tag Khách lớn → decoration-warning (VÀNG)
        - 'loyal' nếu chỉ có tag Khách quen → decoration-info (XANH DƯƠNG)
        - 'premium' nếu có cả 2 tags → decoration-danger (ĐỎ)
        - '' nếu không có tag nào
        """
        for rec in self:
            # Kiểm tra partner tồn tại
            if not rec.partner_id:
                rec.partner_vip_class = ''
                continue
            
            # Kiểm tra field pancake_tag_ids có tồn tại không
            if not hasattr(rec.partner_id, 'pancake_tag_ids'):
                rec.partner_vip_class = ''
                continue
            
            # Kiểm tra có tags không
            pancake_tags = rec.partner_id.pancake_tag_ids
            if not pancake_tags:
                rec.partner_vip_class = ''
                continue
            
            tag_names = [tag.name.lower() for tag in pancake_tags]
            
            # Kiểm tra tag
            is_vip = 'khách lớn' in tag_names or 'vip' in tag_names
            is_loyal = 'khách quen' in tag_names or 'loyal' in tag_names
            
            # Quyết định class
            if is_vip and is_loyal:
                rec.partner_vip_class = 'premium'  # Cả 2 → ĐỎ
            elif is_vip:
                rec.partner_vip_class = 'vip'      # Chỉ VIP → VÀNG
            elif is_loyal:
                rec.partner_vip_class = 'loyal'    # Chỉ Loyal → XANH
            else:
                rec.partner_vip_class = ''


    def _compute_user_flags(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        is_manager = user.has_group('dac_erp.group_dac_erp_manager')
        is_design = user.has_group('dac_erp.group_dac_erp_design')
        is_production = user.has_group('dac_erp.group_dac_erp_production')
        is_sale = user.has_group('dac_erp.group_dac_erp_sale')
        
        for rec in self:
            rec.is_admin_user = is_admin
            rec.is_manager_user = is_manager
            rec.is_design_user = is_design
            rec.is_production_user = is_production
            rec.is_sale_user = is_sale