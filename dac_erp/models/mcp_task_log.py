from odoo import fields, models


class DacErpMcpTaskLog(models.Model):
    _name = 'dac.erp.mcp.task.log'
    _description = 'MCP Task Operation Log'
    _order = 'create_date desc'

    action_type = fields.Selection([
        ('task_create', 'Tạo task'),
        ('task_update', 'Cập nhật task'),
        ('task_status', 'Cập nhật trạng thái task'),
        ('task_note', 'Thêm ghi chú task'),
        ('task_blocker', 'Set/Clear blocker task'),
        ('order_assign_designer', 'Giao designer cho đơn'),
        ('order_ensure_task', 'Ensure task từ đơn'),
    ], string='Loại hành động', required=True)

    task_id = fields.Many2one(
        'dac.work.task', string='Task', ondelete='set null', index=True,
    )
    request_id = fields.Char(string='Request ID', index=True)
    agent_name = fields.Char(string='Tên Agent')
    payload_json = fields.Text(string='Request payload')
    response_json = fields.Text(string='Response snapshot')
    status = fields.Selection([
        ('success', 'Thành công'),
        ('replayed', 'Đã replay'),
        ('failed', 'Thất bại'),
    ], string='Trạng thái', required=True, default='success')
    error_message = fields.Text(string='Lỗi')

    _sql_constraints = [
        ('unique_request_id', 'UNIQUE(request_id)',
         'request_id phải là duy nhất — duplicate request sẽ bị phát hiện là replay.'),
    ]
