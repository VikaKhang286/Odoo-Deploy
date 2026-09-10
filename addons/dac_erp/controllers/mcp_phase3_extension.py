# -*- coding: utf-8 -*-
"""MCP Phase 3 — outbound message send to Pancake/Page.fm.

Route mới:
  POST /dac_erp/mcp/v1/conversations/<int:conversation_id>/send-message
  Header: X-MCP-API-KEY (write key)
  Body:
    {
      "text": "Xin chào ...",          // required
      "attachment_urls": [],            // optional list
      "via": "auto",                    // optional, info-only (Pancake routes)
      "request_id": "uuid",             // required — idempotency
      "agent_name": "OpenClaw",         // required
      "model_name": "...",              // optional
      "reason": "..."                   // optional
    }

Tin gửi qua Pancake API. Log vào `dac_erp.mcp.conversation.message.log` cho audit.
"""
import json
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import pancake_messaging
from .mcp import McpHttpError, MCPReadController


_logger = logging.getLogger(__name__)


class MCPPhase3ExtensionController(MCPReadController):
    """Phase 3: send-message route."""

    MCP_MSG_LOG_MODEL = 'dac_erp.mcp.conversation.message.log'
    MCP_MSG_SEND_FIELDS = {
        'text', 'attachment_urls', 'via',
        'request_id', 'agent_name', 'model_name', 'reason',
    }
    MCP_MSG_VIA_ALLOWED = {'auto', 'zalo', 'facebook', 'instagram'}

    def _normalize_mcp_send_message_payload(self, payload):
        payload = self._get_v3_json_payload(payload=payload)
        unknown = sorted(set(payload) - self.MCP_MSG_SEND_FIELDS)
        if unknown:
            raise ValueError("Trường không được phép: %s" % ', '.join(unknown))

        if 'request_id' not in payload or not isinstance(payload.get('request_id'), str) \
                or not payload.get('request_id').strip():
            raise ValueError("request_id is required")
        if 'agent_name' not in payload or not isinstance(payload.get('agent_name'), str) \
                or not payload.get('agent_name').strip():
            raise ValueError("agent_name is required")

        text = payload.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required")

        attachment_urls = payload.get('attachment_urls') or []
        if attachment_urls and not isinstance(attachment_urls, list):
            raise ValueError("attachment_urls must be a list")
        for idx, url in enumerate(attachment_urls):
            if not isinstance(url, str) or not url.strip():
                raise ValueError("attachment_urls[%s] must be a non-empty string" % idx)

        via = payload.get('via') or 'auto'
        if not isinstance(via, str) or via not in self.MCP_MSG_VIA_ALLOWED:
            raise ValueError("via must be one of: %s" % ', '.join(sorted(self.MCP_MSG_VIA_ALLOWED)))

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
            'text': text.strip(),
            'attachment_urls': [u.strip() for u in attachment_urls],
            'via': via,
            'request_id': payload['request_id'].strip(),
            'agent_name': payload['agent_name'].strip(),
            'model_name': model_name or False,
            'reason': reason,
        }

    def _check_msg_log_replay(self, env, request_id, payload_fingerprint):
        log_record = env[self.MCP_MSG_LOG_MODEL].sudo().search(
            [('request_id', '=', request_id)], limit=1)
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise McpHttpError(
                409,
                'conflict',
                'request_id was already used with a different payload',
                details={'request_id': request_id},
            )
        return log_record

    def _build_msg_replayed_response(self, log_record):
        try:
            data = json.loads(log_record.response_snapshot_json) if log_record.response_snapshot_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        # conversation_id Many2one comodel page.fm.conversation có thể _unknown
        # khi dac_erp load mà chưa có CRM_DAC. Đọc raw FK qua SQL để tránh AttributeError.
        log_record.env.cr.execute(
            'SELECT conversation_id FROM dac_erp_mcp_conversation_message_log WHERE id = %s',
            [log_record.id],
        )
        row = log_record.env.cr.fetchone()
        conv_fk = row[0] if row and row[0] else None
        if conv_fk:
            data['conversation_id'] = conv_fk
        data['log_id'] = log_record.id
        data['idempotent_replay'] = True
        return data

    def _run_mcp_send_message_action(self, conversation_id, payload=None, env=None):
        env = self._get_env(env)
        conversation = env['page.fm.conversation'].sudo().browse(int(conversation_id))
        if not conversation.exists():
            raise McpHttpError(404, 'not_found', 'Conversation not found')

        try:
            normalized = self._normalize_mcp_send_message_payload(payload)
        except ValueError as exc:
            raise McpHttpError(400, 'validation_error', str(exc))

        payload_fingerprint = self._compute_payload_fingerprint(normalized)
        existing_log = self._check_msg_log_replay(
            env=env,
            request_id=normalized['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            return self._build_msg_replayed_response(existing_log)

        # Gọi Pancake API
        result = pancake_messaging.send_pancake_message(
            env=env,
            conversation=conversation,
            text=normalized['text'],
            attachment_urls=normalized['attachment_urls'] or None,
        )

        text_preview = normalized['text'][:200]
        common_log_vals = {
            'conversation_id': conversation.id,
            'action_type': 'message_send',
            'request_id': normalized['request_id'],
            'request_payload_json': self._dump_json_text(normalized),
            'payload_fingerprint': payload_fingerprint,
            'text_preview': text_preview,
            'via_channel': normalized['via'],
            'agent_name': normalized['agent_name'],
            'model_name': normalized['model_name'] or False,
            'reason': normalized['reason'] or False,
        }

        if not result.get('ok'):
            err_code = result.get('error_code') or 'pancake_api_error'
            err_msg = result.get('error_message') or 'Unknown error'
            log_record = env[self.MCP_MSG_LOG_MODEL].sudo().create({
                **common_log_vals,
                'status': 'failed',
                'pancake_http_status': result.get('http_status') or False,
                'response_snapshot_json': self._dump_json_text(result),
                'error_code': err_code,
                'error_message': err_msg,
            })
            # Phân loại lỗi để OpenClaw biết retry hay không
            if err_code == 'token_not_configured':
                raise McpHttpError(503, 'config_missing', err_msg)
            if err_code in ('invalid_conversation', 'invalid_text', 'invalid_attachments',
                            'missing_external_ids'):
                raise McpHttpError(400, 'validation_error', err_msg)
            # network_error / pancake_api_error → 502 (downstream)
            raise McpHttpError(502, err_code, err_msg,
                               details={'log_id': log_record.id,
                                        'http_status': result.get('http_status')})

        # Success
        response_data = {
            'conversation_id': conversation.id,
            'action': 'message_send',
            'pancake_message_id': result.get('message_id'),
            'pancake_http_status': result.get('http_status'),
            'text_preview': text_preview,
            'via': normalized['via'],
            'idempotent_replay': False,
        }
        log_record = env[self.MCP_MSG_LOG_MODEL].sudo().create({
            **common_log_vals,
            'status': 'success',
            'pancake_message_id': result.get('message_id') or False,
            'pancake_http_status': result.get('http_status') or False,
            'response_snapshot_json': self._dump_json_text(response_data),
        })
        response_data['log_id'] = log_record.id
        log_record.sudo().write({'response_snapshot_json': self._dump_json_text(response_data)})
        return response_data

    def _dispatch_mcp_send_message(self, conversation_id, env=None, headers=None,
                                    provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, provided_key=provided_key, headers=headers)
        response_data = self._run_mcp_send_message_action(
            conversation_id=conversation_id, payload=payload, env=env,
        )
        return self._mcp_detail_payload(response_data), 200

    @http.route('/dac_erp/mcp/v1/conversations/<int:conversation_id>/send-message',
                type='http', auth='public', csrf=False, methods=['POST'])
    def mcp_conversation_send_message(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_send_message,
            conversation_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )
