from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    dac_role = fields.Selection(
        related='user_id.dac_role',
        string='Vai trò DAC',
        readonly=False,
        related_sudo=False,
        groups='base.group_system',
        help='Vai trò của tài khoản người dùng liên kết với nhân viên này.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if self.env.context.get('salary_simulation'):
            return employees
        # Only provision newly created employees without an explicit user link.
        # Creating an employee from the user form already supplies user_id.
        for employee in employees.filtered(lambda record: not record.user_id):
            employee._dac_create_internal_user()
        return employees

    def _dac_create_internal_user(self):
        self.ensure_one()
        # HR officers can create employees but cannot create res.users directly.
        # Elevate only provisioning; never copy caller-supplied groups or defaults.
        Users = self.env['res.users'].sudo().with_context(
            {key: value for key, value in self.env.context.items()
             if not key.startswith('default_')},
            active_test=False,
            no_reset_password=True,
            mail_create_nosubscribe=True,
        )
        login = (self.work_email or '').strip()
        if login:
            if Users.search_count([('login', '=ilike', login)]):
                raise ValidationError(_(
                    'Email công việc %s đã được dùng làm tên đăng nhập. '
                    'Hãy chọn tài khoản đó tại trường Người dùng liên quan '
                    'hoặc sử dụng email khác.', login,
                ))
        else:
            base_login = 'employee.%s' % self.id
            login = base_login
            suffix = 1
            while Users.search_count([('login', '=', login)]):
                login = '%s.%s' % (base_login, suffix)
                suffix += 1
        user = Users.create({
            'name': self.name,
            'login': login,
            'email': self.work_email or False,
            'partner_id': self.work_contact_id.id,
            'company_id': self.company_id.id,
            'company_ids': [(6, 0, self.company_id.ids)],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
            'active': self.active,
            'create_employee': False,
        })
        self.user_id = user

    def action_dac_create_user(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Chỉ quản trị viên được tạo tài khoản tại đây.'))
        self.check_access('write')
        if not self.user_id:
            self._dac_create_internal_user()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
