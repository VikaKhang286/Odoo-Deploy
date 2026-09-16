import logging
from odoo import models, fields, api, _
from odoo.addons.dac_erp.models.phone_utils import normalize_phone_vn  # noqa: F401 (re-exported)

_logger = logging.getLogger(__name__)


class PageFmCustomer(models.Model):
    """Bảng alias: nhiều Pancake Customer UUID → 1 res.partner.

    Cho phép:
    - 1 khách hàng dùng nhiều tài khoản Facebook/Zalo trên Pancake
    - Khách vãng lai Odoo được auto-link khi xuất hiện trên Pancake
    """
    _name = 'page.fm.customer'
    _description = 'Pancake Customer Alias'
    _order = 'is_primary desc, create_date asc'

    pancake_customer_id = fields.Char(
        string='Pancake Customer UUID',
        required=True,
        index=True,
        help='UUID hoặc ID số từ Pancake (customer.id trong API)',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Khách hàng Odoo',
        required=True,
        ondelete='cascade',
        index=True,
    )
    page_id = fields.Many2one(
        'page.fm.page',
        string='Trang Pancake',
        ondelete='set null',
        help='Trang Pancake mà UUID này xuất hiện (tuỳ chọn)',
    )
    is_primary = fields.Boolean(
        string='ID chính',
        default=True,
        help='Đánh dấu đây là Pancake ID chính của khách hàng',
    )
    note = fields.Char(string='Ghi chú')

    # Computed for display
    partner_name = fields.Char(related='partner_id.name', string='Tên khách', store=False)
    partner_phone = fields.Char(related='partner_id.phone', string='SĐT', store=False)

    _sql_constraints = [
        (
            'unique_pancake_customer_id',
            'unique(pancake_customer_id)',
            'Pancake Customer UUID này đã được liên kết với 1 khách hàng Odoo khác.',
        ),
    ]

    @api.model
    def find_partner_by_pancake_id(self, pancake_customer_id):
        """Tìm partner từ Pancake Customer UUID qua bảng alias.

        Trả về res.partner recordset (empty hoặc 1 record).
        """
        if not pancake_customer_id:
            return self.env['res.partner'].browse()
        alias = self.sudo().search([('pancake_customer_id', '=', pancake_customer_id)], limit=1)
        return alias.partner_id if alias else self.env['res.partner'].browse()

    @api.model
    def link_or_create_alias(self, pancake_customer_id, partner, page=None, is_primary=True):
        """Tạo hoặc cập nhật alias linking pancake_customer_id → partner.

        Trả về page.fm.customer record.
        """
        if not pancake_customer_id or not partner:
            return self.browse()
        existing = self.sudo().search([('pancake_customer_id', '=', pancake_customer_id)], limit=1)
        if existing:
            if existing.partner_id.id != partner.id:
                _logger.warning(
                    'Pancake UUID %s đã link với partner %s, không thể link lại với %s',
                    pancake_customer_id[:12], existing.partner_id.name, partner.name,
                )
            return existing
        vals = {
            'pancake_customer_id': pancake_customer_id,
            'partner_id': partner.id,
            'is_primary': is_primary,
        }
        if page:
            vals['page_id'] = page.id
        return self.sudo().create(vals)
