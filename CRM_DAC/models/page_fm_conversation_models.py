import requests
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from odoo import SUPERUSER_ID
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import time
import odoo

_logger = logging.getLogger(__name__)

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
    
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer (Partner)",
        # tracking=True,
        help="Liên kết với Customer trong hệ thống Odoo."
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
            
            # Xác định tag cần set - ưu tiên sử dụng odoo_tag_code
            if require_processing:
                # require_processing = True -> "Đang tư vấn"
                tag = self._get_tag_by_code('CONSULTING') or self._get_tag_by_code('PROCESSING')
                remove_tag = self._get_tag_by_code('DONE') or self._get_tag_by_code('COMPLETED')
                
                # Fallback sang tag mapping
                tag_name = tag.name if tag else "Đang tư vấn"
                remove_tag_name = remove_tag.name if remove_tag else "Done"
            else:
                # require_processing = False -> "Done"
                tag = self._get_tag_by_code('DONE') or self._get_tag_by_code('COMPLETED')
                remove_tag = self._get_tag_by_code('CONSULTING') or self._get_tag_by_code('PROCESSING')
                
                # Fallback sang tag mapping
                tag_name = tag.name if tag else "Done"
                remove_tag_name = remove_tag.name if remove_tag else "Đang tư vấn"

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
        for rec in self:
            if not rec.pancake_tag_ids:
                continue  # Không có tags → skip
            
            tag_names = [tag.name for tag in rec.pancake_tag_ids]
            
            # Tags yêu cầu xử lý
            processing_tags = ['Đang tư vấn', 'Chưa thu tiền', 'Đang thiết kế', 'Đang sản xuất']
            done_tags = ['Done', 'Fail']
            
            has_processing_tag = any(tag in tag_names for tag in processing_tags)
            has_done_tag = any(tag in tag_names for tag in done_tags)
            
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
                _logger.info(f"🏷️ Auto-detect require_processing={new_value} cho conversation {rec.id} từ tags: {tag_names}")
    
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
        for c in self:
            # Lấy tin nhắn cuối (ưu tiên inserted_at_fm)
            msg_order = 'inserted_at_fm desc, id desc' if 'inserted_at_fm' in Message._fields else 'id desc'
            last_msg = Message.search([('conversation_id', '=', c.id)], limit=1, order=msg_order)

            vals = {}

            # 1) Logic trạng thái
            if getattr(c, 'is_unread_fm', False):
                # Có tin chưa đọc -> 'Tin mới', cần xử lý
                vals.update({'status_state': 'new', 'require_processing': True})
            elif last_msg and (last_msg.sender_name_fm and not last_msg.staff_name_fm):
                # Tin cuối là của KH -> 'Chăm lại khách', cần xử lý
                vals.update({'status_state': 'recontact', 'require_processing': True})
            elif last_msg and last_msg.staff_name_fm:
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
        """
        Tries to find a phone number in messages, then finds or creates a partner
        based on that phone number.
        """
        self.ensure_one()
        if self.partner_id:
            return  # Already has a partner

        Partner = self.env['res.partner'].sudo()

        # 1) Ưu tiên tìm theo pancake_id (customer_fm_id)
        partner = Partner.search([('pancake_id', '=', self.customer_fm_id)], limit=1)

        # 2) Fallback nếu chưa có: thử phone/email + name
        if not partner:
            domain_fallback = []
            if self.phone and self.customer_name_fm:
                domain_fallback = [('phone', '=', self.phone), ('name', '=ilike', self.customer_name_fm)]
            # (tuỳ chọn) else thử theo email nếu có field chứa email…
            if domain_fallback:
                partner = Partner.search(domain_fallback, limit=1)
                if partner and not partner.pancake_id and self.customer_fm_id:
                    partner.write({'pancake_id': self.customer_fm_id})

        # 3) Nếu vẫn không có → tạo mới với pancake_id
        if not partner:
            partner = Partner.create({
                'name': self.customer_name_fm or f"Khách hàng {self.conversation_fm_id}",
                'pancake_id': self.customer_fm_id,
                'company_type': 'person',
                'company_id': False,
            })

        self.partner_id = partner
        


    def _fetch_message_batch(self, page_specific_access_token, current_offset=0, retry_count=0):
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
                
                should_continue = True
                all_msgs = data.get('messages', [])
                filtered_msgs = []

                # If we are not loading all, stop when we see the last saved message
                if self.last_message_id and not self.env.context.get('load_all', False):
                    for msg in all_msgs:
                        if msg.get('id') == self.last_message_id:
                            should_continue = False
                            break # Stop here, don't add this message or any older ones
                        filtered_msgs.append(msg)
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
                    return (False, [])
                    
            except requests.exceptions.RequestException as e:
                error_msg = str(e).lower()
                if 'rate limit' in error_msg or 'too many requests' in error_msg:
                    _logger.warning(f"Rate limit hit for {conv_fm_id} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Longer delay for rate limits
                        continue
                
                _logger.error(f"Request error fetching messages (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return (False, [])
                    
            except Exception as e:
                _logger.error(f"Unexpected error fetching messages (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt == max_retries - 1:
                    return (False, [])

        return (False, [])

    def _fetch_all_messages(self, page_specific_access_token):
        self.ensure_one()
        all_messages = []
        offset = 0
        batch_limit = 25

        while True:
            should_continue, batch = self._fetch_message_batch(page_specific_access_token, offset)
            if not batch:
                break
            
            all_messages.extend(batch)
            offset += len(batch)
            
            if not should_continue or len(batch) < batch_limit:
                break

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
        if 'unread_only' in kwargs and kwargs['unread_only'] is not None:
            unread_first = bool(kwargs['unread_only'])

        def _to_dt_any(v, is_end=False):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            s = str(v)
            # ISO 8601 (chấp nhận 'Z')
            try:
                return datetime.fromisoformat(s.replace('Z', '+00:00'))
            except Exception:
                pass
            # 'YYYY-MM-DD' hoặc 'YYYY-MM-DD HH:MM:SS'
            try:
                if len(s) == 10:
                    return fields.Datetime.to_datetime(s + (' 23:59:59' if is_end else ' 00:00:00'))
                return fields.Datetime.to_datetime(s)
            except Exception:
                return None

        dt_from = _to_dt_any(date_from, is_end=False)
        dt_to   = _to_dt_any(date_to,   is_end=True)
        
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return False
        
        for record in self:
            page_specific_access_token = record.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_specific_access_token:
                _logger.error(f"Không thể tạo token cho trang của hội thoại {record.conversation_fm_id}")
                continue

            # Fallback: dữ liệu cũ chưa có conv_page_fm_id thì gán bằng page_fm_id_str_related
            if not record.conv_page_fm_id and record.page_fm_id_str_related:
                record.write({'conv_page_fm_id': record.page_fm_id_str_related})

            messages = record._fetch_all_messages(page_specific_access_token)
            if not messages:
                record.write({'last_message_sync_fm': fields.Datetime.now()})
                _logger.info(f"Không có tin nhắn mới cho hội thoại {record.name}")
                continue

            _logger.info(f"Lấy được {len(messages)} tin nhắn từ API cho hội thoại {record.name}")

            Message = self.env['page.fm.message']
            

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
                    continue

                inserted_at_api = msg_data.get('inserted_at', datetime.now().isoformat())
                try:
                    dt_obj = datetime.fromisoformat(inserted_at_api.replace('Z', '+00:00'))
                    inserted_at = dt_obj.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
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
                        dt_obj = datetime.fromisoformat(previous_time_api.replace('Z', '+00:00'))
                        previous_time = dt_obj.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
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
                                url_content = attachments[0].get('video_data').get('url', '')

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
                }
                Message.create(values)
                
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

            record.write({'last_message_sync_fm': datetime.now()})
            record.invalidate_recordset(['message_count'])

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

        # Gọi hàm tính toán lại last_message_at_fm cho tất cả records đã sync
        try:
            # Gọi hàm compute một lần cho tất cả các records đã sync
            self._compute_last_message_at_fm()
        except Exception as e:
            _logger.error(f"Lỗi khi tính toán lại last_message_at_fm: {e}")

        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
        if any(k in vals for k in ('status_state', 'is_unread_fm')):
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
        
    # === BATCH & CRON SYNC =================================================
        
    @api.model
    def cron_smart_message_sync(self, batch_limit=50):
        """TIER 3: Smart message sync với priority mới (time-based metrics TRƯỚC require_processing)
        
        Thứ tự ưu tiên (từ cao xuống thấp):
        1. partner_id IS NULL → Conversations mới từ Pancake, chưa có khách hàng trong hệ thống
        2. last_message_at_fm > last_message_sync_fm → Có tin nhắn mới chưa sync
        3. last_update_at trong 3 ngày → Có hoạt động gần đây
        4. require_processing = True → Cờ xử lý thủ công (ưu tiên thấp nhất)
        
        Batch size: 50 conversations/lần (tương đương ~3 phút sync)
        """
        _logger.info("🎯 TIER 3: Starting Smart Message Sync (Priority-based)")
        
        from datetime import datetime, timedelta
        
        # Ngưỡng thời gian: 3 ngày
        three_days_ago = datetime.now() - timedelta(days=3)
        
        # === PRIORITY 1: Conversations MỚI (partner_id IS NULL) ===
        priority_1 = self.search([
            ('partner_id', '=', False),
            '|',
            ('last_message_sync_fm', '=', False),
            ('last_message_at_fm', '>', fields.Datetime.to_string(three_days_ago))
        ], limit=batch_limit, order='updated_at_fm desc')
        
        if priority_1:
            _logger.info(f"🆕 Priority 1: Syncing {len(priority_1)} NEW conversations (partner_id IS NULL)")
            self._perform_sync_batch_smart(priority_1, "P1-NEW")
            return True  # Xử lý xong batch này, lần sau tiếp tục
        
        # === PRIORITY 2: Có tin nhắn MỚI chưa sync ===
        # Điều kiện: last_message_at_fm > last_message_sync_fm (hoặc chưa sync bao giờ)
        priority_2 = self.search([
            ('partner_id', '!=', False),  # Đã có khách hàng
            '|',
            ('last_message_sync_fm', '=', False),  # Chưa sync bao giờ
            '&',
            ('last_message_at_fm', '!=', False),
            ('last_message_at_fm', '>', 'last_message_sync_fm')  # Tin nhắn mới hơn lần sync cuối
        ], limit=batch_limit, order='last_message_at_fm desc')
        
        if priority_2:
            _logger.info(f"💬 Priority 2: Syncing {len(priority_2)} conversations with NEW messages")
            self._perform_sync_batch_smart(priority_2, "P2-NEWMSG")
            return True
        
        # === PRIORITY 3: Hoạt động GẦN ĐÂY (last_update_at < 3 ngày) ===
        priority_3 = self.search([
            ('partner_id', '!=', False),
            ('last_update_at', '>=', fields.Datetime.to_string(three_days_ago)),
            '|',
            ('last_message_sync_fm', '=', False),
            ('last_message_sync_fm', '<', fields.Datetime.to_string(three_days_ago))
        ], limit=batch_limit, order='last_update_at desc')
        
        if priority_3:
            _logger.info(f"⏰ Priority 3: Syncing {len(priority_3)} conversations with RECENT activity")
            self._perform_sync_batch_smart(priority_3, "P3-RECENT")
            return True
        
        # === PRIORITY 4: Cờ require_processing (thủ công - ưu tiên THẤP NHẤT) ===
        priority_4 = self.search([
            ('require_processing', '=', True),
            ('partner_id', '!=', False),
            '|',
            ('last_message_sync_fm', '=', False),
            ('last_message_sync_fm', '<', fields.Datetime.to_string(three_days_ago))
        ], limit=batch_limit, order='last_processing_change_at desc')
        
        if priority_4:
            _logger.info(f"🚩 Priority 4: Syncing {len(priority_4)} conversations with MANUAL flag (require_processing)")
            self._perform_sync_batch_smart(priority_4, "P4-MANUAL")
            return True
        
        _logger.info("✅ TIER 3 Complete: No conversations to sync (all up-to-date)")
        return True
    
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

    @api.model
    def cron_sync_conversations_batch(self, batch_size=None):
        """Đồng bộ theo batch với cơ chế reset con trỏ:
        - Pha 1: các conv mới (id > last_id) theo thứ tự tăng
        - Nếu không có conv mới → Reset con trỏ về 0 và bắt đầu lại từ đầu
        - Pha 2: phần còn lại dành cho conv cần xử lý / chưa đọc (không ảnh hưởng con trỏ)
        - Sau mỗi conv mới thành công → cập nhật con trỏ
        - Log ID cuối cùng đã đồng bộ
        """
        size = self._get_batch_size(batch_size)
        last_id = self._get_conv_pointer()
        processed = 0
        last_processed_id = last_id

        # --- PHA 1: conv mới theo con trỏ, id tăng dần ---
        new_convs = self.search([('id', '>', last_id)], order="id asc", limit=size)
        
        # *** FIX: Nếu không có conversation mới, reset con trỏ về 0 ***
        if not new_convs and last_id > 0:
            _logger.info(f"Pancake Sync: Đã đồng bộ hết conversations (pointer={last_id}). Reset về 0 để bắt đầu lại.")
            self._set_conv_pointer(0)
            last_id = 0
            last_processed_id = 0
            # Lấy lại conversations từ đầu
            new_convs = self.search([('id', '>', 0)], order="id asc", limit=size)

        # --- PHA 2: nếu còn quota, lấy conv cũ nhưng cần xử lý/chưa đọc ---
        remainder = size - len(new_convs)
        extra_convs = self.browse()
        if remainder > 0:
            extra_domain = [
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
        """Cron sync với circuit breaker - xử lý lỗi token/timeout mạnh mẽ hơn
        
        Circuit Breaker Logic:
        - Nếu có > 3 lỗi liên tiếp → tạm dừng 15 phút
        - Nếu timeout/token error → clear cache và retry
        - Rate limiting: delay giữa các request
        
        Tối ưu sync:
        - Chỉ sync conversations có hoạt động trong 7 ngày gần đây
        - HOẶC conversations chưa đọc / cần xử lý (bất kể thời gian)
        - Skip conversations cũ không hoạt động để tiết kiệm tài nguyên
        """
        import time
        
        # Kiểm tra circuit breaker
        circuit_key = 'page_fm_circuit_breaker_until'
        circuit_until = self.env['ir.config_parameter'].sudo().get_param(circuit_key)
        
        if circuit_until:
            circuit_datetime = datetime.fromisoformat(circuit_until)
            if datetime.now() < circuit_datetime:
                remaining = (circuit_datetime - datetime.now()).seconds // 60
                _logger.info(f"Circuit breaker active - còn {remaining} phút")
                return 0
        
        # Reset circuit breaker
        self.env['ir.config_parameter'].sudo().set_param(circuit_key, '')
        
        size = self._get_batch_size(batch_size)
        last_id = self._get_conv_pointer()
        processed = 0
        error_count = 0
        consecutive_errors = 0
        last_processed_id = last_id

        # Cho phép batch size lên đến 50, chỉ giảm nếu quá lớn
        if size > 50:
            size = 50
            _logger.info("Giảm batch size xuống 50 để tránh rate limit")
        
        _logger.info(f"Pancake Circuit Breaker Sync: sẽ xử lý tối đa {size} conversations")

        # 🆕 Tính ngày 7 ngày trước
        seven_days_ago = datetime.now() - timedelta(days=7)
        seven_days_str = seven_days_ago.strftime('%Y-%m-%d %H:%M:%S')
        
        # 🆕 Domain filter: Chỉ sync conversations ACTIVE trong 7 ngày hoặc cần xử lý
        active_filter = [
            '|',  # OR
            '|',  # OR
            ('updated_at_fm', '>=', seven_days_str),  # Cập nhật trong 7 ngày
            ('is_unread_fm', '=', True),  # Hoặc chưa đọc
            ('require_processing', '=', True),  # Hoặc cần xử lý
        ]
        
        # Lấy conversations cần sync với filter
        new_convs_domain = [('id', '>', last_id)] + active_filter
        new_convs = self.search(new_convs_domain, order="id asc", limit=size)
        
        # Log số conversations bị skip
        total_new = self.search_count([('id', '>', last_id)])
        skipped = total_new - len(new_convs)
        if skipped > 0:
            _logger.info(f"⚡ Tối ưu: Skip {skipped} conversations cũ không hoạt động (>7 ngày, đã đọc, không cần xử lý)")
        
        # *** FIX: Nếu không có conversation mới, reset con trỏ về 0 ***
        if not new_convs and last_id > 0:
            _logger.info(f"Circuit Breaker Sync: Đã đồng bộ hết conversations (pointer={last_id}). Reset về 0 để bắt đầu lại.")
            self._set_conv_pointer(0)
            last_id = 0
            last_processed_id = 0
            # Lấy lại conversations từ đầu với active filter
            new_convs = self.search([('id', '>', 0)] + active_filter, order="id asc", limit=size)
        
        remainder = size - len(new_convs)
        extra_convs = self.browse()
        
        if remainder > 0:
            # Extra conversations: Ưu tiên chưa đọc/cần xử lý trong 7 ngày
            extra_domain = [
                ('id', '<=', last_id),
                '|', ('require_processing', '=', True),
                    ('is_unread_fm', '=', True),
            ] + active_filter
            extra_convs = self.search(extra_domain, order="last_message_sync_fm asc", limit=remainder)

        convs = new_convs | extra_convs
        if not convs:
            #_logger.info("Pancake Circuit Breaker Sync: không có hội thoại nào cần đồng bộ")
            return 0

        _logger.info(f"Pancake Circuit Breaker Sync: bắt đầu sync {len(convs)} conversations (active trong 7 ngày hoặc cần xử lý)")

        for i, conv in enumerate(convs):
            try:
                # Rate limiting: delay giữa các request - giảm delay cho batch size lớn hơn
                if i > 0:
                    delay = 1.5 if len(convs) <= 50 else 2  # 1.5s cho ≤50, 2s cho >50
                    time.sleep(delay)
                
                # Sync conversation
                result = conv.action_sync_messages()
                
                if result:
                    self.env.cr.commit()
                    processed += 1
                    consecutive_errors = 0  # Reset consecutive error count
                    
                    # Cập nhật pointer cho conv mới
                    if conv.id > last_processed_id:
                        last_processed_id = conv.id
                        self._set_conv_pointer(last_processed_id)
                else:
                    _logger.warning(f"Sync failed for conversation {conv.id} - no result")
                    consecutive_errors += 1
                    
            except Exception as e:
                error_msg = str(e).lower()
                error_count += 1
                consecutive_errors += 1
                
                _logger.error(f"Circuit Breaker Sync: lỗi conversation {conv.id}: {e}")
                
                # Xử lý lỗi timeout/token đặc biệt
                if any(keyword in error_msg for keyword in ['timeout', 'token', 'rate limit', 'too many requests']):
                    _logger.warning(f"Detected timeout/token error - clearing token cache")
                    
                    # Clear token cache
                    try:
                        conv.page_fm_page_id.action_clear_token_cache()
                        time.sleep(5)  # Đợi 5 giây sau khi clear cache
                    except:
                        pass
                
                # Circuit breaker: nếu > 3 lỗi liên tiếp → dừng 15 phút
                if consecutive_errors >= 3:
                    circuit_until = (datetime.now() + timedelta(minutes=15)).isoformat()
                    self.env['ir.config_parameter'].sudo().set_param(circuit_key, circuit_until)
                    
                    _logger.error(f"Circuit breaker TRIGGERED after {consecutive_errors} consecutive errors - pausing for 15 minutes")
                    break
                
                # Rollback và tiếp tục với conversation tiếp theo
                self.env.cr.rollback()
                time.sleep(3)  # Delay lâu hơn sau lỗi

        # 🆕 Sync tags từ các pages liên quan (sau khi sync messages xong)
        if processed > 0:
            try:
                # Lấy danh sách các pages UNIQUE có conversations vừa sync
                unique_pages = convs.mapped('page_fm_page_id')
                if unique_pages:
                    _logger.info(f"🏷️ Syncing tags for {len(unique_pages)} unique pages after message sync...")
                    for page in unique_pages:
                        try:
                            page.action_sync_specific_pages_conversations()
                            _logger.info(f"Synced tags for page '{page.name}' (ID: {page.id})")
                            time.sleep(2)  # Rate limiting giữa các page
                        except Exception as e:
                            _logger.error(f"Failed to sync tags for page '{page.name}': {e}")
            except Exception as e:
                _logger.error(f"Error during tag sync in cron: {e}")
        
        final_message = (f"Circuit Breaker Sync completed: {processed}/{len(convs)} success, "
                        f"{error_count} errors, pointer: {last_id} → {last_processed_id}")
        
        if consecutive_errors >= 3:
            final_message += f" - CIRCUIT BREAKER ACTIVE (15 min pause)"
        
        _logger.info(final_message)
        return processed


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
        all_conversations = self.env['page.fm.conversation'].search([])
        
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