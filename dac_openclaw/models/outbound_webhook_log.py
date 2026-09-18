# -*- coding: utf-8 -*-
from odoo import fields, models


# Event types — đồng bộ với what's documented trong design doc Phase 2
OUTBOUND_EVENT_TYPES = [
    ('order.created', 'Order Created'),
    ('order.stage_changed', 'Order Stage Changed'),
    ('order.cancelled', 'Order Cancelled'),
    ('order.reopened', 'Order Reopened'),
    ('order.payment_confirmed', 'Order Payment Confirmed'),
    ('conversation.new_message', 'Conversation New Message'),
    ('conversation.assigned', 'Conversation Assigned'),
    ('conversation.unassigned', 'Conversation Unassigned (no owner)'),
    ('conversation.status_changed', 'Conversation Status Changed'),
    ('task.created', 'Task Created'),
    ('task.assigned', 'Task Assigned'),
    ('task.completed', 'Task Completed'),
    ('task.overdue', 'Task Overdue'),
    ('task.blocked', 'Task Blocked'),
    ('task.context_updated', 'Task Context Updated (order fields changed)'),
    ('order.ready_for_design', 'Order Ready for Design (no designer assigned)'),
    ('order.design_assigned', 'Order Designer Assigned'),
    ('order.ready_for_production', 'Order Ready for Production (design done, no prod assigned)'),
    ('order.production_assigned', 'Order Production User Assigned'),
    ('design.task.created', 'Design Task Created'),
    ('design.task.done', 'Design Task Done'),
    ('production.task.created', 'Production Task Created'),
    ('production.task.done', 'Production Task Done'),
    ('customer.created', 'Customer Created'),
]


class DacOpenclawOutboundWebhookLog(models.Model):
    _name = 'dac_openclaw.outbound.webhook.log'
    _description = 'DAC OpenClaw Outbound Webhook Event Log'
    _order = 'id desc'

    event_id = fields.Char(required=True, index=True, copy=False,
                           help='UUID duy nhất cho event này — idempotency key')
    event_type = fields.Selection(OUTBOUND_EVENT_TYPES, required=True, index=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    # Optional FK references — set theo loại event
    sale_order_id = fields.Many2one('sale.order', index=True, ondelete='set null')
    conversation_id = fields.Many2one('page.fm.conversation', index=True, ondelete='set null')
    task_id = fields.Many2one('dac.work.task', index=True, ondelete='set null')
    partner_id = fields.Many2one('res.partner', index=True, ondelete='set null')

    payload_json = fields.Text(required=True,
                                help='JSON payload đã được serialize và gửi')
    signature = fields.Char(help='HMAC-SHA256 signature của payload')
    target_url = fields.Char(help='URL gửi đến (snapshot tại thời điểm gửi)')

    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('sending', 'Sending'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped (config disabled)'),
            ('giveup', 'Give Up (max retry)'),
        ],
        required=True,
        default='pending',
        index=True,
    )
    retry_count = fields.Integer(default=0)
    last_attempt_at = fields.Datetime()
    next_retry_at = fields.Datetime(index=True)

    http_status_code = fields.Integer()
    response_body = fields.Text()
    error_message = fields.Text()

    _sql_constraints = [
        ('uniq_event_id', 'unique(event_id)', 'event_id must be unique.'),
    ]
