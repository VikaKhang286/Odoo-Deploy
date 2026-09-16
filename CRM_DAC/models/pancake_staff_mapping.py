import logging
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PAGES_FM_PUBLIC_API_V2_BASE_URL = "https://pages.fm/api/public_api/v2"


class PancakeStaffMapping(models.Model):
    _name = 'pancake.staff.mapping'
    _description = 'Ánh xạ Nhân viên Pancake → Tài khoản Odoo'
    _order = 'name asc'

    pancake_staff_id = fields.Char(
        string='Pancake Staff ID',
        index=True,
        readonly=True,
        help='ID nhân viên từ Pancake (UUID hoặc numeric)',
    )
    name = fields.Char(
        string='Tên nhân viên Pancake',
        readonly=True,
    )
    email = fields.Char(
        string='Email Pancake',
        readonly=True,
    )
    odoo_user_id = fields.Many2one(
        'res.users',
        string='Tài khoản Odoo',
        ondelete='set null',
        domain=[('share', '=', False)],
        help='Chọn tài khoản Odoo tương ứng với nhân viên Pancake này',
    )
    message_count = fields.Integer(
        string='Số tin nhắn',
        compute='_compute_message_count',
        store=False,
    )
    already_mapped = fields.Boolean(
        string='Đã mapping',
        compute='_compute_already_mapped',
        store=False,
    )

    _sql_constraints = [
        ('pancake_staff_id_uniq', 'unique(pancake_staff_id)',
         'Pancake Staff ID phải là duy nhất!'),
    ]

    @api.depends('pancake_staff_id')
    def _compute_message_count(self):
        for rec in self:
            if rec.pancake_staff_id:
                rec.message_count = self.env['page.fm.message'].search_count([
                    ('staff_id_fm', '=', rec.pancake_staff_id),
                ])
            else:
                rec.message_count = 0

    @api.depends('odoo_user_id')
    def _compute_already_mapped(self):
        for rec in self:
            rec.already_mapped = bool(rec.odoo_user_id)

    def action_collect_from_messages(self):
        """Thu thập nhân viên Pancake từ tin nhắn đã đồng bộ trong DB."""
        Message = self.env['page.fm.message'].sudo()
        # Lấy tất cả (staff_id_fm, staff_name_fm) duy nhất có staff_id_fm
        self.env.cr.execute("""
            SELECT DISTINCT staff_id_fm, MAX(staff_name_fm) AS staff_name_fm
            FROM page_fm_message
            WHERE staff_id_fm IS NOT NULL AND staff_id_fm != ''
            GROUP BY staff_id_fm
        """)
        rows = self.env.cr.fetchall()

        created = 0
        updated = 0
        for staff_id, staff_name in rows:
            existing = self.search([('pancake_staff_id', '=', staff_id)], limit=1)
            if existing:
                if staff_name and not existing.name:
                    existing.write({'name': staff_name})
                updated += 1
            else:
                self.create({
                    'pancake_staff_id': staff_id,
                    'name': staff_name or staff_id,
                })
                created += 1

        # Cũng thu thập từ email lưu trong res.users đã có pancake_id
        ResUsers = self.env['res.users'].sudo()
        users_with_pancake = ResUsers.search([
            ('pancake_id', '!=', False),
        ])
        for user in users_with_pancake:
            existing = self.search([
                ('pancake_staff_id', '=', user.pancake_id),
            ], limit=1)
            if existing:
                if not existing.odoo_user_id:
                    existing.write({'odoo_user_id': user.id})
                if not existing.email and user.email:
                    existing.write({'email': user.email})
            # Nếu chưa có thì không tự tạo từ res.users — chỉ enrich nếu đã có

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hoàn tất',
                'message': f'Đã thu thập {created} nhân viên mới, cập nhật {updated} nhân viên từ tin nhắn.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_apply_mapping(self):
        """Áp dụng mapping: ghi pancake_id vào res.users tương ứng."""
        applied = 0
        skipped = 0
        for rec in self:
            if not rec.odoo_user_id or not rec.pancake_staff_id:
                skipped += 1
                continue
            user = rec.odoo_user_id.sudo()
            user.write({'pancake_id': rec.pancake_staff_id})
            if rec.email and not user.email:
                user.write({'email': rec.email})
            applied += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Áp dụng mapping thành công',
                'message': f'Đã cập nhật pancake_id cho {applied} tài khoản Odoo. Bỏ qua {skipped} (chưa chọn tài khoản).',
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def action_collect_and_open(self):
        """Button từ menu: thu thập rồi mở list view."""
        self.sudo().action_collect_from_messages()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nhân viên Pancake',
            'res_model': 'pancake.staff.mapping',
            'view_mode': 'list,form',
            'target': 'current',
        }
