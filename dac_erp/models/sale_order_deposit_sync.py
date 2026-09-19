from odoo import api, models, _
from odoo.exceptions import UserError


class SaleOrderDepositSync(models.Model):
    _inherit = 'sale.order'

    def _editable_deposit_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and (
                line.product_id.default_code == 'DEPOSIT'
                or line.name == 'Đặt cọc'
            )
        )

    @api.onchange('deposit_amount')
    def _onchange_confirmed_deposit_amount(self):
        for order in self.filtered('is_deposit_confirmed'):
            lines = order._editable_deposit_lines()
            if len(lines) == 1:
                lines.update({'price_unit': -order.deposit_amount,
                              'product_uom_qty': 1, 'discount': 0})

    def write(self, vals):
        if 'deposit_amount' not in vals:
            return super().write(vals)
        # A failed accounting update must also undo the order amount/lines.
        with self.env.cr.savepoint():
            result = super().write(vals)
            for order in self.filtered('is_deposit_confirmed'):
                order._sync_confirmed_deposit_amount()
        return result

    def _sync_confirmed_deposit_amount(self):
        self.ensure_one()
        amount = self.deposit_amount
        if self.currency_id.compare_amounts(amount, 0) <= 0:
            raise UserError(_('Tiền cọc đã xác nhận phải lớn hơn 0.'))
        if self.currency_id.compare_amounts(amount, self.amount_total) > 0:
            raise UserError(_('Tiền cọc không được lớn hơn tổng tiền đơn hàng.'))
        invoices = self.env['account.move'].search([
            ('invoice_origin', '=', self.name),
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '!=', 'cancel'),
        ])
        deposits = invoices.filtered('dac_deposit_invoice')
        if len(deposits) != 1:
            raise UserError(_('Cần đúng một hóa đơn cọc để tự động điều chỉnh tiền cọc.'))
        invoice = deposits
        lines = self._editable_deposit_lines()
        if len(lines) > 1:
            raise UserError(_('Đơn có nhiều dòng cọc; vui lòng kiểm tra trước khi điều chỉnh.'))
        if invoice.currency_id != self.currency_id:
            raise UserError(_('Hóa đơn cọc và đơn hàng phải dùng cùng tiền tệ.'))
        if invoice.currency_id.compare_amounts(invoice.amount_total, amount):
            if invoices - deposits:
                raise UserError(_('Đơn đã có hóa đơn thanh toán cuối. Vui lòng xử lý hóa đơn đó trước khi điều chỉnh cọc.'))
            invoice_lines = invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
            if len(invoice_lines) != 1 or invoice_lines.tax_ids:
                raise UserError(_('Chỉ tự động điều chỉnh hóa đơn cọc có một dòng và không có thuế.'))
            payment = invoice._get_reconciled_payments()
            counterparts = invoice._get_reconciled_amls()
            if counterparts and (len(payment) != 1 or counterparts - payment.move_id.line_ids):
                raise UserError(_('Hóa đơn cọc có đối soát phức tạp; vui lòng kiểm tra chứng từ trước khi sửa.'))
            if payment:
                if (payment.reconciled_invoice_ids != invoice
                        or payment.currency_id != invoice.currency_id
                        or invoice.currency_id.compare_amounts(payment.amount, invoice.amount_total)
                        or not invoice.currency_id.is_zero(invoice.amount_residual)
                        or payment.move_id._get_reconciled_statement_lines()):
                    raise UserError(_('Phiếu thu cọc phải thanh toán riêng, đầy đủ cho hóa đơn này và chưa đối soát ngân hàng.'))
            was_posted = invoice.state == 'posted'
            old_amount = invoice.amount_total
            # Standard Odoo methods preserve lock-date and secured-entry checks.
            if was_posted:
                invoice.button_draft()
            if payment:
                payment.action_draft()
                payment.write({'amount': amount})
            invoice_lines.write({'quantity': 1, 'price_unit': amount, 'discount': 0})
            if was_posted:
                invoice.action_post()
            if payment:
                payment.action_post()
                receivable = (invoice.line_ids + payment.move_id.line_ids).filtered(
                    lambda line: line.account_id.account_type == 'asset_receivable'
                    and not line.reconciled
                )
                receivable.reconcile()
            self.message_post(body=_('Điều chỉnh tiền cọc: %(old)s → %(new)s; đã đồng bộ hóa đơn %(invoice)s.',
                                      old=old_amount, new=amount, invoice=invoice.name))
        if not lines:
            self.add_deposit_order_line(amount, invoice=invoice)
            lines = self._editable_deposit_lines()
        lines.write({'price_unit': -amount, 'product_uom_qty': 1, 'discount': 0,
                     'tax_id': [(5, 0, 0)]})
        self.invalidate_recordset(['total_deposit_paid', 'deposit_paid_display', 'remaining_amount_display'])
