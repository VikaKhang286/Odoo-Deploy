# -*- coding: utf-8 -*-
"""MCP Staff Identity Bridge.

GET  /dac_erp/mcp/v1/staff
     Lists DAC staff (any user holding a DAC group).  Includes external_identities
     from dac.openclaw.user.mapping so agents can bridge owner.id <-> Zalo/OpenClaw.

POST /dac_erp/mcp/v1/staff/<user_id>/external-identities
     Upserts an external identity mapping for a staff member.
     Requires write API key.  Idempotent by request_id.

Semantic note — owner.id in /conversations
──────────────────────────────────────────
page.fm.conversation.owner_id is Many2one('res.users').
Therefore owner.id in every /conversations response is a res.users primary key —
it matches user_id in /staff directly.

Shared-account flag
───────────────────
dac_is_shared_account on res.users is set manually via Odoo backend.
When True, the agent should NOT send targeted personal reminders for that account
because the Odoo credential is shared by more than one physical person.
"""
import logging

from odoo import http
from odoo.addons.dac_erp.controllers.mcp import MCPReadController, McpHttpError

_logger = logging.getLogger(__name__)

_VALID_CHANNELS = frozenset({'telegram', 'zalo', 'zalouser', 'facebook', 'webchat', 'other'})

# DAC leaf groups — implied groups propagate automatically, so searching for these
# leaf IDs covers all role combos (sale_all -> sale, full_stack -> sale_all -> sale, etc.)
_DAC_LEAF_GROUP_XMLIDS = [
    'dac_erp.group_dac_erp_sale',
    'dac_erp.group_dac_erp_manager',
    'dac_erp.group_dac_erp_design',
    'dac_erp.group_dac_erp_production',
]


class MCPStaffController(MCPReadController):

    # ─── GET /dac_erp/mcp/v1/staff ──────────────────────────────────

    @http.route(
        '/dac_erp/mcp/v1/staff',
        type='http',
        auth='public',
        csrf=False,
        methods=['GET'],
    )
    def mcp_list_staff(self, **kwargs):
        return self._handle_mcp_http(self._dispatch_list_staff, **kwargs)

    def _dispatch_list_staff(self, env=None, headers=None, **kwargs):
        env = self._get_env(env)
        self._ensure_mcp_read_api_key(env=env, headers=headers)

        # Parse params
        active_flag = self._as_bool(kwargs.get('active', 'true'), 'active')
        if active_flag is None:
            active_flag = True

        q = (kwargs.get('q') or '').strip()

        team_id_raw = kwargs.get('team_id')
        team_id = None
        if team_id_raw not in (None, ''):
            try:
                team_id = int(team_id_raw)
            except (TypeError, ValueError):
                raise McpHttpError(400, 'validation_error', 'team_id must be an integer')

        limit, offset = self._normalize_capped_limit_offset(
            limit=kwargs.get('limit'),
            offset=kwargs.get('offset'),
            default_limit=50,
            max_limit=200,
        )

        # Gather DAC group IDs; implied groups propagate so leaf IDs are sufficient
        dac_group_ids = [
            g.id
            for xmlid in _DAC_LEAF_GROUP_XMLIDS
            for g in [env.ref(xmlid, raise_if_not_found=False)]
            if g
        ]

        # Build domain
        domain = [('active', '=', active_flag)]
        if dac_group_ids:
            domain.append(('groups_id', 'in', dac_group_ids))
        if team_id is not None:
            domain.append(('sale_team_id', '=', team_id))
        if q:
            domain += [
                '|', ('name', 'ilike', q),
                '|', ('login', 'ilike', q),
                     ('email', 'ilike', q),
            ]

        # with_context(active_test=False) so our explicit active= domain wins
        UserModel = env['res.users'].sudo().with_context(active_test=False)
        users = UserModel.search(domain, limit=limit, offset=offset, order='name asc')
        total = UserModel.search_count(domain)

        sale_group = env.ref('dac_erp.group_dac_erp_sale', raise_if_not_found=False)
        sale_group_id = sale_group.id if sale_group else None

        # Batch-fetch external identities (dac.openclaw.user.mapping)
        mappings_by_user = {}
        if users.ids:
            for m in env['dac.openclaw.user.mapping'].sudo().search([
                ('user_id', 'in', users.ids),
                ('active', '=', True),
            ]):
                mappings_by_user.setdefault(m.user_id.id, []).append(m)

        # Batch-fetch pages via conversation ownership
        pages_by_user = self._staff_get_pages_by_user(env, users.ids)

        items = [
            self._serialize_staff_member(
                user,
                sale_group_id=sale_group_id,
                mappings=mappings_by_user.get(user.id, []),
                pages=pages_by_user.get(user.id, []),
            )
            for user in users
        ]
        return self._mcp_list_payload(items, total), 200

    def _staff_get_pages_by_user(self, env, user_ids):
        """Return {user_id: [{id, name, page_fm_id}]} derived from conversation ownership."""
        if not user_ids:
            return {}
        try:
            groups = env['page.fm.conversation'].sudo().read_group(
                [('owner_id', 'in', user_ids)],
                ['owner_id', 'page_fm_page_id'],
                ['owner_id', 'page_fm_page_id'],
                lazy=False,
            )
        except Exception:
            return {}

        page_ids_needed = set()
        raw_pairs = []
        for g in groups:
            uid_field = g.get('owner_id')
            pgid_field = g.get('page_fm_page_id')
            if not uid_field or not pgid_field:
                continue
            uid = uid_field[0] if isinstance(uid_field, (list, tuple)) else uid_field
            pgid = pgid_field[0] if isinstance(pgid_field, (list, tuple)) else pgid_field
            raw_pairs.append((uid, pgid))
            page_ids_needed.add(pgid)

        if not page_ids_needed:
            return {}

        try:
            pages = env['page.fm.page'].sudo().browse(list(page_ids_needed)).exists()
            page_map = {
                p.id: {
                    'id': p.id,
                    'name': getattr(p, 'name', None),
                    'page_fm_id': getattr(p, 'page_fm_id_str', None) or getattr(p, 'page_fm_id', None),
                }
                for p in pages
            }
        except Exception:
            return {}

        result = {}
        seen = {}  # (user_id, page_id) dedup
        for uid, pgid in raw_pairs:
            if (uid, pgid) in seen:
                continue
            seen[(uid, pgid)] = True
            page_data = page_map.get(pgid)
            if page_data:
                result.setdefault(uid, []).append(page_data)
        return result

    def _serialize_staff_member(self, user, sale_group_id=None, mappings=None, pages=None):
        partner = getattr(user, 'partner_id', None)
        is_sales = bool(sale_group_id and any(g.id == sale_group_id for g in user.groups_id))

        teams = []
        try:
            team = getattr(user, 'sale_team_id', None)
            if team and team.id:
                teams = [{'id': team.id, 'name': getattr(team, 'name', None)}]
        except Exception:
            pass

        external_identities = [
            {
                'channel': m.channel,
                'value': m.target,
                'label': m.note or None,
            }
            for m in (mappings or [])
        ]

        return {
            'user_id': user.id,
            'name': user.name,
            'login': user.login,
            'email': getattr(partner, 'email', None) or getattr(user, 'email', None) or None,
            'phone': getattr(partner, 'phone', None) or getattr(partner, 'mobile', None) or None,
            'active': bool(user.active),
            'is_sales': is_sales,
            'is_shared_account': bool(getattr(user, 'dac_is_shared_account', False)),
            'teams': teams,
            'pages': pages or [],
            'external_identities': external_identities,
        }

    # ─── POST /staff/<user_id>/external-identities ──────────────────

    @http.route(
        '/dac_erp/mcp/v1/staff/<int:user_id>/external-identities',
        type='http',
        auth='public',
        csrf=False,
        methods=['POST'],
    )
    def mcp_upsert_staff_external_identity(self, user_id, **kwargs):
        return self._handle_mcp_http(
            self._dispatch_upsert_external_identity,
            user_id=user_id,
            payload=self._get_v3_json_payload(),
            **kwargs
        )

    def _dispatch_upsert_external_identity(self, user_id, payload=None, env=None, headers=None, **kwargs):
        env = self._get_env(env)
        self._ensure_mcp_write_api_key(env=env, headers=headers)

        payload = payload or {}
        request_id = (payload.get('request_id') or '').strip()
        agent_name = (payload.get('agent_name') or '').strip()
        reason = (payload.get('reason') or '').strip()
        channel = (payload.get('channel') or '').strip()
        value = (payload.get('value') or '').strip()
        label = (payload.get('label') or '').strip() or None

        if not request_id:
            raise McpHttpError(400, 'missing_field', "Field 'request_id' is required")
        if not channel:
            raise McpHttpError(400, 'missing_field', "Field 'channel' is required")
        if not value:
            raise McpHttpError(400, 'missing_field', "Field 'value' is required")
        if channel not in _VALID_CHANNELS:
            raise McpHttpError(
                400, 'validation_error',
                f"channel must be one of: {', '.join(sorted(_VALID_CHANNELS))}",
            )

        user = env['res.users'].sudo().browse(user_id).exists()
        if not user:
            raise McpHttpError(404, 'not_found', f'Staff user {user_id} not found')

        Log = env['dac.erp.mcp.staff.identity.log']

        # Idempotency: same request_id → return cached result
        existing_log = Log.sudo().search([('request_id', '=', request_id)], limit=1)
        if existing_log:
            return self._mcp_detail_payload({
                **self._serialize_identity_result(user, existing_log.mapping_id, existing_log.action),
                'idempotent_hit': True,
            }), 200

        # Upsert dac.openclaw.user.mapping
        Mapping = env['dac.openclaw.user.mapping']
        existing_mapping = Mapping.sudo().search([
            ('user_id', '=', user_id),
            ('channel', '=', channel),
            ('target', '=', value),
        ], limit=1)

        if existing_mapping:
            existing_mapping.sudo().write({'note': label, 'active': True})
            action = 'update'
            mapping = existing_mapping
        else:
            mapping = Mapping.sudo().create({
                'user_id': user_id,
                'channel': channel,
                'target': value,
                'note': label,
                'active': True,
                'notify_enabled': True,
                'digest_enabled': True,
                'deadline_enabled': True,
            })
            action = 'create'

        # Record for idempotency
        Log.sudo().create({
            'request_id': request_id,
            'agent_name': agent_name,
            'reason': reason,
            'user_id': user_id,
            'channel': channel,
            'value': value,
            'label': label,
            'mapping_id': mapping.id,
            'action': action,
        })

        return self._mcp_detail_payload({
            **self._serialize_identity_result(user, mapping, action),
            'idempotent_hit': False,
        }), 200

    def _serialize_identity_result(self, user, mapping, action='create'):
        return {
            'user_id': user.id if user else None,
            'user_name': user.name if user else None,
            'mapping_id': mapping.id if mapping else None,
            'channel': getattr(mapping, 'channel', None) if mapping else None,
            'value': getattr(mapping, 'target', None) if mapping else None,
            'label': getattr(mapping, 'note', None) if mapping else None,
            'action': action,
        }
