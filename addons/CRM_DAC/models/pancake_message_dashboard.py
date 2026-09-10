from odoo import _, api, fields, models


class PancakeMessageDashboard(models.TransientModel):
    _name = 'pancake.message.dashboard'
    _inherit = 'pancake.sync.dashboard'
    _description = 'Pancake Message Dashboard'

    selected_conversation_id = fields.Many2one('page.fm.conversation', string='Hội thoại đang xem')
    conversation_preview_ids = fields.Many2many('page.fm.conversation', string='Danh sách hội thoại', readonly=True)
    selected_message_ids = fields.One2many(
        related='selected_conversation_id.conv_message_ids',
        string='Danh sách tin nhắn',
        readonly=True,
    )
    selected_partner_id = fields.Many2one(
        related='selected_conversation_id.partner_id',
        string='Khách hàng',
        readonly=True,
    )
    selected_customer_name = fields.Char(
        related='selected_conversation_id.customer_name_fm',
        string='Tên khách Pancake',
        readonly=True,
    )
    selected_phone = fields.Char(related='selected_conversation_id.phone', string='Số điện thoại', readonly=True)
    selected_platform = fields.Char(related='selected_conversation_id.platform_fm', string='Nền tảng', readonly=True)
    selected_page_id = fields.Many2one(
        related='selected_conversation_id.page_fm_page_id',
        string='Page',
        readonly=True,
    )
    selected_status_state = fields.Selection(
        related='selected_conversation_id.status_state',
        string='Trạng thái',
        readonly=True,
    )
    selected_require_processing = fields.Boolean(
        related='selected_conversation_id.require_processing',
        string='Cần xử lý',
        readonly=True,
    )
    selected_is_unread = fields.Boolean(
        related='selected_conversation_id.is_unread_fm',
        string='Chưa đọc',
        readonly=True,
    )
    selected_suggestion_note = fields.Text(
        related='selected_conversation_id.suggestion_note',
        string='Ghi chú',
        readonly=True,
    )
    selected_last_message_sync_at = fields.Datetime(
        related='selected_conversation_id.last_message_sync_fm',
        string='Đồng bộ tin nhắn lần cuối',
        readonly=True,
    )
    selected_message_count = fields.Integer(
        related='selected_conversation_id.message_count',
        string='Số tin nhắn',
        readonly=True,
    )
    selected_order_count = fields.Integer(string='Số đơn hàng', readonly=True)
    can_manage_sync = fields.Boolean(string='Có quyền đồng bộ', compute='_compute_can_manage_sync')

    @api.depends_context('uid')
    def _compute_can_manage_sync(self):
        can_manage = self.env.user.has_group('dac_erp.group_dac_erp_manager') or self.env.user.has_group('base.group_system')
        for record in self:
            record.can_manage_sync = can_manage

    @api.model
    def _message_dashboard_domain(self):
        return [('page_fm_page_id.active', '=', True)]

    @api.model
    def _get_preview_conversations(self, limit=25):
        return self.env['page.fm.conversation'].sudo().search(
            self._message_dashboard_domain(),
            order='last_update_at desc, id desc',
            limit=limit,
        )

    @api.model
    def _get_dashboard_record(self, conversation_id=None):
        dashboard = self.search([('create_uid', '=', self.env.uid)], order='id desc', limit=1)
        selected_conversation_id = conversation_id or (dashboard.selected_conversation_id.id if dashboard else False)
        values = self._build_dashboard_values(selected_conversation_id=selected_conversation_id)
        if dashboard:
            dashboard.write(values)
            return dashboard
        return self.create(values)

    @api.model
    def _build_dashboard_values(self, selected_conversation_id=None):
        values = super()._build_dashboard_values()
        can_manage_sync = self.env.user.has_group('dac_erp.group_dac_erp_manager') or self.env.user.has_group('base.group_system')
        preview_conversations = self._get_preview_conversations(limit=25)
        selected_conversation = self.env['page.fm.conversation'].sudo().browse(selected_conversation_id).exists()
        if not selected_conversation:
            selected_conversation = preview_conversations[:1]
        values.update({
            'conversation_preview_ids': [(6, 0, preview_conversations.ids)],
            'selected_conversation_id': selected_conversation.id if selected_conversation else False,
            'selected_order_count': self.env['sale.order'].sudo().search_count([
                ('partner_id', 'child_of', selected_conversation.partner_id.commercial_partner_id.id),
            ]) if selected_conversation and selected_conversation.partner_id else 0,
        })
        if not can_manage_sync:
            values.update({
                'access_token': '',
                'webhook_secret': '',
                'token_check_message': False,
            })
        return values

    @api.model
    def _build_open_dashboard_action(self, dashboard):
        form_view = self.env.ref('CRM_DAC.view_pancake_message_dashboard_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dashboard Tin nhắn Pancake'),
            'res_model': self._name,
            'res_id': dashboard.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'current',
        }

    def _refresh_dashboard_record(self):
        self.ensure_one()
        values = self._build_dashboard_values(selected_conversation_id=self.selected_conversation_id.id)
        self.write(values)
        return self

    @api.model
    def action_open_dashboard(self, conversation_id=None):
        dashboard = self._get_dashboard_record(conversation_id=conversation_id)
        return self._build_open_dashboard_action(dashboard)

    def action_view_all_conversations(self):
        return self.env.ref('CRM_DAC.action_page_fm_conversation_all').read()[0]

    def action_open_selected_conversation(self):
        self.ensure_one()
        if not self.selected_conversation_id:
            return self.action_reload_dashboard()
        return {
            'type': 'ir.actions.act_window',
            'name': self.selected_conversation_id.display_name,
            'res_model': 'page.fm.conversation',
            'res_id': self.selected_conversation_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_selected_partner(self):
        self.ensure_one()
        if not self.selected_conversation_id:
            return self.action_reload_dashboard()
        return self.selected_conversation_id.action_open_partner()

    def action_open_selected_orders(self):
        self.ensure_one()
        if not self.selected_conversation_id:
            return self.action_reload_dashboard()
        return self.selected_conversation_id.action_open_partner_orders()

    def action_open_selected_on_pancake(self):
        self.ensure_one()
        if not self.selected_conversation_id:
            return self.action_reload_dashboard()
        return self.selected_conversation_id.action_open_on_pancake()
