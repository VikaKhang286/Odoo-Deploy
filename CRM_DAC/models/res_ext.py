import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.addons.dac_erp.models.phone_utils import normalize_phone_vn

_logger = logging.getLogger(__name__)

class ResUsers(models.Model):
    _inherit = 'res.users'
    
    # Field chính - đang dùng trong code
    pancake_id = fields.Char(string="Pancake Admin ID", index=True, copy=False)

    
    # Field mới - phân biệt rõ ràng 2 loại ID
    pancake_uuid = fields.Char(string="Pancake UUID (Đúng)", index=True, copy=False,
                                help="UUID từ creator.id - Định dạng: bd901904-38fd-4e4d-a839-1adc1e651f54")
    pancake_number_id = fields.Char(string="Pancake number ID (Số)", index=True, copy=False,
                                 help="id số - Định dạng: 741331342729875")
    
    @api.model
    def find_by_pancake_id(self, pancake_id_value):
        """
        Tìm user theo Pancake ID - kiểm tra cả 3 field:
        - pancake_id
        - pancake_uuid  
        - pancake_number_id
        
        Returns: res.users recordset (empty hoặc 1 record)
        """
        if not pancake_id_value:
            return self.browse()
        
        user = self.sudo().search([
            '|', '|',
            ('pancake_id', '=', pancake_id_value),
            ('pancake_uuid', '=', pancake_id_value),
            ('pancake_number_id', '=', pancake_id_value)
        ], limit=1)
        
        if user:
            # Log để biết tìm được từ field nào
            matched_field = 'pancake_id' if user.pancake_id == pancake_id_value else \
                           'pancake_uuid' if user.pancake_uuid == pancake_id_value else \
                           'pancake_number_id'
            _logger.debug(f"Found user {user.name} by {matched_field}={pancake_id_value[:8]}...")
        
        return user

class ResPartner(models.Model):
    _inherit = 'res.partner'

    # === PANCAKE CUSTOMER LINK ===
    pancake_id = fields.Char(string="Pancake Customer ID", index=True, copy=False)

    # Bảng alias: nhiều Pancake UUID → 1 partner
    pancake_customer_ids = fields.One2many(
        'page.fm.customer', 'partner_id',
        string='Pancake Customer IDs',
        help='Tất cả Pancake UUID được liên kết với khách hàng này',
    )

    # === PHONE NORMALIZATION ===
    phone_normalized = fields.Char(
        string='SĐT chuẩn hoá',
        compute='_compute_phone_normalized',
        store=True,
        index=True,
        copy=False,
        help='Số điện thoại đã chuẩn hoá về dạng 0XXXXXXXXX (VN)',
    )

    @api.depends('phone')
    def _compute_phone_normalized(self):
        for p in self:
            p.phone_normalized = normalize_phone_vn(p.phone)

    conversation_ids = fields.One2many(
        'page.fm.conversation', 'partner_id', string='Conversations'
    )
    conversation_count = fields.Integer(
        string='Conversations', compute='_compute_conversation_count'
    )
    is_pancake_customer = fields.Boolean(
        string='Khách từ Pancake', compute='_compute_is_pancake_customer'
    )
    pancake_icon_html = fields.Html(
        string='',
        compute='_compute_pancake_icon_html',
        sanitize=False,
        store=False,
    )
    is_new_customer = fields.Boolean(
        string='Khách hàng mới', compute='_compute_is_new_customer',
        help="Khách mới liên hệ trong vòng 7 ngày và chưa có đơn hàng nào."
    )

    # === PANCAKE TAGS ===
    pancake_tag_ids = fields.Many2many(
        'page.fm.tag',
        'res_partner_pancake_tag_rel',
        'partner_id',
        'tag_id',
        string="Thẻ từ Pancake",
        help="Tags được đồng bộ từ conversation mới nhất trên Pancake"
    )

    def _compute_conversation_count(self):
        read_group = self.env['page.fm.conversation'].read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'], ['partner_id']
        )
        map_count = {r['partner_id'][0]: r['partner_id_count'] for r in read_group}
        for p in self:
            p.conversation_count = map_count.get(p.id, 0)

    def _compute_is_pancake_customer(self):
        for p in self:
            p.is_pancake_customer = bool(p.conversation_count)

    def _compute_pancake_icon_html(self):
        icon = (
            '<span title="Khách từ Pancake" '
            'style="color:#0084ff;font-size:13px;vertical-align:middle;">'
            '<i class="fa fa-comments"></i></span>'
        )
        for p in self:
            p.pancake_icon_html = icon if p.conversation_count else ''

    def _compute_is_new_customer(self):
        one_week_ago = fields.Datetime.now() - timedelta(days=7)
        for partner in self:
            is_recent = bool(partner.create_date and partner.create_date >= one_week_ago)
            if not is_recent:
                first_conv = self.env['page.fm.conversation'].sudo().search([
                    ('partner_id', '=', partner.id)
                ], order='create_date asc', limit=1)
                if first_conv and first_conv.create_date and first_conv.create_date >= one_week_ago:
                    is_recent = True
            
            if not is_recent:
                partner.is_new_customer = False
                continue
            
            orders = self.env['sale.order'].sudo().search_count([
                ('partner_id', 'child_of', partner.commercial_partner_id.id),
                ('state', '!=', 'cancel')
            ])
            partner.is_new_customer = (orders == 0)

    def action_view_conversations(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Conversations'),
            'res_model': 'page.fm.conversation',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('partner_id', 'child_of', self.commercial_partner_id.id)],
            'context': {'search_default_partner_id': self.id},
        }
        return action

    def action_view_partner_orders(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        domain = [('partner_id', 'child_of', commercial.id)]
        count = self.env['sale.order'].search_count(domain)
        if not count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Chưa có đơn hàng'),
                    'message': _('Khách hàng này chưa có đơn hàng nào trên hệ thống.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        # Sử dụng action custom của DAC thay vì action gốc của Odoo
        action = self.env.ref('dac_erp.dac_sale_order_custom_action').read()[0]
        action['domain'] = domain
        action['context'] = {'search_default_partner_id': commercial.id}
        return action
    
    
    responsible_user_id = fields.Many2one(
        'res.users', string="Người phụ trách (Pancake)", index=True, copy=False
    )
    participant_user_ids = fields.Many2many(
        'res.users', 'res_partner_conv_user_rel', 'partner_id', 'user_id',
        string="Nhóm phụ trách (Pancake)", copy=False
    )

    def sync_staff_from_conversations(self):
        """Đẩy owner/participants mới nhất từ hội thoại sang khách hàng.
        - responsible_user_id: Ghi đè (người phụ trách hiện tại)
        - participant_user_ids: MERGE (nhóm phụ trách - chỉ thêm, không xóa)
        """
        Conv = self.env['page.fm.conversation'].sudo()
        for partner in self:
            conv = Conv.search(
                [('partner_id', '=', partner.id)],
                order='updated_at_fm desc, id desc', limit=1
            )
            vals = {}
            if conv:
                # Người phụ trách hiện tại - ghi đè
                vals['responsible_user_id'] = conv.owner_id.id or False
                
                # Nhóm phụ trách - MERGE (chỉ thêm, không xóa)
                if conv.participant_user_ids:
                    old_participants = set(partner.participant_user_ids.ids)
                    new_participants = set(conv.participant_user_ids.ids)
                    merged_participants = old_participants.union(new_participants)
                    vals['participant_user_ids'] = [(6, 0, list(merged_participants))]
                    
            if vals:
                partner.write(vals)
                if 'participant_user_ids' in vals:
                    _logger.debug(f"✅ Synced staff to partner {partner.name}: owner={conv.owner_id.name if conv and conv.owner_id else 'None'}, participants={len(merged_participants) if conv else 0}")
    
    
    def sync_tags_from_conversations(self):
        """Đồng bộ tags từ conversation mới nhất sang khách hàng."""
        Conv = self.env['page.fm.conversation'].sudo()
        for partner in self:
            # Lấy conversation mới nhất có tags
            conv = Conv.search(
                [('partner_id', '=', partner.id), ('pancake_tag_ids', '!=', False)],
                order='updated_at_fm desc, id desc', limit=1
            )
            if conv and conv.pancake_tag_ids:
                partner.write({
                    'pancake_tag_ids': [(6, 0, conv.pancake_tag_ids.ids)]
                })
                _logger.debug(f"✅ Synced {len(conv.pancake_tag_ids)} tags from conversation to partner {partner.name}")

                
    _sql_constraints = [
        ('pancake_id_company_uniq',
        'unique(pancake_id, company_id)',
        'Pancake Customer ID must be unique per company.')
    ]


class SaleOrderExt(models.Model):
    _inherit = 'sale.order'

    partner_is_pancake = fields.Boolean(
        related='partner_id.is_pancake_customer',
        string='Khách từ Pancake',
        store=False,
    )
    partner_pancake_icon_html = fields.Html(
        string='',
        compute='_compute_partner_pancake_icon_html',
        sanitize=False,
        store=False,
    )

    @api.depends('conversation_count')
    def _compute_partner_pancake_icon_html(self):
        icon = (
            '<span title="Khách từ Pancake" '
            'style="color:#0084ff;font-size:13px;vertical-align:middle;">'
            '<i class="fa fa-comments"></i></span>'
        )
        for order in self:
            order.partner_pancake_icon_html = icon if order.conversation_count > 0 else ''

    def action_open_create_order_wizard_from_list(self):
        """Mở wizard tạo đơn từ nút trong danh sách đơn hàng."""
        return self.env['dac.create.order.wizard'].sudo().action_open_wizard()

    def action_open_invoice_upload_from_list(self):
        """Mở dialog upload hoá đơn ảnh để tạo đơn hàng mới từ list view."""
        return {
            'type': 'ir.actions.client',
            'tag': 'sale_ai_invoice_reader.open_upload_dialog',
            'params': {},
        }