from datetime import timedelta
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo import fields

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


READ_KEY = 'task-read-test-key'
WRITE_KEY = 'task-write-test-key'


@tagged('post_install', '-at_install')
class TestOpenclawTaskIntegration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', READ_KEY)
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', WRITE_KEY)
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.openclaw_base_url', 'https://openclaw.test')

        group_user = cls.env.ref('base.group_user')
        cls.employee = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Employee OC',
            'login': 'employee_oc@test.com',
            'email': 'employee_oc@test.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Manager OC',
            'login': 'manager_oc@test.com',
            'email': 'manager_oc@test.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.admin = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin OC',
            'login': 'admin_oc@test.com',
            'email': 'admin_oc@test.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'OpenClaw Partner'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'user_id': cls.employee.id,
            'order_state_custom': 'quotation',
        })
        cls.employee_mapping = cls.env['dac.openclaw.user.mapping'].sudo().create({
            'user_id': cls.employee.id,
            'channel': 'telegram',
            'target': '@employee',
            'role': 'employee',
        })
        cls.manager_mapping = cls.env['dac.openclaw.user.mapping'].sudo().create({
            'user_id': cls.manager.id,
            'channel': 'telegram',
            'target': '@manager',
            'role': 'manager',
            'manager_user_ids': [(6, 0, [cls.employee.id])],
        })
        cls.admin_mapping = cls.env['dac.openclaw.user.mapping'].sudo().create({
            'user_id': cls.admin.id,
            'channel': 'telegram',
            'target': '@admin',
            'role': 'admin',
        })

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _run(self, method, *args, **kwargs):
        return self.controller._run_mcp_handler(method, *args, **kwargs)

    def _payload(self, **extra):
        payload = {'channel': 'telegram', 'target': '@employee'}
        payload.update(extra)
        return payload

    def test_resolve_user_success(self):
        payload, code = self._run(
            self.controller._dispatch_openclaw_resolve_user,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload={'channel': 'telegram', 'target': '@employee'},
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload['data']['user']['id'], self.employee.id)
        self.assertEqual(payload['data']['role'], 'employee')

    def test_tasks_self_forces_current_user(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Self Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
        })
        other = self.env['dac.work.task'].sudo().create({
            'name': 'Other Task',
            'order_id': self.order.id,
            'assigned_user_id': self.manager.id,
        })
        payload, code = self._run(
            self.controller._dispatch_openclaw_tasks_self,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload={'channel': 'telegram', 'target': '@employee', 'filters': {'assigned_user_id': self.manager.id}},
        )
        self.assertEqual(code, 200)
        ids = {item['id'] for item in payload['items']}
        self.assertIn(task.id, ids)
        self.assertNotIn(other.id, ids)

    def test_tasks_employee_denied_for_employee_role(self):
        payload, code = self._run(
            self.controller._dispatch_openclaw_tasks_employee,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload={'channel': 'telegram', 'target': '@employee', 'employee': {'user_id': self.manager.id}},
        )
        self.assertEqual(code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_scope')

    def test_tasks_employee_allowed_for_manager_scope(self):
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Managed Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
        })
        payload, code = self._run(
            self.controller._dispatch_openclaw_tasks_employee,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload={'channel': 'telegram', 'target': '@manager', 'employee': {'user_id': self.employee.id}},
        )
        self.assertEqual(code, 200)
        ids = {item['id'] for item in payload['items']}
        self.assertIn(task.id, ids)

    def test_team_summary_returns_summary(self):
        self.env['dac.work.task'].sudo().create([
            {'name': 'S1', 'order_id': self.order.id, 'assigned_user_id': self.employee.id, 'priority': 'urgent'},
            {'name': 'S2', 'order_id': self.order.id, 'assigned_user_id': self.employee.id, 'state': 'in_progress'},
        ])
        payload, code = self._run(
            self.controller._dispatch_openclaw_team_summary,
            env=self.env,
            headers=self._headers(READ_KEY),
            payload={'channel': 'telegram', 'target': '@manager', 'filters': {}},
        )
        self.assertEqual(code, 200)
        self.assertGreaterEqual(payload['data']['summary']['total'], 2)

    def test_cron_daily_digest_creates_notification_log(self):
        self.env['dac.work.task'].sudo().create({
            'name': 'Digest Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            self.env['dac.work.task'].sudo().cron_send_openclaw_daily_digest()
        log = self.env['dac.openclaw.notification.log'].sudo().search([('event_type', '=', 'daily_digest')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.status, 'sent')

    def test_send_payload_reuses_existing_event_id_log(self):
        service = self.env['dac.openclaw.notification.service']
        payload = service.build_payload(
            event_type='daily_digest',
            mapping=self.employee_mapping,
            tasks=self.env['dac.work.task'],
            summary={'total': 0},
            event_id='fixed-event-id',
        )
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            first = service.send_payload('/hooks/odoo-daily-digest', payload, mapping=self.employee_mapping)
            second = service.send_payload('/hooks/odoo-daily-digest', payload, mapping=self.employee_mapping)
        self.assertEqual(first.id, second.id)
        count = self.env['dac.openclaw.notification.log'].sudo().search_count([('event_id', '=', 'fixed-event-id')])
        self.assertEqual(count, 1)

    # ── Cron reminder tests ───────────────────────────────────────────

    def test_cron_reminder_fires_for_passed_deadline(self):
        """Cron phải gửi reminder cho task có deadline đã qua, chưa nhắc."""
        past = fields.Datetime.now() - timedelta(hours=1)
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Overdue Reminder Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': past,
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_reminder'),
        ], limit=1)
        self.assertTrue(log, "Phải có notification log cho task_reminder")
        self.assertEqual(log.status, 'sent')
        self.assertTrue(task.x_openclaw_last_reminder_at, "x_openclaw_last_reminder_at phải được set")

    def test_cron_reminder_fires_for_passed_remind_at(self):
        """Khi có remind_at, cron dùng remind_at thay vì deadline."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'remind_at Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(hours=24),  # deadline chưa đến
            'remind_at': now - timedelta(hours=1),  # remind_at đã qua
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_reminder'),
        ], limit=1)
        self.assertTrue(log, "remind_at đã qua → phải được nhắc dù deadline chưa đến")
        self.assertEqual(log.status, 'sent')

    def test_cron_reminder_skips_within_cooldown(self):
        """Task nhắc gần đây (trong cooldown 60 phút) không nhắc lại."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Within Cooldown Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now - timedelta(hours=1),
            # Nhắc 30 phút trước — vẫn trong cooldown 60 phút
            'x_openclaw_last_reminder_at': now - timedelta(minutes=30),
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
            post.assert_not_called()
        reminder_log_count = self.env['dac.openclaw.notification.log'].sudo().search_count([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_reminder'),
        ])
        self.assertEqual(reminder_log_count, 0, "Không gửi lại khi cooldown chưa hết")

    def test_cron_reminder_resends_after_cooldown_expires(self):
        """Task có x_openclaw_last_reminder_at > cooldown thì gửi lại."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Cooldown Expired Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now - timedelta(hours=1),
            # Nhắc 2 giờ trước — đã vượt cooldown 60 phút
            'x_openclaw_last_reminder_at': now - timedelta(hours=2),
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_reminder'),
        ], limit=1)
        self.assertTrue(log, "Phải gửi lại sau khi cooldown hết")
        self.assertEqual(log.status, 'sent')

    def test_cron_reminder_skips_deadline_older_than_48h(self):
        """Task có deadline quá 48 giờ không được nhắc để tránh spam."""
        old_deadline = fields.Datetime.now() - timedelta(hours=49)
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Old Deadline Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': old_deadline,
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
            post.assert_not_called()

    def test_cron_reminder_skips_done_task(self):
        """Task đã done không được nhắc."""
        past = fields.Datetime.now() - timedelta(hours=1)
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Done Task Reminder',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': past,
            'state': 'done',
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
            post.assert_not_called()

    # ── task_assigned notification tests ─────────────────────────────

    def test_task_assigned_notification_on_create(self):
        """Tạo task với assigned_user_id → webhook task_assigned được gửi ngay."""
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            task = self.env['dac.work.task'].sudo().create({
                'name': 'Assigned On Create',
                'order_id': self.order.id,
                'assigned_user_id': self.employee.id,
            })
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_assigned'),
        ], limit=1)
        self.assertTrue(log, "Phải có log task_assigned khi tạo task có assigned_user_id")
        self.assertEqual(log.status, 'sent')

    def test_task_assigned_notification_on_reassign(self):
        """Thay đổi assigned_user_id → webhook task_assigned gửi cho người nhận mới."""
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Reassign Task',
            'order_id': self.order.id,
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            task.write({'assigned_user_id': self.employee.id})
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_assigned'),
        ], limit=1)
        self.assertTrue(log, "Phải có log task_assigned khi giao task cho người mới")

    def test_task_assigned_no_notification_without_mapping(self):
        """Không có mapping → không crash, không tạo log."""
        no_mapping_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No Mapping User',
            'login': 'no_mapping@test.com',
            'email': 'no_mapping@test.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            task = self.env['dac.work.task'].sudo().create({
                'name': 'No Mapping Assign',
                'order_id': self.order.id,
                'assigned_user_id': no_mapping_user.id,
            })
            post.assert_not_called()
        log_count = self.env['dac.openclaw.notification.log'].sudo().search_count([
            ('task_id', '=', task.id),
        ])
        self.assertEqual(log_count, 0)

    def test_task_write_same_user_no_extra_notification(self):
        """Cập nhật field khác (không phải assigned_user_id) → không gửi thêm task_assigned."""
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            task = self.env['dac.work.task'].sudo().create({
                'name': 'Same User Write',
                'order_id': self.order.id,
                'assigned_user_id': self.employee.id,
            })
            call_count_after_create = post.call_count
            task.write({'name': 'Updated Name', 'priority': 'high'})
        self.assertEqual(post.call_count, call_count_after_create,
                         "Cập nhật non-assigned fields không được gửi thêm webhook")

    # ── Deadline warning tests ────────────────────────────────────────

    def test_cron_deadline_warning_fires_for_upcoming_deadline(self):
        """Task có deadline trong 60 phút tới → cảnh báo được gửi."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Upcoming Deadline Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(minutes=60),  # trong cửa sổ 120 phút
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
        log = self.env['dac.openclaw.notification.log'].sudo().search([
            ('task_id', '=', task.id),
            ('event_type', '=', 'task_reminder'),
        ], limit=1)
        self.assertTrue(log, "Phải có log task_reminder cho deadline warning")
        self.assertEqual(log.status, 'sent')
        task.invalidate_recordset()
        self.assertTrue(task.x_openclaw_last_deadline_warning_at,
                        "x_openclaw_last_deadline_warning_at phải được set")

    def test_cron_deadline_warning_skips_overdue(self):
        """Task có deadline đã qua không được xử lý ở đường deadline warning."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Already Overdue Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now - timedelta(hours=1),  # đã qua
        })
        Task = self.env['dac.work.task'].sudo()
        self.assertFalse(
            Task._should_send_deadline_warning(task, now=now),
            "deadline đã qua → không phải deadline warning",
        )

    def test_cron_deadline_warning_skips_beyond_window(self):
        """Task có deadline quá xa (> 120 phút) không được cảnh báo."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Far Future Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(hours=5),  # ngoài cửa sổ 120 phút
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            self.env['dac.work.task'].sudo()._process_openclaw_deadline_warnings(now=now)
            post.assert_not_called()

    def test_cron_deadline_warning_skips_within_cooldown(self):
        """Deadline warning đã gửi gần đây không gửi lại."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Warning Cooldown Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(minutes=60),
            'x_openclaw_last_deadline_warning_at': now - timedelta(minutes=20),  # 20 phút trước
        })
        Task = self.env['dac.work.task'].sudo()
        self.assertFalse(
            Task._should_send_deadline_warning(task, now=now),
            "warning gửi 20 phút trước → còn trong cooldown 60 phút → skip",
        )

    def test_cron_deadline_warning_skips_if_disabled(self):
        """Khi openclaw_enable_deadline_warning=0 thì không quét task nào."""
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_enable_deadline_warning', '0',
        )
        now = fields.Datetime.now()
        self.env['dac.work.task'].sudo().create({
            'name': 'Warning Disabled Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(minutes=60),
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            stats = self.env['dac.work.task'].sudo()._process_openclaw_deadline_warnings(now=now)
            post.assert_not_called()
        self.assertEqual(stats['scanned'], 0)
        # Restore
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_enable_deadline_warning', '1',
        )

    # ── Guard helper unit tests ───────────────────────────────────────

    def test_should_send_reminder_returns_false_for_done_task(self):
        """_should_send_reminder phải trả False khi task đã done."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Done Guard Test',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now - timedelta(hours=1),
            'state': 'done',
        })
        self.assertFalse(self.env['dac.work.task']._should_send_reminder(task, now=now))

    def test_should_send_reminder_returns_false_without_assigned_user(self):
        """_should_send_reminder phải trả False khi không có assigned_user_id."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'No User Guard Test',
            'order_id': self.order.id,
            'deadline': now - timedelta(hours=1),
        })
        self.assertFalse(self.env['dac.work.task']._should_send_reminder(task, now=now))

    def test_should_send_deadline_warning_returns_true_when_due(self):
        """_should_send_deadline_warning trả True khi deadline trong window, chưa nhắc."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Warning Guard True',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now + timedelta(minutes=90),
        })
        self.assertTrue(self.env['dac.work.task']._should_send_deadline_warning(task, now=now))

    def test_cron_no_spam_on_repeated_runs(self):
        """Cron chạy lặp lại trong cooldown không gửi thêm notification."""
        now = fields.Datetime.now()
        task = self.env['dac.work.task'].sudo().create({
            'name': 'No Spam Task',
            'order_id': self.order.id,
            'assigned_user_id': self.employee.id,
            'deadline': now - timedelta(hours=1),
        })
        with patch('odoo.addons.dac_erp.services.openclaw_notification_service.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            post.return_value.raise_for_status.return_value = None
            # Lần 1 — gửi thành công
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
            first_call_count = post.call_count
            # Lần 2 ngay sau — cùng now → cooldown chưa hết
            self.env['dac.work.task'].sudo().cron_send_openclaw_deadline_reminders()
        # Lần 2 không được gọi thêm
        self.assertEqual(post.call_count, first_call_count,
                         "Lần chạy thứ 2 trong cooldown không được gửi thêm")
