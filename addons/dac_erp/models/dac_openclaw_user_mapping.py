import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DacOpenclawUserMapping(models.Model):
    _name = 'dac.openclaw.user.mapping'
    _description = 'OpenClaw User Mapping'
    _order = 'user_id, channel, target'

    user_id = fields.Many2one(
        'res.users',
        string='Odoo User',
        required=True,
        ondelete='cascade',
        index=True,
    )
    channel = fields.Selection([
        ('telegram', 'Telegram'),
        ('zalo', 'Zalo OA'),
        ('zalouser', 'Zalo User'),
        ('facebook', 'Facebook'),
        ('webchat', 'Web Chat'),
        ('other', 'Other'),
    ], string='Channel', required=True, default='telegram', index=True)
    target = fields.Char(string='Target', required=True, index=True)
    notify_enabled = fields.Boolean(string='Nhận thông báo', default=True)
    digest_enabled = fields.Boolean(string='Nhận daily digest', default=True)
    deadline_enabled = fields.Boolean(string='Nhận deadline reminder', default=True)
    role = fields.Selection([
        ('employee', 'Employee'),
        ('manager', 'Manager'),
        ('admin', 'Admin'),
    ], string='OpenClaw Role', required=True, default='employee', index=True)
    manager_user_ids = fields.Many2many(
        'res.users',
        'dac_openclaw_mapping_manager_rel',
        'mapping_id',
        'user_id',
        string='Manager Scope Users',
        help='Danh sách nhân viên mà mapping manager được phép xem qua OpenClaw.',
    )
    active = fields.Boolean(default=True)
    note = fields.Text(string='Ghi chú')

    display_name_label = fields.Char(
        string='Display Label',
        compute='_compute_display_name_label',
        store=False,
    )

    _sql_constraints = [
        ('uniq_channel_target', 'unique(channel, target)', 'Channel + target phải là duy nhất.'),
        ('uniq_user_channel_target', 'unique(user_id, channel, target)', 'Mapping đã tồn tại cho user/channel/target này.'),
    ]

    @api.depends('user_id', 'channel', 'target')
    def _compute_display_name_label(self):
        for rec in self:
            parts = [rec.user_id.name or '', rec.channel or '', rec.target or '']
            rec.display_name_label = ' / '.join([p for p in parts if p])

    @api.constrains('target')
    def _check_target_not_blank(self):
        for rec in self:
            if not (rec.target or '').strip():
                raise ValidationError('Target không được để trống.')

    @api.model
    def resolve_mapping(self, channel, target, active_only=True):
        channel = (channel or '').strip()
        target = (target or '').strip()
        if not channel or not target:
            raise ValidationError('channel và target là bắt buộc.')

        domain = [('channel', '=', channel), ('target', '=', target)]
        if active_only:
            domain.append(('active', '=', True))
        mappings = self.sudo().search(domain)
        if not mappings:
            return self.browse()
        if len(mappings) > 1:
            raise ValidationError('Tồn tại nhiều mapping cho cùng channel/target.')
        return mappings[0]

    @api.model
    def _get_employee_delivery_mapping(self, user, notify_type=None):
        """Tra mapping nhận thông báo của một user.

        :param user: res.users record
        :param notify_type: 'notify' | 'digest' | 'deadline' | None
            Nếu cung cấp, lọc thêm theo flag tương ứng.
            - 'notify'   → notify_enabled = True  (thông báo task, assign)
            - 'digest'   → digest_enabled = True   (daily digest)
            - 'deadline' → deadline_enabled = True (nhắc deadline/remind_at)
        :return: recordset dac.openclaw.user.mapping — có thể rỗng nếu không tìm thấy.
            Nhiều mapping → trả tất cả (caller tự quyết dùng cái nào / gửi tất).
        """
        if not user or not user.id:
            return self.sudo().browse()

        domain = [
            ('user_id', '=', user.id),
            ('active', '=', True),
        ]
        _notify_flag_map = {
            'notify': 'notify_enabled',
            'digest': 'digest_enabled',
            'deadline': 'deadline_enabled',
        }
        if notify_type in _notify_flag_map:
            domain.append((_notify_flag_map[notify_type], '=', True))

        return self.sudo().search(domain)

    @api.model
    def _install_seed_data(self):
        """Tạo mapping seed cho Dương Tuấn Kiệt nếu chưa tồn tại.

        Được gọi từ data/openclaw_user_mapping_seed.xml khi install/upgrade.
        Hàm tự kiểm tra idempotency — gọi nhiều lần không tạo thêm record.
        Dùng raw SQL để lookup tên vì ORM search partner_id.name có quirk
        trong context <function> XML loading.
        """
        # Lookup bằng raw SQL — đáng tin cậy hơn ORM search cho related field
        # Không lọc theo u.active — user có thể đang archived trong một số môi trường
        self.env.cr.execute(
            """
            SELECT u.id FROM res_users u
            JOIN res_partner rp ON rp.id = u.partner_id
            WHERE rp.name = %s
            ORDER BY u.active DESC, u.id
            LIMIT 1
            """,
            ['Dương Tuấn Kiệt'],
        )
        row = self.env.cr.fetchone()
        if not row:
            _logger.warning(
                'openclaw seed: không tìm thấy user "Dương Tuấn Kiệt", bỏ qua seed data.'
            )
            return
        user = self.env['res.users'].sudo().browse(row[0])

        existing = self.sudo().search([
            ('channel', '=', 'zalouser'),
            ('target', '=', '3360952219918690445'),
        ], limit=1)
        if existing:
            _logger.info('openclaw seed: mapping đã tồn tại, bỏ qua.')
            return

        self.sudo().create({
            'user_id': user.id,
            'channel': 'zalouser',
            'target': '3360952219918690445',
            'active': True,
            'notify_enabled': True,
            'digest_enabled': True,
            'deadline_enabled': True,
            'note': 'Seed: Dương Tuấn Kiệt — Zalo personal',
        })
        _logger.info(
            'openclaw seed: đã tạo mapping zalouser cho user %s (id=%s)', user.name, user.id
        )

    @api.model
    def resolve_internal_recipient(self, channel, target):
        """Resolve channel + target → Odoo internal staff user (JSON-serializable).

        This is a REVERSE LOOKUP for INTERNAL RECIPIENTS only — i.e. staff
        members who receive OpenClaw notifications on their personal messaging
        accounts (e.g. Zalo personal of Dương Tuấn Kiệt).  It does NOT map
        customer/Pancake/Page.fm conversation participants.

        Rules:
          - Only active mappings are considered.
          - DB unique constraint on (channel, target) guarantees at most one
            record per pair; the search returns 0 or 1 results by design.
          - Returns found=False dict (never raises) when no mapping exists.
          - Returns found=False when mapping exists but is inactive.

        :param channel: str — e.g. 'zalouser', 'telegram'
        :param target:  str — the staff member's external user ID in that channel
        :return: {found, user_id, user_name, role, mapping_id, channel, target}
        :raises ValidationError: only when channel or target are blank
        """
        channel = (channel or '').strip()
        target = (target or '').strip()
        if not channel:
            raise ValidationError('channel là bắt buộc.')
        if not target:
            raise ValidationError('target là bắt buộc.')

        mapping = self.sudo().search([
            ('channel', '=', channel),
            ('target', '=', target),
            ('active', '=', True),
        ], limit=1)

        if not mapping:
            _logger.info(
                'resolve_internal_recipient: không tìm thấy mapping %s/%s', channel, target
            )
            return {
                'found': False,
                'user_id': None,
                'user_name': None,
                'role': None,
                'mapping_id': None,
                'channel': channel,
                'target': target,
            }

        _logger.info(
            'resolve_internal_recipient: %s/%s → user=%s (id=%s)',
            channel, target, mapping.user_id.name, mapping.user_id.id,
        )
        return {
            'found': True,
            'user_id': mapping.user_id.id,
            'user_name': mapping.user_id.name,
            'role': mapping.role,
            'mapping_id': mapping.id,
            'channel': channel,
            'target': target,
        }

    def get_scope_user_ids(self, include_self=True):
        self.ensure_one()
        if self.role == 'admin':
            return None
        if self.role == 'manager':
            user_ids = set(self.manager_user_ids.ids)
            if include_self and self.user_id:
                user_ids.add(self.user_id.id)
            return sorted(user_ids)
        return [self.user_id.id] if self.user_id else []
