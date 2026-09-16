from datetime import timedelta

from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError


class ProductionDeadlineWizard(models.TransientModel):
    _name = 'production.deadline.wizard'
    _description = 'Choose Production Deadline Before Starting Production'

    order_name = fields.Char(string='Đơn hàng', readonly=True)
    production_deadline = fields.Date(string='Ngày hoàn thành', required=False)
    default_deadline_days = fields.Integer(string='Số ngày mặc định', readonly=True)
    default_deadline_date = fields.Date(string='Ngày hoàn thành mặc định', readonly=True)

    @api.model
    def _get_configured_default_deadline_days(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.production_default_deadline_days',
            default='3',
        )
        try:
            days = int(param)
        except (TypeError, ValueError):
            days = 3
        return max(days, 1)

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type == 'form' and result.get('arch'):
            arch = etree.fromstring(result['arch'])
            default_button = arch.xpath("//button[@name='action_use_default_deadline']")
            if default_button:
                default_button[0].set(
                    'string',
                    f"Mặc định {self._get_configured_default_deadline_days()} ngày",
                )
                result['arch'] = etree.tostring(arch, encoding='unicode')
        return result

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if not active_id:
            return res

        order = self.env['sale.order'].browse(active_id)
        if not order.exists():
            return res

        today = fields.Date.context_today(self)
        default_days = self._get_configured_default_deadline_days()
        res.update({
            'order_name': order.name,
            'default_deadline_days': default_days,
            'default_deadline_date': today + timedelta(days=default_days),
        })
        return res

    def _get_active_order(self):
        self.ensure_one()
        order = self.env['sale.order'].browse(self.env.context.get('active_id'))
        if not order.exists():
            raise UserError('Không tìm thấy đơn hàng để cập nhật ngày hoàn thành.')
        return order

    def action_confirm(self):
        self.ensure_one()
        if not self.production_deadline:
            raise UserError('Vui lòng nhập ngày hoàn thành hoặc dùng ngày mặc định.')

        order = self._get_active_order()
        order.production_deadline = self.production_deadline
        result = order._action_proceed_to_production_with_deadline()
        if result is True:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return result

    def action_use_default_deadline(self):
        self.ensure_one()
        order = self._get_active_order()
        deadline = self.default_deadline_date
        if not deadline:
            today = fields.Date.context_today(self)
            deadline = today + timedelta(days=max(self.default_deadline_days or 0, 1))
        order.production_deadline = deadline
        result = order._action_proceed_to_production_with_deadline()
        if result is True:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return result
