import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
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

    PARAM_MAIN_ACCESS_TOKEN = 'page_fm.access_token'
    PARAM_MAIN_ACCESS_TOKEN_COMPAT = 'pages_fm_main_access_token'
    PARAM_TOKEN_CHECK_STATUS = 'page_fm.token_check_status'
    PARAM_TOKEN_CHECK_MESSAGE = 'page_fm.token_check_message'
    PARAM_TOKEN_CHECK_AT = 'page_fm.token_check_at'
    PARAM_TOKEN_CHECK_PAGE_COUNT = 'page_fm.token_check_page_count'
    PARAM_POINTER = 'pancake.last_conv_id'
    PARAM_CIRCUIT_UNTIL = 'page_fm_circuit_breaker_until'

    name = fields.Char(string="Page Name", index=True)
    page_fm_id_str = fields.Char(string="Page.fm ID", index=True, required=False, copy=False)
    active = fields.Boolean(string="API Active", default=True, index=True, help="Trạng thái active từ API (dựa trên is_activated)")
    sync_enabled = fields.Boolean(
        string="Đồng bộ",
        default=True,
        index=True,
        tracking=True,
        help="Chỉ các page được chọn mới tham gia toàn bộ luồng đồng bộ Pancake.",
    )
    catalog_status = fields.Selection(
        [('active', 'Đang hoạt động'), ('inactive', 'Không hoạt động'), ('unknown', 'Không rõ')],
        string="Trạng thái catalog",
        default='unknown',
        index=True,
    )
    last_catalog_sync_at = fields.Datetime(string="Lần tải danh mục gần nhất")
    last_selection_changed_at = fields.Datetime(string="Lần đổi chọn đồng bộ")
    last_message_sync_at = fields.Datetime(string="Lần sync tin nhắn gần nhất", compute='_compute_last_message_sync_at')
    page_token_cached = fields.Boolean(
        string="Đã có token trang",
        compute='_compute_page_token_cache_state',
        readonly=True,
    )
    page_token_cached_at = fields.Datetime(
        string="Lần tạo token trang gần nhất",
        compute='_compute_page_token_cache_state',
        readonly=True,
    )
    # 'active' của Odoo dùng cho archive/unarchive, trường này có thể đặt tên khác nếu muốn phân biệt rõ
    # Ví dụ: api_is_activated = fields.Boolean(string="API Is Activated")

    conversation_ids = fields.One2many('page.fm.conversation', 'page_fm_page_id', string="Conversations")
    conversation_count = fields.Integer(string="Conversation Count", compute='_compute_conversation_count', store=True)

    _sql_constraints = [
        ('page_fm_id_str_uniq', 'unique (page_fm_id_str)', 'Page.fm ID phải là duy nhất!')
    ]

    def init(self):
        self._cr.execute(
            """
            UPDATE page_fm_page
               SET sync_enabled = TRUE
             WHERE sync_enabled IS NULL
            """
        )
        self._cr.execute(
            """
            UPDATE page_fm_page
               SET catalog_status = CASE WHEN active THEN 'active' ELSE 'inactive' END
             WHERE catalog_status IS NULL
            """
        )

    @api.depends('conversation_ids')
    def _compute_conversation_count(self):
        for record in self:
            record.conversation_count = len(record.conversation_ids)

    @api.depends('conversation_ids.last_message_sync_fm')
    def _compute_last_message_sync_at(self):
        for record in self:
            sync_values = record.conversation_ids.mapped('last_message_sync_fm')
            sync_values = [value for value in sync_values if value]
            record.last_message_sync_at = max(sync_values) if sync_values else False

    @api.depends('page_fm_id_str')
    def _compute_page_token_cache_state(self):
        keys = []
        for record in self:
            if not record.page_fm_id_str:
                record.page_token_cached = False
                record.page_token_cached_at = False
                continue
            keys.append(f"page_token_{record.page_fm_id_str}")
            keys.append(f"page_token_time_{record.page_fm_id_str}")

        param_map = {}
        if keys:
            params = self.env['ir.config_parameter'].sudo().search([('key', 'in', keys)])
            param_map = {param.key: param.value for param in params}

        for record in self:
            if not record.page_fm_id_str:
                continue
            token = (param_map.get(f"page_token_{record.page_fm_id_str}") or '').strip()
            cached_at_raw = (param_map.get(f"page_token_time_{record.page_fm_id_str}") or '').strip()
            cached_at = False
            if cached_at_raw:
                try:
                    cached_at = fields.Datetime.to_datetime(cached_at_raw)
                except Exception:
                    cached_at = False
            record.page_token_cached = bool(token)
            record.page_token_cached_at = cached_at

    @api.model
    def _get_icp(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _get_main_access_token(self):
        icp = self._get_icp()
        return (
            icp.get_param(self.PARAM_MAIN_ACCESS_TOKEN)
            or icp.get_param(self.PARAM_MAIN_ACCESS_TOKEN_COMPAT)
            or ''
        ).strip()

    @api.model
    def _count_catalog_pages(self, payload):
        categorized = payload.get('categorized', {}) if isinstance(payload, dict) else {}
        if not isinstance(categorized, dict):
            return 0
        total = 0
        for key in ('activated', 'inactivated'):
            pages = categorized.get(key, [])
            if isinstance(pages, list):
                total += len([page for page in pages if isinstance(page, dict)])
        return total

    @api.model
    def _extract_catalog_pages(self, payload):
        categorized = payload.get('categorized', {}) if isinstance(payload, dict) else {}
        if not isinstance(categorized, dict):
            return []

        pages = []
        for key, is_activated in (('activated', True), ('inactivated', False)):
            values = categorized.get(key, [])
            if not isinstance(values, list):
                continue
            for page in values:
                if not isinstance(page, dict):
                    continue
                item = dict(page)
                item['is_activated'] = bool(page.get('is_activated', is_activated))
                pages.append(item)
        return pages

    @api.model
    def _store_token_check_result(self, result):
        icp = self._get_icp()
        icp.set_param(self.PARAM_TOKEN_CHECK_STATUS, result.get('status') or '')
        icp.set_param(self.PARAM_TOKEN_CHECK_MESSAGE, result.get('message') or '')
        icp.set_param(
            self.PARAM_TOKEN_CHECK_AT,
            fields.Datetime.to_string(result.get('checked_at')) if result.get('checked_at') else '',
        )
        icp.set_param(self.PARAM_TOKEN_CHECK_PAGE_COUNT, str(int(result.get('page_count', 0) or 0)))

    @api.model
    def _request_page_catalog(self, access_token):
        url = f"{PAGES_FM_API_V1_BASE_URL}/pages"
        response = requests.get(
            url,
            params={'access_token': access_token},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=15,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return response, payload

    @api.model
    def _check_main_access_token(self, access_token=None, store=True):
        checked_at = fields.Datetime.now()
        token = (access_token or self._get_main_access_token() or '').strip()
        if not token:
            result = {
                'status': 'invalid',
                'message': 'Thiếu access token chính.',
                'page_count': 0,
                'payload': {},
                'checked_at': checked_at,
            }
            if store:
                self._store_token_check_result(result)
            return result

        try:
            response, payload = self._request_page_catalog(token)
        except requests.exceptions.RequestException as exc:
            result = {
                'status': 'network_error',
                'message': str(exc),
                'page_count': 0,
                'payload': {},
                'checked_at': checked_at,
            }
            if store:
                self._store_token_check_result(result)
            return result

        message = ''
        if isinstance(payload, dict):
            message = str(payload.get('message') or '').strip()
        message_lower = message.lower()
        page_count = self._count_catalog_pages(payload)

        status = 'valid'
        if response.status_code in (401, 403):
            status = 'invalid'
            if not message:
                message = f'HTTP {response.status_code}'
        elif isinstance(payload, dict) and payload.get('success') is False:
            if 'expired' in message_lower:
                status = 'expired'
            elif any(keyword in message_lower for keyword in ('invalid', 'unauthorized', 'forbidden')):
                status = 'invalid'
            else:
                status = 'unknown_error'
        elif not isinstance(payload, dict):
            status = 'unknown_error'
            message = 'Phản hồi Pancake không hợp lệ.'

        if status == 'valid' and not message:
            message = 'Token hợp lệ.'

        result = {
            'status': status,
            'message': message,
            'page_count': page_count,
            'payload': payload if isinstance(payload, dict) else {},
            'checked_at': checked_at,
        }
        if store:
            self._store_token_check_result(result)
        return result

    @api.model
    def _fetch_page_catalog(self, access_token=None, store=True):
        result = self._check_main_access_token(access_token=access_token, store=store)
        if result.get('status') != 'valid':
            return result
        result['pages'] = self._extract_catalog_pages(result.get('payload') or {})
        return result

    @api.model
    def _active_page_domain(self):
        return [('active', '=', True)]

    @api.model
    def _get_active_page_count(self):
        return self.search_count(self._active_page_domain())

    @api.model
    def _selected_page_domain(self):
        return self._active_page_domain() + [('sync_enabled', '=', True)]

    @api.model
    def _get_selected_pages(self):
        return self._get_pages_for_sync_scope('selected_pages')

    @api.model
    def _get_all_pages_for_selection(self):
        return self.search(self._active_page_domain(), order='name asc, id asc')

    @api.model
    def _normalize_sync_scope(self, sync_scope=None):
        if sync_scope == 'all_active_pages':
            return 'all_active_pages'
        return 'selected_pages'

    @api.model
    def _page_domain_for_sync_scope(self, sync_scope=None):
        sync_scope = self._normalize_sync_scope(sync_scope)
        if sync_scope == 'all_active_pages':
            return self._active_page_domain()
        return self._selected_page_domain()

    @api.model
    def _get_pages_for_sync_scope(self, sync_scope=None):
        return self.search(self._page_domain_for_sync_scope(sync_scope), order='name asc, id asc')

    @api.model
    def _get_page_count_for_sync_scope(self, sync_scope=None):
        return self.search_count(self._page_domain_for_sync_scope(sync_scope))

    @api.model
    def _reset_selection_scope_state(self, reason):
        self.env['page.fm.conversation'].sudo()._reset_conv_pointer()
        self._get_icp().set_param(self.PARAM_CIRCUIT_UNTIL, '')
        _logger.info("Reset deep-sync pointer vì thay đổi phạm vi page đồng bộ: %s", reason)

    @api.model
    def _get_selected_page_snapshot(self):
        return self._get_page_snapshot_for_sync_scope('selected_pages')

    @api.model
    def _get_page_snapshot_for_sync_scope(self, sync_scope=None):
        pages = self._get_pages_for_sync_scope(sync_scope)
        return ', '.join(pages.mapped('page_fm_id_str'))

    @api.model
    def _upsert_pages_from_catalog(self, catalog_payload):
        pages_to_process = self._extract_catalog_pages(catalog_payload)
        now = fields.Datetime.now()
        processed = self.browse()
        for page_data in pages_to_process:
            page = self._create_or_update_page(page_data, last_catalog_sync_at=now, default_sync_enabled=False)
            if page:
                processed |= page
        return processed

    @api.model
    def _load_pages_from_token(self, access_token=None, store=True):
        result = self._fetch_page_catalog(access_token=access_token, store=store)
        if result.get('status') != 'valid':
            result['loaded_pages'] = self.browse()
            return result
        result['loaded_pages'] = self._upsert_pages_from_catalog(result.get('payload') or {})
        return result

    @api.model
    def _prepare_page_tokens_from_main_token(self, main_access_token=None, pages=None):
        token = (main_access_token or self._get_main_access_token() or '').strip()
        if not token:
            raise UserError(_('Thiếu main access token để tạo token trang.'))

        target_pages = pages if pages is not None else self
        if not target_pages:
            target_pages = self._get_selected_pages()
        target_pages = target_pages.filtered(lambda page: page.active and page.page_fm_id_str)

        prepared_page_count = 0
        skipped_page_count = 0
        failed_pages = []

        for page in target_pages:
            page_token = page._generate_page_specific_access_token(token)
            if page_token:
                prepared_page_count += 1
            else:
                failed_pages.append(page.page_fm_id_str or page.name or str(page.id))

        if pages is not None:
            skipped_page_count = len(pages - target_pages)

        return {
            'prepared_page_count': prepared_page_count,
            'skipped_page_count': skipped_page_count,
            'failed_page_count': len(failed_pages),
            'failed_pages': failed_pages,
        }

    @api.model
    def _is_retryable_page_token_error(self, payload, error_message):
        message = (error_message or '').strip().lower()
        error_code = 0
        if isinstance(payload, dict):
            try:
                error_code = int(payload.get('error_code') or 0)
            except Exception:
                error_code = 0

        if error_code in (102,):
            return True
        if 'expired' in message or 'access_token renewed' in message:
            return True
        return 'invalid access_token' in message

    def write(self, vals):
        selection_changed = False
        pages_to_clear_cache = self.browse()
        if 'sync_enabled' in vals:
            target_value = bool(vals.get('sync_enabled'))
            selection_changed = any(record.sync_enabled != target_value for record in self)
            if selection_changed:
                vals = dict(vals)
                vals['last_selection_changed_at'] = fields.Datetime.now()
                if not target_value:
                    pages_to_clear_cache = self.filtered('sync_enabled')

        res = super().write(vals)

        if selection_changed:
            if pages_to_clear_cache:
                for page in pages_to_clear_cache:
                    page.clear_token_cache()
            self._reset_selection_scope_state('page_selection_changed')
        return res
    
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
        main_access_token = self._get_main_access_token()
        if not main_access_token:
            _logger.error("Thiếu main_access_token, không thể lấy hội thoại.")
            return False # Hoặc raise UserError

        pages = self._get_selected_pages()
        if not pages:
            _logger.info("Không có page nào được chọn để đồng bộ conversation.")
            return False

        for odoo_page in pages: # self ở đây là recordset các page đã chọn
            _logger.info(f"Đang chuẩn bị đồng bộ hội thoại cho page: {odoo_page.name} (FM ID: {odoo_page.page_fm_id_str})")
            conversations_list = odoo_page._fetch_conversations_for_page_record(main_access_token)
            if conversations_list:
                odoo_page._create_or_update_conversations(conversations_list)
            else:
                _logger.info(f"Không có hội thoại nào được lấy hoặc có lỗi khi lấy hội thoại cho page {odoo_page.page_fm_id_str}")
        return True


    def _generate_page_specific_access_token(self, main_access_token, retry_count=0, max_retries=3, job=None):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str

        def _job_log(level, message):
            if not job:
                return
            job.sudo().write({'current_page_name': self.name})
            job._append_log(level, message)
            self.env.cr.commit()
        
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
                _job_log('warning', f"[{self.name}] Retry tạo token trang lần {retry_count}/{max_retries}, chờ {wait_time}s.")
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
                    _job_log('success', f"[{self.name}] Tạo lại page token thành công sau {retry_count} lần thử.")
                return token
            
            error_msg = data.get('message', 'Unknown error')
            _logger.error(f"Failed to generate page token for {page_fm_id}: {error_msg}")
            
            # Chỉ retry với lỗi token thực sự có thể hồi phục.
            if self._is_retryable_page_token_error(data, error_msg):
                _logger.warning(f"Page token generation hit retryable token error for {page_fm_id}, clearing cache")
                _job_log('warning', f"[{self.name}] Page token lỗi `{error_msg}`, đang xóa cache và thử lại.")
                self.clear_token_cache()
                if retry_count < max_retries:
                    return self._generate_page_specific_access_token(main_access_token, retry_count + 1, max_retries, job=job)
            
            return None
            
        except (requests.exceptions.ConnectTimeout, requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if retry_count < max_retries:
                _logger.warning(f"Network error for page {page_fm_id}, retry {retry_count + 1}/{max_retries}: {e}")
                _job_log('warning', f"[{self.name}] Lỗi mạng khi tạo token trang: {e}. Đang retry {retry_count + 1}/{max_retries}.")
                return self._generate_page_specific_access_token(main_access_token, retry_count + 1, max_retries, job=job)
            else:
                _logger.error(f"Max retries exceeded for page {page_fm_id}: {e}")
                _job_log('error', f"[{self.name}] Hết số lần retry tạo token trang: {e}")
                return None
                
        except Exception as e:
            _logger.error(f"Error generating page token for {page_fm_id}: {e}", exc_info=True)
            _job_log('error', f"[{self.name}] Lỗi tạo token trang: {e}")
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
    def _create_or_update_page(self, page_data_from_api, last_catalog_sync_at=None, default_sync_enabled=False):
        # Lấy id page từ API
        page_fm_id = str(page_data_from_api.get('id') or '').strip()
        if not page_fm_id:
            #_logger.warning("API page data missing 'id'. Skipping.")
            return None

        page_name = page_data_from_api.get('name') or f"Page {page_fm_id}"
        # Danh sách API ‘categorized.activated’: mặc định True nếu thiếu
        is_api_activated = bool(page_data_from_api.get('is_activated', True))
        catalog_status = 'active' if is_api_activated else 'inactive'

        vals = {
            'name': page_name,
            'active': is_api_activated,   # (giải pháp nóng; về lâu dài tách thành api_is_activated)
            'catalog_status': catalog_status,
            'last_catalog_sync_at': last_catalog_sync_at or fields.Datetime.now(),
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
            if existing.catalog_status != catalog_status:
                to_write['catalog_status'] = catalog_status
            if existing.last_catalog_sync_at != vals['last_catalog_sync_at']:
                to_write['last_catalog_sync_at'] = vals['last_catalog_sync_at']
            if to_write:
                existing.write(to_write)
            _logger.debug("Page processed: %s (OdooID:%s, FMID:%s)", page_name, existing.id, page_fm_id)
            return existing

        # 3) CHƯA CÓ → TẠO MỚI, BỌC RIÊNG CREATE() ĐỂ CHỐNG ĐUA UNIQUE
        vals['page_fm_id_str'] = page_fm_id
        vals['sync_enabled'] = bool(default_sync_enabled)
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
                    if rec.catalog_status != catalog_status:
                        to_write['catalog_status'] = catalog_status
                    if rec.last_catalog_sync_at != vals['last_catalog_sync_at']:
                        to_write['last_catalog_sync_at'] = vals['last_catalog_sync_at']
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
        if self.env['pancake.message.sync.job'].sudo().is_manual_sync_in_progress():
            _logger.info("Bỏ qua continuous metadata sync vì đang có job đồng bộ toàn bộ thủ công.")
            return False

        _logger.info("🔄 TIER 2: Starting Quick Metadata Sync (Conversations only)")
        log_model = self.env['pancake.message.sync.log'].sudo()
        
        token_check = self._check_main_access_token(store=True)
        if token_check.get('status') != 'valid':
            _logger.error("Token Pancake không hợp lệ cho Tier 2: %s", token_check.get('message'))
            self.env['page.fm.conversation'].sudo()._record_continuous_layer_stats(
                'candidate_refresh',
                conversations_checked=0,
                messages_created=0,
                error_count=1,
            )
            log_model.create_continuous_log(
                'candidate_refresh',
                'error',
                token_check.get('message') or 'Token Pancake không hợp lệ cho lớp cập nhật hội thoại mới.',
                event_code='continuous_invalid_token',
            )
            return False
        main_access_token = self._get_main_access_token()

        sync_stats = self.env['page.fm.conversation'].sudo()._compute_sync_window_stats('candidate_refresh')
        if not sync_stats.get('window_start_epoch'):
            _logger.warning("Không có page nào được chọn để sync metadata.")
            log_model.create_continuous_log(
                'candidate_refresh',
                'warning',
                'Bỏ qua cập nhật hội thoại mới vì chưa có page nào được chọn đồng bộ.',
                event_code='continuous_no_selected_pages',
            )
            return True

        candidate_stats = self.sync_selected_page_conversation_candidates(
            main_access_token,
            since_timestamp=sync_stats['window_start_epoch'],
            until_timestamp=sync_stats['window_end_epoch'],
            order_by='updated_at',
        )
        self.env['page.fm.conversation'].sudo()._record_continuous_layer_stats(
            'candidate_refresh',
            conversations_checked=candidate_stats['conversation_count'],
            messages_created=0,
            error_count=candidate_stats['error_count'],
        )
        log_level = 'success' if not candidate_stats['error_count'] else 'warning'
        log_model.create_continuous_log(
            'candidate_refresh',
            log_level,
            "Cập nhật hội thoại mới hoàn tất: %s hội thoại, %s page, %s lỗi." % (
                candidate_stats['conversation_count'],
                candidate_stats['page_count'],
                candidate_stats['error_count'],
            ),
            event_code='continuous_candidate_refresh_summary',
        )
        _logger.info(
            "🎉 TIER 2 Complete: Synced %s conversations across %s selected pages",
            candidate_stats['conversation_count'],
            candidate_stats['page_count'],
        )
        return True

    @api.model
    def _job_requested_stop(self, job):
        if not job:
            return False
        fresh_job = self.env['pancake.message.sync.job'].sudo().search([('id', '=', job.id)], limit=1)
        return bool(fresh_job and (fresh_job.state == 'stopping' or fresh_job.stop_requested))

    @api.model
    def _resolve_job_page_resume(self, job, pages):
        start_index = 0
        skipped_missing_page = False
        if not job or not pages:
            return start_index, skipped_missing_page

        cursor_page = job.phase_cursor_page_id
        cursor_index = int(job.phase_cursor_page_index or 0)
        if cursor_page:
            page_ids = pages.ids
            if cursor_page.id in page_ids:
                start_index = page_ids.index(cursor_page.id) + 1
            else:
                skipped_missing_page = True
                start_index = min(cursor_index, len(page_ids))
        elif cursor_index:
            start_index = min(cursor_index, len(pages))
        return start_index, skipped_missing_page

    @api.model
    def run_quick_sync_for_job(self, job):
        sync_scope = self._normalize_sync_scope(job.sync_scope)
        token_check = self._check_main_access_token(store=True)
        if token_check.get('status') != 'valid':
            job.sudo().write({
                'token_status': token_check.get('status'),
                'token_message': token_check.get('message'),
                'catalog_page_count': int(token_check.get('page_count', 0) or 0),
            })
            job._append_log('error', f"Tier 2 dừng sớm vì token `{token_check.get('status')}`: {token_check.get('message')}")
            self.env.cr.commit()
            return {'ok': False}
        main_access_token = self._get_main_access_token()

        pages = self._get_pages_for_sync_scope(sync_scope)
        if not pages:
            empty_message = (
                'Tier 2 không có page active nào để đồng bộ metadata.'
                if sync_scope == 'all_active_pages'
                else 'Tier 2 không có page nào được chọn để đồng bộ metadata.'
            )
            total_pages = self._get_active_page_count()
            job.sudo().write({
                'catalog_page_count': int(token_check.get('page_count', 0) or 0),
                'selected_page_count': 0,
                'skipped_page_count': total_pages,
                'total_page_count': 0,
                'processed_page_count': 0,
                'current_page_name': False,
            })
            job._append_log('warning', empty_message)
            self.env.cr.commit()
            return {'ok': True, 'page_count': 0, 'synced_conversation_count': 0}

        total_synced = 0
        page_count = len(pages)
        start_index, skipped_missing_page = self._resolve_job_page_resume(job, pages)
        total_pages = self._get_active_page_count()
        job.sudo().write({
            'token_status': token_check.get('status'),
            'token_message': token_check.get('message'),
            'catalog_page_count': int(token_check.get('page_count', 0) or 0),
            'selected_page_count': page_count,
            'skipped_page_count': max(total_pages - page_count, 0),
            'selected_page_snapshot': self._get_page_snapshot_for_sync_scope(sync_scope),
            'total_page_count': page_count,
            'processed_page_count': start_index,
            'current_page_name': False,
        })
        job._append_log('info', f'Tier 2 bắt đầu quét metadata cho {page_count} page trong phạm vi `{sync_scope}`.')
        if skipped_missing_page:
            job._append_log(
                'warning',
                'Checkpoint page của Tier 2 không còn active trong phạm vi hiện tại. Hệ thống sẽ tiếp tục từ vị trí gần nhất còn hợp lệ.',
                event_code='page_skipped_inactive_after_resume',
                resume_marker=True,
            )
        if start_index:
            job._append_log(
                'info',
                f'Tier 2 tiếp tục từ page thứ {start_index + 1}/{page_count} dựa trên checkpoint đã lưu.',
                resume_marker=True,
            )
        self.env.cr.commit()

        if start_index >= page_count:
            return {'ok': True, 'page_count': page_count, 'synced_conversation_count': total_synced}

        for relative_index, page in enumerate(pages[start_index:], start=1):
            index = start_index + relative_index
            if self._job_requested_stop(job):
                return {
                    'ok': True,
                    'stopped': True,
                    'page_count': page_count,
                    'synced_conversation_count': total_synced,
                }

            job.sudo().write({
                'processed_page_count': index - 1,
                'current_page_name': page.name,
            })
            job._refresh_runtime_metrics()
            job._append_log(
                'info',
                f"Tier 2 [{index}/{page_count}] đang quét metadata page `{page.name}`.",
                event_code='page_started',
                page=page,
            )
            self.env.cr.commit()

            try:
                conversations_list = page._fetch_conversations_for_page_record(main_access_token, job=job, phase_label='tier_2')
                synced_count = len(conversations_list or [])
                if conversations_list:
                    page._create_or_update_conversations(conversations_list)
                    total_synced += synced_count
                    job._append_log(
                        'success',
                        f"Tier 2 [{index}/{page_count}] page `{page.name}`: cập nhật {synced_count} conversation metadata.",
                        event_code='page_completed',
                        page=page,
                        stats={'synced_conversation_count': synced_count},
                    )
                else:
                    job._append_log(
                        'warning',
                        f"Tier 2 [{index}/{page_count}] page `{page.name}`: không lấy được conversation metadata.",
                        event_code='page_completed',
                        page=page,
                    )
            except Exception as exc:
                job._append_log(
                    'error',
                    f"Tier 2 [{index}/{page_count}] page `{page.name}` lỗi: {exc}",
                    event_code='page_failed_api',
                    page=page,
                )
                _logger.error(f"Error syncing conversations for page {page.name}: {exc}", exc_info=True)
            finally:
                job.sudo().write({
                    'processed_page_count': index,
                    'current_page_name': page.name,
                })
                job._save_checkpoint(page=page, page_index=index, stats={'phase': 'tier_2'})
                job._refresh_runtime_metrics()
                self.env.cr.commit()

        return {'ok': True, 'page_count': page_count, 'synced_conversation_count': total_synced}
    
    @api.model
    def process_api_pages_data(self, pages_api_response_json):
        return self._upsert_pages_from_catalog(pages_api_response_json)


    def perform_full_sync(self):
        _logger.info("Starting selected Page.fm sync (Selected Pages & Conversations).")
        token_check = self._check_main_access_token(store=True)
        if token_check.get('status') != 'valid':
            _logger.warning("Main Page.fm Access Token không hợp lệ. Sync aborted: %s", token_check.get('message'))
            return False
        main_access_token = self._get_main_access_token()
        selected_pages = self._get_selected_pages()
        if not selected_pages:
            _logger.warning("Không có page nào được chọn để full sync.")
            return True

        try:
            for odoo_page in selected_pages:
                conversations_list_for_page = odoo_page._fetch_conversations_for_page_record(main_access_token)
                if conversations_list_for_page:
                    odoo_page._create_or_update_conversations(conversations_list_for_page)
            _logger.info("Full Page.fm sync completed successfully for selected pages.")
            return True
        except Exception as e:
            _logger.error(f"Error during selected Page.fm sync: {e}", exc_info=True)
            return False

    @api.model
    def run_full_sync_for_job(self, job):
        sync_scope = self._normalize_sync_scope(job.sync_scope)
        token_check = self._check_main_access_token(store=True)
        if token_check.get('status') != 'valid':
            job.sudo().write({
                'token_status': token_check.get('status'),
                'token_message': token_check.get('message'),
                'catalog_page_count': int(token_check.get('page_count', 0) or 0),
            })
            job._append_log('error', f"Tier 1 dừng sớm vì token `{token_check.get('status')}`: {token_check.get('message')}")
            self.env.cr.commit()
            return {'ok': False}
        main_access_token = self._get_main_access_token()

        selected_pages = self._get_pages_for_sync_scope(sync_scope)
        page_count = len(selected_pages)
        start_index, skipped_missing_page = self._resolve_job_page_resume(job, selected_pages)
        total_synced = 0
        total_pages = self._get_active_page_count()
        job.sudo().write({
            'token_status': token_check.get('status'),
            'token_message': token_check.get('message'),
            'catalog_page_count': int(token_check.get('page_count', 0) or 0),
            'selected_page_count': page_count,
            'skipped_page_count': max(total_pages - page_count, 0),
            'selected_page_snapshot': self._get_page_snapshot_for_sync_scope(sync_scope),
            'total_page_count': page_count,
            'processed_page_count': start_index,
            'current_page_name': False,
        })
        job._append_log(
            'info',
            'Tier 1 bắt đầu quét page trong phạm vi `%s`. Token status: %s. Page catalog gần nhất: %s. Selected: %s. Skipped: %s. Snapshot: %s'
            % (
                sync_scope,
                token_check.get('status'),
                int(token_check.get('page_count', 0) or 0),
                page_count,
                max(total_pages - page_count, 0),
                job.selected_page_snapshot or '—',
            ),
        )
        if skipped_missing_page:
            job._append_log(
                'warning',
                'Checkpoint page của Tier 1 không còn active trong phạm vi hiện tại. Hệ thống sẽ tiếp tục từ vị trí gần nhất còn hợp lệ.',
                event_code='page_skipped_inactive_after_resume',
                resume_marker=True,
            )
        if start_index:
            job._append_log(
                'info',
                f'Tier 1 tiếp tục từ page thứ {start_index + 1}/{page_count} dựa trên checkpoint đã lưu.',
                resume_marker=True,
            )
        self.env.cr.commit()

        if not selected_pages:
            empty_message = (
                'Tier 1 không có page active nào để đồng bộ.'
                if sync_scope == 'all_active_pages'
                else 'Tier 1 không có page nào được chọn để đồng bộ.'
            )
            job._append_log('warning', empty_message)
            return {
                'ok': True,
                'page_count': 0,
                'synced_conversation_count': 0,
                'graceful_empty': True,
            }

        if start_index >= page_count:
            return {'ok': True, 'page_count': page_count, 'synced_conversation_count': total_synced}

        for relative_index, odoo_page in enumerate(selected_pages[start_index:], start=1):
            index = start_index + relative_index
            if self._job_requested_stop(job):
                return {
                    'ok': True,
                    'stopped': True,
                    'page_count': page_count,
                    'synced_conversation_count': total_synced,
                }

            job.sudo().write({
                'processed_page_count': index - 1,
                'current_page_name': odoo_page.name,
            })
            job._refresh_runtime_metrics()
            job._append_log(
                'info',
                f"Tier 1 [{index}/{page_count}] đang quét page `{odoo_page.name}`.",
                event_code='page_started',
                page=odoo_page,
            )
            self.env.cr.commit()

            try:
                conversations_list_for_page = odoo_page._fetch_conversations_for_page_record(main_access_token, job=job, phase_label='tier_1')
                synced_count = len(conversations_list_for_page or [])
                if conversations_list_for_page:
                    odoo_page._create_or_update_conversations(conversations_list_for_page)
                    total_synced += synced_count
                    job._append_log(
                        'success',
                        f"Tier 1 [{index}/{page_count}] page `{odoo_page.name}`: lấy {synced_count} conversation.",
                        event_code='page_completed',
                        page=odoo_page,
                        stats={'synced_conversation_count': synced_count},
                    )
                else:
                    job._append_log(
                        'warning',
                        f"Tier 1 [{index}/{page_count}] page `{odoo_page.name}`: không lấy được conversation nào.",
                        event_code='page_completed',
                        page=odoo_page,
                    )
            except Exception as exc:
                job._append_log(
                    'error',
                    f"Tier 1 [{index}/{page_count}] page `{odoo_page.name}` lỗi: {exc}",
                    event_code='page_failed_api',
                    page=odoo_page,
                )
                _logger.error(f"Error syncing page {odoo_page.name}: {exc}", exc_info=True)
            finally:
                job.sudo().write({
                    'processed_page_count': index,
                    'current_page_name': odoo_page.name,
                })
                job._save_checkpoint(page=odoo_page, page_index=index, stats={'phase': 'tier_1'})
                job._refresh_runtime_metrics()
                self.env.cr.commit()

        return {'ok': True, 'page_count': page_count, 'synced_conversation_count': total_synced}

    def action_enable_sync(self):
        if self:
            self.write({'sync_enabled': True})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_disable_sync(self):
        if self:
            self.write({'sync_enabled': False})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_load_page_catalog(self):
        result = self._load_pages_from_token(store=True)
        if result.get('status') != 'valid':
            raise UserError(result.get('message') or 'Không thể tải danh sách page từ Pancake.')
        self._prepare_page_tokens_from_main_token(pages=result.get('loaded_pages', self.browse()))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    
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
        """Sync all active pages that are marked sync_enabled."""
        pages = self._get_selected_pages()
        if not pages:
            raise UserError(_('Chưa có page active nào được bật cờ Đồng bộ.'))

        try:
            main_token = self._get_main_access_token()
            if not main_token:
                raise ValueError(_('No main access token configured'))

            total_conversations = 0
            for page in pages:
                conversations = page._fetch_conversations_for_page_record(main_token)
                conv_count = len(conversations) if conversations else 0
                total_conversations += conv_count
                if conversations:
                    page._create_or_update_conversations(conversations)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _(
                        'Đã đồng bộ %(page_count)s page đã chọn, lấy %(conversation_count)s conversations.'
                    ) % {
                        'page_count': len(pages),
                        'conversation_count': total_conversations,
                    },
                    'type': 'success'
                }
            }
        except Exception as e:
            _logger.error("Error refreshing selected pages: %s", e, exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Error refreshing selected pages: %s') % str(e),
                    'type': 'danger'
                }
            }

    def action_generate_access_token(self):
        """Generate or refresh page access token cache for selected pages."""
        try:
            main_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
            result = self._prepare_page_tokens_from_main_token(main_access_token=main_token, pages=self)
            prepared = result.get('prepared_page_count', 0)
            failed = result.get('failed_page_count', 0)
            skipped = result.get('skipped_page_count', 0)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success') if not failed else _('Completed with warnings'),
                    'message': _(
                        'Prepared %(prepared)s page token(s), failed %(failed)s, skipped %(skipped)s.'
                    ) % {
                        'prepared': prepared,
                        'failed': failed,
                        'skipped': skipped,
                    },
                    'type': 'success' if not failed else 'warning'
                }
            }
        except Exception as e:
            _logger.error(f"Error generating page token cache: {e}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Error generating token: %s') % str(e),
                    'type': 'danger'
                }
            }

    def _fetch_conversations_for_page_record(
        self,
        main_access_token,
        job=None,
        phase_label=None,
        raise_on_error=False,
        since_timestamp=None,
        until_timestamp=None,
        order_by='updated_at',
    ):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        page_specific_access_token = self._generate_page_specific_access_token(main_access_token, job=job)
        if not page_specific_access_token:
            error = ValueError(_('Khong tao duoc page access token cho page `%s`.') % (self.name or page_fm_id or self.id))
            if raise_on_error:
                raise error
            _logger.error("%s", error)
            return []

        processed_conversations = []
        last_conversation_id = None

        while True:
            conversations_api_url = f"{PAGES_FM_PUBLIC_API_V2_BASE_URL}/pages/{page_fm_id}/conversations"
            params = {
                'page_access_token': page_specific_access_token,
                'page_id': page_fm_id,
            }
            if since_timestamp is not None:
                params['since'] = int(since_timestamp)
            if until_timestamp is not None:
                params['until'] = int(until_timestamp)
            if order_by:
                params['order_by'] = order_by
            if last_conversation_id:
                params['last_conversation_id'] = last_conversation_id

            try:
                response = requests.get(
                    conversations_api_url,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    params=params,
                    timeout=25,
                )
                try:
                    data = response.json()
                except Exception:
                    data = {}

                message = str(data.get('message') or '').strip().lower()
                if response.status_code in (401, 403) or any(
                    keyword in message
                    for keyword in ('access_token renewed', 'expired', 'invalid access_token')
                ):
                    self.clear_token_cache()
                    if job:
                        job._append_log(
                            'warning',
                            f'[{self.name}] page token het han hoac bi thu hoi, dang xin lai token trang.',
                            event_code='page_token_refresh',
                            page=self,
                        )
                    page_specific_access_token = self._generate_page_specific_access_token(main_access_token, job=job)
                    if not page_specific_access_token:
                        raise ValueError(_('Khong tao lai duoc page access token cho page `%s`.') % (self.name or page_fm_id or self.id))
                    params['page_access_token'] = page_specific_access_token
                    response = requests.get(
                        conversations_api_url,
                        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                        params=params,
                        timeout=25,
                    )
                    try:
                        data = response.json()
                    except Exception:
                        data = {}

                response.raise_for_status()
                if not data.get('success'):
                    raise ValueError(data.get('message') or _('Pancake conversations API returned unsuccessful response.'))

                api_conversations = data.get('conversations', [])
                if not isinstance(api_conversations, list) or not api_conversations:
                    break

                for conv_data in api_conversations:
                    if not isinstance(conv_data, dict) or not conv_data.get('id'):
                        continue

                    platform = 'Khong ro'
                    from_id = conv_data.get('from', {}).get('id', '').lower()
                    page_id_api = (conv_data.get('page_id') or '').strip()
                    if from_id.startswith('pzl_') or page_id_api.lower().startswith('pzl_'):
                        platform = 'Zalo'
                    elif from_id.startswith('fb_') or (page_id_api.isdigit() and not page_id_api.startswith('igo_')) or page_id_api.lower().startswith('fb_'):
                        platform = 'Facebook'
                    elif from_id.startswith('igo_') or page_id_api.lower().startswith('igo_'):
                        platform = 'Instagram'
                    elif conv_data.get('type') and conv_data.get('type') != 'INBOX':
                        platform = conv_data['type']

                    updated_at_str = conv_data.get('updated_at', datetime.now().isoformat())
                    try:
                        dt_object = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        updated_at_fmt = dt_object.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    except ValueError:
                        updated_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)

                    api_tags = conv_data.get('tags', []) or []
                    api_tag_ids = []
                    if isinstance(api_tags, list):
                        for tag_obj in api_tags:
                            if isinstance(tag_obj, dict) and tag_obj.get('id'):
                                api_tag_ids.append(tag_obj['id'])

                    current_assign_users = conv_data.get('current_assign_users', []) or []
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
                                        'name': name,
                                    })

                    from_obj = conv_data.get('from', {})
                    # Thử các field name phổ biến cho avatar từ Pancake/Facebook API
                    avatar_url = (
                        from_obj.get('picture')
                        or from_obj.get('avatar')
                        or from_obj.get('avatar_url')
                        or from_obj.get('profile_pic')
                        or from_obj.get('profile_picture')
                        or ''
                    )

                    processed_conversations.append({
                        'conversation_fm_id': conv_data.get('id'),
                        'page_fm_page_id': self.id,
                        'customer_fm_id': conv_data.get('customer_id'),
                        'customer_name_fm': from_obj.get('name') or 'Khach an danh',
                        'customer_avatar_url': avatar_url,
                        'last_message_snippet': conv_data.get('snippet') or 'Khong co tin nhan',
                        'updated_at_fm': updated_at_fmt,
                        'is_unread_fm': not conv_data.get('seen', False),
                        'platform_fm': platform,
                        'conv_page_fm_id': page_id_api,
                        'api_tag_ids': api_tag_ids,
                        'assignee_data': assignee_data,
                    })

                next_last_conversation_id = api_conversations[-1].get('id')
                if not next_last_conversation_id or next_last_conversation_id == last_conversation_id:
                    break
                last_conversation_id = next_last_conversation_id

            except Exception as exc:
                _logger.error("Error fetching conversations for page %s: %s", self.page_fm_id_str, exc, exc_info=True)
                if raise_on_error:
                    raise
                break

        return processed_conversations

    @api.model
    def sync_selected_page_conversation_candidates(
        self,
        main_access_token,
        since_timestamp=None,
        until_timestamp=None,
        order_by='updated_at',
        job=None,
        raise_on_error=False,
    ):
        pages = self._get_selected_pages()
        stats = {
            'page_count': len(pages),
            'conversation_count': 0,
            'error_count': 0,
        }
        if not pages:
            return stats

        for page in pages:
            try:
                conversations_list = page._fetch_conversations_for_page_record(
                    main_access_token,
                    job=job,
                    raise_on_error=raise_on_error,
                    since_timestamp=since_timestamp,
                    until_timestamp=until_timestamp,
                    order_by=order_by,
                )
                if conversations_list:
                    page._create_or_update_conversations(conversations_list)
                    stats['conversation_count'] += len(conversations_list)
            except Exception as exc:
                stats['error_count'] += 1
                _logger.error(
                    "Error syncing conversation candidates for page %s: %s",
                    page.name,
                    exc,
                    exc_info=True,
                )
                if raise_on_error:
                    raise

        return stats
