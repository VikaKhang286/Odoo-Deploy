from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestEmployeeUserProvisioning(TransactionCase):
    def test_batch_email_and_no_email(self):
        employees = self.env['hr.employee'].create([
            {'name': 'DAC With Email', 'work_email': 'dac.provision@example.invalid'},
            {'name': 'DAC Without Email'},
        ])
        self.assertEqual(employees[0].user_id.login, 'dac.provision@example.invalid')
        self.assertEqual(employees[1].user_id.login, 'employee.%s' % employees[1].id)
        for employee in employees:
            user = employee.user_id
            self.assertTrue(user.has_group('base.group_user'))
            self.assertFalse(user.has_group('base.group_system'))
            self.assertFalse(user.share)
            self.assertEqual(user.partner_id, employee.work_contact_id)
            self.assertEqual(user.company_ids, employee.company_id)
            self.assertEqual(user.employee_id, employee)

    def test_explicit_user_and_reverse_creation(self):
        Users = self.env['res.users'].with_context(no_reset_password=True)
        user = Users.create({
            'name': 'DAC Existing User', 'login': 'dac.existing.test',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        count = Users.search_count([])
        employee = self.env['hr.employee'].create({'name': user.name, 'user_id': user.id})
        self.assertEqual(employee.user_id, user)
        self.assertEqual(Users.search_count([]), count)
        reverse = Users.create({
            'name': 'DAC Reverse', 'login': 'dac.reverse.test', 'create_employee': True,
        })
        self.assertEqual(len(reverse.employee_ids), 1)
        self.assertEqual(Users.search_count([]), count + 1)

    def test_duplicate_archived_login_rejected(self):
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Existing', 'login': 'dac.duplicate@example.invalid', 'active': False,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['hr.employee'].create({
                'name': 'Duplicate', 'work_email': 'DAC.DUPLICATE@example.invalid',
            })

    def test_hr_officer_cannot_inherit_admin_defaults(self):
        officer = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'HR Officer', 'login': 'dac.hr.officer.test',
            'groups_id': [(6, 0, [self.env.ref('hr.group_hr_user').id])],
        })
        employee = self.env['hr.employee'].with_user(officer).with_context(
            default_groups_id=[(6, 0, [self.env.ref('base.group_system').id])],
        ).create({'name': 'Officer Created'})
        self.assertTrue(employee.user_id.sudo().has_group('base.group_user'))
        self.assertFalse(employee.user_id.sudo().has_group('base.group_system'))

    def test_existing_employee_write_does_not_provision(self):
        employee = self.env['hr.employee'].with_context(salary_simulation=True).create({
            'name': 'Existing Unlinked',
        })
        self.assertFalse(employee.user_id)
        employee.write({'work_email': 'dac.old.employee@example.invalid'})
        self.assertFalse(employee.user_id)
