import mimetypes
import json
import requests
from datetime import timedelta
from difflib import SequenceMatcher
from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


def _normalize_phone(phone):
    """Chuẩn hoá SĐT VN về dạng 0xxxxxxxxx."""
    if not phone:
        return ''
    digits = ''.join(c for c in phone if c.isdigit())
    if digits.startswith('84') and len(digits) > 9:
        digits = '0' + digits[2:]
    return digits


def _clean_honorific(name):
    """Bỏ kính ngữ Anh/Chị ở đầu nếu còn ≥2 từ sau (tránh bỏ tên Anh/Chị)."""
    if not name:
        return name
    parts = name.strip().split()
    if len(parts) >= 3 and parts[0].lower() in ('anh', 'chị', 'chi'):
        return ' '.join(parts[1:])
    return name


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    invoice_file = fields.Binary(string='File hóa đơn', attachment=True)
    invoice_filename = fields.Char(string='Tên file hóa đơn')
    ai_analysis_warning = fields.Text(string='Cảnh báo từ AI', readonly=True)

    # kept for backward compat
    def _clean_phone(self, phone):
        return _normalize_phone(phone)

    def _get_gemini_config(self):
        api_keys = self.env['gemini.api.key'].sudo().search([('is_active', '=', True)], order='sequence, id')
        if not api_keys:
            raise UserError("Vui lòng cấu hình ít nhất một Gemini API Key hoạt động trong phần Cài đặt hệ thống!")

        gemini_models = self.env['gemini.model.priority'].sudo().search([], order='sequence, id')
        model_names = [m.model_name for m in gemini_models] or ['gemini-2.5-flash', 'gemini-2.0-flash']

        get_param = self.env['ir.config_parameter'].sudo().get_param
        system_prompt = get_param('sale_ai_invoice_reader.gemini_system_prompt')
        rotation_enabled = get_param('sale_ai_invoice_reader.gemini_api_rotation') != 'False'

        api_keys_ordered = list(api_keys)
        if rotation_enabled:
            last_key_id_str = get_param('sale_ai_invoice_reader.last_api_key_id')
            last_key_id = int(last_key_id_str) if last_key_id_str else False
            if last_key_id:
                last_idx = next((i for i, k in enumerate(api_keys_ordered) if k.id == last_key_id), -1)
                if last_idx != -1:
                    api_keys_ordered = api_keys_ordered[last_idx + 1:] + api_keys_ordered[:last_idx + 1]

        return api_keys_ordered, model_names, system_prompt

    def _call_gemini_api(self, file_data_b64, filename):
        if isinstance(file_data_b64, bytes):
            file_data_b64 = file_data_b64.decode('utf-8')

        mime_type = 'image/jpeg'
        if filename:
            guessed, _ = mimetypes.guess_type(filename)
            if guessed:
                mime_type = guessed
            elif filename.lower().endswith('.pdf'):
                mime_type = 'application/pdf'
            elif filename.lower().endswith('.png'):
                mime_type = 'image/png'

        api_keys_ordered, model_names, system_prompt = self._get_gemini_config()

        payload = {
            "contents": [{
                "parts": [
                    {"text": "Hãy bóc tách dữ liệu từ tập tin hóa đơn đính kèm này."},
                    {"inlineData": {"mimeType": mime_type, "data": file_data_b64}},
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "customer": {
                            "type": "OBJECT",
                            "properties": {
                                "name": {"type": "STRING"},
                                "phone": {"type": "STRING"},
                                "address": {"type": "STRING"},
                            },
                            "required": ["name", "phone", "address"],
                        },
                        "order_lines": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "product_name": {"type": "STRING"},
                                    "quantity": {"type": "NUMBER"},
                                    "price_unit": {"type": "NUMBER"},
                                    "subtotal": {"type": "NUMBER"},
                                },
                                "required": ["product_name", "quantity", "price_unit", "subtotal"],
                            },
                        },
                        "total_amount": {"type": "NUMBER"},
                        "invoice_number": {"type": "STRING"},
                        "invoice_date": {"type": "STRING"},
                        "note": {"type": "STRING"},
                    },
                    "required": ["customer", "order_lines", "total_amount", "invoice_number", "invoice_date", "note"],
                },
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        response_json = None
        last_error = None
        used_key_id = False

        for model in model_names:
            for key_record in api_keys_ordered:
                url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                       f"{model}:generateContent?key={key_record.key}")
                try:
                    _logger.info("Calling Gemini model=%s key_id=%s", model, key_record.id)
                    resp = requests.post(url, headers={'Content-Type': 'application/json'},
                                         json=payload, timeout=(10, 60))
                    if resp.status_code == 200:
                        response_json = resp.json()
                        used_key_id = key_record.id
                        break
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    _logger.warning("Gemini failed model=%s key_id=%s: %s", model, key_record.id, last_error)
                except requests.exceptions.RequestException as e:
                    last_error = str(e)
                    _logger.warning("Gemini exception model=%s key_id=%s: %s", model, key_record.id, last_error)
            if response_json:
                break

        if not response_json:
            raise UserError(
                f"Không thể đọc hóa đơn bằng AI sau khi đã thử tất cả các Model và API Keys.\nLỗi: {last_error}"
            )

        if used_key_id:
            self.env['ir.config_parameter'].sudo().set_param(
                'sale_ai_invoice_reader.last_api_key_id', str(used_key_id)
            )

        try:
            candidates = response_json.get('candidates', [])
            if not candidates:
                raise ValueError("Candidates rỗng")
            text_content = candidates[0]['content']['parts'][0]['text']
            return json.loads(text_content)
        except Exception as e:
            raise UserError(
                f"Dữ liệu trả về từ AI không hợp lệ.\nChi tiết: {e}\nPhản hồi thô: {response_json}"
            )

    def _match_customer(self, ai_name, ai_phone):
        """Tìm partner phù hợp nhất + gợi ý (dùng cho mode existing)."""
        clean_ai_phone = _normalize_phone(ai_phone)
        partner = False
        suggested_ids = []

        if clean_ai_phone:
            suffix = clean_ai_phone[-9:] if len(clean_ai_phone) >= 9 else clean_ai_phone
            if suffix:
                phone_candidates = self.env['res.partner'].search(
                    ['|', ('phone', 'like', suffix), ('mobile', 'like', suffix)], limit=10
                )
                for p in phone_candidates:
                    if (_normalize_phone(p.phone) == clean_ai_phone
                            or _normalize_phone(p.mobile) == clean_ai_phone):
                        if not partner:
                            partner = p
                        if p.id not in suggested_ids:
                            suggested_ids.append(p.id)

        if not partner and ai_name:
            exact = self.env['res.partner'].search([('name', '=ilike', ai_name)], limit=1)
            if exact:
                partner = exact
                if exact.id not in suggested_ids:
                    suggested_ids.append(exact.id)
            else:
                like_matches = self.env['res.partner'].search([('name', 'ilike', ai_name)], limit=5)
                for p in like_matches:
                    if p.id not in suggested_ids:
                        suggested_ids.append(p.id)
                if like_matches:
                    partner = like_matches[0]
                else:
                    first_word = (ai_name.split() or [''])[0]
                    if first_word:
                        fuzzy_candidates = self.env['res.partner'].search(
                            [('name', 'ilike', first_word)], limit=100
                        )
                        best_ratio, best_partner = 0.0, False
                        for cand in fuzzy_candidates:
                            ratio = SequenceMatcher(None, cand.name.lower(), ai_name.lower()).ratio()
                            if ratio > best_ratio:
                                best_ratio, best_partner = ratio, cand
                        if best_ratio >= 0.70:
                            partner = best_partner
                            if best_partner.id not in suggested_ids:
                                suggested_ids.append(best_partner.id)

        return partner, suggested_ids[:5]

    def _build_invoice_wizard(self, file_data_b64, filename, order_id=False):
        extracted_data = self._call_gemini_api(file_data_b64, filename)

        customer_info = extracted_data.get('customer', {})
        ai_name = customer_info.get('name', '').strip()
        ai_phone = customer_info.get('phone', '').strip()
        ai_address = customer_info.get('address', '').strip()
        order_lines = extracted_data.get('order_lines', [])
        ai_invoice_number = extracted_data.get('invoice_number', '').strip()
        ai_invoice_date = extracted_data.get('invoice_date', '').strip()
        ai_note = extracted_data.get('note', '').strip()
        clean_ai_phone = _normalize_phone(ai_phone)
        cleaned_name = _clean_honorific(ai_name)

        mode = 'existing' if order_id else 'new'

        # --- Partner matching ---
        partner, suggested_ids = self._match_customer(ai_name, ai_phone)

        warnings = []
        partner_found = bool(partner)
        create_partner = not partner

        if partner:
            similarity = SequenceMatcher(None, partner.name.lower(), ai_name.lower()).ratio()
            if similarity < 0.70:
                warnings.append(
                    f"Tên khách hàng bóc tách '{ai_name}' khác biệt với tên hệ thống '{partner.name}'"
                    f" (Độ khớp: {int(similarity * 100)}%)."
                )
            clean_p_phone = _normalize_phone(partner.phone)
            clean_p_mobile = _normalize_phone(partner.mobile)
            partner_phones = [p for p in [clean_p_phone, clean_p_mobile] if p]
            if clean_ai_phone and clean_ai_phone not in partner_phones:
                sys_phone = partner.phone or partner.mobile or 'không có'
                warnings.append(
                    f"Số điện thoại trên hóa đơn ({ai_phone}) không khớp với số trên hệ thống ({sys_phone})."
                )
        else:
            warnings.append(
                f"Không tìm thấy khách hàng '{ai_name}' (SĐT: {ai_phone}) trên hệ thống."
            )

        # --- Build line previews ---
        wizard_lines = []
        for line in order_lines:
            p_name = line.get('product_name', '').strip()
            qty = line.get('quantity', 1)
            price = line.get('price_unit', 0)
            product = self.env['product.product'].search([('name', '=ilike', p_name)], limit=1)
            if not product:
                product = self.env['product.product'].search([('name', 'ilike', p_name)], limit=1)
            if not product:
                warnings.append(f"Không tìm thấy sản phẩm '{p_name}' trong hệ thống. Vui lòng chọn thủ công.")
            wizard_lines.append((0, 0, {
                'product_name': p_name,
                'product_id': product.id if product else False,
                'quantity': qty,
                'price_unit': price,
            }))

        order_obj = self.env['sale.order'].browse(order_id) if order_id else False
        default_import_mode = 'replace' if (not order_obj or not order_obj.order_line) else 'append'

        wizard_vals = {
            'sale_order_id': order_id or False,
            'mode': mode,
            'partner_id': partner.id if partner else False,
            'partner_found': partner_found,
            'create_partner': create_partner,
            'skip_partner': False,
            'partner_name': ai_name,
            'partner_phone': ai_phone,
            'partner_address': ai_address,
            'warnings_text': '\n'.join(warnings) if warnings else '',
            'import_mode': default_import_mode,
            'line_ids': wizard_lines,
            'suggested_partner_ids': [(6, 0, suggested_ids)],
            # New fields
            'extracted_name': ai_name,
            'extracted_phone': ai_phone,
            'extracted_address': ai_address,
            'cleaned_name': cleaned_name,
            'invoice_number': ai_invoice_number,
            'invoice_date_text': ai_invoice_date,
            'invoice_note': ai_note,
        }

        # For new order mode: pre-compute matches
        if mode == 'new':
            WizardModel = self.env['gemini.create.partner.wizard']
            conv_ids, pancake_total = WizardModel._find_pancake_matches('7d', cleaned_name, clean_ai_phone, 5)
            pancake_partner_ids = self.env['page.fm.conversation'].sudo().browse(conv_ids).mapped('partner_id').ids
            partner_ids, partner_total = WizardModel._find_partner_matches(
                cleaned_name, clean_ai_phone, ai_address, 5, exclude_ids=pancake_partner_ids
            )
            wizard_vals.update({
                'pancake_match_ids': [(6, 0, conv_ids)],
                'pancake_total': pancake_total,
                'partner_match_ids': [(6, 0, partner_ids)],
                'partner_total': partner_total,
            })

        wizard = self.env['gemini.create.partner.wizard'].sudo().create(wizard_vals)
        return {
            'name': 'Xem trước và đối chiếu Hóa đơn AI',
            'type': 'ir.actions.act_window',
            'res_model': 'gemini.create.partner.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'res_id': wizard.id,
            'context': {'dialog_size': 'extra-large'},
        }

    def action_open_upload_dialog(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'sale_ai_invoice_reader.open_upload_dialog',
            'params': {'order_id': self.id},
        }

    @api.model
    def action_open_upload_dialog_new_order(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'sale_ai_invoice_reader.open_upload_dialog',
            'params': {},
        }

    def action_open_manual_import_wizard(self):
        """Nhập đơn thủ công — mở thẳng wizard tạo đơn (mode='new') để gõ tay,
        cùng form với luồng 'Nhập đơn từ ảnh' nhưng bỏ phần AI bóc tách."""
        wizard = self.env['gemini.create.partner.wizard'].sudo().create({
            'mode': 'new',
            'is_manual': True,
            'create_partner': False,
            'import_mode': 'replace',
        })
        return {
            'name': 'Nhập đơn thủ công',
            'type': 'ir.actions.act_window',
            'res_model': 'gemini.create.partner.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'res_id': wizard.id,
            'context': {'dialog_size': 'extra-large'},
        }

    @api.model
    def action_read_invoice_ai_from_data(self, file_data=False, filename='invoice.jpg', order_id=False):
        if not file_data:
            raise UserError("Không có dữ liệu file để đọc!")
        return self._build_invoice_wizard(file_data, filename, order_id=order_id or False)

    def action_read_invoice_ai(self):
        self.ensure_one()
        if not self.invoice_file:
            raise UserError("Vui lòng tải lên ảnh hoặc file PDF hóa đơn trước khi thực hiện!")
        file_data = self.invoice_file
        if isinstance(file_data, bytes):
            file_data = file_data.decode('utf-8')
        return self._build_invoice_wizard(file_data, self.invoice_filename or 'invoice.jpg', order_id=self.id)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_wizard_order_count = fields.Integer(
        string='Số đơn hàng',
        compute='_compute_ai_wizard_order_count',
        store=False,
    )

    def _compute_ai_wizard_order_count(self):
        result = self.env['sale.order'].read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'], ['partner_id'],
        )
        counts = {r['partner_id'][0]: r['partner_id_count'] for r in result}
        for rec in self:
            rec.ai_wizard_order_count = counts.get(rec.id, 0)

    def action_view_orders_in_wizard(self):
        """Mở danh sách đơn hàng của partner này trong popup."""
        self.ensure_one()
        if not self.ai_wizard_order_count:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': f'Đơn hàng — {self.name}',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'target': 'new',
        }

    def action_select_as_ai_wizard_partner(self):
        """Chọn partner này làm khách hàng trong wizard tạo đơn từ ảnh."""
        self.ensure_one()
        wizard_id = self.env.context.get('active_wizard_id')
        if not wizard_id:
            return
        wizard = self.env['gemini.create.partner.wizard'].sudo().browse(wizard_id)
        if wizard.exists():
            wizard.write({'partner_id': self.id, 'create_partner': False})
        return wizard._reload_wizard_action()


class GeminiInvoiceLinePreview(models.TransientModel):
    _name = 'gemini.invoice.line.preview'
    _description = 'Chi tiết dòng hàng xem trước'

    wizard_id = fields.Many2one('gemini.create.partner.wizard', string='Wizard', ondelete='cascade')
    product_name = fields.Char(string='Tên sản phẩm (Hóa đơn)', required=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm hệ thống')
    quantity = fields.Float(string='Số lượng', default=1.0)
    price_unit = fields.Float(string='Đơn giá')
    subtotal = fields.Float(string='Thành tiền', compute='_compute_subtotal', store=True)
    currency_id = fields.Many2one(
        'res.currency', string='Tiền tệ',
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.quantity * rec.price_unit

    @api.onchange('product_id')
    def _onchange_product_id_fill_name(self):
        """Nhập tay: chọn sản phẩm hệ thống thì tự điền tên dòng nếu còn trống."""
        for rec in self:
            if rec.product_id and not rec.product_name:
                rec.product_name = rec.product_id.display_name


class GeminiCreatePartnerWizard(models.TransientModel):
    _name = 'gemini.create.partner.wizard'
    _description = 'Xem trước và đối chiếu Hóa đơn AI'

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán hàng')
    mode = fields.Selection([
        ('existing', 'Cập nhật đơn hàng hiện tại'),
        ('new', 'Tạo đơn hàng mới'),
    ], string='Chế độ', default='existing', required=True)
    # True khi mở từ "Nhập đơn thủ công" (không có bước AI bóc tách ảnh) —
    # ẩn vùng thông tin bóc tách + gợi ý, cho phép gõ tay tên sản phẩm.
    is_manual = fields.Boolean(string='Nhập tay', default=False)

    # Customer selection
    partner_id = fields.Many2one('res.partner', string='Khách hàng hệ thống')
    partner_found = fields.Boolean(string='Tìm thấy khách hàng')
    suggested_partner_ids = fields.Many2many(
        'res.partner', 'gemini_wizard_suggested_partner_rel',
        'wizard_id', 'suggest_partner_id', string='Gợi ý từ AI',
    )
    create_partner = fields.Boolean(string='Tạo mới khách hàng?', default=False)
    skip_partner = fields.Boolean(string='Bỏ qua cập nhật khách hàng', default=False)
    partner_name = fields.Char(string='Tên khách hàng')
    partner_phone = fields.Char(string='Số điện thoại')
    partner_address = fields.Char(string='Địa chỉ')

    warnings_text = fields.Text(string='Cảnh báo')
    import_mode = fields.Selection([
        ('append', 'Bổ sung (Giữ dòng cũ, thêm dòng mới)'),
        ('replace', 'Thay thế (Xóa dòng cũ, ghi đè dòng mới)'),
        ('update', 'Cập nhật (Trùng sản phẩm sẽ cập nhật SL/Giá, khác sẽ bổ sung)'),
    ], string='Phương thức đối chiếu', default='append', required=True)

    line_ids = fields.One2many('gemini.invoice.line.preview', 'wizard_id', string='Dòng hàng bóc tách')
    total_wizard = fields.Float(
        string='Tổng cộng (xem trước)',
        compute='_compute_total_wizard', store=False,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Tiền tệ',
        default=lambda self: self.env.company.currency_id,
    )

    # --- Thông tin AI bóc tách (new mode) ---
    extracted_name = fields.Char(string='Tên (AI bóc tách)')
    extracted_phone = fields.Char(string='SĐT (AI bóc tách)')
    invoice_number = fields.Char(string='Số hoá đơn')
    invoice_date_text = fields.Char(string='Ngày hoá đơn (AI)')
    invoice_note = fields.Text(string='Ghi chú trên hoá đơn')

    # --- Trạng thái & thanh toán ban đầu (new mode) ---
    initial_state = fields.Selection([
        ('quotation', 'Báo giá'),
        ('deposit', 'Đặt cọc'),
        ('production', 'Đang sản xuất'),
        ('installation', 'Thi công'),
        ('delivery', 'Giao hàng'),
        ('payment', 'Thu tiền'),
        ('completed', 'Hoàn thành'),
    ], string='Trạng thái đơn', default='quotation')
    fulfillment_method = fields.Selection([
        ('delivery', 'Giao hàng'),
        ('installation', 'Thi công - lắp đặt'),
    ], string='Hình thức thực hiện', default='delivery')
    has_deposit = fields.Boolean(string='Có đặt cọc?', default=False)
    initial_deposit_amount = fields.Float(string='Số tiền cọc', default=0.0)
    extracted_address = fields.Char(string='Địa chỉ (AI bóc tách)')
    cleaned_name = fields.Char(string='Tên sau xử lý')

    # --- Zone 1: Gợi ý Pancake ---
    pancake_match_ids = fields.Many2many(
        'page.fm.conversation',
        'gemini_wiz_pancake_rel', 'wizard_id', 'conv_id',
        string='Gợi ý từ Pancake',
    )
    pancake_search_window = fields.Selection(
        [('7d', '7 ngày'), ('1m', '1 tháng'), ('3m', '3 tháng')],
        default='7d', string='Khoảng tìm kiếm Pancake',
    )
    pancake_limit = fields.Integer(default=5)
    pancake_total = fields.Integer(default=0)

    # --- Zone 2: Gợi ý hệ thống (không phải Pancake) ---
    partner_match_ids = fields.Many2many(
        'res.partner',
        'gemini_wiz_partner_match_rel', 'wizard_id', 'match_partner_id',
        string='Gợi ý từ hệ thống',
    )
    partner_limit = fields.Integer(default=5)
    partner_total = fields.Integer(default=0)

    @api.depends('line_ids.subtotal')
    def _compute_total_wizard(self):
        for rec in self:
            rec.total_wizard = sum(rec.line_ids.mapped('subtotal'))

    @staticmethod
    def _parse_invoice_date(date_str):
        """Thử parse chuỗi ngày từ AI thành Datetime. Hỗ trợ DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY."""
        from datetime import datetime
        if not date_str:
            return False
        formats = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y', '%Y/%m/%d']
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return False

    # ------------------------------------------------------------------ #
    #  Scoring helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _name_score(search_name, candidate_name):
        """
        Tính điểm tên: so sánh whole-word, không phải substring.
        Yêu cầu TẤT CẢ token của search_name đều có trong candidate_name.
        Trả về điểm > 0 chỉ khi tất cả token khớp, ngược lại 0.
        """
        if not search_name or not candidate_name:
            return 0
        tokens = [t for t in search_name.lower().split() if len(t) > 1]
        if not tokens:
            return 0
        candidate_words = set(candidate_name.lower().split())
        matched = sum(1 for t in tokens if t in candidate_words)
        # Yêu cầu tất cả token đều khớp — loại bỏ gợi ý không liên quan
        if matched < len(tokens):
            return 0
        return matched * 40

    def _score_pancake_conv(self, conv, cleaned_name, clean_phone):
        score = 0
        phone_matched = False
        if clean_phone:
            candidates = list(filter(None, [
                _normalize_phone(conv.phone or ''),
                _normalize_phone(conv.partner_id.phone or '') if conv.partner_id else '',
                _normalize_phone(conv.partner_id.mobile or '') if conv.partner_id else '',
            ]))
            if clean_phone in candidates:
                score += 100
                phone_matched = True
        name_score = self._name_score(cleaned_name, conv.customer_name_fm or '')
        # Nếu có SĐT khớp: tên là bonus; nếu không có SĐT: tên phải đủ điều kiện
        if name_score > 0:
            score += name_score if phone_matched else name_score
        elif not phone_matched:
            return 0  # không có SĐT, không khớp tên → loại
        return score

    def _score_partner_record(self, partner, cleaned_name, clean_phone, address):
        score = 0
        phone_matched = False
        if clean_phone:
            if clean_phone in list(filter(None, [
                _normalize_phone(partner.phone or ''),
                _normalize_phone(partner.mobile or ''),
            ])):
                score += 100
                phone_matched = True
        name_score = self._name_score(cleaned_name, partner.name or '')
        if name_score > 0:
            score += name_score
        elif not phone_matched:
            return 0  # không có SĐT, không khớp tên → loại
        if address and partner.street:
            if address.lower()[:30] in partner.street.lower():
                score += 20
        return score

    # ------------------------------------------------------------------ #
    #  Search methods (@api.model — gọi được từ SaleOrder._build_invoice) #
    # ------------------------------------------------------------------ #

    @api.model
    def _find_pancake_matches(self, window, cleaned_name, clean_phone, limit):
        """Trả về (conv_ids[:limit], total_count) có score > 0 trong window."""
        days = {'7d': 7, '1m': 30, '3m': 90}.get(window, 7)
        cutoff = fields.Datetime.now() - timedelta(days=days)
        Conversation = self.env['page.fm.conversation'].sudo()
        candidates = Conversation.search(
            [('last_message_at_fm', '>=', cutoff)],
            order='last_message_at_fm desc', limit=500,
        )
        scored = []
        for conv in candidates:
            score = self._score_pancake_conv(conv, cleaned_name, clean_phone)
            if score > 0:
                scored.append((score, conv.id))
        scored.sort(key=lambda x: x[0], reverse=True)
        all_ids = [cid for _, cid in scored]
        return all_ids[:limit], len(all_ids)

    @api.model
    def _find_partner_matches(self, cleaned_name, clean_phone, address, limit, exclude_ids=None):
        """Trả về (partner_ids[:limit], total_count) có score > 0, loại trừ exclude_ids."""
        exclude_ids = list(exclude_ids or [])
        Partner = self.env['res.partner'].sudo()
        candidate_ids = set()

        if clean_phone:
            suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
            for p in Partner.search(['|', ('phone', 'like', suffix), ('mobile', 'like', suffix)], limit=50):
                candidate_ids.add(p.id)

        if cleaned_name:
            for token in [t for t in cleaned_name.split() if len(t) > 1]:
                for p in Partner.search([('name', 'ilike', token)], limit=30):
                    candidate_ids.add(p.id)

        all_partners = Partner.browse(list(candidate_ids - set(exclude_ids)))
        scored = []
        for p in all_partners:
            score = self._score_partner_record(p, cleaned_name, clean_phone, address)
            if score > 0:
                scored.append((score, p.id))
        scored.sort(key=lambda x: x[0], reverse=True)
        all_ids = [pid for _, pid in scored]
        return all_ids[:limit], len(all_ids)

    # ------------------------------------------------------------------ #
    #  Wizard action buttons                                               #
    # ------------------------------------------------------------------ #

    def _reload_wizard_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gemini.create.partner.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    def _get_clean_phone(self):
        return _normalize_phone(self.extracted_phone or '')

    def action_load_more_pancake(self):
        self.ensure_one()
        new_limit = self.pancake_limit + 5
        conv_ids, total = self._find_pancake_matches(
            self.pancake_search_window, self.cleaned_name, self._get_clean_phone(), new_limit,
        )
        self.write({'pancake_match_ids': [(6, 0, conv_ids)], 'pancake_limit': new_limit, 'pancake_total': total})
        return self._reload_wizard_action()

    def action_expand_pancake_1m(self):
        self.ensure_one()
        conv_ids, total = self._find_pancake_matches('1m', self.cleaned_name, self._get_clean_phone(), 5)
        self.write({
            'pancake_match_ids': [(6, 0, conv_ids)],
            'pancake_search_window': '1m', 'pancake_limit': 5, 'pancake_total': total,
        })
        return self._reload_wizard_action()

    def action_expand_pancake_3m(self):
        self.ensure_one()
        conv_ids, total = self._find_pancake_matches('3m', self.cleaned_name, self._get_clean_phone(), 5)
        self.write({
            'pancake_match_ids': [(6, 0, conv_ids)],
            'pancake_search_window': '3m', 'pancake_limit': 5, 'pancake_total': total,
        })
        return self._reload_wizard_action()

    def action_load_more_partners(self):
        self.ensure_one()
        new_limit = self.partner_limit + 5
        pancake_partner_ids = self.pancake_match_ids.mapped('partner_id').ids
        partner_ids, total = self._find_partner_matches(
            self.cleaned_name, self._get_clean_phone(), self.extracted_address,
            new_limit, exclude_ids=pancake_partner_ids,
        )
        self.write({'partner_match_ids': [(6, 0, partner_ids)], 'partner_limit': new_limit, 'partner_total': total})
        return self._reload_wizard_action()

    def action_toggle_create_partner(self):
        self.ensure_one()
        self.write({'create_partner': not self.create_partner, 'partner_id': False})
        return self._reload_wizard_action()

    # ------------------------------------------------------------------ #
    #  Import                                                              #
    # ------------------------------------------------------------------ #

    def action_import_invoice(self):
        self.ensure_one()

        partner = False
        if not self.skip_partner:
            if self.create_partner:
                if not self.partner_name:
                    raise UserError("Vui lòng điền tên khách hàng để tạo mới!")
                partner = self.env['res.partner'].create({
                    'name': self.partner_name,
                    'phone': self.partner_phone,
                    'street': self.partner_address,
                })
            else:
                if not self.partner_id:
                    raise UserError("Vui lòng chọn khách hàng hoặc tích chọn 'Tạo mới khách hàng'.")
                partner = self.partner_id

        existing_lines_by_prod = {}
        if self.mode == 'existing' and self.sale_order_id:
            for ol in self.sale_order_id.order_line:
                if ol.product_id:
                    existing_lines_by_prod[ol.product_id.id] = ol

        lines_to_write = []
        for line in self.line_ids:
            prod = line.product_id
            if (self.import_mode == 'update' and self.mode == 'existing'
                    and prod and prod.id in existing_lines_by_prod):
                existing_line = existing_lines_by_prod[prod.id]
                lines_to_write.append((1, existing_line.id, {
                    'product_uom_qty': line.quantity,
                    'price_unit': line.price_unit,
                }))
            else:
                lines_to_write.append((0, 0, {
                    'product_id': prod.id if prod else False,
                    'name': prod.display_name if prod else line.product_name,
                    'product_uom_qty': line.quantity,
                    'price_unit': line.price_unit,
                }))

        if self.mode == 'new':
            if not partner:
                raise UserError("Cần có thông tin khách hàng để tạo đơn hàng mới!")
            order_vals = {'partner_id': partner.id}
            if self.invoice_number:
                order_vals['order_number'] = self.invoice_number
            if self.invoice_date_text:
                parsed_date = self._parse_invoice_date(self.invoice_date_text)
                if parsed_date:
                    order_vals['date'] = parsed_date
            if self.invoice_note:
                order_vals['note'] = self.invoice_note
            if self.initial_state and self.initial_state != 'quotation':
                order_vals['order_state_custom'] = self.initial_state
            if self.fulfillment_method:
                order_vals['fulfillment_method'] = self.fulfillment_method
            order_vals['has_deposit'] = self.has_deposit
            if self.has_deposit and self.initial_deposit_amount > 0:
                order_vals['deposit_amount'] = self.initial_deposit_amount
            new_order = self.env['sale.order'].sudo().create(order_vals)
            new_order.order_line = lines_to_write
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': new_order.id,
                'view_mode': 'form',
                'target': 'current',
            }

        order = self.sale_order_id
        if not order:
            raise UserError("Không tìm thấy đơn hàng để cập nhật!")
        if partner:
            order.partner_id = partner.id
        if self.import_mode == 'replace':
            order.order_line = [(5, 0, 0)] + lines_to_write
        else:
            order.order_line = lines_to_write
        order.ai_analysis_warning = self.warnings_text
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # Compatibility wrappers
    def action_create_partner_and_import(self):
        self.ensure_one()
        self.create_partner = True
        self.skip_partner = False
        return self.action_import_invoice()

    def action_only_import(self):
        self.ensure_one()
        self.create_partner = False
        self.skip_partner = True
        return self.action_import_invoice()
