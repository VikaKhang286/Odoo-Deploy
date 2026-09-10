"""Test Phase 5 automation crons + data quality."""
from datetime import timedelta
from unittest import SkipTest

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPhase5DataQuality(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.DQ = cls.env['dac_openclaw.data.quality.issue']
        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")
        cls.partner = cls.env['res.partner'].create({'name': 'DQ Partner'})
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'DQ User', 'login': 'dq_user@example.com',
            'email': 'dq_user@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'DQ Page', 'page_fm_id_str': 'dq-page-001',
        })

    def setUp(self):
        super().setUp()
        # Clear existing issues
        self.DQ.sudo().search([]).unlink()

    def test_orphan_task_detected(self):
        # Tạo task valid trước, rồi SQL-update để giả lập orphan (bypass ORM constraint)
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Orphan Task',
            'order_id': order.id,
            'state': 'draft',
        })
        self.env.cr.execute(
            "UPDATE dac_work_task SET order_id = NULL, conversation_id = NULL WHERE id = %s",
            [task.id],
        )
        self.env.invalidate_all()
        self.DQ.cron_data_quality_scan()
        issue = self.DQ.sudo().search([
            ('issue_type', '=', 'task_orphan'),
            ('task_id', '=', task.id),
        ], limit=1)
        self.assertTrue(issue)
        self.assertEqual(issue.severity, 'medium')

    def test_orphan_resolved_when_linked(self):
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Orphan Will Link',
            'order_id': order.id,  # Valid lúc create
            'state': 'draft',
        })
        # SQL bypass để giả lập orphan
        self.env.cr.execute(
            "UPDATE dac_work_task SET order_id = NULL, conversation_id = NULL WHERE id = %s",
            [task.id],
        )
        self.env.invalidate_all()
        self.DQ.cron_data_quality_scan()
        issue = self.DQ.sudo().search([
            ('issue_type', '=', 'task_orphan'),
            ('task_id', '=', task.id),
        ], limit=1)
        self.assertTrue(issue)
        # Link lại task qua SQL (write() sẽ trigger constraint)
        self.env.cr.execute(
            "UPDATE dac_work_task SET order_id = %s WHERE id = %s",
            [order.id, task.id],
        )
        self.env.invalidate_all()
        # Re-scan → auto-resolve
        self.DQ.cron_data_quality_scan()
        issue.invalidate_recordset()
        self.assertTrue(issue.resolved)

    def test_task_unassigned_too_long(self):
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Old Draft',
            'order_id': order.id,
            'state': 'draft',
            # assigned_user_id = False
        })
        # Pass _age_24h=0 để mọi task draft đều match
        self.DQ.cron_data_quality_scan(_age_24h=0)
        issue = self.DQ.sudo().search([
            ('issue_type', '=', 'task_unassigned_too_long'),
            ('task_id', '=', task.id),
        ], limit=1)
        self.assertTrue(issue)
        self.assertEqual(issue.severity, 'high')

    def test_conversation_no_owner_detected(self):
        conv = self.env['page.fm.conversation'].sudo().create({
            'conversation_fm_id': 'dq-conv-no-owner',
            'page_fm_page_id': self.page.id,
            'status_state': 'new',
            'customer_name_fm': 'Test',
        })
        # Pass _age_30m=-1 → threshold = now + 1 min, mọi conv mới đều match
        self.DQ.cron_data_quality_scan(_age_30m=-1)
        issue = self.DQ.sudo().search([
            ('issue_type', '=', 'conversation_no_owner'),
            ('conversation_id', '=', conv.id),
        ], limit=1)
        self.assertTrue(issue)

    def test_order_stale_quotation(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'order_state_custom': 'quotation',
        })
        # Pass _age_7d=0 để mọi quotation đều match (test hook)
        self.DQ.cron_data_quality_scan(_age_7d=0)
        issue = self.DQ.sudo().search([
            ('issue_type', '=', 'order_stale_quotation'),
            ('order_id', '=', order.id),
        ], limit=1)
        self.assertTrue(issue)

    def test_issue_dedup_no_duplicate_creation(self):
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].sudo().create({
            'name': 'T', 'order_id': order.id, 'state': 'draft',
        })
        # SQL bypass để giả lập orphan
        self.env.cr.execute(
            "UPDATE dac_work_task SET order_id = NULL, conversation_id = NULL WHERE id = %s",
            [task.id],
        )
        self.env.invalidate_all()
        # Run scan 3 lần → chỉ 1 issue cho task_orphan
        self.DQ.cron_data_quality_scan()
        self.DQ.cron_data_quality_scan()
        self.DQ.cron_data_quality_scan()
        issues = self.DQ.sudo().search([
            ('issue_type', '=', 'task_orphan'),
            ('task_id', '=', task.id),
        ])
        self.assertEqual(len(issues), 1)


@tagged('post_install', '-at_install')
class TestPhase5AutomationScanner(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Scanner = cls.env['dac_openclaw.automation.scanner']
        cls.WebhookLog = cls.env['dac_openclaw.outbound.webhook.log']
        # Bật webhook (state=pending) khi enqueue
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('dac_openclaw.webhook_enabled', 'true')
        icp.set_param('dac_openclaw.webhook_url', 'https://x.example.com/events')
        icp.set_param('dac_openclaw.webhook_secret', 'x')

        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")
        cls.partner = cls.env['res.partner'].create({'name': 'AS Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'AS Page', 'page_fm_id_str': 'as-page-001',
        })

    def setUp(self):
        super().setUp()

    def test_scan_unassigned_conversations_fires_event(self):
        conv = self.env['page.fm.conversation'].sudo().create({
            'conversation_fm_id': 'as-unassigned-001',
            'page_fm_page_id': self.page.id,
            'status_state': 'new',
            'customer_name_fm': 'Test',
        })
        # Dùng _age_minutes=0 để mọi conv mới đều match threshold
        self.Scanner.cron_scan_unassigned_conversations(_age_minutes=-1)
        events = self.WebhookLog.sudo().search([
            ('event_type', '=', 'conversation.unassigned'),
            ('conversation_id', '=', conv.id),
        ])
        self.assertEqual(len(events), 1)

    def test_scan_unassigned_cooldown(self):
        conv = self.env['page.fm.conversation'].sudo().create({
            'conversation_fm_id': 'as-cooldown-001',
            'page_fm_page_id': self.page.id,
            'status_state': 'new',
            'customer_name_fm': 'Test',
        })
        self.Scanner.cron_scan_unassigned_conversations(_age_minutes=-1)
        self.Scanner.cron_scan_unassigned_conversations(_age_minutes=-1)
        # Cooldown 4h — chỉ 1 event
        events = self.WebhookLog.sudo().search([
            ('event_type', '=', 'conversation.unassigned'),
            ('conversation_id', '=', conv.id),
        ])
        self.assertEqual(len(events), 1)

    def test_scan_overdue_tasks_fires_event(self):
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        past_deadline = fields.Datetime.now() - timedelta(hours=2)
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Overdue T',
            'order_id': order.id,
            'state': 'in_progress',
            'deadline': past_deadline,
        })
        self.Scanner.cron_scan_overdue_tasks()
        events = self.WebhookLog.sudo().search([
            ('event_type', '=', 'task.overdue'),
            ('task_id', '=', task.id),
        ])
        self.assertEqual(len(events), 1)

    def test_scan_overdue_skips_done_tasks(self):
        order = self.env['sale.order'].sudo().create({'partner_id': self.partner.id})
        past_deadline = fields.Datetime.now() - timedelta(hours=2)
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Done overdue',
            'order_id': order.id,
            'state': 'done',  # Đã done → không scan
            'deadline': past_deadline,
        })
        self.Scanner.cron_scan_overdue_tasks()
        events = self.WebhookLog.sudo().search([
            ('event_type', '=', 'task.overdue'),
            ('task_id', '=', task.id),
        ])
        self.assertEqual(len(events), 0)

    def test_scan_duplicate_orders(self):
        # amount_total là computed/stored — set trực tiếp qua SQL để test stable
        o1 = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'order_state_custom': 'quotation',
        })
        o2 = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'order_state_custom': 'quotation',
        })
        # Force amount_total để query GROUP BY có data ổn định
        self.env.cr.execute(
            "UPDATE sale_order SET amount_total = 5500 WHERE id IN (%s, %s)",
            [o1.id, o2.id],
        )
        self.env.invalidate_all()
        self.Scanner.cron_scan_duplicate_orders()
        events = self.WebhookLog.sudo().search([
            ('event_type', '=', 'order.created'),
        ], limit=20)
        found_duplicate = False
        for evt in events:
            if 'duplicate_warning' in (evt.payload_json or ''):
                found_duplicate = True
                break
        self.assertTrue(found_duplicate, "Duplicate order event should be fired")
