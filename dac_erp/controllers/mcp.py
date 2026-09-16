# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import html_escape

from odoo.addons.dac_erp.controllers.api_v2_controller import DataExportV2Controller
from odoo.addons.dac_erp.controllers.api_v3_conversation_controller import ConversationAIV3Controller
from odoo.addons.dac_erp.services.mcp_normalizer import (
    normalize_conversation_item,
    normalize_invoice_item,
    normalize_message_item,
    normalize_order_item,
    normalize_order_payment_snapshot,
    normalize_payment_item,
)


_logger = logging.getLogger(__name__)


def _mcp_json_default(obj):
    """Custom JSON serializer fallback.
    Converts Odoo False (empty relational/char field) to None (JSON null).
    Other non-serializable objects fall back to str().
    """
    if obj is False:
        return None
    return str(obj)


class McpHttpError(Exception):
    def __init__(self, status_code, code, message, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class MCPReadController(ConversationAIV3Controller):
    MCP_READ_KEY_PARAM = 'dac_erp.mcp_read_key'
    MCP_WRITE_KEY_PARAM = 'dac_erp.mcp_write_key'
    MCP_ORDER_LOG_MODEL = 'dac_erp.mcp.order.log'
    MCP_BULK_LOG_MODEL = 'dac_erp.mcp.bulk.log'
    MCP_AUTO_RUN_LOG_MODEL = 'dac_erp.mcp.auto.run.log'
    MCP_CUSTOMER_CARE_ACTIVITY_MARKER = '[MCP Customer Care][OpenClaw]'
    MCP_CUSTOMER_CARE_PLAN_REQUEST_ID_PLACEHOLDER = '<CALLER_MUST_SET_UNIQUE_REQUEST_ID>'
    MCP_CUSTOMER_CARE_DEFAULT_NOTE_TEMPLATE = (
        'Khach da nhan nhung chua thay nhan vien phan hoi. '
        'Muc uu tien: {care_priority}. '
        'Ly do: {care_reason}. '
        'Khach da cho khoang {waiting_minutes} phut.'
    )
    MCP_CUSTOMER_CARE_DEFAULT_FOLLOWUP_SUMMARY = 'Phan hoi khach dang cho'
    MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST = 'request'
    MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM = 'system_parameter'
    MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK = 'fallback'
    MCP_SCOPE_EXTERNAL = 'external'
    MCP_SCOPE_INTERNAL = 'internal'
    MCP_SCOPE_ALL = 'all'
    MCP_ACTIVITY_TYPE_NONE = 'none'
    MCP_ACTIVITY_TYPE_TODO = 'todo'
    MCP_ACTIVITY_TYPE_CALL = 'call'
    MCP_ACTIVITY_TYPE_FOLLOWUP = 'followup'
    MCP_ALLOWED_CUSTOMER_CARE_POLICIES = {'conservative', 'standard', 'urgent_only'}
    MCP_ALLOWED_CONVERSATION_SCOPES = {MCP_SCOPE_EXTERNAL, MCP_SCOPE_INTERNAL, MCP_SCOPE_ALL}
    MCP_CUSTOMER_CARE_REVIEW_NOTE_TYPES = {
        'internal_note',
        'warning',
        'escalation',
        'customer_commitment',
    }
    MCP_CUSTOMER_CARE_TRIAGE_PRESETS = {
        'note_only',
        'needs_staff_reply',
        'waiting_customer',
        'needs_internal_review',
        'keep_processing',
        'clear_processing_after_staff_reply',
    }
    MCP_ORDER_WRITE_ACTIONS = {
        'order_create',
        'order_update',
        'order_confirm_info',
        'order_proceed_to_production',
        'order_proceed_to_delivery',
        'order_proceed_to_installation',
        'order_create_deposit_invoice',
        'order_create_final_invoice',
        'order_confirm_deposit_invoice',
        'order_confirm_final_payment',
        'order_next_step',
    }
    MCP_ORDER_CREATE_FIELDS = {
        'partner_id',
        'conversation_id',
        'user_id',
        'order_number',
        'client_order_ref',
        'phone',
        'fulfillment_method',
        'delivery_address',
        'installation_address',
        'production_deadline',
        'has_deposit',
        'deposit_amount',
        'is_priority',
        'is_priority_today',
        'order_lines',
        'employee_confirmation',
        'confirmation_text',
        'confirmed_by_user_id',
        'request_id',
        'agent_name',
        'model_name',
        'reason',
    }
    MCP_ORDER_UPDATE_FIELDS = {
        'order_number',
        'client_order_ref',
        'phone',
        'user_id',
        'fulfillment_method',
        'delivery_address',
        'installation_address',
        'production_deadline',
        'has_deposit',
        'deposit_amount',
        'is_priority',
        'is_priority_today',
        'order_lines',
        'line_mode',
        'employee_confirmation',
        'confirmation_text',
        'confirmed_by_user_id',
        'request_id',
        'agent_name',
        'model_name',
        'reason',
    }
    MCP_ORDER_UPDATE_BLOCKED_FIELDS = {
        'partner_id',
        'conversation_id',
        'state',
        'order_state_custom',
        'is_quotation_confirmed',
        'is_deposit_confirmed',
        'is_production_confirmed',
        'is_delivery_confirmed',
        'is_installation_confirmed',
        'is_payment_confirmed',
        'is_order_completed',
        'reached_production',
        'left_production_date',
        'started_delivery',
        'started_installation',
        'design_done',
        'design_done_date',
        'design_done_user_id',
        'production_done',
        'production_done_date',
        'production_done_user_id',
    }
    MCP_ORDER_LINE_FIELDS = {
        'id',
        'product_id',
        'name',
        'description',
        'height',
        'width',
        'product_uom_qty',
        'price_unit',
        'discount',
        'tax_id',
    }
    MCP_ORDER_MUTABLE_STATES = {'quotation', 'deposit'}
    MCP_ORDER_TERMINAL_STATES = {'completed', 'cancel'}
    MCP_SERVICE_NAME = 'dac_erp_mcp'

    # ── Task API constants ─────────────────────────────────────────────
    MCP_TASK_LOG_MODEL = 'dac.erp.mcp.task.log'
    MCP_OPENCLAW_MAPPING_MODEL = 'dac.openclaw.user.mapping'
    MCP_TASK_CREATE_FIELDS = {
        'name', 'description', 'priority', 'deadline', 'remind_at',
        'order_id', 'conversation_id', 'assigned_user_id', 'notes',
        'request_id', 'agent_name',
    }
    MCP_TASK_UPDATE_FIELDS = {
        'name', 'description', 'priority', 'deadline', 'remind_at',
        'assigned_user_id', 'state', 'notes',
        'request_id', 'agent_name',
    }
    MCP_TASK_BLOCKED_STATES = {'done', 'cancelled'}

    def _mcp_error_payload(self, code, message, details=None):
        payload = {
            'ok': False,
            'error': {
                'code': code,
                'message': message,
            }
        }
        if details is not None:
            payload['error']['details'] = details
        return payload

    # Envelope shapes used by this API (A4):
    #   list   → {ok, count, total, items, _envelope_type:"list"}
    #   detail → {ok, data:{...}, _envelope_type:"detail"}
    #   context (conversation context endpoint) uses detail envelope with nested keys
    # _envelope_type is a hint for clients; it does not change other fields.

    def _mcp_list_payload(self, items, total):
        return {
            'ok': True,
            'count': len(items),
            'total': total,
            'items': items,
            '_envelope_type': 'list',
        }

    def _mcp_detail_payload(self, data):
        return {
            'ok': True,
            'data': data,
            '_envelope_type': 'detail',
        }

    def _mcp_json_response(self, data, status_code=200):
        return http.Response(
            json.dumps(data, ensure_ascii=False, default=_mcp_json_default),
            content_type='application/json',
            status=status_code,
        )

    def _request_headers(self, headers=None):
        if headers is not None:
            return headers
        try:
            return request.httprequest.headers
        except Exception:
            return {}

    def _ensure_mcp_read_api_key(self, env=None, provided_key=None, headers=None):
        env = self._get_env(env)
        headers = self._request_headers(headers=headers)
        key = provided_key
        if key is None:
            key = headers.get('X-MCP-API-KEY') or headers.get('x-mcp-api-key')
        if key is None or str(key).strip() == '':
            raise McpHttpError(401, 'missing_api_key', 'Missing X-MCP-API-KEY')

        key = str(key).strip()
        icp = env['ir.config_parameter'].sudo()
        read_key = (icp.get_param(self.MCP_READ_KEY_PARAM) or '').strip()
        write_key = (icp.get_param(self.MCP_WRITE_KEY_PARAM) or '').strip()
        accepted_keys = [value for value in (read_key, write_key) if value]
        if key not in accepted_keys:
            raise McpHttpError(403, 'invalid_api_key', 'Invalid MCP API key')
        return True

    def _ensure_mcp_write_api_key(self, env=None, provided_key=None, headers=None, read_key_code='insufficient_permission', read_key_message='MCP write key required'):
        env = self._get_env(env)
        headers = self._request_headers(headers=headers)
        key = provided_key
        if key is None:
            key = headers.get('X-MCP-API-KEY') or headers.get('x-mcp-api-key')
        if key is None or str(key).strip() == '':
            raise McpHttpError(401, 'missing_api_key', 'Missing X-MCP-API-KEY')

        key = str(key).strip()
        icp = env['ir.config_parameter'].sudo()
        write_key = (icp.get_param(self.MCP_WRITE_KEY_PARAM) or '').strip()
        read_key = (icp.get_param(self.MCP_READ_KEY_PARAM) or '').strip()
        if not write_key:
            raise RuntimeError("MCP write key is not configured in ir.config_parameter")
        if key == write_key:
            return True
        if read_key and key == read_key:
            raise McpHttpError(403, read_key_code, read_key_message)
        raise McpHttpError(403, 'invalid_api_key', 'Invalid MCP API key')

    def _normalize_capped_limit_offset(self, limit=None, offset=None, default_limit=20, max_limit=100):
        limit_value, offset_value = self._normalize_limit_offset(limit=limit, offset=offset, default_limit=default_limit)
        return min(limit_value, max_limit), offset_value

    def _parse_include_lines(self, value, default=False):
        if value in (None, ''):
            return bool(default)
        parsed = self._as_bool(value, 'include_lines')
        return bool(parsed)

    def _get_mcp_icp(self, env=None):
        env = self._get_env(env)
        return env['ir.config_parameter'].sudo()

    def _get_mcp_config_int(self, key, default_value, env=None, min_value=None):
        raw_value = (self._get_mcp_icp(env=env).get_param(key) or '').strip()
        if not raw_value:
            return default_value, False
        try:
            value = int(raw_value)
        except Exception:
            return default_value, False
        if min_value is not None and value < min_value:
            return default_value, False
        return value, True

    def _get_mcp_config_bool(self, key, default_value, env=None):
        raw_value = self._get_mcp_icp(env=env).get_param(key)
        if raw_value in (None, ''):
            return bool(default_value), False
        parsed = self._as_bool(raw_value, key)
        if parsed is None:
            return bool(default_value), False
        return bool(parsed), True

    def _get_mcp_config_text(self, key, default_value, env=None):
        value = self._get_mcp_icp(env=env).get_param(key)
        value = (value or '').strip()
        if not value:
            return default_value, False
        return value, True

    def _normalize_customer_care_urgent_minutes(self, value, default_value=120):
        if value in (None, ''):
            return default_value
        try:
            urgent_minutes = int(value)
        except Exception as exc:
            raise ValueError("urgent_minutes must be an integer") from exc
        if urgent_minutes < 0:
            raise ValueError("urgent_minutes must be >= 0")
        return urgent_minutes

    def _get_customer_care_threshold_config(self, env=None, request_sla_minutes=None, request_urgent_minutes=None):
        env = self._get_env(env)
        if request_sla_minutes not in (None, '') or request_urgent_minutes not in (None, ''):
            return {
                'sla_minutes': self._normalize_customer_care_sla_minutes(request_sla_minutes, default_value=60),
                'urgent_minutes': self._normalize_customer_care_urgent_minutes(request_urgent_minutes, default_value=120),
                'source': self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST,
            }

        sla_minutes, sla_valid = self._get_mcp_config_int(
            'dac_erp.mcp.customer_care.sla_minutes_default',
            60,
            env=env,
            min_value=0,
        )
        urgent_minutes, urgent_valid = self._get_mcp_config_int(
            'dac_erp.mcp.customer_care.urgent_minutes_default',
            120,
            env=env,
            min_value=0,
        )
        source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM if sla_valid and urgent_valid else self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK
        return {
            'sla_minutes': sla_minutes,
            'urgent_minutes': urgent_minutes,
            'source': source,
        }

    def _get_customer_care_default_policy(self, env=None):
        env = self._get_env(env)
        policy, valid = self._get_mcp_config_text(
            'dac_erp.mcp.customer_care.default_policy',
            'standard',
            env=env,
        )
        if not valid or policy not in self.MCP_ALLOWED_CUSTOMER_CARE_POLICIES:
            return 'standard', self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK
        return policy, self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM

    def _parse_mcp_working_time(self, value, field_name):
        value = (value or '').strip()
        if len(value) != 5 or value[2] != ':':
            raise ValueError("%s must be in HH:MM format" % field_name)
        hour_text, minute_text = value.split(':', 1)
        if not hour_text.isdigit() or not minute_text.isdigit():
            raise ValueError("%s must be in HH:MM format" % field_name)
        hour = int(hour_text)
        minute = int(minute_text)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("%s must be a valid time" % field_name)
        return hour * 60 + minute

    def _parse_mcp_working_days(self, value, field_name='working_days'):
        values = []
        for raw_part in str(value or '').split(','):
            part = raw_part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise ValueError("%s must only contain integers 1..7" % field_name)
            day = int(part)
            if day < 1 or day > 7:
                raise ValueError("%s must only contain integers 1..7" % field_name)
            if day not in values:
                values.append(day)
        if not values:
            raise ValueError("%s cannot be empty" % field_name)
        return values

    def _get_mcp_working_hours_config(self, env=None):
        env = self._get_env(env)
        icp = self._get_mcp_icp(env=env)
        defaults = {
            'morning_start': '08:00',
            'morning_end': '12:00',
            'afternoon_start': '13:30',
            'afternoon_end': '17:30',
            'working_days': '1,2,3,4,5,6',
            'timezone_mode': 'company',
            'fixed_timezone': 'Asia/Ho_Chi_Minh',
        }
        values = {}
        source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM
        for key, default_value in defaults.items():
            raw_value = (icp.get_param('dac_erp.mcp.working_hours.%s' % key) or '').strip()
            if not raw_value:
                raw_value = default_value
                source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK
            values[key] = raw_value
        try:
            morning_start = self._parse_mcp_working_time(values['morning_start'], 'morning_start')
            morning_end = self._parse_mcp_working_time(values['morning_end'], 'morning_end')
            afternoon_start = self._parse_mcp_working_time(values['afternoon_start'], 'afternoon_start')
            afternoon_end = self._parse_mcp_working_time(values['afternoon_end'], 'afternoon_end')
            working_days = self._parse_mcp_working_days(values['working_days'])
            if morning_start >= morning_end or afternoon_start >= afternoon_end:
                raise ValueError("working hours ranges are invalid")
        except Exception:
            source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK
            morning_start = self._parse_mcp_working_time(defaults['morning_start'], 'morning_start')
            morning_end = self._parse_mcp_working_time(defaults['morning_end'], 'morning_end')
            afternoon_start = self._parse_mcp_working_time(defaults['afternoon_start'], 'afternoon_start')
            afternoon_end = self._parse_mcp_working_time(defaults['afternoon_end'], 'afternoon_end')
            working_days = self._parse_mcp_working_days(defaults['working_days'])
            values = dict(defaults)

        timezone_mode = values['timezone_mode'] if values['timezone_mode'] in ('company', 'user', 'fixed') else 'company'
        if timezone_mode != values['timezone_mode']:
            source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK
        return {
            'morning_start': morning_start,
            'morning_end': morning_end,
            'afternoon_start': afternoon_start,
            'afternoon_end': afternoon_end,
            'working_days': working_days,
            'timezone_mode': timezone_mode,
            'fixed_timezone': values['fixed_timezone'] or 'Asia/Ho_Chi_Minh',
            'source': source,
        }

    def _get_mcp_working_hours_timezone(self, env=None):
        env = self._get_env(env)
        config = self._get_mcp_working_hours_config(env=env)
        tz_name = None
        if config['timezone_mode'] == 'fixed':
            tz_name = config['fixed_timezone']
        elif config['timezone_mode'] == 'user':
            tz_name = env.user.tz
        else:
            company = env.company.sudo()
            tz_name = (
                getattr(getattr(company, 'resource_calendar_id', None), 'tz', None)
                or getattr(company.partner_id, 'tz', None)
                or env.user.tz
            )
        return self._get_timezone(env=env, params={'tz': tz_name or 'UTC'})

    def _build_customer_care_deadline_info(self, priority, env=None, params=None):
        env = self._get_env(env)
        tz = self._get_mcp_working_hours_timezone(env=env)
        config = self._get_mcp_working_hours_config(env=env)
        now_local = datetime.now(tz)
        if priority == 'low':
            return {'deadline_policy': 'manual', 'recommended_deadline': None}

        day_cursor = now_local.date()
        now_minutes = now_local.hour * 60 + now_local.minute
        working_day_set = set(config['working_days'])

        while True:
            weekday_number = day_cursor.weekday() + 1
            if weekday_number in working_day_set:
                if day_cursor == now_local.date():
                    if now_minutes <= config['morning_end'] or now_minutes <= config['afternoon_end']:
                        return {
                            'deadline_policy': 'same_day',
                            'recommended_deadline': day_cursor.isoformat(),
                        }
                else:
                    return {
                        'deadline_policy': 'next_working_shift',
                        'recommended_deadline': day_cursor.isoformat(),
                    }
            day_cursor = day_cursor + timedelta(days=1)

    def _get_mcp_activity_type_config(self, env=None):
        env = self._get_env(env)
        xmlid_defaults = {
            self.MCP_ACTIVITY_TYPE_TODO: 'mail.mail_activity_data_todo',
            self.MCP_ACTIVITY_TYPE_CALL: 'mail.mail_activity_data_call',
            self.MCP_ACTIVITY_TYPE_FOLLOWUP: 'dac_erp.mail_activity_type_cskh_followup',
        }
        code_defaults = {
            'urgent': self.MCP_ACTIVITY_TYPE_CALL,
            'high': self.MCP_ACTIVITY_TYPE_FOLLOWUP,
            'medium': self.MCP_ACTIVITY_TYPE_TODO,
            'low': self.MCP_ACTIVITY_TYPE_NONE,
        }
        icp = self._get_mcp_icp(env=env)
        xmlids = {}
        for code, default_xmlid in xmlid_defaults.items():
            xmlids[code] = (icp.get_param('dac_erp.mcp.activity_type.%s_xmlid' % code) or default_xmlid).strip() or default_xmlid
        mapping = {}
        for priority, default_code in code_defaults.items():
            configured = (icp.get_param('dac_erp.mcp.customer_care.%s_activity_type' % priority) or default_code).strip() or default_code
            mapping[priority] = configured if configured in (self.MCP_ACTIVITY_TYPE_CALL, self.MCP_ACTIVITY_TYPE_FOLLOWUP, self.MCP_ACTIVITY_TYPE_TODO, self.MCP_ACTIVITY_TYPE_NONE) else default_code
        return {'xmlids': xmlids, 'mapping': mapping}

    def _resolve_mcp_activity_type(self, env, activity_type_code='auto', activity_type_xmlid=None, priority=None):
        config = self._get_mcp_activity_type_config(env=env)
        if activity_type_xmlid:
            try:
                activity_type = env.ref(activity_type_xmlid)
            except Exception as exc:
                raise ValueError("activity_type_xmlid does not reference an existing mail.activity.type") from exc
            return {
                'code': activity_type_code if activity_type_code not in (None, '', 'auto') else None,
                'xmlid': activity_type_xmlid,
                'record': activity_type,
            }

        code = activity_type_code or 'auto'
        if code == 'auto':
            code = config['mapping'].get(priority or 'medium', self.MCP_ACTIVITY_TYPE_TODO)
        if code == self.MCP_ACTIVITY_TYPE_NONE:
            return {
                'code': self.MCP_ACTIVITY_TYPE_NONE,
                'xmlid': None,
                'record': False,
            }
        if code not in (self.MCP_ACTIVITY_TYPE_CALL, self.MCP_ACTIVITY_TYPE_FOLLOWUP, self.MCP_ACTIVITY_TYPE_TODO):
            raise ValueError("activity_type_code must be one of auto,call,followup,todo")
        xmlid = config['xmlids'][code]
        try:
            activity_type = env.ref(xmlid)
        except Exception as exc:
            raise ValueError("Configured activity type XMLID %s was not found" % xmlid) from exc
        return {
            'code': code,
            'xmlid': xmlid,
            'record': activity_type,
        }

    def _is_datetime_within_mcp_working_hours(self, dt_value=None, env=None):
        env = self._get_env(env)
        tz = self._get_mcp_working_hours_timezone(env=env)
        config = self._get_mcp_working_hours_config(env=env)
        dt_value = dt_value or datetime.now(tz)
        if getattr(dt_value, 'tzinfo', None) is None:
            dt_value = tz.localize(dt_value)
        else:
            dt_value = dt_value.astimezone(tz)
        weekday_number = dt_value.weekday() + 1
        if weekday_number not in set(config['working_days']):
            return False
        current_minutes = dt_value.hour * 60 + dt_value.minute
        return (
            config['morning_start'] <= current_minutes <= config['morning_end']
            or config['afternoon_start'] <= current_minutes <= config['afternoon_end']
        )

    def _get_customer_care_auto_run_config(self, env=None):
        env = self._get_env(env)
        guard_config = self._get_mcp_global_guard_config(env=env)
        enabled, _enabled_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_enabled',
            False,
            env=env,
        )
        dry_run_default, _dry_run_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_dry_run_default',
            True,
            env=env,
        )
        batch_limit, _batch_valid = self._get_mcp_config_int(
            'dac_erp.mcp.customer_care.auto_run_batch_limit',
            50,
            env=env,
            min_value=1,
        )
        batch_limit = min(batch_limit, 100)
        execute_followups, _followups_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_execute_followups',
            True,
            env=env,
        )
        execute_notes, _notes_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_execute_notes',
            True,
            env=env,
        )
        execute_triage, _triage_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_execute_triage',
            True,
            env=env,
        )
        exclude_internal, _internal_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_exclude_internal',
            True,
            env=env,
        )
        allow_mark_read, _mark_read_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_allow_mark_read',
            False,
            env=env,
        )
        allow_done, _allow_done_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_allow_done',
            False,
            env=env,
        )
        cron_enabled, _cron_enabled_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_cron_enabled',
            False,
            env=env,
        )
        cron_interval_minutes, _cron_interval_valid = self._get_mcp_config_int(
            'dac_erp.mcp.customer_care.auto_run_cron_interval_minutes',
            30,
            env=env,
            min_value=5,
        )
        cron_interval_minutes = min(cron_interval_minutes, 1440)
        working_hours_only, _working_hours_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.customer_care.auto_run_working_hours_only',
            True,
            env=env,
        )
        return {
            'enabled': bool(enabled),
            'dry_run_default': bool(dry_run_default),
            'batch_limit': int(batch_limit),
            'max_batch_limit': int(guard_config['max_batch_limit']),
            'execute_followups': bool(execute_followups),
            'execute_notes': bool(execute_notes),
            'execute_triage': bool(execute_triage),
            'exclude_internal': bool(exclude_internal),
            'allow_mark_read': bool(allow_mark_read),
            'allow_done': bool(allow_done),
            'cron_enabled': bool(cron_enabled),
            'cron_interval_minutes': int(cron_interval_minutes),
            'working_hours_only': bool(working_hours_only),
            'min_interval_seconds': int(guard_config['auto_run_min_interval_seconds']),
        }

    def _get_mcp_global_guard_config(self, env=None):
        env = self._get_env(env)
        max_batch_limit, _limit_valid = self._get_mcp_config_int(
            'dac_erp.mcp.max_batch_limit_default',
            100,
            env=env,
            min_value=1,
        )
        min_interval_seconds, _interval_valid = self._get_mcp_config_int(
            'dac_erp.mcp.auto_run_min_interval_seconds',
            60,
            env=env,
            min_value=0,
        )
        return {
            'max_batch_limit': min(max_batch_limit, 100),
            'auto_run_min_interval_seconds': max(min_interval_seconds, 0),
        }

    def _try_ref(self, env, xmlid):
        if not xmlid:
            return False
        try:
            return env.ref(xmlid).sudo()
        except Exception:
            return False

    def _get_mcp_module_info(self, env=None):
        env = self._get_env(env)
        module = env['ir.module.module'].sudo().search([('name', '=', 'dac_erp')], limit=1)
        return {
            'name': 'dac_erp',
            'installed': bool(module and module.state == 'installed'),
            'version': (module.installed_version or module.latest_version or '1.0') if module else '1.0',
        }

    def _get_mcp_working_hours_warning_code(self, env=None):
        env = self._get_env(env)
        icp = self._get_mcp_icp(env=env)
        defaults = {
            'morning_start': '08:00',
            'morning_end': '12:00',
            'afternoon_start': '13:30',
            'afternoon_end': '17:30',
            'working_days': '1,2,3,4,5,6',
            'timezone_mode': 'company',
            'fixed_timezone': 'Asia/Ho_Chi_Minh',
        }
        raw_values = {
            key: (icp.get_param('dac_erp.mcp.working_hours.%s' % key) or '').strip()
            for key in defaults
        }
        candidate_values = {
            key: raw_values[key] or default_value
            for key, default_value in defaults.items()
        }
        try:
            morning_start = self._parse_mcp_working_time(candidate_values['morning_start'], 'morning_start')
            morning_end = self._parse_mcp_working_time(candidate_values['morning_end'], 'morning_end')
            afternoon_start = self._parse_mcp_working_time(candidate_values['afternoon_start'], 'afternoon_start')
            afternoon_end = self._parse_mcp_working_time(candidate_values['afternoon_end'], 'afternoon_end')
            self._parse_mcp_working_days(candidate_values['working_days'])
            if morning_start >= morning_end or afternoon_start >= afternoon_end:
                raise ValueError("working hours ranges are invalid")
            if candidate_values['timezone_mode'] not in ('company', 'user', 'fixed'):
                raise ValueError("timezone mode is invalid")
        except Exception:
            return 'invalid_working_hours_config'
        return None

    def _get_mcp_health_data(self, env=None):
        env = self._get_env(env)
        icp = self._get_mcp_icp(env=env)
        module_info = self._get_mcp_module_info(env=env)
        auto_config = self._get_customer_care_auto_run_config(env=env)
        threshold_config = self._get_customer_care_threshold_config(env=env)
        default_policy, _policy_source = self._get_customer_care_default_policy(env=env)
        working_hours_warning = self._get_mcp_working_hours_warning_code(env=env)
        activity_config = self._get_mcp_activity_type_config(env=env)
        todo_activity = self._try_ref(env, activity_config['xmlids'].get(self.MCP_ACTIVITY_TYPE_TODO))
        call_activity = self._try_ref(env, activity_config['xmlids'].get(self.MCP_ACTIVITY_TYPE_CALL))
        followup_activity = self._try_ref(env, activity_config['xmlids'].get(self.MCP_ACTIVITY_TYPE_FOLLOWUP))
        cron_record = self._try_ref(env, 'dac_erp.ir_cron_mcp_customer_care_auto_run')
        money_confirmation_required, _money_confirmation_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.order.money_change_confirmation_required',
            True,
            env=env,
        )
        conversation_scope = self._get_mcp_conversation_scope_config(env=env)
        read_key = (icp.get_param(self.MCP_READ_KEY_PARAM) or '').strip()
        write_key = (icp.get_param(self.MCP_WRITE_KEY_PARAM) or '').strip()
        warnings = []
        if not read_key:
            warnings.append('mcp_read_key_missing')
        if not write_key:
            warnings.append('mcp_write_key_missing')
        if not followup_activity:
            warnings.append('followup_activity_type_missing')
        if working_hours_warning:
            warnings.append(working_hours_warning)
        if auto_config['enabled'] and not bool(getattr(cron_record, 'active', False)):
            warnings.append('auto_run_enabled_but_cron_inactive')
        if bool(getattr(cron_record, 'active', False)) and not auto_config['enabled']:
            warnings.append('cron_active_but_auto_run_disabled')
        if not money_confirmation_required:
            warnings.append('money_confirmation_disabled')

        status = 'ok'
        if not module_info['installed']:
            status = 'error'
        elif warnings:
            status = 'warning'

        return {
            'service': self.MCP_SERVICE_NAME,
            'status': status,
            'version': module_info['version'],
            'database': env.cr.dbname,
            'module': module_info,
            'config': {
                'read_key_configured': bool(read_key),
                'write_key_configured': bool(write_key),
                'auto_run_enabled': auto_config['enabled'],
                'auto_run_cron_enabled': auto_config['cron_enabled'],
                'auto_run_cron_active': bool(getattr(cron_record, 'active', False)),
                'sla_minutes_default': threshold_config['sla_minutes'],
                'urgent_minutes_default': threshold_config['urgent_minutes'],
                'default_policy': default_policy,
                'working_hours_configured': working_hours_warning is None,
                'followup_activity_type_found': bool(followup_activity),
                'call_activity_type_found': bool(call_activity),
                'todo_activity_type_found': bool(todo_activity),
                'money_confirmation_required': bool(money_confirmation_required),
                'internal_read_allowed': bool(conversation_scope['allow_internal_read']),
                'max_batch_limit_default': self._get_mcp_global_guard_config(env=env)['max_batch_limit'],
                'auto_run_min_interval_seconds': self._get_mcp_global_guard_config(env=env)['auto_run_min_interval_seconds'],
            },
            'warnings': warnings,
        }

    def _get_mcp_tool_manifest(self, env=None):
        customer_care_forbidden = [
            'customer_facing_message',
            'mark_read',
            'close_conversation',
            'owner_reassignment',
            'participant_reassignment',
            'customer_order_linkage_change',
        ]
        order_forbidden = [
            'raw_state_write',
            'cancel',
            'rollback',
            'payment_reset',
        ]
        return [
            {'name': 'mcp_health', 'method': 'GET', 'path': '/dac_erp/mcp/v1/health', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Health check only', 'forbidden_actions': []},
            {'name': 'mcp_capabilities', 'method': 'GET', 'path': '/dac_erp/mcp/v1/capabilities', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Capability discovery only', 'forbidden_actions': []},
            {'name': 'list_conversations', 'method': 'GET', 'path': '/dac_erp/mcp/v1/conversations', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Default scope external', 'forbidden_actions': []},
            {'name': 'get_conversation_messages', 'method': 'GET', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/messages', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'External by default; internal requires explicit include', 'forbidden_actions': []},
            {'name': 'get_conversation_context', 'method': 'GET', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/context', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'External by default; internal requires explicit include', 'forbidden_actions': []},
            {'name': 'list_internal_conversations', 'method': 'GET', 'path': '/dac_erp/mcp/v1/internal/conversations', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Manual or explicit scope only', 'forbidden_actions': []},
            {'name': 'get_internal_messages', 'method': 'GET', 'path': '/dac_erp/mcp/v1/internal/conversations/<conversation_id>/messages', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Manual or explicit scope only', 'forbidden_actions': []},
            {'name': 'get_internal_context', 'method': 'GET', 'path': '/dac_erp/mcp/v1/internal/conversations/<conversation_id>/context', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Manual or explicit scope only', 'forbidden_actions': []},
            {'name': 'customer_care_queue', 'method': 'GET', 'path': '/dac_erp/mcp/v1/customer-care/queue', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'customer_care_action_plan', 'method': 'POST', 'path': '/dac_erp/mcp/v1/customer-care/action-plan', 'read_write': 'read_only', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed, review payload templates before execute', 'forbidden_actions': customer_care_forbidden},
            {'name': 'customer_care_create_followups', 'method': 'POST', 'path': '/dac_erp/mcp/v1/customer-care/create-followups', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed with dedupe on', 'forbidden_actions': customer_care_forbidden},
            {'name': 'customer_care_apply_reviewed_actions', 'method': 'POST', 'path': '/dac_erp/mcp/v1/customer-care/apply-reviewed-actions', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed for safe presets only', 'forbidden_actions': customer_care_forbidden},
            {'name': 'customer_care_auto_run', 'method': 'POST', 'path': '/dac_erp/mcp/v1/customer-care/auto-run', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed for customer-care internal operations only', 'forbidden_actions': customer_care_forbidden + ['order_mutation', 'payment_mutation']},
            {'name': 'customer_care_auto_run_runs', 'method': 'GET', 'path': '/dac_erp/mcp/v1/customer-care/auto-run/runs', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Read execution audit output only', 'forbidden_actions': []},
            {'name': 'customer_care_auto_run_report', 'method': 'GET', 'path': '/dac_erp/mcp/v1/customer-care/auto-run/runs/<run_id>', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Read execution audit output only', 'forbidden_actions': []},
            {'name': 'customer_search', 'method': 'GET', 'path': '/dac_erp/mcp/v1/customers/search', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'customer_resolve', 'method': 'POST', 'path': '/dac_erp/mcp/v1/customers/resolve', 'read_write': 'read_only', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'product_search', 'method': 'GET', 'path': '/dac_erp/mcp/v1/products/search', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'product_resolve', 'method': 'POST', 'path': '/dac_erp/mcp/v1/products/resolve', 'read_write': 'read_only', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'list_orders', 'method': 'GET', 'path': '/dac_erp/mcp/v1/orders', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'get_order', 'method': 'GET', 'path': '/dac_erp/mcp/v1/orders/<order_id>', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'list_conversation_orders', 'method': 'GET', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/orders', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': []},
            {'name': 'create_order', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': True, 'safe_for_auto_mode': False, 'default_policy': 'Prepare only; execute only with confirmation when money-impact fields exist', 'forbidden_actions': order_forbidden, 'notes': 'Employee confirmation is required for money-impact create payloads.'},
            {'name': 'update_order', 'method': 'PATCH', 'path': '/dac_erp/mcp/v1/orders/<order_id>', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': True, 'safe_for_auto_mode': False, 'default_policy': 'Prepare only; execute only with confirmation when money-impact fields exist', 'forbidden_actions': order_forbidden, 'notes': 'Employee confirmation is required for money-impact updates.'},
            {'name': 'confirm_order_info', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/confirm-info', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Allowed after stage validation', 'forbidden_actions': order_forbidden},
            {'name': 'proceed_to_production', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/proceed-to-production', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Allowed after stage validation', 'forbidden_actions': order_forbidden},
            {'name': 'proceed_to_delivery', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/proceed-to-delivery', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Allowed after stage validation', 'forbidden_actions': order_forbidden},
            {'name': 'proceed_to_installation', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/proceed-to-installation', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Allowed after stage validation', 'forbidden_actions': order_forbidden},
            {'name': 'create_deposit_invoice', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/create-deposit-invoice', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Legacy reviewed route only', 'forbidden_actions': order_forbidden},
            {'name': 'create_final_invoice', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/create-final-invoice', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Legacy reviewed route only', 'forbidden_actions': order_forbidden},
            {'name': 'confirm_deposit_invoice', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/confirm-deposit-invoice', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': True, 'safe_for_auto_mode': False, 'default_policy': 'Execute only with explicit employee confirmation', 'forbidden_actions': order_forbidden + ['customer_facing_message']},
            {'name': 'confirm_final_payment', 'method': 'POST', 'path': '/dac_erp/mcp/v1/orders/<order_id>/actions/confirm-final-payment', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': True, 'safe_for_auto_mode': False, 'default_policy': 'Execute only with explicit employee confirmation', 'forbidden_actions': order_forbidden + ['customer_facing_message']},
            {'name': 'conversation_ai_summary', 'method': 'POST', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/ai-summary', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed', 'forbidden_actions': customer_care_forbidden},
            {'name': 'conversation_ai_note', 'method': 'POST', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/ai-note', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed for internal notes only', 'forbidden_actions': customer_care_forbidden},
            {'name': 'conversation_activity', 'method': 'POST', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/activities', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Use for reviewed internal follow-up only', 'forbidden_actions': customer_care_forbidden},
            {'name': 'conversation_triage', 'method': 'PATCH', 'path': '/dac_erp/mcp/v1/conversations/<conversation_id>/triage', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Use reviewed presets or whitelisted triage only', 'forbidden_actions': customer_care_forbidden},
            # Staff Identity Bridge — owner.id in /conversations is res.users.id; use these to map to external channels
            {'name': 'list_staff', 'method': 'GET', 'path': '/dac_erp/mcp/v1/staff', 'read_write': 'read', 'requires_write_key': False, 'requires_employee_confirmation': False, 'safe_for_auto_mode': True, 'default_policy': 'Auto allowed — read-only internal staff directory', 'forbidden_actions': [], 'notes': 'Returns user_id matching owner.id in /conversations. Filter by ?active=, ?team_id=, ?q=. Each item includes external_identities (channel+value mappings to Zalo/OpenClaw) and is_shared_account flag.'},
            {'name': 'upsert_staff_external_identity', 'method': 'POST', 'path': '/dac_erp/mcp/v1/staff/<user_id>/external-identities', 'read_write': 'write', 'requires_write_key': True, 'requires_employee_confirmation': False, 'safe_for_auto_mode': False, 'default_policy': 'Idempotent upsert of channel+value mapping only — no order/payment/message side effects', 'forbidden_actions': ['order_mutation', 'payment_mutation', 'customer_facing_message'], 'notes': 'Body: {request_id, agent_name, reason, channel, value, label}. Idempotent by request_id. Channels: telegram, zalo, zalouser, facebook, webchat, other.'},
        ]

    def _get_mcp_capabilities_data(self, env=None):
        env = self._get_env(env)
        default_policy, _source = self._get_customer_care_default_policy(env=env)
        module_info = self._get_mcp_module_info(env=env)
        return {
            'service': self.MCP_SERVICE_NAME,
            'version': module_info['version'],
            'default_policy': default_policy,
            'tools': self._get_mcp_tool_manifest(env=env),
        }

    def _get_mcp_conversation_scope_config(self, env=None):
        env = self._get_env(env)
        default_scope, _scope_valid = self._get_mcp_config_text(
            'dac_erp.mcp.conversation.default_scope',
            self.MCP_SCOPE_EXTERNAL,
            env=env,
        )
        if default_scope not in self.MCP_ALLOWED_CONVERSATION_SCOPES:
            default_scope = self.MCP_SCOPE_EXTERNAL
        allow_internal_read, _allow_valid = self._get_mcp_config_bool(
            'dac_erp.mcp.conversation.allow_internal_read',
            True,
            env=env,
        )
        return {
            'default_scope': default_scope,
            'allow_internal_read': allow_internal_read,
        }

    def _resolve_mcp_conversation_scope(self, env=None, params=None, force_internal=False):
        env = self._get_env(env)
        params = params or {}
        config = self._get_mcp_conversation_scope_config(env=env)
        if force_internal:
            return self.MCP_SCOPE_INTERNAL
        scope = params.get('scope')
        include_internal = params.get('include_internal')
        if scope not in (None, ''):
            scope = str(scope).strip().lower()
            if scope not in self.MCP_ALLOWED_CONVERSATION_SCOPES:
                raise McpHttpError(400, 'validation_error', 'scope must be one of external,internal,all')
        elif include_internal not in (None, ''):
            parsed = self._as_bool(include_internal, 'include_internal')
            if parsed is None:
                raise McpHttpError(400, 'validation_error', 'include_internal must be one of 1,0,true,false')
            scope = self.MCP_SCOPE_ALL if parsed else self.MCP_SCOPE_EXTERNAL
        else:
            scope = config['default_scope']
        if scope in (self.MCP_SCOPE_INTERNAL, self.MCP_SCOPE_ALL) and not config['allow_internal_read']:
            raise McpHttpError(403, 'permission_denied', 'Internal conversation read is disabled')
        return scope

    def _enforce_mcp_internal_conversation_access(self, conversation, include_internal=False, env=None):
        env = self._get_env(env)
        if not conversation or not bool(getattr(conversation, 'is_internal_conversation', False)):
            return
        config = self._get_mcp_conversation_scope_config(env=env)
        if not config['allow_internal_read']:
            raise McpHttpError(403, 'permission_denied', 'Internal conversation read is disabled')
        if not include_internal:
            raise McpHttpError(403, 'permission_denied', 'Internal conversation requires include_internal=1')

    def _get_mcp_conversation_record(self, conversation_id, env=None):
        env = self._get_env(env)
        conversation = env['page.fm.conversation'].sudo().browse(int(conversation_id)).exists()
        if not conversation:
            raise McpHttpError(404, 'not_found', 'Conversation not found')
        return conversation

    def _get_mcp_conversation_record_for_read(self, conversation_id, env=None, include_internal=False):
        conversation = self._get_mcp_conversation_record(conversation_id, env=env)
        self._enforce_mcp_internal_conversation_access(
            conversation,
            include_internal=include_internal,
            env=env,
        )
        return conversation

    def _get_mcp_order_record(self, order_id, env=None, error_code='not_found', error_message='Order not found'):
        env = self._get_env(env)
        order = env['sale.order'].sudo().browse(int(order_id)).exists()
        if not order:
            raise McpHttpError(404, error_code, error_message)
        return order

    def _normalize_conversation_records(self, raw_items, env=None):
        env = self._get_env(env)
        conversation_ids = [item.get('id') for item in raw_items if item.get('id')]
        record_map = {
            conversation.id: conversation
            for conversation in env['page.fm.conversation'].sudo().browse(conversation_ids).exists()
        }
        return [
            normalize_conversation_item(item, conversation=record_map.get(item.get('id')))
            for item in raw_items
        ]

    def _get_mcp_conversation_payload(self, conversation_id, env=None, include_internal=False):
        env = self._get_env(env)
        conversation = self._get_mcp_conversation_record_for_read(
            conversation_id,
            env=env,
            include_internal=include_internal,
        )
        metrics = self._build_conversation_business_metrics(env=env, conversation_ids=[conversation.id])
        raw_item = self._serialize_conversation_v2(conversation, business_metric=metrics.get(conversation.id, {}))
        return normalize_conversation_item(raw_item, conversation=conversation)

    def _get_mcp_messages_payload(self, conversation_id, env=None, include_internal=False, **params):
        env = self._get_env(env)
        self._get_mcp_conversation_record_for_read(
            conversation_id,
            env=env,
            include_internal=include_internal,
        )
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=100,
            max_limit=300,
        )
        raw_payload = self._get_v2_messages_data(
            env=env,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
            date=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
            sender_role=params.get('sender_role'),
            type_content=params.get('type_content'),
        )
        ordered_items = list(reversed(raw_payload.get('items') or []))
        normalized_items = [normalize_message_item(item) for item in ordered_items]
        return self._mcp_list_payload(normalized_items, raw_payload.get('total', 0))

    def _get_optional_v3_json_payload(self, payload=None):
        if payload is not None:
            return self._get_v3_json_payload(payload=payload)
        try:
            raw_data = request.httprequest.data.decode('utf-8') if request.httprequest.data else ''
        except Exception:
            raw_data = ''
        if not raw_data.strip():
            return {}
        return self._get_v3_json_payload()

    def _normalize_customer_care_message_limit(self, value, default_limit=10, max_limit=20):
        limit = default_limit
        if value not in (None, ''):
            try:
                limit = int(value)
            except Exception as exc:
                raise ValueError("message_limit must be an integer") from exc
        if limit < 0:
            raise ValueError("message_limit must be >= 0")
        return min(limit, max_limit)

    # Maximum waiting_minutes reported in queue (30 days).
    # Conversations older than this still appear but cap at this value.
    MCP_WAITING_MINUTES_CAP = 43200

    def _compute_customer_care_waiting_minutes(self, metric):
        last_customer = metric.get('last_customer_message_at')
        last_staff = metric.get('last_staff_reply_at')
        if not last_customer:
            return None
        if last_staff and last_staff >= last_customer:
            return 0
        now_utc = datetime.utcnow().replace(microsecond=0)
        delta = now_utc - last_customer
        raw_minutes = max(int(delta.total_seconds() // 60), 0)
        return min(raw_minutes, self.MCP_WAITING_MINUTES_CAP)

    def _build_customer_care_reason(self, conversation, metric, waiting_minutes, sla_minutes, urgent_minutes):
        require_processing = bool(getattr(conversation, 'require_processing', False))
        is_unread = bool(getattr(conversation, 'is_unread_fm', False))
        is_unreplied = bool(metric.get('is_unreplied'))
        last_customer = metric.get('last_customer_message_at')
        last_staff = metric.get('last_staff_reply_at')

        if require_processing and is_unreplied:
            return 'requires_processing_and_unreplied'
        if waiting_minutes is not None and waiting_minutes > urgent_minutes:
            return 'sla_breach_critical'
        if waiting_minutes is not None and waiting_minutes > sla_minutes:
            return 'sla_breach'
        if last_customer and not last_staff:
            return 'customer_waiting_for_first_reply'
        if last_customer and (not last_staff or last_customer > last_staff):
            return 'customer_waiting_for_reply'
        if is_unread:
            return 'unread_conversation'
        if require_processing:
            return 'requires_processing'
        return 'customer_care_review'

    def _build_customer_care_priority(self, conversation, metric, waiting_minutes, sla_minutes, urgent_minutes):
        require_processing = bool(getattr(conversation, 'require_processing', False))
        is_unread = bool(getattr(conversation, 'is_unread_fm', False))
        is_unreplied = bool(metric.get('is_unreplied'))

        if (waiting_minutes is not None and waiting_minutes > urgent_minutes) or (require_processing and is_unreplied):
            return 'urgent'
        if is_unreplied or (waiting_minutes is not None and waiting_minutes > sla_minutes):
            return 'high'
        if is_unread or require_processing:
            return 'medium'
        return 'low'

    def _build_customer_care_recommended_action(self, conversation, care_reason):
        owner = getattr(conversation, 'owner_id', None)
        if care_reason in ('requires_processing_and_unreplied', 'customer_waiting_for_reply', 'customer_waiting_for_first_reply', 'sla_breach', 'sla_breach_critical'):
            if owner:
                return 'Tao nhac viec cho owner phan hoi khach'
            return 'Gan nguoi phu trach va nhac phan hoi khach'
        if care_reason == 'unread_conversation':
            return 'Nhan vien kiem tra hoi thoai va cap nhat triage'
        if care_reason == 'requires_processing':
            return 'Nhan vien xu ly hoi thoai dang require_processing'
        return 'Nhan vien xem lai hoi thoai de tranh bo sot'

    def _build_customer_care_recommended_deadline(self, priority, env=None, params=None):
        deadline_info = self._build_customer_care_deadline_info(priority, env=env, params=params)
        return deadline_info.get('recommended_deadline')

    def _conversation_matches_customer_care_queue(self, conversation, metric, sla_minutes):
        is_unreplied = bool(metric.get('is_unreplied'))
        is_unread = bool(getattr(conversation, 'is_unread_fm', False))
        require_processing = bool(getattr(conversation, 'require_processing', False))
        last_customer = metric.get('last_customer_message_at')
        last_staff = metric.get('last_staff_reply_at')
        waiting_minutes = self._compute_customer_care_waiting_minutes(metric)
        if is_unreplied or is_unread or require_processing:
            return True, waiting_minutes
        if last_customer and last_staff and last_customer > last_staff:
            return True, waiting_minutes
        if last_customer and not last_staff:
            return True, waiting_minutes
        if waiting_minutes is not None and waiting_minutes > sla_minutes:
            return True, waiting_minutes
        return False, waiting_minutes

    def _get_customer_care_messages(self, conversation_id, limit, env=None):
        if limit <= 0:
            return []
        payload = self._get_mcp_messages_payload(
            conversation_id,
            env=env,
            limit=limit,
            offset=0,
        )
        return payload.get('items') or []

    def _normalize_customer_care_sla_minutes(self, value, default_value=60):
        if value in (None, ''):
            return default_value
        try:
            sla_minutes = int(value)
        except Exception as exc:
            raise ValueError("sla_minutes must be an integer") from exc
        if sla_minutes < 0:
            raise ValueError("sla_minutes must be >= 0")
        return sla_minutes

    def _build_customer_care_row(self, conversation, metric, sla_minutes, urgent_minutes):
        matches, waiting_minutes = self._conversation_matches_customer_care_queue(conversation, metric, sla_minutes)
        care_reason = self._build_customer_care_reason(conversation, metric, waiting_minutes, sla_minutes, urgent_minutes)
        care_priority = self._build_customer_care_priority(conversation, metric, waiting_minutes, sla_minutes, urgent_minutes)
        return {
            'conversation': conversation,
            'metric': metric,
            'matches': bool(matches),
            'waiting_minutes': waiting_minutes,
            'care_reason': care_reason,
            'care_priority': care_priority,
            'sla_minutes': sla_minutes,
            'urgent_minutes': urgent_minutes,
        }

    def _serialize_customer_care_row(self, row, env=None, include_messages=False, message_limit=10, params=None):
        env = self._get_env(env)
        params = params or {}
        conversation = row['conversation']
        metric = row['metric']
        raw_item = self._serialize_conversation_v2(conversation, business_metric=metric)
        last_customer = metric.get('last_customer_message_at')
        waiting_since = (
            last_customer.strftime('%Y-%m-%dT%H:%M:%SZ')
            if last_customer and hasattr(last_customer, 'strftime')
            else (str(last_customer) if last_customer else None)
        )
        return {
            'care_priority': row['care_priority'],
            'care_reason': row['care_reason'],
            'waiting_minutes': row['waiting_minutes'],
            'waiting_since': waiting_since,
            'recommended_action': self._build_customer_care_recommended_action(conversation, row['care_reason']),
            'recommended_deadline': self._build_customer_care_recommended_deadline(row['care_priority'], env=env, params=params),
            'conversation': normalize_conversation_item(raw_item, conversation=conversation),
            'messages': self._get_customer_care_messages(conversation.id, message_limit, env=env) if include_messages else [],
        }

    def _get_customer_care_queue_row_by_conversation(self, conversation, env=None, sla_minutes=60, urgent_minutes=120):
        env = self._get_env(env)
        metrics = self._build_conversation_business_metrics(env=env, conversation_ids=[conversation.id])
        metric = metrics.get(conversation.id, {})
        return self._build_customer_care_row(conversation, metric, sla_minutes, urgent_minutes)

    def _get_customer_care_assignee_user(self, conversation, env=None):
        env = self._get_env(env)
        candidate_ids = []
        owner = getattr(conversation, 'owner_id', None)
        if owner:
            candidate_ids.append(owner.id)
        for participant in getattr(conversation, 'participant_user_ids', env['res.users']):
            candidate_ids.append(participant.id)

        seen_ids = set()
        for user_id in candidate_ids:
            if not user_id or user_id in seen_ids:
                continue
            seen_ids.add(user_id)
            user = env['res.users'].sudo().browse(user_id)
            if user.exists():
                return user
        return env['res.users']

    def _safe_customer_care_template_value(self, value):
        if value in (None, False):
            return ''
        return str(value)

    def _render_customer_care_note(self, template, context_values):
        template = (template or '').strip()
        if not template:
            template = self.MCP_CUSTOMER_CARE_DEFAULT_NOTE_TEMPLATE

        class SafeMap(dict):
            def __missing__(self, key):
                return ''

        safe_values = SafeMap({
            key: self._safe_customer_care_template_value(value)
            for key, value in (context_values or {}).items()
        })
        try:
            rendered = template.format_map(safe_values)
        except Exception:
            rendered = template
        marker = self.MCP_CUSTOMER_CARE_ACTIVITY_MARKER
        if marker not in rendered:
            rendered = '%s\n\n%s' % (rendered.strip(), marker)
        return rendered.strip()

    def _find_existing_customer_care_open_activity(self, env, conversation, summary, reason=None):
        model_id = env['ir.model']._get_id('page.fm.conversation')
        activities = env['mail.activity'].sudo().search(
            [('res_model_id', '=', model_id), ('res_id', '=', conversation.id)],
            order='id desc',
        )
        marker = self.MCP_CUSTOMER_CARE_ACTIVITY_MARKER
        for activity in activities:
            if (activity.summary or '').strip() == (summary or '').strip():
                return activity
            if marker in (activity.note or ''):
                return activity
        if activities:
            logs = env['page.fm.conversation.ai.log'].sudo().search(
                [
                    ('conversation_id', '=', conversation.id),
                    ('action_type', '=', 'activity_create'),
                    ('activity_id', 'in', activities.ids),
                ],
                order='id desc',
            )
            for log in logs:
                if reason and log.reason == reason:
                    return log.activity_id
                if marker in (log.note_text or ''):
                    return log.activity_id
        return False

    def _normalize_mcp_customer_care_followup_payload(self, payload=None, env=None):
        env = self._get_env(env)
        payload = self._get_v3_json_payload(payload=payload)
        allowed_fields = {
            'conversation_ids',
            'default_deadline_date',
            'summary_template',
            'note_template',
            'sla_minutes',
            'urgent_minutes',
            'activity_type_code',
            'activity_type_xmlid',
            'dedupe_existing_open_activity',
            'revalidate_queue',
            'set_require_processing',
            'dry_run',
            'request_id',
            'agent_name',
            'model_name',
            'reason',
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported customer-care bulk fields: %s" % ', '.join(unknown_fields))

        metadata = self._normalize_mcp_order_metadata(payload)
        if not metadata.get('reason'):
            raise ValueError("reason is required")

        conversation_ids = payload.get('conversation_ids')
        if not isinstance(conversation_ids, list):
            raise ValueError("conversation_ids is required")
        if not conversation_ids:
            raise ValueError("conversation_ids cannot be empty")
        if len(conversation_ids) > 50:
            raise ValueError("conversation_ids cannot contain more than 50 items")

        cleaned_ids = []
        seen_ids = set()
        for index, value in enumerate(conversation_ids):
            conversation_id = self._as_int(value, 'conversation_ids[%s]' % index)
            if conversation_id in seen_ids:
                continue
            seen_ids.add(conversation_id)
            cleaned_ids.append(conversation_id)

        deadline_date = self._coerce_nullable_date(payload.get('default_deadline_date'), 'default_deadline_date')

        summary_template = payload.get('summary_template')
        if not isinstance(summary_template, str) or not summary_template.strip():
            raise ValueError("summary_template is required")

        note_template = payload.get('note_template')
        if note_template not in (None, False):
            if not isinstance(note_template, str):
                raise ValueError("note_template must be a string")
            note_template = note_template.strip() or False
        else:
            note_template = False

        dedupe_existing_open_activity = self._coerce_mcp_nullable_bool(
            payload.get('dedupe_existing_open_activity'),
            'dedupe_existing_open_activity',
        )
        revalidate_queue = self._coerce_mcp_nullable_bool(payload.get('revalidate_queue'), 'revalidate_queue')
        set_require_processing = self._coerce_mcp_nullable_bool(
            payload.get('set_require_processing'),
            'set_require_processing',
        )
        dry_run = self._coerce_mcp_nullable_bool(payload.get('dry_run'), 'dry_run')
        activity_type_code = payload.get('activity_type_code', 'auto')
        if activity_type_code not in (None, False):
            if not isinstance(activity_type_code, str) or not activity_type_code.strip():
                raise ValueError("activity_type_code must be a non-empty string")
            activity_type_code = activity_type_code.strip().lower()
        else:
            activity_type_code = 'auto'
        if activity_type_code not in ('auto', self.MCP_ACTIVITY_TYPE_CALL, self.MCP_ACTIVITY_TYPE_FOLLOWUP, self.MCP_ACTIVITY_TYPE_TODO):
            raise ValueError("activity_type_code must be one of auto,call,followup,todo")
        activity_type_xmlid = payload.get('activity_type_xmlid')
        if activity_type_xmlid not in (None, False):
            if not isinstance(activity_type_xmlid, str) or not activity_type_xmlid.strip():
                raise ValueError("activity_type_xmlid must be a non-empty string")
            activity_type_xmlid = activity_type_xmlid.strip()
        else:
            activity_type_xmlid = False
        if activity_type_xmlid:
            self._resolve_mcp_activity_type(
                env,
                activity_type_code=activity_type_code,
                activity_type_xmlid=activity_type_xmlid,
                priority='medium',
            )
        threshold_config = self._get_customer_care_threshold_config(
            env=env,
            request_sla_minutes=payload.get('sla_minutes'),
            request_urgent_minutes=payload.get('urgent_minutes'),
        )

        return dict(
            metadata,
            conversation_ids=cleaned_ids,
            default_deadline_date=deadline_date,
            summary_template=summary_template.strip(),
            note_template=note_template,
            sla_minutes=threshold_config['sla_minutes'],
            urgent_minutes=threshold_config['urgent_minutes'],
            dedupe_existing_open_activity=True if dedupe_existing_open_activity is None else dedupe_existing_open_activity,
            revalidate_queue=True if revalidate_queue is None else revalidate_queue,
            set_require_processing=True if set_require_processing is None else set_require_processing,
            dry_run=False if dry_run is None else dry_run,
            activity_type_code=activity_type_code,
            activity_type_xmlid=activity_type_xmlid,
        )

    def _handle_mcp_bulk_idempotency_or_raise(self, env=None, request_id=None, payload_fingerprint=None):
        env = self._get_mcp_write_env(env)
        log_record = env[self.MCP_BULK_LOG_MODEL].sudo().search([('request_id', '=', request_id)], limit=1)
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                'idempotency_conflict',
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _create_mcp_bulk_log(
        self,
        env=None,
        action_type=None,
        normalized_payload=None,
        payload_fingerprint=None,
        response_data=None,
        status='success',
        error_code=None,
        error_message=None,
    ):
        env = self._get_mcp_write_env(env)
        normalized_payload = normalized_payload or {}
        response_data = response_data or {}
        return env[self.MCP_BULK_LOG_MODEL].sudo().create({
            'action_type': action_type,
            'request_id': normalized_payload.get('request_id'),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'payload_fingerprint': payload_fingerprint,
            'response_snapshot_json': self._dump_json_text(response_data),
            'agent_name': normalized_payload.get('agent_name'),
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'status': status,
            'error_code': error_code or False,
            'error_message': error_message or False,
        })

    def _build_mcp_bulk_replayed_response_data(self, log_record):
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        data['request_id'] = data.get('request_id') or log_record.request_id
        data['idempotent_replay'] = True
        return data

    def _handle_mcp_auto_run_idempotency_or_raise(self, env=None, request_id=None, payload_fingerprint=None):
        env = self._get_mcp_write_env(env)
        log_record = env[self.MCP_AUTO_RUN_LOG_MODEL].sudo().search([('request_id', '=', request_id)], limit=1)
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                'idempotency_conflict',
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _create_mcp_auto_run_log(
        self,
        env=None,
        normalized_payload=None,
        payload_fingerprint=None,
        response_data=None,
        summary=None,
        items=None,
        status='success',
        error_code=None,
        error_message=None,
        mode='manual_api',
        started_at=None,
        finished_at=None,
        duration_ms=None,
    ):
        env = self._get_mcp_write_env(env)
        normalized_payload = normalized_payload or {}
        response_data = response_data or {}
        summary = summary or {}
        items = items or []
        return env[self.MCP_AUTO_RUN_LOG_MODEL].sudo().create({
            'name': 'Customer Care Auto Run %s' % (normalized_payload.get('request_id') or ''),
            'request_id': normalized_payload.get('request_id'),
            'payload_fingerprint': payload_fingerprint,
            'mode': mode or 'manual_api',
            'dry_run': bool(normalized_payload.get('dry_run')),
            'policy': normalized_payload.get('policy') or False,
            'sla_minutes': normalized_payload.get('sla_minutes') or 0,
            'urgent_minutes': normalized_payload.get('urgent_minutes') or 0,
            'batch_limit': normalized_payload.get('batch_limit') or 0,
            'filters_json': self._dump_json_text(normalized_payload.get('filters') or {}),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'response_snapshot_json': self._dump_json_text(response_data),
            'summary_json': self._dump_json_text(summary),
            'item_results_json': self._dump_json_text(items),
            'status': status,
            'error_code': error_code or False,
            'error_message': error_message or False,
            'agent_name': normalized_payload.get('agent_name') or '',
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'started_at': started_at or fields.Datetime.now(),
            'finished_at': finished_at or False,
            'duration_ms': duration_ms or 0,
        })

    def _build_mcp_auto_run_replayed_response_data(self, log_record):
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        data['run_id'] = data.get('run_id') or log_record.id
        data['request_id'] = data.get('request_id') or log_record.request_id
        data['idempotent_replay'] = True
        return data

    def _get_customer_care_item_request_id(self, bulk_request_id, conversation_id, suffix, item_index=None):
        request_id = '%s:%s:%s' % (bulk_request_id, int(conversation_id), suffix)
        if item_index is not None:
            request_id = '%s:%s' % (request_id, int(item_index))
        return request_id

    def _build_customer_care_item_context(self, conversation, queue_row):
        return {
            'conversation_id': conversation.id,
            'customer_name': getattr(conversation, 'customer_name_clean', None) or getattr(conversation, 'customer_name_fm', None) or getattr(conversation, 'name', None),
            'care_priority': queue_row.get('care_priority'),
            'care_reason': queue_row.get('care_reason'),
            'waiting_minutes': queue_row.get('waiting_minutes') if queue_row.get('waiting_minutes') is not None else '',
            'last_customer_message_at': self._serialize_value((queue_row.get('metric') or {}).get('last_customer_message_at')),
            'last_staff_reply_at': self._serialize_value((queue_row.get('metric') or {}).get('last_staff_reply_at')),
            'external_url': self._build_external_url(conversation),
        }

    def _create_customer_care_followup_activity_result(
        self,
        env,
        conversation,
        assigned_user,
        normalized_payload,
        queue_row,
    ):
        activity_type_info = self._resolve_mcp_activity_type(
            env,
            activity_type_code=normalized_payload.get('activity_type_code') or 'auto',
            activity_type_xmlid=normalized_payload.get('activity_type_xmlid') or False,
            priority=queue_row.get('care_priority'),
        )
        if not activity_type_info.get('record'):
            raise ValueError("No executable activity type mapping is available for this priority")
        note = self._render_customer_care_note(
            normalized_payload.get('note_template'),
            self._build_customer_care_item_context(conversation, queue_row),
        )
        activity_payload = {
            'summary': normalized_payload['summary_template'],
            'note': note,
            'user_id': assigned_user.id,
            'deadline_date': normalized_payload.get('default_deadline_date') or self._build_customer_care_deadline_info(
                queue_row.get('care_priority'),
                env=env,
            ).get('recommended_deadline'),
            'request_id': self._get_customer_care_item_request_id(normalized_payload['request_id'], conversation.id, 'activity'),
            'agent_name': normalized_payload['agent_name'],
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'activity_type_xmlid': activity_type_info['xmlid'],
        }
        activity_fingerprint = self._compute_payload_fingerprint(activity_payload)
        result = self._create_conversation_followup_activity(
            env,
            conversation,
            activity_payload,
            activity_fingerprint,
        )
        data = result.get('data') or {}
        data['activity_type'] = {
            'id': activity_type_info['record'].id,
            'name': activity_type_info['record'].name,
            'xmlid': activity_type_info['xmlid'],
            'code': activity_type_info['code'],
        }
        return data

    def _apply_customer_care_require_processing(
        self,
        env,
        conversation,
        normalized_payload,
        queue_row,
    ):
        if not normalized_payload.get('set_require_processing'):
            return {}
        if not queue_row.get('matches'):
            return {}
        if bool(getattr(conversation, 'require_processing', False)):
            return {}
        triage_payload = {
            'require_processing': True,
            'request_id': self._get_customer_care_item_request_id(normalized_payload['request_id'], conversation.id, 'triage'),
            'agent_name': normalized_payload['agent_name'],
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
        }
        triage_fingerprint = self._compute_payload_fingerprint(triage_payload)
        result = self._update_conversation_triage(
            env,
            conversation,
            triage_payload,
            triage_fingerprint,
        )
        return result.get('data') or {}

    def _build_customer_care_followup_item_result(
        self,
        conversation,
        queue_row,
        action,
        assigned_user_id=None,
        deadline_date=None,
        activity_id=None,
        activity_type=None,
        existing_activity_id=None,
        log_id=None,
        skip_reason=None,
        ok=True,
        error=None,
    ):
        item = {
            'conversation_id': conversation.id,
            'ok': bool(ok),
            'action': action,
            'care_priority': queue_row.get('care_priority'),
            'care_reason': queue_row.get('care_reason'),
            'waiting_minutes': queue_row.get('waiting_minutes'),
        }
        if assigned_user_id:
            item['assigned_user_id'] = assigned_user_id
        if deadline_date:
            item['deadline_date'] = self._serialize_value(deadline_date)
        if activity_id:
            item['activity_id'] = activity_id
        if activity_type:
            item['activity_type'] = activity_type
        if existing_activity_id:
            item['existing_activity_id'] = existing_activity_id
        if log_id:
            item['log_id'] = log_id
        if skip_reason:
            item['skip_reason'] = skip_reason
        if error:
            item['error'] = error
        return item

    def _collect_customer_care_queue_rows(self, env=None, sla_minutes=60, urgent_minutes=120, **params):
        env = self._get_env(env)
        domain_params = {
            'conversation_id': params.get('conversation_id'),
            'page_id': params.get('page_id'),
            'platform': params.get('platform'),
            'owner_id': params.get('owner_id'),
            'assignee_user_id': params.get('assignee_user_id'),
            'tag_code': params.get('tag_code'),
            'tag_mode': 'any',
            'date_field': 'last_message_at_fm',
            'is_internal': False,
            # Exclude conversations already marked as handled (status_state='done').
            # These have been actioned and should not appear in the care queue.
            'status': 'new,recontact,waiting',
        }
        domain, _applied_filters, date_field = self._build_v2_conversation_domain(env=env, params=domain_params)
        Conv = env['page.fm.conversation'].sudo()
        candidates = Conv.search(domain, order='%s desc, id desc' % date_field)
        metrics = self._build_conversation_business_metrics(env=env, conversation_ids=candidates.ids)

        queue_rows = []
        for conversation in candidates:
            metric = metrics.get(conversation.id, {})
            row = self._build_customer_care_row(conversation, metric, sla_minutes, urgent_minutes)
            if not row['matches']:
                continue
            queue_rows.append(row)

        priority_rank = {'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}
        queue_rows.sort(
            key=lambda row: (
                priority_rank.get(row['care_priority'], 9),
                -(row['waiting_minutes'] if row['waiting_minutes'] is not None else -1),
                row['metric'].get('last_customer_message_at') or datetime.min,
                row['conversation'].id,
            )
        )
        return queue_rows

    def _build_customer_care_queue_payload(self, env=None, include_messages=False, message_limit=10, **params):
        env = self._get_env(env)
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=50,
            max_limit=100,
        )
        threshold_config = self._get_customer_care_threshold_config(
            env=env,
            request_sla_minutes=params.get('sla_minutes'),
            request_urgent_minutes=params.get('urgent_minutes'),
        )
        queue_rows = self._collect_customer_care_queue_rows(
            env=env,
            sla_minutes=threshold_config['sla_minutes'],
            urgent_minutes=threshold_config['urgent_minutes'],
            conversation_id=params.get('conversation_id'),
            page_id=params.get('page_id'),
            platform=params.get('platform'),
            owner_id=params.get('owner_id'),
            assignee_user_id=params.get('assignee_user_id'),
            tag_code=params.get('tag_code'),
        )
        total = len(queue_rows)
        page_rows = queue_rows[offset:offset + limit]

        items = []
        for row in page_rows:
            items.append(self._serialize_customer_care_row(
                row,
                env=env,
                include_messages=include_messages,
                message_limit=message_limit,
                params=params,
            ))
        payload = self._mcp_list_payload(items, total)
        payload['config'] = threshold_config
        return payload

    def _process_customer_care_followup_item(self, env, conversation, queue_row, normalized_payload):
        deadline_date = normalized_payload.get('default_deadline_date') or self._build_customer_care_deadline_info(
            queue_row.get('care_priority'),
            env=env,
        ).get('recommended_deadline')
        if bool(getattr(conversation, 'is_internal_conversation', False)):
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='skipped',
                skip_reason='invalid_conversation_state',
            )

        if getattr(conversation, 'status_state', None) == 'done' and not queue_row.get('matches'):
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='skipped',
                skip_reason='already_done',
            )

        if normalized_payload.get('revalidate_queue') and not queue_row.get('matches'):
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='skipped',
                skip_reason='not_in_customer_care_queue',
            )

        assigned_user = self._get_customer_care_assignee_user(conversation, env=env)
        if not assigned_user:
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='skipped',
                skip_reason='no_assigned_user',
            )

        summary = normalized_payload['summary_template']
        if normalized_payload.get('dedupe_existing_open_activity'):
            existing_activity = self._find_existing_customer_care_open_activity(
                env,
                conversation,
                summary,
                reason=normalized_payload.get('reason'),
            )
            if existing_activity:
                return self._build_customer_care_followup_item_result(
                    conversation,
                    queue_row,
                    action='skipped',
                    assigned_user_id=existing_activity.user_id.id or assigned_user.id,
                    deadline_date=existing_activity.date_deadline or deadline_date,
                    existing_activity_id=existing_activity.id,
                    skip_reason='open_activity_exists',
                )

        if normalized_payload.get('dry_run'):
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='would_create',
                assigned_user_id=assigned_user.id,
                deadline_date=deadline_date,
            )

        try:
            with env.cr.savepoint():
                activity_data = self._create_customer_care_followup_activity_result(
                    env,
                    conversation,
                    assigned_user,
                    normalized_payload,
                    queue_row,
                )
                self._apply_customer_care_require_processing(
                    env,
                    conversation,
                    normalized_payload,
                    queue_row,
                )
                return self._build_customer_care_followup_item_result(
                    conversation,
                    queue_row,
                    action='created',
                    assigned_user_id=activity_data.get('assigned_user_id') or assigned_user.id,
                    deadline_date=activity_data.get('deadline_date') or deadline_date,
                    activity_id=activity_data.get('activity_id'),
                    activity_type=activity_data.get('activity_type'),
                    log_id=activity_data.get('log_id'),
                )
        except (ValueError, ValidationError) as exc:
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='failed',
                ok=False,
                error={'code': 'validation_error', 'message': str(exc)},
            )
        except UserError as exc:
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='failed',
                ok=False,
                error={'code': 'business_rule_violation', 'message': str(exc)},
            )
        except Exception as exc:
            _logger.exception(
                "Customer care follow-up item failed for conversation %s",
                conversation.id,
            )
            return self._build_customer_care_followup_item_result(
                conversation,
                queue_row,
                action='failed',
                ok=False,
                error={'code': 'unexpected_error', 'message': str(exc)},
            )

    def _run_mcp_customer_care_create_followups(self, payload=None, env=None):
        env = self._get_mcp_write_env(env)
        try:
            normalized_payload = self._normalize_mcp_customer_care_followup_payload(payload=payload, env=env)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)

        existing_log = self._handle_mcp_bulk_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_bulk_replayed_response_data(existing_log)

        conversations = env['page.fm.conversation'].sudo().browse(normalized_payload['conversation_ids']).exists()
        if not conversations:
            raise McpHttpError(404, 'not_found', 'Conversation not found')

        conversation_map = {conversation.id: conversation for conversation in conversations}
        metrics = self._build_conversation_business_metrics(env=env, conversation_ids=conversations.ids)

        items = []
        created_count = 0
        skipped_count = 0
        failed_count = 0

        try:
            for conversation_id in normalized_payload['conversation_ids']:
                conversation = conversation_map.get(conversation_id)
                if not conversation:
                    items.append({
                        'conversation_id': conversation_id,
                        'ok': True,
                        'action': 'skipped',
                        'skip_reason': 'not_found',
                    })
                    skipped_count += 1
                    continue

                queue_row = self._build_customer_care_row(
                    conversation,
                    metrics.get(conversation.id, {}),
                    normalized_payload['sla_minutes'],
                    normalized_payload['urgent_minutes'],
                )
                if not normalized_payload.get('default_deadline_date'):
                    deadline_info = self._build_customer_care_deadline_info(queue_row.get('care_priority'), env=env)
                    normalized_payload['default_deadline_date'] = deadline_info.get('recommended_deadline')
                item = self._process_customer_care_followup_item(
                    env,
                    conversation,
                    queue_row,
                    normalized_payload,
                )
                items.append(item)
                if item['action'] == 'created':
                    created_count += 1
                elif item['action'] in ('skipped', 'would_create'):
                    skipped_count += 1
                elif item['action'] == 'failed':
                    failed_count += 1

            response_data = {
                'request_id': normalized_payload['request_id'],
                'created_count': 0 if normalized_payload.get('dry_run') else created_count,
                'skipped_count': skipped_count,
                'failed_count': failed_count,
                'dry_run': bool(normalized_payload.get('dry_run')),
                'items': items,
                'idempotent_replay': False,
            }
            bulk_log = self._create_mcp_bulk_log(
                env=env,
                action_type='customer_care_create_followups',
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data=response_data,
                status='success',
            )
            bulk_log.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
            return response_data
        except McpHttpError:
            raise
        except Exception as exc:
            _logger.exception("Customer care follow-up bulk request failed")
            self._create_mcp_bulk_log(
                env=env,
                action_type='customer_care_create_followups',
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data={},
                status='failed',
                error_code='unexpected_error',
                error_message=str(exc),
            )
            raise

    def _render_customer_care_plain_text(self, template, context_values, default_template=None):
        template = (template or '').strip()
        if not template:
            template = (default_template or '').strip()
        if not template:
            return False

        class SafeMap(dict):
            def __missing__(self, key):
                return ''

        safe_values = SafeMap({
            key: self._safe_customer_care_template_value(value)
            for key, value in (context_values or {}).items()
        })
        try:
            return template.format_map(safe_values).strip()
        except Exception:
            return template.strip()

    def _normalize_mcp_customer_care_reviewed_actions_payload(self, payload=None):
        payload = self._get_v3_json_payload(payload=payload)
        allowed_fields = {
            'items',
            'default_note_template',
            'revalidate_queue',
            'dry_run',
            'request_id',
            'agent_name',
            'model_name',
            'reason',
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported customer-care reviewed-action fields: %s" % ', '.join(unknown_fields))

        metadata = self._normalize_mcp_order_metadata(payload)
        if not metadata.get('reason'):
            raise ValueError("reason is required")

        items = payload.get('items')
        if not isinstance(items, list):
            raise ValueError("items is required")
        if not items:
            raise ValueError("items cannot be empty")
        if len(items) > 50:
            raise ValueError("items cannot contain more than 50 items")

        default_note_template = payload.get('default_note_template')
        if default_note_template not in (None, False):
            if not isinstance(default_note_template, str):
                raise ValueError("default_note_template must be a string")
            default_note_template = default_note_template.strip() or False
        else:
            default_note_template = False

        revalidate_queue = self._coerce_mcp_nullable_bool(payload.get('revalidate_queue'), 'revalidate_queue')
        dry_run = self._coerce_mcp_nullable_bool(payload.get('dry_run'), 'dry_run')

        normalized_items = []
        allowed_item_fields = {'conversation_id', 'note_text', 'note_type', 'triage_preset', 'reason'}
        for index, raw_item in enumerate(items):
            normalized_item = {'item_index': index}
            if not isinstance(raw_item, dict):
                normalized_item['_item_error'] = {
                    'code': 'validation_error',
                    'message': 'items[%s] must be an object' % index,
                }
                normalized_items.append(normalized_item)
                continue

            unknown_item_fields = sorted(set(raw_item) - allowed_item_fields)
            if unknown_item_fields:
                normalized_item['_item_error'] = {
                    'code': 'validation_error',
                    'message': 'Unsupported items[%s] fields: %s' % (index, ', '.join(unknown_item_fields)),
                }
                normalized_items.append(normalized_item)
                continue

            try:
                normalized_item['conversation_id'] = self._as_int(
                    raw_item.get('conversation_id'),
                    'items[%s].conversation_id' % index,
                )
                if not normalized_item['conversation_id']:
                    raise ValueError("items[%s].conversation_id is required" % index)
            except ValueError as exc:
                normalized_item['_item_error'] = {
                    'code': 'validation_error',
                    'message': str(exc),
                }
                normalized_items.append(normalized_item)
                continue

            note_text = raw_item.get('note_text')
            if note_text not in (None, False):
                if not isinstance(note_text, str):
                    normalized_item['_item_error'] = {
                        'code': 'validation_error',
                        'message': 'items[%s].note_text must be a string' % index,
                    }
                    normalized_items.append(normalized_item)
                    continue
                note_text = note_text.strip() or False
            else:
                note_text = False

            note_type = raw_item.get('note_type', 'internal_note')
            if note_type not in (None, False):
                if not isinstance(note_type, str) or not note_type.strip():
                    normalized_item['_item_error'] = {
                        'code': 'validation_error',
                        'message': 'items[%s].note_type must be a non-empty string' % index,
                    }
                    normalized_items.append(normalized_item)
                    continue
                note_type = note_type.strip()
            else:
                note_type = 'internal_note'
            if note_type not in self.MCP_CUSTOMER_CARE_REVIEW_NOTE_TYPES:
                normalized_item['_item_error'] = {
                    'code': 'validation_error',
                    'message': 'items[%s].note_type must be one of %s' % (
                        index,
                        ','.join(sorted(self.MCP_CUSTOMER_CARE_REVIEW_NOTE_TYPES)),
                    ),
                }
                normalized_items.append(normalized_item)
                continue

            triage_preset = raw_item.get('triage_preset')
            if triage_preset not in (None, False):
                if not isinstance(triage_preset, str) or not triage_preset.strip():
                    normalized_item['_item_error'] = {
                        'code': 'validation_error',
                        'message': 'items[%s].triage_preset must be a non-empty string' % index,
                    }
                    normalized_items.append(normalized_item)
                    continue
                triage_preset = triage_preset.strip()
                if triage_preset not in self.MCP_CUSTOMER_CARE_TRIAGE_PRESETS:
                    normalized_item['_item_error'] = {
                        'code': 'validation_error',
                        'message': 'items[%s].triage_preset must be one of %s' % (
                            index,
                            ','.join(sorted(self.MCP_CUSTOMER_CARE_TRIAGE_PRESETS)),
                        ),
                    }
                    normalized_items.append(normalized_item)
                    continue
            else:
                triage_preset = False

            item_reason = raw_item.get('reason')
            if item_reason not in (None, False):
                if not isinstance(item_reason, str):
                    normalized_item['_item_error'] = {
                        'code': 'validation_error',
                        'message': 'items[%s].reason must be a string' % index,
                    }
                    normalized_items.append(normalized_item)
                    continue
                item_reason = item_reason.strip() or False
            else:
                item_reason = False

            normalized_item.update({
                'conversation_id': normalized_item['conversation_id'],
                'note_text': note_text,
                'note_type': note_type,
                'triage_preset': triage_preset,
                'reason': item_reason or metadata['reason'],
            })
            normalized_items.append(normalized_item)

        return dict(
            metadata,
            items=normalized_items,
            default_note_template=default_note_template,
            revalidate_queue=True if revalidate_queue is None else revalidate_queue,
            dry_run=False if dry_run is None else dry_run,
        )

    def _build_customer_care_review_item_context(self, conversation, queue_row, triage_preset=None):
        values = self._build_customer_care_item_context(conversation, queue_row)
        values['triage_preset'] = triage_preset or ''
        return values

    def _customer_care_staff_has_replied_after_customer(self, queue_row):
        metric = queue_row.get('metric') or {}
        last_customer = metric.get('last_customer_message_at')
        last_staff = metric.get('last_staff_reply_at')
        if not last_customer or not last_staff:
            return False
        if last_staff >= last_customer:
            return True
        return bool(metric.get('_last_message_role') == 'staff')

    def _build_customer_care_review_note_text(self, conversation, queue_row, item_payload, request_payload):
        note_text = item_payload.get('note_text')
        if note_text:
            return note_text
        return self._render_customer_care_plain_text(
            request_payload.get('default_note_template'),
            self._build_customer_care_review_item_context(
                conversation,
                queue_row,
                triage_preset=item_payload.get('triage_preset'),
            ),
        )

    def _build_customer_care_reviewed_triage_plan(self, conversation, queue_row, item_payload, request_payload):
        preset = item_payload.get('triage_preset')
        if not preset or preset == 'note_only':
            return {'apply': False}

        if getattr(conversation, 'status_state', None) == 'done':
            return {'apply': False, 'skip_reason': 'already_done'}

        queue_matches = bool(queue_row.get('matches'))
        staff_replied_after_customer = self._customer_care_staff_has_replied_after_customer(queue_row)
        target_values = {}

        if preset in ('needs_staff_reply', 'needs_internal_review'):
            if not queue_matches:
                return {'apply': False, 'skip_reason': 'not_in_customer_care_queue'}
            target_values = {
                'status_state': 'recontact',
                'require_processing': True,
            }
        elif preset == 'keep_processing':
            if not queue_matches:
                return {'apply': False, 'skip_reason': 'not_in_customer_care_queue'}
            target_values = {
                'require_processing': True,
            }
        elif preset == 'waiting_customer':
            if not staff_replied_after_customer:
                return {'apply': False, 'skip_reason': 'unsafe_waiting_customer_preset'}
            target_values = {
                'status_state': 'waiting',
                'require_processing': False,
            }
        elif preset == 'clear_processing_after_staff_reply':
            if not staff_replied_after_customer:
                return {'apply': False, 'skip_reason': 'unsafe_clear_processing'}
            target_values = {
                'require_processing': False,
            }

        changed_fields = {}
        current_status = getattr(conversation, 'status_state', None)
        current_processing = bool(getattr(conversation, 'require_processing', False))
        if 'status_state' in target_values and target_values['status_state'] != current_status:
            changed_fields['status_state'] = target_values['status_state']
        if 'require_processing' in target_values and target_values['require_processing'] != current_processing:
            changed_fields['require_processing'] = target_values['require_processing']

        if not changed_fields:
            return {'apply': False, 'skip_reason': 'no_change_needed'}

        triage_payload = {
            'request_id': self._get_customer_care_item_request_id(
                request_payload['request_id'],
                conversation.id,
                'triage',
                item_index=item_payload.get('item_index'),
            ),
            'agent_name': request_payload['agent_name'],
            'model_name': request_payload.get('model_name') or False,
            'reason': item_payload.get('reason') or request_payload.get('reason') or False,
        }
        triage_payload.update(changed_fields)
        return {
            'apply': True,
            'payload': triage_payload,
            'changed_fields': changed_fields,
        }

    def _build_customer_care_reviewed_item_result(
        self,
        conversation_id,
        queue_row=None,
        ok=True,
        action='skipped',
        note_log_id=None,
        triage_log_id=None,
        triage_preset=None,
        changed_fields=None,
        skip_reason=None,
        error=None,
    ):
        queue_row = queue_row or {}
        return {
            'conversation_id': conversation_id,
            'ok': bool(ok),
            'action': action,
            'note_log_id': note_log_id,
            'triage_log_id': triage_log_id,
            'triage_preset': triage_preset or False,
            'changed_fields': changed_fields or {},
            'care_priority': queue_row.get('care_priority'),
            'care_reason': queue_row.get('care_reason'),
            'waiting_minutes': queue_row.get('waiting_minutes'),
            'skip_reason': skip_reason,
            'error': error,
        }

    def _process_customer_care_reviewed_action_item(self, env, item_payload, conversation_map, metrics, request_payload, threshold_config=None):
        conversation_id = item_payload.get('conversation_id')
        if item_payload.get('_item_error'):
            return self._build_customer_care_reviewed_item_result(
                conversation_id,
                ok=False,
                action='failed',
                error=item_payload['_item_error'],
            )

        conversation = conversation_map.get(conversation_id)
        if not conversation:
            return self._build_customer_care_reviewed_item_result(
                conversation_id,
                action='skipped',
                skip_reason='not_found',
            )

        threshold_config = threshold_config or self._get_customer_care_threshold_config(env=env)
        queue_row = self._build_customer_care_row(
            conversation,
            metrics.get(conversation.id, {}),
            threshold_config['sla_minutes'],
            threshold_config['urgent_minutes'],
        )

        if bool(getattr(conversation, 'is_internal_conversation', False)):
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                action='skipped',
                triage_preset=item_payload.get('triage_preset'),
                skip_reason='internal_conversation',
            )

        note_text = self._build_customer_care_review_note_text(
            conversation,
            queue_row,
            item_payload,
            request_payload,
        )
        triage_plan = self._build_customer_care_reviewed_triage_plan(
            conversation,
            queue_row,
            item_payload,
            request_payload,
        )
        triage_preset = item_payload.get('triage_preset') or False
        note_requested = bool(note_text)
        triage_requested = bool(triage_preset and triage_preset != 'note_only')

        if not note_requested and not triage_requested and not triage_preset:
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                action='skipped',
                skip_reason='no_action_requested',
            )

        if triage_preset == 'note_only' and not note_requested:
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                action='skipped',
                triage_preset=triage_preset,
                skip_reason='no_action_requested',
            )

        triage_will_apply = bool(triage_plan.get('apply'))
        triage_skip_reason = triage_plan.get('skip_reason')

        if request_payload.get('dry_run'):
            if note_requested and triage_will_apply:
                action = 'would_create_note_and_update_triage'
            elif note_requested:
                action = 'would_create_note'
            elif triage_will_apply:
                action = 'would_update_triage'
            else:
                action = 'skipped'
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                action=action,
                triage_preset=triage_preset,
                changed_fields=triage_plan.get('changed_fields') or {},
                skip_reason=triage_skip_reason if action == 'skipped' else None,
            )

        if not note_requested and not triage_will_apply:
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                action='skipped',
                triage_preset=triage_preset,
                skip_reason=triage_skip_reason or 'no_action_requested',
            )

        note_payload = False
        note_fingerprint = False
        if note_requested:
            note_payload = {
                'note_text': note_text,
                'note_type': item_payload.get('note_type') or 'internal_note',
                'request_id': self._get_customer_care_item_request_id(
                    request_payload['request_id'],
                    conversation.id,
                    'note',
                    item_index=item_payload.get('item_index'),
                ),
                'agent_name': request_payload['agent_name'],
                'model_name': request_payload.get('model_name') or False,
                'reason': item_payload.get('reason') or request_payload.get('reason') or False,
            }
            note_fingerprint = self._compute_payload_fingerprint(note_payload)

        try:
            with env.cr.savepoint():
                note_result = {}
                triage_result = {}
                if note_payload:
                    note_result = self._create_mcp_conversation_ai_note(
                        env,
                        conversation,
                        note_payload,
                        note_fingerprint,
                    )
                if triage_will_apply:
                    triage_payload = triage_plan['payload']
                    triage_result = self._update_conversation_triage(
                        env,
                        conversation,
                        triage_payload,
                        self._compute_payload_fingerprint(triage_payload),
                    )
        except (ValueError, ValidationError) as exc:
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                ok=False,
                action='failed',
                triage_preset=triage_preset,
                error={'code': 'validation_error', 'message': str(exc)},
            )
        except UserError as exc:
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                ok=False,
                action='failed',
                triage_preset=triage_preset,
                error={'code': 'business_rule_violation', 'message': str(exc)},
            )
        except Exception as exc:
            _logger.exception(
                "Customer care reviewed-action item failed for conversation %s",
                conversation.id,
            )
            return self._build_customer_care_reviewed_item_result(
                conversation.id,
                queue_row=queue_row,
                ok=False,
                action='failed',
                triage_preset=triage_preset,
                error={'code': 'unexpected_error', 'message': str(exc)},
            )

        if note_payload and triage_will_apply:
            action = 'note_created_and_triage_updated'
        elif note_payload:
            action = 'note_created' if not triage_requested else 'note_created_triage_skipped'
        else:
            action = 'triage_updated'

        return self._build_customer_care_reviewed_item_result(
            conversation.id,
            queue_row=queue_row,
            action=action,
            note_log_id=(note_result or {}).get('log_id'),
            triage_log_id=(triage_result or {}).get('log_id'),
            triage_preset=triage_preset,
            changed_fields=(triage_result or {}).get('changed_fields') or (triage_plan.get('changed_fields') or {}),
            skip_reason=triage_skip_reason if action == 'note_created_triage_skipped' else None,
        )

    def _run_mcp_customer_care_apply_reviewed_actions(self, payload=None, env=None):
        env = self._get_mcp_write_env(env)
        try:
            normalized_payload = self._normalize_mcp_customer_care_reviewed_actions_payload(payload=payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)

        existing_log = self._handle_mcp_bulk_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_bulk_replayed_response_data(existing_log)

        valid_conversation_ids = [
            item['conversation_id']
            for item in normalized_payload['items']
            if item.get('conversation_id')
        ]
        conversations = env['page.fm.conversation'].sudo().browse(valid_conversation_ids).exists()
        if valid_conversation_ids and not conversations:
            raise McpHttpError(404, 'not_found', 'Conversation not found')

        conversation_map = {conversation.id: conversation for conversation in conversations}
        metrics = self._build_conversation_business_metrics(env=env, conversation_ids=conversations.ids)

        items = []
        processed_count = len(normalized_payload['items'])
        note_created_count = 0
        triage_updated_count = 0
        skipped_count = 0
        failed_count = 0

        try:
            for item_payload in normalized_payload['items']:
                item_result = self._process_customer_care_reviewed_action_item(
                    env,
                    item_payload,
                    conversation_map,
                    metrics,
                    normalized_payload,
                )
                items.append(item_result)
                if item_result['action'] in ('note_created', 'note_created_and_triage_updated', 'note_created_triage_skipped'):
                    note_created_count += 1
                if item_result['action'] in ('triage_updated', 'note_created_and_triage_updated'):
                    triage_updated_count += 1
                if item_result['action'] == 'skipped':
                    skipped_count += 1
                if item_result['action'] == 'failed':
                    failed_count += 1

            response_data = {
                'request_id': normalized_payload['request_id'],
                'processed_count': processed_count,
                'note_created_count': 0 if normalized_payload.get('dry_run') else note_created_count,
                'triage_updated_count': 0 if normalized_payload.get('dry_run') else triage_updated_count,
                'skipped_count': skipped_count,
                'failed_count': failed_count,
                'dry_run': bool(normalized_payload.get('dry_run')),
                'items': items,
                'idempotent_replay': False,
            }
            bulk_log = self._create_mcp_bulk_log(
                env=env,
                action_type='customer_care_apply_reviewed_actions',
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data=response_data,
                status='success',
            )
            bulk_log.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
            return response_data
        except McpHttpError:
            raise
        except Exception as exc:
            _logger.exception("Customer care reviewed-actions bulk request failed")
            self._create_mcp_bulk_log(
                env=env,
                action_type='customer_care_apply_reviewed_actions',
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data={},
                status='failed',
                error_code='unexpected_error',
                error_message=str(exc),
            )
            raise

    def _normalize_mcp_customer_care_action_plan_payload(self, payload=None, env=None):
        env = self._get_env(env)
        payload = self._get_optional_v3_json_payload(payload=payload)
        allowed_fields = {
            'conversation_ids',
            'filters',
            'sla_minutes',
            'urgent_minutes',
            'limit',
            'offset',
            'include_messages',
            'message_limit',
            'include_existing_activity_check',
            'policy',
            'default_deadline_date',
            'templates',
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported customer-care action-plan fields: %s" % ', '.join(unknown_fields))

        conversation_ids = payload.get('conversation_ids')
        cleaned_ids = []
        if conversation_ids not in (None, False):
            if not isinstance(conversation_ids, list):
                raise ValueError("conversation_ids must be a list")
            if len(conversation_ids) > 50:
                raise ValueError("conversation_ids cannot contain more than 50 items")
            seen_ids = set()
            for index, value in enumerate(conversation_ids):
                conversation_id = self._as_int(value, 'conversation_ids[%s]' % index)
                if not conversation_id:
                    raise ValueError("conversation_ids[%s] must be an integer" % index)
                if conversation_id in seen_ids:
                    continue
                seen_ids.add(conversation_id)
                cleaned_ids.append(conversation_id)

        filters = payload.get('filters') or {}
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")
        allowed_filter_fields = {'assignee_user_id', 'owner_id', 'page_id', 'platform', 'conversation_id', 'tag_code'}
        unknown_filter_fields = sorted(set(filters) - allowed_filter_fields)
        if unknown_filter_fields:
            raise ValueError("Unsupported filters fields: %s" % ', '.join(unknown_filter_fields))

        templates = payload.get('templates') or {}
        if not isinstance(templates, dict):
            raise ValueError("templates must be an object")
        allowed_template_fields = {'followup_summary', 'followup_note', 'internal_note'}
        unknown_template_fields = sorted(set(templates) - allowed_template_fields)
        if unknown_template_fields:
            raise ValueError("Unsupported templates fields: %s" % ', '.join(unknown_template_fields))

        normalized_templates = {}
        for key in allowed_template_fields:
            value = templates.get(key)
            if value not in (None, False):
                if not isinstance(value, str):
                    raise ValueError("templates.%s must be a string" % key)
                value = value.strip() or False
            else:
                value = False
            normalized_templates[key] = value

        include_messages = self._coerce_mcp_nullable_bool(payload.get('include_messages'), 'include_messages')
        include_existing_activity_check = self._coerce_mcp_nullable_bool(
            payload.get('include_existing_activity_check'),
            'include_existing_activity_check',
        )
        limit, offset = self._normalize_capped_limit_offset(
            limit=payload.get('limit'),
            offset=payload.get('offset'),
            default_limit=50,
            max_limit=100,
        )

        normalized_filters = {}
        for field_name in ('assignee_user_id', 'owner_id', 'page_id', 'conversation_id'):
            normalized_filters[field_name] = self._coerce_nullable_int(filters.get(field_name), field_name)
        platform = filters.get('platform')
        if platform not in (None, False):
            if not isinstance(platform, str):
                raise ValueError("filters.platform must be a string")
            platform = platform.strip() or False
        else:
            platform = False
        normalized_filters['platform'] = platform
        tag_code = filters.get('tag_code')
        if tag_code not in (None, False):
            if not isinstance(tag_code, str):
                raise ValueError("filters.tag_code must be a string")
            tag_code = tag_code.strip() or False
        else:
            tag_code = False
        normalized_filters['tag_code'] = tag_code

        default_deadline_date = self._coerce_nullable_date(payload.get('default_deadline_date'), 'default_deadline_date')
        threshold_config = self._get_customer_care_threshold_config(
            env=env,
            request_sla_minutes=payload.get('sla_minutes'),
            request_urgent_minutes=payload.get('urgent_minutes'),
        )
        if payload.get('policy') in (None, ''):
            policy, policy_source = self._get_customer_care_default_policy(env=env)
        else:
            policy = payload.get('policy')
            if not isinstance(policy, str):
                raise ValueError("policy must be one of conservative,standard,urgent_only")
            policy = policy.strip()
            policy_source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST
        if policy not in self.MCP_ALLOWED_CUSTOMER_CARE_POLICIES:
            raise ValueError("policy must be one of conservative,standard,urgent_only")

        return {
            'conversation_ids': cleaned_ids,
            'filters': normalized_filters,
            'sla_minutes': threshold_config['sla_minutes'],
            'urgent_minutes': threshold_config['urgent_minutes'],
            'limit': limit,
            'offset': offset,
            'include_messages': bool(include_messages) if include_messages is not None else False,
            'message_limit': self._normalize_customer_care_message_limit(payload.get('message_limit'), default_limit=10, max_limit=20),
            'include_existing_activity_check': True if include_existing_activity_check is None else include_existing_activity_check,
            'policy': policy,
            'policy_source': policy_source,
            'default_deadline_date': default_deadline_date,
            'templates': normalized_templates,
        }

    def _customer_care_assignee_available(self, conversation, env=None):
        assigned_user = self._get_customer_care_assignee_user(conversation, env=env)
        return bool(assigned_user and assigned_user.exists()), assigned_user

    def _render_customer_care_plan_template(self, template, conversation, queue_row, triage_preset=None, default_template=None):
        return self._render_customer_care_plain_text(
            template,
            self._build_customer_care_review_item_context(
                conversation,
                queue_row,
                triage_preset=triage_preset,
            ),
            default_template=default_template,
        )

    def _serialize_customer_care_plan_conversation(self, conversation, queue_row):
        raw_item = self._serialize_conversation_v2(conversation, business_metric=queue_row.get('metric') or {})
        return normalize_conversation_item(raw_item, conversation=conversation)

    def _build_customer_care_activity_recommendation(self, env, priority, default_deadline_date=None):
        deadline_info = self._build_customer_care_deadline_info(priority, env=env)
        recommended_deadline = default_deadline_date or deadline_info.get('recommended_deadline')
        activity_type_info = self._resolve_mcp_activity_type(
            env,
            activity_type_code='auto',
            activity_type_xmlid=False,
            priority=priority,
        )
        return {
            'activity_type_code': activity_type_info.get('code') or self.MCP_ACTIVITY_TYPE_NONE,
            'activity_type_xmlid': activity_type_info.get('xmlid'),
            'deadline_policy': deadline_info.get('deadline_policy'),
            'recommended_deadline': recommended_deadline,
        }

    def _build_customer_care_followup_payload_template(self, conversation, queue_row, normalized_payload, reason_code):
        templates = normalized_payload.get('templates') or {}
        activity_recommendation = self._build_customer_care_activity_recommendation(
            conversation.env,
            queue_row.get('care_priority'),
            default_deadline_date=normalized_payload.get('default_deadline_date'),
        )
        deadline_date = activity_recommendation.get('recommended_deadline')
        return {
            'conversation_ids': [conversation.id],
            'default_deadline_date': self._serialize_value(deadline_date) if deadline_date else None,
            'summary_template': templates.get('followup_summary') or self.MCP_CUSTOMER_CARE_DEFAULT_FOLLOWUP_SUMMARY,
            'note_template': self._render_customer_care_plan_template(
                templates.get('followup_note'),
                conversation,
                queue_row,
                default_template=self.MCP_CUSTOMER_CARE_DEFAULT_NOTE_TEMPLATE,
            ),
            'sla_minutes': normalized_payload['sla_minutes'],
            'activity_type_code': activity_recommendation.get('activity_type_code') or 'auto',
            'activity_type_xmlid': activity_recommendation.get('activity_type_xmlid'),
            'dedupe_existing_open_activity': True,
            'revalidate_queue': True,
            'set_require_processing': True,
            'dry_run': False,
            'request_id': self.MCP_CUSTOMER_CARE_PLAN_REQUEST_ID_PLACEHOLDER,
            'agent_name': 'OpenClaw',
            'model_name': '<OPTIONAL>',
            'reason': reason_code,
        }

    def _build_customer_care_reviewed_payload_template(self, conversation, queue_row, normalized_payload, triage_preset, reason_code):
        templates = normalized_payload.get('templates') or {}
        priority = queue_row.get('care_priority')
        note_type = 'warning' if priority == 'urgent' else 'internal_note'
        return {
            'items': [
                {
                    'conversation_id': conversation.id,
                    'note_text': self._render_customer_care_plan_template(
                        templates.get('internal_note'),
                        conversation,
                        queue_row,
                        triage_preset=triage_preset,
                        default_template='OpenClaw review: {care_priority} - {care_reason}. Khach da cho khoang {waiting_minutes} phut.',
                    ),
                    'note_type': note_type,
                    'triage_preset': triage_preset,
                    'reason': reason_code,
                }
            ],
            'revalidate_queue': True,
            'dry_run': False,
            'request_id': self.MCP_CUSTOMER_CARE_PLAN_REQUEST_ID_PLACEHOLDER,
            'agent_name': 'OpenClaw',
            'model_name': '<OPTIONAL>',
            'reason': 'reviewed_customer_care_actions',
        }

    def _build_customer_care_plan_step(self, step_type, target_route=None, payload_template=None, requires_human_review=True):
        step = {
            'type': step_type,
            'requires_human_review': bool(requires_human_review),
        }
        if target_route:
            step['target_route'] = target_route
        if payload_template is not None:
            step['payload_template'] = payload_template
        return step

    def _customer_care_policy_allows_action(self, policy, priority):
        if policy == 'urgent_only':
            return priority == 'urgent'
        if policy == 'conservative':
            return priority in ('urgent', 'high')
        return priority in ('urgent', 'high', 'medium')

    def _build_customer_care_action_plan_item(self, env, conversation, queue_row, normalized_payload):
        include_messages = normalized_payload.get('include_messages')
        existing_activity = False
        existing_activity_id = False
        if normalized_payload.get('include_existing_activity_check'):
            existing_activity = self._find_existing_customer_care_open_activity(
                env,
                conversation,
                (normalized_payload.get('templates') or {}).get('followup_summary') or self.MCP_CUSTOMER_CARE_DEFAULT_FOLLOWUP_SUMMARY,
                reason=queue_row.get('care_reason'),
            )
            existing_activity_id = existing_activity.id if existing_activity else False

        item = {
            'conversation_id': conversation.id,
            'status': 'monitor',
            'care_priority': queue_row.get('care_priority'),
            'care_reason': queue_row.get('care_reason'),
            'waiting_minutes': queue_row.get('waiting_minutes'),
            'existing_open_activity': bool(existing_activity),
            'existing_activity_id': existing_activity_id or None,
            'activity_recommendation': self._build_customer_care_activity_recommendation(
                env,
                queue_row.get('care_priority'),
                default_deadline_date=normalized_payload.get('default_deadline_date'),
            ),
            'recommended_summary': '',
            'recommended_steps': [],
            'conversation': self._serialize_customer_care_plan_conversation(conversation, queue_row),
            'messages': self._get_customer_care_messages(conversation.id, normalized_payload['message_limit'], env=env) if include_messages else [],
        }

        priority = queue_row.get('care_priority')
        policy = normalized_payload['policy']
        queue_matches = bool(queue_row.get('matches'))
        staff_replied_after_customer = self._customer_care_staff_has_replied_after_customer(queue_row)
        has_assignee, assigned_user = self._customer_care_assignee_available(conversation, env=env)
        require_processing = bool(getattr(conversation, 'require_processing', False))
        is_unread = bool(getattr(conversation, 'is_unread_fm', False))
        is_internal = bool(getattr(conversation, 'is_internal_conversation', False))
        status_state = getattr(conversation, 'status_state', None)
        reason_code = queue_row.get('care_reason')
        metric = queue_row.get('metric') or {}
        last_customer = metric.get('last_customer_message_at')
        last_staff = metric.get('last_staff_reply_at')
        customer_waiting = bool(last_customer and (not last_staff or last_customer > last_staff))

        if is_internal:
            item['status'] = 'skipped'
            item['skip_reason'] = 'internal_conversation'
            item['recommended_summary'] = 'Hoi thoai noi bo, khong de xuat write action qua customer-care flow.'
            item['recommended_steps'] = [self._build_customer_care_plan_step('no_action', requires_human_review=False)]
            return item

        if status_state == 'done':
            if queue_matches:
                item['status'] = 'manual_review'
                item['recommended_summary'] = 'Hoi thoai da done nhung van con dau hieu care-risk, can nhan vien xem tay.'
                item['recommended_steps'] = [self._build_customer_care_plan_step('monitor', requires_human_review=True)]
            else:
                item['status'] = 'skipped'
                item['skip_reason'] = 'already_done'
                item['recommended_summary'] = 'Hoi thoai da done va khong con de xuat action an toan.'
                item['recommended_steps'] = [self._build_customer_care_plan_step('no_action', requires_human_review=False)]
            return item

        if not queue_matches and not staff_replied_after_customer:
            item['status'] = 'skipped'
            item['skip_reason'] = 'not_in_customer_care_queue'
            item['recommended_summary'] = 'Hoi thoai hien khong nam trong queue risk va khong co preset an toan nao can ap dung.'
            item['recommended_steps'] = [self._build_customer_care_plan_step('no_action', requires_human_review=False)]
            return item

        if not self._customer_care_policy_allows_action(policy, priority):
            if priority == 'medium' and policy == 'conservative':
                item['status'] = 'read_more' if not include_messages else 'monitor'
                item['recommended_summary'] = 'Muc uu tien trung binh; policy conservative chi de xuat doc them context hoac monitor.'
                item['recommended_steps'] = [self._build_customer_care_plan_step('read_context' if not include_messages else 'monitor', requires_human_review=True)]
            else:
                item['status'] = 'skipped'
                item['skip_reason'] = 'skipped_by_policy'
                item['recommended_summary'] = 'Policy hien tai khong cho phep de xuat executable action cho muc uu tien nay.'
                item['recommended_steps'] = [self._build_customer_care_plan_step('monitor', requires_human_review=True)]
            return item

        recommended_steps = []
        if customer_waiting:
            item['recommended_summary'] = 'Khach dang cho phan hoi, nen tao nhac viec va danh dau can xu ly neu an toan.'
            if not has_assignee:
                recommended_steps.append(self._build_customer_care_plan_step('manual_assignment_review'))
                item['status'] = 'manual_review'
            else:
                if not existing_activity:
                    recommended_steps.append(self._build_customer_care_plan_step(
                        'create_followup',
                        target_route='POST /dac_erp/mcp/v1/customer-care/create-followups',
                        payload_template=self._build_customer_care_followup_payload_template(
                            conversation,
                            queue_row,
                            normalized_payload,
                            reason_code,
                        ),
                    ))
                recommended_steps.append(self._build_customer_care_plan_step(
                    'apply_reviewed_actions',
                    target_route='POST /dac_erp/mcp/v1/customer-care/apply-reviewed-actions',
                    payload_template=self._build_customer_care_reviewed_payload_template(
                        conversation,
                        queue_row,
                        normalized_payload,
                        'needs_staff_reply',
                        reason_code,
                    ),
                ))
                item['status'] = 'action_recommended'
        elif require_processing and staff_replied_after_customer:
            if policy == 'standard':
                item['status'] = 'action_recommended'
                item['recommended_summary'] = 'Hoi thoai van require_processing du staff da reply; co the clear processing neu da an toan.'
                recommended_steps.append(self._build_customer_care_plan_step(
                    'apply_reviewed_actions',
                    target_route='POST /dac_erp/mcp/v1/customer-care/apply-reviewed-actions',
                    payload_template=self._build_customer_care_reviewed_payload_template(
                        conversation,
                        queue_row,
                        normalized_payload,
                        'clear_processing_after_staff_reply',
                        'staff_replied_waiting_customer',
                    ),
                ))
            else:
                item['status'] = 'manual_review'
                item['recommended_summary'] = 'Can xac nhan bang tay truoc khi clear processing theo policy hien tai.'
                recommended_steps.append(self._build_customer_care_plan_step('monitor'))
        elif staff_replied_after_customer and is_unread:
            if policy == 'conservative':
                item['status'] = 'read_more' if not include_messages else 'monitor'
                item['recommended_summary'] = 'Staff da reply gan day; policy conservative chi de xuat doc them hoac monitor.'
                recommended_steps.append(self._build_customer_care_plan_step('read_context' if not include_messages else 'monitor'))
            else:
                item['status'] = 'action_recommended'
                item['recommended_summary'] = 'Staff da reply sau khach; co the cap nhat waiting_customer neu can.'
                recommended_steps.append(self._build_customer_care_plan_step(
                    'apply_reviewed_actions',
                    target_route='POST /dac_erp/mcp/v1/customer-care/apply-reviewed-actions',
                    payload_template=self._build_customer_care_reviewed_payload_template(
                        conversation,
                        queue_row,
                        normalized_payload,
                        'waiting_customer',
                        'staff_replied_waiting_customer',
                    ),
                ))
        elif priority == 'medium' and policy == 'standard' and queue_matches:
            if existing_activity:
                item['status'] = 'monitor'
                item['recommended_summary'] = 'Da co open activity phu hop cho muc uu tien trung binh; chi can monitor them.'
                recommended_steps.append(self._build_customer_care_plan_step('monitor'))
            elif not has_assignee:
                item['status'] = 'manual_review'
                item['recommended_summary'] = 'Hoi thoai muc uu tien trung binh chua co owner/assignee hop le, can review va phan cong tay.'
                recommended_steps.append(self._build_customer_care_plan_step('manual_assignment_review'))
            else:
                item['status'] = 'action_recommended'
                item['recommended_summary'] = 'Hoi thoai muc uu tien trung binh van con queue risk; co the tao To Do follow-up an toan.'
                recommended_steps.append(self._build_customer_care_plan_step(
                    'create_followup',
                    target_route='POST /dac_erp/mcp/v1/customer-care/create-followups',
                    payload_template=self._build_customer_care_followup_payload_template(
                        conversation,
                        queue_row,
                        normalized_payload,
                        reason_code,
                    ),
                ))
                if require_processing:
                    recommended_steps.append(self._build_customer_care_plan_step(
                        'apply_reviewed_actions',
                        target_route='POST /dac_erp/mcp/v1/customer-care/apply-reviewed-actions',
                        payload_template=self._build_customer_care_reviewed_payload_template(
                            conversation,
                            queue_row,
                            normalized_payload,
                            'keep_processing',
                            reason_code,
                        ),
                    ))
        elif existing_activity:
            item['status'] = 'monitor'
            item['recommended_summary'] = 'Da co open activity phu hop, khong de xuat tao follow-up moi.'
            if priority in ('urgent', 'high'):
                recommended_steps.append(self._build_customer_care_plan_step(
                    'apply_reviewed_actions',
                    target_route='POST /dac_erp/mcp/v1/customer-care/apply-reviewed-actions',
                    payload_template=self._build_customer_care_reviewed_payload_template(
                        conversation,
                        queue_row,
                        normalized_payload,
                        'note_only',
                        reason_code,
                    ),
                ))
            else:
                recommended_steps.append(self._build_customer_care_plan_step('monitor'))
        elif not has_assignee:
            item['status'] = 'manual_review'
            item['recommended_summary'] = 'Hoi thoai chua co owner/assignee hop le, can review va phan cong tay.'
            recommended_steps.append(self._build_customer_care_plan_step('manual_assignment_review'))
        else:
            item['status'] = 'monitor'
            item['recommended_summary'] = 'Khong co write action an toan nao ro rang; nen monitor hoac doc them context.'
            recommended_steps.append(self._build_customer_care_plan_step('monitor'))

        if not recommended_steps:
            item['status'] = 'skipped'
            item['skip_reason'] = 'no_safe_action'
            item['recommended_summary'] = 'Khong co action an toan nao duoc de xuat.'
            recommended_steps = [self._build_customer_care_plan_step('no_action', requires_human_review=False)]

        item['recommended_steps'] = recommended_steps
        return item

    def _build_customer_care_action_plan_data(self, env, normalized_payload):
        items = []
        if normalized_payload['conversation_ids']:
            conversations = env['page.fm.conversation'].sudo().browse(normalized_payload['conversation_ids']).exists()
            conversation_map = {conversation.id: conversation for conversation in conversations}
            metrics = self._build_conversation_business_metrics(env=env, conversation_ids=conversations.ids)
            total = len(normalized_payload['conversation_ids'])
            for conversation_id in normalized_payload['conversation_ids']:
                conversation = conversation_map.get(conversation_id)
                if not conversation:
                    items.append({
                        'conversation_id': conversation_id,
                        'status': 'skipped',
                        'skip_reason': 'not_found',
                        'recommended_summary': 'Conversation khong ton tai.',
                        'recommended_steps': [self._build_customer_care_plan_step('no_action', requires_human_review=False)],
                        'messages': [],
                    })
                    continue
                queue_row = self._build_customer_care_row(
                    conversation,
                    metrics.get(conversation.id, {}),
                    normalized_payload['sla_minutes'],
                    normalized_payload['urgent_minutes'],
                )
                items.append(self._build_customer_care_action_plan_item(env, conversation, queue_row, normalized_payload))
            return {
                'policy': normalized_payload['policy'],
                'sla_minutes': normalized_payload['sla_minutes'],
                'count': len(items),
                'total': total,
                'items': items,
            }

        queue_rows = self._collect_customer_care_queue_rows(
            env=env,
            sla_minutes=normalized_payload['sla_minutes'],
            urgent_minutes=normalized_payload['urgent_minutes'],
            assignee_user_id=normalized_payload['filters'].get('assignee_user_id'),
            owner_id=normalized_payload['filters'].get('owner_id'),
            page_id=normalized_payload['filters'].get('page_id'),
            platform=normalized_payload['filters'].get('platform'),
            conversation_id=normalized_payload['filters'].get('conversation_id'),
            tag_code=normalized_payload['filters'].get('tag_code'),
        )
        total = len(queue_rows)
        page_rows = queue_rows[normalized_payload['offset']:normalized_payload['offset'] + normalized_payload['limit']]
        for queue_row in page_rows:
            items.append(self._build_customer_care_action_plan_item(
                env,
                queue_row['conversation'],
                queue_row,
                normalized_payload,
            ))
        return {
            'policy': normalized_payload['policy'],
            'sla_minutes': normalized_payload['sla_minutes'],
            'count': len(items),
            'total': total,
            'items': items,
        }

    def _run_mcp_customer_care_action_plan(self, payload=None, env=None):
        env = self._get_env(env)
        try:
            normalized_payload = self._normalize_mcp_customer_care_action_plan_payload(payload=payload, env=env)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        return self._build_customer_care_action_plan_data(env, normalized_payload)

    def _normalize_mcp_customer_care_auto_run_payload(self, payload=None, env=None, mode='manual_api'):
        env = self._get_mcp_write_env(env)
        payload = self._get_v3_json_payload(payload=payload)
        allowed_fields = {
            'filters',
            'conversation_ids',
            'policy',
            'sla_minutes',
            'urgent_minutes',
            'batch_limit',
            'dry_run',
            'execute_followups',
            'execute_notes',
            'execute_triage',
            'dedupe_existing_open_activity',
            'set_require_processing',
            'include_messages',
            'message_limit',
            'request_id',
            'agent_name',
            'model_name',
            'reason',
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported customer-care auto-run fields: %s" % ', '.join(unknown_fields))

        metadata = self._normalize_mcp_order_metadata(payload)
        if not metadata.get('reason'):
            raise ValueError("reason is required")

        auto_config = self._get_customer_care_auto_run_config(env=env)
        threshold_config = self._get_customer_care_threshold_config(
            env=env,
            request_sla_minutes=payload.get('sla_minutes'),
            request_urgent_minutes=payload.get('urgent_minutes'),
        )

        conversation_ids = payload.get('conversation_ids')
        cleaned_ids = []
        if conversation_ids not in (None, False):
            if not isinstance(conversation_ids, list):
                raise ValueError("conversation_ids must be a list")
            if len(conversation_ids) > 100:
                raise ValueError("conversation_ids cannot contain more than 100 items")
            seen_ids = set()
            for index, value in enumerate(conversation_ids):
                conversation_id = self._as_int(value, 'conversation_ids[%s]' % index)
                if conversation_id in seen_ids:
                    continue
                seen_ids.add(conversation_id)
                cleaned_ids.append(conversation_id)

        filters = payload.get('filters') or {}
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")
        allowed_filter_fields = {'assignee_user_id', 'owner_id', 'page_id', 'platform', 'conversation_id', 'tag_code'}
        unknown_filter_fields = sorted(set(filters) - allowed_filter_fields)
        if unknown_filter_fields:
            raise ValueError("Unsupported filters fields: %s" % ', '.join(unknown_filter_fields))

        normalized_filters = {}
        for field_name in ('assignee_user_id', 'owner_id', 'page_id', 'conversation_id'):
            normalized_filters[field_name] = self._coerce_nullable_int(filters.get(field_name), field_name)
        for field_name in ('platform', 'tag_code'):
            value = filters.get(field_name)
            if value not in (None, False):
                if not isinstance(value, str):
                    raise ValueError("filters.%s must be a string" % field_name)
                value = value.strip() or False
            else:
                value = False
            normalized_filters[field_name] = value

        policy_source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST if payload.get('policy') not in (None, '') else self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM
        if payload.get('policy') in (None, ''):
            policy, config_policy_source = self._get_customer_care_default_policy(env=env)
            if config_policy_source == self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_FALLBACK:
                policy_source = config_policy_source
        else:
            policy = payload.get('policy')
            if not isinstance(policy, str):
                raise ValueError("policy must be one of conservative,standard,urgent_only")
            policy = policy.strip()
        if policy not in self.MCP_ALLOWED_CUSTOMER_CARE_POLICIES:
            raise ValueError("policy must be one of conservative,standard,urgent_only")

        max_batch_limit = min(auto_config.get('max_batch_limit') or 100, 100)
        if payload.get('batch_limit') in (None, ''):
            batch_limit = min(auto_config['batch_limit'], max_batch_limit)
            batch_limit_source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM
        else:
            batch_limit = self._as_int(payload.get('batch_limit'), 'batch_limit')
            if batch_limit < 1:
                raise ValueError("batch_limit must be >= 1")
            batch_limit = min(batch_limit, max_batch_limit)
            batch_limit_source = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST

        include_messages = self._coerce_mcp_nullable_bool(payload.get('include_messages'), 'include_messages')
        dedupe_existing_open_activity = self._coerce_mcp_nullable_bool(
            payload.get('dedupe_existing_open_activity'),
            'dedupe_existing_open_activity',
        )
        set_require_processing = self._coerce_mcp_nullable_bool(
            payload.get('set_require_processing'),
            'set_require_processing',
        )

        toggle_values = {}
        toggle_sources = {}
        for field_name, config_key in (
            ('dry_run', 'dry_run_default'),
            ('execute_followups', 'execute_followups'),
            ('execute_notes', 'execute_notes'),
            ('execute_triage', 'execute_triage'),
        ):
            if payload.get(field_name) in (None, ''):
                toggle_values[field_name] = bool(auto_config[config_key])
                toggle_sources[field_name] = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_SYSTEM
            else:
                parsed_value = self._coerce_mcp_nullable_bool(payload.get(field_name), field_name)
                toggle_values[field_name] = bool(parsed_value)
                toggle_sources[field_name] = self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST

        normalized = dict(
            metadata,
            mode=mode or 'manual_api',
            filters=normalized_filters,
            conversation_ids=cleaned_ids,
            policy=policy,
            policy_source=policy_source,
            sla_minutes=threshold_config['sla_minutes'],
            urgent_minutes=threshold_config['urgent_minutes'],
            threshold_source=threshold_config.get('source'),
            batch_limit=batch_limit,
            batch_limit_source=batch_limit_source,
            dry_run=toggle_values['dry_run'],
            dry_run_source=toggle_sources['dry_run'],
            execute_followups=toggle_values['execute_followups'],
            execute_followups_source=toggle_sources['execute_followups'],
            execute_notes=toggle_values['execute_notes'],
            execute_notes_source=toggle_sources['execute_notes'],
            execute_triage=toggle_values['execute_triage'],
            execute_triage_source=toggle_sources['execute_triage'],
            dedupe_existing_open_activity=True if dedupe_existing_open_activity is None else dedupe_existing_open_activity,
            set_require_processing=True if set_require_processing is None else set_require_processing,
            include_messages=bool(include_messages) if include_messages is not None else False,
            message_limit=self._normalize_customer_care_message_limit(payload.get('message_limit'), default_limit=5, max_limit=20),
            auto_run_exclude_internal=bool(auto_config['exclude_internal']),
        )
        return normalized

    def _build_customer_care_auto_run_plan_payload(self, normalized_payload):
        selected_conversation_ids = normalized_payload['conversation_ids'][:normalized_payload['batch_limit']]
        return {
            'conversation_ids': selected_conversation_ids,
            'filters': dict(normalized_payload.get('filters') or {}),
            'sla_minutes': normalized_payload['sla_minutes'],
            'urgent_minutes': normalized_payload['urgent_minutes'],
            'limit': normalized_payload['batch_limit'],
            'offset': 0,
            'include_messages': normalized_payload.get('include_messages'),
            'message_limit': normalized_payload.get('message_limit'),
            'include_existing_activity_check': bool(normalized_payload.get('dedupe_existing_open_activity')),
            'policy': normalized_payload['policy'],
            'default_deadline_date': False,
            'templates': {},
        }

    def _build_customer_care_auto_run_activity_type(self, env, activity_recommendation):
        activity_recommendation = activity_recommendation or {}
        code = activity_recommendation.get('activity_type_code') or self.MCP_ACTIVITY_TYPE_NONE
        xmlid = activity_recommendation.get('activity_type_xmlid')
        if code == self.MCP_ACTIVITY_TYPE_NONE or not xmlid:
            return {
                'code': code,
                'xmlid': xmlid,
                'name': None,
            }
        try:
            record = env.ref(xmlid)
        except Exception:
            return {
                'code': code,
                'xmlid': xmlid,
                'name': None,
            }
        return {
            'id': record.id,
            'code': code,
            'xmlid': xmlid,
            'name': record.name,
        }

    def _build_customer_care_auto_run_item(self, env, plan_item, normalized_payload):
        conversation_id = plan_item.get('conversation_id')
        item = {
            'conversation_id': conversation_id,
            'status': 'no_action',
            'care_priority': plan_item.get('care_priority'),
            'care_reason': plan_item.get('care_reason'),
            'waiting_minutes': plan_item.get('waiting_minutes'),
            'planned_actions': [],
            'executed_actions': [],
            'activity_id': None,
            'note_log_id': None,
            'triage_log_id': None,
            'triage_preset': None,
            'activity_type': self._build_customer_care_auto_run_activity_type(env, plan_item.get('activity_recommendation') or {}),
            'deadline_date': (plan_item.get('activity_recommendation') or {}).get('recommended_deadline'),
            'skip_reason': plan_item.get('skip_reason'),
            'error': None,
        }
        if plan_item.get('status') == 'failed':
            item['status'] = 'failed'
            item['error'] = plan_item.get('error') or {'code': 'unexpected_error', 'message': 'Action plan item failed'}
            return item

        steps = {step.get('type'): step for step in (plan_item.get('recommended_steps') or [])}
        reviewed_step = steps.get('apply_reviewed_actions')
        reviewed_item = (((reviewed_step or {}).get('payload_template') or {}).get('items') or [{}])[0] if reviewed_step else {}
        disabled_reasons = []

        if steps.get('create_followup'):
            if normalized_payload.get('execute_followups'):
                item['planned_actions'].append('create_followup')
            else:
                disabled_reasons.append(
                    'action_disabled_by_request'
                    if normalized_payload.get('execute_followups_source') == self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST
                    else 'action_disabled_by_config'
                )

        if reviewed_step and reviewed_item.get('note_text'):
            if normalized_payload.get('execute_notes'):
                item['planned_actions'].append('create_internal_note')
            else:
                disabled_reasons.append(
                    'action_disabled_by_request'
                    if normalized_payload.get('execute_notes_source') == self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST
                    else 'action_disabled_by_config'
                )

        triage_preset = reviewed_item.get('triage_preset')
        if reviewed_step and triage_preset and triage_preset != 'note_only':
            if normalized_payload.get('execute_triage'):
                item['planned_actions'].append('apply_triage_preset')
                item['triage_preset'] = triage_preset
            else:
                disabled_reasons.append(
                    'action_disabled_by_request'
                    if normalized_payload.get('execute_triage_source') == self.MCP_CUSTOMER_CARE_CONFIG_SOURCE_REQUEST
                    else 'action_disabled_by_config'
                )
        elif triage_preset:
            item['triage_preset'] = triage_preset

        if item['planned_actions']:
            item['status'] = 'would_execute' if normalized_payload.get('dry_run') else 'executed'
            return item

        if (steps.get('manual_assignment_review') or {}).get('type') == 'manual_assignment_review':
            item['status'] = 'skipped'
            item['skip_reason'] = 'no_assigned_user'
            return item
        if plan_item.get('existing_open_activity'):
            item['status'] = 'skipped'
            item['skip_reason'] = 'existing_open_activity'
            return item
        if item.get('skip_reason'):
            item['status'] = 'skipped'
        elif disabled_reasons:
            item['status'] = 'skipped'
            item['skip_reason'] = disabled_reasons[0]
        elif plan_item.get('status') in ('manual_review', 'monitor', 'read_more'):
            item['status'] = 'no_action'
            item['skip_reason'] = 'no_safe_action'
        else:
            item['status'] = 'skipped'
            item['skip_reason'] = 'no_safe_action'
        return item

    def _execute_customer_care_auto_run_item(self, env, conversation, queue_row, plan_item, normalized_payload, metrics):
        item = self._build_customer_care_auto_run_item(env, plan_item, normalized_payload)
        if item['status'] in ('failed', 'skipped', 'no_action') and not item['planned_actions']:
            return item
        if normalized_payload.get('dry_run'):
            item['status'] = 'would_execute'
            return item

        steps = {step.get('type'): step for step in (plan_item.get('recommended_steps') or [])}
        followup_step = steps.get('create_followup')
        reviewed_step = steps.get('apply_reviewed_actions')
        first_error = None
        last_skip_reason = item.get('skip_reason')

        if 'create_followup' in item['planned_actions'] and followup_step:
            followup_payload = dict((followup_step.get('payload_template') or {}))
            followup_payload.update({
                'request_id': normalized_payload['request_id'],
                'agent_name': normalized_payload['agent_name'],
                'model_name': normalized_payload.get('model_name') or False,
                'reason': ((followup_step.get('payload_template') or {}).get('reason') or normalized_payload.get('reason') or False),
                'dry_run': False,
                'dedupe_existing_open_activity': normalized_payload.get('dedupe_existing_open_activity'),
                'set_require_processing': normalized_payload.get('set_require_processing'),
                'sla_minutes': normalized_payload.get('sla_minutes'),
                'urgent_minutes': normalized_payload.get('urgent_minutes'),
            })
            followup_result = self._process_customer_care_followup_item(
                env,
                conversation,
                queue_row,
                followup_payload,
            )
            if followup_result.get('action') == 'created':
                item['executed_actions'].append('create_followup')
                item['activity_id'] = followup_result.get('activity_id')
                item['activity_type'] = followup_result.get('activity_type') or item.get('activity_type')
                item['deadline_date'] = followup_result.get('deadline_date') or item.get('deadline_date')
            elif followup_result.get('action') == 'skipped':
                last_skip_reason = followup_result.get('skip_reason') or last_skip_reason
            elif followup_result.get('action') == 'failed':
                first_error = followup_result.get('error') or first_error

        if reviewed_step and ('create_internal_note' in item['planned_actions'] or 'apply_triage_preset' in item['planned_actions']):
            reviewed_payload_template = (reviewed_step.get('payload_template') or {})
            reviewed_item = dict(((reviewed_payload_template.get('items') or [{}])[0]))
            if 'create_internal_note' not in item['planned_actions']:
                reviewed_item['note_text'] = False
            if 'apply_triage_preset' not in item['planned_actions']:
                reviewed_item['triage_preset'] = False
            reviewed_item['item_index'] = 0
            reviewed_request_payload = {
                'request_id': normalized_payload['request_id'],
                'agent_name': normalized_payload['agent_name'],
                'model_name': normalized_payload.get('model_name') or False,
                'reason': normalized_payload.get('reason') or False,
                'default_note_template': False,
                'dry_run': False,
            }
            reviewed_result = self._process_customer_care_reviewed_action_item(
                env,
                reviewed_item,
                {conversation.id: conversation},
                metrics,
                reviewed_request_payload,
                threshold_config={
                    'sla_minutes': normalized_payload['sla_minutes'],
                    'urgent_minutes': normalized_payload['urgent_minutes'],
                },
            )
            action_name = reviewed_result.get('action')
            if action_name in ('note_created', 'note_created_and_triage_updated', 'note_created_triage_skipped'):
                item['executed_actions'].append('create_internal_note')
                item['note_log_id'] = reviewed_result.get('note_log_id')
            if action_name in ('triage_updated', 'note_created_and_triage_updated'):
                item['executed_actions'].append('apply_triage_preset')
                item['triage_log_id'] = reviewed_result.get('triage_log_id')
                item['triage_preset'] = reviewed_result.get('triage_preset') or item.get('triage_preset')
            if action_name == 'skipped':
                last_skip_reason = reviewed_result.get('skip_reason') or last_skip_reason
            if action_name == 'note_created_triage_skipped':
                last_skip_reason = reviewed_result.get('skip_reason') or last_skip_reason
            if action_name == 'failed':
                first_error = reviewed_result.get('error') or first_error

        if first_error:
            item['status'] = 'failed'
            item['error'] = first_error
            item['skip_reason'] = last_skip_reason
            return item
        if item['executed_actions']:
            item['status'] = 'executed'
            item['skip_reason'] = last_skip_reason if not item['executed_actions'] else None
            return item
        item['status'] = 'skipped'
        item['skip_reason'] = last_skip_reason or 'no_change_needed'
        return item

    def _run_mcp_customer_care_auto_run(self, payload=None, env=None, mode='manual_api'):
        env = self._get_mcp_write_env(env)
        started_at = datetime.utcnow()
        try:
            normalized_payload = self._normalize_mcp_customer_care_auto_run_payload(payload=payload, env=env, mode=mode)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_auto_run_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_auto_run_replayed_response_data(existing_log)

        plan_payload = self._build_customer_care_auto_run_plan_payload(normalized_payload)
        plan_data = self._build_customer_care_action_plan_data(env, plan_payload)
        items = []
        actionable_count = 0
        followup_created_count = 0
        note_created_count = 0
        triage_updated_count = 0
        skipped_count = 0
        failed_count = 0
        metrics = {}
        conversation_map = {}

        if plan_payload['conversation_ids']:
            conversations = env['page.fm.conversation'].sudo().browse(plan_payload['conversation_ids']).exists()
            conversation_map = {conversation.id: conversation for conversation in conversations}
            metrics = self._build_conversation_business_metrics(env=env, conversation_ids=conversations.ids)
        else:
            queue_rows = self._collect_customer_care_queue_rows(
                env=env,
                sla_minutes=normalized_payload['sla_minutes'],
                urgent_minutes=normalized_payload['urgent_minutes'],
                assignee_user_id=normalized_payload['filters'].get('assignee_user_id'),
                owner_id=normalized_payload['filters'].get('owner_id'),
                page_id=normalized_payload['filters'].get('page_id'),
                platform=normalized_payload['filters'].get('platform'),
                conversation_id=normalized_payload['filters'].get('conversation_id'),
                tag_code=normalized_payload['filters'].get('tag_code'),
            )
            conversation_map = {
                row['conversation'].id: row['conversation']
                for row in queue_rows[:normalized_payload['batch_limit']]
            }
            metrics = {
                row['conversation'].id: row['metric']
                for row in queue_rows[:normalized_payload['batch_limit']]
            }

        try:
            for plan_item in plan_data.get('items') or []:
                conversation_id = plan_item.get('conversation_id')
                conversation = conversation_map.get(conversation_id)
                if not conversation:
                    item = self._build_customer_care_auto_run_item(env, plan_item, normalized_payload)
                    if item['status'] == 'failed':
                        failed_count += 1
                    else:
                        skipped_count += 1
                    items.append(item)
                    continue

                queue_row = self._build_customer_care_row(
                    conversation,
                    metrics.get(conversation.id, {}),
                    normalized_payload['sla_minutes'],
                    normalized_payload['urgent_minutes'],
                )
                if normalized_payload.get('auto_run_exclude_internal') and bool(getattr(conversation, 'is_internal_conversation', False)):
                    item = self._build_customer_care_auto_run_item(env, dict(plan_item, skip_reason='internal_conversation', status='skipped'), normalized_payload)
                    item['status'] = 'skipped'
                    item['skip_reason'] = 'internal_conversation'
                    items.append(item)
                    skipped_count += 1
                    continue
                if getattr(conversation, 'status_state', None) == 'done':
                    item = self._build_customer_care_auto_run_item(env, dict(plan_item, skip_reason='already_done', status='skipped'), normalized_payload)
                    item['status'] = 'skipped'
                    item['skip_reason'] = 'already_done'
                    items.append(item)
                    skipped_count += 1
                    continue

                item = self._execute_customer_care_auto_run_item(
                    env,
                    conversation,
                    queue_row,
                    plan_item,
                    normalized_payload,
                    metrics,
                )
                if item['planned_actions']:
                    actionable_count += 1
                if 'create_followup' in item.get('executed_actions', []):
                    followup_created_count += 1
                if 'create_internal_note' in item.get('executed_actions', []):
                    note_created_count += 1
                if 'apply_triage_preset' in item.get('executed_actions', []):
                    triage_updated_count += 1
                if item['status'] in ('skipped', 'no_action'):
                    skipped_count += 1
                if item['status'] == 'failed':
                    failed_count += 1
                items.append(item)

            response_data = {
                'request_id': normalized_payload['request_id'],
                'dry_run': bool(normalized_payload.get('dry_run')),
                'policy': normalized_payload['policy'],
                'sla_minutes': normalized_payload['sla_minutes'],
                'urgent_minutes': normalized_payload['urgent_minutes'],
                'batch_limit': normalized_payload['batch_limit'],
                'source': {
                    'mode': 'conversation_ids' if normalized_payload['conversation_ids'] else 'queue',
                    'filters': normalized_payload.get('filters') or {},
                },
                'summary': {
                    'evaluated_count': len(items),
                    'actionable_count': actionable_count,
                    'followup_created_count': 0 if normalized_payload.get('dry_run') else followup_created_count,
                    'note_created_count': 0 if normalized_payload.get('dry_run') else note_created_count,
                    'triage_updated_count': 0 if normalized_payload.get('dry_run') else triage_updated_count,
                    'skipped_count': skipped_count,
                    'failed_count': failed_count,
                },
                'items': items,
                'idempotent_replay': False,
            }
            finished_at = datetime.utcnow()
            duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
            log_record = self._create_mcp_auto_run_log(
                env=env,
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data=response_data,
                summary=response_data['summary'],
                items=items,
                status='success',
                mode=mode,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
            response_data['run_id'] = log_record.id
            log_record.sudo().write({
                'response_snapshot_json': self._dump_json_text(response_data),
                'summary_json': self._dump_json_text(response_data['summary']),
                'item_results_json': self._dump_json_text(items),
            })
            return response_data
        except McpHttpError:
            raise
        except Exception as exc:
            _logger.exception("Customer care auto-run request failed")
            finished_at = datetime.utcnow()
            duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
            self._create_mcp_auto_run_log(
                env=env,
                normalized_payload=normalized_payload,
                payload_fingerprint=payload_fingerprint,
                response_data={},
                summary={},
                items=[],
                status='failed',
                mode=mode,
                error_code='unexpected_error',
                error_message=str(exc),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
            raise

    def _run_customer_care_auto_run_cron(self, env=None, now_dt=None):
        env = self._get_mcp_write_env(env)
        auto_config = self._get_customer_care_auto_run_config(env=env)
        if not auto_config['enabled'] or not auto_config['cron_enabled']:
            return {'status': 'noop', 'reason': 'disabled'}
        if auto_config['working_hours_only'] and not self._is_datetime_within_mcp_working_hours(now_dt, env=env):
            return {'status': 'noop', 'reason': 'outside_working_hours'}
        run_dt = now_dt or datetime.now(self._get_mcp_working_hours_timezone(env=env))
        request_id = 'oclaw-auto-cron-%s' % run_dt.strftime('%Y%m%d-%H%M')
        payload = {
            'filters': {},
            'policy': self._get_customer_care_default_policy(env=env)[0],
            'dry_run': auto_config['dry_run_default'],
            'batch_limit': auto_config['batch_limit'],
            'execute_followups': auto_config['execute_followups'],
            'execute_notes': auto_config['execute_notes'],
            'execute_triage': auto_config['execute_triage'],
            'dedupe_existing_open_activity': True,
            'set_require_processing': True,
            'include_messages': False,
            'message_limit': 5,
            'request_id': request_id,
            'agent_name': 'OpenClawCron',
            'model_name': False,
            'reason': 'scheduled_customer_care_auto_run',
        }
        return self._run_mcp_customer_care_auto_run(payload=payload, env=env, mode='cron')

    def _get_mcp_customer_care_auto_run_report(self, run_id, env=None):
        env = self._get_env(env)
        run = env[self.MCP_AUTO_RUN_LOG_MODEL].sudo().browse(run_id)
        if not run.exists():
            raise McpHttpError(404, 'not_found', 'Auto-run log not found')
        try:
            response_snapshot = json.loads(run.response_snapshot_json) if run.response_snapshot_json else {}
        except Exception:
            response_snapshot = {}
        try:
            summary = json.loads(run.summary_json) if run.summary_json else {}
        except Exception:
            summary = {}
        try:
            items = json.loads(run.item_results_json) if run.item_results_json else []
        except Exception:
            items = []
        return {
            'run_id': run.id,
            'request_id': run.request_id,
            'status': run.status,
            'mode': run.mode,
            'dry_run': bool(run.dry_run),
            'policy': run.policy,
            'summary': response_snapshot.get('summary') or summary,
            'items': response_snapshot.get('items') or items,
            'started_at': self._serialize_value(run.started_at),
            'finished_at': self._serialize_value(run.finished_at),
            'duration_ms': run.duration_ms or 0,
        }

    def _get_mcp_customer_care_auto_run_run_list(self, env=None, params=None):
        env = self._get_env(env)
        params = params or {}
        max_limit = min(self._get_mcp_global_guard_config(env=env)['max_batch_limit'], 100)
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=20,
            max_limit=max_limit,
        )
        domain = []
        status_value = params.get('status')
        if status_value:
            statuses = [item.strip() for item in str(status_value).split(',') if item.strip()]
            allowed_statuses = {'success', 'replayed', 'conflict', 'failed'}
            if any(item not in allowed_statuses for item in statuses):
                raise ValueError("status must only contain success,replayed,conflict,failed")
            domain.append(('status', 'in', statuses))
        dry_run_value = params.get('dry_run')
        if dry_run_value not in (None, ''):
            parsed_dry_run = self._as_bool(dry_run_value, 'dry_run')
            if parsed_dry_run is None:
                raise ValueError("dry_run must be one of 1,0,true,false")
            domain.append(('dry_run', '=', bool(parsed_dry_run)))
        mode_value = params.get('mode')
        if mode_value not in (None, ''):
            mode_value = str(mode_value).strip()
            if mode_value not in ('manual_api', 'cron'):
                raise ValueError("mode must be one of manual_api,cron")
            domain.append(('mode', '=', mode_value))
        if params.get('request_id'):
            domain.append(('request_id', '=', str(params.get('request_id')).strip()))
        if params.get('agent_name'):
            domain.append(('agent_name', 'ilike', str(params.get('agent_name')).strip()))

        date_window = self._parse_datetime_window(
            env=env,
            params=params,
            date_value=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
        )
        if date_window.get('dt_from_utc'):
            domain.append(('started_at', '>=', fields.Datetime.to_string(date_window['dt_from_utc'])))
        if date_window.get('dt_to_utc'):
            domain.append(('started_at', '<=', fields.Datetime.to_string(date_window['dt_to_utc'])))

        RunLog = env[self.MCP_AUTO_RUN_LOG_MODEL].sudo()
        total = RunLog.search_count(domain)
        runs = RunLog.search(domain, order='id desc', limit=limit, offset=offset)
        items = []
        for run in runs:
            try:
                summary = json.loads(run.summary_json) if run.summary_json else {}
            except Exception:
                summary = {}
            items.append({
                'run_id': run.id,
                'request_id': run.request_id,
                'status': run.status,
                'mode': run.mode,
                'dry_run': bool(run.dry_run),
                'policy': run.policy,
                'summary': summary,
                'started_at': self._serialize_value(run.started_at),
                'finished_at': self._serialize_value(run.finished_at),
                'duration_ms': run.duration_ms or 0,
            })
        return self._mcp_list_payload(items, total)

    def _normalize_customer_search_query(self, query):
        original_query = (query or '').strip()
        normalized_query = original_query
        lowered = normalized_query.lower()
        for prefix in ('anh ', 'chi ', 'co ', 'chu ', 'bac ', 'em ', 'ban ', 'cong ty ', 'cty '):
            if lowered.startswith(prefix):
                normalized_query = normalized_query[len(prefix):].strip()
                break
        return original_query, normalized_query

    def _normalize_phone_for_match(self, value):
        cleaned = ''.join(ch for ch in str(value or '') if ch.isdigit())
        if cleaned.startswith('84') and len(cleaned) >= 9:
            return '0' + cleaned[2:]
        return cleaned

    def _build_customer_disambiguation_label(self, partner):
        parts = [partner.display_name or partner.name]
        company_name = getattr(partner, 'commercial_company_name', None) or getattr(getattr(partner, 'parent_id', None), 'name', None)
        phone = partner.phone or partner.mobile
        address = partner.contact_address or partner.city or partner.street
        if company_name and company_name not in parts:
            parts.append(company_name)
        if phone:
            parts.append(phone)
        if address:
            parts.append(address)
        return ' - '.join([part for part in parts if part])

    def _score_customer_candidate(self, partner, original_query=None, normalized_query=None, phone=None, email=None, company=None, vat=None, linked_partner_id=None):
        matched_fields = []
        confidence = 0.0
        normalized_phone = self._normalize_phone_for_match(phone)
        partner_phone_values = [
            self._normalize_phone_for_match(partner.phone),
            self._normalize_phone_for_match(partner.mobile),
        ]
        if normalized_phone and normalized_phone in partner_phone_values:
            confidence = max(confidence, 1.0)
            matched_fields.append('phone')
        if email and (partner.email or '').strip().lower() == str(email).strip().lower():
            confidence = max(confidence, 0.98)
            matched_fields.append('email')
        if linked_partner_id and partner.id == linked_partner_id:
            confidence = max(confidence, 0.95)
            matched_fields.append('conversation_link')
        if vat and (partner.vat or '').strip().lower() == str(vat).strip().lower():
            confidence = max(confidence, 0.9)
            matched_fields.append('vat')
        normalized_query_lc = (normalized_query or '').strip().lower()
        original_query_lc = (original_query or '').strip().lower()
        partner_name = (partner.name or '').strip().lower()
        display_name = (partner.display_name or '').strip().lower()
        company_name = (getattr(partner, 'commercial_company_name', None) or getattr(getattr(partner, 'parent_id', None), 'name', None) or '').strip().lower()
        if normalized_query_lc:
            if normalized_query_lc == partner_name or normalized_query_lc == display_name:
                confidence = max(confidence, 0.9)
                matched_fields.append('name')
            elif normalized_query_lc in partner_name or normalized_query_lc in display_name:
                confidence = max(confidence, 0.82 if len(normalized_query_lc) >= 4 else 0.75)
                matched_fields.append('name')
            elif company_name and normalized_query_lc in company_name:
                confidence = max(confidence, 0.72)
                matched_fields.append('company')
        if company and company_name and str(company).strip().lower() in company_name:
            confidence = max(confidence, 0.8)
            matched_fields.append('company')
        if original_query_lc and original_query_lc == partner_name and 'name' not in matched_fields:
            confidence = max(confidence, 0.9)
            matched_fields.append('name')
        return confidence, matched_fields

    def _serialize_customer_candidate(self, partner, matched_fields, confidence):
        company_name = getattr(partner, 'commercial_company_name', None) or getattr(getattr(partner, 'parent_id', None), 'name', None)
        return {
            'id': partner.id,
            'display_name': partner.display_name,
            'name': partner.name,
            'phone': partner.phone,
            'mobile': partner.mobile,
            'email': partner.email,
            'company_name': company_name,
            'address': partner.contact_address or partner.city or partner.street or None,
            'matched_fields': matched_fields,
            'confidence': round(confidence, 2),
            'disambiguation_label': self._build_customer_disambiguation_label(partner),
        }

    def _search_customer_candidates(self, env=None, q=None, phone=None, mobile=None, email=None, company=None, vat=None, conversation_id=None, limit=10, offset=0):
        env = self._get_env(env)
        original_query, normalized_query = self._normalize_customer_search_query(q)
        linked_partner_id = False
        if conversation_id:
            conversation = self._get_mcp_conversation_record(conversation_id, env=env)
            linked_partner_id = getattr(getattr(conversation, 'partner_id', None), 'id', False)
        search_terms = [term for term in [normalized_query, phone, mobile, email, company, vat] if term]
        domain = []
        if search_terms:
            term = search_terms[0]
            domain = ['|', '|', '|', ('name', 'ilike', term), ('phone', 'ilike', term), ('mobile', 'ilike', term), ('email', 'ilike', term)]
        partners = env['res.partner'].sudo().search(domain, limit=max(limit + offset + 40, 50), order='id desc')
        scored = []
        for partner in partners:
            confidence, matched_fields = self._score_customer_candidate(
                partner,
                original_query=original_query,
                normalized_query=normalized_query,
                phone=phone or mobile,
                email=email,
                company=company,
                vat=vat,
                linked_partner_id=linked_partner_id,
            )
            if confidence <= 0:
                continue
            scored.append((confidence, partner.id, partner, matched_fields))
        scored.sort(key=lambda item: (-item[0], -item[1], (item[2].display_name or item[2].name or '')))
        page = scored[offset:offset + limit]
        items = [self._serialize_customer_candidate(partner, matched_fields, confidence) for confidence, _pid, partner, matched_fields in page]
        status = 'not_found'
        if len(items) == 1 and (items[0]['confidence'] >= 0.9 or linked_partner_id == items[0]['id']):
            status = 'exact_match'
        elif items:
            status = 'multiple_matches' if len(items) > 1 else 'exact_match'
        prompt_suggestion = None
        if status == 'multiple_matches':
            labels = [item['disambiguation_label'] for item in items[:3]]
            prompt_suggestion = 'Toi tim thay %s ket qua. Anh/chi muon chon %s?' % (
                len(items),
                ' hay '.join(labels),
            )
        return {
            'query': original_query,
            'normalized_query': normalized_query or original_query,
            'status': status,
            'count': len(items),
            'items': items,
            'prompt_suggestion': prompt_suggestion,
            'linked_partner_id': linked_partner_id or None,
        }

    def _serialize_product_candidate(self, product, matched_fields, confidence):
        taxes = [{'id': tax.id, 'name': tax.name} for tax in product.taxes_id]
        currency = product.currency_id if getattr(product, 'currency_id', False) else product.company_id.currency_id
        return {
            'id': product.id,
            'template_id': product.product_tmpl_id.id,
            'name': product.name,
            'display_name': product.display_name,
            'default_code': product.default_code,
            'barcode': product.barcode,
            'category': {
                'id': product.categ_id.id,
                'name': product.categ_id.name,
            } if product.categ_id else None,
            'list_price': product.lst_price,
            'uom': {
                'id': product.uom_id.id,
                'name': product.uom_id.name,
            } if product.uom_id else None,
            'taxes': taxes,
            'currency': {
                'id': currency.id,
                'name': currency.name,
                'symbol': currency.symbol,
            } if currency else None,
            'active': bool(product.active),
            'sale_ok': bool(product.sale_ok),
            'matched_fields': matched_fields,
            'confidence': round(confidence, 2),
            'disambiguation_label': '%s - %s - %s' % (
                product.display_name,
                product.default_code or '-',
                ('{:,.0f}'.format(product.lst_price or 0)).replace(',', '.'),
            ),
        }

    def _get_recent_context_product_ids(self, env=None, conversation_id=None, customer_id=None, query=None):
        env = self._get_env(env)
        query_lc = (query or '').strip().lower()
        domain = []
        if conversation_id:
            domain.append(('order_id.conversation_id', '=', conversation_id))
        if customer_id:
            domain.append(('order_id.partner_id', '=', customer_id))
        if not domain:
            return set()
        lines = env['sale.order.line'].sudo().search(domain, order='create_date desc, id desc', limit=30)
        product_ids = set()
        for line in lines:
            product = line.product_id
            if not product:
                continue
            if not query_lc or query_lc in (product.display_name or '').lower() or query_lc in (product.default_code or '').lower():
                product_ids.add(product.id)
        return product_ids

    def _search_product_candidates(self, env=None, q=None, default_code=None, barcode=None, category_id=None, sale_ok=None, active=True, limit=10, offset=0, conversation_id=None, customer_id=None):
        env = self._get_env(env)
        query = (q or '').strip()
        normalized_query = query.strip().lower()
        domain = []
        if active is not None:
            domain.append(('active', '=', bool(active)))
        if sale_ok is not False:
            domain.append(('sale_ok', '=', True))
        if category_id:
            domain.append(('categ_id', '=', int(category_id)))
        search_term = default_code or barcode or query
        if search_term:
            domain.extend(['|', '|', ('name', 'ilike', search_term), ('default_code', 'ilike', search_term), ('barcode', 'ilike', search_term)])
        products = env['product.product'].sudo().search(domain, limit=max(limit + offset + 40, 50), order='id desc')
        recent_context_ids = self._get_recent_context_product_ids(
            env=env,
            conversation_id=conversation_id,
            customer_id=customer_id,
            query=query,
        )
        scored = []
        for product in products:
            matched_fields = []
            confidence = 0.0
            if default_code and (product.default_code or '').strip().lower() == str(default_code).strip().lower():
                confidence = max(confidence, 1.0)
                matched_fields.append('default_code')
            if barcode and (product.barcode or '').strip() == str(barcode).strip():
                confidence = max(confidence, 0.99)
                matched_fields.append('barcode')
            name_lc = (product.name or '').strip().lower()
            display_name_lc = (product.display_name or '').strip().lower()
            categ_name_lc = (product.categ_id.name or '').strip().lower() if product.categ_id else ''
            if normalized_query:
                if normalized_query == (product.default_code or '').strip().lower():
                    confidence = max(confidence, 1.0)
                    matched_fields.append('default_code')
                elif normalized_query == name_lc or normalized_query == display_name_lc:
                    confidence = max(confidence, 0.9)
                    matched_fields.append('name')
                elif normalized_query in name_lc or normalized_query in display_name_lc:
                    confidence = max(confidence, 0.82)
                    matched_fields.append('name')
                elif categ_name_lc and normalized_query in categ_name_lc:
                    confidence = max(confidence, 0.7)
                    matched_fields.append('category')
            if product.id in recent_context_ids:
                confidence = max(confidence, min(confidence + 0.08, 0.95) if confidence else 0.76)
                if 'recent_order_context' not in matched_fields:
                    matched_fields.append('recent_order_context')
            if confidence <= 0:
                continue
            scored.append((confidence, product.id, product, matched_fields))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2].display_name or item[2].name or ''))
        page = scored[offset:offset + limit]
        items = [self._serialize_product_candidate(product, matched_fields, confidence) for confidence, _pid, product, matched_fields in page]
        status = 'not_found'
        if len(items) == 1 and items[0]['confidence'] >= 0.9:
            status = 'exact_match'
        elif items:
            status = 'multiple_matches' if len(items) > 1 else 'exact_match'
        prompt_suggestion = None
        if status == 'multiple_matches':
            labels = [item['disambiguation_label'] for item in items[:3]]
            prompt_suggestion = 'Toi tim thay %s san pham. Anh/chi muon chon %s?' % (
                len(items),
                ' hay '.join(labels),
            )
        return {
            'query': query,
            'normalized_query': normalized_query,
            'status': status,
            'count': len(items),
            'items': items,
            'prompt_suggestion': prompt_suggestion,
            'recent_context_ids': list(recent_context_ids),
        }

    def _build_mcp_order_domain(self, env=None, params=None):
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
                domain.append(('state', 'in', states))
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

    def _collect_order_related_maps(self, orders=None, metrics=None, env=None):
        env = self._get_env(env)
        orders = orders or env['sale.order']
        metrics = metrics or {}
        invoice_ids = []
        payment_ids = []
        for order in orders:
            metric = metrics.get(order.id, {})
            if metric.get('latest_deposit_invoice_id'):
                invoice_ids.append(metric['latest_deposit_invoice_id'])
            if metric.get('latest_deposit_payment_id'):
                payment_ids.append(metric['latest_deposit_payment_id'])
        invoice_map = {}
        payment_map = {}
        if invoice_ids:
            invoice_map = {
                invoice.id: invoice
                for invoice in env['account.move'].sudo().browse(invoice_ids).exists()
            }
        if payment_ids:
            payment_map = {
                payment.id: payment
                for payment in env['account.payment'].sudo().browse(payment_ids).exists()
            }
        return invoice_map, payment_map

    def _get_order_conversation_id_map(self, order_ids=None, env=None):
        env = self._get_env(env)
        order_ids = [int(order_id) for order_id in (order_ids or []) if order_id]
        if not order_ids:
            return {}
        env.cr.execute(
            "SELECT id, conversation_id FROM sale_order WHERE id IN %s",
            [tuple(order_ids)],
        )
        return {
            row[0]: row[1]
            for row in env.cr.fetchall()
            if row[1]
        }

    def _normalize_order_records(self, orders=None, metrics=None, include_lines=False, env=None):
        env = self._get_env(env)
        orders = orders or env['sale.order']
        metrics = metrics or {}
        invoice_map, payment_map = self._collect_order_related_maps(orders=orders, metrics=metrics, env=env)
        conversation_id_map = self._get_order_conversation_id_map(order_ids=orders.ids, env=env)
        conversation_map = {}
        if conversation_id_map and 'page.fm.conversation' in env.registry.models:
            conversation_map = {
                conversation.id: conversation
                for conversation in env['page.fm.conversation'].sudo().browse(list(set(conversation_id_map.values()))).exists()
            }
        normalized_items = []
        for order in orders:
            metric = metrics.get(order.id, {})
            conversation = conversation_map.get(conversation_id_map.get(order.id))
            raw_item = {
                'id': order.id,
                'name': order.name,
                'order_number': getattr(order, 'order_number', None),
                'client_order_ref': order.client_order_ref,
                'date': self._serialize_value(getattr(order, 'date', None)),
                'date_order': self._serialize_value(getattr(order, 'date_order', None)),
                'create_date': self._serialize_value(getattr(order, 'create_date', None)),
                'amount_total': order.amount_total,
                'amount_untaxed': order.amount_untaxed,
                'amount_tax': order.amount_tax,
                'deposit_invoice_count': metric.get('deposit_invoice_count', 0),
                'deposit_payment_count': metric.get('deposit_payment_count', 0),
                'production_deadline': self._serialize_value(getattr(order, 'production_deadline', None)),
                'delivery_address': getattr(order, 'delivery_address', None),
                'installation_address': getattr(order, 'installation_address', None),
                'note': order.note,
                'conversation': {
                    'id': conversation.id,
                    'conversation_fm_id': getattr(conversation, 'conversation_fm_id', None),
                    'customer_name': getattr(conversation, 'customer_name_clean', None) or getattr(conversation, 'customer_name_fm', None) or getattr(conversation, 'name', None),
                } if conversation else None,
            }
            normalized_items.append(normalize_order_item(
                raw_item,
                order=order,
                conversation=conversation,
                include_lines=include_lines,
                latest_deposit_invoice=invoice_map.get(metric.get('latest_deposit_invoice_id')),
                latest_deposit_payment=payment_map.get(metric.get('latest_deposit_payment_id')),
            ))
        return normalized_items

    def _get_mcp_orders_payload(self, env=None, include_lines=False, default_order=None, **params):
        env = self._get_env(env)
        Order = env['sale.order'].sudo()
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=20,
            max_limit=100,
        )
        domain, _applied_filters = self._build_mcp_order_domain(env=env, params=params)

        deposit_event = params.get('deposit_event')
        if deposit_event not in (None, '', 'invoice_created', 'payment_received'):
            raise ValueError("deposit_event must be one of invoice_created,payment_received")

        has_deposit_invoice = self._as_bool(params.get('has_deposit_invoice'), 'has_deposit_invoice')

        base_order = params.get('order') or default_order or 'date desc, id desc'
        all_orders = Order.search(domain)
        metrics, _deposit_window = self._build_order_deposit_metrics(env=env, orders=all_orders, params=params)

        filtered_orders = []
        for order in all_orders:
            metric = metrics.get(order.id, {})
            if has_deposit_invoice is not None and bool(metric.get('deposit_invoice_count')) != has_deposit_invoice:
                continue
            if deposit_event == 'invoice_created' and not metric.get('_matching_invoice_sort_dt'):
                continue
            if deposit_event == 'payment_received' and not metric.get('_matching_payment_sort_dt'):
                continue
            filtered_orders.append(order)

        if deposit_event == 'invoice_created':
            filtered_orders.sort(
                key=lambda record: (metrics[record.id].get('_matching_invoice_sort_dt') or datetime.min, record.id),
                reverse=True,
            )
            total = len(filtered_orders)
            page_orders = Order.browse([order.id for order in filtered_orders[offset:offset + limit]]).exists()
        elif deposit_event == 'payment_received':
            filtered_orders.sort(
                key=lambda record: (metrics[record.id].get('_matching_payment_sort_dt') or datetime.min, record.id),
                reverse=True,
            )
            total = len(filtered_orders)
            page_orders = Order.browse([order.id for order in filtered_orders[offset:offset + limit]]).exists()
        elif has_deposit_invoice is not None:
            total = len(filtered_orders)
            page_orders = Order.search([('id', 'in', [order.id for order in filtered_orders])], limit=limit, offset=offset, order=base_order)
        else:
            total = len(all_orders)
            page_orders = Order.search(domain, limit=limit, offset=offset, order=base_order)

        return self._mcp_list_payload(
            self._normalize_order_records(
                orders=page_orders,
                metrics=metrics,
                include_lines=include_lines,
                env=env,
            ),
            total,
        )

    def _get_mcp_order_payload(self, order_id, env=None, include_lines=True):
        env = self._get_env(env)
        order = self._get_mcp_order_record(order_id, env=env)
        metrics, _deposit_window = self._build_order_deposit_metrics(env=env, orders=order, params={})
        items = self._normalize_order_records(
            orders=order,
            metrics=metrics,
            include_lines=include_lines,
            env=env,
        )
        return items[0] if items else None

    def _get_mcp_order_write_env(self, env=None):
        return self._get_v2_write_env(env)

    def _coerce_mcp_nullable_bool(self, value, field_name):
        if value in (None, ''):
            return None
        parsed = self._as_bool(value, field_name)
        if parsed is None:
            raise ValueError("%s must be one of 1,0,true,false" % field_name)
        return parsed

    def _normalize_mcp_order_metadata(self, payload):
        if 'request_id' not in payload or not isinstance(payload.get('request_id'), str) or not payload.get('request_id').strip():
            raise ValueError("request_id is required")
        if 'agent_name' not in payload or not isinstance(payload.get('agent_name'), str) or not payload.get('agent_name').strip():
            raise ValueError("agent_name is required")
        model_name = payload.get('model_name')
        if model_name not in (None, False):
            if not isinstance(model_name, str):
                raise ValueError("model_name must be a string")
            model_name = model_name.strip() or False
        reason = payload.get('reason')
        if reason not in (None, False):
            if not isinstance(reason, str):
                raise ValueError("reason must be a string")
            reason = reason.strip() or False
        else:
            reason = False
        return {
            'request_id': payload['request_id'].strip(),
            'agent_name': payload['agent_name'].strip(),
            'model_name': model_name or False,
            'reason': reason,
        }

    def _get_mcp_order_money_confirmation_config(self, env=None):
        env = self._get_mcp_order_write_env(env)
        required, _valid = self._get_mcp_config_bool(
            'dac_erp.mcp.order.money_change_confirmation_required',
            True,
            env=env,
        )
        field_text, _field_valid = self._get_mcp_config_text(
            'dac_erp.mcp.order.money_change_fields',
            'product_uom_qty,price_unit,discount,tax_id,deposit_amount,has_deposit,order_lines',
            env=env,
        )
        field_names = []
        for raw_field in str(field_text or '').split(','):
            field_name = raw_field.strip()
            if field_name and field_name not in field_names:
                field_names.append(field_name)
        if not field_names:
            field_names = ['product_uom_qty', 'price_unit', 'discount', 'tax_id', 'deposit_amount', 'has_deposit', 'order_lines']
        return {
            'required': bool(required),
            'field_names': field_names,
        }

    def _collect_mcp_money_impact_fields(self, payload, env=None):
        money_fields = []
        config = self._get_mcp_order_money_confirmation_config(env=env)
        configured = set(config['field_names'])
        direct_candidates = ('deposit_amount', 'has_deposit')
        for field_name in direct_candidates:
            if field_name in payload and field_name in configured and field_name not in money_fields:
                money_fields.append(field_name)
        if 'line_mode' in payload and payload.get('line_mode') == 'replace':
            if 'line_mode' not in money_fields:
                money_fields.append('line_mode')
        if 'order_lines' in payload and 'order_lines' in configured:
            money_fields.append('order_lines')
            for raw_line in payload.get('order_lines') or []:
                if not isinstance(raw_line, dict):
                    continue
                for field_name in ('product_id', 'product_uom_qty', 'price_unit', 'discount', 'tax_id'):
                    if field_name in raw_line and field_name not in money_fields:
                        money_fields.append(field_name)
        return money_fields

    def _normalize_mcp_order_action_payload(self, payload=None):
        payload = self._get_v3_json_payload(payload=payload)
        allowed_fields = {'request_id', 'agent_name', 'model_name', 'reason'}
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported action payload fields: %s" % ', '.join(unknown_fields))
        return self._normalize_mcp_order_metadata(payload)

    def _normalize_mcp_order_payment_action_payload(self, payload=None, env=None, order=None):
        env = self._get_mcp_order_write_env(env)
        payload = self._get_v3_json_payload(payload=payload)
        allowed_fields = {'journal_id', 'payment_date', 'request_id', 'agent_name', 'model_name', 'reason'}
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported payment payload fields: %s" % ', '.join(unknown_fields))

        metadata = self._normalize_mcp_order_metadata(payload)
        if not metadata.get('reason'):
            raise ValueError("reason is required")

        journal_id = self._coerce_nullable_int(payload.get('journal_id'), 'journal_id')
        if not journal_id:
            raise ValueError("journal_id is required")
        journal = self._ensure_record_exists(env, 'account.journal', journal_id, 'journal_id')
        if getattr(journal, 'type', None) not in ('bank', 'cash'):
            raise ValueError("journal_id must reference a bank or cash journal")
        if order and getattr(journal, 'company_id', None) and getattr(order, 'company_id', None) and journal.company_id != order.company_id:
            raise ValueError("journal_id does not belong to the same company as the order")

        payment_date = self._coerce_nullable_date(payload.get('payment_date'), 'payment_date')
        if not payment_date:
            raise ValueError("payment_date is required")

        return dict(metadata, journal_id=journal.id, payment_date=payment_date)

    def _normalize_mcp_order_line_payload(self, env, raw_line, index, require_full=False):
        if not isinstance(raw_line, dict):
            raise ValueError("order_lines[%s] must be an object" % index)
        unknown_fields = sorted(set(raw_line) - self.MCP_ORDER_LINE_FIELDS)
        if unknown_fields:
            raise ValueError("Unsupported order_lines[%s] fields: %s" % (index, ', '.join(unknown_fields)))

        normalized = {}
        line_id = raw_line.get('id')
        if line_id not in (None, '', False):
            normalized['id'] = self._as_int(line_id, 'order_lines[%s].id' % index)

        product_id = raw_line.get('product_id')
        name = raw_line.get('name')
        # Dòng tự do (in ấn): chấp nhận name thay cho product_id
        if require_full and product_id in (None, '', False) and name in (None, '', False):
            raise ValueError("order_lines[%s] must have product_id or name" % index)
        if product_id not in (None, '', False):
            normalized['product_id'] = self._ensure_record_exists(
                env,
                'product.product',
                self._as_int(product_id, 'order_lines[%s].product_id' % index),
                'order_lines[%s].product_id' % index,
            ).id
        if name not in (None, '', False):
            if not isinstance(name, str):
                raise ValueError("order_lines[%s].name must be a string" % index)
            normalized['name'] = name

        if 'description' in raw_line:
            description = raw_line.get('description')
            if description not in (None, False) and not isinstance(description, str):
                raise ValueError("order_lines[%s].description must be a string or null" % index)
            normalized['description'] = description or False

        for dimension_field in ('height', 'width'):
            if dimension_field in raw_line:
                value = raw_line.get(dimension_field)
                if value in (None, ''):
                    normalized[dimension_field] = 0.0
                else:
                    normalized[dimension_field] = self._as_float(value, 'order_lines[%s].%s' % (index, dimension_field))

        quantity = raw_line.get('product_uom_qty')
        if require_full and quantity in (None, '', False):
            raise ValueError("order_lines[%s].product_uom_qty is required" % index)
        if quantity not in (None, '', False):
            quantity_value = self._as_float(quantity, 'order_lines[%s].product_uom_qty' % index)
            if quantity_value is None or quantity_value <= 0:
                raise ValueError("order_lines[%s].product_uom_qty must be > 0" % index)
            normalized['quantity'] = quantity_value

        price_unit = raw_line.get('price_unit')
        if require_full and price_unit in (None, '', False):
            raise ValueError("order_lines[%s].price_unit is required" % index)
        if price_unit not in (None, '', False):
            price_value = self._as_float(price_unit, 'order_lines[%s].price_unit' % index)
            if price_value is None or price_value < 0:
                raise ValueError("order_lines[%s].price_unit must be >= 0" % index)
            normalized['price_unit'] = price_value

        if 'tax_id' in raw_line:
            normalized['tax_ids'] = self._normalize_tax_ids(env, raw_line.get('tax_id'), 'order_lines[%s].tax_id' % index)
        if 'discount' in raw_line:
            discount_value = self._as_float(raw_line.get('discount'), 'order_lines[%s].discount' % index)
            if discount_value is None or discount_value < 0 or discount_value > 100:
                raise ValueError("order_lines[%s].discount must be between 0 and 100" % index)
            normalized['discount'] = discount_value

        return normalized

    def _normalize_mcp_order_lines(self, env, order_lines, line_mode, is_update=False):
        if order_lines is None:
            return None
        if not isinstance(order_lines, list):
            raise ValueError("order_lines must be an array")
        normalized_lines = []
        for index, raw_line in enumerate(order_lines):
            if not isinstance(raw_line, dict):
                raise ValueError("order_lines[%s] must be an object" % index)
            require_full = not is_update or line_mode == 'replace' or raw_line.get('id') in (None, '', False)
            normalized_line = self._normalize_mcp_order_line_payload(env, raw_line, index, require_full=require_full)
            if line_mode == 'replace' and 'id' in normalized_line:
                raise ValueError("order_lines[%s].id is not supported in replace mode" % index)
            normalized_lines.append(normalized_line)
        return normalized_lines

    def _normalize_mcp_order_write_payload(self, payload=None, is_update=False, order=None, env=None):
        env = self._get_mcp_order_write_env(env)
        payload = self._get_v3_json_payload(payload=payload)
        metadata = self._normalize_mcp_order_metadata(payload)
        money_impact_fields = self._collect_mcp_money_impact_fields(payload, env=env)
        money_confirmation_config = self._get_mcp_order_money_confirmation_config(env=env)

        allowed_fields = self.MCP_ORDER_UPDATE_FIELDS if is_update else self.MCP_ORDER_CREATE_FIELDS
        blocked_fields = sorted(set(payload) & self.MCP_ORDER_UPDATE_BLOCKED_FIELDS) if is_update else []
        if blocked_fields:
            raise ValueError("Unsupported immutable/system fields: %s" % ', '.join(blocked_fields))
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError("Unsupported order fields: %s" % ', '.join(unknown_fields))

        v2_payload = {}
        extra_order_vals = {}
        touched_fields = set()
        employee_confirmation = self._coerce_mcp_nullable_bool(payload.get('employee_confirmation'), 'employee_confirmation')
        confirmation_text = payload.get('confirmation_text')
        if confirmation_text not in (None, False):
            if not isinstance(confirmation_text, str):
                raise ValueError("confirmation_text must be a string")
            confirmation_text = confirmation_text.strip()
        else:
            confirmation_text = ''
        confirmed_by_user_id = self._coerce_nullable_int(payload.get('confirmed_by_user_id'), 'confirmed_by_user_id')
        if confirmed_by_user_id:
            confirmed_by_user_id = self._ensure_record_exists(env, 'res.users', confirmed_by_user_id, 'confirmed_by_user_id').id

        if not is_update:
            partner_id = self._coerce_nullable_int(payload.get('partner_id'), 'partner_id')
            if not partner_id:
                raise ValueError("partner_id is required")
            v2_payload['partner_id'] = self._ensure_record_exists(env, 'res.partner', partner_id, 'partner_id').id
            touched_fields.add('partner_id')
            if 'conversation_id' in payload:
                conversation_id = self._coerce_nullable_int(payload.get('conversation_id'), 'conversation_id')
                if conversation_id:
                    if 'page.fm.conversation' not in env.registry.models:
                        raise LookupError("Conversation not found")
                    conversation = env['page.fm.conversation'].sudo().browse(conversation_id).exists()
                    if not conversation:
                        raise LookupError("Conversation not found")
                    v2_payload['conversation_id'] = conversation.id
                    touched_fields.add('conversation_id')
                else:
                    v2_payload['conversation_id'] = False

        if 'user_id' in payload:
            user_id = self._coerce_nullable_int(payload.get('user_id'), 'user_id')
            extra_order_vals['user_id'] = self._ensure_record_exists(env, 'res.users', user_id, 'user_id').id if user_id else False
            v2_payload['user_id'] = extra_order_vals['user_id']
            touched_fields.add('user_id')

        for text_field in ('order_number', 'client_order_ref', 'delivery_address', 'installation_address'):
            if text_field in payload:
                v2_payload[text_field] = self._coerce_text_value(payload.get(text_field), text_field)
                touched_fields.add(text_field)

        if 'phone' in payload:
            extra_order_vals['phone'] = self._coerce_text_value(payload.get('phone'), 'phone')
            touched_fields.add('phone')

        if 'fulfillment_method' in payload:
            fulfillment_method = payload.get('fulfillment_method')
            if fulfillment_method not in ('delivery', 'installation'):
                raise ValueError("fulfillment_method must be one of delivery,installation")
            extra_order_vals['fulfillment_method'] = fulfillment_method
            touched_fields.add('fulfillment_method')

        if 'production_deadline' in payload:
            v2_payload['production_deadline'] = self._coerce_nullable_date(payload.get('production_deadline'), 'production_deadline')
            if not v2_payload['production_deadline']:
                raise ValueError("production_deadline is required")
            touched_fields.add('production_deadline')
        elif not is_update:
            raise ValueError("production_deadline is required")

        if 'has_deposit' in payload:
            v2_payload['has_deposit'] = self._coerce_mcp_nullable_bool(payload.get('has_deposit'), 'has_deposit')
            touched_fields.add('has_deposit')

        if 'deposit_amount' in payload:
            deposit_amount = self._as_float(payload.get('deposit_amount'), 'deposit_amount')
            if deposit_amount is None or deposit_amount < 0:
                raise ValueError("deposit_amount must be >= 0")
            v2_payload['deposit_amount'] = deposit_amount
            touched_fields.add('deposit_amount')

        for bool_field in ('is_priority', 'is_priority_today'):
            if bool_field in payload:
                extra_order_vals[bool_field] = self._coerce_mcp_nullable_bool(payload.get(bool_field), bool_field)
                touched_fields.add(bool_field)

        line_mode = payload.get('line_mode')
        if is_update:
            if line_mode in (None, '') and payload.get('order_lines') is not None:
                line_mode = 'patch'
            if line_mode not in (None, 'patch', 'replace'):
                raise ValueError("line_mode must be one of patch,replace")
        elif line_mode not in (None, ''):
            raise ValueError("line_mode is only supported on PATCH /dac_erp/mcp/v1/orders/<order_id>")

        order_lines = self._normalize_mcp_order_lines(
            env=env,
            order_lines=payload.get('order_lines') if 'order_lines' in payload else None,
            line_mode=line_mode or 'replace',
            is_update=is_update,
        )
        if not is_update and not order_lines:
            raise ValueError("order_lines is required")
        if order_lines is not None:
            v2_payload['order_lines'] = order_lines
            touched_fields.add('order_lines')
        if is_update and order_lines is not None:
            v2_payload['line_mode'] = line_mode or 'patch'
            touched_fields.add('line_mode')

        effective_fulfillment = extra_order_vals.get('fulfillment_method') or (getattr(order, 'fulfillment_method', None) if order else None) or 'delivery'
        effective_delivery_address = v2_payload.get('delivery_address') if 'delivery_address' in v2_payload else (getattr(order, 'delivery_address', None) if order else None)
        effective_installation_address = v2_payload.get('installation_address') if 'installation_address' in v2_payload else (getattr(order, 'installation_address', None) if order else None)
        effective_deadline = v2_payload.get('production_deadline') if 'production_deadline' in v2_payload else (getattr(order, 'production_deadline', None) if order else None)

        if not effective_deadline:
            raise ValueError("production_deadline is required")
        if effective_fulfillment == 'delivery' and not (effective_delivery_address or '').strip():
            raise ValueError("delivery_address is required when fulfillment_method=delivery")
        if effective_fulfillment == 'installation' and not (effective_installation_address or '').strip():
            raise ValueError("installation_address is required when fulfillment_method=installation")

        confirmation_required = bool(money_impact_fields and money_confirmation_config['required'])
        if confirmation_required and (employee_confirmation is not True or not confirmation_text):
            raise McpHttpError(
                400,
                'confirmation_required',
                'Changing money-impact fields requires explicit employee confirmation',
                details={'money_impact_fields': money_impact_fields},
            )

        return dict(
            metadata,
            v2_payload=v2_payload,
            extra_order_vals=extra_order_vals,
            touched_fields=sorted(touched_fields),
            money_change_confirmation={
                'required': confirmation_required,
                'confirmed': bool(employee_confirmation) if confirmation_required else False,
                'confirmation_text': confirmation_text or False,
                'confirmed_by_user_id': confirmed_by_user_id or False,
                'money_impact_fields': money_impact_fields,
            },
        )

    def _get_mcp_order_write_snapshot(self, order_id, env=None):
        env = self._get_mcp_order_write_env(env)
        snapshot = self._get_mcp_order_payload(order_id, env=env, include_lines=True) or {}
        order = self._get_mcp_order_record(order_id, env=env)
        snapshot = dict(snapshot)
        snapshot.update({
            'phone': getattr(order, 'phone', None),
            'fulfillment_method': getattr(order, 'fulfillment_method', None),
            'is_priority': bool(getattr(order, 'is_priority', False)) if 'is_priority' in order._fields else None,
            'is_priority_today': bool(getattr(order, 'is_priority_today', False)) if 'is_priority_today' in order._fields else None,
        })
        return snapshot

    def _build_mcp_order_changed_fields(self, before_snapshot, after_snapshot, touched_fields):
        before_snapshot = before_snapshot or {}
        after_snapshot = after_snapshot or {}
        changed_fields = {}
        for field_name in touched_fields or []:
            if field_name == 'line_mode':
                continue
            if field_name == 'order_lines':
                if before_snapshot.get('lines') != after_snapshot.get('lines'):
                    changed_fields['lines'] = after_snapshot.get('lines') or []
                continue
            if before_snapshot.get(field_name) != after_snapshot.get(field_name):
                changed_fields[field_name] = after_snapshot.get(field_name)
        return changed_fields

    def _create_mcp_order_log(
        self,
        env=None,
        order=None,
        conversation=None,
        conversation_id=None,
        action_type=None,
        normalized_payload=None,
        payload_fingerprint=None,
        old_value=None,
        new_value=None,
        response_data=None,
        status='success',
        invoice=None,
        payment=None,
        error_code=None,
        error_message=None,
    ):
        env = self._get_mcp_order_write_env(env)
        if action_type not in self.MCP_ORDER_WRITE_ACTIONS:
            raise ValueError("Unsupported order action_type %s" % action_type)
        normalized_payload = normalized_payload or {}
        create_vals = {
            'order_id': order.id if order else False,
            'conversation_id': conversation_id if conversation_id is not None else (conversation.id if conversation else False),
            'action_type': action_type,
            'request_id': normalized_payload.get('request_id'),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'payload_fingerprint': payload_fingerprint,
            'old_value_json': self._dump_json_text(old_value or {}),
            'new_value_json': self._dump_json_text(new_value or {}),
            'response_snapshot_json': self._dump_json_text(response_data or {}),
            'agent_name': normalized_payload.get('agent_name'),
            'model_name': normalized_payload.get('model_name') or False,
            'reason': normalized_payload.get('reason') or False,
            'status': status,
            'invoice_id': invoice.id if invoice else False,
            'payment_id': payment.id if payment else False,
            'error_code': error_code or False,
            'error_message': error_message or False,
        }
        return env[self.MCP_ORDER_LOG_MODEL].sudo().create(create_vals)

    def _build_mcp_order_replayed_response_data(self, log_record, env=None, order_snapshot_builder=None):
        env = self._get_mcp_order_write_env(env)
        data = {}
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        order = log_record.order_id.sudo() if log_record.order_id else False
        if order:
            data['order_id'] = order.id
            if order_snapshot_builder:
                data['order'] = order_snapshot_builder(order)
            else:
                data['order'] = self._get_mcp_order_write_snapshot(order.id, env=env)
        data['log_id'] = log_record.id
        data['idempotent_replay'] = True
        data.setdefault('changed_fields', {})
        return data

    def _handle_mcp_order_write_idempotency_or_raise(self, env=None, request_id=None, payload_fingerprint=None, conflict_code='conflict'):
        env = self._get_mcp_order_write_env(env)
        log_record = env[self.MCP_ORDER_LOG_MODEL].sudo().search([('request_id', '=', request_id)], limit=1)
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                conflict_code,
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _create_mcp_order_record(self, env=None, normalized_payload=None):
        env = self._get_mcp_order_write_env(env)
        normalized_payload = normalized_payload or {}
        v2_payload = dict(normalized_payload.get('v2_payload') or {})
        normalized_v2 = self._normalize_order_write_payload(env=env, payload=v2_payload, is_update=False)
        order_vals = dict(normalized_v2['order_vals'] or {})
        conversation_id = order_vals.pop('conversation_id', False)
        order_vals.update(normalized_payload.get('extra_order_vals') or {})
        order_lines = normalized_v2.get('order_lines')
        order_model = env['sale.order'].sudo().with_context(**self._get_v2_write_context())
        with env.cr.savepoint():
            order = order_model.create(order_vals)
            if conversation_id:
                env.cr.execute(
                    "UPDATE sale_order SET conversation_id = %s WHERE id = %s",
                    [conversation_id, order.id],
                )
                order.invalidate_recordset(['conversation_id'])
            if order_lines is not None:
                self._apply_order_line_operations(env=env, order=order, order_lines=order_lines, line_mode='replace')
        return order

    def _update_mcp_order_record(self, order, env=None, normalized_payload=None):
        env = self._get_mcp_order_write_env(env)
        normalized_payload = normalized_payload or {}
        v2_payload = dict(normalized_payload.get('v2_payload') or {})
        normalized_v2 = self._normalize_order_write_payload(env=env, payload=v2_payload, is_update=True)
        order_vals = dict(normalized_v2['order_vals'] or {})
        order_vals.update(normalized_payload.get('extra_order_vals') or {})
        order_lines = normalized_v2.get('order_lines')
        line_mode = normalized_v2.get('line_mode')
        with env.cr.savepoint():
            if order_vals:
                order.with_context(**self._get_v2_write_context()).write(order_vals)
            if order_lines is not None:
                self._apply_order_line_operations(env=env, order=order, order_lines=order_lines, line_mode=line_mode)
        return order

    def _run_mcp_order_write_action(self, action_type, payload=None, order_id=None, env=None):
        env = self._get_mcp_order_write_env(env)
        is_update = action_type == 'order_update'
        order = self._get_mcp_order_record(order_id, env=env) if is_update else False
        if order and getattr(order, 'order_state_custom', None) not in self.MCP_ORDER_MUTABLE_STATES:
            raise McpHttpError(400, 'validation_error', 'Order can only be updated in quotation or deposit stage')

        try:
            normalized_payload = self._normalize_mcp_order_write_payload(payload=payload, is_update=is_update, order=order, env=env)
        except LookupError:
            raise McpHttpError(404, 'not_found', 'Conversation not found')
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(existing_log, env=env)

        before_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env) if order else {}

        try:
            if action_type == 'order_create':
                order = self._create_mcp_order_record(env=env, normalized_payload=normalized_payload)
            else:
                order = self._update_mcp_order_record(order, env=env, normalized_payload=normalized_payload)
        except LookupError as exc:
            message = str(exc)
            if 'Order' in message:
                raise McpHttpError(404, 'not_found', 'Order not found')
            raise McpHttpError(404, 'not_found', 'Conversation not found')
        except (ValueError, ValidationError, UserError) as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'insufficient_permission', str(exc))

        after_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        conversation_id_map = self._get_order_conversation_id_map(order_ids=[order.id], env=env)
        changed_fields = self._build_mcp_order_changed_fields(
            before_snapshot,
            after_snapshot,
            normalized_payload.get('touched_fields') or [],
        )
        response_data = {
            'order_id': order.id,
            'changed_fields': changed_fields,
            'order': after_snapshot,
            'money_change_confirmation': normalized_payload.get('money_change_confirmation') or {
                'required': False,
                'confirmed': False,
                'confirmation_text': False,
                'confirmed_by_user_id': False,
                'money_impact_fields': [],
            },
            'idempotent_replay': False,
        }
        log_record = self._create_mcp_order_log(
            env=env,
            order=order,
            action_type=action_type,
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=before_snapshot,
            new_value=after_snapshot,
            response_data=response_data,
            status='success',
            conversation_id=conversation_id_map.get(order.id) or False,
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _get_mcp_order_stage(self, order):
        return getattr(order, 'order_state_custom', None)

    def _raise_order_workflow_business_violation(self, message):
        raise McpHttpError(400, 'business_rule_violation', message)

    def _raise_order_interactive_action_unsupported(self, message):
        raise McpHttpError(400, 'unsupported_interactive_action', message)

    def _raise_order_payment_business_violation(self, message, details=None):
        raise McpHttpError(422, 'business_rule_violation', message, details=details)

    def _raise_order_payment_conflict(self, message, details=None):
        raise McpHttpError(409, 'business_conflict', message, details=details)

    def _guard_mcp_order_workflow_action(self, order, action_type):
        current_stage = self._get_mcp_order_stage(order)
        if current_stage in self.MCP_ORDER_TERMINAL_STATES:
            self._raise_order_workflow_business_violation(
                "Order workflow action is not allowed when order_state_custom is %s" % current_stage
            )
        if action_type == 'order_confirm_info':
            if current_stage != 'quotation':
                self._raise_order_workflow_business_violation("confirm-info is only allowed from quotation stage")
        elif action_type == 'order_proceed_to_production':
            if current_stage != 'deposit':
                self._raise_order_workflow_business_violation("proceed-to-production is only allowed from deposit stage")
        elif action_type == 'order_proceed_to_delivery':
            if current_stage != 'production':
                self._raise_order_workflow_business_violation("proceed-to-delivery is only allowed from production stage")
            if getattr(order, 'fulfillment_method', None) != 'delivery':
                self._raise_order_workflow_business_violation("proceed-to-delivery requires fulfillment_method=delivery")
        elif action_type == 'order_proceed_to_installation':
            if current_stage != 'production':
                self._raise_order_workflow_business_violation("proceed-to-installation is only allowed from production stage")
            if getattr(order, 'fulfillment_method', None) != 'installation':
                self._raise_order_workflow_business_violation("proceed-to-installation requires fulfillment_method=installation")
        else:
            raise ValueError("Unsupported workflow action_type %s" % action_type)
        return current_stage

    def _execute_mcp_order_workflow_action(self, order, action_type):
        if action_type == 'order_confirm_info':
            return order.action_confirm_info()
        if action_type == 'order_proceed_to_production':
            return order.with_context(from_ui_button=True).action_proceed_to_production()
        if action_type == 'order_proceed_to_delivery':
            return order.action_proceed_to_delivery()
        if action_type == 'order_proceed_to_installation':
            return order.action_proceed_to_installation()
        raise ValueError("Unsupported workflow action_type %s" % action_type)

    def _get_order_invoice_records(self, order, env=None, deposit_flag=None, include_cancelled=False):
        env = self._get_mcp_order_write_env(env)
        if not order:
            return env['account.move']
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', '=', order.name),
        ]
        if deposit_flag is True:
            domain.append(('dac_deposit_invoice', '=', True))
        elif deposit_flag is False:
            domain.append(('dac_deposit_invoice', '=', False))
        if not include_cancelled:
            domain.append(('state', '!=', 'cancel'))
        return env['account.move'].sudo().search(domain, order='id asc')

    def _get_newest_invoice(self, invoices):
        invoices = invoices or invoices.env['account.move']
        if not invoices:
            return False
        return invoices.sorted(lambda inv: inv.id)[-1]

    def _extract_created_invoice(self, order, before_invoice_ids, env=None, deposit_flag=None):
        invoices = self._get_order_invoice_records(order, env=env, deposit_flag=deposit_flag)
        created = invoices.filtered(lambda inv: inv.id not in (before_invoice_ids or set()))
        return self._get_newest_invoice(created)

    def _get_order_payment_register_journal(self, journal_id, env=None):
        env = self._get_mcp_order_write_env(env)
        return env['account.journal'].sudo().browse(int(journal_id)).exists()

    def _get_invoice_payment_records(self, invoice, env=None):
        env = self._get_mcp_order_write_env(env)
        payments = env['account.payment']
        if not invoice:
            return payments
        if hasattr(invoice, '_get_reconciled_payments'):
            try:
                payments = invoice._get_reconciled_payments()
            except Exception:
                payments = env['account.payment']
        if not payments and 'reconciled_invoice_ids' in env['account.payment']._fields:
            payments = env['account.payment'].sudo().search([
                ('reconciled_invoice_ids', 'in', invoice.ids),
            ], order='id asc')
        return payments

    def _get_newest_payment_for_invoice(self, invoice, env=None):
        payments = self._get_invoice_payment_records(invoice, env=env)
        if not payments:
            return False
        return payments.sorted(lambda pay: pay.id)[-1]

    def _get_deposit_invoice_for_order(self, order, env=None, include_cancelled=False):
        invoices = self._get_order_invoice_records(order, env=env, deposit_flag=True, include_cancelled=include_cancelled)
        return self._get_newest_invoice(invoices)

    def _get_final_invoice_for_order(self, order, env=None, include_cancelled=False):
        invoices = self._get_order_invoice_records(order, env=env, deposit_flag=False, include_cancelled=include_cancelled)
        return self._get_newest_invoice(invoices)

    def _get_mcp_payment_action_order_snapshot(self, order):
        return normalize_order_payment_snapshot(order.sudo())

    def _get_deposit_artifact_snapshots(self, order, env=None):
        invoice = self._get_deposit_invoice_for_order(order, env=env)
        payment = self._get_newest_payment_for_invoice(invoice, env=env) if invoice else False
        return invoice, payment, normalize_invoice_item(invoice), normalize_payment_item(payment)

    def _get_final_artifact_snapshots(self, order, env=None):
        invoice = self._get_final_invoice_for_order(order, env=env)
        payment = self._get_newest_payment_for_invoice(invoice, env=env) if invoice else False
        return invoice, payment, normalize_invoice_item(invoice), normalize_payment_item(payment)

    def _create_mcp_payment_wizard(self, wizard_model, order, journal_id, payment_date, env=None):
        env = self._get_mcp_order_write_env(env)
        return env[wizard_model].sudo().with_context(
            active_model='sale.order',
            active_id=order.id,
            active_ids=order.ids,
        ).create({
            'journal_id': journal_id,
            'payment_date': payment_date,
        })

    def _guard_mcp_order_invoice_action(self, order, action_type):
        current_stage = self._get_mcp_order_stage(order)
        if current_stage in self.MCP_ORDER_TERMINAL_STATES:
            self._raise_order_workflow_business_violation(
                "Order invoice action is not allowed when order_state_custom is %s" % current_stage
            )
        if action_type == 'order_create_deposit_invoice':
            if current_stage != 'deposit':
                self._raise_order_workflow_business_violation("create-deposit-invoice is only allowed from deposit stage")
            if not bool(getattr(order, 'has_deposit', False)):
                self._raise_order_workflow_business_violation("create-deposit-invoice requires has_deposit=true")
            if float(getattr(order, 'deposit_amount', 0.0) or 0.0) <= 0:
                self._raise_order_workflow_business_violation("create-deposit-invoice requires deposit_amount > 0")
            existing = self._get_order_invoice_records(order, env=order.env, deposit_flag=True)
            if existing:
                self._raise_order_workflow_business_violation("Deposit invoice already exists for this order")
        elif action_type == 'order_create_final_invoice':
            if current_stage != 'payment':
                self._raise_order_workflow_business_violation("create-final-invoice is only allowed from payment stage")
            existing = self._get_order_invoice_records(order, env=order.env, deposit_flag=False)
            if existing:
                self._raise_order_workflow_business_violation("Final invoice already exists for this order")
        else:
            raise ValueError("Unsupported invoice action_type %s" % action_type)
        return current_stage

    def _execute_mcp_order_invoice_action(self, order, action_type):
        if action_type == 'order_create_deposit_invoice':
            return order.action_deposit_invoice()
        if action_type == 'order_create_final_invoice':
            return order.action_create_final_invoice()
        raise ValueError("Unsupported invoice action_type %s" % action_type)

    def _run_mcp_order_invoice_action(self, action_type, order_id, action_name, payload=None, env=None):
        env = self._get_mcp_order_write_env(env)
        order = self._get_mcp_order_record(order_id, env=env)
        try:
            normalized_payload = self._normalize_mcp_order_action_payload(payload=payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(existing_log, env=env)

        current_stage = self._guard_mcp_order_invoice_action(order, action_type)
        before_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        before_invoice_ids = set(self._get_order_invoice_records(
            order,
            env=env,
            deposit_flag=True if action_type == 'order_create_deposit_invoice' else False,
            include_cancelled=True,
        ).ids)

        try:
            action_result = self._execute_mcp_order_invoice_action(order, action_type)
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'insufficient_permission', str(exc))

        created_invoice = self._extract_created_invoice(
            order,
            before_invoice_ids=before_invoice_ids,
            env=env,
            deposit_flag=True if action_type == 'order_create_deposit_invoice' else False,
        )
        order.invalidate_recordset()
        after_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        new_stage = self._get_mcp_order_stage(order)
        invoice_payload = normalize_invoice_item(created_invoice) if created_invoice else None

        if isinstance(action_result, dict) and not created_invoice:
            is_notification_only = (
                action_result.get('type') == 'ir.actions.client'
                and action_result.get('tag') == 'display_notification'
            )
            if not is_notification_only:
                self._raise_order_interactive_action_unsupported(
                    "Invoice action requires interactive UI handling and is not supported through this MCP route"
                )

        response_data = {
            'order_id': order.id,
            'action': action_name,
            'old_stage': current_stage,
            'new_stage': new_stage,
            'invoice': invoice_payload,
            'order': after_snapshot,
            'idempotent_replay': False,
        }
        conversation_id_map = self._get_order_conversation_id_map(order_ids=[order.id], env=env)
        log_record = self._create_mcp_order_log(
            env=env,
            order=order,
            action_type=action_type,
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=before_snapshot,
            new_value={
                'order': after_snapshot,
                'invoice': invoice_payload,
            },
            response_data=response_data,
            status='success',
            conversation_id=conversation_id_map.get(order.id) or False,
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _build_mcp_payment_action_response(
        self,
        order,
        action_type,
        request_id,
        order_snapshot,
        invoice_payload=None,
        payment_payload=None,
        details=None,
    ):
        response_data = {
            'order_id': order.id,
            'action_type': action_type,
            'request_id': request_id,
            'invoice': invoice_payload,
            'payment': payment_payload,
            'order': order_snapshot,
        }
        if details:
            response_data['details'] = details
        return response_data

    def _finalize_mcp_payment_action_log(
        self,
        env,
        order,
        action_type,
        normalized_payload,
        payload_fingerprint,
        before_snapshot,
        invoice,
        payment,
        response_data,
    ):
        conversation_id_map = self._get_order_conversation_id_map(order_ids=[order.id], env=env)
        log_record = self._create_mcp_order_log(
            env=env,
            order=order,
            action_type=action_type,
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=before_snapshot,
            new_value={
                'invoice': normalize_invoice_item(invoice),
                'payment': normalize_payment_item(payment),
                'order': response_data.get('order'),
            },
            response_data=response_data,
            status='success',
            conversation_id=conversation_id_map.get(order.id) or False,
            invoice=invoice,
            payment=payment,
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _run_mcp_confirm_deposit_invoice(self, order_id, payload=None, env=None):
        env = self._get_mcp_order_write_env(env)
        order = self._get_mcp_order_record(order_id, env=env, error_code='order_not_found')
        try:
            normalized_payload = self._normalize_mcp_order_payment_action_payload(payload=payload, env=env, order=order)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
            conflict_code='idempotency_conflict',
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(
                existing_log,
                env=env,
                order_snapshot_builder=self._get_mcp_payment_action_order_snapshot,
            )

        before_snapshot = self._get_mcp_payment_action_order_snapshot(order)
        invoice, payment, invoice_payload, payment_payload = self._get_deposit_artifact_snapshots(order, env=env)
        if invoice and getattr(invoice, 'state', None) == 'posted' and getattr(invoice, 'payment_state', None) == 'paid':
            response_data = self._build_mcp_payment_action_response(
                order,
                action_type='confirm_deposit_invoice',
                request_id=normalized_payload['request_id'],
                order_snapshot=before_snapshot,
                invoice_payload=invoice_payload,
                payment_payload=payment_payload,
                details={'already_confirmed': True},
            )
            return self._finalize_mcp_payment_action_log(
                env,
                order,
                'order_confirm_deposit_invoice',
                normalized_payload,
                payload_fingerprint,
                before_snapshot,
                invoice,
                payment,
                response_data,
            )

        current_stage = self._get_mcp_order_stage(order)
        if current_stage in self.MCP_ORDER_TERMINAL_STATES:
            self._raise_order_payment_business_violation(
                "confirm-deposit-invoice is not allowed when order_state_custom is %s" % current_stage
            )
        if current_stage != 'deposit':
            self._raise_order_payment_business_violation("confirm-deposit-invoice is only allowed from deposit stage")
        if not bool(getattr(order, 'has_deposit', False)):
            self._raise_order_payment_business_violation("This order is not configured to require a deposit")
        if float(getattr(order, 'deposit_amount', 0.0) or 0.0) <= 0:
            self._raise_order_payment_business_violation("Deposit amount is not configured for this order")

        journal = self._get_order_payment_register_journal(normalized_payload['journal_id'], env=env)
        if not journal:
            raise McpHttpError(400, 'validation_error', 'journal_id is required')

        before_invoice_ids = set(self._get_order_invoice_records(order, env=env, deposit_flag=True, include_cancelled=True).ids)
        try:
            wizard = self._create_mcp_payment_wizard(
                'deposit.confirm.wizard',
                order,
                journal.id,
                normalized_payload['payment_date'],
                env=env,
            )
            wizard.action_confirm()
        except (UserError, ValidationError) as exc:
            self._raise_order_payment_business_violation(str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'permission_denied', str(exc))

        order.invalidate_recordset()
        invoice = self._extract_created_invoice(order, before_invoice_ids=before_invoice_ids, env=env, deposit_flag=True) or self._get_deposit_invoice_for_order(order, env=env)
        payment = self._get_newest_payment_for_invoice(invoice, env=env) if invoice else False
        invoice_payload = normalize_invoice_item(invoice)
        payment_payload = normalize_payment_item(payment)
        after_snapshot = self._get_mcp_payment_action_order_snapshot(order)
        response_data = self._build_mcp_payment_action_response(
            order,
            action_type='confirm_deposit_invoice',
            request_id=normalized_payload['request_id'],
            order_snapshot=after_snapshot,
            invoice_payload=invoice_payload,
            payment_payload=payment_payload,
        )
        return self._finalize_mcp_payment_action_log(
            env,
            order,
            'order_confirm_deposit_invoice',
            normalized_payload,
            payload_fingerprint,
            before_snapshot,
            invoice,
            payment,
            response_data,
        )

    def _run_mcp_confirm_final_payment(self, order_id, payload=None, env=None):
        env = self._get_mcp_order_write_env(env)
        order = self._get_mcp_order_record(order_id, env=env, error_code='order_not_found')
        try:
            normalized_payload = self._normalize_mcp_order_payment_action_payload(payload=payload, env=env, order=order)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
            conflict_code='idempotency_conflict',
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(
                existing_log,
                env=env,
                order_snapshot_builder=self._get_mcp_payment_action_order_snapshot,
            )

        before_snapshot = self._get_mcp_payment_action_order_snapshot(order)
        remaining_amount_before = before_snapshot.get('amount_residual')
        invoice, payment, invoice_payload, payment_payload = self._get_final_artifact_snapshots(order, env=env)

        if invoice and getattr(invoice, 'payment_state', None) == 'paid':
            response_data = self._build_mcp_payment_action_response(
                order,
                action_type='confirm_final_payment',
                request_id=normalized_payload['request_id'],
                order_snapshot=before_snapshot,
                invoice_payload=invoice_payload,
                payment_payload=payment_payload,
                details={'already_confirmed': True, 'remaining_amount_before': remaining_amount_before},
            )
            return self._finalize_mcp_payment_action_log(
                env,
                order,
                'order_confirm_final_payment',
                normalized_payload,
                payload_fingerprint,
                before_snapshot,
                invoice,
                payment,
                response_data,
            )

        if bool(getattr(order, 'is_order_completed', False)) and (remaining_amount_before or 0.0) <= 0:
            response_data = self._build_mcp_payment_action_response(
                order,
                action_type='confirm_final_payment',
                request_id=normalized_payload['request_id'],
                order_snapshot=before_snapshot,
                invoice_payload=invoice_payload,
                payment_payload=payment_payload,
                details={'already_confirmed': True, 'remaining_amount_before': remaining_amount_before},
            )
            return self._finalize_mcp_payment_action_log(
                env,
                order,
                'order_confirm_final_payment',
                normalized_payload,
                payload_fingerprint,
                before_snapshot,
                invoice,
                payment,
                response_data,
            )

        if invoice:
            self._raise_order_payment_conflict(
                "A final invoice already exists for this order; use the accounting UI or a dedicated future payment route",
                details={'invoice_id': invoice.id},
            )

        current_stage = self._get_mcp_order_stage(order)
        if current_stage in self.MCP_ORDER_TERMINAL_STATES:
            self._raise_order_payment_business_violation(
                "confirm-final-payment is not allowed when order_state_custom is %s" % current_stage
            )
        if current_stage != 'payment':
            self._raise_order_payment_business_violation("confirm-final-payment is only allowed from payment stage")

        journal = self._get_order_payment_register_journal(normalized_payload['journal_id'], env=env)
        if not journal:
            raise McpHttpError(400, 'validation_error', 'journal_id is required')

        action_result = None
        before_invoice_ids = set(self._get_order_invoice_records(order, env=env, deposit_flag=False, include_cancelled=True).ids)
        try:
            if (remaining_amount_before or 0.0) <= 0:
                action_result = order.action_create_final_invoice()
            else:
                wizard = self._create_mcp_payment_wizard(
                    'final.payment.confirm.wizard',
                    order,
                    journal.id,
                    normalized_payload['payment_date'],
                    env=env,
                )
                action_result = wizard.action_confirm()
        except (UserError, ValidationError) as exc:
            self._raise_order_payment_business_violation(str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'permission_denied', str(exc))

        order.invalidate_recordset()
        invoice = self._extract_created_invoice(order, before_invoice_ids=before_invoice_ids, env=env, deposit_flag=False) or self._get_final_invoice_for_order(order, env=env)
        payment = self._get_newest_payment_for_invoice(invoice, env=env) if invoice else False
        invoice_payload = normalize_invoice_item(invoice)
        payment_payload = normalize_payment_item(payment)
        after_snapshot = self._get_mcp_payment_action_order_snapshot(order)

        if isinstance(action_result, dict):
            is_notification_only = (
                action_result.get('type') == 'ir.actions.client'
                and action_result.get('tag') == 'display_notification'
            )
            is_reload_only = (
                action_result.get('type') == 'ir.actions.client'
                and action_result.get('tag') == 'reload'
            )
            if not (is_notification_only or is_reload_only):
                raise McpHttpError(
                    409,
                    'unsupported_interactive_action',
                    'Final payment confirmation requires interactive UI handling and is not supported through this MCP route',
                )

        response_data = self._build_mcp_payment_action_response(
            order,
            action_type='confirm_final_payment',
            request_id=normalized_payload['request_id'],
            order_snapshot=after_snapshot,
            invoice_payload=invoice_payload,
            payment_payload=payment_payload,
            details={'remaining_amount_before': remaining_amount_before},
        )
        return self._finalize_mcp_payment_action_log(
            env,
            order,
            'order_confirm_final_payment',
            normalized_payload,
            payload_fingerprint,
            before_snapshot,
            invoice,
            payment,
            response_data,
        )

    def _run_mcp_order_workflow_action(self, action_type, order_id, action_name, payload=None, env=None):
        env = self._get_mcp_order_write_env(env)
        order = self._get_mcp_order_record(order_id, env=env)
        try:
            normalized_payload = self._normalize_mcp_order_action_payload(payload=payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_mcp_order_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_mcp_order_replayed_response_data(existing_log, env=env)

        current_stage = self._guard_mcp_order_workflow_action(order, action_type)

        before_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        try:
            action_result = self._execute_mcp_order_workflow_action(order, action_type)
        except (UserError, ValidationError) as exc:
            raise McpHttpError(400, 'business_rule_violation', str(exc))
        except AccessError as exc:
            raise McpHttpError(403, 'insufficient_permission', str(exc))

        if isinstance(action_result, dict):
            self._raise_order_workflow_business_violation(
                "Workflow action requires interactive UI handling and is not supported through this MCP route"
            )

        order.invalidate_recordset()
        after_snapshot = self._get_mcp_order_write_snapshot(order.id, env=env)
        new_stage = self._get_mcp_order_stage(order)
        response_data = {
            'order_id': order.id,
            'action': action_name,
            'old_stage': current_stage,
            'new_stage': new_stage,
            'order': after_snapshot,
            'idempotent_replay': False,
        }
        conversation_id_map = self._get_order_conversation_id_map(order_ids=[order.id], env=env)
        log_record = self._create_mcp_order_log(
            env=env,
            order=order,
            action_type=action_type,
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=before_snapshot,
            new_value=after_snapshot,
            response_data=response_data,
            status='success',
            conversation_id=conversation_id_map.get(order.id) or False,
        )
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _get_mcp_write_env(self, env=None):
        return self._get_v3_write_env(env)

    def _normalize_mcp_write_payload(self, action_type, payload=None):
        try:
            return self._normalize_v3_request_payload(action_type, payload or {})
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

    def _get_mcp_write_conversation(self, conversation_id, env=None):
        try:
            return self._find_v3_conversation_or_404(conversation_id, env=env)
        except LookupError:
            raise McpHttpError(404, 'not_found', 'Conversation not found')

    def _handle_mcp_write_idempotency_or_raise(self, env=None, request_id=None, payload_fingerprint=None):
        try:
            return self._handle_idempotency_or_raise(
                env=env,
                request_id=request_id,
                payload_fingerprint=payload_fingerprint,
            )
        except ValueError as exc:
            raise McpHttpError(409, 'conflict', str(exc))

    def _post_mcp_internal_note(self, conversation, note_text, agent_name):
        if not hasattr(conversation, 'message_post'):
            return False, False
        body = "<p><strong>AI note (%s)</strong></p><p>%s</p>" % (
            html_escape(agent_name or 'AI'),
            html_escape(note_text or ''),
        )
        message = conversation.sudo().message_post(
            body=body,
            subtype_xmlid='mail.mt_note',
        )
        return bool(message), message.id if message else False

    def _create_mcp_conversation_ai_note(self, env, conversation, normalized_payload, payload_fingerprint):
        message_posted = False
        posted_message_id = False
        if normalized_payload.get('note_type') == 'internal_note':
            message_posted, posted_message_id = self._post_mcp_internal_note(
                conversation,
                normalized_payload['note_text'],
                normalized_payload.get('agent_name'),
            )
        changed_fields = {
            'note_text': normalized_payload['note_text'],
            'note_type': normalized_payload['note_type'],
        }
        response_data = {
            'conversation_id': conversation.id,
            'changed_fields': changed_fields,
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
            'message_posted': bool(message_posted),
        }
        if posted_message_id:
            response_data['message_id'] = posted_message_id
        log_record = self._create_ai_log(
            env=env,
            conversation=conversation,
            action_type='note_create',
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value={},
            new_value=dict(changed_fields, message_posted=bool(message_posted)),
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        response_data['idempotent_replay'] = False
        log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
        return response_data

    def _normalize_mcp_write_result(self, result):
        data = dict(result.get('data') or {})
        data.setdefault('conversation_id', data.get('conversation_id'))
        data.setdefault('changed_fields', {})
        data.setdefault('conversation', {})
        data.setdefault('idempotent_replay', False)
        return data

    def _run_mcp_write_action(self, action_type, conversation_id, executor, payload=None, env=None):
        env = self._get_mcp_write_env(env)
        payload = self._get_v3_json_payload(payload=payload)
        normalized_payload = self._normalize_mcp_write_payload(action_type, payload=payload)
        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        conversation = self._get_mcp_write_conversation(conversation_id, env=env)

        existing_log = self._handle_mcp_write_idempotency_or_raise(
            env=env,
            request_id=normalized_payload['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_replayed_response_data(existing_log, conversation)

        try:
            result = executor(env, conversation, normalized_payload, payload_fingerprint)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        except LookupError:
            raise McpHttpError(404, 'not_found', 'Conversation not found')

        if isinstance(result, dict) and 'data' in result:
            return self._normalize_mcp_write_result(result)
        return self._normalize_mcp_write_result({'data': result})

    def _dispatch_mcp_conversations(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        scope = self._resolve_mcp_conversation_scope(env=env, params=params)
        is_internal = None
        if scope == self.MCP_SCOPE_EXTERNAL:
            is_internal = False
        elif scope == self.MCP_SCOPE_INTERNAL:
            is_internal = True
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=20,
            max_limit=100,
        )
        raw_payload = self._get_v2_conversations_data(
            env=env,
            conversation_id=params.get('conversation_id'),
            page_id=params.get('page_id'),
            page_fm_id_str=params.get('page_fm_id_str'),
            platform=params.get('platform'),
            status=params.get('status'),
            require_processing=params.get('require_processing'),
            has_unread=params.get('has_unread'),
            unread_only=params.get('unread_only'),
            is_internal=is_internal,
            owner_id=params.get('owner_id'),
            participant_id=params.get('participant_id'),
            assignee_user_id=params.get('assignee_user_id'),
            staff_user_id=params.get('staff_user_id'),
            date=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
            days=params.get('days'),
            date_field=params.get('date_field'),
            unreplied=params.get('unreplied'),
            unreplied_date=params.get('unreplied_date'),
            unreplied_date_from=params.get('unreplied_date_from'),
            unreplied_date_to=params.get('unreplied_date_to'),
            tag_code=params.get('tag_code'),
            tag_mode=params.get('tag_mode'),
            limit=limit,
            offset=offset,
            asc=params.get('asc'),
        )
        payload = self._mcp_list_payload(
            self._normalize_conversation_records(raw_payload.get('items') or [], env=env),
            raw_payload.get('total', 0),
        )
        return payload, 200

    def _dispatch_mcp_health(self, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        return self._mcp_detail_payload(self._get_mcp_health_data(env=env)), 200

    def _dispatch_mcp_capabilities(self, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        return self._mcp_detail_payload(self._get_mcp_capabilities_data(env=env)), 200

    def _dispatch_mcp_conversation_messages(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        scope = self._resolve_mcp_conversation_scope(env=env, params=params)
        include_internal = scope in (self.MCP_SCOPE_INTERNAL, self.MCP_SCOPE_ALL)
        message_params = dict(params or {})
        message_params.pop('include_internal', None)
        message_params.pop('scope', None)
        return self._get_mcp_messages_payload(
            conversation_id,
            env=env,
            include_internal=include_internal,
            **message_params
        ), 200

    def _dispatch_mcp_conversation_context(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        scope = self._resolve_mcp_conversation_scope(env=env, params=params)
        include_internal = scope in (self.MCP_SCOPE_INTERNAL, self.MCP_SCOPE_ALL)
        conversation_payload = self._get_mcp_conversation_payload(conversation_id, env=env, include_internal=include_internal)
        messages_payload = self._get_mcp_messages_payload(
            conversation_id,
            env=env,
            include_internal=include_internal,
            limit=params.get('limit'),
            offset=params.get('offset'),
            date=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
            sender_role=params.get('sender_role'),
            type_content=params.get('type_content'),
        )
        return self._mcp_detail_payload({
            'conversation': conversation_payload,
            'messages': messages_payload['items'],
        }), 200

    def _dispatch_mcp_internal_conversations(self, env=None, headers=None, provided_key=None, **params):
        params = dict(params or {}, scope=self.MCP_SCOPE_INTERNAL, include_internal='1')
        return self._dispatch_mcp_conversations(env=env, headers=headers, provided_key=provided_key, **params)

    def _dispatch_mcp_internal_conversation_messages(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        params = dict(params or {}, scope=self.MCP_SCOPE_INTERNAL, include_internal='1')
        return self._dispatch_mcp_conversation_messages(conversation_id, env=env, headers=headers, provided_key=provided_key, **params)

    def _dispatch_mcp_internal_conversation_context(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        params = dict(params or {}, scope=self.MCP_SCOPE_INTERNAL, include_internal='1')
        return self._dispatch_mcp_conversation_context(conversation_id, env=env, headers=headers, provided_key=provided_key, **params)

    def _dispatch_mcp_customer_care_queue(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        include_messages = self._parse_include_lines(params.get('include_messages'), default=False)
        message_limit = self._normalize_customer_care_message_limit(params.get('message_limit'), default_limit=10, max_limit=20)
        payload = self._build_customer_care_queue_payload(
            env=env,
            assignee_user_id=params.get('assignee_user_id'),
            owner_id=params.get('owner_id'),
            page_id=params.get('page_id'),
            platform=params.get('platform'),
            conversation_id=params.get('conversation_id'),
            tag_code=params.get('tag_code'),
            limit=params.get('limit'),
            offset=params.get('offset'),
            sla_minutes=params.get('sla_minutes'),
            urgent_minutes=params.get('urgent_minutes'),
            include_messages=include_messages,
            message_limit=message_limit,
        )
        return payload, 200

    def _dispatch_mcp_customers_search(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=10,
            max_limit=20,
        )
        response_data = self._search_customer_candidates(
            env=env,
            q=params.get('q'),
            phone=params.get('phone'),
            mobile=params.get('mobile'),
            email=params.get('email'),
            company=params.get('company'),
            vat=params.get('vat'),
            conversation_id=self._coerce_nullable_int(params.get('conversation_id'), 'conversation_id'),
            limit=limit,
            offset=offset,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customers_resolve(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        payload = self._get_optional_v3_json_payload(payload=payload)
        limit, offset = self._normalize_capped_limit_offset(limit=payload.get('limit'), offset=0, default_limit=10, max_limit=20)
        conversation_id = self._coerce_nullable_int(payload.get('conversation_id'), 'conversation_id')
        mention_text = payload.get('mention_text')
        if mention_text not in (None, False) and not isinstance(mention_text, str):
            raise McpHttpError(400, 'validation_error', 'mention_text must be a string')
        if conversation_id:
            conversation = self._get_mcp_conversation_record(conversation_id, env=env)
            if getattr(conversation, 'partner_id', False):
                candidate = self._serialize_customer_candidate(conversation.partner_id, ['conversation_link'], 0.95)
                return self._mcp_detail_payload({
                    'status': 'exact_match',
                    'source': 'conversation_link',
                    'selected': candidate,
                    'candidates': [candidate],
                    'prompt_suggestion': None,
                }), 200
        result = self._search_customer_candidates(
            env=env,
            q=mention_text,
            phone=payload.get('phone_hint'),
            email=payload.get('email_hint'),
            company=payload.get('company_hint'),
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
        source = 'none'
        if payload.get('phone_hint'):
            source = 'phone_hint'
        elif payload.get('email_hint'):
            source = 'email_hint'
        elif payload.get('company_hint'):
            source = 'company_search'
        elif mention_text:
            source = 'name_search'
        selected = result['items'][0] if result['status'] == 'exact_match' and result['items'] else None
        return self._mcp_detail_payload({
            'status': result['status'],
            'source': source,
            'selected': selected,
            'candidates': result['items'],
            'prompt_suggestion': result['prompt_suggestion'],
        }), 200

    def _dispatch_mcp_products_search(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        limit, offset = self._normalize_capped_limit_offset(
            limit=params.get('limit'),
            offset=params.get('offset'),
            default_limit=10,
            max_limit=20,
        )
        sale_ok = self._as_bool(params.get('sale_ok'), 'sale_ok')
        active = self._as_bool(params.get('active'), 'active')
        response_data = self._search_product_candidates(
            env=env,
            q=params.get('q'),
            default_code=params.get('default_code'),
            barcode=params.get('barcode'),
            category_id=self._coerce_nullable_int(params.get('category_id'), 'category_id'),
            sale_ok=False if sale_ok is False else True,
            active=True if active is None else bool(active),
            limit=limit,
            offset=offset,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_products_resolve(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        payload = self._get_optional_v3_json_payload(payload=payload)
        limit, offset = self._normalize_capped_limit_offset(limit=payload.get('limit'), offset=0, default_limit=10, max_limit=20)
        mention_text = payload.get('mention_text')
        if mention_text not in (None, False) and not isinstance(mention_text, str):
            raise McpHttpError(400, 'validation_error', 'mention_text must be a string')
        conversation_id = self._coerce_nullable_int(payload.get('conversation_id'), 'conversation_id')
        customer_id = self._coerce_nullable_int(payload.get('customer_id'), 'customer_id')
        result = self._search_product_candidates(
            env=env,
            q=mention_text,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        source = 'none'
        if mention_text:
            if any('default_code' in item.get('matched_fields', []) for item in result['items']):
                source = 'product_code'
            elif any('recent_order_context' in item.get('matched_fields', []) for item in result['items']):
                source = 'recent_order_context'
            else:
                source = 'name_search'
        selected = result['items'][0] if result['status'] == 'exact_match' and result['items'] else None
        return self._mcp_detail_payload({
            'status': result['status'],
            'source': source,
            'selected': selected,
            'candidates': result['items'],
            'prompt_suggestion': result['prompt_suggestion'],
        }), 200

    def _dispatch_mcp_customer_care_create_followups(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(
            env=env,
            provided_key=provided_key,
            headers=headers,
            read_key_code='insufficient_permission',
            read_key_message='MCP write key required',
        )
        response_data = self._run_mcp_customer_care_create_followups(payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_care_apply_reviewed_actions(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(
            env=env,
            provided_key=provided_key,
            headers=headers,
            read_key_code='insufficient_permission',
            read_key_message='MCP write key required',
        )
        response_data = self._run_mcp_customer_care_apply_reviewed_actions(payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_care_action_plan(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_customer_care_action_plan(payload=payload, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_care_auto_run(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_customer_care_auto_run(payload=payload, env=env, mode='manual_api')
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_care_auto_run_report(self, run_id, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._get_mcp_customer_care_auto_run_report(run_id, env=env)
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_customer_care_auto_run_runs(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        try:
            payload = self._get_mcp_customer_care_auto_run_run_list(env=env, params=params)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))
        return payload, 200

    def _dispatch_mcp_orders(self, env=None, headers=None, provided_key=None, default_order=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        include_lines = self._parse_include_lines(params.get('include_lines'), default=False)
        payload = self._get_mcp_orders_payload(
            env=env,
            include_lines=include_lines,
            default_order=default_order,
            date=params.get('date'),
            date_from=params.get('date_from'),
            date_to=params.get('date_to'),
            date_field=params.get('date_field'),
            user_id=params.get('user_id'),
            partner_id=params.get('partner_id'),
            conversation_id=params.get('conversation_id'),
            pancake_conversation_id=params.get('pancake_conversation_id'),
            state=params.get('state'),
            custom_state=params.get('custom_state'),
            company_id=params.get('company_id'),
            has_deposit=params.get('has_deposit'),
            is_order_completed=params.get('is_order_completed'),
            min_total=params.get('min_total'),
            max_total=params.get('max_total'),
            deposit_event=params.get('deposit_event'),
            has_deposit_invoice=params.get('has_deposit_invoice'),
            deposit_date=params.get('deposit_date'),
            deposit_date_from=params.get('deposit_date_from'),
            deposit_date_to=params.get('deposit_date_to'),
            limit=params.get('limit'),
            offset=params.get('offset'),
            order=params.get('order'),
        )
        return payload, 200

    def _dispatch_mcp_order_detail(self, order_id, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        include_lines = self._parse_include_lines(params.get('include_lines'), default=True)
        payload = self._get_mcp_order_payload(order_id, env=env, include_lines=include_lines)
        return self._mcp_detail_payload(payload), 200

    def _dispatch_mcp_conversation_orders(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        conversation = self._get_mcp_conversation_record(conversation_id, env=env)
        include_lines = self._parse_include_lines(params.get('include_lines'), default=False)
        payload = self._get_mcp_orders_payload(
            env=env,
            include_lines=include_lines,
            default_order='date_order desc, create_date desc, id desc',
            conversation_id=conversation.id,
            state=params.get('state'),
            custom_state=params.get('custom_state'),
            limit=params.get('limit'),
            offset=params.get('offset'),
        )
        return payload, 200

    def _dispatch_mcp_conversation_ai_summary(self, conversation_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_write_action(
            action_type='summary_upsert',
            conversation_id=conversation_id,
            executor=self._update_conversation_ai_summary,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_conversation_ai_note(self, conversation_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_write_action(
            action_type='note_create',
            conversation_id=conversation_id,
            executor=self._create_mcp_conversation_ai_note,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_conversation_activity(self, conversation_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_write_action(
            action_type='activity_create',
            conversation_id=conversation_id,
            executor=self._create_conversation_followup_activity,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_conversation_triage(self, conversation_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_write_action(
            action_type='triage_update',
            conversation_id=conversation_id,
            executor=self._update_conversation_triage,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_create(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_write_action(
            action_type='order_create',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_update(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_write_action(
            action_type='order_update',
            order_id=order_id,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_confirm_info(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_workflow_action(
            action_type='order_confirm_info',
            order_id=order_id,
            action_name='confirm_info',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_proceed_to_production(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_workflow_action(
            action_type='order_proceed_to_production',
            order_id=order_id,
            action_name='proceed_to_production',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_proceed_to_delivery(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_workflow_action(
            action_type='order_proceed_to_delivery',
            order_id=order_id,
            action_name='proceed_to_delivery',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_proceed_to_installation(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_workflow_action(
            action_type='order_proceed_to_installation',
            order_id=order_id,
            action_name='proceed_to_installation',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_create_deposit_invoice(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_invoice_action(
            action_type='order_create_deposit_invoice',
            order_id=order_id,
            action_name='create_deposit_invoice',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_create_final_invoice(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_order_invoice_action(
            action_type='order_create_final_invoice',
            order_id=order_id,
            action_name='create_final_invoice',
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_confirm_deposit_invoice(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(
            env=env,
            provided_key=provided_key,
            headers=headers,
            read_key_code='insufficient_permission',
            read_key_message='MCP write key required',
        )
        response_data = self._run_mcp_confirm_deposit_invoice(
            order_id,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_order_confirm_final_payment(self, order_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(
            env=env,
            provided_key=provided_key,
            headers=headers,
            read_key_code='insufficient_permission',
            read_key_message='MCP write key required',
        )
        response_data = self._run_mcp_confirm_final_payment(
            order_id,
            payload=payload,
            env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _run_mcp_handler(self, handler, *args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except McpHttpError as exc:
            return self._mcp_error_payload(exc.code, exc.message, details=exc.details), exc.status_code
        except (ValidationError, UserError) as exc:
            return self._mcp_error_payload('validation_error', str(exc)), 400
        except AccessError as exc:
            return self._mcp_error_payload('insufficient_permission', str(exc)), 403
        except ValueError as exc:
            return self._mcp_error_payload('invalid_request', str(exc)), 400
        except Exception as exc:
            _logger.error("Error in MCP adapter route: %s", exc, exc_info=True)
            return self._mcp_error_payload('internal_error', 'Internal server error'), 500

    def _handle_mcp_http(self, handler, *args, **kwargs):
        payload, status_code = self._run_mcp_handler(handler, *args, **kwargs)
        return self._mcp_json_response(payload, status_code=status_code)

    @http.route('/dac_erp/mcp/v1/health', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_health(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_health, **kwargs)

    @http.route('/dac_erp/mcp/v1/capabilities', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_capabilities(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_capabilities, **kwargs)

    @http.route('/dac_erp/mcp/v1/conversations', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_list_conversations(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_conversations, **kwargs)

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/messages', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_conversation_messages(self, conversation_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_conversation_messages, conversation_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/context', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_conversation_context(self, conversation_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_conversation_context, conversation_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/internal/conversations', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_list_internal_conversations(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_internal_conversations, **kwargs)

    @http.route('/dac_erp/mcp/v1/internal/conversations/<int:conversation_id>/messages', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_internal_conversation_messages(self, conversation_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_internal_conversation_messages, conversation_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/internal/conversations/<int:conversation_id>/context', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_internal_conversation_context(self, conversation_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_internal_conversation_context, conversation_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/customer-care/queue', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_customer_care_queue(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_customer_care_queue, **kwargs)

    @http.route('/dac_erp/mcp/v1/customers/search', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_customers_search(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_customers_search, **kwargs)

    @http.route('/dac_erp/mcp/v1/customers/resolve', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customers_resolve(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customers_resolve,
            payload=self._get_optional_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/products/search', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_products_search(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_products_search, **kwargs)

    @http.route('/dac_erp/mcp/v1/products/resolve', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_products_resolve(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_products_resolve,
            payload=self._get_optional_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/create-followups', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customer_care_create_followups(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_create_followups,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/apply-reviewed-actions', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customer_care_apply_reviewed_actions(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_apply_reviewed_actions,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/action-plan', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customer_care_action_plan(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_action_plan,
            payload=self._get_optional_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/auto-run', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_customer_care_auto_run(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_auto_run,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/auto-run/runs', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_customer_care_auto_run_runs(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_auto_run_runs,
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/customer-care/auto-run/runs/<int:run_id>', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_customer_care_auto_run_report(self, run_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_customer_care_auto_run_report,
            run_id,
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_list_orders(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_orders, **kwargs)

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_order_detail(self, order_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_order_detail, order_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/orders', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_create_order(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_create,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>', type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_update_order(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_update,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/confirm-info', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_confirm_info(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_confirm_info,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/proceed-to-production', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_proceed_to_production(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_proceed_to_production,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/proceed-to-delivery', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_proceed_to_delivery(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_proceed_to_delivery,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/proceed-to-installation', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_proceed_to_installation(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_proceed_to_installation,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/create-deposit-invoice', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_create_deposit_invoice(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_create_deposit_invoice,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/create-final-invoice', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_create_final_invoice(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_create_final_invoice,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/confirm-deposit-invoice', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_confirm_deposit_invoice(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_confirm_deposit_invoice,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/orders/<int:order_id>/actions/confirm-final-payment', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_order_confirm_final_payment(self, order_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_order_confirm_final_payment,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/orders', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_conversation_orders(self, conversation_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_conversation_orders, conversation_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/ai-summary', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_conversation_ai_summary(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_ai_summary,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/ai-note', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_conversation_ai_note(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_ai_note,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/activities', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_conversation_activity(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_activity,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/triage', type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_conversation_triage(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_triage,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    # ══════════════════════════════════════════════════════════════════
    # Task API — relation resolvers
    # ══════════════════════════════════════════════════════════════════

    def _resolve_task_order_id(self, env, value):
        """Chấp nhận DB id (int) hoặc order name (str như 'DAC00123')."""
        if isinstance(value, int):
            order = env['sale.order'].sudo().browse(value)
            if not order.exists():
                raise ValueError("Không tìm thấy sale.order id=%s" % value)
            return order.id
        if isinstance(value, str):
            order = env['sale.order'].sudo().search([('name', '=', value)], limit=1)
            if not order:
                raise ValueError("Không tìm thấy sale.order name='%s'" % value)
            return order.id
        raise ValueError("order_id phải là int hoặc str, nhận được: %r" % type(value).__name__)

    def _resolve_task_conversation_id(self, env, value):
        """Chấp nhận DB id (int) hoặc conversation_fm_id (str)."""
        if isinstance(value, int):
            conv = env['page.fm.conversation'].sudo().browse(value)
            if not conv.exists():
                raise ValueError("Không tìm thấy page.fm.conversation id=%s" % value)
            return conv.id
        if isinstance(value, str):
            conv = env['page.fm.conversation'].sudo().search(
                [('conversation_fm_id', '=', value)], limit=1
            )
            if not conv:
                raise ValueError("Không tìm thấy page.fm.conversation conversation_fm_id='%s'" % value)
            return conv.id
        raise ValueError("conversation_id phải là int hoặc str, nhận được: %r" % type(value).__name__)

    def _resolve_task_assigned_user_id(self, env, value):
        """Chấp nhận DB id (int), login email (str), hoặc pancake_id (str)."""
        if isinstance(value, int):
            user = env['res.users'].sudo().browse(value)
            if not user.exists():
                raise ValueError("Không tìm thấy res.users id=%s" % value)
            return user.id
        if isinstance(value, str):
            user = env['res.users'].sudo().search([('login', '=', value)], limit=1)
            if not user:
                # thử pancake_id nếu model có field đó
                user = env['res.users'].sudo().search(
                    [('pancake_id', '=', value)], limit=1
                )
            if not user:
                raise ValueError("Không tìm thấy res.users với login/pancake_id='%s'" % value)
            return user.id
        raise ValueError("assigned_user_id phải là int hoặc str, nhận được: %r" % type(value).__name__)

    # ══════════════════════════════════════════════════════════════════
    # Task API — normalize payloads
    # ══════════════════════════════════════════════════════════════════

    def _normalize_mcp_task_create_payload(self, payload, env):
        payload = self._get_v3_json_payload(payload=payload)
        unknown = sorted(set(payload) - self.MCP_TASK_CREATE_FIELDS)
        if unknown:
            raise ValueError("Trường không được phép: %s" % ', '.join(unknown))

        name = payload.get('name')
        if not name or not str(name).strip():
            raise ValueError("'name' là bắt buộc và không được để trống")

        order_raw = payload.get('order_id')
        conversation_raw = payload.get('conversation_id')
        if order_raw is None and conversation_raw is None:
            raise ValueError("Phải cung cấp ít nhất 'order_id' hoặc 'conversation_id'")

        vals = {'name': str(name).strip()}

        if order_raw is not None:
            vals['order_id'] = self._resolve_task_order_id(env, order_raw)
        if conversation_raw is not None:
            vals['conversation_id'] = self._resolve_task_conversation_id(env, conversation_raw)

        if payload.get('description') is not None:
            vals['description'] = str(payload['description'])
        if payload.get('notes') is not None:
            vals['notes'] = str(payload['notes'])
        if payload.get('priority') is not None:
            allowed_priorities = {'normal', 'high', 'urgent'}
            p = str(payload['priority'])
            if p not in allowed_priorities:
                raise ValueError("priority phải là: %s" % ', '.join(sorted(allowed_priorities)))
            vals['priority'] = p
        if payload.get('deadline') is not None:
            vals['deadline'] = payload['deadline']
        if payload.get('remind_at') is not None:
            vals['remind_at'] = payload['remind_at']
        if payload.get('assigned_user_id') is not None:
            vals['assigned_user_id'] = self._resolve_task_assigned_user_id(env, payload['assigned_user_id'])

        metadata = {
            'request_id': payload.get('request_id'),
            'agent_name': payload.get('agent_name'),
        }
        return vals, metadata

    def _normalize_mcp_task_update_payload(self, payload, env):
        payload = self._get_v3_json_payload(payload=payload)
        unknown = sorted(set(payload) - self.MCP_TASK_UPDATE_FIELDS)
        if unknown:
            raise ValueError("Trường không được phép: %s" % ', '.join(unknown))

        vals = {}
        if payload.get('name') is not None:
            vals['name'] = str(payload['name']).strip()
            if not vals['name']:
                raise ValueError("'name' không được để trống")
        if payload.get('description') is not None:
            vals['description'] = str(payload['description'])
        if payload.get('notes') is not None:
            vals['notes'] = str(payload['notes'])
        if payload.get('priority') is not None:
            allowed = {'normal', 'high', 'urgent'}
            p = str(payload['priority'])
            if p not in allowed:
                raise ValueError("priority phải là: %s" % ', '.join(sorted(allowed)))
            vals['priority'] = p
        if payload.get('state') is not None:
            allowed_states = {'draft', 'in_progress', 'done', 'cancelled'}
            s = str(payload['state'])
            if s not in allowed_states:
                raise ValueError("state phải là: %s" % ', '.join(sorted(allowed_states)))
            vals['state'] = s
        if payload.get('deadline') is not None:
            vals['deadline'] = payload['deadline']
        if payload.get('remind_at') is not None:
            vals['remind_at'] = payload['remind_at']
        if payload.get('assigned_user_id') is not None:
            vals['assigned_user_id'] = self._resolve_task_assigned_user_id(env, payload['assigned_user_id'])

        metadata = {
            'request_id': payload.get('request_id'),
            'agent_name': payload.get('agent_name'),
        }
        return vals, metadata

    # ══════════════════════════════════════════════════════════════════
    # Task API — serializer
    # ══════════════════════════════════════════════════════════════════

    def _serialize_mcp_task(self, task):
        # conversation_id → page.fm.conversation is not in dac_erp's dependency chain.
        # Both ORM and record.read() fail when comodel is _unknown, so we read the raw
        # FK integer directly from the database cursor.
        task.env.cr.execute(
            'SELECT conversation_id FROM dac_work_task WHERE id = %s', [task.id]
        )
        row = task.env.cr.fetchone()
        conv_id = row[0] if row and row[0] else None

        return {
            'id': task.id,
            'name': task.name,
            'description': task.description or None,
            'state': task.state,
            'priority': task.priority,
            'deadline': task.deadline.isoformat() if task.deadline else None,
            'remind_at': task.remind_at.isoformat() if task.remind_at else None,
            'order_id': task.order_id.id if task.order_id else None,
            'order_name': task.order_id.name if task.order_id else None,
            'conversation_id': conv_id,
            'assigned_user_id': task.assigned_user_id.id if task.assigned_user_id else None,
            'assigned_user_name': task.assigned_user_id.name if task.assigned_user_id else None,
            'created_by_agent': task.created_by_agent or None,
            'notes': task.notes or None,
            'create_date': task.create_date.isoformat() if task.create_date else None,
            'write_date': task.write_date.isoformat() if task.write_date else None,
        }

    # ══════════════════════════════════════════════════════════════════
    # Task API — log helper
    # ══════════════════════════════════════════════════════════════════

    def _create_mcp_task_log(self, env, action_type, request_id, agent_name,
                              payload_json, response_data, task=None, status='success',
                              error_message=None):
        import json as _json
        vals = {
            'action_type': action_type,
            'request_id': request_id,
            'agent_name': agent_name or '',
            'payload_json': payload_json if isinstance(payload_json, str)
                            else _json.dumps(payload_json, ensure_ascii=False, default=str),
            'response_json': _json.dumps(response_data, ensure_ascii=False, default=str),
            'status': status,
        }
        if task:
            vals['task_id'] = task.id
        if error_message:
            vals['error_message'] = error_message
        try:
            return env[self.MCP_TASK_LOG_MODEL].sudo().create(vals)
        except Exception as exc:
            _logger.warning("Không thể tạo MCP task log: %s", exc)
            return None

    def _check_mcp_task_log_replay(self, env, request_id):
        """Trả về (response_dict, True) nếu request_id đã tồn tại; (None, False) nếu chưa."""
        if not request_id:
            return None, False
        import json as _json
        existing = env[self.MCP_TASK_LOG_MODEL].sudo().search(
            [('request_id', '=', request_id)], limit=1
        )
        if existing:
            try:
                return _json.loads(existing.response_json or '{}'), True
            except Exception:
                return {}, True
        return None, False

    # ══════════════════════════════════════════════════════════════════
    # Task API — action handler
    # ══════════════════════════════════════════════════════════════════

    def _run_mcp_task_action(self, action_type, payload, env, task_id=None):
        import json as _json

        if action_type == 'task_create':
            vals, meta = self._normalize_mcp_task_create_payload(payload, env)
            request_id = meta.get('request_id')
            agent_name = meta.get('agent_name') or ''

            # Idempotency check
            cached, is_replay = self._check_mcp_task_log_replay(env, request_id)
            if is_replay:
                response = dict(cached)
                response['_replayed'] = True
                return response

            if agent_name:
                vals['created_by_agent'] = agent_name

            task = env['dac.work.task'].sudo().create(vals)

            response_data = self._serialize_mcp_task(task)
            payload_str = _json.dumps(payload, ensure_ascii=False, default=str) \
                          if not isinstance(payload, str) else payload
            self._create_mcp_task_log(
                env, action_type, request_id, agent_name,
                payload_str, response_data, task=task, status='success',
            )
            return response_data

        elif action_type == 'task_update':
            if not task_id:
                raise ValueError("task_id là bắt buộc cho task_update")

            task = env['dac.work.task'].sudo().browse(task_id)
            if not task.exists():
                raise McpHttpError(404, 'task_not_found', "Không tìm thấy task id=%s" % task_id)

            vals, meta = self._normalize_mcp_task_update_payload(payload, env)
            request_id = meta.get('request_id')
            agent_name = meta.get('agent_name') or ''

            # Idempotency check
            cached, is_replay = self._check_mcp_task_log_replay(env, request_id)
            if is_replay:
                response = dict(cached)
                response['_replayed'] = True
                return response

            # Không cho update task đã đóng
            if task.state in self.MCP_TASK_BLOCKED_STATES:
                raise McpHttpError(
                    400, 'task_state_blocked',
                    "Không thể cập nhật task đang ở trạng thái '%s'" % task.state,
                )

            if not vals:
                raise ValueError("Không có trường nào để cập nhật")

            task.write(vals)

            response_data = self._serialize_mcp_task(task)
            payload_str = _json.dumps(payload, ensure_ascii=False, default=str) \
                          if not isinstance(payload, str) else payload
            self._create_mcp_task_log(
                env, action_type, request_id, agent_name,
                payload_str, response_data, task=task, status='success',
            )
            return response_data

        else:
            raise ValueError("action_type không hợp lệ: %s" % action_type)

    # ══════════════════════════════════════════════════════════════════
    # Task API — dispatch methods
    # ══════════════════════════════════════════════════════════════════

    def _dispatch_mcp_task_list(self, env=None, headers=None, provided_key=None, **params):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)

        domain = self._build_task_domain_from_filters(params)

        try:
            limit = min(int(params.get('limit', 50)), 100)
            offset = int(params.get('offset', 0))
        except (TypeError, ValueError):
            limit, offset = 50, 0

        tasks = env['dac.work.task'].sudo().search(domain, limit=limit, offset=offset)
        total = env['dac.work.task'].sudo().search_count(domain)
        items = [self._serialize_mcp_task(t) for t in tasks]
        return self._mcp_list_payload(items, total), 200

    def _build_task_domain_from_filters(self, params):
        domain = []
        order_id_param = params.get('order_id')
        conversation_id_param = params.get('conversation_id')
        state_param = params.get('state')
        assigned_user_id_param = params.get('assigned_user_id')
        priority_param = params.get('priority')
        deadline_before_param = params.get('deadline_before')
        deadline_after_param = params.get('deadline_after')
        overdue_raw = params.get('overdue', '')
        overdue_param = str(overdue_raw).lower() in ('1', 'true', 'yes')

        if order_id_param:
            try:
                domain.append(('order_id', '=', int(order_id_param)))
            except (TypeError, ValueError):
                raise ValueError('order_id phải là integer')
        if conversation_id_param:
            try:
                domain.append(('conversation_id', '=', int(conversation_id_param)))
            except (TypeError, ValueError):
                raise ValueError('conversation_id phải là integer')
        if state_param:
            allowed_states = {'draft', 'in_progress', 'done', 'cancelled'}
            if state_param not in allowed_states:
                raise ValueError("state phải là: %s" % ', '.join(sorted(allowed_states)))
            domain.append(('state', '=', state_param))
        if assigned_user_id_param:
            try:
                domain.append(('assigned_user_id', '=', int(assigned_user_id_param)))
            except (TypeError, ValueError):
                raise ValueError('assigned_user_id phải là integer')
        if priority_param:
            allowed_priorities = {'normal', 'high', 'urgent'}
            if priority_param not in allowed_priorities:
                raise ValueError("priority phải là: %s" % ', '.join(sorted(allowed_priorities)))
            domain.append(('priority', '=', priority_param))
        if deadline_before_param:
            try:
                dt = datetime.fromisoformat(str(deadline_before_param).replace('Z', '+00:00'))
                domain.append(('deadline', '<=', dt.strftime('%Y-%m-%d %H:%M:%S')))
            except ValueError:
                raise ValueError('deadline_before phải là ISO 8601 (YYYY-MM-DD hoặc YYYY-MM-DDTHH:MM:SS)')
        if deadline_after_param:
            try:
                dt = datetime.fromisoformat(str(deadline_after_param).replace('Z', '+00:00'))
                domain.append(('deadline', '>=', dt.strftime('%Y-%m-%d %H:%M:%S')))
            except ValueError:
                raise ValueError('deadline_after phải là ISO 8601 (YYYY-MM-DD hoặc YYYY-MM-DDTHH:MM:SS)')
        if overdue_param:
            now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            domain += [
                ('deadline', '!=', False),
                ('deadline', '<', now_str),
                ('state', 'not in', ['done', 'cancelled']),
            ]
        return domain

    def _resolve_openclaw_mapping(self, env, payload):
        payload = self._get_v3_json_payload(payload=payload)
        channel = (payload.get('channel') or '').strip()
        target = (payload.get('target') or '').strip()
        if not channel or not target:
            raise ValueError('channel và target là bắt buộc')
        mappings = env[self.MCP_OPENCLAW_MAPPING_MODEL].sudo().search([
            ('channel', '=', channel),
            ('target', '=', target),
            ('active', '=', True),
        ])
        if not mappings:
            raise McpHttpError(404, 'user_mapping_not_found', 'Không tìm thấy mapping OpenClaw phù hợp')
        if len(mappings) > 1:
            raise McpHttpError(409, 'duplicate_user_mapping', 'Có nhiều mapping cho cùng channel/target')
        return mappings[0]

    def _serialize_openclaw_mapping(self, mapping):
        return {
            'user': {
                'id': mapping.user_id.id,
                'name': mapping.user_id.name,
                'login': mapping.user_id.login,
            },
            'role': mapping.role,
            'notification': {
                'channel': mapping.channel,
                'target': mapping.target,
                'notify_enabled': mapping.notify_enabled,
                'digest_enabled': mapping.digest_enabled,
                'deadline_enabled': mapping.deadline_enabled,
            },
            'manager_scope': {
                'user_ids': mapping.manager_user_ids.ids,
            },
        }

    def _get_openclaw_scope_user_ids(self, mapping, include_self=True):
        if mapping.role == 'admin':
            return None
        if mapping.role == 'manager':
            user_ids = set(mapping.manager_user_ids.ids)
            if include_self and mapping.user_id:
                user_ids.add(mapping.user_id.id)
            return sorted(user_ids)
        return [mapping.user_id.id] if mapping.user_id else []

    def _resolve_openclaw_employee_user(self, env, employee_payload):
        employee_payload = employee_payload or {}
        user_id = employee_payload.get('user_id')
        login = employee_payload.get('login')
        target = employee_payload.get('target')
        if user_id:
            user = env['res.users'].sudo().browse(int(user_id))
            if user.exists():
                return user
        if login:
            user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
            if user:
                return user
        if target:
            mapping = env[self.MCP_OPENCLAW_MAPPING_MODEL].sudo().search([
                ('target', '=', target),
                ('active', '=', True),
            ], limit=1)
            if mapping:
                return mapping.user_id
        raise McpHttpError(404, 'employee_not_found', 'Không tìm thấy nhân viên cần tra cứu')

    def _dispatch_openclaw_resolve_user(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        mapping = self._resolve_openclaw_mapping(env, payload)
        return self._mcp_detail_payload(self._serialize_openclaw_mapping(mapping)), 200

    def _dispatch_openclaw_tasks_self(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        payload = self._get_v3_json_payload(payload=payload)
        mapping = self._resolve_openclaw_mapping(env, payload)
        filters = dict(payload.get('filters') or {})
        filters['assigned_user_id'] = mapping.user_id.id
        domain = self._build_task_domain_from_filters(filters)
        tasks = env['dac.work.task'].sudo().search(domain, limit=min(int(filters.get('limit', 50)), 100), offset=int(filters.get('offset', 0)))
        total = env['dac.work.task'].sudo().search_count(domain)
        items = [self._serialize_mcp_task(t) for t in tasks]
        return self._mcp_list_payload(items, total), 200

    def _dispatch_openclaw_tasks_employee(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        payload = self._get_v3_json_payload(payload=payload)
        mapping = self._resolve_openclaw_mapping(env, payload)
        if mapping.role not in ('manager', 'admin'):
            raise McpHttpError(403, 'insufficient_scope', 'Bạn không có quyền xem task nhân viên khác')
        employee_user = self._resolve_openclaw_employee_user(env, payload.get('employee'))
        scope_user_ids = self._get_openclaw_scope_user_ids(mapping, include_self=True)
        if scope_user_ids is not None and employee_user.id not in scope_user_ids:
            raise McpHttpError(403, 'insufficient_scope', 'Nhân viên nằm ngoài phạm vi quản lý')
        filters = dict(payload.get('filters') or {})
        filters['assigned_user_id'] = employee_user.id
        domain = self._build_task_domain_from_filters(filters)
        tasks = env['dac.work.task'].sudo().search(domain, limit=min(int(filters.get('limit', 50)), 100), offset=int(filters.get('offset', 0)))
        total = env['dac.work.task'].sudo().search_count(domain)
        items = [self._serialize_mcp_task(t) for t in tasks]
        return self._mcp_list_payload(items, total), 200

    def _dispatch_openclaw_team_summary(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        payload = self._get_v3_json_payload(payload=payload)
        mapping = self._resolve_openclaw_mapping(env, payload)
        if mapping.role not in ('manager', 'admin'):
            raise McpHttpError(403, 'insufficient_scope', 'Bạn không có quyền xem team summary')
        filters = dict(payload.get('filters') or {})
        domain = self._build_task_domain_from_filters(filters)
        scope_user_ids = self._get_openclaw_scope_user_ids(mapping, include_self=False)
        if scope_user_ids is not None:
            domain.append(('assigned_user_id', 'in', scope_user_ids))
        tasks = env['dac.work.task'].sudo().search(domain)
        by_user = []
        for user in tasks.mapped('assigned_user_id'):
            user_tasks = tasks.filtered(lambda t: t.assigned_user_id.id == user.id)
            by_user.append({
                'user_id': user.id,
                'user_name': user.name,
                'total': len(user_tasks),
                'overdue': len(user_tasks.filtered(lambda t: t.deadline and t.deadline < fields.Datetime.now() and t.state not in ['done', 'cancelled'])),
                'urgent': len(user_tasks.filtered(lambda t: t.priority == 'urgent')),
            })
        summary = {
            'total': len(tasks),
            'overdue': len(tasks.filtered(lambda t: t.deadline and t.deadline < fields.Datetime.now() and t.state not in ['done', 'cancelled'])),
            'urgent': len(tasks.filtered(lambda t: t.priority == 'urgent')),
            'by_state': {
                'draft': len(tasks.filtered(lambda t: t.state == 'draft')),
                'in_progress': len(tasks.filtered(lambda t: t.state == 'in_progress')),
                'done': len(tasks.filtered(lambda t: t.state == 'done')),
                'cancelled': len(tasks.filtered(lambda t: t.state == 'cancelled')),
            },
            'by_user': by_user,
        }
        return self._mcp_detail_payload({
            'summary': summary,
            'scope': {
                'manager_user_id': mapping.user_id.id,
                'user_ids': scope_user_ids or [],
            },
        }), 200

    def _dispatch_mcp_task_get(self, task_id, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)
        task = env['dac.work.task'].sudo().browse(task_id)
        if not task.exists():
            raise McpHttpError(404, 'task_not_found', "Không tìm thấy task id=%s" % task_id)
        return self._mcp_detail_payload(self._serialize_mcp_task(task)), 200

    def _dispatch_mcp_task_create(self, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_task_action(
            action_type='task_create', payload=payload, env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    def _dispatch_mcp_task_update(self, task_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_task_action(
            action_type='task_update', payload=payload, env=env, task_id=task_id,
        )
        return self._mcp_detail_payload(response_data), 200

    # ══════════════════════════════════════════════════════════════════
    # Task API — routes
    # ══════════════════════════════════════════════════════════════════

    @http.route('/dac_erp/mcp/v1/tasks', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_list_tasks(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_task_list, **kwargs)

    @http.route('/dac_erp/mcp/v1/tasks', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_create_task(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_task_create,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/tasks/<int:task_id>', type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_get_task(self, task_id, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_task_get, task_id, **kwargs)

    @http.route('/dac_erp/mcp/v1/tasks/<int:task_id>', type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_update_task(self, task_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_task_update,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/openclaw/resolve-user', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_openclaw_resolve_user(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_openclaw_resolve_user,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/openclaw/tasks/self', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_openclaw_tasks_self(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_openclaw_tasks_self,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/openclaw/tasks/employee', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_openclaw_tasks_employee(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_openclaw_tasks_employee,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v1/openclaw/tasks/team-summary', type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_openclaw_team_summary(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_openclaw_team_summary,
            payload=self._get_v3_json_payload(),
            **kwargs
        )
