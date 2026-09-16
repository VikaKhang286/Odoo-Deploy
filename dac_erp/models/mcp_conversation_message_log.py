# -*- coding: utf-8 -*-
from odoo import fields, models


class DacErpMcpConversationMessageLog(models.Model):
    _name = 'dac_erp.mcp.conversation.message.log'
    _description = 'DAC ERP MCP Outbound Message Log'
    _order = 'id desc'

    conversation_id = fields.Many2one(
        'page.fm.conversation',
        index=True,
        ondelete='set null',
    )
    action_type = fields.Selection(
        [('message_send', 'Message Send')],
        required=True,
        default='message_send',
        index=True,
    )
    request_id = fields.Char(required=True, index=True)
    request_payload_json = fields.Text(required=True)
    payload_fingerprint = fields.Char(required=True, index=True)
    text_preview = fields.Char(help='First 200 chars of message')
    via_channel = fields.Char(help='auto/zalo/facebook/etc')
    pancake_message_id = fields.Char(index=True,
                                       help='ID trả về từ Pancake nếu API có')
    pancake_http_status = fields.Integer()
    response_snapshot_json = fields.Text()
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
        required=True,
        default='success',
        index=True,
    )
    error_code = fields.Char()
    error_message = fields.Text()
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    created_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, readonly=True)

    _sql_constraints = [
        ('uniq_request_id', 'unique(request_id)', 'MCP message send request_id must be unique.'),
    ]
