# -*- coding: utf-8 -*-
"""MCP v2 standardization layer.

V2 mục tiêu:
1. Response format chuẩn `{success, data, error, meta}` với meta chứa trace_id, took_ms
2. Rate limiting per API key (token-bucket)
3. Backward compat: v2 routes wrap v1 dispatchers — không duplicate code

Cấu hình:
- ICP `dac_erp.mcp_rate_limit_enabled`     : 'true' để bật
- ICP `dac_erp.mcp_rate_limit_capacity`    : burst (default 60)
- ICP `dac_erp.mcp_rate_limit_refill_per_sec` : tốc độ refill (default 2 → 120/phút)

V2 routes hiện có (giai đoạn đầu — sẽ mở rộng dần):
  POST   /dac_erp/mcp/v2/orders/<id>/actions/cancel
  POST   /dac_erp/mcp/v2/customers
  PATCH  /dac_erp/mcp/v2/customers/<id>
  PATCH  /dac_erp/mcp/v2/conversations/<id>/assign
  POST   /dac_erp/mcp/v2/conversations/<id>/send-message
  GET    /dac_erp/mcp/v2/health

Mọi route còn lại của v1 vẫn dùng được như cũ.
"""
import json
import time
import uuid

from odoo import http
from odoo.http import request

from ..services import mcp_rate_limit
from .mcp import McpHttpError, _mcp_json_default
from .mcp_phase1_extension import MCPPhase1ExtensionController
from .mcp_phase3_extension import MCPPhase3ExtensionController
from .mcp_sprint1_dispatchers import MCPSprint1Controller


def _start_clock():
    return time.monotonic()


def _took_ms(start):
    return int((time.monotonic() - start) * 1000)


def _v2_detail(data, trace_id, took_ms):
    return {
        'ok': True,
        'data': data,
        '_envelope_type': 'detail',
        'meta': {'trace_id': trace_id, 'took_ms': took_ms},
    }


def _v2_list(items, count, total, trace_id, took_ms):
    return {
        'ok': True,
        'count': count,
        'total': total,
        'items': items,
        '_envelope_type': 'list',
        'meta': {'trace_id': trace_id, 'took_ms': took_ms},
    }


def _v2_error(code, message, trace_id, took_ms, details=None):
    err = {'code': code, 'message': message}
    if details:
        err['details'] = details
    return {
        'ok': False,
        'error': err,
        '_envelope_type': 'error',
        'meta': {'trace_id': trace_id, 'took_ms': took_ms},
    }


class MCPv2WrapperController(MCPSprint1Controller, MCPPhase1ExtensionController, MCPPhase3ExtensionController):
    """V2 layer — multiple-inherit từ Phase 1 + Phase 3 extension để có đủ dispatchers."""

    def _make_v2_response(self, data, status_code, trace_id, start_clock,
                          extra_headers=None):
        """Wrap dict thành v2 response. data = phần data hoặc error đã có sẵn."""
        took = _took_ms(start_clock)
        headers = {'Content-Type': 'application/json',
                   'X-MCP-Trace-Id': trace_id}
        if extra_headers:
            headers.update(extra_headers)
        return http.Response(
            json.dumps(data, ensure_ascii=False, default=_mcp_json_default),
            content_type='application/json',
            status=status_code,
            headers=list(headers.items()),
        )

    def _handle_v2(self, dispatcher, *args, **kwargs):
        """Run dispatcher, reformat to v2 envelope {ok, _envelope_type, meta}."""
        start = _start_clock()
        trace_id = (request.httprequest.headers.get('X-Trace-Id')
                    or str(uuid.uuid4()))
        env = request.env

        # Rate limit (chỉ áp dụng khi có api key)
        api_key = (request.httprequest.headers.get('X-MCP-API-KEY')
                   or request.httprequest.headers.get('x-mcp-api-key'))
        if api_key:
            try:
                allowed, retry_after = mcp_rate_limit.check_rate_limit(env, api_key)
            except Exception:
                allowed, retry_after = True, 0
            if not allowed:
                body = _v2_error(
                    'rate_limit_exceeded', 'Too many requests',
                    trace_id, _took_ms(start),
                    details={'retry_after': retry_after},
                )
                return self._make_v2_response(
                    body, 429, trace_id, start,
                    extra_headers={'Retry-After': str(retry_after)},
                )

        # Gọi v1 dispatcher
        try:
            payload, status_code = dispatcher(*args, **kwargs)
        except McpHttpError as exc:
            body = _v2_error(exc.code, exc.message, trace_id,
                             _took_ms(start), details=exc.details)
            return self._make_v2_response(body, exc.status_code, trace_id, start)
        except Exception as exc:
            body = _v2_error('internal_error', 'Internal server error',
                             trace_id, _took_ms(start),
                             details={'exception': str(exc)[:300]})
            return self._make_v2_response(body, 500, trace_id, start)

        took = _took_ms(start)

        if isinstance(payload, dict) and payload.get('ok') is True:
            if 'items' in payload:
                # List envelope: v1 returns {ok, count, total, items, _envelope_type}
                body = _v2_list(
                    items=payload.get('items', []),
                    count=payload.get('count', len(payload.get('items', []))),
                    total=payload.get('total', payload.get('count', 0)),
                    trace_id=trace_id,
                    took_ms=took,
                )
            else:
                # Detail envelope: v1 returns {ok, data, _envelope_type}
                body = _v2_detail(payload.get('data'), trace_id, took)
            return self._make_v2_response(body, status_code, trace_id, start)

        if isinstance(payload, dict) and payload.get('ok') is False:
            err = payload.get('error') or {}
            body = _v2_error(
                err.get('code') or 'unknown_error',
                err.get('message') or 'Unknown error',
                trace_id, took,
                details=err.get('details'),
            )
            return self._make_v2_response(body, status_code, trace_id, start)

        # Fallback: wrap nguyên thành detail
        body = _v2_detail(payload, trace_id, took)
        return self._make_v2_response(body, status_code, trace_id, start)

    # ─────────────────────────────────────────────────────────────────
    # V2 ROUTES
    # ─────────────────────────────────────────────────────────────────

    @http.route('/dac_erp/mcp/v2/health',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_health(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_health, **kwargs)

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/actions/cancel',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_order_cancel(self, order_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_order_cancel,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/actions/reopen',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_order_reopen(self, order_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_order_reopen,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/customers',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_customer_create(self, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_customer_create,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/customers/<int:partner_id>',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_v2_customer_update(self, partner_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_customer_update,
            partner_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/conversations/<int:conversation_id>/assign',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_v2_conversation_assign(self, conversation_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_conversation_assign,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/conversations/<int:conversation_id>/send-message',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_conversation_send_message(self, conversation_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_send_message,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_order_detail(self, order_id, **kwargs):
        return self._handle_v2(self._dispatch_mcp_order_detail, order_id, **kwargs)

    @http.route('/dac_erp/mcp/v2/orders',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_orders_list(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_orders, **kwargs)

    @http.route('/dac_erp/mcp/v2/conversations',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_conversations_list(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_conversations, **kwargs)

    @http.route('/dac_erp/mcp/v2/customers/search',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_customers_search(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_customers_search, **kwargs)

    @http.route('/dac_erp/mcp/v2/tasks',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_tasks_list(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_task_list, **kwargs)

    @http.route('/dac_erp/mcp/v2/tasks',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_tasks_create(self, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_task_create,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/tasks/<int:task_id>',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_task_get(self, task_id, **kwargs):
        return self._handle_v2(self._dispatch_mcp_task_get, task_id, **kwargs)

    @http.route('/dac_erp/mcp/v2/tasks/<int:task_id>',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_v2_task_update(self, task_id, **kwargs):
        return self._handle_v2(
            self._dispatch_mcp_task_update,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    @http.route('/dac_erp/mcp/v2/customer-care/queue',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_customer_care_queue(self, **kwargs):
        return self._handle_v2(self._dispatch_mcp_customer_care_queue, **kwargs)

    # ── Sprint 1 v2 routes ────────────────────────────────────────────

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/task-context',
                type='http', auth='public', csrf=False, methods=['GET'])
    def mcp_v2_s1_order_task_context(self, order_id, **kwargs):
        return self._handle_v2(self._dispatch_s1_order_task_context, order_id, **kwargs)

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/assign-designer',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_s1_order_assign_designer(self, order_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_order_assign_designer,
            order_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/ensure-design-task',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_s1_order_ensure_design_task(self, order_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_order_ensure_task,
            order_id,
            'design',
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v2/orders/<int:order_id>/ensure-production-task',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_s1_order_ensure_production_task(self, order_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_order_ensure_task,
            order_id,
            'production',
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v2/tasks/<int:task_id>/status',
                type='http', auth='public', csrf=False, methods=['PATCH'])
    def mcp_v2_s1_task_status(self, task_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_task_status,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v2/tasks/<int:task_id>/note',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_s1_task_note(self, task_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_task_note,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )

    @http.route('/dac_erp/mcp/v2/tasks/<int:task_id>/blocker',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_v2_s1_task_blocker(self, task_id, **kwargs):
        return self._handle_v2(
            self._dispatch_s1_task_blocker,
            task_id,
            payload=self._get_v3_json_payload(),
            **kwargs,
        )
