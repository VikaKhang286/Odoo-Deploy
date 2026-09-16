# -*- coding: utf-8 -*-
import pytz
import json
import logging
from datetime import datetime, date, timedelta, time
from odoo import http, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)


class DataExportController(http.Controller):
    """
    Controller API để export toàn bộ dữ liệu từ Odoo
    Endpoints:
    - /api/export/all - Get tất cả dữ liệu
    - /api/export/sales - Get dữ liệu đơn hàng
    - /api/export/customers - Get dữ liệu khách hàng
    - /api/export/invoices - Get dữ liệu hóa đơn
    - /api/export/payments - Get dữ liệu phiếu thu
    - /api/export/employees - Get dữ liệu nhân viên

    Phase 1 security: tất cả export routes yêu cầu X-API-KEY header khớp với
    ICP param `dac_erp.export_api_key`. Nếu ICP param chưa cấu hình → routes
    trả 503 (config_missing) để bắt buộc admin set key trước khi mở public.
    """

    EXPORT_API_KEY_PARAM = 'dac_erp.export_api_key'

    def _check_export_api_key(self):
        """Trả None nếu OK, hoặc http.Response error nếu fail. Gọi ở đầu mọi route."""
        expected = (request.env['ir.config_parameter'].sudo()
                    .get_param(self.EXPORT_API_KEY_PARAM) or '').strip()
        if not expected:
            _logger.warning("Export API key not configured (ICP %s). Rejecting request.",
                            self.EXPORT_API_KEY_PARAM)
            return http.Response(
                json.dumps({
                    'success': False,
                    'error': {
                        'code': 'config_missing',
                        'message': ('Export API key chưa được cấu hình. '
                                    'Admin set ICP param %s trước khi gọi.' % self.EXPORT_API_KEY_PARAM),
                    },
                }, ensure_ascii=False),
                content_type='application/json',
                status=503,
            )
        provided = request.httprequest.headers.get('X-API-KEY')
        if not provided:
            return http.Response(
                json.dumps({
                    'success': False,
                    'error': {'code': 'missing_api_key', 'message': 'Missing X-API-KEY header'},
                }, ensure_ascii=False),
                content_type='application/json',
                status=401,
            )
        if str(provided).strip() != expected:
            return http.Response(
                json.dumps({
                    'success': False,
                    'error': {'code': 'invalid_api_key', 'message': 'Invalid X-API-KEY'},
                }, ensure_ascii=False),
                content_type='application/json',
                status=403,
            )
        return None

    def _json_response(self, data, status_code=200):
        """Helper để trả response JSON chuẩn"""
        response = {
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'status_code': status_code
        }
        return http.Response(
            json.dumps(response, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status_code
        )

    def _error_response(self, message, status_code=400):
        """Helper để trả error response"""
        response = {
            'success': False,
            'error': message,
            'timestamp': datetime.now().isoformat(),
            'status_code': status_code
        }
        return http.Response(
            json.dumps(response, ensure_ascii=False),
            content_type='application/json',
            status=status_code
        )

    def _serialize_record(self, record, fields_to_include):
        """Helper để serialize record thành dict"""
        result = {}
        for field_name in fields_to_include:
            if hasattr(record, field_name):
                value = getattr(record, field_name)
                
                # Xử lý các loại field đặc biệt
                if isinstance(value, models.Model):
                    # Many2one field
                    result[field_name] = {
                        'id': value.id,
                        'name': value.display_name if hasattr(value, 'display_name') else str(value)
                    }
                elif hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
                    # One2many/Many2many fields
                    result[field_name] = [{'id': r.id, 'name': r.display_name if hasattr(r, 'display_name') else str(r)} for r in value]
                elif isinstance(value, (date, datetime)):
                    # Date/Datetime fields
                    result[field_name] = value.isoformat() if value else None
                else:
                    # Các field khác
                    result[field_name] = value
        
        return result

    @http.route('/dac_erp/api/export/all', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_all_data(self, **kwargs):
        """API endpoint để get tất cả dữ liệu"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            _logger.info("API Export All Data được gọi")
            data = {
                'sales': self._get_sales_data(**kwargs),
                'customers': self._get_customers_data(**kwargs),
                'invoices': self._get_invoices_data(**kwargs),
                'payments': self._get_payments_data(**kwargs),
                'employees': self._get_employees_data(**kwargs),
                'products': self._get_products_data(**kwargs),
                'summary': self._get_summary_stats(**kwargs)
            }
            
            _logger.info(f"API Export All Data - Total records: {sum(len(v) if isinstance(v, list) else 0 for v in data.values())}")
            
            # Trả về HTTP response thay vì JSON response
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Error in export_all_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export dữ liệu: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/sales', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_sales_data(self, **kwargs):
        """API endpoint để get dữ liệu đơn hàng"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_sales_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_sales_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export đơn hàng: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/debug/simple', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_simple(self, **kwargs):
        """Debug endpoint đơn giản"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            partners = request.env['res.partner'].sudo().search([('is_company', '=', False)], limit=1)
            if partners:
                partner = partners[0]
                orders = request.env['sale.order'].sudo().search([('partner_id', '=', partner.id)])
                result = {
                    'partner_id': partner.id,
                    'partner_name': partner.name,
                    'orders_count': len(orders),
                    'orders_data': [{'id': o.id, 'name': o.name} for o in orders[:2]]
                }
            else:
                result = {'error': 'No partners found'}
            
            return http.Response(
                json.dumps(result, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            return http.Response(
                json.dumps({'error': str(e)}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/customers', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_customers_data(self, **kwargs):
        """API endpoint để get dữ liệu khách hàng với filter và limit mặc định"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            result = self._get_customers_data(**kwargs)
            return http.Response(
                json.dumps(result, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_customers_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export khách hàng: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/invoices', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_invoices_data(self, **kwargs):
        """API endpoint để get dữ liệu hóa đơn"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_invoices_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_invoices_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export hóa đơn: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/payments', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_payments_data(self, **kwargs):
        """API endpoint để get dữ liệu phiếu thu"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_payments_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_payments_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export phiếu thu: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/employees', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_employees_data(self, **kwargs):
        """API endpoint để get dữ liệu nhân viên"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_employees_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_employees_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export nhân viên: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/conversation_info', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_conversation_info(self, 
                                 limit=None, 
                                 offset=0,
                                 conversation_id=None,  # 🆕 Filter theo ID conversation
                                 page_id=None,
                                 page_fm_id_str=None,  # 🆕 Filter theo page_fm_id_str
                                 status=None,
                                 require_processing=None,
                                 has_unread=None,
                                 unread_only=None,  # 🆕 Alias cho has_unread
                                 owner_id=None,
                                 participant_id=None,
                                 staff_user_id=None,  # 🆕 Filter theo staff user
                                 staff_id_fm=None,  # 🆕 Filter theo staff Pancake ID
                                 staff_name=None,  # 🆕 Filter theo tên staff
                                 date=None,  # 🆕 Filter theo 1 ngày cụ thể
                                 date_from=None,
                                 date_to=None,
                                 days=None,  # 🆕 Filter theo số ngày gần nhất
                                 date_field='updated_at_fm',  # 🆕 Field để filter: 'updated_at_fm' | 'last_message_at_fm'
                                 is_internal=None,  # Filter nội bộ
                                 asc=None,  # 🆕 Sắp xếp ASC/DESC
                                 include_last_message=None,  # 🆕 Include last message detail
                                 include_message_count=None,  # 🆕 Include message count
                                 **kwargs):
        """
        API endpoint để get conversations với thông tin đầy đủ:
        - Người phụ trách chính (owner)
        - Nhóm người tham gia (participants)
        - Trạng thái conversation
        - Tin nhắn cuối
        - Tags
        
        Parameters:
        - limit: Số lượng conversation (mặc định 100)
        - offset: Bỏ qua bao nhiêu records
        - conversation_id: ID của conversation (Odoo ID) - 🆕
        - page_id: ID của page (Odoo ID)
        - page_fm_id_str: ID của page từ Pages.fm - 🆕
        - status: Trạng thái (new, recontact, waiting, done)
        - require_processing: '1'/'0' - Có yêu cầu xử lý không
        - has_unread/unread_only: '1'/'0' - Có tin nhắn chưa đọc không
        - owner_id: ID người phụ trách CHÍNH (Odoo user ID)
        - participant_id: ID người THAM GIA (Odoo user ID)
        - staff_user_id: ID staff user (Odoo user ID) - 🆕
        - staff_id_fm: ID staff từ Pancake - 🆕
        - staff_name: Tên staff (tìm kiếm gần đúng) - 🆕
        - date: Lọc theo 1 ngày cụ thể (YYYY-MM-DD) - 🆕
        - date_from: Lọc từ ngày (YYYY-MM-DD)
        - date_to: Lọc đến ngày (YYYY-MM-DD)
        - days: Số ngày gần nhất - 🆕
        - date_field: Field để filter theo thời gian - 🆕
          * 'updated_at_fm' (mặc định): Thời điểm cập nhật cuối conversation
          * 'last_message_at_fm': Thời điểm tin nhắn cuối được gửi
        - is_internal: '1'/'0' - Lọc cuộc trò chuyện nội bộ
        - asc: '1'/'0' - Sắp xếp tăng/giảm dần - 🆕
        - include_last_message: '1'/'0' - Bao gồm chi tiết tin nhắn cuối - 🆕
        - include_message_count: '1'/'0' - Đếm số tin nhắn - 🆕
        """
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_conversation_info(
                limit=limit,
                offset=offset,
                conversation_id=conversation_id,
                page_id=page_id,
                page_fm_id_str=page_fm_id_str,
                status=status,
                require_processing=require_processing,
                has_unread=has_unread,
                unread_only=unread_only,
                owner_id=owner_id,
                participant_id=participant_id,
                staff_user_id=staff_user_id,
                staff_id_fm=staff_id_fm,
                staff_name=staff_name,
                date=date,
                date_from=date_from,
                date_to=date_to,
                days=days,
                date_field=date_field,
                is_internal=is_internal,
                asc=asc,
                include_last_message=include_last_message,
                include_message_count=include_message_count,
                **kwargs
            )
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_conversation_info: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export conversations: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    def _get_conversation_info(self,
                               limit=None,
                               offset=0,
                               conversation_id=None,
                               page_id=None,
                               page_fm_id_str=None,
                               status=None,
                               require_processing=None,
                               has_unread=None,
                               unread_only=None,
                               owner_id=None,
                               participant_id=None,
                               staff_user_id=None,
                               staff_id_fm=None,
                               staff_name=None,
                               date=None,
                               date_from=None,
                               date_to=None,
                               days=None,
                               date_field='updated_at_fm',
                               is_internal=None,
                               asc=None,
                               include_last_message=None,
                               include_message_count=None,
                               **kwargs):
        """
        Get conversations với thông tin đầy đủ về participants và status
        
        Filter logic:
        - conversation_id: Lọc theo ID conversation cụ thể
        - owner_id: CHỈ lấy conversations mà user này là OWNER
        - participant_id: Lấy conversations mà user này là OWNER HOẶC PARTICIPANT
        - staff_*: Filter theo staff từ message (tìm conversations có message từ staff này)
        - date_field: Field để filter theo thời gian ('updated_at_fm' hoặc 'last_message_at_fm')
        - is_internal: '1' = chỉ nội bộ, '0' = chỉ không nội bộ, None = tất cả
        """
        
        Conv = request.env['page.fm.conversation'].sudo()
        Message = request.env['page.fm.message'].sudo()
        
        # --- Timezone & helpers ---
        args = request.httprequest.args
        tzname = args.get('tz') or request.env.context.get('tz') or 'UTC'
        try:
            tz = pytz.timezone(tzname)
        except Exception:
            tz = pytz.UTC

        def to_utc(dt):
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            return dt.astimezone(pytz.UTC)

        def parse_any(s, is_end=False):
            if not s:
                return None
            if len(s) == 10:
                d = datetime.strptime(s, '%Y-%m-%d').date()
                t = time.max if is_end else time.min
                return to_utc(datetime.combine(d, t))
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
            return to_utc(dt)
        
        # Build domain
        domain = []
        
        # Filter theo conversation_id cụ thể
        if conversation_id:
            try:
                cid = int(conversation_id)
                domain.append(('id', '=', cid))
            except:
                pass
        
        if page_id:
            try:
                pid = int(page_id)
                domain.append(('page_fm_page_id', '=', pid))
            except:
                pass
        
        if page_fm_id_str:
            domain.append(('page_fm_page_id.page_fm_id_str', '=', page_fm_id_str))
        
        if status:
            statuses = [s.strip() for s in str(status).split(',') if s.strip()]
            if statuses:
                domain.append(('status_state', 'in', statuses))
        
        if require_processing is not None and str(require_processing) != '':
            domain.append(('require_processing', '=', str(require_processing).lower() in ('1', 'true', 't', 'yes')))
        
        # Support both has_unread and unread_only
        unread_filter = unread_only if unread_only is not None else has_unread
        if unread_filter is not None and str(unread_filter) != '':
            domain.append(('is_unread_fm', '=', str(unread_filter).lower() in ('1', 'true', 't', 'yes')))
        
        # Filter theo is_internal_conversation
        if is_internal is not None and str(is_internal) != '':
            domain.append(('is_internal_conversation', '=', str(is_internal).lower() in ('1', 'true', 't', 'yes')))
        
        # Filter theo OWNER
        if owner_id:
            try:
                oid = int(owner_id)
                domain.append(('owner_id', '=', oid))
            except:
                pass
        
        # Filter theo PARTICIPANT
        if participant_id and not owner_id:
            try:
                pid = int(participant_id)
                domain.append('|')
                domain.append(('owner_id', '=', pid))
                domain.append(('participant_user_ids', 'in', [pid]))
            except:
                pass
        
        # --- Xử lý date filters với timezone ---
        dt_from_utc = dt_to_utc = None
        
        # Validate and set date field (chỉ cho phép 2 giá trị hợp lệ)
        if date_field not in ('updated_at_fm', 'last_message_at_fm'):
            dt_field = 'updated_at_fm'  # Default nếu giá trị không hợp lệ
        else:
            dt_field = date_field
        
        if date_from or date_to:
            dt_from_utc = parse_any(date_from, is_end=False) if date_from else None
            dt_to_utc = parse_any(date_to, is_end=True) if date_to else None
        elif date:
            dt_from_utc = parse_any(date, is_end=False)
            dt_to_utc = parse_any(date, is_end=True)
        elif days is not None:
            try:
                days_int = int(days)
            except Exception:
                days_int = 1
            now_tz = datetime.now(tz)
            start_tz = (now_tz - timedelta(days=days_int)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_tz = now_tz.replace(hour=23, minute=59, second=59, microsecond=999999)
            dt_from_utc = start_tz.astimezone(pytz.UTC)
            dt_to_utc = end_tz.astimezone(pytz.UTC)
        
        # --- Filter theo staff (từ messages) ---
        conv_ids_from_staff = None
        if staff_user_id or staff_id_fm or staff_name:
            msg_domain = []
            
            if page_id:
                msg_domain.append(('conversation_id.page_fm_page_id', '=', int(page_id)))
            if page_fm_id_str:
                msg_domain.append(('conversation_id.page_fm_page_id.page_fm_id_str', '=', page_fm_id_str))
            
            if staff_user_id:
                msg_domain.append(('staff', '=', int(staff_user_id)))
            if staff_id_fm:
                msg_domain.append(('staff_id_fm', '=', str(staff_id_fm)))
            if staff_name:
                msg_domain.append(('staff_name_fm', 'ilike', staff_name))
            
            # Thêm điều kiện thời gian cho message nếu có
            if dt_from_utc:
                msg_domain.append(('inserted_at_fm', '>=', fields.Datetime.to_string(dt_from_utc)))
            if dt_to_utc:
                msg_domain.append(('inserted_at_fm', '<=', fields.Datetime.to_string(dt_to_utc)))
            
            msg_records = Message.search(msg_domain)
            conv_ids_from_staff = list({m.conversation_id.id for m in msg_records if m.conversation_id})
            
            if conv_ids_from_staff:
                domain.append(('id', 'in', conv_ids_from_staff))
            else:
                # Không có message nào từ staff này
                return {
                    'success': True,
                    'count': 0,
                    'limit': int(limit) if limit else 100,
                    'offset': int(offset) if offset else 0,
                    'total': 0,
                    'items': [],
                }
        else:
            # Áp dụng date filter cho conversation nếu không filter theo staff
            if dt_from_utc:
                domain.append((dt_field, '>=', fields.Datetime.to_string(dt_from_utc)))
            if dt_to_utc:
                domain.append((dt_field, '<=', fields.Datetime.to_string(dt_to_utc)))
        
        # Search conversations
        limit = int(limit) if limit else 100
        offset = int(offset) if offset else 0
        
        # Determine sort order
        if asc is not None:
            order = f'{dt_field} {"asc" if str(asc) in ("1","true","True") else "desc"}'
        else:
            order = f'{dt_field} desc'
        
        conversations = Conv.search(domain, limit=limit, offset=offset, order=order)
        
        conv_data = []
        for conv in conversations:
            # Owner (người phụ trách chính)
            user_id = None
            if conv.owner_id:
                user_id = {
                    'id': conv.owner_id.id,
                    'name': conv.owner_id.name,
                    'email': conv.owner_id.email,
                    'pancake_id': getattr(conv.owner_id, 'pancake_id', None),
                    'pancake_uuid': getattr(conv.owner_id, 'pancake_uuid', None),
                }
            
            # Participants (nhóm người tham gia)
            participants = []
            if conv.participant_user_ids:
                for user in conv.participant_user_ids:
                    participants.append({
                        'id': user.id,
                        'name': user.name,
                        'email': user.email,
                        'pancake_id': getattr(user, 'pancake_id', None),
                        'pancake_uuid': getattr(user, 'pancake_uuid', None),
                    })
            
            # Partner (khách hàng)
            customer = None
            if conv.partner_id:
                customer = {
                    'id': conv.partner_id.id,
                    'name': conv.partner_id.name,
                    'phone': conv.partner_id.phone or conv.partner_id.mobile,
                    'email': conv.partner_id.email,
                }
            
            # Tags
            tags = []
            pancake_tags = getattr(conv, 'pancake_tag_ids', None) or getattr(conv, 'tag_ids', None)
            if pancake_tags:
                for tag in pancake_tags:
                    tags.append({
                        'id': tag.id,
                        'name': tag.name,
                        'fm_id': getattr(tag, 'tag_fm_id', None),
                        'color': getattr(tag, 'fm_color_hex', None),
                    })
            
            # Platform info
            platform = getattr(conv, 'platform_fm', None)
            
            # Build external URL
            external_url = None
            try:
                page_id_str = getattr(conv, 'conv_page_fm_id', None) or (
                    getattr(conv.page_fm_page_id, 'page_fm_id_str', None) 
                    if hasattr(conv, 'page_fm_page_id') else None
                )
                conv_fm_id = getattr(conv, 'conversation_fm_id', None)
                if page_id_str and conv_fm_id and hasattr(conv, '_build_external_url_for_platform'):
                    external_url = conv._build_external_url_for_platform(page_id_str, conv_fm_id)
            except Exception:
                pass
            
            # Last message info
            last_message = {
                'snippet': getattr(conv, 'last_message_snippet', None),
                'snippet_clean': getattr(conv, 'last_message_snippet_clean', None),
                'id': getattr(conv, 'last_message_id', None),
            }
            
            # Status info
            status_info = {
                'state': conv.status_state,
                'label': conv.status_label if hasattr(conv, 'status_label') else None,
                'require_processing': bool(conv.require_processing),
                'is_unread': bool(conv.is_unread_fm),
                'last_processing_change_at': conv.last_processing_change_at.isoformat() if getattr(conv, 'last_processing_change_at', None) else None,
            }
            
            # Notes
            notes = {
                'suggestion_note': getattr(conv, 'suggestion_note', None),
                'suggestion_note_clean': getattr(conv, 'suggestion_note_clean', None),
                'last_suggestion_at': conv.last_suggestion_at.isoformat() if getattr(conv, 'last_suggestion_at', None) else None,
            }
            
            # Page info
            page_info = None
            if conv.page_fm_page_id:
                page_info = {
                    'id': conv.page_fm_page_id.id,
                    'name': getattr(conv.page_fm_page_id, 'page_name', None),
                    'page_fm_id': getattr(conv.page_fm_page_id, 'page_fm_id_str', None),
                }
            
            conv_item = {
                # Basic info
                'id': conv.id,
                'conversation_fm_id': getattr(conv, 'conversation_fm_id', None),
                'customer_fm_id': getattr(conv, 'customer_fm_id', None),
                'name': conv.name,
                'customer_name_fm': getattr(conv, 'customer_name_fm', None),
                'customer_name_clean': getattr(conv, 'customer_name_clean', None),
                'phone': conv.phone,
                'platform': platform,
                
                # Timestamps
                'updated_at_fm': conv.updated_at_fm.isoformat() if conv.updated_at_fm else None,
                'create_date': conv.create_date.isoformat() if conv.create_date else None,
                'last_message_sync_fm': conv.last_message_sync_fm.isoformat() if getattr(conv, 'last_message_sync_fm', None) else None,
                'last_message_at_fm': conv.last_message_at_fm.isoformat() if getattr(conv, 'last_message_at_fm', None) else None,  # 🆕
                
                # Owner & Participants
                'user_id': user_id,
                'participants': participants,
                'participants_count': len(participants),
                
                # Customer
                'customer': customer,
                
                # Status
                'status': status_info,
                
                # Internal conversation flag
                'is_internal_conversation': bool(getattr(conv, 'is_internal_conversation', False)),
                
                # Messages
                'last_message': last_message,
                'message_count': getattr(conv, 'message_count', 0),
                
                # Tags
                'tags': tags,
                'tags_count': len(tags),
                
                # Notes
                'notes': notes,
                
                # Page
                'page': page_info,
                
                # External URL
                'external_url': external_url,
            }
            
            # Add message count if requested
            if include_message_count and str(include_message_count) in ('1', 'true', 'True'):
                conv_item['message_count_total'] = Message.search_count([('conversation_id', '=', conv.id)])
            
            # Add detailed last message if requested
            if include_last_message and str(include_last_message) in ('1', 'true', 'True'):
                msg_order = 'inserted_at_fm desc' if 'inserted_at_fm' in Message._fields else 'id desc'
                last_msg = Message.search([('conversation_id', '=', conv.id)], limit=1, order=msg_order)
                if last_msg:
                    m = last_msg[0]
                    try:
                        attachments = json.loads(m.attachments_json) if m.attachments_json else None
                    except Exception:
                        attachments = m.attachments_json
                    conv_item['last_message_detail'] = {
                        'id': m.id,
                        'message_fm_id': getattr(m, 'message_fm_id', None),
                        'inserted_at_fm': m.inserted_at_fm.isoformat() if getattr(m, 'inserted_at_fm', None) else None,
                        'sender_name_fm': getattr(m, 'sender_name_fm', None),
                        'staff_name_fm': getattr(m, 'staff_name_fm', None),
                        'type_content': getattr(m, 'type_content', None),
                        'content_html': getattr(m, 'content_html', None),
                        'attachments': attachments,
                    }
            
            conv_data.append(conv_item)
        
        return {
            'success': True,
            'count': len(conv_data),
            'limit': limit,
            'offset': offset,
            'total': Conv.search_count(domain),
            'order': order,
            'date_field': dt_field,
            'items': conv_data,
        }

    def _get_sales_data(
        self,
        limit=None,
        offset=0,
        # thời gian
        date=None,                  # YYYY-MM-DD (lấy đúng 1 ngày)
        date_from=None,             # YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS
        date_to=None,
        date_field='date',          # 'date' (custom) | 'date_order' | 'create_date' 
        # bộ lọc cơ bản
        user_id=None,               # id người phụ trách – cho phép 'me'
        partner_id=None,            # id khách hàng
        conversation_id=None,       # id conversation liên kết (Odoo ID)
        pancake_conversation_id=None, # id conversation từ Pancake
        state=None,                 # CSV: draft,sent,sale,done,cancel
        custom_state=None,          # CSV: quotation,deposit,production,delivery,payment
        company_id=None,            # id công ty
        has_deposit=None,           # '1'/'0'
        is_order_completed=None,    # '1'/'0'
        # bộ lọc số liệu
        min_total=None,             # số: tổng tối thiểu
        max_total=None,             # số: tổng tối đa
        # hiển thị
        order='date desc',          # cột sắp xếp
        include_lines='1',          # '1' trả kèm dòng hàng, '0' bỏ để nhẹ
        include_conversation='1',   # '1' trả kèm dữ liệu conversation, '0' bỏ
        conv_limit=None,            # số hội thoại muốn lấy; all -> 100; mặc định 3
        format=None,                # 'flat' => trả list thuần (tương thích cũ)
        **kwargs
    ):
        def _as_bool(v):
            return str(v).lower() in ('1', 'true', 't', 'yes', 'y')

        def _as_int(v):
            try:
                return int(v)
            except Exception:
                return None

        def _as_float(v):
            try:
                return float(v)
            except Exception:
                return None

        # conv_limit (ưu tiên tham số conv_limit; sau đó đọc include_conversation)
        if conv_limit is not None:
            conv_limit = 100 if str(conv_limit).lower() == 'all' else (_as_int(conv_limit) or 3)
        else:
            # Logic mới: chỉ dùng include_conversation như boolean, không phải số
            # Nếu include_conversation='1' thì mặc định lấy 3 conversations
            # Nếu là số cụ thể thì dùng số đó
            if str(include_conversation).isdigit() and int(include_conversation) > 1:
                conv_limit = int(include_conversation)
            elif _as_bool(include_conversation):
                conv_limit = 3  # Mặc định 3 conversations khi include_conversation=true
            else:
                conv_limit = 0

        domain = []

        # Chọn field ngày hợp lệ
        df = date_field if date_field in ('date', 'date_order', 'create_date') else 'date'

        # Hỗ trợ ?date=YYYY-MM-DD
        if date and (not date_from and not date_to):
            date_from = f"{date} 00:00:00"
            date_to   = f"{date} 23:59:59"

        if date_from:
            domain.append((df, '>=', date_from))
        if date_to:
            domain.append((df, '<=', date_to))

        # Người phụ trách
        if user_id:
            uid = _as_int(user_id) if user_id != 'me' else request.env.user.id
            if uid:
                domain.append(('user_id', '=', uid))

        # Khách hàng
        if partner_id:
            pid = _as_int(partner_id)
            if pid:
                domain.append(('partner_id', '=', pid))

        # Conversation ID (Odoo)
        if conversation_id:
            cid = _as_int(conversation_id)
            if cid:
                domain.append(('conversation_id', '=', cid))

        # Pancake Conversation ID
        if pancake_conversation_id:
            domain.append(('conversation_id.conversation_fm_id', '=', str(pancake_conversation_id)))

        # Trạng thái custom (sử dụng order_state_custom thay vì core state)
        if state:
            states = [s.strip() for s in str(state).split(',') if s.strip()]
            if states:
                domain.append(('order_state_custom', 'in', states))

        # Trạng thái custom (backward compatibility)
        if custom_state:
            csts = [s.strip() for s in str(custom_state).split(',') if s.strip()]
            if csts:
                domain.append(('order_state_custom', 'in', csts))

        # Công ty
        if company_id:
            cid = _as_int(company_id)
            if cid:
                domain.append(('company_id', '=', cid))

        # Cọc / hoàn thành
        if has_deposit is not None and str(has_deposit) != '':
            domain.append(('has_deposit', '=', _as_bool(has_deposit)))
        if is_order_completed is not None and str(is_order_completed) != '':
            domain.append(('is_order_completed', '=', _as_bool(is_order_completed)))

        # Tổng tiền
        mn = _as_float(min_total)
        mx = _as_float(max_total)
        if mn is not None:
            domain.append(('amount_total', '>=', mn))
        if mx is not None:
            domain.append(('amount_total', '<=', mx))

        # Truy vấn
        limit = int(limit) if limit else 100
        offset = int(offset) if offset else 0
        order = order or 'date desc'

        Order = request.env['sale.order'].sudo()  # giữ sudo như hiện tại
        orders = Order.search(domain, limit=limit, offset=offset, order=order)

        # Serialize
        send_lines = _as_bool(include_lines)
        items = []
        
        # Chuẩn bị model hội thoại (luôn khởi tạo để support conversation fields)
        Conv = None
        try:
            env_conv = request.env['page.fm.conversation']
            Conv = env_conv.sudo()
            # Test để đảm bảo model hoạt động
            conv_test = Conv.search([], limit=1)
            _logger.info(f"Conversation model loaded successfully, type: {type(Conv)}, test search works: {bool(conv_test)}")
        except Exception as e:
            Conv = None
            _logger.warning(f"Conversation model not available: {str(e)}")
        
        for so in orders:
            # ---- amounts & flags ----
            amounts = {'untaxed': so.amount_untaxed, 'tax': so.amount_tax, 'total': so.amount_total}
            flags   = {
                'has_deposit':      bool(getattr(so, 'has_deposit', False)),
                'is_completed':     bool(getattr(so, 'is_order_completed', False)),
                'is_priority':      bool(getattr(so, 'is_priority', False)),
                'is_priority_today':bool(getattr(so, 'is_priority_today', False)),
            }

            # ---- customer ----
            customer = None
            if so.partner_id:
                try:
                    disp_addr = so.partner_id._display_address() if hasattr(so.partner_id, '_display_address') else None
                except Exception:
                    disp_addr = None
                customer = {
                    'id': so.partner_id.id,
                    'name': so.partner_id.name,
                    'phone': getattr(so.partner_id, 'phone', None) or getattr(so.partner_id, 'mobile', None),
                    'address': getattr(so, 'delivery_address', None) or disp_addr,
                }

            # ---- people (sale / thiết kế / sản xuất / nhóm) ----
            def pack_user(u): return {'id': u.id, 'name': u.name} if u else None
            sale_user = pack_user(getattr(so, 'user_id', None))
            designer  = pack_user(getattr(so, 'design', None)) or pack_user(getattr(so, 'user_id_design', None)) or pack_user(getattr(so, 'design_user_id', None))
            producer  = pack_user(getattr(so, 'production', None)) or pack_user(getattr(so, 'user_id_production', None)) or pack_user(getattr(so, 'production_user_id', None))

            grp_raw = getattr(so, 'production_group_ids', None) or getattr(so, 'production_team_ids', None) or getattr(so, 'production_group_id', None)
            if grp_raw and hasattr(grp_raw, '__iter__'):
                production_group = [{'id': g.id, 'name': g.name} for g in grp_raw]
            else:
                production_group = [{'id': grp_raw.id, 'name': grp_raw.name}] if getattr(grp_raw, 'id', False) else []

            people = {'sale': sale_user, 'designer': designer, 'producer': producer, 'production_group': production_group}

            # ---- deposit / design / production / delivery ----
            deposit = {'enabled': flags['has_deposit'], 'amount': float(getattr(so, 'deposit_amount', 0.0) or 0.0)}
            design  = {'link': getattr(so, 'design_link', None) or getattr(so, 'link_design', None) or getattr(so, 'dac_design_link', None)}
            production = {
                'deadline': getattr(so, 'production_deadline', None).isoformat() if getattr(so, 'production_deadline', None) else None,
                'is_delayed': bool(getattr(so, 'is_delay', False) or getattr(so, 'is_production_delayed', False)),
                'delay_date': getattr(so, 'delay_date', None).isoformat() if getattr(so, 'delay_date', None) else None,
                'delay_reason': getattr(so, 'delay_reason', None),
            }
            delivery = {'address': getattr(so, 'delivery_address', None)}
            installation = {'address': getattr(so, 'installation_address', None)}

            # ---- order_number (đa tên field) ----
            order_number = (
                getattr(so, 'order_number', None) or
                getattr(so, 'so_number', None) or
                getattr(so, 'order_no', None) or
                getattr(so, 'client_order_ref', False)
            )

            row = {
                # cũ
                'id': so.id,
                'name': so.name,
                'client_order_ref': so.client_order_ref,  # Thêm field này để map CSV
                'partner_id': {'id': so.partner_id.id, 'name': so.partner_id.name} if so.partner_id else None,
                'user_id': {'id': so.user_id.id, 'name': so.user_id.name} if so.user_id else None,
                'company_id': {'id': so.company_id.id, 'name': so.company_id.name} if so.company_id else None,
                'state': getattr(so, 'order_state_custom', None),
                'order_state_custom': getattr(so, 'order_state_custom', None),
                'date_order': so.date_order.isoformat() if so.date_order else None,
                'create_date': so.create_date.isoformat() if so.create_date else None,
                'date': so.date.isoformat() if hasattr(so, 'date') and so.date else (so.date_order.isoformat() if so.date_order else None),
                'amount_total': so.amount_total,
                'amount_untaxed': so.amount_untaxed,
                'amount_tax': so.amount_tax,
                'has_deposit': flags['has_deposit'],
                'deposit_amount': float(getattr(so, 'deposit_amount', 0.0) or 0.0),
                'is_order_completed': flags['is_completed'],
                'production_deadline': getattr(so, 'production_deadline', None).isoformat() if getattr(so, 'production_deadline', None) else None,
                'delivery_address': getattr(so, 'delivery_address', None),

                # mới
                'order_number': order_number,
                'amounts': amounts,
                'flags': flags,
                'customer': customer,
                'people': people,
                'deposit': deposit,
                'design': design,
                'production': production,
                'delivery': delivery,
                'installation': installation,
            }
            
            # Safe access cho conversation_id & build conversation data
            primary_conv = None
            conv_items = []
            conversation_id_val = None
            pancake_conversation_id_val = None

            # a) ưu tiên field M2O trực tiếp nếu chuẩn model
            try:
                if hasattr(so, 'conversation_id'):
                    conversation_field = getattr(so, 'conversation_id', None)
                    if conversation_field and hasattr(conversation_field, 'id') and hasattr(conversation_field, 'exists'):
                        if conversation_field.exists() and getattr(conversation_field, '_name', '') == 'page.fm.conversation':
                            primary_conv = conversation_field
                            _logger.info(f"Order {so.name}: Found direct conversation_id={conversation_field.id}")
            except Exception as e:
                _logger.warning(f"Error accessing conversation_id for order {so.name}: {str(e)}")

            # b) tìm theo partner (bao gồm cả commercial partner và children)
            pid = None
            commercial_pid = None
            if so.partner_id:
                try:
                    # Lấy cả partner hiện tại và commercial partner
                    pid = so.partner_id.id
                    commercial_partner = getattr(so.partner_id, 'commercial_partner_id', so.partner_id) or so.partner_id
                    commercial_pid = commercial_partner.id
                    _logger.info(f"Order {so.name}: partner_id={pid}, commercial_partner_id={commercial_pid}, primary_conv={bool(primary_conv)}")
                except Exception:
                    pid = so.partner_id.id
                    commercial_pid = pid
                    _logger.info(f"Order {so.name}: partner_id={pid} (fallback), primary_conv={bool(primary_conv)}")

            if not primary_conv and Conv is not None and commercial_pid:
                try:
                    _logger.info(f"Order {so.name}: Starting conversation search for commercial_pid={commercial_pid}")
                    
                    # Tìm theo child_of commercial partner
                    primary_conv = Conv.search([
                        ('partner_id', 'child_of', commercial_pid)
                    ], order='updated_at_fm desc, write_date desc', limit=1)
                    
                    if primary_conv:
                        _logger.info(f"Order {so.name}: Found conversation via child_of commercial partner {commercial_pid}, conversation_id={primary_conv.id}")
                    else:
                        _logger.info(f"Order {so.name}: No conversation found via child_of commercial partner {commercial_pid}")
                        
                        # Fallback: tìm theo partner_id trực tiếp
                        primary_conv = Conv.search([
                            ('partner_id', '=', pid)
                        ], order='updated_at_fm desc, write_date desc', limit=1)
                        
                        if primary_conv:
                            _logger.info(f"Order {so.name}: Found conversation via direct partner {pid}, conversation_id={primary_conv.id}")
                        else:
                            _logger.info(f"Order {so.name}: No conversation found via direct partner {pid}")
                            
                except Exception as e:
                    _logger.warning(f"Error finding conversation by partner for order {so.name}: {str(e)}")
            else:
                _logger.info(f"Order {so.name}: Skipping conversation search - primary_conv={bool(primary_conv)}, Conv is None={Conv is None}, commercial_pid={commercial_pid}")

            # c) danh sách hội thoại theo conv_limit
            _logger.info(f"Order {so.name}: Checking conv_limit - Conv is None={Conv is None}, commercial_pid={commercial_pid}, conv_limit={conv_limit}")
            if Conv is not None and commercial_pid and (conv_limit or 0) > 0:
                try:
                    _logger.info(f"Order {so.name}: Searching for conversations with conv_limit={conv_limit}")
                    all_convs = Conv.search([
                        ('partner_id', 'child_of', commercial_pid)
                    ], order='updated_at_fm desc, write_date desc', limit=int(conv_limit))
                    
                    _logger.info(f"Order {so.name}: Found {len(all_convs)} conversations for conv_limit")
                    
                    for cc in all_convs:
                        # Build external URL for conversation using model method
                        external_url = None
                        try:
                            page_id = getattr(cc, 'conv_page_fm_id', None) or (getattr(cc.page_fm_page_id, 'page_fm_id_str', None) if hasattr(cc, 'page_fm_page_id') else None)
                            conv_fm_id = getattr(cc, 'conversation_fm_id', None)
                            if page_id and conv_fm_id:
                                external_url = cc._build_external_url_for_platform(page_id, conv_fm_id)
                        except Exception:
                            pass

                        conv_items.append({
                            'id': cc.id,
                            'pancake_id': getattr(cc, 'conversation_fm_id', None),
                            'name': getattr(cc, 'name', None) or getattr(cc, 'display_name', None),
                            'status': getattr(cc, 'status_state', None) or getattr(cc, 'status', None),
                            'require_processing': bool(getattr(cc, 'require_processing', False)),
                            'updated_at': cc.updated_at_fm.isoformat() if getattr(cc, 'updated_at_fm', None) else None,
                            'last_message': getattr(cc, 'last_message_snippet', None),
                            'external_url': external_url,
                            'tags': [{
                                'id': t.id, 'name': t.name,
                                'fm_id': getattr(t, 'tag_fm_id', None),
                                'color': getattr(t, 'fm_color_hex', None)
                            } for t in (getattr(cc, 'pancake_tag_ids', []) or getattr(cc, 'tag_ids', []))]
                        })
                except Exception as e:
                    _logger.warning(f"Error getting conversation list for order {so.name}: {str(e)}")

            # d) build primary conversation object
            conversation_obj = None
            if primary_conv and hasattr(primary_conv, 'exists') and primary_conv.exists():
                try:
                    conversation_id_val = primary_conv.id
                    pancake_conversation_id_val = getattr(primary_conv, 'conversation_fm_id', None)
                    
                    # Build external URL for primary conversation using model method
                    external_url = None
                    try:
                        page_id = getattr(primary_conv, 'conv_page_fm_id', None) or (getattr(primary_conv.page_fm_page_id, 'page_fm_id_str', None) if hasattr(primary_conv, 'page_fm_page_id') else None)
                        if page_id and pancake_conversation_id_val:
                            external_url = primary_conv._build_external_url_for_platform(page_id, pancake_conversation_id_val)
                    except Exception:
                        pass

                    conversation_obj = {
                        'id': primary_conv.id,
                        'name': getattr(primary_conv, 'name', '') or '',
                        'pancake_id': pancake_conversation_id_val,
                        'pancake_conversation_id': pancake_conversation_id_val,  # backward compatibility
                        'status': getattr(primary_conv, 'status_state', None) or getattr(primary_conv, 'status', None),
                        'require_processing': bool(getattr(primary_conv, 'require_processing', False)),
                        'updated_at': primary_conv.updated_at_fm.isoformat() if getattr(primary_conv, 'updated_at_fm', None) else None,
                        'last_message': getattr(primary_conv, 'last_message_snippet', None),
                        'external_url': external_url,
                        'created_date': primary_conv.create_date.isoformat() if hasattr(primary_conv, 'create_date') and primary_conv.create_date else None,
                        'last_activity_date': primary_conv.updated_at_fm.isoformat() if getattr(primary_conv, 'updated_at_fm', None) else None,
                        'assigned_user_id': {
                            'id': primary_conv.owner_id.id,
                            'name': primary_conv.owner_id.name
                        } if hasattr(primary_conv, 'owner_id') and primary_conv.owner_id else None,
                        'partner_id': {
                            'id': primary_conv.partner_id.id,
                            'name': primary_conv.partner_id.name
                        } if primary_conv.partner_id else None,
                        'tags': [{
                            'id': t.id, 'name': t.name,
                            'fm_id': getattr(t, 'tag_fm_id', None),
                            'color': getattr(t, 'fm_color_hex', None)
                        } for t in (getattr(primary_conv, 'pancake_tag_ids', []) or getattr(primary_conv, 'tag_ids', []))],
                        'description': getattr(primary_conv, 'suggestion_note', '') or ''
                    }
                except Exception as e:
                    _logger.warning(f"Failed to load conversation data for order {so.name}: {str(e)}")
                    conversation_obj = None

            row.update({
                'conversation_id': conversation_id_val,
                'pancake_conversation_id': pancake_conversation_id_val,
                'conversation': conversation_obj,
                'conversations': {
                    'count': len(conv_items),
                    'primary_id': conversation_id_val,
                    'items': conv_items,
                },
            })
            if send_lines:
                # order_lines (tên cũ) + lines (tên mới)
                order_lines = [{
                    'id': l.id,
                    'product_id': {'id': l.product_id.id, 'name': l.product_id.name} if l.product_id else None,
                    'name': l.name,
                    'product_uom_qty': l.product_uom_qty,
                    'price_unit': l.price_unit,
                    'price_subtotal': l.price_subtotal,
                    'display_type': l.display_type,
                } for l in so.order_line]
                lines = [{
                    'id': l.id,
                    'product': {'id': l.product_id.id, 'name': l.product_id.name} if l.product_id else None,
                    'name': l.name,
                    'qty': l.product_uom_qty,
                    'price_unit': l.price_unit,
                    'subtotal': l.price_subtotal,
                    'display_type': l.display_type,
                } for l in so.order_line]
                row['order_lines'] = order_lines  # tên cũ
                row['lines'] = lines              # tên mới
            items.append(row)

        # Tương thích ngược: ?format=flat -> trả list thuần như trước
        if (format or '').lower() == 'flat':
            return items

        return {
            'count': len(items),
            'limit': limit,
            'offset': offset,
            'order': order,
            'date_field': df,
            'domain': domain,   # tiện debug
            'items': items,
        }


    def _get_customers_data(self, 
                           limit=None, 
                           include_conversation='1', 
                           include_orders='1', 
                           include_order_details='0', 
                           # Filters for conversations
                           has_orders_only='0', 
                           has_conversation_only='0',
                           # Filters for orders
                           state=None,  # Filter by order state
                           order_state_custom=None,  # Filter by custom order state
                           **kwargs):
        """Get dữ liệu khách hàng - với filter theo trạng thái đơn hàng"""
        # Giới hạn mặc định
        limit = int(limit) if limit else 150  
        
        # Bước 1: Xây dựng domain lọc partners
        domain = [('is_company', '=', False)]
        partner_ids_to_include = None
        
        # Filter theo orders state nếu có
        if state or order_state_custom:
            order_domain = []
            if state:
                states = [s.strip() for s in str(state).split(',') if s.strip()]
                if states:
                    order_domain.append(('order_state_custom', 'in', states))
            
            if order_state_custom:
                custom_states = [s.strip() for s in str(order_state_custom).split(',') if s.strip()]
                if custom_states:
                    order_domain.append(('order_state_custom', 'in', custom_states))
            
            # Lấy partner_ids từ orders thỏa mãn
            orders_with_filter = request.env['sale.order'].sudo().search(order_domain)
            partner_ids_with_orders = set(orders_with_filter.mapped('partner_id.id'))
            
            _logger.info(f"🔍 Order Filter Debug: Found {len(orders_with_filter)} orders matching state filter, {len(partner_ids_with_orders)} unique partners")
            
            if not partner_ids_with_orders:
                return {'count': 0, 'limit': limit, 'applied_filters': {'state': state, 'order_state_custom': order_state_custom}, 'items': []}
            
            partner_ids_to_include = partner_ids_with_orders
        
        # Filter theo has_orders_only nếu có
        if str(has_orders_only).lower() in ('1', 'true'):
            # Lấy tất cả partner có ít nhất 1 order
            all_partners_with_orders = request.env['sale.order'].sudo().search([]).mapped('partner_id.id')
            all_partners_with_orders = set(all_partners_with_orders)
            
            if partner_ids_to_include is not None:
                partner_ids_to_include = partner_ids_to_include.intersection(all_partners_with_orders)
            else:
                partner_ids_to_include = all_partners_with_orders
                
            _logger.info(f"🔍 Has Orders Filter Debug: Found {len(partner_ids_to_include)} partners with orders")
        
        # Filter theo has_conversation_only nếu có
        if str(has_conversation_only).lower() in ('1', 'true'):
            # Lấy tất cả partner có conversation
            try:
                Conv = request.env['page.fm.conversation'].sudo()
                all_partners_with_conversations = Conv.search([]).mapped('partner_id.id')
                all_partners_with_conversations = set(all_partners_with_conversations)
                
                if partner_ids_to_include is not None:
                    partner_ids_to_include = partner_ids_to_include.intersection(all_partners_with_conversations)
                else:
                    partner_ids_to_include = all_partners_with_conversations
                    
                _logger.info(f"🔍 Has Conversation Filter Debug: Found {len(partner_ids_to_include)} partners with conversations")
            except Exception as e:
                _logger.warning(f"Error filtering partners with conversations: {str(e)}")
                if partner_ids_to_include is None:
                    partner_ids_to_include = set()
        
        # Áp dụng filter partner_ids vào domain
        if partner_ids_to_include is not None:
            if not partner_ids_to_include:
                return {'count': 0, 'limit': limit, 'applied_filters': {'state': state, 'has_orders_only': has_orders_only, 'has_conversation_only': has_conversation_only}, 'items': []}
            domain.append(('id', 'in', list(partner_ids_to_include)))
        
        partners = request.env['res.partner'].sudo().search(domain, limit=limit, order='create_date desc')
        
        # Debug info
        total_partners = request.env['res.partner'].sudo().search_count([])
        total_individual = request.env['res.partner'].sudo().search_count([('is_company', '=', False)])
        #_logger.info(f"🔍 Customer API Debug: Total partners: {total_partners}, Individual: {total_individual}, Found with filter: {len(partners)}, Limit: {limit}")
        #_logger.info(f"🔍 Applied Filters: state={state}, has_orders_only={has_orders_only}, has_conversation_only={has_conversation_only}")
        
        customers_data = []
        for partner in partners:
            # Lấy người phụ trách từ đơn hàng gần nhất
            latest_order = request.env['sale.order'].sudo().search([
                ('partner_id', '=', partner.id)
            ], limit=1, order='create_date desc')
            
            responsible_user = None
            if latest_order and latest_order.user_id:
                responsible_user = {
                    'id': latest_order.user_id.id,
                    'name': latest_order.user_id.name,
                    'login': latest_order.user_id.login
                }
            
            # Lấy thông tin conversation nếu có
            conversation_data = None
            if str(include_conversation).lower() in ('1', 'true'):
                try:
                    Conv = request.env['page.fm.conversation'].sudo()
                    conversation = Conv.search([
                        ('partner_id', '=', partner.id)
                    ], order='updated_at_fm desc, write_date desc', limit=1)
                    
                    if conversation:
                        conversation_data = {
                            'id': conversation.id,
                            'name': getattr(conversation, 'name', '') or '',
                            'pancake_conversation_id': getattr(conversation, 'conversation_fm_id', None),
                            'status': getattr(conversation, 'status_state', None),
                            'require_processing': getattr(conversation, 'require_processing', False),
                            'is_unread': getattr(conversation, 'is_unread_fm', False),
                            'last_message_snippet': getattr(conversation, 'last_message_snippet', ''),
                            'updated_at_fm': conversation.updated_at_fm.isoformat() if hasattr(conversation, 'updated_at_fm') and conversation.updated_at_fm else None,
                            'owner_id': {
                                'id': conversation.owner_id.id,
                                'name': conversation.owner_id.name
                            } if hasattr(conversation, 'owner_id') and conversation.owner_id else None,
                        }
                except Exception as e:
                    _logger.warning(f"Error loading conversation for partner {partner.name}: {str(e)}")
            
            # Get orders data if requested
            orders_data = None
            total_orders = 0
            total_invoiced = 0.0
            orders_by_state = {}
            try:
                # Áp dụng filter cho orders nếu có
                order_domain = [('partner_id', '=', partner.id)]
                if state or order_state_custom:
                    if state:
                        states = [s.strip() for s in str(state).split(',') if s.strip()]
                        if states:
                            order_domain.append(('order_state_custom', 'in', states))
                    if order_state_custom:
                        custom_states = [s.strip() for s in str(order_state_custom).split(',') if s.strip()]
                        if custom_states:
                            order_domain.append(('order_state_custom', 'in', custom_states))
                
                orders = request.env['sale.order'].sudo().search(order_domain, order='create_date desc')
                
                total_orders = len(orders)
                total_invoiced = sum(orders.mapped('amount_total')) if orders else 0.0
                
                # Thống kê orders theo state
                for order in orders:
                    order_state = getattr(order, 'order_state_custom', 'unknown')
                    orders_by_state[order_state] = orders_by_state.get(order_state, 0) + 1
                
                if str(include_orders).lower() in ('1', 'true'):
                    orders_data = []
                    for order in orders:
                        order_data = {
                            'id': order.id,
                            'name': order.name,
                            'state': getattr(order, 'order_state_custom', None),
                            'amount_total': order.amount_total,
                            'create_date': order.create_date.isoformat() if order.create_date else None,
                            'conversation_id': getattr(order, 'conversation_id', {}).id if hasattr(getattr(order, 'conversation_id', None), 'id') else None,
                        }
                        
                        # Add detailed lines if requested
                        if str(include_order_details).lower() in ('1', 'true'):
                            order_data['lines'] = [
                                {
                                    'id': line.id,
                                    'product_id': {'id': line.product_id.id, 'name': line.product_id.name} if line.product_id else None,
                                    'name': line.name,
                                    'product_uom_qty': line.product_uom_qty,
                                    'price_unit': line.price_unit,
                                    'price_subtotal': line.price_subtotal
                                } for line in order.order_line
                            ]
                        
                        orders_data.append(order_data)
            except Exception as e:
                _logger.warning(f"Error loading orders for partner {partner.name}: {str(e)}")
                total_orders = 0
                total_invoiced = 0.0
            
            # Filters đã được áp dụng ở domain level, không cần filter thêm ở đây
            
            customer_data = {
                'id': partner.id,
                'name': partner.name,
                'phone': partner.phone,
                'email': partner.email,
                'mobile': partner.mobile,
                'street': partner.street,
                'street2': partner.street2,
                'city': partner.city,
                'state_id': {
                    'id': partner.state_id.id,
                    'name': partner.state_id.name
                } if partner.state_id else None,
                'country_id': {
                    'id': partner.country_id.id,
                    'name': partner.country_id.name
                } if partner.country_id else None,
                'zip': partner.zip,
                'vat': partner.vat,
                'create_date': partner.create_date.isoformat() if partner.create_date else None,
                'write_date': partner.write_date.isoformat() if partner.write_date else None,
                'customer_rank': partner.customer_rank,
                'supplier_rank': partner.supplier_rank,
                'is_company': partner.is_company,
                # Người phụ trách (từ đơn hàng gần nhất)
                'responsible_user': responsible_user,
                # Thông tin conversation
                'conversation': conversation_data,
                # Thông tin orders
                'orders': orders_data,
                # Thống kê đơn hàng với filter áp dụng
                'total_orders': total_orders,
                'total_invoiced': total_invoiced,
                'orders_by_state': orders_by_state,  # Thống kê theo state
                # Thống kê conversation
                'has_conversation': conversation_data is not None,
                'total_conversations': request.env['page.fm.conversation'].sudo().search_count([('partner_id', '=', partner.id)]) if 'page.fm.conversation' in request.env else 0,
            }
            customers_data.append(customer_data)
        
        # Trả kết quả với metadata
        result = {
            'count': len(customers_data),
            'limit': limit,
            'applied_filters': {
                'state': state,
                'order_state_custom': order_state_custom,
                'has_orders_only': has_orders_only,
                'has_conversation_only': has_conversation_only,
            },
            'items': customers_data
        }
        
        return result

    def _get_invoices_data(self, limit=None, date_from=None, date_to=None, **kwargs):
        """Get dữ liệu hóa đơn"""
        domain = [('move_type', '=', 'out_invoice')]
        
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        limit = int(limit) if limit else 1000
        invoices = request.env['account.move'].sudo().search(domain, limit=limit, order='create_date desc')
        
        invoices_data = []
        for invoice in invoices:
            invoice_data = {
                'id': invoice.id,
                'name': invoice.name,
                'partner_id': {
                    'id': invoice.partner_id.id,
                    'name': invoice.partner_id.name
                },
                'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                'invoice_date_due': invoice.invoice_date_due.isoformat() if invoice.invoice_date_due else None,
                'create_date': invoice.create_date.isoformat() if invoice.create_date else None,
                'amount_total': invoice.amount_total,
                'amount_untaxed': invoice.amount_untaxed,
                'amount_tax': invoice.amount_tax,
                'amount_residual': invoice.amount_residual,
                'state': invoice.state,
                'payment_state': invoice.payment_state,
                'invoice_origin': invoice.invoice_origin,
                'dac_deposit_invoice': getattr(invoice, 'dac_deposit_invoice', False),
                'invoice_lines': [
                    {
                        'id': line.id,
                        'product_id': {
                            'id': line.product_id.id,
                            'name': line.product_id.name
                        } if line.product_id else None,
                        'name': line.name,
                        'quantity': line.quantity,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'display_type': line.display_type
                    } for line in invoice.invoice_line_ids
                ]
            }
            invoices_data.append(invoice_data)
        
        return invoices_data

    def _get_payments_data(self, limit=None, date_from=None, date_to=None, **kwargs):
        """Get dữ liệu phiếu thu"""
        domain = [('payment_type', '=', 'inbound')]
        
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        limit = int(limit) if limit else 1000
        payments = request.env['account.payment'].sudo().search(domain, limit=limit, order='create_date desc')
        
        payments_data = []
        for payment in payments:
            payment_data = {
                'id': payment.id,
                'name': payment.name,
                'partner_id': {
                    'id': payment.partner_id.id,
                    'name': payment.partner_id.name
                } if payment.partner_id else None,
                'amount': payment.amount,
                'currency_id': {
                    'id': payment.currency_id.id,
                    'name': payment.currency_id.name
                },
                'payment_date': payment.date.isoformat() if payment.date else None,
                'create_date': payment.create_date.isoformat() if payment.create_date else None,
                'state': payment.state,
                'payment_method_line_id': {
                    'id': payment.payment_method_line_id.id,
                    'name': payment.payment_method_line_id.name
                } if payment.payment_method_line_id else None,
                'memo': getattr(payment, 'memo', None),  # Thay vì communication
                # Thông tin custom nếu có
                'sale_order_origin': getattr(payment, 'sale_order_origin', None),
                'is_deposit_payment': getattr(payment, 'is_deposit_payment', False),
                'is_final_payment': getattr(payment, 'is_final_payment', False)
            }
            payments_data.append(payment_data)
        
        return payments_data

    def _get_employees_data(self, limit=None, **kwargs):
        """Get dữ liệu nhân viên - Lấy từ res.users (người phụ trách đơn hàng)"""
        limit = int(limit) if limit else 500
        
        # Lấy các users có phụ trách đơn hàng
        users_with_orders = request.env['res.users'].sudo().search([
            ('active', '=', True),
            ('share', '=', False),  # Chỉ lấy internal users
        ], limit=limit, order='create_date desc')
        
        employees_data = []
        for user in users_with_orders:
            # Đếm số đơn hàng phụ trách
            order_count = request.env['sale.order'].sudo().search_count([
                ('user_id', '=', user.id)
            ])
            
            # Lấy thông tin từ employee record nếu có
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1) if 'hr.employee' in request.env else None
            
            employee_data = {
                'id': user.id,
                'name': user.name,
                'login': user.login,
                'email': user.email,
                'phone': user.phone,
                'mobile': user.mobile,
                'active': user.active,
                'create_date': user.create_date.isoformat() if user.create_date else None,
                'last_login': user.login_date.isoformat() if user.login_date else None,
                'company_id': {
                    'id': user.company_id.id,
                    'name': user.company_id.name
                } if user.company_id else None,
                # Thống kê đơn hàng
                'total_orders_managed': order_count,
                # Thông tin từ HR Employee nếu có
                'hr_info': {
                    'job_title': employee.job_title if employee else None,
                    'department_id': {
                        'id': employee.department_id.id,
                        'name': employee.department_id.name
                    } if employee and employee.department_id else None,
                    'manager_id': {
                        'id': employee.parent_id.id,
                        'name': employee.parent_id.name
                    } if employee and employee.parent_id else None,
                    'work_email': employee.work_email if employee else None,
                    'work_phone': employee.work_phone if employee else None,
                } if employee else None
            }
            employees_data.append(employee_data)
        
        return employees_data
        
        return employees_data

    def _get_products_data(self, limit=None, **kwargs):
        """Get dữ liệu sản phẩm"""
        limit = int(limit) if limit else 1000
        products = request.env['product.product'].sudo().search([
            ('sale_ok', '=', True)  # Chỉ lấy sản phẩm có thể bán
        ], limit=limit, order='create_date desc')
        
        products_data = []
        for product in products:
            product_data = {
                'id': product.id,
                'name': product.name,
                'default_code': product.default_code,
                'barcode': product.barcode,
                'list_price': product.list_price,
                'standard_price': product.standard_price,
                'type': product.type,
                'categ_id': {
                    'id': product.categ_id.id,
                    'name': product.categ_id.name
                },
                'uom_id': {
                    'id': product.uom_id.id,
                    'name': product.uom_id.name
                },
                'active': product.active,
                'sale_ok': product.sale_ok,
                'purchase_ok': product.purchase_ok,
                'create_date': product.create_date.isoformat() if product.create_date else None,
                # Sử dụng getattr để tránh lỗi nếu field không tồn tại
                'qty_available': getattr(product, 'qty_available', 0),
                'virtual_available': getattr(product, 'virtual_available', 0)
            }
            products_data.append(product_data)
        
        return products_data

    def _get_summary_stats(self, **kwargs):
        """Get thống kê tổng quan"""
        # Kiểm tra modules có tồn tại không
        total_employees = 0
        if 'hr.employee' in request.env:
            total_employees = request.env['hr.employee'].sudo().search_count([])
            
        return {
            'total_orders': request.env['sale.order'].sudo().search_count([]),
            'total_customers': request.env['res.partner'].sudo().search_count([('customer_rank', '>', 0)]),
            'total_invoices': request.env['account.move'].sudo().search_count([('move_type', '=', 'out_invoice')]),
            'total_payments': request.env['account.payment'].sudo().search_count([('payment_type', '=', 'inbound')]),
            'total_employees': total_employees,
            'total_products': request.env['product.product'].sudo().search_count([('sale_ok', '=', True)]),
            'total_revenue_this_month': self._get_monthly_revenue(),
            'orders_by_state': self._get_orders_by_state()
        }

    def _get_monthly_revenue(self):
        """Tính doanh thu tháng hiện tại"""
        current_month_start = fields.Date.today().replace(day=1)
        orders = request.env['sale.order'].sudo().search([
            ('date_order', '>=', current_month_start),
            ('state', 'in', ['sale', 'done'])
        ])
        return sum(orders.mapped('amount_total'))

    def _get_orders_by_state(self):
        """Thống kê đơn hàng theo trạng thái"""
        states = ['draft', 'sent', 'sale', 'done', 'cancel']
        result = {}
        for state in states:
            count = request.env['sale.order'].sudo().search_count([('state', '=', state)])
            result[state] = count
        
        # Thống kê custom state nếu có
        if hasattr(request.env['sale.order'], 'order_state_custom'):
            custom_states = ['quotation', 'deposit', 'production', 'delivery', 'payment']
            result['custom_states'] = {}
            for state in custom_states:
                count = request.env['sale.order'].sudo().search_count([('order_state_custom', '=', state)])
                result['custom_states'][state] = count
        
        return result

    # --- MESSAGES EXPORT -------------------------------------------------
    @http.route('/dac_erp/api/export/messages', type='http', auth='public', csrf=False, methods=['GET'])
    def export_messages_data(self,
                            conversation_id=None,
                            conversation_fm_id=None,
                            date=None,            # YYYY-MM-DD (lấy đúng 1 ngày)
                            date_from=None,       # YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS
                            date_to=None,
                            limit=None,
                            offset=0,
                            asc='1',              # '1' = ASC, '0' = DESC
                            include_raw='0',      # '1' để gửi cả raw_json_message
                            **kwargs):
        """
        Trả về danh sách message của 1 conversation, có lọc theo ngày.
        BẮT BUỘC truyền 1 trong 2: conversation_id (Odoo ID) hoặc conversation_fm_id (ID từ Pages/Pancake).
        """
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            data = self._get_messages_data(
                conversation_id=conversation_id,
                conversation_fm_id=conversation_fm_id,
                date=date,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
                asc=asc,
                include_raw=include_raw,
            )
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_messages_data: {e}", exc_info=True)
            return http.Response(
                json.dumps({'error': f'Lỗi khi export messages: {e}'}),
                content_type='application/json',
                status=500
            )

    def _get_messages_data(self,
                        conversation_id=None,
                        conversation_fm_id=None,
                        date=None,
                        date_from=None,
                        date_to=None,
                        limit=None,
                        offset=0,
                        asc='1',
                        include_raw='0',
                        **kwargs):
        """Lấy dữ liệu message theo conversation + ngày."""
        domain = []

        # --- bắt buộc: xác định conversation ---
        if conversation_id:
            try:
                conversation_id = int(conversation_id)
            except Exception:
                raise ValueError("conversation_id phải là số nguyên.")
            domain.append(('conversation_id', '=', conversation_id))
        elif conversation_fm_id:
            domain.append(('conversation_id.conversation_fm_id', '=', conversation_fm_id))
        else:
            raise ValueError("Thiếu conversation_id hoặc conversation_fm_id.")

        # --- chuẩn hoá ngày ---
        # Nếu có 'date' => lấy trọn ngày đó
        if date and (not date_from and not date_to):
            date_from = f"{date} 00:00:00"
            date_to   = f"{date} 23:59:59"

        if date_from:
            domain.append(('inserted_at_fm', '>=', date_from))
        if date_to:
            domain.append(('inserted_at_fm', '<=', date_to))

        # --- paging & sort ---
        limit = int(limit) if limit else 200
        offset = int(offset) if offset else 0
        order = 'inserted_at_fm asc' if str(asc) in ('1', 'true', 'True') else 'inserted_at_fm desc'

        Message = request.env['page.fm.message'].sudo()
        messages = Message.search(domain, limit=limit, offset=offset, order=order)

        rows = []
        for m in messages:
            # attachments_json có thể là str; parse an toàn
            try:
                attachments = json.loads(m.attachments_json) if m.attachments_json else None
            except Exception:
                attachments = m.attachments_json

            row = {
                # khóa chính
                'id': m.id,
                'message_fm_id': getattr(m, 'message_fm_id', None),

                # thông tin conversation (đủ để đối soát)
                'conversation': {
                    'id': m.conversation_id.id if m.conversation_id else None,
                    'name': m.conversation_id.display_name if m.conversation_id else None,
                    'conversation_fm_id': getattr(m.conversation_id, 'conversation_fm_id', None),
                    'page': {
                        'id': m.conversation_id.page_fm_page_id.id if m.conversation_id and m.conversation_id.page_fm_page_id else None,
                        'name': m.conversation_id.page_fm_page_id.name if m.conversation_id and m.conversation_id.page_fm_page_id else None,
                        'page_fm_id_str': getattr(m.conversation_id.page_fm_page_id, 'page_fm_id_str', None),
                    } if m.conversation_id else None,
                },

                # mốc thời gian
                'inserted_at_fm': m.inserted_at_fm.isoformat() if getattr(m, 'inserted_at_fm', None) else None,
                'previous_time':  m.previous_time.isoformat()  if getattr(m, 'previous_time', None)  else None,

                # người gửi / staff
                'sender_name_fm': getattr(m, 'sender_name_fm', None),
                'staff_name_fm':  getattr(m, 'staff_name_fm', None),
                'staff_id_fm':    getattr(m, 'staff_id_fm', None),
                'staff_user': ({
                    'id': m.staff.id,
                    'name': m.staff.display_name
                } if getattr(m, 'staff', False) else None),

                # nội dung
                'content_html': getattr(m, 'content_html', None),
                'type_content': getattr(m, 'type_content', None),
                'url_content':  getattr(m, 'url_content', None),
                'attachments':  attachments,
            }

            if str(include_raw) in ('1', 'true', 'True'):
                row['raw_json_message'] = getattr(m, 'raw_json_message', None)

            rows.append(row)

        return {
            'count': len(rows),
            'limit': limit,
            'offset': offset,
            'order': order,
            'items': rows,
        }
    # --- /MESSAGES EXPORT ------------------------------------------------


    # --- CONVERSATIONS EXPORT (DEPRECATED - Use /conversation_info instead) ---
    # The /export/conversations endpoint has been removed.
    # Please use /export/conversation_info with the same parameters.
    # --- /CONVERSATIONS EXPORT -------------------------------------------------
    

    # --- /UPDATE CONVERSATION STATUS -------------------------------------------
    
    @http.route('/dac_erp/api/debug/link_order_conversation', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def debug_link_order_conversation(self, order_id=None, conversation_id=None, **kwargs):
        """Debug API để link order với conversation"""
        auth_error = self._check_export_api_key()
        if auth_error:
            return auth_error
        try:
            if not order_id or not conversation_id:
                return http.Response(
                    json.dumps({'error': 'Cần truyền order_id và conversation_id'}),
                    content_type='application/json',
                    status=400
                )
            
            order = request.env['sale.order'].sudo().browse(int(order_id))
            conversation = request.env['page.fm.conversation'].sudo().browse(int(conversation_id))
            
            if not order.exists():
                return http.Response(
                    json.dumps({'error': f'Không tìm thấy order ID {order_id}'}),
                    content_type='application/json',
                    status=404
                )
                
            if not conversation.exists():
                return http.Response(
                    json.dumps({'error': f'Không tìm thấy conversation ID {conversation_id}'}),
                    content_type='application/json',
                    status=404
                )
            
            # Link conversation
            order.conversation_id = conversation.id
            
            result = {
                'success': True,
                'order': {
                    'id': order.id,
                    'name': order.name,
                    'partner': order.partner_id.name,
                },
                'conversation': {
                    'id': conversation.id,
                    'pancake_id': conversation.conversation_fm_id,
                    'partner': conversation.partner_id.name if conversation.partner_id else None,
                },
                'linked': True
            }
            
            return http.Response(
                json.dumps(result, ensure_ascii=False),
                content_type='application/json',
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Error in debug_link_order_conversation: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': str(e)}),
                content_type='application/json',
                status=500
            )
class DacConversationApi(http.Controller):

    @http.route('/dac_erp/api/conversation/update_status', type='json', auth='public', methods=['POST'], csrf=False)
    def update_conversation_status(self, **payload):
        """
        API tối ưu để cập nhật trạng thái conversation:
        
        Payload structure:
        {
          "conversation_id": 123,                    // ID conversation (bắt buộc)
          "suggestion": "Gợi ý xử lý từ AI...",      // Ghi chú & gợi ý (tùy chọn)
          "status_state": "new|recontact|waiting|done", // Trạng thái (tùy chọn)
          "require_processing": true|false,          // Yêu cầu xử lý (tùy chọn)
          "mark_read": true|false                    // Đánh dấu đã đọc (tùy chọn)
        }
        
        Các cách nhận diện conversation (chọn 1):
        - conversation_id: Odoo ID
        - id: Legacy Odoo ID  
        - conversation_fm_id: External Pages/Pancake ID
        """
        try:
            data = request.get_json_data() or payload
            Conv = request.env['page.fm.conversation'].sudo()
            rec = None
            
            # Tìm conversation theo 3 cách khác nhau
            if data.get('conversation_id'):
                conv_id = int(data['conversation_id'])
                rec = Conv.browse(conv_id)
            elif data.get('id'):
                rec = Conv.browse(int(data['id']))
            elif data.get('conversation_fm_id'):
                rec = Conv.search([('conversation_fm_id', '=', data['conversation_fm_id'])], limit=1)
            
            if not rec or not rec.exists():
                return {'ok': False, 'error': 'Conversation not found'}

            vals = {}
            
            # Xử lý ghi chú/gợi ý (UNIFIED field)
            if data.get('suggestion'):
                vals['suggestion_note'] = data['suggestion']
                vals['last_suggestion_at'] = fields.Datetime.now()
            elif data.get('note'):  # Legacy support
                vals['suggestion_note'] = data['note']
                vals['last_suggestion_at'] = fields.Datetime.now()
            
            # Xử lý trạng thái
            status_state = data.get('status_state')
            if status_state and status_state in ('new', 'recontact', 'waiting', 'done'):
                vals['status_state'] = status_state
                vals['status_set_by_id'] = request.env.user.id
                vals['status_set_at'] = fields.Datetime.now()
                
                # Auto-set require_processing khi done
                if status_state == 'done':
                    vals['require_processing'] = False
            
            # Xử lý require_processing
            if 'require_processing' in data:
                vals['require_processing'] = bool(data['require_processing'])
            
            # Xử lý mark_read
            if data.get('mark_read') and 'is_unread_fm' in Conv._fields:
                vals['is_unread_fm'] = not bool(data['mark_read'])  # true = đã đọc => is_unread_fm = False

            # Cập nhật nếu có thay đổi
            if vals:
                rec.write(vals)
                # Trigger compute status_label
                rec._compute_status_label()
                return {'ok': True, 'id': rec.id, 'updated_fields': list(vals.keys())}
            else:
                return {'ok': True, 'id': rec.id, 'message': 'No changes made'}
        
        except Exception as e:
            _logger.error(f"Error in update_conversation_status: {str(e)}", exc_info=True)
            return {'ok': False, 'error': str(e)}

    @http.route('/dac_erp/api/conversation/toggle_checklist', type='json', auth='public', methods=['POST'], csrf=False)
    def toggle_checklist(self, **payload):
        """
        DEPRECATED: Sử dụng toggle_require_processing thay thế
        Body JSON: { "id": 123 } hoặc { "conversation_fm_id": "xxx" }
        """
        Conv = request.env['page.fm.conversation'].sudo()
        rec = None
        if payload.get('id'):
            rec = Conv.browse(int(payload['id']))
        elif payload.get('conversation_fm_id'):
            rec = Conv.search([('conversation_fm_id', '=', payload['conversation_fm_id'])], limit=1)
        if not rec:
            return {'ok': False, 'error': 'Conversation not found'}
        
        # Chuyển đổi sang dùng require_processing logic
        result = rec.action_toggle_require_processing()
        return {'ok': True, 'result': result}
    
    @http.route('/dac_erp/api/conversation/toggle_require_processing', type='json', auth='public', methods=['POST'], csrf=False)
    def toggle_require_processing(self, **payload):
        """
        API mới: Toggle trạng thái yêu cầu xử lý
        Body JSON: { "conversation_id": 123 } hoặc { "conversation_fm_id": "xxx" }
        """
        Conv = request.env['page.fm.conversation'].sudo()
        rec = None
        if payload.get('conversation_id'):
            rec = Conv.browse(int(payload['conversation_id']))
        elif payload.get('id'):  # Legacy support
            rec = Conv.browse(int(payload['id']))
        elif payload.get('conversation_fm_id'):
            rec = Conv.search([('conversation_fm_id', '=', payload['conversation_fm_id'])], limit=1)
        
        if not rec:
            return {'ok': False, 'error': 'Conversation not found'}
        
        result = rec.action_toggle_require_processing()
        return {'ok': True, 'result': result}
        return {'ok': True, 'checklist_ok': rec.checklist_ok}