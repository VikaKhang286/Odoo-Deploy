# -*- coding: utf-8 -*-

from odoo import fields, models


class DacErpMcpBulkLog(models.Model):
    _name = 'dac_erp.mcp.bulk.log'
    _description = 'DAC ERP MCP Bulk Request Log'
    _order = 'id desc'

    action_type = fields.Selection(
        [
            ('customer_care_create_followups', 'Customer Care Create Followups'),
            ('customer_care_apply_reviewed_actions', 'Customer Care Apply Reviewed Actions'),
        ],
        string='Action Type',
        required=True,
        index=True,
    )
    request_id = fields.Char(required=True, index=True)
    request_payload_json = fields.Text(string='Request Payload JSON')
    payload_fingerprint = fields.Char(required=True, index=True)
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
        ('uniq_request_id', 'unique(request_id)', 'MCP bulk request_id must be unique.'),
    ]
