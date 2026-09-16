from odoo import models


class NoDepositConfirmWizard(models.TransientModel):
    _name = 'no.deposit.confirm.wizard'
    _description = 'Xac nhan don hang khong co coc'

    def action_confirm_no_deposit(self):
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['sale.order'].browse(active_id)
            if not order.production_deadline:
                return order._open_production_deadline_wizard()
            order.has_deposit = False
            order._mark_production_started()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
