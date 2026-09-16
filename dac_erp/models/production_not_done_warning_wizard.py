from odoo import fields, models


class ProductionNotDoneWarningWizard(models.TransientModel):
    _name = 'production.not.done.warning.wizard'
    _description = 'Cảnh báo sản xuất chưa hoàn tất'

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_confirm_and_proceed(self):
        active_id = self.env.context.get('active_id')
        if not active_id:
            return {'type': 'ir.actions.act_window_close'}

        order = self.env['sale.order'].browse(active_id)
        if not order.exists():
            return {'type': 'ir.actions.act_window_close'}

        # sudo: wizard action — sale user có thể không thuộc group production
        order.sudo().write({
            'production_done': True,
            'production_done_date': fields.Datetime.now(),
            'production_done_user_id': self.env.user.id,
        })
        order.sudo().message_post(
            body=f"{self.env.user.name} đã xác nhận hoàn tất sản xuất (qua bước giao hàng).",
            subtype_xmlid='mail.mt_note',
        )

        # Đánh dấu tất cả task sản xuất của đơn này là hoàn thành
        production_tasks = self.env['dac.work.task'].sudo().search([
            ('order_id', '=', order.id),
            ('task_type', '=', 'production'),
            ('state', 'not in', ['done', 'cancelled']),
        ])
        if production_tasks:
            production_tasks.sudo().write({'state': 'done'})

        order.action_proceed_to_delivery()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
