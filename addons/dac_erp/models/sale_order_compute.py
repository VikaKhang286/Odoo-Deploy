from odoo import models, fields, api
from odoo.tools import html_escape
import logging

_logger = logging.getLogger(__name__)


class SaleOrderCompute(models.Model):
    _inherit = 'sale.order'

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

    @api.depends('order_line', 'order_line.price_subtotal', 'order_line.price_unit')
    def _compute_amount_untaxed_original(self):
        """Tính số tiền sản phẩm gốc (Thành tiền - chỉ dòng dương, bỏ qua dòng cọc âm)"""
        for order in self:
            # Chỉ lấy dòng sản phẩm có giá dương (bỏ qua dòng cọc âm)
            product_lines = order.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
            order.amount_untaxed_original = sum(product_lines.mapped('price_subtotal'))

    @api.depends('order_line', 'order_line.price_tax')
    def _compute_amount_tax_positive_lines(self):
        """Tính thuế chỉ từ dòng có giá dương (bỏ qua dòng cọc âm)"""
        for order in self:
            # Chỉ lấy dòng sản phẩm có giá dương (bỏ qua dòng cọc âm)
            product_lines = order.order_line.filtered(lambda l: not l.display_type and l.price_unit >= 0)
            order.amount_tax = sum(product_lines.mapped('price_tax'))

    @api.depends(
        'amount_untaxed_original', 'amount_tax', 'promotion_amount',
        'shipping_fee',
    )
    def _compute_amount_total_positive_lines(self):
        """Tính tổng tiền đơn hàng, gồm phí vận chuyển."""
        for order in self:
            order.amount_total = (
                order.amount_untaxed_original
                + order.shipping_fee
                + order.amount_tax
                - order.promotion_amount
            )

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
                else:
                    # Chỉ có hóa đơn cọc -> KHÔNG set hoàn thành
                    _logger.info(f"Order {order.name}: Chỉ có hóa đơn cọc đã thanh toán, chưa set hoàn thành")

    @api.depends('order_line', 'order_line.display_type', 'order_line.price_subtotal', 'order_line.price_unit')
    def _compute_amount_untaxed_positive_lines(self):
        for order in self:
            # chỉ lấy dòng sản phẩm thực (không display_type) và giá dương
            positive_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.price_unit >= 0
            )
            # price_subtotal: đã trừ chiết khấu, chưa có thuế
            order.amount_untaxed = sum(positive_lines.mapped('price_subtotal'))

    @api.depends('production_deadline', 'order_state_custom', 'production_done')
    def _compute_is_production_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_production_overdue = (
                rec.order_state_custom == 'production'
                and bool(rec.production_deadline)
                and not rec.production_done
                and rec.production_deadline < today
            )

    def _dac_make_badge(self, key: str, label: str) -> str:
        key = (key or '').strip()
        label = (label or key or '').strip()
        return (
            f'<span class="badge rounded-pill dac-badge dac-badge--{html_escape(key)}">'
            f'{html_escape(label)}</span>'
        )

    @api.depends('order_state_custom', 'design_done', 'user_id_design',
                 'production_done', 'is_production_confirmed', 'is_production_overdue')
    def _compute_order_state_badge(self):
        selection = dict(self._fields['order_state_custom'].selection)
        for rec in self:
            key = rec.order_state_custom or ''
            label = selection.get(key, key)
            # Làm giàu badge ở trạng thái production với sub-context
            if key == 'production':
                if rec.is_production_overdue:
                    rec.order_state_badge = (
                        f'<span class="badge rounded-pill dac-badge dac-badge--production-overdue">'
                        f'{html_escape(label)} / Trễ hạn</span>'
                    )
                    continue
                if rec.production_done and not rec.is_production_confirmed:
                    label = f'{label} / Chờ XN'
                elif not rec.design_done and rec.user_id_design:
                    label = f'{label} / Chờ TK'
            rec.order_state_badge = rec._dac_make_badge(key, label)

    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)

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
