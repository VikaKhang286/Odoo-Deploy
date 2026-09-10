from odoo import models, fields, api

# 7 profile vai trò DAC — hiển thị trong dropdown "Vai trò DAC" duy nhất.
_DAC_ROLE_SEL = [
    ('manager',           'DAC Manager'),
    ('sale_all',          'DAC Sale (Xem tất cả đơn)'),
    ('sale',              'DAC Sale (Đơn của mình)'),
    ('design',            'DAC Design'),
    ('production',        'DAC Production'),
    ('design_production', 'DAC Design + Production'),
    ('full_stack',        'DAC Full-stack'),
]

_DAC_XMLIDS = {
    'manager':           'dac_erp.group_dac_erp_manager',
    'sale_all':          'dac_erp.group_dac_erp_sale_all',
    'sale':              'dac_erp.group_dac_erp_sale',
    'design':            'dac_erp.group_dac_erp_design',
    'production':        'dac_erp.group_dac_erp_production',
    'design_production': 'dac_erp.group_dac_erp_design_production',
    'full_stack':        'dac_erp.group_dac_erp_full_stack',
}

# Thứ tự NHẬN DIỆN khi compute (tách khỏi thứ tự hiển thị để bền vững):
# combo nhiều implied nhất phải đứng trước nhóm con của nó, nếu không
# một full_stack user (có cả sale/design/production) sẽ bị nhận nhầm.
_DAC_ROLE_PRIORITY = [
    'full_stack',
    'design_production',
    'manager',
    'sale_all',
    'design',
    'production',
    'sale',
]


class ResUsersDac(models.Model):
    _inherit = 'res.users'

    dac_job_id = fields.Many2one(
        related='employee_id.job_id',
        string='Vị trí công việc',
        readonly=False,
        related_sudo=False,
    )

    dac_role = fields.Selection(
        _DAC_ROLE_SEL,
        string='Vai trò DAC',
        compute='_compute_dac_role',
        inverse='_set_dac_role',
        store=False,
    )
    # Tài khoản dùng chung: nhiều người thật dùng cùng một credentials Odoo.
    # Khi True, agent KHÔNG được nhắc đích danh vì không biết ai đang cầm điện thoại.
    dac_is_shared_account = fields.Boolean(
        string='Tài khoản dùng chung',
        default=False,
        help='Đánh dấu nếu nhiều nhân viên thật dùng chung tài khoản này. '
             'Agent OpenClaw sẽ bỏ qua nhắc việc cá nhân cho tài khoản này.',
    )

    def _dac_groups(self):
        return {k: self.env.ref(v) for k, v in _DAC_XMLIDS.items()}

    @api.model
    def _dac_exact_role_domain(self, role):
        # Match the same precedence as _compute_dac_role, including combo roles.
        groups = self._dac_groups()
        higher_roles = _DAC_ROLE_PRIORITY[:_DAC_ROLE_PRIORITY.index(role)]
        return [
            ('active', '=', True),
            ('share', '=', False),
            ('groups_id', 'in', [groups[role].id]),
            ('groups_id', 'not in', [groups[key].id for key in higher_roles]),
        ]

    @api.depends('groups_id')
    def _compute_dac_role(self):
        dac = self._dac_groups()
        for user in self:
            user.dac_role = next(
                (k for k in _DAC_ROLE_PRIORITY if dac[k] in user.groups_id),
                False,
            )

    def _set_dac_role(self):
        # Tự resolve implied_ids: gán cùng lúc target group + toàn bộ group nó implies.
        # Lý do: Odoo không luôn cascade implied_ids khi (3,) và (4,) trộn trong cùng 1 write,
        # khiến combo group thêm vào nhưng các group con không kèm theo.
        dac = self._dac_groups()
        all_ids = {g.id for g in dac.values()}
        for user in self:
            non_dac = [gid for gid in user.groups_id.ids if gid not in all_ids]
            target_ids = set(non_dac)
            if user.dac_role:
                target = dac[user.dac_role]
                target_ids.add(target.id)
                target_ids.update(target.trans_implied_ids.ids)
            user.write({'groups_id': [(6, 0, list(target_ids))]})

    # ------------------------------------------------------------------
    # Helper phân quyền tập trung — thay cho has_group(...) rải rác.
    # ------------------------------------------------------------------
    def _dac_is_admin(self):
        return self.has_group('base.group_system')

    def _dac_is_manager(self):
        return self.has_group('dac_erp.group_dac_erp_manager')

    def _dac_is_sale(self):
        return self.has_group('dac_erp.group_dac_erp_sale')

    def _dac_is_design(self):
        return self.has_group('dac_erp.group_dac_erp_design')

    def _dac_is_production(self):
        return self.has_group('dac_erp.group_dac_erp_production')

    def _dac_is_worker_only(self):
        """Thợ thiết kế/sản xuất thuần — không phải manager/sale/admin."""
        return (self._dac_is_design() or self._dac_is_production()) and \
            not (self._dac_is_manager() or self._dac_is_sale() or self._dac_is_admin())
