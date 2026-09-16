from odoo import models
import logging

_logger = logging.getLogger(__name__)


class SaleOrderTask(models.Model):
    _inherit = 'sale.order'

    def _sync_design_task(self):
        """Tạo hoặc cập nhật task thiết kế khi sale phân công / cập nhật deadline."""
        if not self.user_id_design:
            return
        # sudo: sale user có thể không có quyền tạo task trong context hiện tại
        Task = self.env['dac.work.task'].sudo()
        existing = Task.search([
            ('order_id', '=', self.id),
            ('task_type', '=', 'design'),
            ('created_by_agent', '=', 'sale_assignment'),
            ('state', 'not in', ['done', 'cancelled']),
        ], limit=1)
        dl = self.design_deadline
        deadline_dt = (str(dl) + ' 23:59:00') if dl else False
        order_ref = self.order_number or self.name
        if existing:
            existing.with_context(dac_skip_order_sync=True).write({
                'assigned_user_id': self.user_id_design.id,
                'deadline': deadline_dt,
            })
        else:
            Task.with_context(dac_skip_order_sync=True).create({
                'name': 'Thiết kế: ' + order_ref,
                'task_type': 'design',
                'order_id': self.id,
                'assigned_user_id': self.user_id_design.id,
                'deadline': deadline_dt,
                'created_by_agent': 'sale_assignment',
                'state': 'draft',
                'priority': 'high' if self.is_priority or self.is_priority_today else 'normal',
            })

    def _sync_production_task(self):
        """Tạo hoặc cập nhật task sản xuất khi sale phân công / cập nhật deadline."""
        if not self.user_id_production:
            return
        # sudo: sale user có thể không có quyền tạo task trong context hiện tại
        Task = self.env['dac.work.task'].sudo()
        existing = Task.search([
            ('order_id', '=', self.id),
            ('task_type', '=', 'production'),
            ('created_by_agent', '=', 'sale_assignment'),
            ('state', 'not in', ['done', 'cancelled']),
        ], limit=1)
        dl = self.production_deadline
        deadline_dt = (str(dl) + ' 23:59:00') if dl else False
        order_ref = self.order_number or self.name
        if existing:
            existing.with_context(dac_skip_order_sync=True).write({
                'assigned_user_id': self.user_id_production.id,
                'deadline': deadline_dt,
            })
        else:
            Task.with_context(dac_skip_order_sync=True).create({
                'name': 'Thi công: ' + order_ref,
                'task_type': 'production',
                'order_id': self.id,
                'assigned_user_id': self.user_id_production.id,
                'deadline': deadline_dt,
                'created_by_agent': 'sale_assignment',
                'state': 'draft',
                'priority': 'high' if self.is_priority or self.is_priority_today else 'normal',
            })

    def action_quick_create_task(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dac.quick.task.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }
