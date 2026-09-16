# -*- coding: utf-8 -*-
import json
import logging
from datetime import date, datetime, time, timedelta

import pytz

from odoo import fields, http
from odoo.http import request

from .data_export_controller import DataExportController

_logger = logging.getLogger(__name__)


class DataExportV2Controller(DataExportController):
    """Canonical v2 API endpoints for AI-agent analytics."""

    V2_WRITE_API_KEY_PARAM = 'dac_erp.api_v2_write_key'
    V2_ORDER_WRITE_FIELDS = {
        'partner_id',
        'conversation_id',
        'user_id',
        'client_order_ref',
        'order_number',
        'note',
        'delivery_address',
        'installation_address',
        'has_deposit',
        'deposit_amount',
        'production_deadline',
        'order_lines',
        'line_mode',
    }
    V2_ORDER_IMMUTABLE_UPDATE_FIELDS = {'partner_id', 'conversation_id'}
    V2_ORDER_LINE_FIELDS = {
        'id',
        'product_id',
        'name',
        'description',
        'quantity',
        'price_unit',
        'discount',
        'tax_ids',
        'height',
        'width',
        'display_type',
        'action',
    }
    V2_ORDER_LINE_DISPLAY_TYPES = {'line_note', 'line_section'}
    V2_ORDER_LINE_ACTIONS = {'upsert', 'delete'}
    V2_ORDER_PROTECTED_PRODUCT_CODES = {'DEPOSIT', 'DEDUCT_DEPOSIT'}

    # ---------------------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------------------
    def _raw_json_response(self, data, status_code=200):
        return http.Response(
            json.dumps(data, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status_code,
        )

    def _get_env(self, env=None):
        return env if env is not None else request.env

    def _get_timezone(self, env=None, params=None):
        env = self._get_env(env)
        tzname = None
        if params:
            tzname = params.get('tz')
        if not tzname:
            try:
                tzname = request.httprequest.args.get('tz')
            except Exception:
                tzname = None
        tzname = tzname or env.context.get('tz') or 'UTC'
        try:
            return pytz.timezone(tzname)
        except Exception:
            return pytz.UTC

    def _to_utc_naive(self, value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = pytz.UTC.localize(value)
        return value.astimezone(pytz.UTC).replace(tzinfo=None)

    def _to_local_datetime(self, value, tz):
        if not value:
            return None
        if value.tzinfo is None:
            value = pytz.UTC.localize(value)
        return value.astimezone(tz)

    def _serialize_value(self, value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    def _write_json_response(self, success=True, data=None, message=None, error=None, status_code=200):
        payload = {
            'success': bool(success),
            'message': message,
            'status_code': status_code,
        }
        if success:
            payload['data'] = data
        else:
            payload['error'] = error or message
        return http.Response(
            json.dumps(payload, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status_code,
        )

    def _as_bool(self, value, field_name):
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in ('1', 'true', 't', 'yes', 'y'):
            return True
        if normalized in ('0', 'false', 'f', 'no', 'n'):
            return False
        raise ValueError("%s must be one of 1,0,true,false" % field_name)

    def _as_int(self, value, field_name):
        if value is None or value == '':
            return None
        try:
            return int(value)
        except Exception as exc:
            raise ValueError("%s must be an integer" % field_name) from exc

    def _as_float(self, value, field_name):
        if value is None or value == '':
            return None
        try:
            return float(value)
        except Exception as exc:
            raise ValueError("%s must be a number" % field_name) from exc

    def _normalize_limit_offset(self, limit=None, offset=0, default_limit=100):
        try:
            limit_value = int(limit) if limit else default_limit
        except Exception as exc:
            raise ValueError("limit must be an integer") from exc
        try:
            offset_value = int(offset) if offset else 0
        except Exception as exc:
            raise ValueError("offset must be an integer") from exc
        if limit_value < 0:
            raise ValueError("limit must be >= 0")
        if offset_value < 0:
            raise ValueError("offset must be >= 0")
        return limit_value, offset_value

    def _parse_datetime_value(self, raw_value, tz, is_end=False):
        if raw_value is None or raw_value == '':
            return None
        value = str(raw_value).strip()
        if value.lower() == 'today':
            local_day = datetime.now(tz).date()
            local_dt = datetime.combine(local_day, time.max if is_end else time.min)
            return self._to_utc_naive(tz.localize(local_dt))
        if len(value) == 10:
            local_day = datetime.strptime(value, '%Y-%m-%d').date()
            local_dt = datetime.combine(local_day, time.max if is_end else time.min)
            return self._to_utc_naive(tz.localize(local_dt))
        try:
            dt_value = datetime.fromisoformat(value)
        except ValueError:
            dt_value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        if dt_value.tzinfo is None:
            dt_value = tz.localize(dt_value)
        return self._to_utc_naive(dt_value)

    def _parse_datetime_window(self, env=None, params=None, date_value=None, date_from=None, date_to=None):
        params = params or {}
        env = self._get_env(env)
        tz = self._get_timezone(env=env, params=params)
        dt_from = None
        dt_to = None
        if date_value and not date_from and not date_to:
            dt_from = self._parse_datetime_value(date_value, tz, is_end=False)
            dt_to = self._parse_datetime_value(date_value, tz, is_end=True)
        else:
            dt_from = self._parse_datetime_value(date_from, tz, is_end=False) if date_from else None
            dt_to = self._parse_datetime_value(date_to, tz, is_end=True) if date_to else None
        return {
            'tz': tz,
            'dt_from_utc': dt_from,
            'dt_to_utc': dt_to,
        }

    def _parse_day_value(self, raw_value, tz, field_name):
        if raw_value is None or raw_value == '':
            return None
        value = str(raw_value).strip().lower()
        if value == 'today':
            return datetime.now(tz).date()
        try:
            return datetime.strptime(str(raw_value).strip(), '%Y-%m-%d').date()
        except Exception as exc:
            raise ValueError("%s must be today or YYYY-MM-DD" % field_name) from exc

    def _parse_day_window(self, env=None, params=None, prefix=''):
        params = params or {}
        env = self._get_env(env)
        tz = self._get_timezone(env=env, params=params)
        if prefix:
            single_key = '%s_date' % prefix
            from_key = '%s_date_from' % prefix
            to_key = '%s_date_to' % prefix
        else:
            single_key = 'date'
            from_key = 'date_from'
            to_key = 'date_to'

        single_value = params.get(single_key)
        from_value = params.get(from_key)
        to_value = params.get(to_key)
        if single_value and (from_value or to_value):
            raise ValueError("%s cannot be combined with %s or %s" % (single_key, from_key, to_key))

        local_from = None
        local_to = None
        if single_value:
            local_from = self._parse_day_value(single_value, tz, single_key)
            local_to = local_from
        else:
            local_from = self._parse_day_value(from_value, tz, from_key) if from_value else None
            local_to = self._parse_day_value(to_value, tz, to_key) if to_value else None

        dt_from_utc = None
        dt_to_utc = None
        if local_from:
            dt_from_utc = self._to_utc_naive(tz.localize(datetime.combine(local_from, time.min)))
        if local_to:
            dt_to_utc = self._to_utc_naive(tz.localize(datetime.combine(local_to, time.max)))

        return {
            'tz': tz,
            'date_from': local_from,
            'date_to': local_to,
            'dt_from_utc': dt_from_utc,
            'dt_to_utc': dt_to_utc,
        }

    def _get_v2_write_env(self, env=None):
        env = self._get_env(env)
        return env(user=env.ref('base.user_admin').id)

    def _get_v2_write_context(self):
        return {
            'mail_create_nolog': True,
            'mail_create_nosubscribe': True,
            'mail_notrack': True,
            'tracking_disable': True,
            'mail_post_autofollow': False,
            'mail_notify_force_send': False,
            'mail_notify_noemail': True,
        }

    def _ensure_v2_write_api_key(self, env=None, headers=None, provided_key=None):
        env = self._get_v2_write_env(env)
        expected_key = env['ir.config_parameter'].sudo().get_param(self.V2_WRITE_API_KEY_PARAM)
        if not expected_key:
            raise RuntimeError("Write API key is not configured in ir.config_parameter")
        if provided_key is None:
            if headers is None:
                headers = getattr(getattr(request, 'httprequest', None), 'headers', {})
            provided_key = headers.get('X-API-KEY')
        if not provided_key or provided_key != expected_key:
            raise PermissionError("Unauthorized: Invalid or missing X-API-KEY")
        return True

    def _get_v2_json_payload(self, payload=None):
        if payload is not None:
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload
        try:
            payload = request.get_json_data()
        except Exception:
            raw_data = request.httprequest.data.decode('utf-8') if request.httprequest.data else ''
            if not raw_data:
                raise ValueError("JSON body is required")
            try:
                payload = json.loads(raw_data)
            except Exception as exc:
                raise ValueError("Invalid JSON body") from exc
        if payload is None:
            raise ValueError("JSON body is required")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _coerce_text_value(self, value, field_name):
        if value is None:
            return False
        if isinstance(value, str):
            return value
        raise ValueError("%s must be a string or null" % field_name)

    def _coerce_nullable_int(self, value, field_name):
        if value in (None, '', False):
            return False
        return self._as_int(value, field_name)

    def _coerce_nullable_date(self, value, field_name):
        if value in (None, '', False):
            return False
        return self._parse_day_value(value, pytz.UTC, field_name)

    def _ensure_record_exists(self, env, model_name, record_id, field_name):
        if model_name not in env.registry.models:
            raise ValueError("%s requires model %s to be installed" % (field_name, model_name))
        record = env[model_name].sudo().browse(int(record_id))
        if not record.exists():
            raise ValueError("%s does not reference an existing %s" % (field_name, model_name))
        return record

    def _is_deposit_keyword_name(self, value):
        name = (value or '').strip().lower()
        if not name:
            return False
        keywords = ('khoản cọc', 'tiền cọc', 'deposit', 'đặt cọc')
        return any(keyword in name for keyword in keywords)

    def _is_system_order_line(self, line):
        return bool(line and (line.price_unit < 0 or line._is_deposit_related()))

    def _serialize_order_line_v2(self, line):
        return {
            'id': line.id,
            'product_id': line.product_id.id if line.product_id else None,
            'name': line.name,
            'description': getattr(line, 'description', None),
            'quantity': float(line.product_uom_qty or 0.0),
            'price_unit': float(line.price_unit or 0.0),
            'discount': float(getattr(line, 'discount', 0.0) or 0.0),
            'tax_ids': list(line.tax_id.ids),
            'height': float(getattr(line, 'height', 0.0) or 0.0),
            'width': float(getattr(line, 'width', 0.0) or 0.0),
            'display_type': line.display_type or None,
        }

    def _serialize_order_v2_write_response(self, env=None, order=None):
        env = self._get_v2_write_env(env)
        order = order.sudo()
        metrics, _deposit_window = self._build_order_deposit_metrics(env=env, orders=order, params={})
        data = self._serialize_order_v2(order, metric=metrics.get(order.id, {}))
        data.update({
            'note': order.note,
            'delivery_address': getattr(order, 'delivery_address', None),
            'installation_address': getattr(order, 'installation_address', None),
            'production_deadline': self._serialize_value(getattr(order, 'production_deadline', None)),
            'order_lines': [self._serialize_order_line_v2(line) for line in order.order_line.sorted(lambda rec: (rec.sequence, rec.id))],
        })
        return data

    def _message_sender_role(self, message):
        if getattr(message, 'staff', False) or getattr(message, 'staff_name_fm', None) or getattr(message, 'staff_id_fm', None):
            return 'staff'
        if getattr(message, 'sender_name_fm', None):
            return 'customer'
        if getattr(message, 'message_fm_id', None) or getattr(message, 'content_html', None) or getattr(message, 'type_content', None):
            return 'system'
        return 'unknown'

    def _attachments_from_message(self, message):
        try:
            return json.loads(message.attachments_json) if message.attachments_json else None
        except Exception:
            return message.attachments_json

    def _parse_csv_strings(self, value, field_name):
        if value in (None, '', False):
            return []
        if isinstance(value, (list, tuple, set)):
            values = [str(item).strip() for item in value if str(item).strip()]
        else:
            values = [item.strip() for item in str(value).split(',') if item.strip()]
        if not values:
            raise ValueError("%s cannot be empty" % field_name)
        return values

    def _build_external_url(self, conversation):
        try:
            page_id = getattr(conversation, 'conv_page_fm_id', None) or (
                getattr(conversation.page_fm_page_id, 'page_fm_id_str', None)
                if getattr(conversation, 'page_fm_page_id', None)
                else None
            )
            conv_fm_id = getattr(conversation, 'conversation_fm_id', None)
            if page_id and conv_fm_id and hasattr(conversation, '_build_external_url_for_platform'):
                return conversation._build_external_url_for_platform(page_id, conv_fm_id)
        except Exception:
            return None
        return None

    # ---------------------------------------------------------------------
    # Conversation business metrics
    # ---------------------------------------------------------------------
    def _build_conversation_business_metrics(self, env=None, conversation_ids=None, customer_window=None):
        env = self._get_env(env)
        conversation_ids = [int(cid) for cid in (conversation_ids or []) if cid]
        metrics = {
            cid: {
                'last_customer_message_at': None,
                'last_staff_reply_at': None,
                'is_unreplied': False,
                'unreplied_since': None,
                '_last_message_id': None,
                '_last_message_role': None,
                '_last_message_at': None,
                '_last_customer_message_id': None,
            }
            for cid in conversation_ids
        }
        if not conversation_ids:
            return metrics

        Message = env['page.fm.message'].sudo()
        all_messages = Message.search(
            [('conversation_id', 'in', conversation_ids)],
            order='conversation_id asc, inserted_at_fm desc, id desc'
        )
        for message in all_messages:
            conv_id = message.conversation_id.id
            metric = metrics.get(conv_id)
            if metric is None:
                continue
            role = self._message_sender_role(message)
            if metric['_last_message_id'] is None:
                metric['_last_message_id'] = message.id
                metric['_last_message_role'] = role
                metric['_last_message_at'] = message.inserted_at_fm
            if role == 'staff' and metric['last_staff_reply_at'] is None:
                metric['last_staff_reply_at'] = message.inserted_at_fm

        customer_domain = [('conversation_id', 'in', conversation_ids)]
        if customer_window:
            if customer_window.get('dt_from_utc'):
                customer_domain.append(('inserted_at_fm', '>=', fields.Datetime.to_string(customer_window['dt_from_utc'])))
            if customer_window.get('dt_to_utc'):
                customer_domain.append(('inserted_at_fm', '<=', fields.Datetime.to_string(customer_window['dt_to_utc'])))
        customer_messages = Message.search(
            customer_domain,
            order='conversation_id asc, inserted_at_fm desc, id desc'
        )
        for message in customer_messages:
            if self._message_sender_role(message) != 'customer':
                continue
            conv_id = message.conversation_id.id
            metric = metrics.get(conv_id)
            if metric is None or metric['_last_customer_message_id'] is not None:
                continue
            metric['_last_customer_message_id'] = message.id
            metric['last_customer_message_at'] = message.inserted_at_fm

        for metric in metrics.values():
            is_unreplied = bool(
                metric['_last_customer_message_id']
                and metric['_last_message_id'] == metric['_last_customer_message_id']
                and metric['_last_message_role'] == 'customer'
            )
            metric['is_unreplied'] = is_unreplied
            metric['unreplied_since'] = metric['last_customer_message_at'] if is_unreplied else None

        return metrics

    def _serialize_conversation_v2(self, conversation, business_metric=None):
        business_metric = business_metric or {}
        participants = []
        for user in conversation.participant_user_ids:
            participants.append({
                'id': user.id,
                'name': user.name,
                'email': user.email,
            })

        owner = None
        if conversation.owner_id:
            owner = {
                'id': conversation.owner_id.id,
                'name': conversation.owner_id.name,
                'email': conversation.owner_id.email,
            }

        assignee_ids = []
        if conversation.owner_id:
            assignee_ids.append(conversation.owner_id.id)
        assignee_ids.extend(conversation.participant_user_ids.ids)
        assignee_ids = list(dict.fromkeys(assignee_ids))

        customer = None
        if conversation.partner_id:
            customer = {
                'id': conversation.partner_id.id,
                'name': conversation.partner_id.name,
                'phone': conversation.partner_id.phone or conversation.partner_id.mobile,
                'email': conversation.partner_id.email,
            }

        page = None
        if conversation.page_fm_page_id:
            page = {
                'id': conversation.page_fm_page_id.id,
                'name': getattr(conversation.page_fm_page_id, 'name', None),
                'page_fm_id': getattr(conversation.page_fm_page_id, 'page_fm_id_str', None),
            }

        tags = []
        pancake_tags = getattr(conversation, 'pancake_tag_ids', None) or getattr(conversation, 'tag_ids', None) or []
        for tag in pancake_tags:
            tags.append({
                'id': tag.id,
                'name': tag.name,
                'fm_id': getattr(tag, 'tag_fm_id', None),
                'color': getattr(tag, 'fm_color_hex', None),
            })

        return {
            'id': conversation.id,
            'conversation_fm_id': getattr(conversation, 'conversation_fm_id', None),
            'customer_fm_id': getattr(conversation, 'customer_fm_id', None),
            'name': conversation.name,
            'customer_name_fm': getattr(conversation, 'customer_name_fm', None),
            'customer_name_clean': getattr(conversation, 'customer_name_clean', None),
            'phone': conversation.phone,
            'platform': getattr(conversation, 'platform_fm', None),
            'updated_at_fm': self._serialize_value(getattr(conversation, 'updated_at_fm', None)),
            'last_message_at_fm': self._serialize_value(getattr(conversation, 'last_message_at_fm', None)),
            'last_message_sync_fm': self._serialize_value(getattr(conversation, 'last_message_sync_fm', None)),
            'create_date': self._serialize_value(getattr(conversation, 'create_date', None)),
            'owner': owner,
            'participants': participants,
            'participants_count': len(participants),
            'assignee_user_ids': assignee_ids,
            'customer': customer,
            'status': {
                'state': conversation.status_state,
                'label': getattr(conversation, 'status_label', None),
                'require_processing': bool(conversation.require_processing),
                'is_unread': bool(conversation.is_unread_fm),
            },
            'is_internal_conversation': bool(getattr(conversation, 'is_internal_conversation', False)),
            'last_message': {
                'snippet': getattr(conversation, 'last_message_snippet', None),
                'snippet_clean': getattr(conversation, 'last_message_snippet_clean', None),
                'id': getattr(conversation, 'last_message_id', None),
            },
            'message_count': getattr(conversation, 'message_count', 0),
            'tags': tags,
            'tags_count': len(tags),
            'page': page,
            'external_url': self._build_external_url(conversation),
            'last_customer_message_at': self._serialize_value(business_metric.get('last_customer_message_at')),
            'last_staff_reply_at': self._serialize_value(business_metric.get('last_staff_reply_at')),
            'is_unreplied': bool(business_metric.get('is_unreplied')),
            'unreplied_since': self._serialize_value(business_metric.get('unreplied_since')),
        }

    def _build_v2_conversation_domain(self, env=None, params=None):
        env = self._get_env(env)
        params = params or {}
        domain = []
        applied_filters = {}

        conversation_id = self._as_int(params.get('conversation_id'), 'conversation_id')
        if conversation_id:
            domain.append(('id', '=', conversation_id))
            applied_filters['conversation_id'] = conversation_id

        page_id = self._as_int(params.get('page_id'), 'page_id')
        if page_id:
            domain.append(('page_fm_page_id', '=', page_id))
            applied_filters['page_id'] = page_id

        page_fm_id_str = params.get('page_fm_id_str')
        if page_fm_id_str:
            domain.append(('page_fm_page_id.page_fm_id_str', '=', page_fm_id_str))
            applied_filters['page_fm_id_str'] = page_fm_id_str

        platform = params.get('platform')
        if platform:
            platform_value = str(platform).strip()
            if not platform_value:
                raise ValueError("platform cannot be empty")
            domain.append(('platform_fm', '=', platform_value))
            applied_filters['platform'] = platform_value

        status = params.get('status')
        if status:
            statuses = [item.strip() for item in str(status).split(',') if item.strip()]
            if statuses:
                domain.append(('status_state', 'in', statuses))
                applied_filters['status'] = statuses

        require_processing = self._as_bool(params.get('require_processing'), 'require_processing')
        if require_processing is not None:
            domain.append(('require_processing', '=', require_processing))
            applied_filters['require_processing'] = require_processing

        unread_value = params.get('unread_only')
        if unread_value is None:
            unread_value = params.get('has_unread')
        unread_filter = self._as_bool(unread_value, 'has_unread')
        if unread_filter is not None:
            domain.append(('is_unread_fm', '=', unread_filter))
            applied_filters['has_unread'] = unread_filter

        is_internal = self._as_bool(params.get('is_internal'), 'is_internal')
        if is_internal is not None:
            domain.append(('is_internal_conversation', '=', is_internal))
            applied_filters['is_internal'] = is_internal

        owner_id = self._as_int(params.get('owner_id'), 'owner_id')
        if owner_id:
            domain.append(('owner_id', '=', owner_id))
            applied_filters['owner_id'] = owner_id

        participant_id = self._as_int(params.get('participant_id'), 'participant_id')
        if participant_id and not owner_id:
            domain.extend(['|', ('owner_id', '=', participant_id), ('participant_user_ids', 'in', [participant_id])])
            applied_filters['participant_id'] = participant_id

        assignee_user_id = self._as_int(params.get('assignee_user_id'), 'assignee_user_id')
        if assignee_user_id:
            domain.extend(['|', ('owner_id', '=', assignee_user_id), ('participant_user_ids', 'in', [assignee_user_id])])
            applied_filters['assignee_user_id'] = assignee_user_id

        date_field = params.get('date_field') or 'last_message_at_fm'
        if date_field not in ('updated_at_fm', 'last_message_at_fm'):
            raise ValueError("date_field must be one of updated_at_fm,last_message_at_fm")

        date_window = self._parse_datetime_window(
            env=env,
            params=params,
            date_value=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
        )
        if date_window.get('dt_from_utc'):
            domain.append((date_field, '>=', fields.Datetime.to_string(date_window['dt_from_utc'])))
            applied_filters['date_from'] = self._serialize_value(date_window['dt_from_utc'])
        if date_window.get('dt_to_utc'):
            domain.append((date_field, '<=', fields.Datetime.to_string(date_window['dt_to_utc'])))
            applied_filters['date_to'] = self._serialize_value(date_window['dt_to_utc'])

        days = params.get('days')
        if days not in (None, '') and not date_window.get('dt_from_utc') and not date_window.get('dt_to_utc'):
            try:
                days_int = int(days)
            except Exception as exc:
                raise ValueError("days must be an integer") from exc
            if days_int < 0:
                raise ValueError("days must be >= 0")
            tz = self._get_timezone(env=env, params=params)
            now_local = datetime.now(tz)
            start_local = (now_local - timedelta(days=days_int)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
            domain.append((date_field, '>=', fields.Datetime.to_string(self._to_utc_naive(start_local))))
            domain.append((date_field, '<=', fields.Datetime.to_string(self._to_utc_naive(end_local))))
            applied_filters['days'] = days_int

        tag_codes = self._parse_csv_strings(params.get('tag_code'), 'tag_code') if params.get('tag_code') not in (None, '', False) else []
        if tag_codes:
            domain.append(('pancake_tag_ids.odoo_tag_code', 'in', tag_codes))
            applied_filters['tag_code'] = tag_codes
            tag_mode = str(params.get('tag_mode') or 'any').strip().lower()
            if tag_mode not in ('any', 'all'):
                raise ValueError("tag_mode must be one of any,all")
            applied_filters['tag_mode'] = tag_mode

        applied_filters['date_field'] = date_field
        return domain, applied_filters, date_field

    # ---------------------------------------------------------------------
    # Orders business metrics
    # ---------------------------------------------------------------------
    def _build_v2_order_domain(self, env=None, params=None):
        env = self._get_env(env)
        params = params or {}
        domain = []
        applied_filters = {}

        date_field = params.get('date_field') or 'date'
        if date_field not in ('date', 'date_order', 'create_date'):
            raise ValueError("date_field must be one of date,date_order,create_date")

        date_window = self._parse_datetime_window(
            env=env,
            params=params,
            date_value=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
        )
        if date_window.get('dt_from_utc'):
            domain.append((date_field, '>=', fields.Datetime.to_string(date_window['dt_from_utc'])))
            applied_filters['date_from'] = self._serialize_value(date_window['dt_from_utc'])
        if date_window.get('dt_to_utc'):
            domain.append((date_field, '<=', fields.Datetime.to_string(date_window['dt_to_utc'])))
            applied_filters['date_to'] = self._serialize_value(date_window['dt_to_utc'])

        user_id = params.get('user_id')
        if user_id:
            uid = env.user.id if user_id == 'me' else self._as_int(user_id, 'user_id')
            if uid:
                domain.append(('user_id', '=', uid))
                applied_filters['user_id'] = uid

        partner_id = self._as_int(params.get('partner_id'), 'partner_id')
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
            applied_filters['partner_id'] = partner_id

        conversation_id = self._as_int(params.get('conversation_id'), 'conversation_id')
        if conversation_id:
            domain.append(('conversation_id', '=', conversation_id))
            applied_filters['conversation_id'] = conversation_id

        pancake_conversation_id = params.get('pancake_conversation_id')
        if pancake_conversation_id:
            domain.append(('conversation_id.conversation_fm_id', '=', str(pancake_conversation_id)))
            applied_filters['pancake_conversation_id'] = str(pancake_conversation_id)

        state = params.get('state')
        if state:
            states = [item.strip() for item in str(state).split(',') if item.strip()]
            if states:
                domain.append(('order_state_custom', 'in', states))
                applied_filters['state'] = states

        custom_state = params.get('custom_state')
        if custom_state:
            states = [item.strip() for item in str(custom_state).split(',') if item.strip()]
            if states:
                domain.append(('order_state_custom', 'in', states))
                applied_filters['custom_state'] = states

        company_id = self._as_int(params.get('company_id'), 'company_id')
        if company_id:
            domain.append(('company_id', '=', company_id))
            applied_filters['company_id'] = company_id

        has_deposit = self._as_bool(params.get('has_deposit'), 'has_deposit')
        if has_deposit is not None:
            domain.append(('has_deposit', '=', has_deposit))
            applied_filters['has_deposit'] = has_deposit

        is_order_completed = self._as_bool(params.get('is_order_completed'), 'is_order_completed')
        if is_order_completed is not None:
            domain.append(('is_order_completed', '=', is_order_completed))
            applied_filters['is_order_completed'] = is_order_completed

        min_total = self._as_float(params.get('min_total'), 'min_total')
        if min_total is not None:
            domain.append(('amount_total', '>=', min_total))
            applied_filters['min_total'] = min_total

        max_total = self._as_float(params.get('max_total'), 'max_total')
        if max_total is not None:
            domain.append(('amount_total', '<=', max_total))
            applied_filters['max_total'] = max_total

        applied_filters['date_field'] = date_field
        return domain, applied_filters

    def _resolve_invoice_event_payload(self, invoice, tz):
        if invoice.invoice_date:
            sort_dt = datetime.combine(invoice.invoice_date, time.min)
            return invoice.invoice_date, sort_dt, invoice.invoice_date.isoformat()
        if invoice.create_date:
            local_dt = self._to_local_datetime(invoice.create_date, tz)
            return local_dt.date(), local_dt.replace(tzinfo=None), invoice.create_date.isoformat()
        return None, None, None

    def _build_order_deposit_metrics(self, env=None, orders=None, params=None):
        env = self._get_env(env)
        params = params or {}
        orders = orders or env['sale.order']
        tz = self._get_timezone(env=env, params=params)
        deposit_window = self._parse_day_window(env=env, params=params, prefix='deposit')
        order_map = {order.id: order for order in orders}
        order_ids_by_name = {}
        for order in orders:
            order_ids_by_name.setdefault(order.name, []).append(order.id)

        metrics = {
            order.id: {
                'deposit_invoice_count': 0,
                'latest_deposit_invoice_id': None,
                'latest_deposit_invoice_date': None,
                'deposit_payment_count': 0,
                'latest_deposit_payment_id': None,
                'latest_deposit_payment_date': None,
                '_latest_invoice_sort_dt': None,
                '_latest_payment_sort_dt': None,
                '_matching_invoice_sort_dt': None,
                '_matching_payment_sort_dt': None,
            }
            for order in orders
        }

        order_names = [order.name for order in orders if order.name]
        if not order_names:
            return metrics, deposit_window

        Move = env['account.move'].sudo()
        Payment = env['account.payment'].sudo()

        deposit_invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', 'in', order_names),
            ('dac_deposit_invoice', '=', True),
            ('state', '!=', 'cancel'),
        ], order='create_date desc, id desc')

        invoice_order_map = {}
        for invoice in deposit_invoices:
            invoice_date, invoice_sort_dt, invoice_label = self._resolve_invoice_event_payload(invoice, tz)
            related_order_ids = order_ids_by_name.get(invoice.invoice_origin, [])
            invoice_order_map[invoice.id] = related_order_ids
            in_range = True
            if deposit_window.get('date_from') and invoice_date:
                in_range = invoice_date >= deposit_window['date_from']
            if in_range and deposit_window.get('date_to') and invoice_date:
                in_range = invoice_date <= deposit_window['date_to']
            for order_id in related_order_ids:
                metric = metrics[order_id]
                metric['deposit_invoice_count'] += 1
                if invoice_sort_dt and (metric['_latest_invoice_sort_dt'] is None or invoice_sort_dt > metric['_latest_invoice_sort_dt']):
                    metric['_latest_invoice_sort_dt'] = invoice_sort_dt
                    metric['latest_deposit_invoice_id'] = invoice.id
                    metric['latest_deposit_invoice_date'] = invoice_label
                if in_range and invoice_sort_dt and (
                    metric['_matching_invoice_sort_dt'] is None or invoice_sort_dt > metric['_matching_invoice_sort_dt']
                ):
                    metric['_matching_invoice_sort_dt'] = invoice_sort_dt

        payments = env['account.payment']
        if deposit_invoices:
            payments = Payment.search([
                ('state', 'in', ['posted', 'paid']),
                ('reconciled_invoice_ids', 'in', deposit_invoices.ids),
            ], order='date desc, id desc')

        payment_seen = {order.id: set() for order in orders}
        for payment in payments:
            related_order_ids = set()
            for invoice in payment.reconciled_invoice_ids.filtered(lambda inv: inv.id in invoice_order_map):
                related_order_ids.update(invoice_order_map.get(invoice.id, []))
            if not related_order_ids:
                continue

            payment_date = payment.date or (payment.create_date.date() if payment.create_date else None)
            payment_sort_dt = datetime.combine(payment.date, time.min) if payment.date else payment.create_date
            payment_label = payment.date.isoformat() if payment.date else self._serialize_value(payment.create_date)
            in_range = True
            if deposit_window.get('date_from') and payment_date:
                in_range = payment_date >= deposit_window['date_from']
            if in_range and deposit_window.get('date_to') and payment_date:
                in_range = payment_date <= deposit_window['date_to']

            for order_id in related_order_ids:
                if payment.id not in payment_seen[order_id]:
                    payment_seen[order_id].add(payment.id)
                    metrics[order_id]['deposit_payment_count'] += 1
                metric = metrics[order_id]
                if payment_sort_dt and (metric['_latest_payment_sort_dt'] is None or payment_sort_dt > metric['_latest_payment_sort_dt']):
                    metric['_latest_payment_sort_dt'] = payment_sort_dt
                    metric['latest_deposit_payment_id'] = payment.id
                    metric['latest_deposit_payment_date'] = payment_label
                if in_range and payment_sort_dt and (
                    metric['_matching_payment_sort_dt'] is None or payment_sort_dt > metric['_matching_payment_sort_dt']
                ):
                    metric['_matching_payment_sort_dt'] = payment_sort_dt

        return metrics, deposit_window

    def _serialize_order_v2(self, order, metric=None):
        metric = metric or {}
        return {
            'id': order.id,
            'name': order.name,
            'order_number': getattr(order, 'order_number', None),
            'client_order_ref': order.client_order_ref,
            'state': getattr(order, 'order_state_custom', None),
            'order_state_custom': getattr(order, 'order_state_custom', None),
            'date': self._serialize_value(getattr(order, 'date', None)),
            'date_order': self._serialize_value(getattr(order, 'date_order', None)),
            'create_date': self._serialize_value(getattr(order, 'create_date', None)),
            'amount_total': order.amount_total,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'customer': {
                'id': order.partner_id.id,
                'name': order.partner_id.name,
                'phone': getattr(order.partner_id, 'phone', None) or getattr(order.partner_id, 'mobile', None),
            } if order.partner_id else None,
            'user_id': {
                'id': order.user_id.id,
                'name': order.user_id.name,
            } if order.user_id else None,
            'company_id': {
                'id': order.company_id.id,
                'name': order.company_id.name,
            } if order.company_id else None,
            'flags': {
                'has_deposit': bool(getattr(order, 'has_deposit', False)),
                'is_completed': bool(getattr(order, 'is_order_completed', False)),
            },
            'deposit': {
                'enabled': bool(getattr(order, 'has_deposit', False)),
                'amount': float(getattr(order, 'deposit_amount', 0.0) or 0.0),
            },
            'conversation_id': order.conversation_id.id if getattr(order, 'conversation_id', False) else None,
            'pancake_conversation_id': getattr(order.conversation_id, 'conversation_fm_id', None) if getattr(order, 'conversation_id', False) else None,
            'deposit_invoice_count': metric.get('deposit_invoice_count', 0),
            'latest_deposit_invoice_id': metric.get('latest_deposit_invoice_id'),
            'latest_deposit_invoice_date': metric.get('latest_deposit_invoice_date'),
            'deposit_payment_count': metric.get('deposit_payment_count', 0),
            'latest_deposit_payment_id': metric.get('latest_deposit_payment_id'),
            'latest_deposit_payment_date': metric.get('latest_deposit_payment_date'),
        }

    def _normalize_order_write_payload(self, env=None, payload=None, is_update=False):
        env = self._get_v2_write_env(env)
        payload = self._get_v2_json_payload(payload=payload)

        unknown_fields = sorted(set(payload) - self.V2_ORDER_WRITE_FIELDS)
        if unknown_fields:
            raise ValueError("Unsupported order fields: %s" % ', '.join(unknown_fields))

        if is_update:
            immutable_fields = sorted(field for field in self.V2_ORDER_IMMUTABLE_UPDATE_FIELDS if field in payload)
            if immutable_fields:
                raise ValueError("%s cannot be updated via this API" % ', '.join(immutable_fields))
        elif 'partner_id' not in payload:
            raise ValueError("partner_id is required")

        normalized = {}
        if 'partner_id' in payload:
            partner_id = self._coerce_nullable_int(payload.get('partner_id'), 'partner_id')
            if not partner_id:
                raise ValueError("partner_id is required")
            normalized['partner_id'] = self._ensure_record_exists(env, 'res.partner', partner_id, 'partner_id').id

        if 'conversation_id' in payload:
            conversation_id = self._coerce_nullable_int(payload.get('conversation_id'), 'conversation_id')
            if conversation_id:
                normalized['conversation_id'] = self._ensure_record_exists(
                    env, 'page.fm.conversation', conversation_id, 'conversation_id'
                ).id
            else:
                normalized['conversation_id'] = False

        if 'user_id' in payload:
            user_id = self._coerce_nullable_int(payload.get('user_id'), 'user_id')
            normalized['user_id'] = self._ensure_record_exists(env, 'res.users', user_id, 'user_id').id if user_id else False

        for text_field in ('client_order_ref', 'order_number', 'note', 'delivery_address', 'installation_address'):
            if text_field in payload:
                normalized[text_field] = self._coerce_text_value(payload.get(text_field), text_field)

        if 'has_deposit' in payload:
            if payload.get('has_deposit') is None:
                raise ValueError("has_deposit must be one of 1,0,true,false")
            normalized['has_deposit'] = self._as_bool(payload.get('has_deposit'), 'has_deposit')

        if 'deposit_amount' in payload:
            if payload.get('deposit_amount') is None:
                raise ValueError("deposit_amount must be a number")
            deposit_amount = self._as_float(payload.get('deposit_amount'), 'deposit_amount')
            if deposit_amount is None:
                raise ValueError("deposit_amount must be a number")
            if deposit_amount < 0:
                raise ValueError("deposit_amount must be >= 0")
            normalized['deposit_amount'] = deposit_amount

        if 'production_deadline' in payload:
            normalized['production_deadline'] = self._coerce_nullable_date(
                payload.get('production_deadline'),
                'production_deadline',
            )

        order_lines = payload.get('order_lines') if 'order_lines' in payload else None
        if order_lines is not None and not isinstance(order_lines, list):
            raise ValueError("order_lines must be an array")

        line_mode = payload.get('line_mode')
        if 'line_mode' in payload and line_mode not in ('replace', 'patch'):
            raise ValueError("line_mode must be one of replace,patch")
        if is_update and order_lines is not None and line_mode not in ('replace', 'patch'):
            raise ValueError("line_mode is required when order_lines is provided")
        if not is_update and 'line_mode' in payload:
            raise ValueError("line_mode is only supported on PATCH /dac_erp/api/v2/orders/<id>")

        return {
            'order_vals': normalized,
            'order_lines': order_lines,
            'line_mode': line_mode,
        }

    def _normalize_tax_ids(self, env, value, field_name):
        if value in (None, False):
            return None
        if not isinstance(value, list):
            raise ValueError("%s must be an array of integers" % field_name)
        tax_ids = []
        for idx, item in enumerate(value):
            tax_id = self._as_int(item, '%s[%s]' % (field_name, idx))
            tax_ids.append(tax_id)
        if tax_ids:
            taxes = env['account.tax'].sudo().browse(tax_ids).exists()
            if len(taxes) != len(set(tax_ids)):
                raise ValueError("%s contains unknown account.tax ids" % field_name)
        return tax_ids

    def _build_product_line_values(self, env, raw_line, index, existing_line=None):
        product_id = raw_line.get('product_id')
        if existing_line and 'product_id' not in raw_line:
            product = existing_line.product_id
        else:
            product_id = self._coerce_nullable_int(product_id, 'order_lines[%s].product_id' % index)
            if not product_id:
                raise ValueError("order_lines[%s].product_id is required for product lines" % index)
            product = self._ensure_record_exists(env, 'product.product', product_id, 'order_lines[%s].product_id' % index)

        product_code = (getattr(product, 'default_code', None) or '').strip().upper()
        if product_code in self.V2_ORDER_PROTECTED_PRODUCT_CODES:
            raise ValueError("order_lines[%s] cannot use protected deposit product %s" % (index, product.display_name))

        if raw_line.get('display_type'):
            raise ValueError("order_lines[%s].display_type is not allowed for product lines" % index)

        quantity_value = raw_line.get('quantity', existing_line.product_uom_qty if existing_line else 1.0)
        quantity = self._as_float(quantity_value, 'order_lines[%s].quantity' % index)
        if quantity is None:
            quantity = 1.0

        price_value = raw_line.get('price_unit', existing_line.price_unit if existing_line else 0.0)
        price_unit = self._as_float(price_value, 'order_lines[%s].price_unit' % index)
        if price_unit is None:
            price_unit = 0.0
        if price_unit < 0:
            raise ValueError("order_lines[%s].price_unit must be >= 0" % index)

        discount_value = raw_line.get('discount', getattr(existing_line, 'discount', 0.0) if existing_line else 0.0)
        discount = self._as_float(discount_value, 'order_lines[%s].discount' % index)
        if discount is None:
            discount = 0.0
        if discount < 0 or discount > 100:
            raise ValueError("order_lines[%s].discount must be between 0 and 100" % index)

        tax_ids = self._normalize_tax_ids(
            env,
            raw_line.get('tax_ids', existing_line.tax_id.ids if existing_line else product.taxes_id.ids),
            'order_lines[%s].tax_ids' % index,
        )
        if tax_ids is None:
            tax_ids = existing_line.tax_id.ids if existing_line else product.taxes_id.ids

        name = raw_line.get('name')
        if name is None:
            name = existing_line.name if existing_line else product.display_name
        elif not isinstance(name, str):
            raise ValueError("order_lines[%s].name must be a string" % index)

        description = raw_line.get('description', getattr(existing_line, 'description', False) if existing_line else False)
        if description not in (None, False) and not isinstance(description, str):
            raise ValueError("order_lines[%s].description must be a string or null" % index)

        height = raw_line.get('height', getattr(existing_line, 'height', 0.0) if existing_line else 0.0)
        width = raw_line.get('width', getattr(existing_line, 'width', 0.0) if existing_line else 0.0)
        height = self._as_float(height, 'order_lines[%s].height' % index) if height not in (None, '') else 0.0
        width = self._as_float(width, 'order_lines[%s].width' % index) if width not in (None, '') else 0.0

        vals = {
            'product_id': product.id,
            'name': name,
            'description': description or False,
            'product_uom_qty': quantity,
            'price_unit': price_unit,
            'discount': discount,
            'tax_id': [(6, 0, tax_ids or [])],
            'display_type': False,
            'height': height or 0.0,
            'width': width or 0.0,
        }
        if getattr(product, 'uom_id', False):
            vals['product_uom'] = product.uom_id.id
        return vals

    def _build_free_text_line_values(self, env, raw_line, index, existing_line=None):
        """Dòng tự do: không cần product_id, name là bắt buộc (đặc thù in ấn)."""
        name = raw_line.get('name', existing_line.name if existing_line else None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("order_lines[%s].name is required when product_id is absent" % index)

        quantity_value = raw_line.get('quantity', existing_line.product_uom_qty if existing_line else 1.0)
        quantity = self._as_float(quantity_value, 'order_lines[%s].quantity' % index)
        if quantity is None:
            quantity = 1.0

        price_value = raw_line.get('price_unit', existing_line.price_unit if existing_line else 0.0)
        price_unit = self._as_float(price_value, 'order_lines[%s].price_unit' % index)
        if price_unit is None:
            price_unit = 0.0
        if price_unit < 0:
            raise ValueError("order_lines[%s].price_unit must be >= 0" % index)

        discount_value = raw_line.get('discount', getattr(existing_line, 'discount', 0.0) if existing_line else 0.0)
        discount = self._as_float(discount_value, 'order_lines[%s].discount' % index)
        if discount is None:
            discount = 0.0
        if discount < 0 or discount > 100:
            raise ValueError("order_lines[%s].discount must be between 0 and 100" % index)

        tax_ids = self._normalize_tax_ids(
            env,
            raw_line.get('tax_ids', existing_line.tax_id.ids if existing_line else []),
            'order_lines[%s].tax_ids' % index,
        )
        if tax_ids is None:
            tax_ids = existing_line.tax_id.ids if existing_line else []

        description = raw_line.get('description', getattr(existing_line, 'description', False) if existing_line else False)
        if description not in (None, False) and not isinstance(description, str):
            raise ValueError("order_lines[%s].description must be a string or null" % index)

        height = raw_line.get('height', getattr(existing_line, 'height', 0.0) if existing_line else 0.0)
        width = raw_line.get('width', getattr(existing_line, 'width', 0.0) if existing_line else 0.0)
        height = self._as_float(height, 'order_lines[%s].height' % index) if height not in (None, '') else 0.0
        width = self._as_float(width, 'order_lines[%s].width' % index) if width not in (None, '') else 0.0

        uom_unit = env.ref('uom.product_uom_unit', raise_if_not_found=False)
        vals = {
            'product_id': False,
            'name': name,
            'description': description or False,
            'product_uom_qty': quantity,
            'price_unit': price_unit,
            'discount': discount,
            'tax_id': [(6, 0, tax_ids or [])],
            'display_type': False,
            'height': height or 0.0,
            'width': width or 0.0,
        }
        if uom_unit:
            vals['product_uom'] = uom_unit.id
        return vals

    def _build_display_line_values(self, env, raw_line, index, existing_line=None):
        display_type = raw_line.get('display_type', existing_line.display_type if existing_line else None)
        if display_type not in self.V2_ORDER_LINE_DISPLAY_TYPES:
            raise ValueError("order_lines[%s].display_type must be one of line_note,line_section" % index)
        if raw_line.get('product_id') not in (None, '', False):
            raise ValueError("order_lines[%s].product_id is not allowed for display lines" % index)

        name = raw_line.get('name', existing_line.name if existing_line else None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("order_lines[%s].name is required for display lines" % index)
        if self._is_deposit_keyword_name(name):
            raise ValueError("order_lines[%s] cannot create or mimic deposit-related system lines" % index)

        quantity_value = raw_line.get('quantity', existing_line.product_uom_qty if existing_line else 0.0)
        quantity = self._as_float(quantity_value, 'order_lines[%s].quantity' % index) if quantity_value not in (None, '') else 0.0
        if quantity not in (0, 0.0):
            raise ValueError("order_lines[%s].quantity must be 0 for display lines" % index)

        price_value = raw_line.get('price_unit', existing_line.price_unit if existing_line else 0.0)
        price_unit = self._as_float(price_value, 'order_lines[%s].price_unit' % index) if price_value not in (None, '') else 0.0
        if price_unit not in (0, 0.0):
            raise ValueError("order_lines[%s].price_unit must be 0 for display lines" % index)

        tax_ids = raw_line.get('tax_ids')
        if tax_ids not in (None, [], False):
            raise ValueError("order_lines[%s].tax_ids must be empty for display lines" % index)

        description = raw_line.get('description', getattr(existing_line, 'description', False) if existing_line else False)
        if description not in (None, False) and not isinstance(description, str):
            raise ValueError("order_lines[%s].description must be a string or null" % index)

        height = raw_line.get('height', getattr(existing_line, 'height', 0.0) if existing_line else 0.0)
        width = raw_line.get('width', getattr(existing_line, 'width', 0.0) if existing_line else 0.0)
        height = self._as_float(height, 'order_lines[%s].height' % index) if height not in (None, '') else 0.0
        width = self._as_float(width, 'order_lines[%s].width' % index) if width not in (None, '') else 0.0

        return {
            'display_type': display_type,
            'name': name,
            'description': description or False,
            'product_id': False,
            'product_uom_qty': 0.0,
            'price_unit': 0.0,
            'tax_id': [(6, 0, [])],
            'height': height or 0.0,
            'width': width or 0.0,
            'product_uom': False,
        }

    def _normalize_order_line_upsert(self, env, raw_line, index, existing_line=None):
        if not isinstance(raw_line, dict):
            raise ValueError("order_lines[%s] must be an object" % index)
        unknown_fields = sorted(set(raw_line) - self.V2_ORDER_LINE_FIELDS)
        if unknown_fields:
            raise ValueError("Unsupported order_lines[%s] fields: %s" % (index, ', '.join(unknown_fields)))

        if raw_line.get('display_type') not in (None, '', False):
            return self._build_display_line_values(env, raw_line, index, existing_line=existing_line)
        if raw_line.get('product_id') not in (None, '', False):
            return self._build_product_line_values(env, raw_line, index, existing_line=existing_line)
        if existing_line and existing_line.display_type:
            return self._build_display_line_values(env, raw_line, index, existing_line=existing_line)
        if existing_line and existing_line.product_id:
            return self._build_product_line_values(env, raw_line, index, existing_line=existing_line)
        if existing_line and not existing_line.product_id:
            # dòng tự do đang được patch (không có product_id)
            return self._build_free_text_line_values(env, raw_line, index, existing_line=existing_line)
        if raw_line.get('name') not in (None, '', False):
            # tạo mới dòng tự do: name bắt buộc, không cần product_id
            return self._build_free_text_line_values(env, raw_line, index)
        raise ValueError("order_lines[%s] must define product_id, name, or display_type" % index)

    def _normalize_order_line_operations(self, env=None, order=None, order_lines=None, line_mode=None):
        env = self._get_v2_write_env(env)
        order_lines = order_lines or []
        if not isinstance(order_lines, list):
            raise ValueError("order_lines must be an array")

        if line_mode == 'replace':
            operations = []
            for index, raw_line in enumerate(order_lines):
                if not isinstance(raw_line, dict):
                    raise ValueError("order_lines[%s] must be an object" % index)
                if raw_line.get('action') not in (None, '', 'upsert'):
                    raise ValueError("order_lines[%s].action must be omitted or upsert for replace mode" % index)
                vals = self._normalize_order_line_upsert(env, raw_line, index)
                operations.append({'action': 'create', 'vals': vals})
            return operations

        if line_mode != 'patch':
            raise ValueError("line_mode must be one of replace,patch")
        if not order:
            raise ValueError("order is required for patch line operations")

        seen_line_ids = set()
        operations = []
        for index, raw_line in enumerate(order_lines):
            if not isinstance(raw_line, dict):
                raise ValueError("order_lines[%s] must be an object" % index)
            unknown_fields = sorted(set(raw_line) - self.V2_ORDER_LINE_FIELDS)
            if unknown_fields:
                raise ValueError("Unsupported order_lines[%s] fields: %s" % (index, ', '.join(unknown_fields)))

            action = raw_line.get('action') or 'upsert'
            if action not in self.V2_ORDER_LINE_ACTIONS:
                raise ValueError("order_lines[%s].action must be one of upsert,delete" % index)

            line_id = raw_line.get('id')
            existing_line = None
            if line_id not in (None, '', False):
                line_id = self._as_int(line_id, 'order_lines[%s].id' % index)
                if line_id in seen_line_ids:
                    raise ValueError("Duplicate order_lines ids are not allowed in patch payload")
                seen_line_ids.add(line_id)
                existing_line = order.order_line.filtered(lambda line: line.id == line_id)[:1]
                if not existing_line:
                    raise ValueError("order_lines[%s].id does not belong to order %s" % (index, order.id))
                if self._is_system_order_line(existing_line):
                    raise ValueError("order_lines[%s].id targets a protected system/deposit line" % index)

            if action == 'delete':
                if not existing_line:
                    raise ValueError("order_lines[%s].id is required for delete action" % index)
                extra_fields = sorted(set(raw_line) - {'id', 'action'})
                if extra_fields:
                    raise ValueError("order_lines[%s] delete action cannot include fields: %s" % (index, ', '.join(extra_fields)))
                operations.append({'action': 'delete', 'line': existing_line})
                continue

            vals = self._normalize_order_line_upsert(env, raw_line, index, existing_line=existing_line)
            operations.append({
                'action': 'update' if existing_line else 'create',
                'line': existing_line,
                'vals': vals,
            })
        return operations

    def _apply_order_line_operations(self, env=None, order=None, order_lines=None, line_mode=None):
        env = self._get_v2_write_env(env)
        order = order.sudo()
        line_model = env['sale.order.line'].sudo().with_context(**self._get_v2_write_context())

        if line_mode == 'replace':
            editable_lines = order.order_line.filtered(lambda line: not self._is_system_order_line(line))
            if editable_lines:
                editable_lines.unlink()
            operations = self._normalize_order_line_operations(
                env=env, order=order, order_lines=order_lines, line_mode='replace'
            )
            for operation in operations:
                vals = dict(operation['vals'], order_id=order.id)
                line_model.create(vals)
            return

        operations = self._normalize_order_line_operations(env=env, order=order, order_lines=order_lines, line_mode='patch')
        for operation in operations:
            if operation['action'] == 'delete':
                operation['line'].sudo().with_context(**self._get_v2_write_context()).unlink()
            elif operation['action'] == 'update':
                operation['line'].sudo().with_context(**self._get_v2_write_context()).write(operation['vals'])
            else:
                vals = dict(operation['vals'], order_id=order.id)
                line_model.create(vals)

    def _create_v2_order(self, env=None, payload=None):
        env = self._get_v2_write_env(env)
        normalized = self._normalize_order_write_payload(env=env, payload=payload, is_update=False)
        order_vals = normalized['order_vals']
        order_lines = normalized['order_lines']

        order_model = env['sale.order'].sudo().with_context(**self._get_v2_write_context())
        with env.cr.savepoint():
            order = order_model.create(order_vals)
            if order_lines is not None:
                self._apply_order_line_operations(env=env, order=order, order_lines=order_lines, line_mode='replace')
        return self._serialize_order_v2_write_response(env=env, order=order)

    def _update_v2_order(self, order_id, env=None, payload=None):
        env = self._get_v2_write_env(env)
        order = env['sale.order'].sudo().browse(int(order_id))
        if not order.exists():
            raise LookupError("Order %s was not found" % order_id)

        normalized = self._normalize_order_write_payload(env=env, payload=payload, is_update=True)
        order_vals = normalized['order_vals']
        order_lines = normalized['order_lines']
        line_mode = normalized['line_mode']

        with env.cr.savepoint():
            if order_vals:
                order.with_context(**self._get_v2_write_context()).write(order_vals)
            if order_lines is not None:
                self._apply_order_line_operations(env=env, order=order, order_lines=order_lines, line_mode=line_mode)
        return self._serialize_order_v2_write_response(env=env, order=order)

    # ---------------------------------------------------------------------
    # Public v2 helpers used by routes and tests
    # ---------------------------------------------------------------------
    def _get_v2_conversations_data(self, env=None, **params):
        env = self._get_env(env)
        Conv = env['page.fm.conversation'].sudo()
        Message = env['page.fm.message'].sudo()

        limit, offset = self._normalize_limit_offset(params.get('limit'), params.get('offset'), default_limit=100)
        domain, applied_filters, date_field = self._build_v2_conversation_domain(env=env, params=params)

        staff_user_id = self._as_int(params.get('staff_user_id'), 'staff_user_id')
        if staff_user_id:
            conv_ids = Message.search([('staff', '=', staff_user_id)]).mapped('conversation_id').ids
            if not conv_ids:
                return {
                    'count': 0,
                    'total': 0,
                    'limit': limit,
                    'offset': offset,
                    'order': '%s desc, id desc' % date_field,
                    'applied_filters': dict(applied_filters, staff_user_id=staff_user_id),
                    'items': [],
                }
            domain.append(('id', 'in', conv_ids))
            applied_filters['staff_user_id'] = staff_user_id

        unreplied = self._as_bool(params.get('unreplied'), 'unreplied')
        unreplied_window = self._parse_day_window(env=env, params=params, prefix='unreplied')
        if unreplied_window.get('date_from'):
            applied_filters['unreplied_date_from'] = self._serialize_value(unreplied_window['date_from'])
        if unreplied_window.get('date_to'):
            applied_filters['unreplied_date_to'] = self._serialize_value(unreplied_window['date_to'])
        if unreplied is not None:
            applied_filters['unreplied'] = unreplied

        base_order = '%s %s, id %s' % (
            date_field,
            'asc' if str(params.get('asc', '')).lower() in ('1', 'true') else 'desc',
            'asc' if str(params.get('asc', '')).lower() in ('1', 'true') else 'desc',
        )

        candidate_conversations = Conv.search(domain, order=base_order)
        business_metrics = {}

        if unreplied is not None:
            business_metrics = self._build_conversation_business_metrics(
                env=env,
                conversation_ids=candidate_conversations.ids,
                customer_window=unreplied_window,
            )
            filtered_ids = [conv.id for conv in candidate_conversations]
            tag_codes = applied_filters.get('tag_code') or []
            if tag_codes and applied_filters.get('tag_mode') == 'all':
                required_codes = set(tag_codes)
                filtered_ids = [
                    conv_id for conv_id in filtered_ids
                    if required_codes.issubset({
                        code for code in candidate_conversations.browse(conv_id).pancake_tag_ids.mapped('odoo_tag_code') if code
                    })
                ]
            filtered_ids = [
                conv_id for conv_id in filtered_ids
                if bool(business_metrics.get(conv_id, {}).get('is_unreplied')) == unreplied
            ]
            if unreplied:
                sort_rows = []
                for conv_id in filtered_ids:
                    metric = business_metrics.get(conv_id, {})
                    sort_rows.append((
                        metric.get('last_customer_message_at') or datetime.min,
                        conv_id,
                    ))
                sort_rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
                sorted_ids = [row[1] for row in sort_rows]
                page_ids = sorted_ids[offset:offset + limit]
                total = len(sorted_ids)
                page_conversations = Conv.browse(page_ids).exists()
                order_value = 'last_customer_message_at desc, id desc'
            else:
                total = len(filtered_ids)
                ordered_filtered = Conv.search([('id', 'in', filtered_ids)], order=base_order)
                page_conversations = ordered_filtered[offset:offset + limit]
                order_value = base_order
        else:
            filtered_conversations = candidate_conversations
            tag_codes = applied_filters.get('tag_code') or []
            if tag_codes and applied_filters.get('tag_mode') == 'all':
                required_codes = set(tag_codes)
                filtered_conversations = candidate_conversations.filtered(
                    lambda conv: required_codes.issubset({code for code in conv.pancake_tag_ids.mapped('odoo_tag_code') if code})
                )
            total = len(filtered_conversations)
            page_conversations = filtered_conversations[offset:offset + limit]
            business_metrics = self._build_conversation_business_metrics(
                env=env,
                conversation_ids=page_conversations.ids,
                customer_window=unreplied_window if unreplied_window.get('date_from') or unreplied_window.get('date_to') else None,
            )
            order_value = base_order

        items = []
        for conversation in page_conversations:
            items.append(self._serialize_conversation_v2(
                conversation,
                business_metric=business_metrics.get(conversation.id, {}),
            ))

        return {
            'count': len(items),
            'total': total,
            'limit': limit,
            'offset': offset,
            'order': order_value,
            'applied_filters': applied_filters,
            'items': items,
        }

    def _get_v2_messages_data(self, env=None, **params):
        env = self._get_env(env)
        Message = env['page.fm.message'].sudo()
        Conv = env['page.fm.conversation'].sudo()

        for invalid_name in ('unread', 'has_unread', 'unread_only'):
            if params.get(invalid_name) not in (None, ''):
                raise ValueError(
                    "Message-level unread filters are not supported. Allowed filters: "
                    "date,date_from,date_to,conversation_unreplied,staff_user_id,assignee_user_id,"
                    "conversation_id,conversation_fm_id,page_id,page_fm_id_str,sender_role,type_content,platform,tag_code"
                )

        limit, offset = self._normalize_limit_offset(params.get('limit'), params.get('offset'), default_limit=200)
        domain = []
        applied_filters = {}

        conversation_id = self._as_int(params.get('conversation_id'), 'conversation_id')
        if conversation_id:
            domain.append(('conversation_id', '=', conversation_id))
            applied_filters['conversation_id'] = conversation_id

        conversation_fm_id = params.get('conversation_fm_id')
        if conversation_fm_id:
            domain.append(('conversation_id.conversation_fm_id', '=', str(conversation_fm_id)))
            applied_filters['conversation_fm_id'] = str(conversation_fm_id)

        page_id = self._as_int(params.get('page_id'), 'page_id')
        if page_id:
            domain.append(('conversation_id.page_fm_page_id', '=', page_id))
            applied_filters['page_id'] = page_id

        page_fm_id_str = params.get('page_fm_id_str')
        if page_fm_id_str:
            domain.append(('conversation_id.page_fm_page_id.page_fm_id_str', '=', str(page_fm_id_str).strip()))
            applied_filters['page_fm_id_str'] = str(page_fm_id_str).strip()

        platform = params.get('platform')
        if platform:
            platform_value = str(platform).strip()
            if not platform_value:
                raise ValueError("platform cannot be empty")
            domain.append(('conversation_id.platform_fm', '=', platform_value))
            applied_filters['platform'] = platform_value

        type_content = params.get('type_content')
        if type_content:
            type_content_value = str(type_content).strip()
            if not type_content_value:
                raise ValueError("type_content cannot be empty")
            domain.append(('type_content', '=', type_content_value))
            applied_filters['type_content'] = type_content_value

        tag_codes = self._parse_csv_strings(params.get('tag_code'), 'tag_code') if params.get('tag_code') not in (None, '', False) else []
        if tag_codes:
            domain.append(('conversation_id.pancake_tag_ids.odoo_tag_code', 'in', tag_codes))
            applied_filters['tag_code'] = tag_codes

        staff_user_id = self._as_int(params.get('staff_user_id'), 'staff_user_id')
        if staff_user_id:
            domain.append(('staff', '=', staff_user_id))
            applied_filters['staff_user_id'] = staff_user_id

        assignee_user_id = self._as_int(params.get('assignee_user_id'), 'assignee_user_id')
        if assignee_user_id:
            assignee_conversations = Conv.search([
                '|', ('owner_id', '=', assignee_user_id), ('participant_user_ids', 'in', [assignee_user_id])
            ])
            if not assignee_conversations:
                return {
                    'count': 0,
                    'total': 0,
                    'limit': limit,
                    'offset': offset,
                    'order': 'inserted_at_fm desc, id desc',
                    'applied_filters': dict(applied_filters, assignee_user_id=assignee_user_id),
                    'items': [],
                }
            domain.append(('conversation_id', 'in', assignee_conversations.ids))
            applied_filters['assignee_user_id'] = assignee_user_id

        date_window = self._parse_datetime_window(
            env=env,
            params=params,
            date_value=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
        )
        if date_window.get('dt_from_utc'):
            domain.append(('inserted_at_fm', '>=', fields.Datetime.to_string(date_window['dt_from_utc'])))
            applied_filters['date_from'] = self._serialize_value(date_window['dt_from_utc'])
        if date_window.get('dt_to_utc'):
            domain.append(('inserted_at_fm', '<=', fields.Datetime.to_string(date_window['dt_to_utc'])))
            applied_filters['date_to'] = self._serialize_value(date_window['dt_to_utc'])

        conversation_unreplied = self._as_bool(params.get('conversation_unreplied'), 'conversation_unreplied')
        business_metrics = {}
        if conversation_unreplied is not None:
            preliminary_messages = Message.search(domain, order='inserted_at_fm desc, id desc') if domain else Message.search([])
            candidate_conv_ids = list(dict.fromkeys(preliminary_messages.mapped('conversation_id').ids))
            if not candidate_conv_ids:
                candidate_conv_ids = Conv.search([]).ids if not domain else []
            business_metrics = self._build_conversation_business_metrics(
                env=env,
                conversation_ids=candidate_conv_ids,
                customer_window=date_window,
            )
            allowed_conv_ids = [
                conv_id for conv_id in candidate_conv_ids
                if bool(business_metrics.get(conv_id, {}).get('is_unreplied')) == conversation_unreplied
            ]
            if not allowed_conv_ids:
                return {
                    'count': 0,
                    'total': 0,
                    'limit': limit,
                    'offset': offset,
                    'order': 'inserted_at_fm desc, id desc',
                    'applied_filters': dict(applied_filters, conversation_unreplied=conversation_unreplied),
                    'items': [],
                }
            domain.append(('conversation_id', 'in', allowed_conv_ids))
            applied_filters['conversation_unreplied'] = conversation_unreplied

        sender_role = params.get('sender_role')
        if sender_role not in (None, '', False):
            sender_role = str(sender_role).strip().lower()
            if sender_role not in ('customer', 'staff', 'system', 'unknown'):
                raise ValueError("sender_role must be one of customer,staff,system,unknown")
            applied_filters['sender_role'] = sender_role

        order_value = 'inserted_at_fm desc, id desc'
        candidate_messages = Message.search(domain, order=order_value)
        if sender_role:
            filtered_messages = candidate_messages.filtered(lambda message: self._message_sender_role(message) == sender_role)
        else:
            filtered_messages = candidate_messages
        total = len(filtered_messages)
        messages = filtered_messages[offset:offset + limit]

        items = []
        for message in messages:
            role = self._message_sender_role(message)
            conv_metric = business_metrics.get(message.conversation_id.id, {})
            items.append({
                'id': message.id,
                'message_fm_id': getattr(message, 'message_fm_id', None),
                'inserted_at_fm': self._serialize_value(getattr(message, 'inserted_at_fm', None)),
                'previous_time': self._serialize_value(getattr(message, 'previous_time', None)),
                'sender_role': role,
                'sender_name_fm': getattr(message, 'sender_name_fm', None),
                'staff_name_fm': getattr(message, 'staff_name_fm', None),
                'staff_id_fm': getattr(message, 'staff_id_fm', None),
                'staff_user': {
                    'id': message.staff.id,
                    'name': message.staff.display_name,
                } if getattr(message, 'staff', False) else None,
                'content_html': getattr(message, 'content_html', None),
                'type_content': getattr(message, 'type_content', None),
                'url_content': getattr(message, 'url_content', None),
                'attachments': self._attachments_from_message(message),
                'conversation': {
                    'id': message.conversation_id.id if message.conversation_id else None,
                    'name': message.conversation_id.display_name if message.conversation_id else None,
                    'conversation_fm_id': getattr(message.conversation_id, 'conversation_fm_id', None),
                    'is_unreplied': bool(conv_metric.get('is_unreplied')),
                    'last_customer_message_at': self._serialize_value(conv_metric.get('last_customer_message_at')),
                    'last_staff_reply_at': self._serialize_value(conv_metric.get('last_staff_reply_at')),
                    'page': {
                        'id': message.conversation_id.page_fm_page_id.id,
                        'name': message.conversation_id.page_fm_page_id.name,
                        'page_fm_id': getattr(message.conversation_id.page_fm_page_id, 'page_fm_id_str', None),
                    } if message.conversation_id and message.conversation_id.page_fm_page_id else None,
                },
            })

        return {
            'count': len(items),
            'total': total,
            'limit': limit,
            'offset': offset,
            'order': order_value,
            'applied_filters': applied_filters,
            'items': items,
        }

    def _get_v2_orders_data(self, env=None, **params):
        env = self._get_env(env)
        Order = env['sale.order'].sudo()

        limit, offset = self._normalize_limit_offset(params.get('limit'), params.get('offset'), default_limit=100)
        domain, applied_filters = self._build_v2_order_domain(env=env, params=params)

        deposit_event = params.get('deposit_event')
        if deposit_event not in (None, '', 'invoice_created', 'payment_received'):
            raise ValueError("deposit_event must be one of invoice_created,payment_received")
        if deposit_event:
            applied_filters['deposit_event'] = deposit_event

        has_deposit_invoice = self._as_bool(params.get('has_deposit_invoice'), 'has_deposit_invoice')
        if has_deposit_invoice is not None:
            applied_filters['has_deposit_invoice'] = has_deposit_invoice

        base_order = params.get('order') or 'date desc, id desc'
        all_orders = Order.search(domain)
        metrics, deposit_window = self._build_order_deposit_metrics(env=env, orders=all_orders, params=params)
        if deposit_window.get('date_from'):
            applied_filters['deposit_date_from'] = self._serialize_value(deposit_window['date_from'])
        if deposit_window.get('date_to'):
            applied_filters['deposit_date_to'] = self._serialize_value(deposit_window['date_to'])

        filtered_orders = []
        for order in all_orders:
            metric = metrics.get(order.id, {})
            if has_deposit_invoice is not None:
                has_invoice_value = bool(metric.get('deposit_invoice_count'))
                if has_invoice_value != has_deposit_invoice:
                    continue
            if deposit_event == 'invoice_created' and not metric.get('_matching_invoice_sort_dt'):
                continue
            if deposit_event == 'payment_received' and not metric.get('_matching_payment_sort_dt'):
                continue
            filtered_orders.append(order)

        if deposit_event == 'invoice_created':
            filtered_orders.sort(
                key=lambda order: (metrics[order.id].get('_matching_invoice_sort_dt') or datetime.min, order.id),
                reverse=True,
            )
            total = len(filtered_orders)
            page_orders = Order.browse([order.id for order in filtered_orders[offset:offset + limit]]).exists()
            order_value = 'latest_deposit_invoice_date desc, id desc'
        elif deposit_event == 'payment_received':
            filtered_orders.sort(
                key=lambda order: (metrics[order.id].get('_matching_payment_sort_dt') or datetime.min, order.id),
                reverse=True,
            )
            total = len(filtered_orders)
            page_orders = Order.browse([order.id for order in filtered_orders[offset:offset + limit]]).exists()
            order_value = 'latest_deposit_payment_date desc, id desc'
        elif has_deposit_invoice is not None:
            total = len(filtered_orders)
            page_orders = Order.search([('id', 'in', [order.id for order in filtered_orders])], limit=limit, offset=offset, order=base_order)
            order_value = base_order
        else:
            total = len(all_orders)
            page_orders = Order.search(domain, limit=limit, offset=offset, order=base_order)
            order_value = base_order

        items = [self._serialize_order_v2(order, metric=metrics.get(order.id, {})) for order in page_orders]
        return {
            'count': len(items),
            'total': total,
            'limit': limit,
            'offset': offset,
            'order': order_value,
            'applied_filters': applied_filters,
            'items': items,
        }

    @http.route('/dac_erp/api/v2/orders', type='http', auth='public', csrf=False, methods=['POST'])
    def v2_orders_create(self, **kwargs):
        del kwargs
        try:
            self._ensure_v2_write_api_key()
            payload = self._get_v2_json_payload()
            data = self._create_v2_order(payload=payload)
            return self._write_json_response(
                success=True,
                data=data,
                message='Order created successfully',
                status_code=201,
            )
        except PermissionError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=401)
        except ValueError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=400)
        except LookupError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=404)
        except Exception as exc:
            _logger.error("Error in v2_orders_create: %s", exc, exc_info=True)
            return self._write_json_response(success=False, message="Lỗi khi tạo order v2", error=str(exc), status_code=500)

    @http.route('/dac_erp/api/v2/orders/<int:order_id>', type='http', auth='public', csrf=False, methods=['PATCH'])
    def v2_orders_update(self, order_id, **kwargs):
        del kwargs
        try:
            self._ensure_v2_write_api_key()
            payload = self._get_v2_json_payload()
            data = self._update_v2_order(order_id, payload=payload)
            return self._write_json_response(
                success=True,
                data=data,
                message='Order updated successfully',
                status_code=200,
            )
        except PermissionError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=401)
        except ValueError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=400)
        except LookupError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=404)
        except Exception as exc:
            _logger.error("Error in v2_orders_update: %s", exc, exc_info=True)
            return self._write_json_response(success=False, message="Lỗi khi cập nhật order v2", error=str(exc), status_code=500)

    # ---------------------------------------------------------------------
    # Routes
    # ---------------------------------------------------------------------
    @http.route('/dac_erp/api/v2/conversations', type='http', auth='public', csrf=False, methods=['GET'])
    def v2_conversations(self, **kwargs):
        try:
            return self._raw_json_response(self._get_v2_conversations_data(**kwargs))
        except ValueError as exc:
            return self._error_response(str(exc), status_code=400)
        except Exception as exc:
            _logger.error("Error in v2_conversations: %s", exc, exc_info=True)
            return self._error_response("Lỗi khi lấy conversations v2: %s" % exc, status_code=500)

    @http.route('/dac_erp/api/v2/messages', type='http', auth='public', csrf=False, methods=['GET'])
    def v2_messages(self, **kwargs):
        try:
            return self._raw_json_response(self._get_v2_messages_data(**kwargs))
        except ValueError as exc:
            return self._error_response(str(exc), status_code=400)
        except Exception as exc:
            _logger.error("Error in v2_messages: %s", exc, exc_info=True)
            return self._error_response("Lỗi khi lấy messages v2: %s" % exc, status_code=500)

    @http.route('/dac_erp/api/v2/orders', type='http', auth='public', csrf=False, methods=['GET'])
    def v2_orders(self, **kwargs):
        try:
            return self._raw_json_response(self._get_v2_orders_data(**kwargs))
        except ValueError as exc:
            return self._error_response(str(exc), status_code=400)
        except Exception as exc:
            _logger.error("Error in v2_orders: %s", exc, exc_info=True)
            return self._error_response("Lỗi khi lấy orders v2: %s" % exc, status_code=500)
