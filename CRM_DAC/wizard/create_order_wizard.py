from odoo import _, api, fields, models
import logging

_logger = logging.getLogger(__name__)

LOAD_LIMIT = 20


class DacCreateOrderWizard(models.TransientModel):
    _name = 'dac.create.order.wizard'
    _description = 'Tạo đơn hàng từ hội thoại Pancake'

    conversation_ids = fields.Many2many(
        'page.fm.conversation',
        'dac_create_order_wiz_conv_rel',
        'wizard_id', 'conversation_id',
        string='Danh sách hội thoại',
        readonly=True,
    )
    search_query = fields.Char(string='Tìm khách hàng / hội thoại')
    load_offset = fields.Integer(default=0)
    has_more = fields.Boolean(default=False)

    def _conversation_domain(self):
        """Domain tìm hội thoại — lọc theo search_query nếu có."""
        domain = [('page_fm_page_id.active', '=', True)]
        query = (self.search_query or '').strip()
        if query:
            domain += [
                '|', '|', '|',
                ('customer_name_fm', 'ilike', query),
                ('last_message_snippet', 'ilike', query),
                ('partner_id.name', 'ilike', query),
                ('partner_id.phone', 'ilike', query),
            ]
        return domain

    def _load_conversations(self, offset=0):
        # sudo: wizard cần đọc tất cả conversation không phân biệt quyền sale
        convs = self.env['page.fm.conversation'].sudo().search(
            self._conversation_domain(),
            order='last_update_at desc, id desc',
            limit=LOAD_LIMIT,
            offset=offset,
        )
        # Tải avatar về binary cho batch đang hiển thị (chỉ tải lần đầu, sau đó cache)
        convs._download_avatar_binary()
        return convs

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        # sudo: wizard cần đọc tất cả conversation không phân biệt quyền sale
        convs = self.env['page.fm.conversation'].sudo().search(
            [('page_fm_page_id.active', '=', True)],
            order='last_update_at desc, id desc',
            limit=LOAD_LIMIT,
        )
        # Tải avatar về binary cho batch đầu (chỉ tải lần đầu, sau đó cache)
        convs._download_avatar_binary()
        vals['conversation_ids'] = [(6, 0, convs.ids)]
        vals['load_offset'] = len(convs)
        vals['has_more'] = len(convs) >= LOAD_LIMIT
        return vals

    @api.onchange('search_query')
    def _onchange_search_query(self):
        """Lọc lại danh sách hội thoại ngay khi gõ vào thanh search (cập nhật tại chỗ)."""
        convs = self._load_conversations(0)
        self.conversation_ids = [(6, 0, convs.ids)]
        self.load_offset = len(convs)
        self.has_more = len(convs) >= LOAD_LIMIT

    def action_search(self):
        """Nút tìm kiếm — reset phân trang và nạp lại theo từ khóa hiện tại."""
        self.ensure_one()
        convs = self._load_conversations(0)
        self.conversation_ids = [(6, 0, convs.ids)]
        self.load_offset = len(convs)
        self.has_more = len(convs) >= LOAD_LIMIT
        return self._reopen()

    def action_load_more(self):
        self.ensure_one()
        new_convs = self._load_conversations(self.load_offset)
        if new_convs:
            self.conversation_ids = [(4, c.id) for c in new_convs]
            self.load_offset += len(new_convs)
        self.has_more = len(new_convs) >= LOAD_LIMIT
        return self._reopen()

    @api.model
    def action_open_wizard(self):
        # sudo: được gọi từ server action / list button không có user context đầy đủ
        wizard = self.sudo().create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo đơn hàng'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo đơn hàng'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }
