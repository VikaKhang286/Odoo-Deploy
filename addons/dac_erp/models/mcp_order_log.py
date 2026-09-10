# -*- coding: utf-8 -*-

from odoo import fields, models


class DacErpMcpOrderLog(models.Model):
    _name = 'dac_erp.mcp.order.log'
    _description = 'DAC ERP MCP Order Write Log'
    _order = 'id desc'

    order_id = fields.Many2one('sale.order', string='Order', index=True, ondelete='set null')
    conversation_id = fields.Many2one('page.fm.conversation', string='Conversation', index=True, ondelete='set null')
    action_type = fields.Selection(
        [
            ('order_create', 'Order Create'),
            ('order_update', 'Order Update'),
            ('order_confirm_info', 'Order Confirm Info'),
            ('order_proceed_to_production', 'Order Proceed To Production'),
            ('order_proceed_to_delivery', 'Order Proceed To Delivery'),
            ('order_proceed_to_installation', 'Order Proceed To Installation'),
            ('order_create_deposit_invoice', 'Order Create Deposit Invoice'),
            ('order_create_final_invoice', 'Order Create Final Invoice'),
            ('order_confirm_deposit_invoice', 'Order Confirm Deposit Invoice'),
            ('order_confirm_final_payment', 'Order Confirm Final Payment'),
            ('order_next_step', 'Order Next Step'),
            ('order_cancel', 'Order Cancel'),
            ('order_reopen', 'Order Reopen'),
        ],
        string='Action Type',
        required=True,
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
    invoice_id = fields.Many2one('account.move', string='Invoice', index=True, ondelete='set null')
    payment_id = fields.Many2one('account.payment', string='Payment', index=True, ondelete='set null')
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
        ('uniq_request_id', 'unique(request_id)', 'MCP order request_id must be unique.'),
    ]
