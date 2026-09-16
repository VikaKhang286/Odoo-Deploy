import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartnerDedupWizard(models.TransientModel):
    """Wizard tìm và gom các khách hàng trùng số điện thoại.

    Luồng sử dụng:
    1. Manager mở wizard từ menu Pancake → Công cụ kỹ thuật → Gom khách trùng
    2. Wizard tự tìm các nhóm partner cùng phone_normalized
    3. Manager xem danh sách, chọn partner "master" cho mỗi nhóm
    4. Nhấn "Gom" → conversations + aliases được chuyển về master; partner trùng bị archive
    """
    _name = 'res.partner.dedup.wizard'
    _description = 'Gom khách hàng trùng số điện thoại'

    line_ids = fields.One2many(
        'res.partner.dedup.wizard.line',
        'wizard_id',
        string='Nhóm khách trùng',
    )
    total_groups = fields.Integer(string='Số nhóm trùng', compute='_compute_stats')
    total_partners = fields.Integer(string='Tổng partner bị trùng', compute='_compute_stats')

    @api.depends('line_ids')
    def _compute_stats(self):
        for w in self:
            w.total_groups = len(w.line_ids)
            w.total_partners = sum(len(l.duplicate_partner_ids) for l in w.line_ids)

    @api.model
    def action_open_wizard(self):
        """Tìm duplicates và mở wizard."""
        wizard = self._find_duplicates_and_create()
        if not wizard.line_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Không có trùng lặp'),
                    'message': _('Không tìm thấy khách hàng nào có cùng số điện thoại.'),
                    'type': 'success',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gom khách hàng trùng'),
            'res_model': 'res.partner.dedup.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _find_duplicates_and_create(self):
        """Tạo wizard record với các nhóm trùng theo phone_normalized."""
        self.env.cr.execute("""
            SELECT phone_normalized, array_agg(id ORDER BY create_date ASC) AS partner_ids
            FROM res_partner
            WHERE phone_normalized IS NOT NULL
              AND phone_normalized != ''
              AND active = TRUE
            GROUP BY phone_normalized
            HAVING count(*) > 1
        """)
        groups = self.env.cr.fetchall()

        wizard = self.create({})
        lines = []
        for phone_norm, partner_ids in groups:
            lines.append({
                'wizard_id': wizard.id,
                'phone_normalized': phone_norm,
                'master_partner_id': partner_ids[0],
                'duplicate_partner_ids': [(6, 0, partner_ids[1:])],
            })
        if lines:
            self.env['res.partner.dedup.wizard.line'].create(lines)
        return wizard

    def action_merge_all(self):
        """Gom tất cả các dòng đã chọn."""
        merged = 0
        for line in self.line_ids:
            if line.should_merge and line.master_partner_id and line.duplicate_partner_ids:
                line._do_merge()
                merged += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hoàn thành'),
                'message': _('Đã gom %d nhóm khách hàng.') % merged,
                'type': 'success',
                'sticky': False,
            },
        }


class ResPartnerDedupWizardLine(models.TransientModel):
    _name = 'res.partner.dedup.wizard.line'
    _description = 'Dòng gom khách trùng'

    wizard_id = fields.Many2one('res.partner.dedup.wizard', required=True, ondelete='cascade')
    phone_normalized = fields.Char(string='SĐT chuẩn hoá', readonly=True)
    master_partner_id = fields.Many2one(
        'res.partner',
        string='Giữ lại (master)',
        required=True,
        help='Partner này sẽ được giữ lại; các partner kia sẽ được archive.',
    )
    duplicate_partner_ids = fields.Many2many(
        'res.partner',
        'dedup_wizard_line_dup_rel',
        'line_id', 'partner_id',
        string='Partner bị trùng (sẽ archive)',
    )
    should_merge = fields.Boolean(string='Gom nhóm này', default=True)
    partner_count = fields.Integer(string='Số lượng', compute='_compute_partner_count')

    @api.depends('duplicate_partner_ids')
    def _compute_partner_count(self):
        for l in self:
            l.partner_count = len(l.duplicate_partner_ids) + 1

    def _do_merge(self):
        """Chuyển conversations, aliases, đơn hàng về master; archive duplicates."""
        self.ensure_one()
        master = self.master_partner_id
        Conv = self.env['page.fm.conversation'].sudo()
        PancakeCustomer = self.env['page.fm.customer'].sudo()
        SaleOrder = self.env['sale.order'].sudo()

        for dup in self.duplicate_partner_ids:
            # Chuyển conversations
            Conv.search([('partner_id', '=', dup.id)]).write({'partner_id': master.id})
            # Chuyển Pancake aliases
            PancakeCustomer.search([('partner_id', '=', dup.id)]).write({'partner_id': master.id})
            # Chuyển đơn hàng
            SaleOrder.search([('partner_id', '=', dup.id)]).write({'partner_id': master.id})
            # Backfill pancake_id nếu master chưa có
            for alias in PancakeCustomer.search([('partner_id', '=', master.id)], limit=1):
                if not master.pancake_id:
                    master.write({'pancake_id': alias.pancake_customer_id})
            # Archive duplicate
            dup.write({'active': False})
            _logger.info('Dedup: archived partner %s (ID %d) → master %s (ID %d)', dup.name, dup.id, master.name, master.id)
