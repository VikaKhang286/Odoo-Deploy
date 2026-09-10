# -*- coding: utf-8 -*-
"""MCP Tag Extension — AI Tag System v2

Adds three MCP-authenticated routes for OpenClaw to read/write Pancake tags
without touching raw /api/v3 endpoints directly.

Routes:
  GET  /dac_erp/mcp/v1/tags                              — list standard tags
  GET  /dac_erp/mcp/v1/conversations/<id>/tags           — read tags on a conversation
  PUT  /dac_erp/mcp/v1/conversations/<id>/tags           — set tags (dry_run=true by default)

Auth:
  GET routes accept readKey OR writeKey (X-MCP-API-KEY).
  PUT route requires writeKey only.

Safety:
  - PUT defaults to dry_run=true. Caller must pass dry_run=false AND --apply explicitly.
  - replace_all mode is BLOCKED. Only replace_ai_scope / add / remove allowed.
  - When dry_run=false: request_id, reason, and evidence (≥1 item) are required.
  - customer_vip (managed_by_ai=False) is never mutated by AI.
  - No API key is logged or returned in any response.
"""
import logging
import uuid as uuid_mod

from odoo import http
from odoo.http import request

from odoo.addons.dac_erp.controllers.mcp import MCPReadController, McpHttpError

_logger = logging.getLogger(__name__)


class McpTagExtension(MCPReadController):

    # ── A1: GET /dac_erp/mcp/v1/tags ─────────────────────────────────────────

    @http.route(
        '/dac_erp/mcp/v1/tags',
        type='http', auth='public', csrf=False, methods=['GET'],
    )
    def mcp_tags_list(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_mcp_tags_list, **kwargs)

    def _dispatch_mcp_tags_list(self, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)

        query_params = {}
        try:
            raw_h = request.httprequest
            query_params = dict(raw_h.args)
        except Exception:
            pass

        page_id_raw = query_params.get('page_id')
        scope = (query_params.get('scope') or '').strip()

        env_read = self._get_v3_write_env(env)
        Tag = env_read['page.fm.tag'].sudo()

        domain = [('active', '=', True)]
        if page_id_raw:
            try:
                domain.append(('page_id', '=', int(page_id_raw)))
            except (ValueError, TypeError) as exc:
                raise McpHttpError(400, 'invalid_page_id', 'page_id must be an integer') from exc
        if scope == 'ai_managed':
            domain.append(('managed_by_ai', '=', True))

        tags = Tag.search(domain, order='page_id, name')
        tag_list = [
            {
                'id': t.id,
                'page_id': t.page_id.id,
                'page_name': t.page_id.name,
                'tag_fm_id': t.tag_fm_id or False,
                'name': t.name,
                'odoo_tag_code': t.odoo_tag_code or False,
                'odoo_tag_label': t.odoo_tag_label or False,
                'managed_by_ai': bool(t.managed_by_ai),
                'fm_color_hex': t.fm_color_hex or False,
                'active': bool(t.active),
            }
            for t in tags
        ]
        return self._mcp_list_payload(tag_list, len(tag_list)), 200

    # ── A2: GET /dac_erp/mcp/v1/conversations/<id>/tags ──────────────────────

    @http.route(
        '/dac_erp/mcp/v1/conversations/<int:conversation_id>/tags',
        type='http', auth='public', csrf=False, methods=['GET'],
    )
    def mcp_conversation_tags_get(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_tags_get, conversation_id, **kwargs
        )

    def _dispatch_mcp_conversation_tags_get(self, conversation_id, env=None, headers=None, provided_key=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, provided_key=provided_key, headers=headers)

        env_read = self._get_v3_write_env(env)
        conversation = env_read['page.fm.conversation'].sudo().browse(int(conversation_id))
        if not conversation.exists():
            raise McpHttpError(404, 'not_found', 'Conversation %s not found' % conversation_id)

        tags = conversation.pancake_tag_ids
        tag_list = [
            {
                'id': t.id,
                'tag_fm_id': t.tag_fm_id or False,
                'name': t.name,
                'odoo_tag_code': t.odoo_tag_code or False,
                'managed_by_ai': bool(t.managed_by_ai),
                'active': bool(t.active),
            }
            for t in tags
        ]
        data = {
            'conversation_id': conversation_id,
            'tags': tag_list,
            'tags_count': len(tag_list),
        }
        return self._mcp_detail_payload(data), 200

    # ── A3: PUT /dac_erp/mcp/v1/conversations/<id>/tags ──────────────────────

    @http.route(
        '/dac_erp/mcp/v1/conversations/<int:conversation_id>/tags',
        type='http', auth='public', csrf=False, methods=['PUT'],
    )
    def mcp_conversation_tags_put(self, conversation_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_mcp_conversation_tags_put,
            conversation_id,
            payload=self._get_optional_v3_json_payload(),
            **kwargs,
        )

    def _normalize_mcp_tag_payload(self, raw_payload):
        """MCP-specific normalization for tag replace.

        Differences from v3 normalization:
        - dry_run defaults to True (not False)
        - request_id auto-generated for dry-run; required for apply
        - agent_name defaults to 'OpenClaw'
        - replace_all mode is BLOCKED
        - reason and evidence (≥1) required only when dry_run=False
        """
        # tag_codes — required
        tag_codes = raw_payload.get('tag_codes')
        if not isinstance(tag_codes, list):
            raise McpHttpError(400, 'invalid_request', 'tag_codes must be a list')
        cleaned_codes = []
        seen = set()
        for i, code in enumerate(tag_codes):
            if not isinstance(code, str) or not code.strip():
                raise McpHttpError(400, 'invalid_request', 'tag_codes[%s] must be a non-empty string' % i)
            c = code.strip()
            if c in seen:
                raise McpHttpError(400, 'invalid_request', 'tag_codes contains duplicate: %s' % c)
            seen.add(c)
            cleaned_codes.append(c)

        # mode — default replace_ai_scope; replace_all BLOCKED
        mode = raw_payload.get('mode', 'replace_ai_scope')
        if mode == 'replace_all':
            raise McpHttpError(
                400, 'unsafe_mode',
                'replace_all is not allowed via MCP. Use replace_ai_scope to safely '
                'replace only AI-managed tags while keeping manual/VIP tags intact.',
            )
        if mode not in ('replace_ai_scope', 'add', 'remove'):
            raise McpHttpError(400, 'invalid_request', 'mode must be one of replace_ai_scope, add, remove')

        # dry_run — DEFAULT TRUE (caller must explicitly pass false + use --apply in CLI)
        dry_run_raw = raw_payload.get('dry_run')
        if dry_run_raw is None:
            dry_run = True
        else:
            coerced = self._as_bool(dry_run_raw, 'dry_run')
            if coerced is None:
                raise McpHttpError(400, 'invalid_request', 'dry_run must be true or false')
            dry_run = bool(coerced)

        # request_id — required when apply; auto-generate for dry-run
        request_id = (raw_payload.get('request_id') or '').strip()
        generated_request_id = False
        if not request_id:
            if not dry_run:
                raise McpHttpError(
                    400, 'missing_request_id',
                    'request_id is required when dry_run=false. '
                    'Pass a stable UUID so the operation is idempotent.',
                )
            request_id = str(uuid_mod.uuid4())
            generated_request_id = True

        # agent_name — default 'OpenClaw'
        agent_name = (raw_payload.get('agent_name') or 'OpenClaw').strip() or 'OpenClaw'

        # reason — required when apply
        reason = (raw_payload.get('reason') or '').strip() or False
        if not dry_run and not reason:
            raise McpHttpError(
                400, 'missing_reason',
                'reason is required when dry_run=false. Document why the AI is applying these tags.',
            )

        # evidence — required (≥1 item) when apply
        evidence_raw = raw_payload.get('evidence') or []
        if not isinstance(evidence_raw, list):
            raise McpHttpError(400, 'invalid_request', 'evidence must be a list of strings')
        evidence = [str(e).strip() for e in evidence_raw if str(e).strip()]
        if not dry_run and len(evidence) == 0:
            raise McpHttpError(
                400, 'missing_evidence',
                'evidence must contain at least one item when dry_run=false. '
                'Provide supporting text from the conversation.',
            )

        # confidence
        confidence_raw = raw_payload.get('confidence')
        if confidence_raw not in (None, ''):
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError) as exc:
                raise McpHttpError(400, 'invalid_request', 'confidence must be a number between 0 and 1') from exc
            if confidence < 0 or confidence > 1:
                raise McpHttpError(400, 'invalid_request', 'confidence must be between 0 and 1')
        else:
            confidence = False

        # needs_review
        needs_review_raw = raw_payload.get('needs_review', False)
        if needs_review_raw not in (None, False):
            nr = self._as_bool(needs_review_raw, 'needs_review')
            if nr is None:
                raise McpHttpError(400, 'invalid_request', 'needs_review must be true or false')
            needs_review = bool(nr)
        else:
            needs_review = False

        # do_not_apply_reason
        do_not_apply_reason = (raw_payload.get('do_not_apply_reason') or '').strip() or False

        # model_name
        model_name = (raw_payload.get('model_name') or '').strip() or False

        return {
            'request_id': request_id,
            '_generated_request_id': generated_request_id,
            'agent_name': agent_name,
            'model_name': model_name,
            'tag_codes': cleaned_codes,
            'mode': mode,
            'dry_run': dry_run,
            'reason': reason,
            'evidence': evidence,
            'confidence': confidence,
            'needs_review': needs_review,
            'do_not_apply_reason': do_not_apply_reason,
        }

    def _dispatch_mcp_conversation_tags_put(self, conversation_id, env=None, headers=None, provided_key=None, payload=None, **params):
        del params
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(
            env=env,
            provided_key=provided_key,
            headers=headers,
            read_key_code='insufficient_permission',
            read_key_message='MCP write key required for tag mutation. Use the write key.',
        )

        raw_payload = payload or {}
        normalized = self._normalize_mcp_tag_payload(raw_payload)
        generated_request_id = normalized.pop('_generated_request_id', False)

        env_write = self._get_v3_write_env(env)
        conversation = env_write['page.fm.conversation'].sudo().browse(int(conversation_id))
        if not conversation.exists():
            raise McpHttpError(404, 'not_found', 'Conversation %s not found' % conversation_id)

        if normalized['dry_run']:
            # Dry-run: no logging, no idempotency, no Pancake sync
            result = self._replace_conversation_tags(env_write, conversation, normalized, None)
            response_data = result['data']
            if generated_request_id:
                response_data['generated_request_id'] = normalized['request_id']
            return self._mcp_detail_payload(response_data), result.get('status_code', 200)

        # Apply: idempotency check
        payload_fingerprint = self._compute_payload_fingerprint(normalized)
        existing_log = self._handle_idempotency_or_raise(
            env=env_write,
            request_id=normalized['request_id'],
            payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            response_data = self._build_replayed_response_data(existing_log, conversation)
            return self._mcp_detail_payload(response_data), 200

        result = self._replace_conversation_tags(env_write, conversation, normalized, payload_fingerprint)
        response_data = result['data']
        return self._mcp_detail_payload(response_data), result.get('status_code', 200)
