"""Test các hook trên sale.order, page.fm.conversation, dac.work.task."""
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestWebhookHooks(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        # Bật webhook để hooks chuyển sang pending
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('dac_openclaw.webhook_url', 'https://openclaw.example.com/events')
        icp.set_param('dac_openclaw.webhook_secret', 'test-secret')
        icp.set_param('dac_openclaw.webhook_enabled', 'true')

        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")
        cls.partner = cls.env['res.partner'].create({'name': 'Hook Test Partner'})
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hook Test User', 'login': 'hook_test@example.com',
            'email': 'hook_test@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Hook Test Product', 'type': 'service', 'list_price': 1000.0,
        })

    def _find_events(self, event_type, **filters):
        domain = [('event_type', '=', event_type)]
        for k, v in filters.items():
            domain.append((k, '=', v))
        return self.env['dac_openclaw.outbound.webhook.log'].sudo().search(domain)

    def test_order_create_fires_order_created(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': 'quotation',
        })
        events = self._find_events('order.created', sale_order_id=order.id)
        self.assertEqual(len(events), 1)
        self.assertIn(events.state, ('pending', 'skipped'))

    def test_order_stage_change_fires_event(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': 'quotation',
        })
        # Change stage
        order.sudo().write({'order_state_custom': 'deposit'})
        stage_events = self._find_events('order.stage_changed', sale_order_id=order.id)
        self.assertEqual(len(stage_events), 1)

    def test_order_cancel_fires_cancelled_subevent(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': 'quotation',
        })
        order.sudo().write({'order_state_custom': 'cancel'})
        events = self._find_events('order.cancelled', sale_order_id=order.id)
        self.assertEqual(len(events), 1)

    def test_order_reopen_fires_reopened_event(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
            'order_state_custom': 'quotation',
        })
        order.sudo().write({'order_state_custom': 'cancel'})
        order.sudo().with_context(allow_reopen_cancelled=True).write({
            'order_state_custom': 'quotation',
        })
        events = self._find_events('order.reopened', sale_order_id=order.id)
        self.assertEqual(len(events), 1)

    def test_conversation_assign_fires_event(self):
        page = self.env['page.fm.page'].create({
            'name': 'Hook Test Page', 'page_fm_id_str': 'hook-test-page',
        })
        conv = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'hook-conv-assign-001',
            'page_fm_page_id': page.id,
            'customer_name_fm': 'Test Customer',
        })
        conv.sudo().write({'owner_id': self.user.id})
        events = self._find_events('conversation.assigned', conversation_id=conv.id)
        self.assertEqual(len(events), 1)

    def test_conversation_status_change_fires(self):
        page = self.env['page.fm.page'].create({
            'name': 'Hook Test Page 2', 'page_fm_id_str': 'hook-test-page-2',
        })
        conv = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'hook-conv-status-001',
            'page_fm_page_id': page.id,
            'customer_name_fm': 'Test Customer',
            'status_state': 'new',
        })
        conv.sudo().write({'status_state': 'done'})
        events = self._find_events('conversation.status_changed', conversation_id=conv.id)
        self.assertEqual(len(events), 1)

    def test_task_create_fires_task_created(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
        })
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Test Task Hook',
            'order_id': order.id,
            'state': 'draft',
        })
        events = self._find_events('task.created', task_id=task.id)
        self.assertEqual(len(events), 1)

    def test_task_assign_fires_assigned(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
            'user_id': self.user.id,
        })
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Test Task Assign',
            'order_id': order.id,
        })
        task.sudo().write({'assigned_user_id': self.user.id})
        events = self._find_events('task.assigned', task_id=task.id)
        # Có thể có 2 events: 1 từ create (nếu assigned_user_id ngay từ create), 1 từ write
        # Trường hợp này task tạo không có assigned_user_id → chỉ 1 event từ write
        self.assertGreaterEqual(len(events), 1)

    def test_task_complete_fires(self):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner.id,
        })
        task = self.env['dac.work.task'].sudo().create({
            'name': 'Test Complete',
            'order_id': order.id,
            'state': 'draft',
        })
        task.sudo().write({'state': 'done'})
        events = self._find_events('task.completed', task_id=task.id)
        self.assertEqual(len(events), 1)
