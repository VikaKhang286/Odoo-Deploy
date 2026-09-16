from odoo import api, fields, models


class DacErpMcpAutoRunLog(models.Model):
    _name = 'dac_erp.mcp.auto.run.log'
    _description = 'DAC ERP MCP Customer Care Auto Run Log'
    _order = 'id desc'

    name = fields.Char(required=True, default='MCP Customer Care Auto Run')
    request_id = fields.Char(required=True, index=True)
    payload_fingerprint = fields.Char(required=True, index=True)
    mode = fields.Selection(
        [('manual_api', 'Manual API'), ('cron', 'Cron')],
        required=True,
        default='manual_api',
        index=True,
    )
    dry_run = fields.Boolean(default=True, index=True)
    policy = fields.Char()
    sla_minutes = fields.Integer()
    urgent_minutes = fields.Integer()
    batch_limit = fields.Integer()
    filters_json = fields.Text()
    request_payload_json = fields.Text()
    response_snapshot_json = fields.Text()
    summary_json = fields.Text()
    item_results_json = fields.Text()
    status = fields.Selection(
        [
            ('success', 'Success'),
            ('replayed', 'Replayed'),
            ('conflict', 'Conflict'),
            ('failed', 'Failed'),
        ],
        required=True,
        default='success',
        index=True,
    )
    error_code = fields.Char()
    error_message = fields.Text()
    agent_name = fields.Char(required=True)
    model_name = fields.Char()
    reason = fields.Text()
    started_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    finished_at = fields.Datetime(readonly=True)
    duration_ms = fields.Integer()
    created_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, readonly=True)

    _sql_constraints = [
        ('uniq_request_id', 'unique(request_id)', 'MCP customer-care auto-run request_id must be unique.'),
    ]

    @api.model
    def _cron_customer_care_auto_run(self):
        from odoo.addons.dac_erp.controllers.mcp import MCPReadController

        controller = MCPReadController()
        return controller._run_customer_care_auto_run_cron(env=self.env)
