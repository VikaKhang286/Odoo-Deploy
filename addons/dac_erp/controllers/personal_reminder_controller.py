# -*- coding: utf-8 -*-
"""MCP endpoints for OpenClaw personal reminder chat flow.

CRUD route: POST /dac_erp/mcp/v1/personal-reminders
  Auth:  X-MCP-API-KEY (write key)
  Body:  {"action": "<action>", ...params}
  Actions: create | list_open | get_latest_open | complete | reschedule

Chat route: POST /dac_erp/mcp/v1/personal-reminders/chat
  Auth:  X-MCP-API-KEY (write key)
  Body:  {"user_id": int, "intent": str, "params": dict, "session_state": dict|null}
  Returns: {"ok": bool, "reply": str, "new_session_state": dict|null,
            "action_taken": str, "task": dict|null}
"""
import json
import logging

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.dac_erp.controllers.mcp import MCPReadController, McpHttpError

_logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({
    'create',
    'list_open',
    'get_latest_open',
    'complete',
    'reschedule',
})


class PersonalReminderController(MCPReadController):

    # ──────────────────────────────────────────────────────────────────
    # Route
    # ──────────────────────────────────────────────────────────────────

    @http.route(
        '/dac_erp/mcp/v1/personal-reminders',
        type='http',
        auth='public',
        csrf=False,
        methods=['POST'],
    )
    def mcp_personal_reminders(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_personal_reminders,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    # ──────────────────────────────────────────────────────────────────
    # Dispatcher
    # ──────────────────────────────────────────────────────────────────

    def _dispatch_personal_reminders(self, payload, env=None, headers=None, **kwargs):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, headers=headers)

        action = (payload.get('action') or '').strip()
        if not action:
            raise McpHttpError(400, 'missing_action', "Field 'action' is required")
        if action not in _VALID_ACTIONS:
            raise McpHttpError(
                400,
                'unknown_action',
                "Unknown action %r. Valid actions: %s" % (action, ', '.join(sorted(_VALID_ACTIONS))),
            )

        svc = env['dac.personal.reminder.service']

        if action == 'create':
            return self._pr_create(svc, payload)
        if action == 'list_open':
            return self._pr_list_open(svc, payload)
        if action == 'get_latest_open':
            return self._pr_get_latest_open(svc, payload)
        if action == 'complete':
            return self._pr_complete(svc, payload)
        if action == 'reschedule':
            return self._pr_reschedule(svc, payload)

    # ──────────────────────────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────────────────────────

    def _pr_create(self, svc, payload):
        user_id = payload.get('user_id')
        name = payload.get('name')
        remind_at = payload.get('remind_at')

        if not user_id:
            raise McpHttpError(400, 'missing_field', "Field 'user_id' is required")
        if not name or not str(name).strip():
            raise McpHttpError(400, 'missing_field', "Field 'name' is required")
        if remind_at is None:
            raise McpHttpError(400, 'missing_field', "Field 'remind_at' is required")

        result = svc.create_personal_reminder_task(
            user_id=int(user_id),
            name=str(name).strip(),
            remind_at=remind_at,
            deadline=payload.get('deadline'),
            notes=payload.get('notes'),
            source=payload.get('source', 'openclaw_chat'),
            channel=payload.get('channel'),
            target=payload.get('target'),
            order_id=payload.get('order_id'),
        )
        return self._mcp_detail_payload(result), 200

    def _pr_list_open(self, svc, payload):
        user_id = payload.get('user_id')
        if not user_id:
            raise McpHttpError(400, 'missing_field', "Field 'user_id' is required")

        limit = payload.get('limit', 5)
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            raise McpHttpError(400, 'invalid_field', "'limit' must be an integer")

        items = svc.find_recent_open_personal_tasks(user_id=int(user_id), limit=limit)
        return self._mcp_list_payload(items, len(items)), 200

    def _pr_get_latest_open(self, svc, payload):
        user_id = payload.get('user_id')
        if not user_id:
            raise McpHttpError(400, 'missing_field', "Field 'user_id' is required")

        task = svc.find_latest_open_personal_task(user_id=int(user_id))
        return self._mcp_detail_payload(task), 200

    def _pr_complete(self, svc, payload):
        task_id = payload.get('task_id')
        if not task_id:
            raise McpHttpError(400, 'missing_field', "Field 'task_id' is required")

        result = svc.complete_personal_reminder_task(
            task_id=int(task_id),
            user_id=payload.get('user_id'),
            completion_note=payload.get('completion_note'),
        )
        status = 200 if result.get('ok') else 409
        return self._mcp_detail_payload(result), status

    def _pr_reschedule(self, svc, payload):
        task_id = payload.get('task_id')
        new_remind_at = payload.get('new_remind_at')

        if not task_id:
            raise McpHttpError(400, 'missing_field', "Field 'task_id' is required")
        if new_remind_at is None:
            raise McpHttpError(400, 'missing_field', "Field 'new_remind_at' is required")

        result = svc.reschedule_personal_reminder_task(
            task_id=int(task_id),
            new_remind_at=new_remind_at,
            user_id=payload.get('user_id'),
            note=payload.get('note'),
        )
        status = 200 if result.get('ok') else 409
        return self._mcp_detail_payload(result), status

    # ──────────────────────────────────────────────────────────────────
    # Chat conversation route
    # ──────────────────────────────────────────────────────────────────

    @http.route(
        '/dac_erp/mcp/v1/personal-reminders/chat',
        type='http',
        auth='public',
        csrf=False,
        methods=['POST'],
    )
    def mcp_personal_reminders_chat(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_personal_reminders_chat,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    def _dispatch_personal_reminders_chat(self, payload, env=None, headers=None, **kwargs):
        from odoo.addons.dac_erp.services.personal_reminder_conversation_service import KNOWN_INTENTS

        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, headers=headers)

        user_id = payload.get('user_id')
        intent = (payload.get('intent') or '').strip()
        params = payload.get('params') or {}
        session_state = payload.get('session_state')

        if not user_id:
            raise McpHttpError(400, 'missing_field', "Field 'user_id' is required")
        if not intent:
            raise McpHttpError(400, 'missing_field', "Field 'intent' is required")
        if intent not in KNOWN_INTENTS:
            raise McpHttpError(
                400,
                'unknown_intent',
                "Unknown intent %r. Valid: %s" % (intent, ', '.join(sorted(KNOWN_INTENTS))),
            )
        if not isinstance(params, dict):
            raise McpHttpError(400, 'invalid_field', "Field 'params' must be a JSON object")

        svc = env['dac.personal.reminder.conversation.service']
        result = svc.handle_turn(
            user_id=int(user_id),
            intent=intent,
            params=params,
            session_state=session_state,
        )
        return result, 200
