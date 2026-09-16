from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from datetime import date, timedelta

_logger = logging.getLogger(__name__)


class SaleOrderWorkflow(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # Dropdown trạng thái cho LIST view (chỉnh sửa inline)
    # ------------------------------------------------------------------
    # Field riêng, KHÔNG lưu DB, tách biệt hoàn toàn với order_state_custom.
    # Lý do: rất nhiều code nội bộ (action, MCP, pancake, completion check) ghi
    # thẳng order_state_custom -> nếu gắn inverse trực tiếp lên nó sẽ vỡ mọi luồng.
    # Khi user đổi dropdown trong list, web client ghi 'order_state_select' ->
    # inverse chạy -> route qua đúng action workflow (side-effect giống nút form).
    order_state_select = fields.Selection(
        selection=lambda self: self._fields['order_state_custom'].selection,
        string='Trạng thái',
        compute='_compute_order_state_select',
        inverse='_inverse_order_state_select',
        store=False,
    )

    @api.depends('order_state_custom')
    def _compute_order_state_select(self):
        for rec in self:
            rec.order_state_select = rec.order_state_custom

    def _inverse_order_state_select(self):
        for rec in self:
            target = rec.order_state_select
            if target and target != rec.order_state_custom:
                rec._apply_quick_state_change(target)

    def _apply_quick_state_change(self, target):
        """Đổi trạng thái từ dropdown trong list -> route qua action workflow.

        Tái dùng đúng các action của form để side-effect/validation giống hệt
        (xác nhận, tạo/kiểm tra hóa đơn cọc, đánh dấu mốc sản xuất...).
        Bước cần nhập liệu (wizard) -> báo lỗi hướng dẫn mở form, không để state dở dang.
        """
        self.ensure_one()
        current = self.order_state_custom
        if target == current:
            return

        _OPEN_FORM = _(
            "Bước này cần nhập liệu/xác nhận trong form đơn hàng "
            "(hạn sản xuất, địa chỉ giao hàng, xác nhận cọc...). "
            "Vui lòng mở đơn hàng để hoàn tất."
        )

        def _run(result):
            # Action trả về dict = wizard cần nhập liệu -> không thể hiện từ list.
            if isinstance(result, dict):
                raise UserError(_OPEN_FORM)

        # Hủy đơn: chỉ hợp lệ từ báo giá, action đã guard hóa đơn.
        if target == 'cancel':
            self.action_cancel_order()
            return

        # Đơn đã hủy thì không cho đổi (đồng bộ với write()).
        if current == 'cancel':
            raise UserError(_("Đơn hàng đã hủy! không thể thay đổi!"))

        _STEP = {
            ('quotation', 'deposit'):
                lambda r: r.action_confirm_info(),
            ('deposit', 'production'):
                lambda r: r.with_context(from_ui_button=True).action_proceed_to_production(),
            ('production', 'delivery'):
                lambda r: r._quick_proceed_fulfillment('delivery'),
            ('production', 'installation'):
                lambda r: r._quick_proceed_fulfillment('installation'),
            ('delivery', 'payment'):
                lambda r: r.action_confirm_info(),
            ('installation', 'payment'):
                lambda r: r.action_confirm_info(),
        }

        handler = _STEP.get((current, target))
        if handler:
            _run(handler(self))
            return

        # Lùi 1 bước (manager/system) -> tái dùng action_back_custom_step (đã gate quyền).
        _LINEAR = ['quotation', 'deposit', 'production', 'delivery', 'installation', 'payment']
        if current in _LINEAR and target in _LINEAR:
            prev_collapse = {
                'delivery': 'production',
                'installation': 'production',
                'payment': self.fulfillment_method or 'delivery',
            }
            expected_prev = prev_collapse.get(current)
            if expected_prev is None and _LINEAR.index(current) > 0:
                expected_prev = _LINEAR[_LINEAR.index(current) - 1]
            if target == expected_prev:
                self.action_back_custom_step()
                return

        labels = dict(self._fields['order_state_custom'].selection)
        raise UserError(_(
            "Không thể chuyển trực tiếp từ '%(from_state)s' sang '%(to_state)s' ngoài danh sách. "
            "Vui lòng dùng form đơn hàng để thực hiện bước này.",
            from_state=labels.get(current, current),
            to_state=labels.get(target, target),
        ))

    def _quick_proceed_fulfillment(self, target):
        """production -> delivery/installation: cần đã xác nhận sản xuất.

        Khớp với form: nút Giao hàng/Thi công bị ẩn theo fulfillment_method
        (action_proceed_to_* không tự kiểm tra) -> ở đây chặn nhánh sai method
        để đơn không bị đẩy sai luồng (vd đơn xe đẩy luôn là 'delivery')."""
        self.ensure_one()
        if not self.is_production_confirmed:
            raise UserError(_(
                "Vui lòng xác nhận sản xuất trong form đơn hàng trước khi chuyển bước."
            ))
        method = self.fulfillment_method or 'delivery'
        if target != method:
            labels = {'delivery': _('Giao hàng'), 'installation': _('Thi công - lắp đặt')}
            raise UserError(_(
                "Đơn hàng có hình thức '%(method)s' nên không thể chuyển sang '%(target)s'. "
                "Vui lòng đổi hình thức trong form nếu cần.",
                method=labels.get(method, method),
                target=labels.get(target, target),
            ))
        if target == 'installation':
            return self.action_proceed_to_installation()
        return self.action_proceed_to_delivery()

    def _get_default_production_deadline_days(self):
        self.ensure_one()
        param = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.production_default_deadline_days',
            default='3',
        )
        try:
            days = int(param)
        except (TypeError, ValueError):
            days = 3
        return max(days, 1)

    def _open_production_deadline_wizard(self):
        self.ensure_one()
        return {
            'name': 'Chọn ngày hoàn thành sản xuất',
            'type': 'ir.actions.act_window',
            'res_model': 'production.deadline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': 'sale.order',
            },
        }

    def _open_delivery_address_wizard(self):
        self.ensure_one()
        return {
            'name': 'Thông tin giao hàng',
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.address.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': 'sale.order',
            },
        }

    def _mark_production_started(self):
        self.ensure_one()
        self.write({
            'order_state_custom': 'production',
            'is_production_confirmed': True,
            'reached_production': True,
        })
        return True

    def _action_proceed_to_production_with_deadline(self):
        self.ensure_one()

        if self.order_state_custom != 'deposit':
            raise UserError("Chỉ có thể tiến hành sản xuất từ trạng thái đặt cọc!")

        if not self.production_deadline:
            return self._open_production_deadline_wizard()

        if not self.has_deposit:
            self._mark_production_started()
            return True

        deposit_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', self.name),
            ('dac_deposit_invoice', '=', True)
        ])

        if deposit_invoices:
            paid_invoices = deposit_invoices.filtered(lambda inv: inv.payment_state == 'paid')
            if not paid_invoices or len(paid_invoices) < len(deposit_invoices):
                raise UserError("Có hóa đơn đặt cọc chưa được thanh toán! Vui lòng thanh toán hóa đơn cọc trước khi tiến hành sản xuất.")

            self._mark_production_started()
            return True

        return {
            'name': 'Xác nhận đơn không cọc',
            'type': 'ir.actions.act_window',
            'res_model': 'no.deposit.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def _confirm_delivery_step(self, delivery_address=None, customer_pickup=False):
        self.ensure_one()

        if self.order_state_custom != 'delivery':
            raise UserError(_("Chỉ có thể xác nhận giao hàng ở bước giao hàng!"))

        address = self.delivery_address if delivery_address is None else delivery_address
        address = (address or '').strip()

        if not address and not customer_pickup:
            return self._open_delivery_address_wizard()

        if customer_pickup and not address:
            address = 'Khách đến nhận hàng'

        self.delivery_address = address
        self.is_delivery_confirmed = True
        self.check_and_update_completion_status()
        if self.order_state_custom != 'completed':
            self.order_state_custom = 'payment'
            _logger.info(f"[CONFIRM] Order {self.name}: Delivery confirmed -> Payment")
        return True

    def action_confirm_delivery_info(self):
        for order in self:
            result = order._confirm_delivery_step()
            if isinstance(result, dict):
                return result
        return True

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
        state_order = ['quotation', 'deposit', 'production', 'delivery', 'installation', 'payment']
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
        state_order = ['quotation', 'deposit', 'production', 'delivery', 'installation', 'payment']
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
            if order.order_state_custom == 'delivery':
                result = order._confirm_delivery_step()
                if isinstance(result, dict):
                    return result
                continue
            # Kiểm tra ở tiến trình đầu tiên (báo giá)
            if order.order_state_custom == 'quotation':
                # Chỉ tính dòng sản phẩm/dịch vụ, không tính section/note.
                # Cho phép dòng không có product_id, miễn là có Tên sản phẩm/Dịch vụ.
                product_lines = order.order_line.filtered(
                    lambda l: not l.display_type and (l.product_id or (l.name or '').strip())
                )
                if not product_lines:
                    raise UserError("Yêu cầu nhập Tên sản phẩm/Dịch vụ trước khi xác nhận!")
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
        # SAFETY CHECK: avoid accidental non-UI triggers
        if not self.env.context.get('from_ui_button'):
            return False

        for order in self:
            result = order._action_proceed_to_production_with_deadline()
            if isinstance(result, dict):
                return result

        return True

    def action_proceed_to_delivery(self):
        """Tiến hành giao hàng từ trạng thái sản xuất"""
        for order in self:
            if order.order_state_custom != 'production':
                raise UserError(_("Chỉ có thể tiến hành giao hàng từ trạng thái sản xuất!"))

            # Đã xác nhận sản xuất (được set khi bấm "Tiến hành sản xuất")
            if not order.is_production_confirmed:
                raise UserError(_("Vui lòng xác nhận sản xuất trước khi tiến hành giao hàng!"))

            # Nếu chưa xác nhận hoàn tất sản xuất, hiện popup cảnh báo
            if not order.production_done:
                return {
                    'name': 'Sản xuất chưa hoàn tất',
                    'type': 'ir.actions.act_window',
                    'res_model': 'production.not.done.warning.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'active_id': order.id,
                        'active_model': 'sale.order',
                    },
                }

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
            order.started_delivery = True
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
