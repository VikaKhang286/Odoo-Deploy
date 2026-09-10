from odoo import fields, models


class DacOpenclawNotificationLog(models.Model):
    _name = 'dac.openclaw.notification.log'
    _description = 'OpenClaw Notification Log'
    _order = 'create_date desc'

    event_id = fields.Char(string='Event ID', required=True, index=True)
    event_type = fields.Selection([
        ('task_assigned', 'Task Assigned'),
        ('task_reminder', 'Task Reminder'),
        ('daily_digest', 'Daily Digest'),
        ('task_escalation', 'Task Escalation'),
        ('manager_digest', 'Manager Digest'),
    ], string='Event Type', required=True, index=True)
    mapping_id = fields.Many2one(
        'dac.openclaw.user.mapping',
        string='Recipient Mapping',
        ondelete='set null',
        index=True,
    )
    user_id = fields.Many2one('res.users', string='Recipient User', ondelete='set null', index=True)
    task_id = fields.Many2one('dac.work.task', string='Task', ondelete='set null', index=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], string='Status', required=True, default='pending', index=True)
    payload_json = fields.Text(string='Payload JSON')
    response_json = fields.Text(string='Response JSON')
    error_message = fields.Text(string='Error Message')
    sent_at = fields.Datetime(string='Sent At')

    _sql_constraints = [
        ('uniq_event_id', 'unique(event_id)', 'event_id phải là duy nhất.'),
    ]
