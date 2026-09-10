# -*- coding: utf-8 -*-

from odoo import fields, models


class DacErpMcpConversationAssignLog(models.Model):
    _name = 'dac_erp.mcp.conversation.assign.log'
    _description = 'DAC ERP MCP Conversation Assign Log'
    _order = 'id desc'

    conversation_id = fields.Many2one(
        'page.fm.conversation',
        string='Conversation',
        index=True,
        ondelete='set null',
    )
    action_type = fields.Selection(
        [
            ('conversation_assign', 'Conversation Assign Owner'),
        ],
        string='Action Type',
        required=True,
        default='conversation_assign',
        index=True,
    )
    request_id = fields.Char(required=True, index=True)
    request_payload_json = fields.Text(string='Request Payload JSON')
    payload_fingerprint = fields.Char(required=True, index=True)
    old_value_json = fields.Text(string='Old Value JSON')
    new_value_json = fields.Text(string='New Value JSON')
    response_snapshot_json = fields.Text(string='Response Snapshot JSON')
    agent_name = fields.Char(required=True)
    model_name = fields.Char()
    reason = fields.Text()
    status = fields.Selection(
        [
            ('success', 'Success'),
            ('replayed', 'Replayed'),
            ('conflict', 'Conflict'),
            ('failed', 'Failed'),
            ('error', 'Error'),
        ],
        string='Status',
        required=True,
        default='success',
        index=True,
    )
    error_code = fields.Char()
    error_message = fields.Text()
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    created_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, readonly=True)

    _sql_constraints = [
        ('uniq_request_id', 'unique(request_id)', 'MCP conversation assign request_id must be unique.'),
    ]
