import requests
import json
import logging
from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1"
PAGES_FM_PUBLIC_API_V2_BASE_URL = "https://pages.fm/api/public_api/v2"
# Thêm URL cho API messages nếu khác, dựa trên JS của bạn là:
PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'


class PageFmPage(models.Model):
    _name = 'page.fm.page'
    _description = 'Page.fm Page'
    _order = 'name asc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Page Name", index=True)
    page_fm_id_str = fields.Char(string="Page.fm ID", index=True, required=False, copy=False)
    active = fields.Boolean(string="API Active", default=True, index=True, help="Trạng thái active từ API (dựa trên is_activated)")
    # 'active' của Odoo dùng cho archive/unarchive, trường này có thể đặt tên khác nếu muốn phân biệt rõ
    # Ví dụ: api_is_activated = fields.Boolean(string="API Is Activated")

    conversation_ids = fields.One2many('page.fm.conversation', 'page_fm_page_id', string="Conversations")
    conversation_count = fields.Integer(string="Conversation Count", compute='_compute_conversation_count', store=True)

    _sql_constraints = [
        ('page_fm_id_str_uniq', 'unique (page_fm_id_str)', 'Page.fm ID phải là duy nhất!')
    ]

    @api.depends('conversation_ids')
    def _compute_conversation_count(self):
        for record in self:
            record.conversation_count = len(record.conversation_ids)
    
    def action_view_conversations(self):
        self.ensure_one()
        # Tùy chọn: Kích hoạt đồng bộ hội thoại cho page này trước khi mở view
        # self.action_sync_conversations() 
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conversations for %s') % self.name,
            'res_model': 'page.fm.conversation',
            'view_mode': 'kanban,list,form',
            'domain': [('page_fm_page_id', '=', self.id)],
            'context': {
                'default_page_fm_page_id': self.id, 
                'default_page_fm_id_str_related': self.page_fm_id_str,
                'search_default_filter_unread': 1 
            }
        }
    
    def action_sync_specific_pages_conversations(self):
        # Hàm này có thể được gọi từ một server action trên nhiều page đã chọn
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token, không thể lấy hội thoại.")
            return False # Hoặc raise UserError

        for odoo_page in self: # self ở đây là recordset các page đã chọn
            _logger.info(f"Đang chuẩn bị đồng bộ hội thoại cho page: {odoo_page.name} (FM ID: {odoo_page.page_fm_id_str})")
            conversations_list = odoo_page._fetch_conversations_for_page_record(main_access_token)
            if conversations_list:
                odoo_page._create_or_update_conversations(conversations_list)
            else:
                _logger.info(f"Không có hội thoại nào được lấy hoặc có lỗi khi lấy hội thoại cho page {odoo_page.page_fm_id_str}")
        return True


    def _generate_page_specific_access_token(self, main_access_token, retry_count=0, max_retries=3):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        
        # CACHE TOKEN: Kiểm tra cache trước khi tạo mới
        cache_key = f"page_token_{page_fm_id}"
        cached_token = self.env['ir.config_parameter'].sudo().get_param(cache_key)
        
        # Kiểm tra cache validity (cache 20 giờ thay vì 24 để an toàn)
        cache_time_key = f"page_token_time_{page_fm_id}"
        cached_time = self.env['ir.config_parameter'].sudo().get_param(cache_time_key)
        
        if cached_token and cached_time:
            try:
                cached_datetime = datetime.fromisoformat(cached_time)
                # Giảm xuống 20 giờ để tránh token expire (Pages.fm có thể renew < 24h)
                if (datetime.now() - cached_datetime).total_seconds() < 72000:  # 20 giờ = 72000 giây
                    _logger.debug(f"Using cached token for page {page_fm_id} (age: {(datetime.now() - cached_datetime).total_seconds() / 3600:.1f}h)")
                    return cached_token
                else:
                    _logger.info(f"Cache token expired for page {page_fm_id}, generating new token")
            except:
                _logger.warning(f"Invalid cache time format for page {page_fm_id}, generating new token")
                pass  # Invalid cache time, proceed to generate new token
        
        generate_token_url = f"{PAGES_FM_API_V1_BASE_URL}/pages/{page_fm_id}/generate_page_access_token?access_token={main_access_token}&page_id={page_fm_id}"

        try:
            # Retry logic với exponential backoff
            import time
            if retry_count > 0:
                # Exponential backoff: 2^retry_count seconds
                wait_time = 2 ** retry_count
                _logger.info(f"Retry {retry_count}/{max_retries} after {wait_time}s for page {page_fm_id}")
                time.sleep(wait_time)
            
            _logger.info(f"Generating NEW page token for {page_fm_id}")
            response = requests.post(
                generate_token_url, 
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, 
                timeout=30  # Tăng từ 10s lên 30s
            )
            response.raise_for_status()
            data = response.json()
            if data.get('success') and data.get('page_access_token'):
                token = data['page_access_token']
                
                # CACHE TOKEN mới
                self.env['ir.config_parameter'].sudo().set_param(cache_key, token)
                self.env['ir.config_parameter'].sudo().set_param(cache_time_key, datetime.now().isoformat())
                _logger.info(f"✅ Generated and cached new token for page {page_fm_id}")
                
                if retry_count > 0:
                    _logger.info(f"Retry thành công cho page {page_fm_id} sau {retry_count} lần thử")
                return token
            
            error_msg = data.get('message', 'Unknown error')
            _logger.error(f"Failed to generate page token for {page_fm_id}: {error_msg}")
            
            # Nếu lỗi là token expired, xóa cache và retry
            if 'expired' in error_msg.lower() or 'invalid' in error_msg.lower():
                _logger.warning(f"Main access token might be expired, clearing cache")
                self.clear_token_cache()
                if retry_count < max_retries:
                    return self._generate_page_specific_access_token(main_access_token, retry_count + 1, max_retries)
            
            return None
            
        except (requests.exceptions.ConnectTimeout, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if retry_count < max_retries:
                _logger.warning(f"Network error for page {page_fm_id}, retry {retry_count + 1}/{max_retries}: {e}")
                return self._generate_page_specific_access_token(main_access_token, retry_count + 1, max_retries)
            else:
                _logger.error(f"Max retries exceeded for page {page_fm_id}: {e}")
                return None
                
        except Exception as e:
            _logger.error(f"Error generating page token for {page_fm_id}: {e}", exc_info=True)
            return None

    def clear_token_cache(self):
        """Xóa cache token của page này"""
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        cache_key = f"page_token_{page_fm_id}"
        cache_time_key = f"page_token_time_{page_fm_id}"
        
        self.env['ir.config_parameter'].sudo().set_param(cache_key, '')
        self.env['ir.config_parameter'].sudo().set_param(cache_time_key, '')
        _logger.info(f"Cleared token cache for page {page_fm_id}")

    @api.model
    def clear_all_token_cache(self):
        """Xóa tất cả cache token của toàn bộ pages"""
        params = self.env['ir.config_parameter'].sudo().search([
            '|',
            ('key', 'like', 'page_token_%'),
            ('key', 'like', 'page_token_time_%')
        ])
        params.unlink()
        _logger.info(f"Cleared {len(params)} token cache entries")

    def _fetch_conversations_for_page_record(self, main_access_token):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        odoo_page_id = self.id
        _logger.info(f"Fetching all conversations for Page Odoo ID: {odoo_page_id}, FM ID: {page_fm_id}")
        page_specific_access_token = self._generate_page_specific_access_token(main_access_token)
        if not page_specific_access_token:
            return []

        processed_conversations = []
        last_conversation_id = None
        fetch_limit = 25  # API always returns up to 25

        con = True
        while con:
            conversations_api_url = f"{PAGES_FM_PUBLIC_API_V2_BASE_URL}/pages/{page_fm_id}/conversations"
            params = {
                'page_access_token': page_specific_access_token,
                'page_id': page_fm_id
            }
            if last_conversation_id:
                params['last_conversation_id'] = last_conversation_id

            _logger.info(f"API Call: {conversations_api_url} - params: {params}")

            try:
                response = requests.get(
                    conversations_api_url,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    params=params,
                    timeout=20
                )
                msg = ""
                try:
                    # cố gắng đọc message nếu body là JSON
                    peek = response.json()
                    msg = (peek.get("message") or "").lower()
                except Exception:
                    pass

                if response.status_code in (401, 403) or \
                "access_token renewed" in msg or "expired" in msg or "invalid access_token" in msg:
                    # Token trang đã bị bên kia renew → xóa cache cũ và xin token mới rồi gọi lại 1 lần
                    self.clear_token_cache()
                    page_specific_access_token = self._generate_page_specific_access_token(main_access_token)
                    params['page_access_token'] = page_specific_access_token

                    response = requests.get(
                        conversations_api_url,
                        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                        params=params,
                        timeout=20
                    )
                
                response.raise_for_status()
                data = response.json()
                
                if not data.get('success'):
                    _logger.error(f"API fetch failed: {data.get('message')}")
                    break

                api_conversations = data.get('conversations', [])
                if not isinstance(api_conversations, list) or not api_conversations:
                    _logger.info("No more conversations to fetch.")
                    break

                # Chỉ log số lượng khi fetch nhiều, không log mỗi batch
                if fetch_limit > 1:
                    _logger.debug(f"Fetched {len(api_conversations)} conversations (last_id: {last_conversation_id})")
                else:
                    _logger.info(f"Fetched {len(api_conversations)} conversations (last_id: {last_conversation_id})")

                for conv_data in api_conversations:
                    if not isinstance(conv_data, dict) or not conv_data.get('id'):
                        _logger.warning(f"Skipping invalid data: {conv_data}")
                        continue
                    

                    platform = 'Không rõ'
                    from_id = conv_data.get('from', {}).get('id', '').lower()
                    page_id_api = conv_data.get('page_id', '').lower()

                    if from_id.startswith('pzl_') or page_id_api.startswith('pzl_'):
                        platform = 'Zalo'
                    elif from_id.startswith('fb_') or (page_id_api.isdigit() and not page_id_api.startswith('igo_')) or page_id_api.startswith('fb_'):
                        platform = 'Facebook'
                    elif from_id.startswith('igo_') or page_id_api.startswith('igo_'):
                        platform = 'Instagram'
                    elif conv_data.get('type') and conv_data.get('type') != 'INBOX':
                        platform = conv_data['type']

                    customer_id = conv_data.get('customer_id')
                    updated_at_str = conv_data.get('updated_at', datetime.now().isoformat())
                    try:
                        dt_object = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        updated_at_fmt = dt_object.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                        # Kiểm tra xem updated_at có trễ hơn 2 ngày không
                        # if datetime.now() - dt_object > timedelta(days=2):
                        #     con = False
                    except ValueError:
                        _logger.error(f"Cannot parse updated_at: {updated_at_str}")
                        updated_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)


                    is_unread = not conv_data.get('seen', False)

                    page_id_api = (conv_data.get('page_id') or '').strip()           # NEW
                    
                    # 🆕 Lấy tags từ API (nếu có)
                    # API trả về field 'tags' là array of objects: [None, {'id': 28, 'text': 'Khách lớn', ...}]
                    api_tags = conv_data.get('tags', []) or []
                    api_tag_ids = []
                    if isinstance(api_tags, list):
                        for tag_obj in api_tags:
                            if isinstance(tag_obj, dict) and tag_obj.get('id'):
                                api_tag_ids.append(tag_obj['id'])
                    
                    # 🆕 Lấy assigned users từ API
                    current_assign_users = conv_data.get('current_assign_users', []) or []
                    assignee_data = []  # List of {'id': UUID, 'email': ..., 'name': ...}
                    if isinstance(current_assign_users, list):
                        for user_obj in current_assign_users:
                            if isinstance(user_obj, dict):
                                user_id = user_obj.get('id')  # UUID từ Pancake
                                email = user_obj.get('email')
                                name = user_obj.get('name')
                                if user_id or email:  # Cần ít nhất 1 trong 2
                                    assignee_data.append({
                                        'id': user_id,
                                        'email': email,
                                        'name': name
                                    })
                    
                    processed_conv = {
                        'conversation_fm_id': conv_data.get('id'),
                        'page_fm_page_id': odoo_page_id,
                        'customer_fm_id': customer_id,
                        'customer_name_fm': conv_data.get('from', {}).get('name') or 'Khách ẩn danh',
                        'last_message_snippet': conv_data.get('snippet') or 'Không có tin nhắn',
                        'updated_at_fm': updated_at_fmt,
                        'is_unread_fm': is_unread,
                        'platform_fm': platform,
                        'conv_page_fm_id': page_id_api,
                        'api_tag_ids': api_tag_ids,
                        'assignee_data': assignee_data,  # 🆕 Full data: id, email, name
                    }
                    processed_conversations.append(processed_conv)

                if len(api_conversations) < fetch_limit:
                    break

                last_conversation_id = api_conversations[-1].get('id')

            except Exception as e:
                _logger.error(f"Error fetching conversations: {e}", exc_info=True)
                break

        return processed_conversations



    def _create_or_update_conversations(self, conversations_data_list):
        self.ensure_one()
        ConversationEnv = self.env['page.fm.conversation']
        TagEnv = self.env['page.fm.tag'].sudo()
        created_count = 0
        updated_count = 0
        
        for conv_vals in conversations_data_list:
            conv_fm_id = conv_vals.get('conversation_fm_id')
            if not conv_fm_id: 
                continue
            
            # 🆕 Lấy api_tag_ids và assignee_data trước khi xử lý
            api_tag_ids = conv_vals.pop('api_tag_ids', [])
            assignee_data = conv_vals.pop('assignee_data', [])
            
            # DEBUG: Log để kiểm tra
            # if api_tag_ids:
            #     _logger.info(f"🔍 Processing conv {conv_fm_id} with api_tag_ids: {api_tag_ids}")
            # if assignee_data:
            #     names = [a.get('name') for a in assignee_data if a.get('name')]
            #     _logger.info(f"👥 Processing conv {conv_fm_id} with {len(assignee_data)} assignees: {names}")
            
            conv_vals['page_fm_page_id'] = self.id
            existing_conv = ConversationEnv.search([
                ('conversation_fm_id', '=', conv_fm_id), 
                ('page_fm_page_id', '=', self.id)
            ], limit=1)
            
            try:
                # 🆕 Map tag_ids từ Pancake sang Odoo tags
                odoo_tag_ids = []
                if api_tag_ids:
                    _logger.info(f"🏷️ Mapping {len(api_tag_ids)} tag_ids for conv {conv_fm_id}")
                    for tag_id_str in api_tag_ids:
                        tag = TagEnv.search([
                            ('tag_fm_id', '=', str(tag_id_str)),
                            ('page_id', '=', self.id)
                        ], limit=1)
                        if tag:
                            odoo_tag_ids.append(tag.id)
                            _logger.info(f"✅ Mapped tag_id {tag_id_str} → {tag.name} (id: {tag.id})")
                        else:
                            _logger.warning(f"⚠️ Tag {tag_id_str} not found in Odoo for page {self.page_fm_id_str}")
                
                # Gán tags vào conversation (luôn gán, kể cả khi rỗng để xóa tags đã gỡ)
                conv_vals['pancake_tag_ids'] = [(6, 0, odoo_tag_ids)]
                
                # 🆕 Map assigned users từ Pancake sang Odoo users
                # CHIẾN LƯỢC: Tìm theo pancake_id (UUID) trước, sau đó email
                # KHÔNG XÓA người cũ, CHỈ THÊM vào
                new_user_ids = []
                owner_user_id = False
                
                if assignee_data:
                    ResUsers = self.env['res.users'].sudo()
                    #_logger.info(f"👥 Mapping {len(assignee_data)} assignees for conv {conv_fm_id}")
                    
                    for idx, assignee in enumerate(assignee_data):
                        pancake_id = assignee.get('id')  # UUID
                        email = assignee.get('email')
                        name = assignee.get('name', 'Unknown')
                        
                        user = None
                        
                        # 1. Tìm theo pancake_id (kiểm tra cả 3 field: pancake_id, pancake_uuid, pancake_number_id)
                        if pancake_id:
                            # Tìm trong bất kỳ field nào (OR condition)
                            user = ResUsers.search([
                                '|', '|',
                                ('pancake_id', '=', pancake_id),
                                ('pancake_uuid', '=', pancake_id),
                                ('pancake_number_id', '=', pancake_id)
                            ], limit=1)
                            if user:
                                # Log để biết tìm được từ field nào
                                matched_field = 'pancake_id' if user.pancake_id == pancake_id else \
                                               'pancake_uuid' if user.pancake_uuid == pancake_id else \
                                               'pancake_number_id'
                                _logger.info(f"✅ Found user by {matched_field} {pancake_id[:8]}... → {user.name}")
                        
                        # 2. Nếu không có, tìm theo email (login hoặc email field)
                        if not user and email:
                            user = ResUsers.search([('login', '=', email)], limit=1)
                            if not user:
                                user = ResUsers.search([('email', '=', email)], limit=1)
                            if user:
                                _logger.info(f"✅ Found user by email {email} → {user.name}")
                        
                        if user:
                            new_user_ids.append(user.id)
                            # Owner = người đầu tiên trong list
                            if idx == 0 and not owner_user_id:
                                owner_user_id = user.id
                        else:
                            _logger.debug(f"⚠️ Assignee not found: {name} (pancake_id: {pancake_id[:8] if pancake_id else 'N/A'}, email: {email or 'N/A'})")
                
                # Gán owner (chỉ khi có từ API)
                if owner_user_id:
                    conv_vals['owner_id'] = owner_user_id
                
                # Gán participants - QUAN TRỌNG: KHÔNG xóa người cũ
                if new_user_ids:
                    if existing_conv:
                        # Lấy danh sách cũ và MERGE với mới (không trùng)
                        old_participant_ids = set(existing_conv.participant_user_ids.ids)
                        merged_ids = old_participant_ids.union(set(new_user_ids))
                        conv_vals['participant_user_ids'] = [(6, 0, list(merged_ids))]
                    else:
                        # Conversation mới - chỉ gán người mới
                        conv_vals['participant_user_ids'] = [(6, 0, new_user_ids)]
                
                if existing_conv:
                    # Chỉ log khi có thay đổi tags
                    old_tag_ids = set(existing_conv.pancake_tag_ids.ids)
                    new_tag_ids = set(odoo_tag_ids)
                    
                    if old_tag_ids != new_tag_ids:
                        if odoo_tag_ids:
                            _logger.info(f"🏷️ Update tags for conversation {conv_fm_id}: {len(old_tag_ids)} → {len(new_tag_ids)} tags")
                        else:
                            _logger.info(f"🗑️ Clear tags for conversation {conv_fm_id} (had {len(old_tag_ids)} tags)")
                    
                    # Log khi có thay đổi assigned users
                    old_owner_id = existing_conv.owner_id.id if existing_conv.owner_id else False
                    old_participant_ids = set(existing_conv.participant_user_ids.ids)
                    new_participant_ids = set(conv_vals.get('participant_user_ids', [(6, 0, [])])[0][2])
                    
                    if old_owner_id != owner_user_id and owner_user_id:
                        old_name = existing_conv.owner_id.name if existing_conv.owner_id else "None"
                        new_name = self.env['res.users'].sudo().browse(owner_user_id).name
                        #_logger.info(f"👤 Update owner for conv {conv_fm_id}: {old_name} → {new_name}")
                    
                    if old_participant_ids != new_participant_ids and new_user_ids:
                        added_ids = new_participant_ids - old_participant_ids
                        # if added_ids:
                        #     _logger.info(f"👥 Added {len(added_ids)} participants to conv {conv_fm_id}: total {len(old_participant_ids)} → {len(new_participant_ids)} users")
                    
                    existing_conv.write(conv_vals)
                    updated_count += 1
                    
                    # 🆕 Sync tags sang partner (luôn sync, kể cả khi rỗng)
                    if existing_conv.partner_id:
                        old_partner_tags = set(existing_conv.partner_id.pancake_tag_ids.ids)
                        if old_partner_tags != new_tag_ids:
                            existing_conv.partner_id.sudo().write({
                                'pancake_tag_ids': [(6, 0, odoo_tag_ids)]
                            })
                            # if odoo_tag_ids:
                            #     _logger.info(f"✅ Synced tags to partner {existing_conv.partner_id.name}: {len(old_partner_tags)} → {len(new_tag_ids)}")
                            # else:
                            #     _logger.info(f"🧹 Cleared tags for partner {existing_conv.partner_id.name}")
                else:
                    new_conv = ConversationEnv.create(conv_vals)
                    created_count += 1
                    
                    # Log khi tạo mới conversation có tags
                    # if odoo_tag_ids:
                    #     _logger.info(f"🆕 Created conversation {conv_fm_id} with {len(odoo_tag_ids)} tags")
                    
                    # 🆕 Sync tags sang partner (luôn sync, kể cả khi rỗng)
                    if new_conv.partner_id and odoo_tag_ids:
                        new_conv.partner_id.sudo().write({
                            'pancake_tag_ids': [(6, 0, odoo_tag_ids)]
                        })
                        #_logger.info(f"✅ Synced {len(odoo_tag_ids)} tags to new partner {new_conv.partner_id.name}")
                        
            except Exception as e:
                _logger.error(f"Error C/U conversation FM ID {conv_fm_id} for page {self.page_fm_id_str}: {e}", exc_info=True)
                
        #_logger.info(f"Conversations for page {self.page_fm_id_str}: {created_count} created, {updated_count} updated.")
        self.invalidate_recordset(['conversation_count'])

    @api.model
    def _create_or_update_page(self, page_data_from_api):
        # Lấy id page từ API
        page_fm_id = str(page_data_from_api.get('id') or '').strip()
        if not page_fm_id:
            #_logger.warning("API page data missing 'id'. Skipping.")
            return None

        page_name = page_data_from_api.get('name') or f"Page {page_fm_id}"
        # Danh sách API ‘categorized.activated’: mặc định True nếu thiếu
        is_api_activated = bool(page_data_from_api.get('is_activated', True))

        vals = {
            'name': page_name,
            'active': is_api_activated,   # (giải pháp nóng; về lâu dài tách thành api_is_activated)
        }

        # 1) TÌM THEO ID, KHÔNG LỌC active
        existing = self.with_context(active_test=False).search(
            [('page_fm_id_str', '=', page_fm_id)], limit=1
        )

        if existing:
            # 2) CHỈ GHI KHI THAY ĐỔI
            to_write = {}
            if existing.name != page_name:
                to_write['name'] = page_name
            if existing.active != is_api_activated:
                to_write['active'] = is_api_activated
            if to_write:
                existing.write(to_write)
            _logger.debug("Page processed: %s (OdooID:%s, FMID:%s)", page_name, existing.id, page_fm_id)
            return existing

        # 3) CHƯA CÓ → TẠO MỚI, BỌC RIÊNG CREATE() ĐỂ CHỐNG ĐUA UNIQUE
        vals['page_fm_id_str'] = page_fm_id
        try:
            rec = self.create(vals)
            #_logger.info("Page created: %s (OdooID:%s, FMID:%s)", page_name, rec.id, page_fm_id)
            return rec
        except Exception as e:
            # Nếu 2 worker/môi trường cùng lúc tạo → đụng unique => rollback & lấy lại record
            msg = (str(e) or '').lower()
            if 'duplicate key value violates unique constraint' in msg or 'unique constraint' in msg:
                self.env.cr.rollback()
                rec = self.with_context(active_test=False).search(
                    [('page_fm_id_str', '=', page_fm_id)], limit=1
                )
                if rec:
                    to_write = {}
                    if rec.name != page_name:
                        to_write['name'] = page_name
                    if rec.active != is_api_activated:
                        to_write['active'] = is_api_activated
                    if to_write:
                        rec.write(to_write)
                    #_logger.debug("Page processed after unique hit: %s (OdooID:%s, FMID:%s)", page_name, rec.id, page_fm_id)
                    return rec
            # Không phải lỗi unique → ném tiếp cho dễ debug
            raise

    @api.model
    def cron_quick_sync_conversations(self):
        """TIER 2: Quick metadata sync - Chỉ sync conversations metadata, KHÔNG sync messages
        
        Purpose: Cập nhật nhanh metadata (updated_at, is_unread, tags, assignees) mỗi 30 phút
        để phát hiện conversations mới và thay đổi trạng thái mà không tốn thời gian sync messages.
        """
        _logger.info("🔄 TIER 2: Starting Quick Metadata Sync (Conversations only)")
        
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token, không thể sync conversations.")
            return False
        
        # Lấy tất cả pages active
        pages = self.search([('active', '=', True)])
        if not pages:
            _logger.warning("Không có page nào active để sync.")
            return False
        
        total_synced = 0
        for page in pages:
            try:
                _logger.info(f"📥 Syncing metadata for page: {page.name} (FM ID: {page.page_fm_id_str})")
                conversations_list = page._fetch_conversations_for_page_record(main_access_token)
                
                if conversations_list:
                    page._create_or_update_conversations(conversations_list)
                    total_synced += len(conversations_list)
                    _logger.info(f"✅ Synced {len(conversations_list)} conversations for {page.name}")
                else:
                    _logger.info(f"No conversations found for {page.name}")
                    
            except Exception as e:
                _logger.error(f"Error syncing conversations for page {page.name}: {e}", exc_info=True)
                continue
        
        _logger.info(f"🎉 TIER 2 Complete: Synced {total_synced} conversations across {len(pages)} pages")
        return True
    
    @api.model
    def process_api_pages_data(self, pages_api_response_json):
        if not isinstance(pages_api_response_json, dict):
            #_logger.error("Invalid API response for pages list.")
            return []
        categorized_data = pages_api_response_json.get('categorized', {})
        if not isinstance(categorized_data, dict):
             #_logger.error("Invalid 'categorized' data for pages list.")
             return []

        # Đồng bộ từ cả 'activated' và 'inactivated' nếu API cung cấp page objects trong cả hai
        # Hoặc chỉ từ 'activated' nếu JS chỉ dùng nó. Dựa trên JS: data.categorized.activated
        # Giả sử 'activated' chứa danh sách các object page đang hoạt động
        pages_to_process_data = categorized_data.get('activated', []) 
        if not isinstance(pages_to_process_data, list):
            # Fallback hoặc logic khác nếu 'activated' không phải là list page objects
            # For now, if activated is not a list of objects, we stop here for pages.
            # If your /pages API returns objects in 'inactivated' and just IDs in 'activated', this needs adjustment.
            # The provided JS implies 'activated' is a list of page objects.
            if not isinstance(pages_to_process_data, list): # Double check, could be empty list is intended.
                pages_to_process_data = [] # Avoid error if it's not a list at all

        _logger.info(f"Processing {len(pages_to_process_data)} pages from API's 'activated' list.")
        
        odoo_pages_processed = []
        for page_data_item in pages_to_process_data:
            if isinstance(page_data_item, dict):
                # API trả về `is_activated` cho mỗi page, dùng nó để set trường `active` của Odoo.
                # Nếu page_data_item từ `categorized.activated` thì mặc định `is_activated` là true.
                # Nếu bạn lấy từ nguồn khác, phải đảm bảo có trường `is_activated`.
                # Trong ví dụ JS: return activatedPages.map(page => ({ id: page.id, name: page.name, inactive: !page.is_activated }));
                # Nghĩa là API page object có 'is_activated'.
                odoo_page_record = self._create_or_update_page(page_data_item)
                if odoo_page_record:
                    odoo_pages_processed.append(odoo_page_record)
            else:
                _logger.warning(f"Skipping invalid page data item: {page_data_item}")
        return odoo_pages_processed


    def perform_full_sync(self):
        _logger.info("Starting full Page.fm sync (Pages & Conversations).")
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.warning("Main Page.fm Access Token not configured. Sync aborted.")
            return False

        pages_list_api_url = f"{PAGES_FM_API_V1_BASE_URL}/pages?access_token={main_access_token}"
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        
        try:
            response_pages = requests.get(pages_list_api_url, headers=headers, timeout=15)
            _logger.debug(f"API Get Pages List: {pages_list_api_url} - Status: {response_pages.status_code}")
            response_pages.raise_for_status()
            pages_api_data = response_pages.json()
            
            synced_odoo_pages = self.env[self._name].process_api_pages_data(pages_api_data)
            
            # Bây giờ, lấy hội thoại cho các trang vừa đồng bộ/cập nhật
            if synced_odoo_pages:
                _logger.info(f"Fetching conversations for {len(synced_odoo_pages)} synced/updated pages.")
                for odoo_page in synced_odoo_pages:
                    conversations_list_for_page = odoo_page._fetch_conversations_for_page_record(main_access_token)
                    if conversations_list_for_page:
                        odoo_page._create_or_update_conversations(conversations_list_for_page)
            
            _logger.info("Full Page.fm sync completed successfully.")
            return True
        except Exception as e:
            _logger.error(f"Error during full Page.fm sync: {e}", exc_info=True)
            return False
    
    # @api.model
    # def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, count=False):
    #     # Bỏ gọi API tự động ở đây để tránh quá tải, trừ khi có context đặc biệt
    #     if self.env.context.get('trigger_page_fm_sync_on_search_read'):
    #          _logger.info(">>> PageFmPage search_read: Triggering FULL API sync due to context flag.")
    #          try:
    #              self.env[self._name]._perform_full_sync()
    #          except Exception as e:
    #              _logger.error(f"Error during API sync in search_read: {e}", exc_info=True)
    #     else:
    #         _logger.info(">>> PageFmPage search_read: Skipping automatic API sync.")
            
    #     return super(PageFmPage, self).search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order, count=count)

    # def read(self, fields=None, load='_classic_read', **kwargs):
    #     _logger.info(f">>> PageFmPage read for records {self.ids}. kwargs: {kwargs}")
    #     # Bỏ gọi API tự động ở đây
    #     return super(PageFmPage, self).read(fields=fields, load=load)

    # === Methods for view buttons ===
    
    def action_refresh_page(self):
        """Refresh page data from Pages.fm"""
        for record in self:
            try:
                # Sync lại page này từ API
                main_token = self.env['ir.config_parameter'].sudo().get_param('pages_fm_main_access_token')
                if not main_token:
                    raise ValueError(_('No main access token configured'))
                
                # Fetch conversations for this page
                conversations = record._fetch_conversations_for_page_record(main_token)
                conv_count = len(conversations) if conversations else 0
                
                # Show success message
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Page refreshed successfully. Found %d conversations.') % conv_count,
                        'type': 'success'
                    }
                }
            except Exception as e:
                _logger.error(f"Error refreshing page {record.name}: {e}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error'),
                        'message': _('Error refreshing page: %s') % str(e),
                        'type': 'danger'
                    }
                }

    def action_generate_access_token(self):
        """Generate new access token for this page"""
        for record in self:
            try:
                main_token = self.env['ir.config_parameter'].sudo().get_param('pages_fm_main_access_token')
                if not main_token:
                    raise ValueError(_('No main access token configured'))
                
                # Generate new page token
                new_token = record._generate_page_specific_access_token(main_token)
                if new_token:
                    record.write({'access_token': new_token})
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Success'),
                            'message': _('New access token generated successfully'),
                            'type': 'success'
                        }
                    }
                else:
                    raise ValueError(_('Failed to generate new token'))
                    
            except Exception as e:
                _logger.error(f"Error generating token for page {record.name}: {e}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error'),
                        'message': _('Error generating token: %s') % str(e),
                        'type': 'danger'
                    }
                }