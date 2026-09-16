from datetime import date, datetime, timedelta
from unittest import SkipTest

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpPhase4AFoundation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; Phase 4A MCP tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Phase4A Owner',
            'login': 'phase4a_owner@example.com',
            'email': 'phase4a_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Phase4A Staff',
            'login': 'phase4a_staff@example.com',
            'email': 'phase4a_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Phase4A Page',
            'page_fm_id_str': 'phase4a-page-001',
        })
        cls.company_partner = cls.env['res.partner'].create({'name': 'Cong ty ABC'})
        cls.partner_nam_1 = cls.env['res.partner'].create({
            'name': 'Nguyen Van Nam',
            'phone': '0901234567',
            'street': 'Quan 7, TP.HCM',
        })
        cls.partner_nam_2 = cls.env['res.partner'].create({
            'name': 'Nam',
            'phone': '0918888888',
            'parent_id': cls.company_partner.id,
            'street': 'Thu Duc, TP.HCM',
        })
        cls.partner_email = cls.env['res.partner'].create({
            'name': 'Tran Thi Hang',
            'email': 'hang@example.com',
            'vat': 'VN123',
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'VAT 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        cls.product_a = cls.env['product.product'].create({
            'name': 'Tu bep ABC',
            'default_code': 'TB-ABC',
            'list_price': 10000000.0,
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'Tu bep Premium',
            'default_code': 'TB-PRE',
            'list_price': 15000000.0,
        })
        cls.product_inactive = cls.env['product.product'].create({
            'name': 'Tu bep Inactive',
            'default_code': 'TB-OFF',
            'list_price': 5000000.0,
            'active': False,
        })
        cls.product_not_sale = cls.env['product.product'].create({
            'name': 'No Sale Product',
            'default_code': 'NO-SALE',
            'sale_ok': False,
        })
        cls.bank_journal = cls.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)
        cls.followup_activity_type = cls.env.ref('dac_erp.mail_activity_type_cskh_followup')
        cls.todo_activity_type = cls.env.ref('mail.mail_activity_data_todo')
        cls.call_activity_type = cls.env.ref('mail.mail_activity_data_call')
        cls.conversation_model_id = cls.env['ir.model']._get_id('page.fm.conversation')

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.sla_minutes_default', '60')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '120')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.default_policy', 'standard')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.conversation.default_scope', 'external')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.conversation.allow_internal_read', 'True')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.activity_type.todo_xmlid', 'mail.mail_activity_data_todo')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.activity_type.call_xmlid', 'mail.mail_activity_data_call')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.activity_type.followup_xmlid', 'dac_erp.mail_activity_type_cskh_followup')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.urgent_activity_type', 'call')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.high_activity_type', 'followup')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.medium_activity_type', 'todo')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.low_activity_type', 'none')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.morning_start', '08:00')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.morning_end', '12:00')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.afternoon_start', '13:30')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.afternoon_end', '17:30')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.working_days', '1,2,3,4,5,6')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.timezone_mode', 'fixed')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.working_hours.fixed_timezone', 'Asia/Ho_Chi_Minh')

        self.external_conversation = self._create_conversation('external', self.partner_nam_1, internal=False, is_unread=True)
        self.internal_conversation = self._create_conversation('internal', self.partner_nam_2, internal=True, is_unread=True)
        self.linked_conversation = self._create_conversation('linked', self.partner_nam_1, internal=False, is_unread=False)
        now = datetime.utcnow().replace(microsecond=0)
        self._create_message(self.external_conversation, now - timedelta(minutes=85), sender='customer')
        self._create_message(self.internal_conversation, now - timedelta(minutes=30), sender='customer')
        self._create_message(self.linked_conversation, now - timedelta(minutes=40), sender='customer')
        self._create_message(self.linked_conversation, now - timedelta(minutes=10), sender='staff')

        self.order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner_nam_1.id,
            'user_id': self.owner_user.id,
            'order_state_custom': 'quotation',
            'delivery_address': '123 Duong A',
            'installation_address': '456 Duong B',
            'production_deadline': date.today(),
            'fulfillment_method': 'delivery',
            'has_deposit': True,
            'deposit_amount': 1000000.0,
        })
        self.env.cr.execute(
            "UPDATE sale_order SET conversation_id = %s WHERE id = %s",
            [self.linked_conversation.id, self.order.id],
        )
        self.order.invalidate_recordset(['conversation_id'])
        self.env['sale.order.line'].sudo().create({
            'order_id': self.order.id,
            'product_id': self.product_a.id,
            'name': self.product_a.display_name,
            'product_uom_qty': 1.0,
            'price_unit': 10000000.0,
            'tax_id': [(6, 0, [self.tax.id])],
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _create_conversation(self, suffix, partner, internal=False, is_unread=False):
        return self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'phase4a-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': partner.id,
            'customer_name_fm': partner.name,
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id])],
            'platform_fm': 'facebook',
            'status_state': 'recontact',
            'require_processing': False,
            'is_unread_fm': is_unread,
            'is_internal_conversation': internal,
        })

    def _create_message(self, conversation, inserted_at, sender='customer'):
        vals = {
            'message_fm_id': 'phase4a-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
            'conversation_id': conversation.id,
            'inserted_at_fm': inserted_at,
            'content_html': '<div>Hello</div>',
        }
        if sender == 'staff':
            vals.update({'staff': self.staff_user.id, 'staff_name_fm': self.staff_user.name})
        else:
            vals.update({'sender_name_fm': 'Customer Sender'})
        return self.env['page.fm.message'].create(vals)

    def test_settings_save_load_and_validation(self):
        # set_values() calls env.cr.commit() which is forbidden inside TransactionCase.
        # Write directly to ir.config_parameter — the same storage backend that
        # set_values() uses for config_parameter fields — then verify load-back.
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('dac_erp.mcp.customer_care.sla_minutes_default', '75')
        ICP.set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '150')
        ICP.set_param('dac_erp.mcp.working_hours.morning_start', '07:30')
        ICP.set_param('dac_erp.mcp.working_hours.morning_end', '11:30')
        ICP.set_param('dac_erp.mcp.working_hours.afternoon_start', '13:00')
        ICP.set_param('dac_erp.mcp.working_hours.afternoon_end', '18:00')
        ICP.set_param('dac_erp.mcp.working_hours.working_days', '1,2,3,4,5')

        wizard = self.env['res.config.settings'].create({})
        self.assertEqual(wizard.mcp_customer_care_sla_minutes_default, 75)
        self.assertEqual(wizard.mcp_working_hours_morning_start, '07:30')

        with self.assertRaises(ValidationError):
            self.env['res.config.settings'].create({'mcp_working_hours_morning_start': '99:00'})
        with self.assertRaises(ValidationError):
            self.env['res.config.settings'].create({'mcp_working_hours_working_days': '1,8'})

    def test_queue_uses_system_sla_and_request_override_and_urgent_config(self):
        queue_conversation = self._create_conversation('queue-threshold', self.partner_nam_1, internal=False, is_unread=True)
        now = datetime.utcnow().replace(microsecond=0)
        self._create_message(queue_conversation, now - timedelta(minutes=300), sender='customer')
        self._create_message(queue_conversation, now - timedelta(minutes=295), sender='staff')

        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.sla_minutes_default', '45')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '70')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=queue_conversation.id,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['config']['sla_minutes'], 45)
        self.assertEqual(payload['config']['urgent_minutes'], 70)
        self.assertEqual(payload['config']['source'], 'system_parameter')
        self.assertTrue(payload['items'])

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_queue,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=queue_conversation.id,
            sla_minutes=90,
            urgent_minutes=10000,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['config']['source'], 'request')
        self.assertEqual(payload['config']['sla_minutes'], 90)
        self.assertEqual(payload['config']['urgent_minutes'], 10000)

        metric = {'is_unreplied': False}
        self.assertEqual(
            self.controller._build_customer_care_priority(queue_conversation, metric, 300, 45, 70),
            'urgent',
        )
        self.assertEqual(
            self.controller._build_customer_care_priority(queue_conversation, metric, 300, 90, 10000),
            'high',
        )

    def test_action_plan_uses_default_policy_and_deadline_from_config(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp.customer_care.default_policy', 'urgent_only')
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_action_plan,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload={'conversation_ids': [self.external_conversation.id]},
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['policy'], 'urgent_only')
        recommendation = payload['data']['items'][0]['activity_recommendation']
        self.assertIn(recommendation['deadline_policy'], ('same_day', 'next_working_shift', 'manual'))

    def test_followup_activity_type_mapping_and_explicit_xmlid(self):
        self.assertEqual(self.followup_activity_type.name, 'CSKH Follow-up')

        for request_id, conversation, expected_code in (
            ('phase4a-followup-urgent', self.external_conversation, 'call'),
            ('phase4a-followup-medium', self.linked_conversation, 'todo'),
        ):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_customer_care_create_followups,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload={
                    'conversation_ids': [conversation.id],
                    'summary_template': 'Phan hoi khach dang cho',
                    'note_template': 'Test',
                    'request_id': request_id,
                    'agent_name': 'OpenClaw',
                    'reason': 'bulk_customer_care_reminder',
                },
            )
            self.assertEqual(status_code, 200)
            self.assertEqual(payload['data']['items'][0]['activity_type']['code'], expected_code)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_create_followups,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={
                'conversation_ids': [self.external_conversation.id],
                'summary_template': 'Phan hoi khach dang cho',
                'note_template': 'Test',
                'activity_type_xmlid': 'dac_erp.mail_activity_type_cskh_followup',
                'dedupe_existing_open_activity': False,
                'request_id': 'phase4a-followup-explicit',
                'agent_name': 'OpenClaw',
                'reason': 'bulk_customer_care_reminder',
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['items'][0]['activity_type']['xmlid'], 'dac_erp.mail_activity_type_cskh_followup')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_create_followups,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={
                'conversation_ids': [self.external_conversation.id],
                'summary_template': 'Phan hoi khach dang cho',
                'note_template': 'Test',
                'activity_type_xmlid': 'dac_erp.missing_xmlid',
                'request_id': 'phase4a-followup-invalid',
                'agent_name': 'OpenClaw',
                'reason': 'bulk_customer_care_reminder',
            },
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_internal_scope_and_alias_routes(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            limit=100,
        )
        self.assertEqual(status_code, 200)
        ids = [item['id'] for item in payload['items']]
        self.assertIn(self.external_conversation.id, ids)
        self.assertNotIn(self.internal_conversation.id, ids)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            scope='internal',
            limit=100,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['items'][0]['id'], self.internal_conversation.id)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            scope='all',
            limit=100,
        )
        self.assertEqual(status_code, 200)
        ids = [item['id'] for item in payload['items']]
        self.assertIn(self.external_conversation.id, ids)
        self.assertIn(self.internal_conversation.id, ids)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_messages,
            self.internal_conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'permission_denied')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_messages,
            self.internal_conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            include_internal=1,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['items'])

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_internal_conversation_context,
            self.internal_conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['conversation']['id'], self.internal_conversation.id)

    def test_customer_search_and_resolve(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customers_search,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            phone='0901234567',
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['status'], 'exact_match')
        self.assertEqual(payload['data']['items'][0]['id'], self.partner_nam_1.id)
        self.assertNotIn('property_account_receivable_id', payload['data']['items'][0])

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customers_search,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            q='anh Nam',
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['normalized_query'], 'Nam')
        self.assertEqual(payload['data']['status'], 'multiple_matches')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customers_resolve,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload={'conversation_id': self.linked_conversation.id, 'mention_text': 'anh Nam'},
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['status'], 'exact_match')
        self.assertEqual(payload['data']['source'], 'conversation_link')

    def test_product_search_and_resolve(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_products_search,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            default_code='TB-ABC',
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['status'], 'exact_match')
        self.assertEqual(payload['data']['items'][0]['id'], self.product_a.id)
        self.assertNotIn('standard_price', payload['data']['items'][0])

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_products_search,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            q='tu bep',
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['status'], 'multiple_matches')
        ids = [item['id'] for item in payload['data']['items']]
        self.assertNotIn(self.product_inactive.id, ids)
        self.assertNotIn(self.product_not_sale.id, ids)

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_products_resolve,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload={
                'mention_text': 'tu bep abc',
                'conversation_id': self.linked_conversation.id,
                'customer_id': self.partner_nam_1.id,
            },
        )
        self.assertEqual(status_code, 200)
        self.assertIn(payload['data']['status'], ('exact_match', 'multiple_matches'))
        self.assertIn(payload['data']['source'], ('name_search', 'recent_order_context', 'product_code'))
