# -*- coding: utf-8 -*-
from odoo import fields, models


class McpStaffIdentityLog(models.Model):
    """Idempotency log for POST /staff/<user_id>/external-identities.

    Each write call stores its request_id here.  Re-sending the same
    request_id returns the cached result without touching dac.openclaw.user.mapping again.
    """
    _name = 'dac.erp.mcp.staff.identity.log'
    _description = 'MCP Staff External Identity Write Log'
    _order = 'create_date desc'
    _rec_name = 'request_id'

    request_id = fields.Char(string='Request ID', index=True)
    agent_name = fields.Char(string='Agent Name')
    reason = fields.Text(string='Reason')
    user_id = fields.Many2one('res.users', string='Odoo User', ondelete='cascade', index=True)
    channel = fields.Char(string='Channel')
    value = fields.Char(string='External Value')
    label = fields.Char(string='Label')
    mapping_id = fields.Many2one(
        'dac.openclaw.user.mapping',
        string='Mapping Record',
        ondelete='set null',
    )
    action = fields.Selection([
        ('create', 'Created'),
        ('update', 'Updated'),
    ], string='Action', default='create')
