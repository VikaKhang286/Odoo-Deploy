from odoo import api, fields, models
from odoo.exceptions import UserError


class DacQuickTaskWizard(models.TransientModel):
    _name = 'dac.quick.task.wizard'
    _description = 'Tạo Task Nhanh'

    order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True, readonly=True)
    name = fields.Char(string='Tiêu đề', required=True)
    description = fields.Text(string='Mô tả')
    deadline = fields.Datetime(string='Hạn chót')
    assigned_user_id = fields.Many2one('res.users', string='Người thực hiện')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and 'order_id' in fields_list:
            res['order_id'] = active_id
        return res

    def action_create_task(self):
        self.ensure_one()
        if not self.order_id:
            raise UserError('Không tìm thấy đơn hàng.')
        self.env['dac.work.task'].create({
            'name': self.name,
            'description': self.description,
            'deadline': self.deadline,
            'assigned_user_id': self.assigned_user_id.id if self.assigned_user_id else False,
            'order_id': self.order_id.id,
            'task_type': 'other',
            'state': 'draft',
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}
