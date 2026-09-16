from odoo import fields, models


class PancakeBulkSyncPageLine(models.TransientModel):
    _name = 'pancake.bulk.sync.page.line'
    _description = 'Dòng chọn page cho đồng bộ toàn bộ Pancake'
    _order = 'name asc, id asc'

    dashboard_id = fields.Many2one('pancake.bulk.sync.dashboard', string='Dashboard', required=True, ondelete='cascade')
    page_id = fields.Many2one('page.fm.page', string='Page', required=True)
    name = fields.Char(string='Tên page', readonly=True)
    page_fm_id_str = fields.Char(string='Page.fm ID', readonly=True)
    catalog_status = fields.Selection(
        [('active', 'Đang hoạt động'), ('inactive', 'Không hoạt động'), ('unknown', 'Không rõ')],
        string='Trạng thái catalog',
        readonly=True,
    )
    page_token_cached = fields.Boolean(string='Đã có token trang', readonly=True)
    page_token_cached_at = fields.Datetime(string='Lần tạo token trang gần nhất', readonly=True)
    conversation_count = fields.Integer(string='Conversation', readonly=True)
    last_message_sync_at = fields.Datetime(string='Lần sync tin nhắn gần nhất', readonly=True)
    sync_enabled = fields.Boolean(string='Chọn đồng bộ', default=False)
