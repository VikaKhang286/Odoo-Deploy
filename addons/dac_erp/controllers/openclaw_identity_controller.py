# -*- coding: utf-8 -*-
"""MCP endpoint: resolve internal recipient identity (channel + target → Odoo staff user).

Resolves which INTERNAL STAFF MEMBER owns a given personal messaging account
(e.g. Zalo personal of Dương Tuấn Kiệt) so OpenClaw knows the Odoo user_id
when routing personal reminder replies.

NOT for customer/Pancake/Page.fm conversation mapping.

Route: POST /dac_erp/mcp/v1/openclaw/resolve-internal-recipient
Auth:  X-MCP-API-KEY (write key)
Body:  {"channel": "zalouser", "target": "3360952219918690445"}

Response (found):
  {"ok": true, "data": {"found": true, "user_id": 10, "user_name": "Dương Tuấn Kiệt",
                        "role": "employee", "mapping_id": 3,
                        "channel": "zalouser", "target": "3360952219918690445"}}
Response (not found):
  {"ok": true, "data": {"found": false, "user_id": null, "user_name": null,
                        "role": null, "mapping_id": null,
                        "channel": "zalouser", "target": "3360952219918690445"}}
"""
import logging

from odoo import http

from odoo.addons.dac_erp.controllers.mcp import MCPReadController, McpHttpError

_logger = logging.getLogger(__name__)


class OpenclawIdentityController(MCPReadController):

    @http.route(
        '/dac_erp/mcp/v1/openclaw/resolve-internal-recipient',
        type='http',
        auth='public',
        csrf=False,
        methods=['POST'],
    )
    def openclaw_resolve_internal_recipient(self, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_resolve_internal_recipient,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    def _dispatch_resolve_internal_recipient(self, payload, env=None, headers=None, **kwargs):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, headers=headers)

        channel = (payload.get('channel') or '').strip()
        target = (payload.get('target') or '').strip()

        if not channel:
            raise McpHttpError(400, 'missing_field', "Field 'channel' is required")
        if not target:
            raise McpHttpError(400, 'missing_field', "Field 'target' is required")

        result = env['dac.openclaw.user.mapping'].resolve_internal_recipient(
            channel=channel,
            target=target,
        )
        return self._mcp_detail_payload(result), 200
