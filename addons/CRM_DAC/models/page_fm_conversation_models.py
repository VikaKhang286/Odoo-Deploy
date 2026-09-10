import requests
import json
import logging
import re
import pytz
from concurrent.futures import ThreadPoolExecutor
from odoo import SUPERUSER_ID
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import time
import odoo

_logger = logging.getLogger(__name__)


class PancakeTagSyncError(Exception):
    """Raised when a synchronous Pancake tag update cannot be completed."""

    def __init__(self, message, sync_results=None):
        super().__init__(message)
        self.sync_results = sync_results or []

PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'
PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1"
_FORM_TOUCH_FIELDS = {
        'partner_id', 'phone',
        'is_unread_fm', 'is_internal_conversation',
        'status_state', 'require_processing', 'suggestion_note',
        'owner_id', 'participant_user_ids',
        # thêm các field hiển thị trên form mà bạn muốn tính là “thay đổi”
    }

def sync_one_conversation(conv_id, dbname):
    try:
        with api.Environment.manage():
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                conv = env['page.fm.conversation'].browse(conv_id)
                conv.action_sync_messages()
                cr.commit()
    except Exception as e:
        _logger.error(f"Lỗi khi sync hội thoại {conv_id}: {e}")



class PageFmConversation(models.Model):
    _name = 'page.fm.conversation'
    _description = 'Page.fm Conversation'
    _order = 'updated_at_fm desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _SYNC_TRANSIENT_MAX_RETRIES = 2
    _SYNC_TRANSIENT_BACKOFF_SECONDS = 2

    # == Main Fields ==
    name = fields.Char(string="Customer Name", compute='_compute_name', store=True, help="Tên khách hàng hoặc ID hội thoại")
    conversation_fm_id = fields.Char(string="Conversation FM ID", required=True, index=True, copy=False, help="ID gốc của hội thoại từ API")
    
    page_fm_page_id = fields.Many2one(
        'page.fm.page', 
        string="Page.fm Page", 
        required=True, 
        ondelete='cascade',
        index=True,
        help="Trang Page.fm mà hội thoại này thuộc về"
    )
    page_fm_id_str_related = fields.Char(related='page_fm_page_id.page_fm_id_str', string="Page FM ID (Related)", store=True, readonly=True)

    # --- Dùng cho URL conversation pancake ---
    conv_page_fm_id = fields.Char( 
    string="Conversation Page ID (from API)",
    index=True,
    help="page_id trả về kèm mỗi hội thoại từ API; ưu tiên dùng khi build URL")

    # == Customer & Partner Fields ==
    customer_fm_id = fields.Char(string="Customer FM ID (for API)", index=True, copy=False, help="Customer ID (UUID) từ API, dùng để lấy tin nhắn chi tiết")
    customer_name_fm = fields.Char(string="Customer Name (from API)", help="Tên khách hàng từ API")
    customer_avatar_url = fields.Char(string="Avatar URL (Pancake)", copy=False, help="URL ảnh đại diện từ Pancake — dùng để tải về và đặt vào partner")
    customer_avatar = fields.Binary(string="Avatar (đã tải)", attachment=True, copy=False, help="Ảnh đại diện khách đã tải từ Pancake về Odoo — hiển thị không phụ thuộc CDN")

    partner_id = fields.Many2one(
        'res.partner',
        string="Customer (Partner)",
        # tracking=True,
        help="Liên kết với Customer trong hệ thống Odoo."
    )
    is_new_customer = fields.Boolean(
        string='Khách hàng mới', related='partner_id.is_new_customer', readonly=True
    )
    phone = fields.Char(string="Phone Number", help="Số điện thoại được tìm thấy từ hội thoại.")

    # == Message & Sync Fields ==
    last_message_snippet = fields.Text(string="Last Message Snippet", help="Đoạn tin nhắn cuối cùng")
    last_message_id = fields.Char(string="Last message FM ID")
    updated_at_fm = fields.Datetime(string="Last Updated (FM)", index=True, help="Thời điểm cập nhật cuối cùng của hội thoại từ API")
    is_unread_fm = fields.Boolean(string="Is Unread", help="Đánh dấu hội thoại là chưa đọc (dựa trên logic !conv.seen từ API)", tracking=True)
    platform_fm = fields.Char(string="Platform (FM)", help="Nền tảng của hội thoại (Zalo, Facebook, Instagram, etc.) được suy ra từ API")
    updated_at_fm_by_hand = fields.Datetime(string="Last Updated (by hand)")
    conv_message_ids = fields.One2many('page.fm.message', 'conversation_id', string="Messages")
    message_count = fields.Integer(string="Message Count", compute='_compute_message_count', store=True)
    last_message_sync_fm = fields.Datetime(string="Last Message Sync (FM)", readonly=True, help="Thời điểm cuối cùng đồng bộ tin nhắn cho hội thoại này.")
    last_message_sync_attempt_at = fields.Datetime(
        string="Last Message Sync Attempt At",
        readonly=True,
        help="Lần gần nhất hệ thống thử đồng bộ tin nhắn cho hội thoại này.",
    )
    last_successful_message_sync_at = fields.Datetime(
        string="Last Successful Message Sync At",
        readonly=True,
        help="Lần gần nhất đồng bộ tin nhắn thành công cho hội thoại này, kể cả khi không có tin mới.",
    )
    last_message_sync_origin = fields.Selection(
        [
            ('continuous', 'Đồng bộ liên tục'),
            ('manual_window', 'Đồng bộ cửa sổ'),
            ('manual_full', 'Đồng bộ toàn bộ'),
            ('manual_single', 'Đồng bộ một hội thoại'),
            ('wizard', 'Đồng bộ từ wizard'),
        ],
        string="Last Message Sync Origin",
        readonly=True,
    )

    #Trường last message
    last_message_at_fm = fields.Datetime(
        string="Thời Gian Tin Nhắn Cuối",
        compute="_compute_last_message_at_fm",
        store=True,
        index=True,
        help="Thời điểm tin nhắn cuối cùng được GỬI (từ model Message), dùng để sort/filter tin nhắn mới nhất."
    )

    _sql_constraints = [
        ('conversation_fm_id_page_uniq', 'unique(conversation_fm_id, page_fm_page_id)', 'Conversation FM ID phải là duy nhất cho mỗi trang!')
    ]
    
    
    # ==== STATUS FIELDS (OPTIMIZED) ====
    status_state = fields.Selection([
        ('new', 'Tin mới'),
        ('recontact', 'Chăm lại khách'),
        ('waiting', 'Đợi khách phản hồi'),
        ('done', 'Đã xử lý'),
    ], string="Trạng thái", default='new', index=True, tracking=True)

    # UNIFIED: Chỉ dùng suggestion_note cho mọi loại ghi chú (từ AI, manual, hoặc status note)
    suggestion_note = fields.Text(string="Ghi chú & Gợi ý xử lý", help="Ghi chú trạng thái, gợi ý từ AI hoặc external system", tracking=True)
    last_suggestion_at = fields.Datetime(string="Thời điểm cập nhật ghi chú")
    
    # Trường mới: theo dõi lần cuối thay đổi trạng thái xử lý
    last_processing_change_at = fields.Datetime(string="Thời điểm thay đổi xử lý cuối", help="Thời điểm cuối cùng thay đổi require_processing (dùng để ẩn conversation đã xử lý sau 2 ngày)")
    
    status_set_by_id = fields.Many2one('res.users', "Người cập nhật", tracking=True)
    status_set_at = fields.Datetime("Thời điểm cập nhật", tracking=True)

    # UNIFIED: Chỉ dùng require_processing - tự động quản lý logic checklist
    require_processing = fields.Boolean(string="Có yêu cầu xử lý", default=False, index=True, tracking=True)

    # === PANCAKE TAG MANAGEMENT (Manager only) ===
    pancake_tag_ids = fields.Many2many(
        'page.fm.tag',
        'conversation_pancake_tag_rel',
        'conversation_id',
        'tag_id',
        string="Pancake Tags",
        domain="[('page_id', '=', page_fm_page_id)]",
        help="Tags hiện tại của conversation trên Pancake (chỉ Manager có thể chỉnh sửa)",
        groups="dac_erp.group_dac_erp_manager"
    )
    
    # COMPUTED: status_label được tính toán thay vì lưu trữ
    status_label = fields.Char(string="Nhãn trạng thái", compute='_compute_status_label', help="Text hiển thị trạng thái")

    # COMPUTED: Cleaned text fields for display
    last_message_snippet_clean = fields.Text(string="Last Message (Clean)", compute='_compute_clean_texts', help="Tin nhắn cuối đã làm sạch HTML tags")
    suggestion_note_clean = fields.Text(string="Note (Clean)", compute='_compute_clean_texts', help="Ghi chú đã làm sạch HTML tags")
    customer_name_clean = fields.Char(string="Customer Name (Clean)", compute='_compute_clean_texts', help="Tên khách hàng đã làm sạch")

    @api.depends('last_message_snippet', 'suggestion_note', 'customer_name_fm')
    def _compute_clean_texts(self):
        """Làm sạch HTML tags và format đặc biệt từ text"""
        for record in self:
            record.last_message_snippet_clean = self._clean_text(record.last_message_snippet or '')
            record.suggestion_note_clean = self._clean_text(record.suggestion_note or '')
            record.customer_name_clean = self._clean_text(record.customer_name_fm or '')

    def _clean_text(self, text):
        """Helper function để làm sạch HTML tags và format đặc biệt"""
        if not text:
            return ""
        
        # Loại bỏ HTML tags
        text = re.sub(r'<[^>]*>', ' ', text)
        
        # Loại bỏ stickers và emojis trong []
        text = re.sub(r'\[sticker\]', '[Sticker]', text, flags=re.IGNORECASE)
        text = re.sub(r'\[emoji\]', '[Emoji]', text, flags=re.IGNORECASE)
        text = re.sub(r'\[.*?\]', '', text)
        
        # Loại bỏ các ký tự HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        
        # Loại bỏ khoảng trắng thừa
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()

    @api.depends('status_state', 'require_processing')
    def _compute_status_label(self):
        """Tính toán nhãn hiển thị dựa trên trạng thái và yêu cầu xử lý"""
        default_labels = {
            'new': 'Có tin nhắn mới',
            'recontact': 'Chăm lại khách', 
            'waiting': 'Đợi khách phản hồi',
            'done': 'Đã xử lý',
        }
        for record in self:
            base_label = default_labels.get(record.status_state, record.status_state or '')
            if record.require_processing and record.status_state != 'done':
                record.status_label = f"{base_label}"
            else:
                record.status_label = base_label

    def action_toggle_require_processing(self):
        """Thay thế action_toggle_checklist_ok - Toggle trạng thái yêu cầu xử lý"""
        self.ensure_one()
        new_val = not bool(self.require_processing)
        vals = {
            'require_processing': new_val,
            'is_unread_fm': False,  # đánh dấu là đã đọc khi toggle
            'last_processing_change_at': fields.Datetime.now(),  # Cập nhật thời điểm thay đổi xử lý
        }

        # Bật/ Tắt yêu cầu xử lý
        if not new_val:
            vals['status_state'] = 'done'
        elif self.status_state == 'done':
            vals['status_state'] = 'new'
        
        # Cho phép vượt qua hạn chế của write cho nhóm sale
        self.with_context(allow_toggle_require_processing=True).sudo().write(vals)

        # Đồng bộ tags với Pancake
        self._sync_tags_to_pancake(new_val)
        
        return {
            'require_processing': self.require_processing,
            'is_unread_fm': self.is_unread_fm,
            'status_state': self.status_state,
            'status_label': self.status_label,
        }

    def _get_pancake_tag_mapping(self):
        """Lấy mapping giữa tên tag và ID từ model page.fm.tag"""
        self.ensure_one()
        
        # Lấy tags từ model page.fm.tag cho page hiện tại
        tag_mapping = {}
        page = self.page_fm_page_id
        
        if page:
            tags = self.env['page.fm.tag'].search([('page_id', '=', page.id), ('active', '=', True)])
            for tag in tags:
                # Sử dụng tên tag và tag_fm_id
                tag_name = tag.name or tag.fm_text
                if tag_name and tag.tag_fm_id:
                    try:
                        # Nếu tag_fm_id là số, convert sang int
                        tag_id = int(tag.tag_fm_id) if tag.tag_fm_id.isdigit() else tag.tag_fm_id
                        tag_mapping[tag_name] = tag_id
                    except (ValueError, AttributeError):
                        # Nếu không convert được thì giữ nguyên string
                        tag_mapping[tag_name] = tag.tag_fm_id
        
        # Fallback: Lấy từ system parameters nếu không có tags trong DB
        if not tag_mapping:
            ICP = self.env['ir.config_parameter'].sudo()
            custom_mapping = ICP.get_param('pancake.tag_mapping')
            if custom_mapping:
                try:
                    tag_mapping = json.loads(custom_mapping)
                except json.JSONDecodeError:
                    _logger.warning("Lỗi parse pancake.tag_mapping từ system parameters")
        
        # Fallback cuối cùng: hardcoded mapping
        if not tag_mapping:
            tag_mapping = {
                "Đang tư vấn": 22,
                "Done": 31,
                "Chưa thu tiền": 25,
                "Đang thiết kế": 23,
                "Fail": 29,
                "Khách lớn": 28,
                "Khách quen": 27,
                "Đang sản xuất": 24,
                "Đã mua hàng": 26
            }
        
        _logger.info(f"Tag mapping cho page {page.name}: {tag_mapping}")
        return tag_mapping

    def _get_actual_pancake_tags(self):
        """Lấy tags thực tế từ Pancake - Dựa trên cấu trúc API thực tế"""
        self.ensure_one()
        
        # Lấy access token
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            return None, "Không có access token"

        try:
            page_token = self.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_token:
                return None, f"Không thể tạo page token cho page {self.page_fm_page_id.name}"

            page_id = self.conv_page_fm_id or self.page_fm_page_id.page_fm_id_str
            conversation_id = self.conversation_fm_id
            
            #_logger.info(f"🔍 DEBUG: Conversation ID: {conversation_id}, Page ID: {page_id}")
            
            # THỰC TẾ: Pancake API không hỗ trợ GET tags của conversation cụ thể
            # API conversations chỉ dùng parameter "tags" để FILTER conversations theo tags
            # Không có endpoint riêng để lấy tags của 1 conversation
            
            # Chỉ có thể biết tags qua:
            # 1. Khi sync tags (POST thành công)
            # 2. Hoặc thông qua webhook (nếu có)
            
            #_logger.info("🔍 DEBUG: Pancake API không hỗ trợ GET tags của conversation cụ thể")
            #_logger.info("🔍 DEBUG: Endpoint conversations chỉ dùng tags parameter để filter, không trả về tags")
            
            # Trả về thông tin dựa trên sync gần nhất
            return None, "API không hỗ trợ GET tags của conversation cụ thể"

        except Exception as e:
            _logger.error(f"🔍 DEBUG: Unexpected error: {e}", exc_info=True)
            return None, f"Lỗi kết nối: {str(e)}"

    def _get_tag_by_code(self, code):
        """Lấy tag từ page.fm.tag dựa trên odoo_tag_code"""
        self.ensure_one()
        page = self.page_fm_page_id
        if not page:
            return None
        
        tag = self.env['page.fm.tag'].search([
            ('page_id', '=', page.id),
            ('odoo_tag_code', '=', code),
            ('active', '=', True)
        ], limit=1)
        
        return tag

    def _serialize_ai_tag_snapshot(self, tags=None):
        tags = tags if tags is not None else self.pancake_tag_ids
        rows = []
        for tag in tags:
            rows.append({
                'id': tag.id,
                'code': tag.odoo_tag_code,
                'name': tag.name,
                'tag_fm_id': tag.tag_fm_id,
            })
        rows.sort(key=lambda row: ((row.get('code') or ''), row.get('id') or 0))
        return rows

    def _build_ai_tag_sync_http_context(self):
        self.ensure_one()
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError(_("Missing page_fm.access_token system parameter."))

        page_token = self.page_fm_page_id._generate_page_specific_access_token(main_access_token)
        if not page_token:
            raise UserError(_("Không thể tạo page token cho page %s") % (self.page_fm_page_id.name or self.page_fm_page_id.id))

        page_id = self.conv_page_fm_id or self.page_fm_page_id.page_fm_id_str
        if not page_id or not self.conversation_fm_id:
            raise UserError(_("Conversation thiếu page ID hoặc conversation FM ID để sync tags."))

        return {
            'api_url': f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_id}/conversations/{self.conversation_fm_id}/tags",
            'headers': {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            'params': {
                'page_access_token': page_token,
            },
        }

    def _sync_single_pancake_tag_action(self, http_context, tag, action):
        self.ensure_one()
        if action not in ('add', 'remove'):
            raise ValueError("action must be add or remove")
        if not tag.tag_fm_id:
            raise UserError(_("Tag %s has no Pancake tag ID.") % (tag.name or tag.id))

        try:
            tag_id = int(tag.tag_fm_id) if tag.tag_fm_id.isdigit() else tag.tag_fm_id
        except Exception:
            tag_id = tag.tag_fm_id

        response = requests.post(
            http_context['api_url'],
            json={
                'tag_id': tag_id,
                'action': action,
            },
            headers=http_context['headers'],
            params=http_context['params'],
            timeout=10,
        )
        ok = response.status_code in (200, 201)
        return {
            'action': action,
            'tag_code': tag.odoo_tag_code,
            'tag_name': tag.name,
            'tag_fm_id': tag.tag_fm_id,
            'ok': ok,
            'status_code': response.status_code,
            'response_text': (response.text or '')[:300],
        }

    def _ai_replace_tags_by_codes(
        self, tag_codes, mode='replace_ai_scope', dry_run=False,
        request_context=None, evidence=None, needs_review=False, do_not_apply_reason=None,
    ):
        """Update Pancake tags via AI with safety modes.

        mode:
          replace_ai_scope (default) — only replace tags where managed_by_ai=True; keep manual tags.
          add     — add the specified tags without removing anything.
          remove  — remove the specified tags without adding anything.
          replace_all — full replace (use with care).
        dry_run=True — compute what would change, no writes/API calls.
        needs_review / do_not_apply_reason — skip applying, log intent only.
        """
        self.ensure_one()
        request_context = request_context or {}

        VALID_MODES = ('replace_ai_scope', 'add', 'remove', 'replace_all')
        if mode not in VALID_MODES:
            raise ValueError("mode must be one of %s" % ', '.join(VALID_MODES))

        if not isinstance(tag_codes, list):
            raise ValueError("tag_codes must be a list")

        cleaned_codes = []
        seen_codes = set()
        for raw_code in tag_codes:
            if not isinstance(raw_code, str):
                raise ValueError("tag_codes must contain only strings")
            code = raw_code.strip()
            if not code:
                raise ValueError("tag_codes cannot contain empty values")
            if code in seen_codes:
                raise ValueError("tag_codes cannot contain duplicates")
            seen_codes.add(code)
            cleaned_codes.append(code)

        page = self.page_fm_page_id
        if not page:
            raise UserError(_("Conversation chua lien ket voi page."))

        Tag = self.env['page.fm.tag'].sudo()
        requested_tags = Tag.search([
            ('page_id', '=', page.id),
            ('active', '=', True),
            ('odoo_tag_code', 'in', cleaned_codes),
        ])
        found_codes = {t.odoo_tag_code for t in requested_tags}
        unknown_codes = [c for c in cleaned_codes if c not in found_codes]
        if unknown_codes:
            raise ValueError("Unknown or inactive tag_codes for page %s: %s" % (page.id, ', '.join(unknown_codes)))

        current_tags = self.pancake_tag_ids

        # If AI signals it cannot apply (missing evidence, needs human review)
        if needs_review or do_not_apply_reason:
            return {
                'mode': mode, 'dry_run': dry_run, 'applied': False,
                'not_applied_reason': do_not_apply_reason or 'needs_review',
                'requested_tag_codes': cleaned_codes,
                'applied_tag_codes': [],
                'would_add': [], 'would_remove': [],
                'added_tag_codes': [], 'removed_tag_codes': [],
                'kept_manual_tag_codes': [t.odoo_tag_code for t in current_tags if t.odoo_tag_code and not t.managed_by_ai],
                'not_ai_managed_codes': [],
                'tag_sync_results': [],
                'request_context': request_context,
                'tags': self._serialize_ai_tag_snapshot(),
            }

        current_tag_id_set = set(current_tags.ids)

        if mode == 'replace_ai_scope':
            ai_managed_target = requested_tags.filtered(lambda t: t.managed_by_ai)
            not_ai_managed_codes = [t.odoo_tag_code for t in requested_tags if not t.managed_by_ai]
            ai_target_codes = {t.odoo_tag_code for t in ai_managed_target}
            current_ai = current_tags.filtered(lambda t: t.managed_by_ai)
            current_ai_codes = {t.odoo_tag_code for t in current_ai if t.odoo_tag_code}
            current_manual = current_tags.filtered(lambda t: not t.managed_by_ai)
            kept_manual_codes = [t.odoo_tag_code for t in current_manual if t.odoo_tag_code]
            to_remove = current_ai.filtered(lambda t: t.odoo_tag_code not in ai_target_codes)
            to_add = ai_managed_target.filtered(lambda t: t.odoo_tag_code not in current_ai_codes)
            final_tags = current_manual | ai_managed_target

        elif mode == 'add':
            not_ai_managed_codes = []
            kept_manual_codes = []
            to_remove = Tag.browse()
            to_add = requested_tags.filtered(lambda t: t.id not in current_tag_id_set)
            final_tags = current_tags | requested_tags

        elif mode == 'remove':
            not_ai_managed_codes = []
            kept_manual_codes = []
            to_remove = requested_tags.filtered(lambda t: t.id in current_tag_id_set)
            to_add = Tag.browse()
            final_tags = current_tags - to_remove

        else:  # replace_all
            not_ai_managed_codes = []
            kept_manual_codes = []
            requested_ids = set(requested_tags.ids)
            to_remove = current_tags.filtered(lambda t: t.id not in requested_ids)
            to_add = requested_tags.filtered(lambda t: t.id not in current_tag_id_set)
            final_tags = requested_tags

        would_add = [t.odoo_tag_code for t in to_add if t.odoo_tag_code]
        would_remove = [t.odoo_tag_code for t in to_remove if t.odoo_tag_code]

        if dry_run:
            return {
                'mode': mode, 'dry_run': True, 'applied': False,
                'requested_tag_codes': cleaned_codes,
                'applied_tag_codes': [],
                'would_add': would_add, 'would_remove': would_remove,
                'added_tag_codes': [], 'removed_tag_codes': [],
                'kept_manual_tag_codes': kept_manual_codes,
                'not_ai_managed_codes': not_ai_managed_codes if mode == 'replace_ai_scope' else [],
                'tag_sync_results': [],
                'request_context': request_context,
                'tags': self._serialize_ai_tag_snapshot(),
            }

        # Build Pancake API context
        sync_results = []
        try:
            http_context = self._build_ai_tag_sync_http_context()
        except Exception as exc:
            raise PancakeTagSyncError("Cannot build Pancake sync context: %s" % exc, sync_results=[]) from exc

        def _sync_or_skip(tag, action):
            """Sync to Pancake; skip local:: tags gracefully."""
            if tag.tag_fm_id and tag.tag_fm_id.startswith('local::'):
                return {
                    'action': action, 'tag_code': tag.odoo_tag_code, 'tag_name': tag.name,
                    'tag_fm_id': tag.tag_fm_id, 'ok': True, 'skipped': True,
                    'skip_reason': 'local_tag_not_on_pancake',
                }
            return self._sync_single_pancake_tag_action(http_context, tag, action)

        try:
            for tag in to_remove:
                sync_results.append(_sync_or_skip(tag, 'remove'))
            for tag in to_add:
                sync_results.append(_sync_or_skip(tag, 'add'))
        except requests.exceptions.Timeout as exc:
            raise PancakeTagSyncError("Timeout while syncing tags to Pancake", sync_results=sync_results) from exc
        except requests.exceptions.RequestException as exc:
            raise PancakeTagSyncError("Request error while syncing tags to Pancake: %s" % exc, sync_results=sync_results) from exc

        failed_results = [r for r in sync_results if not r.get('ok') and not r.get('skipped')]
        if failed_results:
            failure_labels = ', '.join(
                "%s:%s" % (r.get('tag_code') or r.get('tag_name') or r.get('tag_fm_id'), r.get('status_code'))
                for r in failed_results
            )
            raise PancakeTagSyncError("Pancake tag sync failed for %s" % failure_labels, sync_results=sync_results)

        self.with_context(skip_auto_bump_require_processing=True).sudo().write({
            'pancake_tag_ids': [(6, 0, final_tags.ids)],
        })

        added_codes = [t.odoo_tag_code for t in to_add if t.odoo_tag_code]
        removed_codes = [t.odoo_tag_code for t in to_remove if t.odoo_tag_code]
        applied_codes = sorted({t.odoo_tag_code for t in final_tags if t.odoo_tag_code})

        return {
            'mode': mode, 'dry_run': False, 'applied': True,
            'requested_tag_codes': cleaned_codes,
            'applied_tag_codes': applied_codes,
            'would_add': would_add, 'would_remove': would_remove,
            'added_tag_codes': added_codes,
            'removed_tag_codes': removed_codes,
            'kept_manual_tag_codes': kept_manual_codes if mode == 'replace_ai_scope' else [],
            'not_ai_managed_codes': not_ai_managed_codes if mode == 'replace_ai_scope' else [],
            'tag_sync_results': sync_results,
            'request_context': request_context,
            'tags': self._serialize_ai_tag_snapshot(tags=final_tags),
        }

    def _sync_tags_to_pancake(self, require_processing):
        """Đồng bộ tags với Pancake dựa trên trạng thái require_processing (AUTO SYNC)
        
        QUAN TRỌNG: Đây là sync TỰ ĐỘNG, chỉ sync 2 tags chính:
        - require_processing = True  -> "Đang tư vấn" 
        - require_processing = False -> "Done"
        
        Manual tags (pancake_tag_ids) KHÔNG bị ảnh hưởng bởi method này.
        """
        self.ensure_one()
        
        #_logger.info(f"🔄 AUTO SYNC: require_processing={require_processing} cho conversation {self.conversation_fm_id}")
        
        # Lấy access token
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.warning("Không có main_access_token để sync tags với Pancake")
            return False

        try:
            # Tạo page-specific token
            page_token = self.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_token:
                _logger.warning(f"Không thể tạo page token cho page {self.page_fm_page_id.name}")
                return False

            # Lấy tag mapping
            tag_mapping = self._get_pancake_tag_mapping()
            
            # require_processing=True  -> set needs_action, remove done
            # require_processing=False -> set done, remove needs_action
            if require_processing:
                tag = self._get_tag_by_code('needs_action')
                remove_tag = self._get_tag_by_code('done')
                tag_name = tag.name if tag else 'needs_action'
                remove_tag_name = remove_tag.name if remove_tag else 'done'
            else:
                tag = self._get_tag_by_code('done')
                remove_tag = self._get_tag_by_code('needs_action')
                tag_name = tag.name if tag else 'done'
                remove_tag_name = remove_tag.name if remove_tag else 'needs_action'

            # Lấy tag ID từ tag object hoặc mapping
            if tag and tag.tag_fm_id:
                try:
                    tag_id = int(tag.tag_fm_id) if tag.tag_fm_id.isdigit() else tag.tag_fm_id
                except (ValueError, AttributeError):
                    tag_id = tag.tag_fm_id
            else:
                tag_id = tag_mapping.get(tag_name)

            if remove_tag and remove_tag.tag_fm_id:
                try:
                    remove_tag_id = int(remove_tag.tag_fm_id) if remove_tag.tag_fm_id.isdigit() else remove_tag.tag_fm_id
                except (ValueError, AttributeError):
                    remove_tag_id = remove_tag.tag_fm_id
            else:
                remove_tag_id = tag_mapping.get(remove_tag_name)

            if not tag_id:
                _logger.warning(f"AUTO SYNC: Không tìm thấy tag ID cho '{tag_name}' (require_processing={require_processing})")
                return False

            # API endpoint - sử dụng conv_page_fm_id nếu có, fallback về page_fm_id_str
            page_id = self.conv_page_fm_id or self.page_fm_page_id.page_fm_id_str
            conversation_id = self.conversation_fm_id
            api_url = f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_id}/conversations/{conversation_id}/tags"

            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Thêm page_access_token vào params hoặc headers tùy theo API format
            params = {'page_access_token': page_token}

            # Gỡ tag cũ trước (nếu có)
            if remove_tag_id:
                remove_data = {
                    "tag_id": remove_tag_id,
                    "action": "remove"
                }
                
                try:
                    remove_response = requests.post(
                        api_url,
                        json=remove_data,
                        headers=headers,
                        params=params,
                        timeout=10
                    )
                    # if remove_response.status_code in (200, 201):
                    #     _logger.info(f"✓ AUTO SYNC: Đã gỡ tag '{remove_tag_name}' (ID: {remove_tag_id}) cho conversation {conversation_id}")
                    # else:
                    #     _logger.warning(f"AUTO SYNC: Không thể gỡ tag cũ: {remove_response.status_code} - {remove_response.text}")
                except Exception as e:
                    _logger.warning(f"AUTO SYNC: Lỗi khi gỡ tag cũ: {e}")

            # Thêm tag mới
            add_data = {
                "tag_id": tag_id,
                "action": "add"
            }
            
            response = requests.post(
                api_url,
                json=add_data,
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code in (200, 201):
                _logger.info(f"✓ AUTO SYNC: Đã sync tag '{tag_name}' (ID: {tag_id}) cho conversation {conversation_id} lên Pancake")
                return True
            else:
                _logger.warning(f"AUTO SYNC: API Pancake trả về lỗi {response.status_code}: {response.text}")
                return False

        except requests.exceptions.Timeout:
            _logger.warning(f"AUTO SYNC: Timeout khi sync tags cho conversation {self.conversation_fm_id}")
            return False
        except requests.exceptions.RequestException as e:
            _logger.warning(f"AUTO SYNC: Lỗi request khi sync tags: {e}")
            return False
        except Exception as e:
            _logger.error(f"AUTO SYNC: Lỗi không mong đợi khi sync tags: {e}", exc_info=True)
            return False

    def action_sync_pancake_tags_manual(self):
        """Sync tags được chọn trong field pancake_tag_ids lên Pancake (chỉ Manager)"""
        self.ensure_one()
        
        if not self.env.user.has_group('dac_erp.group_dac_erp_manager'):
            raise AccessError(_("Chỉ Manager mới có thể sync tags với Pancake!"))
        
        # Phân tích trạng thái và manual tags
        current_state = self.require_processing
        expected_auto_tag = "Đang tư vấn" if current_state else "Done"
        manual_tags = [tag.name for tag in self.pancake_tag_ids] if self.pancake_tag_ids else []
        
        warnings = []
        
        # Thông báo về giới hạn API
        warnings.append("ℹ️ Lưu ý: API không hỗ trợ GET tags, không thể kiểm tra trạng thái hiện tại")
        
        # Warning: Manual tags conflict với auto logic
        if manual_tags:
            if current_state and "Done" in manual_tags and "Đang tư vấn" not in manual_tags:
                warnings.append("⚠️ Bạn đang set 'Done' nhưng trạng thái local là 'Cần xử lý'")
            elif not current_state and "Đang tư vấn" in manual_tags and "Done" not in manual_tags:
                warnings.append("⚠️ Bạn đang set 'Đang tư vấn' nhưng trạng thái local là 'Đã xử lý'")
        
        # Warning: Sẽ override auto sync
        if manual_tags and expected_auto_tag not in manual_tags:
            warnings.append(f"⚠️ Manual sync sẽ override auto logic (dự kiến: {expected_auto_tag})")
        
        # Lấy access token
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi Sync Tags',
                    'message': 'Không có access token để sync với Pancake',
                    'type': 'danger'
                }
            }

        try:
            page_token = self.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_token:
                raise Exception(f"Không thể tạo page token cho page {self.page_fm_page_id.name}")

            # API endpoint
            page_id = self.conv_page_fm_id or self.page_fm_page_id.page_fm_id_str
            conversation_id = self.conversation_fm_id
            api_url = f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_id}/conversations/{conversation_id}/tags"

            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            params = {'page_access_token': page_token}

            success_count = 0
            error_count = 0
            actions_performed = []

            # Lấy tag mapping để thao tác
            tag_mapping = self._get_pancake_tag_mapping()

            # Thực hiện sync
            if not self.pancake_tag_ids:
                # Gỡ tất cả tags hiện có
                actions_performed.append("🧹 Xóa tất cả tags")
                for tag_name, tag_id in tag_mapping.items():
                    try:
                        data = {
                            "tag_id": tag_id,
                            "action": "remove"
                        }
                        
                        response = requests.post(
                            api_url,
                            json=data,
                            headers=headers,
                            params=params,
                            timeout=10
                        )
                        
                        if response.status_code in (200, 201):
                            success_count += 1
                            _logger.info(f"✓ Đã gỡ tag '{tag_name}' (ID: {tag_id}) cho conversation {conversation_id}")
                        else:
                            error_count += 1
                            _logger.warning(f"Lỗi gỡ tag '{tag_name}': {response.status_code} - {response.text}")
                            
                    except Exception as e:
                        error_count += 1
                        _logger.error(f"Lỗi gỡ tag '{tag_name}': {e}")
            else:
                # Sync từng tag được chọn
                for tag in self.pancake_tag_ids:
                    if not tag.tag_fm_id:
                        continue
                        
                    try:
                        tag_id = int(tag.tag_fm_id) if tag.tag_fm_id.isdigit() else tag.tag_fm_id
                        
                        data = {
                            "tag_id": tag_id,
                            "action": "add"
                        }
                        
                        response = requests.post(
                            api_url,
                            json=data,
                            headers=headers,
                            params=params,
                            timeout=10
                        )
                        
                        if response.status_code in (200, 201):
                            success_count += 1
                            actions_performed.append(f"✓ Thêm tag '{tag.name}'")
                            #_logger.info(f"✓ Đã sync tag '{tag.name}' (ID: {tag_id}) cho conversation {conversation_id}")
                        else:
                            error_count += 1
                            actions_performed.append(f"✗ Lỗi tag '{tag.name}'")
                            #_logger.warning(f"Lỗi sync tag '{tag.name}': {response.status_code} - {response.text}")
                            
                    except Exception as e:
                        error_count += 1
                        actions_performed.append(f"✗ Lỗi tag '{tag.name}'")
                        #_logger.error(f"Lỗi sync tag '{tag.name}': {e}")

            # Tạo thông báo kết quả
            if success_count > 0:
                target_tags_str = ", ".join(manual_tags) if manual_tags else "Không có tags"
                
                message_parts = []
                message_parts.append("✅ **MANUAL SYNC THÀNH CÔNG**")
                message_parts.append(f"🎯 **Target**: {target_tags_str}")
                message_parts.append(f"📊 **Kết quả**: {success_count} thành công")
                
                if error_count > 0:
                    message_parts.append(f", {error_count} lỗi")
                
                if warnings:
                    message_parts.append("\n🚨 **CẢNH BÁO**:")
                    message_parts.extend(warnings)
                
                if actions_performed:
                    message_parts.append(f"\n📝 **Chi tiết**:")
                    message_parts.extend(actions_performed[:5])  # Hiển thị tối đa 5 actions
                
                message = "\n".join(message_parts)
                notification_type = 'warning' if warnings else 'success'
                    
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Manual Sync Tags',
                        'message': message,
                        'type': notification_type
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Sync Tags Thất Bại',
                        'message': f'❌ Sync thất bại - {error_count} lỗi\n\n📝 Chi tiết:\n' + "\n".join(actions_performed[:5]),
                        'type': 'danger'
                    }
                }
                
        except Exception as e:
            _logger.error(f"Lỗi sync pancake tags: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi Sync Tags',
                    'message': f"❌ Lỗi không mong đợi: {str(e)}",
                    'type': 'danger'
                }
            }

    # DEPRECATED: Giữ lại cho backward compatibility
    def action_toggle_checklist_ok(self):
        """DEPRECATED: Chuyển đổi sang dùng action_toggle_require_processing"""
        return self.action_toggle_require_processing()

    def action_update_status(self, state, require_processing=False, note=None):
        """Cập nhật trạng thái conversation"""
        self.ensure_one()
        vals = {
            'status_state': state,
            'require_processing': bool(require_processing),
            'status_set_by_id': self.env.user.id,
            'status_set_at': fields.Datetime.now(),
        }
        if note:
            vals.update({
                'suggestion_note': note,
                'last_suggestion_at': fields.Datetime.now(),
            })
        self.sudo().write(vals)
        return True

    def _auto_detect_require_processing_from_tags(self):
        """🆕 Tự động phát hiện require_processing từ Pancake tags
        
        Logic:
        - Tags 'Đang tư vấn', 'Chưa thu tiền', 'Đang thiết kế', 'Đang sản xuất' → require_processing = True
        - Tags 'Done', 'Fail' → require_processing = False
        - Không có tags liên quan → giữ nguyên
        """
        ICP = self.env['ir.config_parameter'].sudo()
        
        processing_tags_param = ICP.get_param('pancake.processing_tags')
        if processing_tags_param:
            processing_tags = [t.strip() for t in processing_tags_param.split(',') if t.strip()]
        else:
            processing_tags = ['Đang tư vấn', 'Chưa thu tiền', 'Đang thiết kế', 'Đang sản xuất']

        done_tags_param = ICP.get_param('pancake.done_tags')
        if done_tags_param:
            done_tags = [t.strip() for t in done_tags_param.split(',') if t.strip()]
        else:
            done_tags = ['Done', 'Fail']

        # Also check by odoo_tag_code for new standard tags
        processing_codes = ['needs_action', 'waiting_customer_reply', 'recontact_needed',
                            'payment_due_after_production']
        done_codes = ['done', 'lost_or_cold']

        for rec in self:
            if not rec.pancake_tag_ids:
                continue  # Không có tags → skip

            tag_names = [tag.name for tag in rec.pancake_tag_ids]
            tag_codes = [tag.odoo_tag_code for tag in rec.pancake_tag_ids if tag.odoo_tag_code]

            has_processing_tag = (
                any(tag in tag_names for tag in processing_tags)
                or any(code in tag_codes for code in processing_codes)
            )
            has_done_tag = (
                any(tag in tag_names for tag in done_tags)
                or any(code in tag_codes for code in done_codes)
            )

            new_value = None
            if has_processing_tag and not has_done_tag:
                new_value = True
            elif has_done_tag and not has_processing_tag:
                new_value = False

            # Chỉ update khi có thay đổi
            if new_value is not None and rec.require_processing != new_value:
                rec.sudo().write({
                    'require_processing': new_value,
                    'last_processing_change_at': fields.Datetime.now()
                })
                _logger.info("Auto-detect require_processing=%s conv %s codes=%s",
                             new_value, rec.id, tag_codes)
    
    def _auto_bump_require_processing(self):
        """Bật require_processing khi có trạng thái đỏ hoặc chưa đọc."""
        for rec in self:
            # trạng thái đỏ HOẶC chưa đọc
            should_process = (
                rec.status_state in ('new', 'recontact') or 
                bool(getattr(rec, 'is_unread_fm', False))
            )
            
            # Cập nhật require_processing
            if should_process != rec.require_processing:
                rec.require_processing = should_process
                #_logger.info(f"Auto {'bật' if should_process else 'tắt'} require_processing cho conversation {rec.id} - Trạng thái: {rec.status_state}, unread: {bool(getattr(rec, 'is_unread_fm', False))}")
    
    def sync_tags_to_partner(self):
        """🆕 Đồng bộ tags từ conversation sang partner"""
        for record in self:
            if record.partner_id and record.pancake_tag_ids:
                try:
                    record.partner_id.sudo().write({
                        'pancake_tag_ids': [(6, 0, record.pancake_tag_ids.ids)]
                    })
                    #_logger.info(f"✅ Synced {len(record.pancake_tag_ids)} tags to partner {record.partner_id.name}")
                except Exception as e:
                    _logger.error(f"Lỗi sync tags to partner: {e}", exc_info=True)

    # (tuỳ chọn) auto gợi ý trạng thái dựa vào unread/last message
    def apply_status_rule(self):
        """Áp dụng quy tắc trạng thái tự động dựa vào tin nhắn
        + Đồng thời refresh last_message_snippet & last_message_id theo tin mới nhất.
        """
        Message = self.env['page.fm.message'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        bot_names_param = ICP.get_param('pancake.bot_names')
        if bot_names_param:
            bot_names = [name.strip().lower() for name in bot_names_param.split(',') if name.strip()]
        else:
            bot_names = ['chatbot', 'pancake bot', 'auto']

        for c in self:
            # Lấy tin nhắn cuối (ưu tiên inserted_at_fm)
            msg_order = 'inserted_at_fm desc, id desc' if 'inserted_at_fm' in Message._fields else 'id desc'
            last_msg = Message.search([('conversation_id', '=', c.id)], limit=1, order=msg_order)

            vals = {}

            # 1) Logic trạng thái
            is_bot = False
            if last_msg and last_msg.staff_name_fm:
                is_bot = last_msg.staff_name_fm.strip().lower() in bot_names

            if getattr(c, 'is_unread_fm', False):
                # Có tin chưa đọc -> 'Tin mới', cần xử lý
                vals.update({'status_state': 'new', 'require_processing': True})
            elif last_msg and (last_msg.sender_name_fm and (not last_msg.staff_name_fm or is_bot)):
                # Tin cuối là của KH (hoặc chatbot trả lời) -> 'Chăm lại khách', cần xử lý
                vals.update({'status_state': 'recontact', 'require_processing': True})
            elif last_msg and last_msg.staff_name_fm and not is_bot:
                # Tin cuối là của NV -> 'Đợi khách phản hồi', không cần xử lý ngay
                vals.update({'status_state': 'waiting', 'require_processing': False})
            else:
                # Không có tin/khác -> 'Đã xử lý'
                vals.update({'status_state': 'done', 'require_processing': False})

            # 2) Làm mới snippet: Ưu tiên tin NHẮN CỦA KHÁCH HÀNG
            if last_msg:
                # Tìm tin khách hàng mới nhất của cuộc hội thoại
                # tiêu chí: không gán staff (staff = False) và không có staff_name_fm
                cust_domain = [
                    ('conversation_id', '=', c.id),
                    ('staff', '=', False),
                    '|', ('staff_name_fm', '=', False), ('staff_name_fm', '=', ''),  # bắt cả None lẫn chuỗi rỗng
                ]
                last_cust_msg = Message.search(cust_domain, limit=1, order=msg_order)

                # Helper dựng snippet ngắn gọn
                def _make_snippet(m):
                    if not m:
                        return False
                    txt = (m.content_html or '').strip()
                    if txt:
                        return txt
                    if m.type_content and m.type_content != 'text':
                        label_map = {'image': 'Ảnh', 'video': 'Video', 'file': 'Tệp', 'audio': 'Audio'}
                        label = label_map.get(m.type_content, m.type_content)
                        suf = (m.url_content or '').strip()
                        return f"[{label}]" + (f" {suf}" if suf else "")
                    return False

                # Ưu tiên snippet từ tin khách; nếu không có thì rơi về tin cuối bất kỳ
                snippet = _make_snippet(last_cust_msg) or _make_snippet(last_msg)

                vals.update({
                    'last_message_snippet': snippet or False,
                    # Giữ nguyên last_message_id theo tin cuối bất kỳ để phục vụ logic sync dừng đúng chỗ
                    'last_message_id': last_msg.message_fm_id or c.last_message_id,
                    # Không đụng vào last_message_sync_fm ở đây
                })

            # Ghi & auto-bump lại theo rule phụ
            if vals:
                c.sudo().write(vals)
                c._auto_bump_require_processing()


    @api.depends('customer_name_fm', 'conversation_fm_id')
    def _compute_name(self):
        for record in self:
            if record.customer_name_fm and record.customer_name_fm not in ['Khách ẩn danh', '']:
                record.name = record.customer_name_fm
            elif record.conversation_fm_id:
                record.name = f"Conv: {record.conversation_fm_id}"
            else:
                record.name = _("N/A")

    @api.depends('conv_message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.conv_message_ids)

    def _find_or_create_partner(self):
        """Tìm hoặc tạo res.partner tương ứng với hội thoại này.

        Thứ tự ưu tiên:
        1. Alias table (page.fm.customer) theo customer_fm_id — chính xác nhất
        2. res.partner.pancake_id — backward compat, migrate sang alias
        3. phone_normalized — auto-link khách vãng lai tạo thủ công trong Odoo
        4. Tạo mới nếu không tìm thấy
        """
        self.ensure_one()
        if self.partner_id:
            return

        from odoo.addons.dac_erp.models.phone_utils import normalize_phone_vn
        Partner = self.env['res.partner'].sudo()
        PancakeCustomer = self.env['page.fm.customer'].sudo()

        partner = Partner.browse()
        phone_norm = normalize_phone_vn(self.phone)

        # 1) Tìm qua alias table
        alias = PancakeCustomer.search([('pancake_customer_id', '=', self.customer_fm_id)], limit=1)
        if alias:
            partner = alias.partner_id
            _logger.debug('Conv %s: found partner %s via alias table', self.conversation_fm_id, partner.name)

        # 2) Tìm theo pancake_id trực tiếp (backward compat) → migrate sang alias
        if not partner and self.customer_fm_id:
            partner = Partner.search([('pancake_id', '=', self.customer_fm_id)], limit=1)
            if partner:
                _logger.debug('Conv %s: found partner %s via pancake_id, migrating to alias', self.conversation_fm_id, partner.name)
                PancakeCustomer.link_or_create_alias(self.customer_fm_id, partner, page=self.page_fm_page_id)

        # 3) Auto-link qua phone chuẩn hoá (khách vãng lai)
        if not partner and phone_norm:
            partner = Partner.search([('phone_normalized', '=', phone_norm)], limit=1)
            if partner:
                _logger.info(
                    'Conv %s: auto-linked walk-in partner %s via phone_normalized=%s',
                    self.conversation_fm_id, partner.name, phone_norm,
                )
                PancakeCustomer.link_or_create_alias(self.customer_fm_id, partner, page=self.page_fm_page_id)
                if not partner.pancake_id and self.customer_fm_id:
                    partner.write({'pancake_id': self.customer_fm_id})

        # 4) Tạo mới
        if not partner:
            partner = Partner.create({
                'name': self.customer_name_fm or f"Khách hàng {self.conversation_fm_id}",
                'pancake_id': self.customer_fm_id,
                'company_type': 'person',
                'company_id': False,
            })
            _logger.info('Conv %s: created new partner %s (pancake_id=%s)', self.conversation_fm_id, partner.name, self.customer_fm_id)
            PancakeCustomer.link_or_create_alias(self.customer_fm_id, partner, page=self.page_fm_page_id)

        self.partner_id = partner

        # Tải avatar nếu partner chưa có ảnh
        if not partner.image_1920 and self.customer_avatar_url:
            self._sync_avatar_to_partner(partner)

    def _sync_avatar_to_partner(self, partner):
        """Tải ảnh đại diện từ customer_avatar_url và gán vào partner.image_1920.

        Chỉ tải nếu partner chưa có ảnh. Không raise — lỗi chỉ được log.
        """
        import base64
        import requests as req

        url = self.customer_avatar_url
        if not url or not partner:
            return
        try:
            resp = req.get(url, timeout=(5, 15), allow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type', '')
            if not content_type.startswith('image/'):
                _logger.warning('Conv %s: avatar URL returned non-image content-type %s', self.conversation_fm_id, content_type)
                return
            image_b64 = base64.b64encode(resp.content)
            partner.sudo().write({'image_1920': image_b64})
            _logger.info('Conv %s: synced avatar to partner %s (%d bytes)', self.conversation_fm_id, partner.name, len(resp.content))
        except Exception as e:
            _logger.warning('Conv %s: failed to download avatar from %s: %s', self.conversation_fm_id, url[:60], e)

    def _download_avatar_binary(self, force=False):
        """Tải ảnh đại diện từ customer_avatar_url về field Binary customer_avatar.

        Dùng để hiển thị avatar offline (không phụ thuộc CDN Pancake hết hạn).
        Bỏ qua record đã có ảnh trừ khi force=True. Không raise — lỗi chỉ log.
        """
        import base64
        import requests as req

        for rec in self:
            if not rec.customer_avatar_url:
                continue
            if rec.customer_avatar and not force:
                continue
            try:
                resp = req.get(rec.customer_avatar_url, timeout=(4, 8), allow_redirects=True)
                resp.raise_for_status()
                content_type = resp.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    _logger.warning('Conv %s: avatar URL trả về content-type không phải ảnh: %s', rec.conversation_fm_id, content_type)
                    continue
                rec.customer_avatar = base64.b64encode(resp.content)
            except Exception as e:
                _logger.warning('Conv %s: tải avatar binary lỗi từ %s: %s', rec.conversation_fm_id, (rec.customer_avatar_url or '')[:60], e)

    @api.model
    def action_sync_all_avatars(self, force=False):
        """Backfill: tải avatar cho tất cả partner chưa có ảnh nhưng conversation có avatar_url.

        Dùng làm wizard action hoặc gọi từ shell.
        force=True → tải lại kể cả partner đã có ảnh.
        """
        domain = [('customer_avatar_url', '!=', False), ('partner_id', '!=', False)]
        if not force:
            domain += [('partner_id.image_1920', '=', False)]

        convs = self.sudo().search(domain)
        # Gom theo partner để tránh tải cùng ảnh nhiều lần (nhiều conv cùng partner)
        seen_partners = set()
        synced = 0
        failed = 0
        for conv in convs:
            if conv.partner_id.id in seen_partners:
                continue
            seen_partners.add(conv.partner_id.id)
            try:
                conv._sync_avatar_to_partner(conv.partner_id)
                synced += 1
            except Exception as e:
                failed += 1
                _logger.warning('Backfill avatar failed for partner %s: %s', conv.partner_id.name, e)

        _logger.info('Avatar backfill done: %d synced, %d failed', synced, failed)
        return {'synced': synced, 'failed': failed}

    def _fetch_message_batch(
        self,
        page_specific_access_token,
        current_offset=0,
        retry_count=0,
        window_start=None,
        stop_at_message_id=None,
    ):
        """Fetch message batch với retry logic và timeout handling"""
        import time
        
        self.ensure_one()
        page_fm_id = self.page_fm_page_id.page_fm_id_str
        conv_fm_id = self.conversation_fm_id
        customer_api_id = self.customer_fm_id

        if not all([page_fm_id, conv_fm_id, customer_api_id, page_specific_access_token]):
            _logger.error(f"Thiếu thông tin để lấy tin nhắn cho hội thoại {conv_fm_id}.")
            return (False, [])

        messages_api_url = f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_fm_id}/conversations/{conv_fm_id}/messages"
        params = {
            'page_access_token': page_specific_access_token,
            'customer_id': customer_api_id,
            'conversation_id': conv_fm_id,
            'page_id': page_fm_id,
            'current_count': current_offset
        }

        max_retries = 3
        timeout_seconds = 25  # Tăng timeout lên 25 giây
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Exponential backoff: 2, 4, 8 giây
                    delay = 2 ** attempt
                    _logger.info(f"Retry attempt {attempt} after {delay}s delay for conversation {conv_fm_id}")
                    time.sleep(delay)

                response = requests.get(
                    messages_api_url,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    params=params,
                    timeout=timeout_seconds
                )
                msg = ""
                try:
                    peek = response.json()
                    msg = (peek.get("message") or "").lower()
                except Exception:
                    pass

                if response.status_code in (401, 403) or \
                "access_token renewed" in msg or "expired" in msg or "invalid access_token" in msg:
                    self.page_fm_page_id.clear_token_cache()
                    new_page_token = self.page_fm_page_id._generate_page_specific_access_token(
                        self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
                    )
                    params['page_access_token'] = new_page_token

                    response = requests.get(
                        messages_api_url,
                        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                        params=params,
                        timeout=timeout_seconds
                    )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and data.get('success') is False:
                    raise RuntimeError(
                        data.get('message') or f"Pancake messages API returned unsuccessful response for conversation {conv_fm_id}."
                    )
                
                should_continue = True
                all_msgs = data.get('messages', [])
                all_msgs = sorted(
                    all_msgs,
                    key=lambda msg: (
                        self._to_aware_utc(msg.get('inserted_at')) or pytz.UTC.localize(datetime(1970, 1, 1)),
                        str(msg.get('id') or ''),
                    ),
                )
                filtered_msgs = []

                frontier_message_id = stop_at_message_id if stop_at_message_id is not None else self.last_message_id

                # Pancake trả page mới nhất trước, nhưng các tin trong từng page lại đi theo chiều cũ -> mới.
                # Vì vậy phải duyệt ngược trong batch để phát hiện đúng frontier / window_start.
                if (frontier_message_id or window_start) and not self.env.context.get('load_all', False):
                    selected_desc = []
                    for msg in reversed(all_msgs):
                        message_dt = self._to_aware_utc(msg.get('inserted_at'))
                        if frontier_message_id and msg.get('id') == frontier_message_id:
                            should_continue = False
                            break
                        if window_start and message_dt and message_dt < window_start:
                            should_continue = False
                            break
                        selected_desc.append(msg)
                    filtered_msgs = list(reversed(selected_desc))
                else:
                    filtered_msgs = all_msgs

                # Success - log if this was a retry
                if attempt > 0:
                    _logger.info(f"Successfully fetched messages for {conv_fm_id} on retry attempt {attempt}")
                
                return (should_continue, filtered_msgs)
                
            except requests.exceptions.Timeout as e:
                _logger.warning(f"Timeout fetching messages (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    _logger.error(f"Final timeout for conversation {conv_fm_id} after {max_retries} attempts")
                    raise RuntimeError(
                        f"Timeout fetching messages for conversation {conv_fm_id} after {max_retries} attempts."
                    ) from e
                    
            except requests.exceptions.RequestException as e:
                error_msg = str(e).lower()
                if 'rate limit' in error_msg or 'too many requests' in error_msg:
                    _logger.warning(f"Rate limit hit for {conv_fm_id} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Longer delay for rate limits
                        continue
                
                _logger.error(f"Request error fetching messages (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Request error fetching messages for conversation {conv_fm_id}: {e}"
                    ) from e
                    
            except Exception as e:
                _logger.error(f"Unexpected error fetching messages (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Unexpected error fetching messages for conversation {conv_fm_id}: {e}"
                    ) from e

        raise RuntimeError(f"Unable to fetch messages for conversation {conv_fm_id}.")

    def _fetch_all_messages(self, page_specific_access_token, window_start=None, stop_at_message_id=None):
        self.ensure_one()
        all_messages = []
        offset = 0

        while True:
            should_continue, batch = self._fetch_message_batch(
                page_specific_access_token,
                offset,
                window_start=window_start,
                stop_at_message_id=stop_at_message_id,
            )
            if not batch:
                break

            all_messages.extend(batch)
            offset += len(batch)

            if not should_continue:
                break

        all_messages = sorted(
            all_messages,
            key=lambda msg: (
                self._to_aware_utc(msg.get('inserted_at')) or pytz.UTC.localize(datetime(1970, 1, 1)),
                str(msg.get('id') or ''),
            ),
            reverse=True,
        )

        if all_messages:
            self.last_message_id = all_messages[0].get('id')

        return all_messages
    
    def _fetch_single_conversation(self, page_specific_access_token):
        """Fetch single conversation detail from Pancake API (including assignees)"""
        self.ensure_one()
        
        if not self.conversation_fm_id:
            _logger.warning(f"Conversation {self.id} has no conversation_fm_id")
            return None
        
        url = f"https://api.pancake.vn/v2/conversations/{self.conversation_fm_id}"
        headers = {'Authorization': f'Bearer {page_specific_access_token}'}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('data')
            else:
                _logger.warning(f"Failed to fetch conversation {self.conversation_fm_id}: {response.status_code}")
                return None
        except Exception as e:
            _logger.error(f"Error fetching conversation {self.conversation_fm_id}: {e}")
            return None

    
    def sync_all_conversations_scheduled(self):
        recent_date = datetime.now() - timedelta(days=1)
        recent_month = datetime.now() - timedelta(days=30)

        # Debug đơn giản
        total_conversations = self.env['page.fm.conversation'].search_count([])
        _logger.info(f"Bắt đầu sync scheduled - Tổng {total_conversations} conversations trong hệ thống")
        
        if total_conversations == 0:
            _logger.warning("Không có conversation nào trong hệ thống! Hãy đồng bộ Pages và Conversations trước.")
            return

        # SIMPLIFIED DOMAIN - Chỉ dùng điều kiện thời gian cơ bản
        conversations = self.env['page.fm.conversation'].search([
            '&',  # AND operator  
            '|',  # OR cho điều kiện thời gian
            ('updated_at_fm_by_hand', '=', False),
            ('updated_at_fm_by_hand', '<', recent_date.strftime('%Y-%m-%d %H:%M:%S')),
            ('updated_at_fm', '>=', recent_month.strftime('%Y-%m-%d %H:%M:%S')),  # AND với cập nhật gần đây
        ])

        # Nếu có conversation được chọn cụ thể (từ UI), dùng chúng thay vì filter
        if len(self) >= 1:  # Sửa từ > 1 thành >= 1 để hỗ trợ chọn 1 conversation
            conversations = self
            _logger.info(f"User đã chọn {len(conversations)} cuộc hội thoại cụ thể để sync")
        else:
            _logger.info(f"Chế độ tự động: Tìm thấy {len(conversations)} cuộc hội thoại cần sync theo filter")
        
        _logger.info(f"Sẽ đồng bộ {len(conversations)} cuộc hội thoại")
        
        if len(conversations) == 0:
            _logger.warning("Không có conversation nào cần đồng bộ sau khi áp dụng filter.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không có conversation nào cần đồng bộ',
                    'type': 'warning'
                }
            }
        
        # Sử dụng helper method chung
        self._perform_sync_batch(conversations)
        
        # Trả về reload action với thông báo
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }



    def _perform_sync_batch(self, conversations):
        """Helper method để thực hiện sync một batch conversations"""
        # Lấy main access token một lần cho tất cả
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return

        synced_count = 0
        error_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5  # Circuit breaker threshold
        
        for conv in conversations:
            try:
                # Circuit breaker: Dừng nếu quá nhiều lỗi liên tiếp
                if consecutive_errors >= max_consecutive_errors:
                    _logger.error(f"Circuit breaker activated: {consecutive_errors} consecutive errors. Stopping sync.")
                    break
                
                customer_name = conv.customer_name_fm or conv.name or f"Conversation {conv.id}"
                _logger.info(f"Bắt đầu sync conversation cho khách hàng: {customer_name} (ID: {conv.id})")
                
                # Kiểm tra token trước khi sync
                page = conv.page_fm_page_id
                if not page:
                    _logger.error(f"Conversation {conv.id} không có page_fm_page_id")
                    error_count += 1
                    consecutive_errors += 1
                    continue
                
                try:
                    page_token = page._generate_page_specific_access_token(main_access_token)
                    if not page_token:
                        _logger.error(f"Không thể tạo token cho page {page.name} (ID: {page.page_fm_id_str})")
                        error_count += 1
                        consecutive_errors += 1
                        continue
                    
                    # Thực hiện sync
                    result = conv.action_sync_messages()
                    message_count = conv.message_count
                    
                    _logger.info(f"✓ Đã sync {message_count} tin nhắn cho cuộc hội thoại của khách hàng: {customer_name}")
                    
                    conv.updated_at_fm_by_hand = datetime.now()
                    synced_count += 1
                    consecutive_errors = 0  # Reset error counter on success
                    self.env.cr.commit()
                    
                    # THÊM RATE LIMITING: Delay giữa các conversation
                    import time
                    time.sleep(0.5)  # Delay 500ms giữa mỗi conversation
                    
                except Exception as token_error:
                    _logger.error(f"Lỗi token/API cho conversation {conv.id} ({customer_name}): {token_error}")
                    error_count += 1
                    consecutive_errors += 1
                    self.env.cr.rollback()
                    
                    # Nếu lỗi timeout, delay lâu hơn trước khi tiếp tục
                    if "timeout" in str(token_error).lower() or "connection" in str(token_error).lower():
                        _logger.warning(f"Network error detected, waiting 5 seconds before continuing...")
                        import time
                        time.sleep(5)
                    
            except Exception as e:
                customer_name = getattr(conv, 'customer_name_fm', None) or getattr(conv, 'name', None) or f"Conversation {conv.id}"
                _logger.error(f"Lỗi khi sync hội thoại {conv.id} ({customer_name}): {e}")
                error_count += 1
                consecutive_errors += 1
                self.env.cr.rollback()
        
        _logger.info(f"Finished sync: {synced_count} thành công, {error_count} lỗi từ tổng {len(conversations)} conversations.")
        
        if error_count > 0:
            _logger.warning(f"Có {error_count} lỗi trong quá trình sync. Kiểm tra: 1) Token API, 2) Kết nối mạng, 3) Log chi tiết ở trên.")

    
    def action_sync_messages(self, date_from=None, date_to=None, unread_first=False, **kwargs):
        """Đồng bộ tin nhắn; hỗ trợ lọc theo khoảng thời gian và cờ ưu tiên (tùy chọn).
       - date_from/date_to: datetime hoặc str (ISO / 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM:SS')
       - unread_first: hiện tại chỉ để tương thích; không ảnh hưởng thứ tự ghi
       - cũng chấp nhận unread_only từ wizard qua **kwargs
       """
        #_logger.info("------------------------------------------->Hello")
        return_stats = bool(kwargs.pop('return_stats', False))
        sync_scope = self._normalize_sync_scope(kwargs.pop('sync_scope', None))
        sync_origin = kwargs.pop('sync_origin', None) or 'manual_single'
        sync_window_key = kwargs.pop('sync_window_key', None)
        allowed_page_ids = kwargs.pop('allowed_page_ids', None)
        if allowed_page_ids is not None:
            allowed_page_ids = {
                int(page_id)
                for page_id in allowed_page_ids
                if page_id
            }
        if 'unread_only' in kwargs and kwargs['unread_only'] is not None:
            unread_first = bool(kwargs['unread_only'])
            if sync_origin == 'manual_single':
                sync_origin = 'wizard'

        dt_from = self._to_aware_utc(date_from, is_end=False)
        dt_to = self._to_aware_utc(date_to, is_end=True)
        
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            if return_stats:
                return {
                    'status': 'error',
                    'error': 'missing_main_access_token',
                    'created_messages': 0,
                    'existing_messages': 0,
                    'fetched_messages': 0,
                }
            return False

        results = []
        for record in self:
            attempt_time = fields.Datetime.now()
            record_stats = {
                'conversation_id': record.id,
                'conversation_name': record.display_name,
                'status': 'pending',
                'created_messages': 0,
                'existing_messages': 0,
                'fetched_messages': 0,
                'last_message_sync_fm': False,
            }
            record.write({
                'last_message_sync_attempt_at': attempt_time,
                'last_message_sync_origin': sync_origin,
            })
            page = record.page_fm_page_id
            page_allowed = bool(page and page.active)
            if page_allowed and allowed_page_ids is not None:
                page_allowed = page.id in allowed_page_ids
            elif page_allowed and sync_scope != 'all_active_pages':
                page_allowed = bool(page.sync_enabled)
            if not page_allowed:
                if not page:
                    message = 'Conversation chưa gắn page.'
                    error_code = 'page_missing'
                elif allowed_page_ids is not None:
                    message = 'Page của conversation nằm ngoài phạm vi job đồng bộ toàn bộ.'
                    error_code = 'page_outside_job_scope'
                else:
                    message = 'Page của conversation chưa được chọn để đồng bộ.'
                    error_code = 'page_not_selected'
                record_stats.update({
                    'status': 'error',
                    'error': error_code,
                })
                if return_stats:
                    results.append(record_stats)
                    continue
                raise UserError(message)

            page_specific_access_token = page._generate_page_specific_access_token(main_access_token)
            if not page_specific_access_token:
                _logger.error(f"Không thể tạo token cho trang của hội thoại {record.conversation_fm_id}")
                record_stats.update({
                    'status': 'error',
                    'error': 'missing_page_access_token',
                })
                results.append(record_stats)
                continue

            # Fallback: dữ liệu cũ chưa có conv_page_fm_id thì gán bằng page_fm_id_str_related
            if not record.conv_page_fm_id and record.page_fm_id_str_related:
                record.write({'conv_page_fm_id': record.page_fm_id_str_related})

            messages = record._fetch_all_messages(
                page_specific_access_token,
                window_start=dt_from,
                stop_at_message_id=record.last_message_id,
            )
            record_stats['fetched_messages'] = len(messages)
            if not messages:
                sync_time = fields.Datetime.now()
                record.write({
                    'last_message_sync_fm': sync_time,
                    'last_successful_message_sync_at': sync_time,
                    'last_message_sync_origin': sync_origin,
                })
                _logger.info(f"Không có tin nhắn mới cho hội thoại {record.name}")
                record_stats.update({
                    'status': 'ok',
                    'last_message_sync_fm': sync_time,
                })
                results.append(record_stats)
                continue

            _logger.info(f"Lấy được {len(messages)} tin nhắn từ API cho hội thoại {record.name}")

            Message = self.env['page.fm.message']
            created_count = 0
            existing_count = 0

            messages_reversed = list(reversed(messages))  # Đảm bảo là list
            for i in range(len(messages_reversed)):  # Process oldest first
                msg_data = messages_reversed[i]
                msg_fm_id = msg_data.get('id')
                if not msg_fm_id:
                    continue

                existing = Message.search([
                    ('message_fm_id', '=', msg_fm_id),
                    ('conversation_id', '=', record.id)
                ], limit=1)

                if existing:
                    existing_count += 1
                    continue

                inserted_at_api = msg_data.get('inserted_at', datetime.now().isoformat())
                dt_obj = None
                try:
                    dt_obj = record._to_aware_utc(inserted_at_api)
                    inserted_at = fields.Datetime.to_string(dt_obj.replace(tzinfo=None))
                except ValueError:
                    inserted_at = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                
                # >>> NEW: lọc theo date_from / date_to nếu có
                if dt_from and dt_obj and dt_obj < dt_from:
                    continue
                if dt_to and dt_obj and dt_obj > dt_to:
                    continue

                previous_time = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                if i + 1 < len(messages_reversed):
                    next_msg_data = messages_reversed[i + 1]
                    previous_time_api = next_msg_data.get('inserted_at', datetime.now().isoformat())
                    try:
                        dt_obj = record._to_aware_utc(previous_time_api)
                        previous_time = fields.Datetime.to_string(dt_obj.replace(tzinfo=None))
                    except ValueError:
                        previous_time= datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                else:
                    previous_time = inserted_at

                type_content =  'text'
                url_content = ''

                if msg_data.get('attachments'):
                    msg_attachments =  msg_data.get('attachments')[0]

                    type_content = msg_attachments.get('type', 'text')
                    url_content = msg_attachments.get('url', '')

                    if not type_content or not url_content:
                        attachments = msg_attachments.get('attachments', [])
                        if attachments:
                            type_content = attachments[0].get('type', 'text')
                            url_content = attachments[0].get('url', '')
                            if type_content == 'video':
                                video_data = attachments[0].get('video_data') or {}
                                url_content = video_data.get('url', '')

                # ---- Find / create staff safely ----
                Users = self.env['res.users'].sudo()
                from_info  = msg_data.get('from') or {}
                admin_id   = str(from_info.get('admin_id') or '').strip()
                admin_name = (from_info.get('admin_name') or '').strip()

                staff = Users.browse()  # mặc định rỗng

                # Chỉ xử lý staff khi có admin_id (tin do nhân viên gửi)
                if admin_id:
                    # 1) Tìm theo pancake_id (kiểm tra cả 3 field: pancake_id, pancake_uuid, pancake_number_id)
                    if 'pancake_id' in Users._fields:
                        staff = Users.search([
                            '|', '|',
                            ('pancake_id', '=', admin_id),
                            ('pancake_uuid', '=', admin_id),
                            ('pancake_number_id', '=', admin_id)
                        ], limit=1)

                    # 2) Không có thì fallback theo tên, nhưng chỉ nhận nếu DUY NHẤT
                    if not staff and admin_name:
                        matches = Users.search([('name', '=', admin_name)], limit=2)
                        if len(matches) == 1:
                            staff = matches

                    # 3) Nếu tìm thấy mà chưa có pancake_id thì gắn thêm (không tạo user mới)
                    if staff and 'pancake_id' in Users._fields and not staff.pancake_id:
                        staff.with_context(no_reset_password=True).write({'pancake_id': admin_id})

                    # 4) Không liên kết vào user hệ thống
                    if staff and staff.login in ('admin', 'public'):
                        staff = Users.browse()

                    # 5) Nếu vẫn không có -> tạo user mới (an toàn)
                    if not staff and admin_name:
                        login_base = f"pancake_{admin_id}"
                        # đảm bảo login duy nhất
                        if Users.search_count([('login', '=', login_base)]) > 0:
                            login_base = f"{login_base}_{int(datetime.now().timestamp())}"

                        vals = {
                            'name': admin_name or 'Unknown Staff',
                            'login': login_base,
                        }
                        if 'pancake_id' in Users._fields:
                            vals['pancake_id'] = admin_id

                        # Tạo không gửi mail reset mật khẩu
                        staff = Users.with_context(no_reset_password=True).create(vals)
                        _logger.info("Created staff user from Pancake: %s (id=%s, admin_id=%s)", staff.name, staff.id, admin_id)
                else:
                    # Tin của khách (không có admin_id) -> không set staff
                    staff = Users.browse()

                values = {
                    'message_fm_id': msg_fm_id,
                    'conversation_id': record.id,
                    'sender_name_fm': msg_data.get('from', {}).get('name'),
                    'staff_name_fm': msg_data.get('from', {}).get('admin_name'),
                    'staff_id_fm': msg_data.get('from', {}).get('admin_id'),
                    'previous_time': previous_time,
                    'staff': staff.id if staff else False,
                    'content_html': msg_data.get('message', ''),
                    # 'attachments_json': json.dumps(msg_data.get('attachments')) if msg_data.get('attachments') else False,
                    'attachments_json': json.dumps(msg_data),
                    'inserted_at_fm': inserted_at,
                    'raw_json_message': json.dumps(msg_data),
                    'type_content': type_content,
                    'url_content': url_content,
                    'sync_origin': sync_origin,
                    'sync_window_key': sync_window_key,
                }
                Message.create(values)
                created_count += 1
                
                # 🆕 YÊU CẦU #2: Tự động gán staff vào participant_user_ids
                if staff:
                    current_participants = set(record.participant_user_ids.ids)
                    if staff.id not in current_participants:
                        current_participants.add(staff.id)
                        record.write({'participant_user_ids': [(6, 0, list(current_participants))]})
                        #_logger.info(f"➕ Auto-added staff {staff.name} to conversation participants (from message)")
                        
                        # 🆕 SYNC VÀO PARTNER luôn
                        if record.partner_id:
                            partner_participants = set(record.partner_id.participant_user_ids.ids)
                            if staff.id not in partner_participants:
                                partner_participants.add(staff.id)
                                record.partner_id.write({'participant_user_ids': [(6, 0, list(partner_participants))]})
                                #_logger.info(f"➕ Auto-added staff {staff.name} to partner {record.partner_id.name} (from message)")

            sync_time = fields.Datetime.now()
            record.write({
                'last_message_sync_fm': sync_time,
                'last_successful_message_sync_at': sync_time,
                'last_message_sync_origin': sync_origin,
            })
            record.invalidate_recordset(['message_count'])
            record_stats.update({
                'status': 'ok',
                'created_messages': created_count,
                'existing_messages': existing_count,
                'last_message_sync_fm': sync_time,
            })

            # 🆕 SYNC ASSIGNEES từ conversation API
            try:
                conv_detail = record._fetch_single_conversation(page_specific_access_token)
                if conv_detail:
                    assignee_data = conv_detail.get('current_assign_users', [])
                    if assignee_data:
                        new_user_ids = []
                        owner_user_id = False
                        ResUsers = self.env['res.users'].sudo()
                        
                        for idx, assignee in enumerate(assignee_data):
                            pancake_id = assignee.get('id')  # UUID
                            email = assignee.get('email')
                            name = assignee.get('name', 'Unknown')
                            
                            user = None
                            
                            # Tìm theo pancake_id (kiểm tra cả 3 field)
                            if pancake_id:
                                user = ResUsers.search([
                                    '|', '|',
                                    ('pancake_id', '=', pancake_id),
                                    ('pancake_uuid', '=', pancake_id),
                                    ('pancake_number_id', '=', pancake_id)
                                ], limit=1)
                                if user:
                                    matched_field = 'pancake_id' if user.pancake_id == pancake_id else \
                                                  'pancake_uuid' if user.pancake_uuid == pancake_id else \
                                                  'pancake_number_id'
                                    #_logger.info(f"✅ Found assignee by {matched_field} {pancake_id[:8]}... → {user.name}")
                            
                            # Tìm theo email
                            if not user and email:
                                user = ResUsers.search([('login', '=', email)], limit=1)
                                if not user:
                                    user = ResUsers.search([('email', '=', email)], limit=1)
                                if user:
                                    _logger.info(f"✅ Found assignee by email {email} → {user.name}")
                            
                            if user:
                                new_user_ids.append(user.id)
                                if idx == 0 and not owner_user_id:
                                    owner_user_id = user.id
                            else:
                                _logger.debug(f"⚠️ Assignee not found: {name} (pancake_id: {pancake_id[:8] if pancake_id else 'N/A'}, email: {email or 'N/A'})")
                        
                        # Gán owner
                        if owner_user_id:
                            record.write({'owner_id': owner_user_id})
                        
                        # Gán participants - MERGE với cũ
                        if new_user_ids:
                            old_participant_ids = set(record.participant_user_ids.ids)
                            merged_ids = old_participant_ids.union(set(new_user_ids))
                            record.write({'participant_user_ids': [(6, 0, list(merged_ids))]})
                            #_logger.info(f"✅ Synced assignees for conversation {record.conversation_fm_id}: {len(merged_ids)} users")
                            
                            # 🆕 SYNC VÀO PARTNER luôn
                            if record.partner_id:
                                partner_participants = set(record.partner_id.participant_user_ids.ids)
                                partner_merged = partner_participants.union(set(new_user_ids))
                                record.partner_id.write({
                                    'participant_user_ids': [(6, 0, list(partner_merged))],
                                    'responsible_user_id': owner_user_id  # Cập nhật người phụ trách hiện tại
                                })
                                #_logger.info(f"✅ Synced assignees to partner {record.partner_id.name}: {len(partner_merged)} users")
                    else:
                        _logger.info(f"ℹ️ No assignees from API for conversation {record.conversation_fm_id}")
            except Exception as e:
                _logger.error(f"❌ Error syncing assignees for conversation {record.id}: {e}", exc_info=True)

            # Tự động cập nhật require_processing sau khi sync tin nhắn
            try:
                record._auto_bump_require_processing()
            except Exception as e:
                _logger.error(f"Lỗi khi cập nhật require_processing cho conversation {record.id}: {e}")

            # Attempt to find or create a partner after syncing
            try:
                if not record.partner_id:
                    record._find_or_create_partner()
            except Exception as e:
                _logger.error(f"Lỗi khi tìm/tạo partner cho hội thoại {record.id}: {e}", exc_info=True)
            
            # 🆕 Đồng bộ tags từ conversation sang partner (luôn sync, kể cả khi rỗng)
            try:
                if record.partner_id:
                    record.partner_id.sudo().write({
                        'pancake_tag_ids': [(6, 0, record.pancake_tag_ids.ids)]
                    })
                    if record.pancake_tag_ids:
                        _logger.info(f"Synced {len(record.pancake_tag_ids)} tags from conversation to partner {record.partner_id.name}")
                    else:
                        _logger.debug(f"Cleared tags for partner {record.partner_id.name} (no tags in conversation)")
            except Exception as e:
                _logger.error(f"Lỗi khi sync tags sang partner: {e}", exc_info=True)

            # Áp dụng rule/refresh snippet
            try:
                record.apply_status_rule()
            except Exception:
                _logger.exception("Lỗi khi áp dụng rule/refresh snippet cho conversation %s", record.id)
                
            # DEPRECATED: Không cần gán staff từ message nữa
            # Staff được gán tự động từ conversation API (chính xác hơn)
            # try:
            #     record._recompute_staff_links()
            # except Exception:
            #     _logger.exception("Lỗi khi gán staff cho conversation %s", record.id)
            
            # >>> NEW: đẩy thông tin phụ trách sang Partner (nếu đã có partner)
            if record.partner_id:
                try:
                    record.partner_id.sync_staff_from_conversations()
                except Exception:
                    _logger.exception("Lỗi khi đồng bộ staff sang partner cho conv %s", record.id)

            results.append(record_stats)

        # Gọi hàm tính toán lại last_message_at_fm cho tất cả records đã sync
        try:
            # Gọi hàm compute một lần cho tất cả các records đã sync
            self._compute_last_message_at_fm()
        except Exception as e:
            _logger.error(f"Lỗi khi tính toán lại last_message_at_fm: {e}")

        if return_stats:
            if len(results) == 1:
                return results[0]
            return {
                'status': 'ok',
                'results': results,
                'created_messages': sum(item.get('created_messages', 0) for item in results),
                'existing_messages': sum(item.get('existing_messages', 0) for item in results),
                'fetched_messages': sum(item.get('fetched_messages', 0) for item in results),
                'processed_conversations': len(results),
            }

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def _selected_sync_conversation_domain(self):
        return self._sync_conversation_domain_for_scope('selected_pages')

    @api.model
    def _normalize_sync_scope(self, sync_scope=None):
        if sync_scope == 'all_active_pages':
            return 'all_active_pages'
        return 'selected_pages'

    @api.model
    def _sync_conversation_domain_for_scope(self, sync_scope=None):
        sync_scope = self._normalize_sync_scope(sync_scope)
        domain = [('page_fm_page_id.active', '=', True)]
        if sync_scope != 'all_active_pages':
            domain.append(('page_fm_page_id.sync_enabled', '=', True))
        return domain

    @api.model
    def _manual_full_sync_is_running(self):
        return self.env['pancake.message.sync.job'].sudo().is_manual_sync_in_progress()

    @api.model
    def _get_full_sync_unsynced_domain(self, sync_started_at, sync_scope=None):
        selected_domain = self._sync_conversation_domain_for_scope(sync_scope)
        if not sync_started_at:
            return selected_domain + [('last_message_sync_fm', '=', False)]
        return selected_domain + [
            '|',
            ('last_message_sync_fm', '=', False),
            ('last_message_sync_fm', '<', fields.Datetime.to_string(sync_started_at)),
        ]

    @api.model
    def _get_full_sync_remaining_count(self, sync_started_at, sync_scope=None):
        return self.search_count(self._get_full_sync_unsynced_domain(sync_started_at, sync_scope=sync_scope))

    @api.model
    def _select_full_sync_tier3_batch(self, sync_started_at, batch_limit=50, sync_scope=None, recent_days=None):
        recent_days = recent_days or self._get_recent_activity_days()
        recent_days_ago = datetime.now() - timedelta(days=recent_days)
        unsynced_domain = self._get_full_sync_unsynced_domain(sync_started_at, sync_scope=sync_scope)

        priority_1 = self.search(
            [('partner_id', '=', False)] + unsynced_domain,
            limit=batch_limit,
            order='updated_at_fm desc, id desc',
        )
        if priority_1:
            return priority_1, 'P1-NEW', 'Conversation mới chưa map khách hàng'

        candidate_limit = max(int(batch_limit or 50) * 5, 100)
        priority_2_candidates = self.search(
            [('partner_id', '!=', False), ('last_message_at_fm', '!=', False)] + unsynced_domain,
            limit=candidate_limit,
            order='last_message_at_fm desc, id desc',
        )
        priority_2 = priority_2_candidates.filtered(
            lambda c: c.last_message_at_fm and (not c.last_message_sync_fm or c.last_message_at_fm > c.last_message_sync_fm)
        )[:batch_limit]
        if priority_2:
            return priority_2, 'P2-NEWMSG', 'Conversation có tin nhắn mới chưa sync'

        priority_3 = self.search(
            [('partner_id', '!=', False), ('last_update_at', '>=', fields.Datetime.to_string(recent_days_ago))] + unsynced_domain,
            limit=batch_limit,
            order='last_update_at desc, id desc',
        )
        if priority_3:
            return priority_3, 'P3-RECENT', 'Conversation có hoạt động gần đây'

        priority_4 = self.search(
            [('require_processing', '=', True), ('partner_id', '!=', False)] + unsynced_domain,
            limit=batch_limit,
            order='last_processing_change_at desc, id desc',
        )
        if priority_4:
            return priority_4, 'P4-MANUAL', 'Conversation đang cần xử lý thủ công'

        return self.browse(), False, False

    @api.model
    def _sync_conversations_job_batch(self, conversations, priority_label=None, job=None, delay_seconds=0.5, sync_scope=None):
        stats = {
            'processed_count': 0,
            'failed_count': 0,
            'created_messages': 0,
            'existing_messages': 0,
            'fetched_messages': 0,
            'priority_label': priority_label,
            'errors': [],
        }
        if not conversations:
            return stats

        for conv in conversations:
            try:
                result = conv.action_sync_messages(
                    return_stats=True,
                    sync_scope=sync_scope,
                    sync_origin='manual_full',
                )
                if result.get('status') == 'error':
                    self.env.cr.rollback()
                    stats['failed_count'] += 1
                    error_message = result.get('error') or f"Sync failed for conversation {conv.id}"
                    stats['errors'].append(error_message)
                    if job:
                        job._append_log(
                            'error',
                            f"[{priority_label or 'SYNC'}] {conv.display_name}: {error_message}",
                            event_code='page_failed_api',
                            page=conv.page_fm_page_id,
                            conversation=conv,
                        )
                        self.env.cr.commit()
                    continue

                stats['processed_count'] += 1
                stats['created_messages'] += int(result.get('created_messages', 0) or 0)
                stats['existing_messages'] += int(result.get('existing_messages', 0) or 0)
                stats['fetched_messages'] += int(result.get('fetched_messages', 0) or 0)
                self.env.cr.commit()
                if delay_seconds:
                    time.sleep(delay_seconds)
            except Exception as exc:
                self.env.cr.rollback()
                stats['failed_count'] += 1
                message = f"{conv.display_name}: {exc}"
                stats['errors'].append(message)
                _logger.error("[%s] Error syncing conversation %s: %s", priority_label or 'SYNC', conv.id, exc)
                if job:
                    job._append_log(
                        'error',
                        f"[{priority_label or 'SYNC'}] {message}",
                        event_code='page_failed_api',
                        page=conv.page_fm_page_id,
                        conversation=conv,
                    )
                    self.env.cr.commit()
                time.sleep(1)

        return stats

    @api.model
    def run_full_sync_tier3_batch(self, sync_started_at, batch_limit=50, job=None, sync_scope=None, recent_days=None):
        conversations, priority_label, priority_description = self._select_full_sync_tier3_batch(
            sync_started_at=sync_started_at,
            batch_limit=batch_limit,
            sync_scope=sync_scope,
            recent_days=recent_days,
        )
        stats = self._sync_conversations_job_batch(
            conversations,
            priority_label=priority_label,
            job=job,
            sync_scope=sync_scope,
        )
        stats.update({
            'priority_description': priority_description,
            'conversation_ids': conversations.ids,
        })
        return stats

    @api.model
    def run_full_sync_tier4_batch(self, sync_started_at, batch_size=50, pointer=0, job=None, sync_scope=None):
        unsynced_domain = self._get_full_sync_unsynced_domain(sync_started_at, sync_scope=sync_scope)
        batch = self.search([('id', '>', pointer)] + unsynced_domain, order='id asc', limit=batch_size)
        reset_happened = False

        if not batch and pointer:
            pointer = 0
            reset_happened = True
            batch = self.search(unsynced_domain, order='id asc', limit=batch_size)

        if not batch:
            return {
                'processed_count': 0,
                'failed_count': 0,
                'created_messages': 0,
                'existing_messages': 0,
                'fetched_messages': 0,
                'next_pointer': 0,
                'reset_happened': reset_happened,
                'completed': True,
                'remaining_count': 0,
                'conversation_ids': [],
            }

        stats = self._sync_conversations_job_batch(
            batch,
            priority_label='TIER4-FULL',
            job=job,
            sync_scope=sync_scope,
        )
        remaining_count = self._get_full_sync_remaining_count(sync_started_at, sync_scope=sync_scope)
        stats.update({
            'next_pointer': batch[-1].id,
            'reset_happened': reset_happened,
            'completed': remaining_count == 0,
            'remaining_count': remaining_count,
            'conversation_ids': batch.ids,
        })
        return stats

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Tự động set require_processing theo logic
        for rec in records:
            try:
                rec._auto_bump_require_processing()
            except Exception as e:
                _logger.error(f"Lỗi khi set require_processing cho conversation {rec.id}: {e}")
        return records



    def write(self, vals):
        """Mô tả:
        - Giới hạn quyền cho nhóm sale (không phải manager)
        - Sau khi ghi, nếu đổi status/unread thì auto cập nhật require_processing
        """
        user = self.env.user
        allow_toggle = self.env.context.get('allow_toggle_require_processing')  # cho phép toggle checklist

        # CRITICAL: Chỉ check permission khi user tồn tại (tránh lỗi khi gọi từ webhook/cron)
        if (user and user.id 
            and user.has_group('dac_erp.group_dac_erp_sale')
            and not user.has_group('dac_erp.group_dac_erp_manager')
            and not allow_toggle):
            allowed = {'status_state', 'is_unread_fm'}
            disallowed = set(vals.keys()) - allowed
            if disallowed:
                raise AccessError(_("Bạn không thể thực hiện thay đổi này. \nVui lòng liên hệ quản lý hoặc quản trị viên để hỗ trợ!"))

        # Nếu sửa suggestion_note -> cập nhật mốc last_suggestion_at
        if 'suggestion_note' in vals:
            # chỉ set khi thực sự có thay đổi nội dung
            now = fields.Datetime.now()
            for rec in self:
                old = (rec.suggestion_note or '').strip()
                new = (vals.get('suggestion_note') or '').strip()
                if old != new:
                    vals = dict(vals)  # tránh mutate
                    vals['last_suggestion_at'] = now
                    break

        # Nếu có thay đổi thuộc nhóm “form”, set last_update_at = now
        if any(k in _FORM_TOUCH_FIELDS for k in vals.keys()):
            vals = dict(vals)  # tránh mutate context
            vals['updated_at_fm_by_hand'] = fields.Datetime.now()  # để compute gom mốc

        res = super(PageFmConversation, self).write(vals)

        # Logic auto-bump khi có thay đổi 2 field này
        if any(k in vals for k in ('status_state', 'is_unread_fm')) and not self.env.context.get('skip_auto_bump_require_processing'):
            for rec in self:
                try:
                    rec._auto_bump_require_processing()
                except Exception:
                    _logger.exception("Auto-bump require_processing failed for conv %s", rec.id)
        return res


    def _build_external_url_for_platform(self, page_id, conv_id):
        """
        Build URL theo đúng mẫu Pancake cung cấp:
        https://pancake.vn/{page_id}?c_id={conv_id}
        """
        if page_id and conv_id:
            return f"https://pancake.vn/{page_id}?c_id={conv_id}"
        return False


    external_url = fields.Char(string="Link Pancake", compute="_compute_external_url", store=False)

    def _compute_external_url(self):
        for r in self:
            page_id = r.conv_page_fm_id or r.page_fm_id_str_related
            conv_id = r.conversation_fm_id
            if page_id and conv_id:
                r.external_url = self._build_external_url_for_platform(page_id, conv_id)
            else:
                r.external_url = False


    def action_open_on_pancake(self):
        self.ensure_one()
        url = self.external_url or '#'
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_open_message_dashboard(self):
        self.ensure_one()
        return self.env['pancake.message.dashboard'].action_open_dashboard(conversation_id=self.id)

    def action_open_message_sync_dashboard(self):
        self.ensure_one()
        return self.env['pancake.sync.dashboard'].action_open_dashboard()

    @api.model
    def _get_continuous_sync_timezone_name(self):
        icp = self.env['ir.config_parameter'].sudo()
        return (icp.get_param('pancake.continuous_sync_timezone') or 'Asia/Ho_Chi_Minh').strip() or 'Asia/Ho_Chi_Minh'

    @api.model
    def _get_continuous_sync_timezone(self):
        timezone_name = self._get_continuous_sync_timezone_name()
        try:
            return pytz.timezone(timezone_name)
        except Exception:
            _logger.warning("Timezone `%s` khong hop le, fallback ve Asia/Ho_Chi_Minh", timezone_name)
            return pytz.timezone('Asia/Ho_Chi_Minh')

    @api.model
    def _to_aware_utc(self, value, is_end=False):
        if not value:
            return None
        if isinstance(value, datetime):
            dt_value = value
        else:
            raw_value = str(value)
            try:
                dt_value = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
            except Exception:
                if len(raw_value) == 10:
                    raw_value = raw_value + (' 23:59:59' if is_end else ' 00:00:00')
                dt_value = fields.Datetime.to_datetime(raw_value)
        if dt_value.tzinfo is None:
            dt_value = pytz.UTC.localize(dt_value)
        return dt_value.astimezone(pytz.UTC)

    @api.model
    def _to_server_datetime_string(self, value):
        if not value:
            return False
        dt_value = self._to_aware_utc(value)
        if not dt_value:
            return False
        return fields.Datetime.to_string(dt_value.replace(tzinfo=None))

    @api.model
    def _build_window_bounds(self, layer_key):
        timezone_obj = self._get_continuous_sync_timezone()
        utc_now = pytz.UTC.localize(fields.Datetime.now())
        local_now = utc_now.astimezone(timezone_obj)
        local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

        if layer_key == 'nightly_two_day':
            local_window_start = (local_today_start - timedelta(days=1))
        else:
            local_window_start = local_today_start

        window_start_utc = local_window_start.astimezone(pytz.UTC)
        window_end_utc = local_now.astimezone(pytz.UTC)
        return window_start_utc, window_end_utc

    @api.model
    def _build_window_stats_from_bounds(self, window_start_utc, window_end_utc):
        return {
            'window_start': window_start_utc,
            'window_end': window_end_utc,
            'window_start_epoch': int(window_start_utc.timestamp()),
            'window_end_epoch': int(window_end_utc.timestamp()),
            'window_start_str': fields.Datetime.to_string(window_start_utc.replace(tzinfo=None)),
            'window_end_str': fields.Datetime.to_string(window_end_utc.replace(tzinfo=None)),
        }

    @api.model
    def _compute_sync_window_stats(self, layer_key):
        window_start_utc, window_end_utc = self._build_window_bounds(layer_key)
        return self._build_window_stats_from_bounds(window_start_utc, window_end_utc)

    @api.model
    def _compute_recent_hours_window_stats(self, hours):
        utc_now = pytz.UTC.localize(fields.Datetime.now())
        window_start_utc = utc_now - timedelta(hours=int(hours or 0))
        return self._build_window_stats_from_bounds(window_start_utc, utc_now)

    @api.model
    def _record_continuous_layer_stats(self, layer_key, conversations_checked=0, messages_created=0, error_count=0):
        icp = self.env['ir.config_parameter'].sudo()
        now_value = fields.Datetime.now()
        prefix = f'pancake.{layer_key}'
        icp.set_param(f'{prefix}.last_run_at', fields.Datetime.to_string(now_value))
        icp.set_param(f'{prefix}.conversations_checked', str(int(conversations_checked or 0)))
        icp.set_param(f'{prefix}.messages_created', str(int(messages_created or 0)))
        icp.set_param(f'{prefix}.error_count', str(int(error_count or 0)))

    @api.model
    def _create_continuous_log(self, layer_key, level, message, event_code=None, page_id=None, conversation_id=None, stats=None, source_type='continuous'):
        stats_json = False
        if stats:
            try:
                stats_json = json.dumps(stats, ensure_ascii=False, default=str)
            except Exception:
                stats_json = False
        return self.env['pancake.message.sync.log'].sudo().create_continuous_log(
            layer_key,
            level,
            message,
            event_code=event_code,
            page_id=page_id,
            conversation_id=conversation_id,
            stats_json=stats_json,
            source_type=source_type,
        )

    @api.model
    def _get_continuous_batch_limit(self):
        icp = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(icp.get_param('pancake.sync_batch_size', '50') or 50), 1)
        except (TypeError, ValueError):
            return 50

    @api.model
    def _get_windowed_conversation_candidates(self, layer_key, limit=None, sync_stats=None):
        sync_stats = sync_stats or self._compute_sync_window_stats(layer_key)
        domain = self._selected_sync_conversation_domain() + [
            ('updated_at_fm', '>=', sync_stats['window_start_str']),
            ('updated_at_fm', '<=', sync_stats['window_end_str']),
        ]
        conversations = self.search(
            domain,
            order='last_message_sync_fm asc nulls first, updated_at_fm desc, id desc',
            limit=limit,
        )
        return conversations, sync_stats

    @api.model
    def _refresh_windowed_conversation_candidates(self, layer_key, sync_stats=None):
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            return {
                'has_token': False,
                'page_count': 0,
                'conversation_count': 0,
                'error_count': 1,
            }
        sync_stats = sync_stats or self._compute_sync_window_stats(layer_key)
        stats = self.env['page.fm.page'].sudo().sync_selected_page_conversation_candidates(
            main_access_token,
            since_timestamp=sync_stats['window_start_epoch'],
            until_timestamp=sync_stats['window_end_epoch'],
            order_by='updated_at',
        )
        stats['has_token'] = True
        return stats

    @api.model
    def _is_transient_sync_exception(self, exc):
        """Best-effort classifier for retryable sync failures."""
        if isinstance(exc, requests.exceptions.RequestException):
            return True
        message = str(exc or '').lower()
        transient_markers = (
            'could not serialize access due to concurrent update',
            'deadlock detected',
            'connection reset',
            'connection aborted',
            'temporarily unavailable',
            'timed out',
            'timeout',
            'name resolution',
            'failed to resolve',
            'max retries exceeded',
            'temporary failure in name resolution',
        )
        return any(marker in message for marker in transient_markers)

    @api.model
    def _sync_conversation_with_transient_retry(
        self,
        conversation,
        sync_stats,
        sync_origin,
        sync_window_key,
        skip_cursor_commit=False,
    ):
        """Sync one conversation with retry/backoff for transient failures."""
        max_retries = max(int(self._SYNC_TRANSIENT_MAX_RETRIES or 0), 0)
        base_backoff = max(int(self._SYNC_TRANSIENT_BACKOFF_SECONDS or 1), 1)
        attempt = 0

        while True:
            try:
                result = conversation.action_sync_messages(
                    date_from=sync_stats['window_start'],
                    date_to=sync_stats['window_end'],
                    return_stats=True,
                    sync_origin=sync_origin,
                    sync_window_key=sync_window_key,
                )
                if not skip_cursor_commit:
                    self.env.cr.commit()
                return result
            except Exception as exc:
                if not skip_cursor_commit:
                    self.env.cr.rollback()
                is_transient = self._is_transient_sync_exception(exc)
                if attempt >= max_retries or not is_transient:
                    raise
                attempt += 1
                wait_seconds = base_backoff * (2 ** (attempt - 1))
                _logger.warning(
                    "Retrying conversation sync %s after transient error (attempt %s/%s, wait=%ss): %s",
                    conversation.id,
                    attempt,
                    max_retries,
                    wait_seconds,
                    exc,
                )
                time.sleep(wait_seconds)

    @api.model
    def _run_windowed_message_sync(self, layer_key, limit=None, sync_stats=None, source_type='continuous', sync_origin='continuous', record_layer_stats=True):
        sync_stats = sync_stats or self._compute_sync_window_stats(layer_key)
        skip_cursor_commit = bool(self.env.context.get('skip_cursor_commit'))
        candidate_stats = self._refresh_windowed_conversation_candidates(layer_key, sync_stats=sync_stats)
        if not candidate_stats.get('has_token'):
            if record_layer_stats:
                self._record_continuous_layer_stats(
                    layer_key,
                    conversations_checked=0,
                    messages_created=0,
                    error_count=candidate_stats.get('error_count', 1),
                )
            self._create_continuous_log(
                layer_key,
                'error',
                'Không thể chạy đồng bộ liên tục vì thiếu hoặc lỗi main access token.',
                event_code='continuous_missing_token',
                stats=candidate_stats,
                source_type=source_type,
            )
            return {
                'candidate_stats': candidate_stats,
                'checked_count': 0,
                'messages_created': 0,
                'messages_existing': 0,
                'messages_fetched': 0,
                'error_count': candidate_stats.get('error_count', 1),
            }
        conversations, sync_stats = self._get_windowed_conversation_candidates(layer_key, limit=limit, sync_stats=sync_stats)

        created_total = 0
        existing_total = 0
        fetched_total = 0
        error_count = int(candidate_stats.get('error_count') or 0)
        checked_count = 0

        for conversation in conversations:
            try:
                result = self._sync_conversation_with_transient_retry(
                    conversation,
                    sync_stats=sync_stats,
                    sync_origin=sync_origin,
                    sync_window_key=layer_key,
                    skip_cursor_commit=skip_cursor_commit,
                )
                checked_count += 1
                if result.get('status') == 'ok':
                    created_total += int(result.get('created_messages') or 0)
                    existing_total += int(result.get('existing_messages') or 0)
                    fetched_total += int(result.get('fetched_messages') or 0)
                else:
                    error_count += 1
            except Exception as exc:
                error_count += 1
                _logger.error(
                    "Windowed message sync error for conversation %s (%s): %s",
                    conversation.id,
                    layer_key,
                    exc,
                    exc_info=True,
                )
                if not skip_cursor_commit:
                    self.env.cr.rollback()
                self._create_continuous_log(
                    layer_key,
                    'error',
                    "Lỗi đồng bộ conversation `%s`: %s" % (
                        conversation.display_name or conversation.id,
                        exc,
                    ),
                    event_code='continuous_conversation_sync_error',
                    page_id=conversation.page_fm_page_id.id,
                    conversation_id=conversation.id,
                    source_type=source_type,
                )

        if record_layer_stats:
            self._record_continuous_layer_stats(
                layer_key,
                conversations_checked=checked_count,
                messages_created=created_total,
                error_count=error_count,
            )
        self._create_continuous_log(
            layer_key,
            'success' if not error_count else 'warning',
            "Hoàn tất `%s`: %s hội thoại, %s tin đọc, %s tin mới, %s tin trùng, %s lỗi." % (
                layer_key,
                checked_count,
                fetched_total,
                created_total,
                existing_total,
                error_count,
            ),
            event_code='manual_window_summary' if source_type == 'manual_window' else 'continuous_layer_summary',
            stats={
                'conversations_checked': checked_count,
                'messages_fetched': fetched_total,
                'messages_created': created_total,
                'messages_existing': existing_total,
                'error_count': error_count,
                'window_start': sync_stats['window_start_str'],
                'window_end': sync_stats['window_end_str'],
            },
            source_type=source_type,
        )
        return {
            'candidate_stats': candidate_stats,
            'checked_count': checked_count,
            'messages_created': created_total,
            'messages_existing': existing_total,
            'messages_fetched': fetched_total,
            'error_count': error_count,
        }
        
    # === BATCH & CRON SYNC =================================================
        
    @api.model
    def cron_smart_message_sync(self, batch_limit=50):
        """Same-day safety sweep cho tin nhắn trong ngày."""
        if self._manual_full_sync_is_running():
            _logger.info("Bỏ qua quét tin nhắn trong ngày vì đang có job đồng bộ toàn bộ thủ công.")
            return False

        limit = batch_limit or self._get_continuous_batch_limit()
        sync_result = self._run_windowed_message_sync('same_day', limit=limit)
        _logger.info(
            "✅ Same-day sweep complete: checked=%s created=%s errors=%s",
            sync_result['checked_count'],
            sync_result['messages_created'],
            sync_result['error_count'],
        )
        return True

    @api.model
    def action_run_same_day_manual_window_sync(self, batch_limit=None):
        if self._manual_full_sync_is_running():
            raise UserError(_('Không thể quét lại trong ngày khi đang có job đồng bộ toàn bộ.'))
        limit = batch_limit or self._get_continuous_batch_limit()
        return self._run_windowed_message_sync(
            'manual_same_day',
            limit=limit,
            sync_stats=self._compute_sync_window_stats('same_day'),
            source_type='manual_window',
            sync_origin='manual_window',
            record_layer_stats=False,
        )

    @api.model
    def action_run_recent_72h_manual_window_sync(self):
        if self._manual_full_sync_is_running():
            raise UserError(_('Không thể quét lại 72 giờ gần nhất khi đang có job đồng bộ toàn bộ.'))
        return self._run_windowed_message_sync(
            'manual_recent_72h',
            limit=None,
            sync_stats=self._compute_recent_hours_window_stats(72),
            source_type='manual_window',
            sync_origin='manual_window',
            record_layer_stats=False,
        )
    
    def _perform_sync_batch_smart(self, conversations, priority_label):
        """Helper method for smart sync with priority tracking"""
        _logger.info(f"🔄 [{priority_label}] Starting sync for {len(conversations)} conversations")
        
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return
        
        synced_count = 0
        error_count = 0
        
        for conv in conversations:
            try:
                page = conv.page_fm_page_id
                if not page:
                    error_count += 1
                    continue
                
                page_token = page._generate_page_specific_access_token(main_access_token)
                if not page_token:
                    error_count += 1
                    continue
                
                # Sync messages
                conv.action_sync_messages()
                synced_count += 1
                
                # Auto-detect require_processing từ tags sau khi sync
                conv._auto_detect_require_processing_from_tags()
                
                self.env.cr.commit()
                
                # Rate limiting
                import time
                time.sleep(0.5)
                
            except Exception as e:
                _logger.error(f"[{priority_label}] Error syncing conversation {conv.id}: {e}")
                error_count += 1
                self.env.cr.rollback()
        
        #_logger.info(f"✅ [{priority_label}] Finished: {synced_count} success, {error_count} errors")
    
    # --- Helper: con trỏ tiến độ ---
    def _get_conv_pointer(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('pancake.last_conv_id', '0') or 0)

    def _set_conv_pointer(self, value):
        self.env['ir.config_parameter'].sudo().set_param('pancake.last_conv_id', str(int(value or 0)))

    def _reset_conv_pointer(self):
        """Reset con trỏ về 0 để bắt đầu đồng bộ lại từ đầu"""
        self._set_conv_pointer(0)
        _logger.info("Reset con trỏ đồng bộ conversation về 0")
        return True

    def _get_batch_size(self, batch_size=None):
        ICP = self.env['ir.config_parameter'].sudo()
        default_size = int(ICP.get_param('pancake.sync_batch_size', '50'))  # 50 mặc định
        return int(batch_size or default_size or 50)

    def _get_recent_activity_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(ICP.get_param('pancake.smart_sync_recent_days', '3') or 3), 1)
        except (TypeError, ValueError):
            return 3

    def _get_deep_sync_recent_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(ICP.get_param('pancake.deep_sync_recent_days', '7') or 7), 1)
        except (TypeError, ValueError):
            return 7

    def _get_circuit_breaker_pause_minutes(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(ICP.get_param('pancake.circuit_breaker_pause_minutes', '15') or 15), 1)
        except (TypeError, ValueError):
            return 15

    def _get_stale_timeout_minutes(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(ICP.get_param('pancake.bulk_sync_stale_timeout_minutes', '10') or 10), 1)
        except (TypeError, ValueError):
            return 10

    @api.model
    def cron_sync_conversations_batch(self, batch_size=None):
        """Đồng bộ theo batch với cơ chế reset con trỏ:
        - Pha 1: các conv mới (id > last_id) theo thứ tự tăng
        - Nếu không có conv mới → Reset con trỏ về 0 và bắt đầu lại từ đầu
        - Pha 2: phần còn lại dành cho conv cần xử lý / chưa đọc (không ảnh hưởng con trỏ)
        - Sau mỗi conv mới thành công → cập nhật con trỏ
        - Log ID cuối cùng đã đồng bộ
        """
        if self._manual_full_sync_is_running():
            _logger.info("Bỏ qua continuous deep sync theo batch vì đang có job đồng bộ toàn bộ thủ công.")
            return False

        size = self._get_batch_size(batch_size)
        last_id = self._get_conv_pointer()
        processed = 0
        last_processed_id = last_id
        selected_domain = self._selected_sync_conversation_domain()

        # --- PHA 1: conv mới theo con trỏ, id tăng dần ---
        new_convs = self.search(selected_domain + [('id', '>', last_id)], order="id asc", limit=size)
        
        # *** FIX: Nếu không có conversation mới, reset con trỏ về 0 ***
        if not new_convs and last_id > 0:
            _logger.info(f"Pancake Sync: Đã đồng bộ hết conversations (pointer={last_id}). Reset về 0 để bắt đầu lại.")
            self._set_conv_pointer(0)
            last_id = 0
            last_processed_id = 0
            # Lấy lại conversations từ đầu
            new_convs = self.search(selected_domain + [('id', '>', 0)], order="id asc", limit=size)

        # --- PHA 2: nếu còn quota, lấy conv cũ nhưng cần xử lý/chưa đọc ---
        remainder = size - len(new_convs)
        extra_convs = self.browse()
        if remainder > 0:
            extra_domain = selected_domain + [
                ('id', '<=', last_id),
                '|', ('require_processing', '=', True),
                    ('is_unread_fm', '=', True),
            ]
            extra_convs = self.search(
                extra_domain,
                order="last_message_sync_fm asc, updated_at_fm desc, id asc",
                limit=remainder,
            )

        # Gộp thứ tự: mới trước, rồi extra
        convs = new_convs | extra_convs
        if not convs:
            _logger.info("Pancake Sync: không có hội thoại nào cần đồng bộ. (pointer=%s)", last_id)
            return 0

        # Chạy đồng bộ
        for conv in convs:
            try:
                conv.action_sync_messages()
                self.env.cr.commit()
                processed += 1

                # Nếu đây là conv mới (id > last_id), cập nhật con trỏ dần lên
                if conv.id > last_processed_id:
                    last_processed_id = conv.id
                    self._set_conv_pointer(last_processed_id)
            except Exception:
                _logger.exception("Pancake Sync: lỗi khi sync hội thoại id=%s", conv.id)
                self.env.cr.rollback()

        _logger.info(
            "Pancake Sync: đã sync %s/%s hội thoại (pointer %s → %s). "
            "ID cuối cùng đã đồng bộ: %s",
            processed, len(convs), last_id, last_processed_id, last_processed_id
        )
        return processed

    @api.model
    def cron_sync_conversations_batch_with_circuit_breaker(self, batch_size=None):
        """Nightly safety sweep cho 2 ngày gần nhất với circuit breaker."""
        if self._manual_full_sync_is_running():
            _logger.info("Bỏ qua quét cuối ngày 2 ngày gần nhất vì đang có job đồng bộ toàn bộ thủ công.")
            return False

        circuit_key = 'page_fm_circuit_breaker_until'
        circuit_until = self.env['ir.config_parameter'].sudo().get_param(circuit_key)
        if circuit_until:
            circuit_datetime = datetime.fromisoformat(circuit_until)
            if datetime.now() < circuit_datetime:
                remaining = (circuit_datetime - datetime.now()).seconds // 60
                _logger.info(f"Circuit breaker active - còn {remaining} phút")
                self._create_continuous_log(
                    'nightly_two_day',
                    'warning',
                    "Bỏ qua quét cuối ngày vì circuit breaker còn hiệu lực %s phút." % remaining,
                    event_code='continuous_circuit_breaker_active',
                )
                return 0

        self.env['ir.config_parameter'].sudo().set_param(circuit_key, '')
        circuit_breaker_pause_minutes = self._get_circuit_breaker_pause_minutes()
        sync_result = self._run_windowed_message_sync('nightly_two_day', limit=None)
        final_message = (
            f"Nightly two-day sweep completed: checked={sync_result['checked_count']}, "
            f"created={sync_result['messages_created']}, errors={sync_result['error_count']}"
        )

        if sync_result['error_count'] >= 3:
            circuit_until = (datetime.now() + timedelta(minutes=circuit_breaker_pause_minutes)).isoformat()
            self.env['ir.config_parameter'].sudo().set_param(circuit_key, circuit_until)
            final_message += f" - CIRCUIT BREAKER ACTIVE ({circuit_breaker_pause_minutes} min pause)"
            self._create_continuous_log(
                'nightly_two_day',
                'warning',
                "Kích hoạt circuit breaker sau nightly sweep vì có %s lỗi liên tiếp. Tạm dừng %s phút." % (
                    sync_result['error_count'],
                    circuit_breaker_pause_minutes,
                ),
                event_code='continuous_circuit_breaker_triggered',
                stats=sync_result,
            )
        
        _logger.info(final_message)
        return sync_result['checked_count']


       # --- NEW: helper hiển thị thông báo ---
    def _notify(self, title, message, notif_type='warning'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }

    # --- NEW: mở form khách hàng ---
    def action_open_partner(self):
        self.ensure_one()
        if not self.partner_id:
            return self._notify(_('Chưa có khách hàng'), _('Hội thoại này chưa liên kết khách hàng.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Khách hàng'),
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.partner_id.id,
            'target': 'current',
        }

    def action_open_create_order_wizard(self):
        """Mở wizard tạo đơn với hội thoại này được chọn sẵn."""
        self.ensure_one()
        # sudo: wizard cần đọc tất cả conversation, caller có thể chỉ có quyền sale
        wizard = self.env['dac.create.order.wizard'].sudo().create({
            'order_type': 'pancake',
            'selected_conversation_id': self.id,
        })
        if self.id not in wizard.conversation_ids.ids:
            wizard.conversation_ids = [(4, self.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tạo đơn hàng',
            'res_model': 'dac.create.order.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    partner_order_count = fields.Integer(
        string='Số đơn hàng',
        compute='_compute_partner_order_count',
        store=False,
    )

    def _compute_partner_order_count(self):
        partner_ids = [r.partner_id.id for r in self if r.partner_id]
        counts = {}
        if partner_ids:
            result = self.env['sale.order'].read_group(
                [('partner_id', 'in', partner_ids)],
                ['partner_id'], ['partner_id'],
            )
            counts = {r['partner_id'][0]: r['partner_id_count'] for r in result}
        for rec in self:
            rec.partner_order_count = counts.get(rec.partner_id.id, 0) if rec.partner_id else 0

    def action_view_partner_sale_orders(self):
        """Mở danh sách đơn hàng của partner liên kết với conversation này."""
        self.ensure_one()
        if not self.partner_id or not self.partner_order_count:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': f'Đơn hàng — {self.partner_id.name}',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.partner_id.id)],
            'target': 'new',
        }

    def action_select_as_ai_wizard_partner(self):
        """Chọn conversation này làm khách hàng trong wizard tạo đơn từ ảnh."""
        self.ensure_one()
        wizard_id = self.env.context.get('active_wizard_id')
        if not wizard_id:
            return
        wizard = self.env['gemini.create.partner.wizard'].sudo().browse(wizard_id)
        if wizard.exists():
            vals = {'create_partner': False}
            if self.partner_id:
                vals['partner_id'] = self.partner_id.id
            else:
                # Conversation chưa link partner — prefill tên để tạo mới
                vals['partner_name'] = self.customer_name_fm or wizard.partner_name
                vals['partner_phone'] = self.phone or wizard.partner_phone
                vals['create_partner'] = True
            wizard.write(vals)
        return wizard.sudo()._reload_wizard_action()

    def action_open_invoice_upload_new_order(self):
        """Mở dialog upload hoá đơn ảnh để tạo đơn hàng mới (không cần orderId)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'sale_ai_invoice_reader.open_upload_dialog',
            'params': {},
        }

    # --- NEW: mở danh sách đơn hàng của khách (bao gồm cả công ty mẹ) ---
    def action_open_partner_orders(self):
        self.ensure_one()
        if not self.partner_id:
            return self._notify(_('Chưa có khách hàng'), _('Hội thoại này chưa liên kết khách hàng.'))
        commercial = self.partner_id.commercial_partner_id
        domain = [('partner_id', 'child_of', commercial.id)]
        count = self.env['sale.order'].search_count(domain)
        if not count:
            return self._notify(_('Chưa có đơn hàng'), _('Khách hàng này chưa có đơn hàng nào trên hệ thống.'))
        action = self.env.ref('dac_erp.dac_sale_order_custom_action').read()[0]
        action['domain'] = domain
        action['context'] = {'search_default_customer': commercial.id}
        return action

    def action_quick_view_messages(self):
        """Mở form hội thoại dạng dialog — dùng cho nút Xem chi tiết trong wizard tạo đơn."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.customer_name_fm or self.display_name,
            'res_model': 'page.fm.conversation',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_order_from_wizard(self):
        """Tạo đơn hàng từ nút Tạo đơn trên mỗi dòng hội thoại trong wizard."""
        self.ensure_one()
        ctx = {'default_conversation_id': self.id}
        if self.partner_id:
            ctx['default_partner_id'] = self.partner_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo đơn hàng'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'context': ctx,
            'target': 'current',
        }

    def action_open_create_order_wizard(self):
        """Mở wizard tạo đơn — dùng cho stat button trên form hội thoại."""
        self.ensure_one()
        # sudo: wizard cần đọc tất cả conversation, caller có thể chỉ có quyền sale
        wizard = self.env['dac.create.order.wizard'].sudo().create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo đơn hàng'),
            'res_model': 'dac.create.order.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }


    # Dành cho người phụ trách
    owner_id = fields.Many2one(
        'res.users', string="Người phụ trách", index=True, copy=False, tracking=True
    )
    participant_user_ids = fields.Many2many(
        'res.users',
        'page_fm_conv_user_rel', 'conv_id', 'user_id',
        string="Nhóm phụ trách", copy=False, tracking=True
    )

    def _recompute_staff_links(self):
        """
        DEPRECATED: Không còn dùng nữa.
        Staff được gán trực tiếp từ conversation API (current_assign_users),
        chính xác hơn việc suy luận từ tin nhắn.
        """
        return
        # Legacy code - giữ lại để tham khảo
        # Message = self.env['page.fm.message'].sudo()
        # Users   = self.env['res.users'].sudo()

        # for rec in self:
        #     need_owner        = not rec.owner_id
        #     need_participants = not rec.participant_user_ids

        #     # nếu cả 2 đều đã có -> bỏ qua
        #     if not (need_owner or need_participants):
        #         continue

        #     # lấy tin có staff mới nhất (để đề xuất owner)
        #     last_staff_msg = False
        #     if need_owner:
        #         last_staff_msg = Message.search(
        #             [('conversation_id', '=', rec.id), ('staff', '!=', False)],
        #             order='inserted_at_fm desc, id desc', limit=1
        #         )

        #     # lấy full danh sách staff đã từng nhắn (để làm participants)
        #     candidates = Users.browse()
        #     if need_participants:
        #         rows = Message.read_group(
        #             [('conversation_id', '=', rec.id), ('staff', '!=', False)],
        #             ['staff'], ['staff']
        #         )
        #         if rows:
        #             # rows[i]['staff'] = [id, display_name]
        #             candidates = Users.browse([r['staff'][0] for r in rows if r.get('staff')])

        #     vals = {}
        #     if need_owner and last_staff_msg and last_staff_msg.staff:
        #         vals['owner_id'] = last_staff_msg.staff.id

        #     if need_participants and candidates:
        #         vals['participant_user_ids'] = [(6, 0, candidates.ids)]

        #     if vals:
        #         rec.write(vals)

    def action_assign_to_me(self):
        for rec in self:
            rec.owner_id = self.env.user.id
        return True
    
    
            
    # Cho cuộc trò chuyện nội bộ
    is_internal_conversation = fields.Boolean(
        string="Cuộc trò chuyện nội bộ",
        default=False,
        tracking=True,
        help="Đánh dấu cuộc trò chuyện này là nội bộ, không hiển thị với nhân viên bán hàng."
    )
    
    
    # Mốc hoạt động cuối
    last_update_at = fields.Datetime(
        string="Cập nhật lần cuối",
        compute="_compute_last_update_at",
        store=True,
        index=True,
        help="Mốc cập nhật gần nhất: mọi thay đổi trên form, sync/POST n8n, đổi trạng thái, ghi chú,..."
    )

    @api.depends(
        'updated_at_fm',          # từ API
        'last_message_sync_fm',   # lần sync gần nhất
        'last_suggestion_at',     # n8n/AI/ghi chú
        'status_set_at',          # đổi trạng thái
        'updated_at_fm_by_hand',  # cập nhật thủ công
    )
    def _compute_last_update_at(self):
        for r in self:
            candidates = [
                r.updated_at_fm,
                r.last_message_sync_fm,
                r.last_suggestion_at,
                r.status_set_at,
                r.updated_at_fm_by_hand,
            ]
            r.last_update_at = max([c for c in candidates if c]) if any(candidates) else False
            
            
    @api.onchange('owner_id')
    def _onchange_owner_push_to_participants(self):
        """Khi người dùng chọn/chỉnh owner trên form:
        - Không đụng gì khác
        - Chỉ đảm bảo owner có mặt trong participant_user_ids
        """
        for rec in self:
            if rec.owner_id and rec.owner_id not in rec.participant_user_ids:
                rec.participant_user_ids |= rec.owner_id

    # === Methods for view buttons ===
    
    def action_debug_sync_assignees(self):
        """
        DEBUG: Force sync conversation và log chi tiết quá trình gán assigned users
        """
        self.ensure_one()
        if not self.conversation_fm_id or not self.page_fm_page_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Missing conversation or page info'),
                    'type': 'danger'
                }
            }
        
        try:
            # 🔍 BƯỚC 0: KIỂM TRA TẤT CẢ USER TRONG HỆ THỐNG
            ResUsers = self.env['res.users'].sudo()
            all_users = ResUsers.search([])
            
            _logger.info("=" * 80)
            _logger.info("🔍 ANALYZING ALL USERS IN SYSTEM - PANCAKE ID FORMATS")
            _logger.info("=" * 80)
            
            users_with_pancake_id = all_users.filtered(lambda u: u.pancake_id)
            users_with_pancake_uuid = all_users.filtered(lambda u: u.pancake_uuid)
            users_with_pancake_number_id = all_users.filtered(lambda u: u.pancake_number_id)
            
            _logger.info(f"\n📊 SUMMARY:")
            _logger.info(f"   - Total users: {len(all_users)}")
            _logger.info(f"   - Users with pancake_id: {len(users_with_pancake_id)}")
            _logger.info(f"   - Users with pancake_uuid: {len(users_with_pancake_uuid)}")
            _logger.info(f"   - Users with pancake_number_id: {len(users_with_pancake_number_id)}")
            
            _logger.info(f"\n📋 DETAILED USER LIST:")
            for user in all_users:
                if user.pancake_id or user.pancake_uuid or user.pancake_number_id:
                    _logger.info(f"\n   User: {user.name} (ID: {user.id}, Login: {user.login})")
                    if user.pancake_id:
                        _logger.info(f"      ✅ pancake_id: {user.pancake_id}")
                        _logger.info(f"         - Length: {len(user.pancake_id)}")
                        _logger.info(f"         - Format: {'UUID' if '-' in user.pancake_id else 'NUMBER' if user.pancake_id.isdigit() else 'OTHER'}")
                    if user.pancake_uuid:
                        _logger.info(f"      ✅ pancake_uuid: {user.pancake_uuid}")
                        _logger.info(f"         - Length: {len(user.pancake_uuid)}")
                    if user.pancake_number_id:
                        _logger.info(f"      ✅ pancake_number_id: {user.pancake_number_id}")
                        _logger.info(f"         - Length: {len(user.pancake_number_id)}")
                    if user.email:
                        _logger.info(f"      📧 Email: {user.email}")
            
            _logger.info("\n" + "=" * 80)
            
            # 1. Lấy token
            main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
            if not main_access_token:
                raise Exception("Missing main access token")
            
            page = self.page_fm_page_id
            page_token = page._generate_page_specific_access_token(main_access_token)
            if not page_token:
                raise Exception("Cannot generate page token")
            
            # 2. Fetch conversation từ API
            import requests
            api_url = f"https://pages.fm/api/public_api/v2/pages/{page.page_fm_id_str}/conversations"
            params = {
                'page_access_token': page_token,
                'page_id': page.page_fm_id_str
            }
            
            _logger.info("=" * 80)
            _logger.info(f"🔍 DEBUG SYNC ASSIGNEES - Conversation: {self.name} (ID: {self.conversation_fm_id})")
            _logger.info("=" * 80)
            
            response = requests.get(api_url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            # Tìm conversation trong response
            conv_data = None
            for c in data.get('conversations', []):
                if c.get('id') == self.conversation_fm_id:
                    conv_data = c
                    break
            
            if not conv_data:
                raise Exception(f"Conversation {self.conversation_fm_id} not found in API response")
            
            # 3. Log toàn bộ conversation data
            import json
            _logger.info("📋 FULL CONVERSATION JSON:")
            _logger.info(json.dumps(conv_data, indent=2, ensure_ascii=False))
            
            # 4. Extract assignee data
            current_assign_users = conv_data.get('current_assign_users', []) or []
            _logger.info(f"\n👥 CURRENT_ASSIGN_USERS: {current_assign_users}")
            
            assignee_data = []
            if isinstance(current_assign_users, list):
                for user_obj in current_assign_users:
                    if isinstance(user_obj, dict):
                        user_id = user_obj.get('id')
                        email = user_obj.get('email')
                        name = user_obj.get('name')
                        if user_id or email:
                            assignee_data.append({
                                'id': user_id,
                                'email': email,
                                'name': name
                            })
            
            _logger.info(f"\n📦 EXTRACTED ASSIGNEE_DATA: {assignee_data}")
            
            # 5. Map to Odoo users - KIỂM TRA CẢ 3 FIELD
            mapped_users = []
            
            for idx, assignee in enumerate(assignee_data):
                pancake_id = assignee.get('id')
                email = assignee.get('email')
                name = assignee.get('name', 'Unknown')
                
                _logger.info(f"\n🔎 Searching user #{idx+1}:")
                _logger.info(f"   - Pancake ID from API: {pancake_id}")
                _logger.info(f"   - ID Length: {len(pancake_id) if pancake_id else 'N/A'}")
                _logger.info(f"   - ID Format: {'UUID' if pancake_id and '-' in pancake_id else 'NUMBER' if pancake_id and str(pancake_id).isdigit() else 'OTHER'}")
                _logger.info(f"   - Email: {email}")
                _logger.info(f"   - Name: {name}")
                
                user = None
                
                # Tìm theo pancake_id (KIỂM TRA CẢ 3 FIELD)
                if pancake_id:
                    _logger.info(f"\n   🔍 Searching by pancake_id in 3 fields...")
                    
                    # Test từng field riêng lẻ để log rõ ràng
                    test1 = ResUsers.search([('pancake_id', '=', pancake_id)], limit=1)
                    if test1:
                        _logger.info(f"      ✅ MATCH in field 'pancake_id': {test1.name} (stored value: {test1.pancake_id})")
                        user = test1
                    else:
                        _logger.info(f"      ❌ NO MATCH in field 'pancake_id'")
                    
                    if not user:
                        test2 = ResUsers.search([('pancake_uuid', '=', pancake_id)], limit=1)
                        if test2:
                            _logger.info(f"      ✅ MATCH in field 'pancake_uuid': {test2.name} (stored value: {test2.pancake_uuid})")
                            user = test2
                        else:
                            _logger.info(f"      ❌ NO MATCH in field 'pancake_uuid'")
                    
                    if not user:
                        test3 = ResUsers.search([('pancake_number_id', '=', pancake_id)], limit=1)
                        if test3:
                            _logger.info(f"      ✅ MATCH in field 'pancake_number_id': {test3.name} (stored value: {test3.pancake_number_id})")
                            user = test3
                        else:
                            _logger.info(f"      ❌ NO MATCH in field 'pancake_number_id'")
                    
                    if user:
                        _logger.info(f"\n   ✅ FINAL MATCH: {user.name} (ID: {user.id})")
                        _logger.info(f"      - User login: {user.login}")
                        _logger.info(f"      - User email: {user.email}")
                        _logger.info(f"      - pancake_id: {user.pancake_id}")
                        _logger.info(f"      - pancake_uuid: {user.pancake_uuid}")
                        _logger.info(f"      - pancake_number_id: {user.pancake_number_id}")
                
                # Tìm theo email
                if not user and email:
                    _logger.info(f"\n   🔍 Searching by email...")
                    user = ResUsers.search([('login', '=', email)], limit=1)
                    if not user:
                        user = ResUsers.search([('email', '=', email)], limit=1)
                    
                    if user:
                        _logger.info(f"   ✅ FOUND by email: {user.name} (ID: {user.id})")
                        _logger.info(f"      - User login: {user.login}")
                        _logger.info(f"      - pancake_id: {user.pancake_id}")
                        _logger.info(f"      - pancake_uuid: {user.pancake_uuid}")
                        _logger.info(f"      - pancake_number_id: {user.pancake_number_id}")
                
                if user:
                    mapped_users.append({
                        'user': user,
                        'index': idx,
                        'source_name': name,
                        'source_email': email,
                        'source_pancake_id': pancake_id
                    })
                else:
                    _logger.warning(f"   ❌ NOT FOUND: {name} (email: {email}, pancake_id: {pancake_id})")
            
            # 6. Log kết quả mapping
            #_logger.info(f"\n📊 MAPPING SUMMARY:")
            #_logger.info(f"   - Total assignees from API: {len(assignee_data)}")
            #_logger.info(f"   - Successfully mapped: {len(mapped_users)}")
            
            if mapped_users:
                owner = mapped_users[0]['user']
                all_users = [m['user'] for m in mapped_users]
                
                #_logger.info(f"\n👤 OWNER (first user): {owner.name} (ID: {owner.id})")
                #_logger.info(f"👥 PARTICIPANTS ({len(all_users)} users):")
                #for m in mapped_users:
                #    _logger.info(f"   - {m['user'].name} (ID: {m['user'].id}) from API: {m['source_name']}")
                
                # 7. Compare with current values
                #_logger.info(f"\n📋 CURRENT STATE:")
                #_logger.info(f"   - Current owner: {self.owner_id.name if self.owner_id else 'None'}")
                #_logger.info(f"   - Current participants: {[u.name for u in self.participant_user_ids]}")
                
                # 8. Update (MERGE mode)
                old_participant_ids = set(self.participant_user_ids.ids)
                new_user_ids = [u.id for u in all_users]
                merged_ids = old_participant_ids.union(set(new_user_ids))
                
                self.write({
                    'owner_id': owner.id,
                    'participant_user_ids': [(6, 0, list(merged_ids))]
                })
                
                #_logger.info(f"\n✅ UPDATED STATE:")
                #_logger.info(f"   - New owner: {self.owner_id.name}")
                #_logger.info(f"   - New participants ({len(self.participant_user_ids)} users): {[u.name for u in self.participant_user_ids]}")
                #_logger.info(f"   - Added: {len(merged_ids) - len(old_participant_ids)} users")
            
            #_logger.info("=" * 80)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Debug Complete'),
                    'message': _('Check server logs for detailed assignee mapping info. Found %d users in system, %d assignees from API, %d mapped successfully.') % (len(all_users), len(assignee_data), len(mapped_users)),
                    'type': 'success',
                    'sticky': True
                }
            }
            
        except Exception as e:
            #_logger.error(f"❌ DEBUG SYNC ERROR: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Debug Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True
                }
            }
    
    def action_refresh_conversation(self):
        """Refresh conversation data from Pages.fm"""
        for record in self:
            if record.conversation_fm_id:
                try:
                    # Sync lại conversation này từ API
                    self.env['page.fm.conversation'].with_context(
                        force_sync_conversation_id=record.conversation_fm_id
                    ).sync_all_conversations_scheduled()
                    # Show success message
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Success'),
                            'message': _('Conversation refreshed successfully'),
                            'type': 'success'
                        }
                    }
                except Exception as e:
                    _logger.error(f"Error refreshing conversation {record.conversation_fm_id}: {e}")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Error'),
                            'message': _('Error refreshing conversation: %s') % str(e),
                            'type': 'danger'
                        }
                    }

    def action_mark_as_read(self):
        """Mark conversation as read"""
        for record in self:
            record.write({'is_unread': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Conversation(s) marked as read'),
                'type': 'success'
            }
        }

    def action_mark_as_unread(self):
        """Mark conversation as unread"""
        for record in self:
            record.write({'is_unread': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Conversation(s) marked as unread'),
                'type': 'success'
            }
        }

    def action_sync_messages_button(self):
        """Nút sync tin nhắn cho form - có thông báo và reload FORM"""
        for record in self:
            try:
                _logger.info(f"Bắt đầu sync tin nhắn cho conversation {record.id} ({record.name})")
                result = record.action_sync_messages()
                
                # Đảm bảo dữ liệu được lưu
                self.env.cr.commit()
                _logger.info(f"Đồng bộ thành công tin nhắn cho conversation {record.conversation_fm_id}")
                
                # QUAN TRỌNG: Trả về action mở lại FORM hiện tại thay vì reload dashboard
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'page.fm.conversation',
                    'res_id': record.id,
                    'view_mode': 'form',
                    'view_type': 'form',
                    'target': 'current',  # Mở trong tab hiện tại
                    'context': self.env.context,
                }
            except Exception as e:
                _logger.error(f"Lỗi khi sync tin nhắn cho conversation {record.id}: {e}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification', 
                    'params': {
                        'title': 'Lỗi đồng bộ',
                        'message': f'Lỗi: {str(e)}',
                        'type': 'danger',
                        'sticky': True
                    }
                }

    def action_sync_tags_from_page(self):
        """Sync tags chỉ cho conversation này từ Page API"""
        self.ensure_one()
        
        if not self.page_fm_page_id:
            raise UserError("Conversation chưa liên kết với Page nào!")
        
        if not self.conversation_fm_id:
            raise UserError("Conversation không có ID từ Pancake!")
        
        # Fetch lại conversation này từ API để lấy tags mới nhất
        try:
            page = self.page_fm_page_id
            main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
            
            if not main_access_token:
                raise UserError("Thiếu cấu hình main_access_token!")
            
            # Fetch ALL conversations từ page (không có cách khác vì API không hỗ trợ lấy 1 conversation)
            _logger.info(f"🔍 Fetching conversations to find {self.conversation_fm_id}...")
            conversations = page._fetch_conversations_for_page_record(main_access_token)
            
            # Tìm conversation này trong kết quả
            conv_data = None
            for conv in conversations:
                if conv.get('conversation_fm_id') == self.conversation_fm_id:
                    conv_data = conv
                    break
            
            if not conv_data:
                raise UserError(f"Không tìm thấy conversation {self.conversation_fm_id} trong API response của page.")
            
            # Chỉ update conversation này thôi (không update toàn bộ)
            _logger.info(f"Found conversation, updating tags only...")
            page._create_or_update_conversations([conv_data])
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Tags',
                    'message': f'Đã đồng bộ tags cho "{self.customer_name_fm}"',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error(f"Error syncing tags: {e}", exc_info=True)
            raise UserError(f"Lỗi khi sync tags: {e}")

    def action_sync_all_conversations_force(self):
        """Force sync ALL conversations without any filters"""
        all_conversations = self.env['page.fm.conversation'].search(self._selected_sync_conversation_domain())
        
        if not all_conversations:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Data'),
                    'message': _('No conversations found in system!'),
                    'type': 'warning'
                }
            }
        
        _logger.info(f"FORCE SYNC: Starting sync for ALL {len(all_conversations)} conversations...")
        
        synced_count = 0
        error_count = 0
        
        for conv in all_conversations:
            try:
                customer_name = getattr(conv, 'customer_name_fm', None) or getattr(conv, 'name', None) or f"Conversation {conv.id}"
                
                # Get page info
                page = conv.page_fm_page_id
                if not page:
                    _logger.warning(f"Conversation {conv.id} ({customer_name}) không có page liên kết")
                    error_count += 1
                    continue
                
                try:
                    # Sync messages using existing method
                    result = conv.action_sync_messages()
                    message_count = conv.message_count
                    
                    _logger.info(f"✓ FORCE SYNC: {message_count} tin nhắn cho cuộc hội thoại: {customer_name}")
                    
                    conv.updated_at_fm_by_hand = datetime.now()
                    synced_count += 1
                    self.env.cr.commit()
                    
                except Exception as sync_error:
                    _logger.error(f"FORCE SYNC error for conversation {conv.id} ({customer_name}): {sync_error}")
                    error_count += 1
                    self.env.cr.rollback()
                    
            except Exception as e:
                customer_name = getattr(conv, 'customer_name_fm', None) or f"Conversation {conv.id}"
                _logger.error(f"FORCE SYNC outer error for conversation {conv.id} ({customer_name}): {e}")
                error_count += 1
                self.env.cr.rollback()
        
        _logger.info(f"FORCE SYNC finished: {synced_count} thành công, {error_count} lỗi từ tổng {len(all_conversations)} conversations.")
        
        # Sau khi sync xong, reload để hiển thị dữ liệu mới
        self.env.cr.commit()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_clear_token_cache(self):
        """Xóa token cache để giải quyết vấn đề timeout"""
        if hasattr(self, 'page_fm_page_id') and self.page_fm_page_id:
            self.page_fm_page_id.clear_token_cache()
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
        else:
            # Clear all cache
            self.env['page.fm.page'].clear_all_token_cache()
            return {
                'type': 'ir.actions.client', 
                'tag': 'reload',
            }

    @api.depends('conv_message_ids.inserted_at_fm')
    def _compute_last_message_at_fm(self):
        """
        Tính toán thời gian của tin nhắn cuối cùng (mới nhất)
        dựa trên 'inserted_at_fm' từ model page.fm.message.
        
        BẢN SỬA LỖI: Dùng ORM (mapped) thay vì read_group.
        Hàm này sẽ đọc từ cache, bao gồm cả các tin nhắn
        vừa được .create() trong CÙNG một transaction.
        """
        #_logger.info(f"Đang compute 'last_message_at_fm' cho {len(self.ids)} conversations (bằng ORM)...")
        for rec in self:
            # self.conv_message_ids sẽ bao gồm cả các tin nhắn
            # vừa được tạo trong transaction này (trong cache)
            if rec.conv_message_ids:
                try:
                    # Lấy tất cả thời gian, lọc bỏ False/None, rồi tìm max
                    all_times = [t for t in rec.conv_message_ids.mapped('inserted_at_fm') if t]
                    if all_times:
                        rec.last_message_at_fm = max(all_times)
                    else:
                        rec.last_message_at_fm = False
                except Exception as e:
                    _logger.error(f"Lỗi khi tính max time cho conv {rec.id}: {e}")
                    rec.last_message_at_fm = False
            else:
                # Không có tin nhắn
                rec.last_message_at_fm = False
