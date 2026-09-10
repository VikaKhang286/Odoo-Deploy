from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError
import logging
from datetime import date, timedelta

_logger = logging.getLogger(__name__)


class SaleOrderInvoice(models.Model):
    _inherit = 'sale.order'

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

    def _check_auto_deposit_on_load(self):
        """Kiểm tra tự động khi load record"""
        self.check_and_add_deposit_line()

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
            self.write({
                'is_payment_confirmed': True,
                'is_order_completed': True,
                'order_state_custom': 'completed',
            })
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

        # Mở popup chọn phương thức thanh toán và tự động tạo phiếu thu
        return {
            'name': 'Xác nhận thanh toán cuối cùng',
            'type': 'ir.actions.act_window',
            'res_model': 'final.payment.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'sale.order',
                'active_id': self.id,
                'default_amount': remaining_amount,
            }
        }

    def _create_final_invoice_and_payment(self, journal_id, payment_date):
        """Logic tạo hóa đơn và thanh toán từ wizard"""
        self.ensure_one()

        # Tìm số tiền cọc đã thanh toán
        deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True),
            ('payment_state', '=', 'paid')
        ])
        deposit_paid = sum(deposit_invoices.mapped('amount_total'))

        # Tạo hóa đơn thanh toán cuối
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'invoice_date': payment_date,
            'dac_deposit_invoice': False,
            'invoice_line_ids': [],
        }

        # Thêm dòng sản phẩm từ order (Bỏ dòng cọc âm)
        for line in self.order_line:
            if line.display_type:
                if 'cọc' in (line.name or '').lower():
                    continue
                invoice_vals['invoice_line_ids'].append((0, 0, {
                    'display_type': line.display_type,
                    'name': line.name,
                    'sequence': line.sequence,
                }))
            elif line.product_id and line.price_unit >= 0:
                invoice_vals['invoice_line_ids'].append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'quantity': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'tax_ids': [(6, 0, line.tax_id.ids)],
                    'sequence': line.sequence,
                }))

        # Deduct deposit
        if deposit_paid > 0:
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

        self._compute_total_invoice_count()
        self._compute_has_final_invoice()

        if invoice.state == 'draft':
            invoice.action_post()

        # Tạo phiếu thu thanh toán
        if invoice.amount_residual > 0:
            payment_register = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=invoice.ids
            ).create({
                'amount': invoice.amount_residual,
                'journal_id': journal_id.id,
                'payment_date': payment_date,
            })
            payment_register._create_payments()

        self.write({
            'is_payment_confirmed': True,
            'is_order_completed': True,
            'order_state_custom': 'completed',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

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
