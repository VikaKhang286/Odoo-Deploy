from datetime import datetime, timedelta
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


class DummyConversation:

    def __init__(self, require_processing=False, is_unread_fm=False):
        self.require_processing = require_processing
        self.is_unread_fm = is_unread_fm
        self.owner_id = False


@tagged('post_install', '-at_install')
class TestMcpCustomerCareQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; customer care queue tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Care Owner',
            'login': 'care_owner@example.com',
            'email': 'care_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Care Staff',
            'login': 'care_staff@example.com',
            'email': 'care_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Care Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Care Page',
            'page_fm_id_str': 'care-page-001',
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _create_conversation(self, suffix, require_processing=False, is_unread=False, platform='facebook'):
        return self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'care-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Customer %s' % suffix,
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id])],
            'platform_fm': platform,
            'status_state': 'recontact',
            'require_processing': require_processing,
            'is_unread_fm': is_unread,
        })

    def _create_message(self, conversation, inserted_at, sender='customer', content_html=None):
        vals = {
            'message_fm_id': 'care-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
            'conversation_id': conversation.id,
            'inserted_at_fm': inserted_at,
            'content_html': content_html or '<div>Hello</div>',
        }
        if sender == 'staff':
            vals.update({
                'staff': self.staff_user.id,
                'staff_name_fm': self.staff_user.name,
            })
        else:
            vals.update({
                'sender_name_fm': 'Customer Sender',
            })
        return self.env['page.fm.message'].create(vals)

    def test_missing_invalid_and_read_write_key_auth(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers={},
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('wrong-key'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        conv = self._create_conversation('auth', require_processing=True)
        for api_key in ('mcp-read-test-key', 'mcp-write-test-key'):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_customer_care_queue,
                env=self.env,
                headers=self._headers(api_key),
                conversation_id=conv.id,
            )
            self.assertEqual(status_code, 200)
            self.assertTrue(payload['ok'])

    def test_unreplied_unread_and_require_processing_are_in_queue(self):
        now = datetime.utcnow().replace(microsecond=0)
        unreplied = self._create_conversation('unreplied')
        self._create_message(unreplied, now - timedelta(minutes=85), sender='customer', content_html='<div>Need reply</div>')

        unread = self._create_conversation('unread', is_unread=True)
        require_processing = self._create_conversation('processing', require_processing=True)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            limit=100,
        )
        self.assertEqual(status_code, 200)
        ids = [item['conversation']['id'] for item in payload['items']]
        self.assertIn(unreplied.id, ids)
        self.assertIn(unread.id, ids)
        self.assertIn(require_processing.id, ids)

    def test_waiting_minutes_and_priority_rules(self):
        now = datetime.utcnow().replace(microsecond=0)
        urgent = self._create_conversation('urgent', require_processing=True)
        self._create_message(urgent, now - timedelta(minutes=130), sender='customer')

        medium = self._create_conversation('medium', is_unread=True)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            sla_minutes=60,
            limit=100,
        )
        self.assertEqual(status_code, 200)
        item_map = {item['conversation']['id']: item for item in payload['items']}

        self.assertEqual(item_map[urgent.id]['care_priority'], 'urgent')
        self.assertGreaterEqual(item_map[urgent.id]['waiting_minutes'], 130)
        self.assertEqual(item_map[medium.id]['care_priority'], 'medium')

        high_priority = self.controller._build_customer_care_priority(
            DummyConversation(),
            {
                'is_unreplied': True,
                'last_customer_message_at': now - timedelta(minutes=85),
                'last_staff_reply_at': None,
            },
            waiting_minutes=85,
            sla_minutes=60,
            urgent_minutes=120,
        )
        self.assertEqual(high_priority, 'high')

        low_priority = self.controller._build_customer_care_priority(
            DummyConversation(),
            {'is_unreplied': False, 'last_customer_message_at': None, 'last_staff_reply_at': None},
            waiting_minutes=None,
            sla_minutes=60,
            urgent_minutes=120,
        )
        self.assertEqual(low_priority, 'low')

    def test_include_messages_and_message_limit_are_capped(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('messages')
        for index in range(25):
            self._create_message(
                conversation,
                now - timedelta(minutes=25 - index),
                sender='customer' if index % 2 == 0 else 'staff',
                content_html='<div>Message %s</div>' % index,
            )

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=conversation.id,
            include_messages=1,
            message_limit=999,
            limit=999,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['total'], 1)
        item = payload['items'][0]
        self.assertEqual(len(item['messages']), 20)
        self.assertLess(item['messages'][0]['id'], item['messages'][-1]['id'])
        self.assertIn('content_text', item['messages'][0])
        self.assertNotIn('raw_msg', item['messages'][0])

    def test_limit_is_capped(self):
        for index in range(0, 120):
            self._create_conversation('bulk-%s' % index, is_unread=True)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            limit=999,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['count'], 100)
