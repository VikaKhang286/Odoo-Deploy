import logging
import re

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _dac_archive_obsolete_category_views(self):
        """Keep legacy customizations recoverable when their field is absent.

        Run before loading the employee form: validating a new extension also
        validates existing sibling extensions left in the production database.
        """
        field_name = 'dac_employee_category'
        if field_name in self._fields:
            return
        views = self.env['ir.ui.view'].with_context(lang=None).search([
            ('model', '=', 'hr.employee'),
            ('active', '=', True),
            ('inherit_id', '!=', False),
            ('mode', '=', 'extension'),
            ('arch_db', 'ilike', field_name),
        ])
        token = re.compile(r'\b%s\b' % field_name)
        obsolete = views.filtered(lambda view: any(
            token.search(value)
            for node in etree.fromstring(view.arch_db).iter()
            for value in node.attrib.values()
        ))
        if obsolete:
            _logger.warning(
                'Archiving employee extension views referencing missing %s: %s. '
                'View definitions are preserved for recovery.',
                field_name, [(view.id, view.name) for view in obsolete],
            )
            obsolete.write({'active': False})

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
