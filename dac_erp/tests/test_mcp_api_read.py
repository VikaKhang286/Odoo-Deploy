import json
from datetime import date, datetime, timedelta
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpApiRead(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP read tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Owner',
            'login': 'mcp_owner@example.com',
            'email': 'mcp_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Participant',
            'login': 'mcp_participant@example.com',
            'email': 'mcp_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Staff',
            'login': 'mcp_staff@example.com',
            'email': 'mcp_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'MCP Partner',
            'phone': '0901234567',
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Page',
            'page_fm_id_str': 'mcp-page-001',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'MCP Product',
            'type': 'service',
            'list_price': 1000000.0,
        })
        cls.product_alt = cls.env['product.product'].create({
            'name': 'MCP Product Alt',
            'type': 'service',
            'list_price': 2000000.0,
        })
        cls.journal = cls.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)
        cls.tag_done = cls.env['page.fm.tag'].create({
            'name': 'Done',
            'tag_fm_id': '401',
            'page_id': cls.page.id,
            'odoo_tag_code': 'DONE',
            'fm_color_hex': '#1550c6',
        })

    def setUp(self):
        super().setUp()
        now = datetime.utcnow().replace(microsecond=0)
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': '  Nguyen   Van A  ',
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id, self.participant_user.id])],
            'platform_fm': 'facebook',
            'status_state': 'recontact',
            'require_processing': True,
            'is_unread_fm': True,
            'pancake_tag_ids': [(6, 0, [self.tag_done.id])],
        })
        self.fallback_conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-fallback-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id])],
            'platform_fm': 'facebook',
        })
        self.message_oldest = self.env['page.fm.message'].create({
            'message_fm_id': 'mcp-msg-oldest-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(minutes=10),
            'sender_name_fm': 'Nguyen Van A',
            'content_html': '<div>  Bao gio <b>giao hang</b>?  </div>',
        })
        self.message_middle = self.env['page.fm.message'].create({
            'message_fm_id': 'mcp-msg-middle-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(minutes=5),
            'staff': self.staff_user.id,
            'staff_name_fm': self.staff_user.name,
            'content_html': '<p>Ngay mai</p>',
        })
        self.message_newest = self.env['page.fm.message'].create({
            'message_fm_id': 'mcp-msg-newest-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(minutes=1),
            'staff': self.staff_user.id,
            'staff_name_fm': self.staff_user.name,
            'content_html': '<p>Xem file</p>',
            'type_content': 'file',
            'attachments_json': json.dumps({
                'attachments': [
                    {
                        'type': 'document',
                        'filename': 'hoa-don.pdf',
                        'mime_type': 'pdf',
                        'url': 'https://content.pancake.vn/invoice.pdf',
                    }
                ],
                'nested': {
                    'items': [
                        {
                            'original_url': 'https://content.pancake.vn/image.jpg',
                            'thumbnail_url': 'https://content.pancake.vn/thumb.jpg',
                            'type': 'image',
                            'file_name': 'image.jpg',
                        }
                    ]
                }
            }),
        })
        self.order_linked = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.owner_user.id,
            'order_state_custom': 'deposit',
            'order_number': 'SO-MCP-%s' % self._testMethodName,
            'client_order_ref': 'REF-%s' % self._testMethodName,
            'delivery_address': '123 Delivery Street',
            'installation_address': '456 Install Street',
            'production_deadline': date.today(),
            'note': 'Order note for MCP',
            'has_deposit': True,
            'deposit_amount': 2000000.0,
        })
        self.order_linked.write({'conversation_id': self.conversation.id})
        self.env['sale.order.line'].create({
            'order_id': self.order_linked.id,
            'product_id': self.product.id,
            'name': 'Tu bep ABC',
            'description': 'Tu bep ABC kich thuoc ...',
            'product_uom_qty': 1,
            'price_unit': 10000000.0,
        })
        self.env['sale.order.line'].create({
            'order_id': self.order_linked.id,
            'product_id': self.product_alt.id,
            'name': 'Mat da',
            'description': 'Mat da granite',
            'product_uom_qty': 2,
            'price_unit': 1250000.0,
        })
        self.env['deposit.confirm.wizard'].with_context(
            active_id=self.order_linked.id,
            active_model='sale.order',
        ).create({
            'journal_id': self.journal.id,
            'payment_date': date.today(),
        }).action_confirm()
        self.order_minimal = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.owner_user.id,
            'order_state_custom': 'quotation',
            'has_deposit': False,
            'deposit_amount': 0.0,
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def test_missing_mcp_key_returns_401(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers={},
        )
        self.assertEqual(status_code, 401)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'missing_api_key')

    def test_invalid_mcp_key_returns_403(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('wrong-key'),
        )
        self.assertEqual(status_code, 403)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

    def test_read_key_can_call_conversations(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=self.conversation.id,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['count'], 1)

    def test_write_key_can_call_conversations(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            conversation_id=self.conversation.id,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['items'][0]['id'], self.conversation.id)

    def test_limit_is_capped_to_max(self):
        for index in range(0, 101):
            self.env['page.fm.conversation'].create({
                'conversation_fm_id': 'mcp-extra-%s-%s' % (self._testMethodName, index),
                'page_fm_page_id': self.page.id,
                'partner_id': self.partner.id,
                'customer_name_fm': 'Extra %s' % index,
                'platform_fm': 'facebook',
            })
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            page_id=self.page.id,
            limit=999,
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['count'], 100)
        self.assertGreater(payload['total'], 100)

    def test_list_conversations_envelope_and_customer_name_fallback(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversations,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=self.fallback_conversation.id,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertIn('count', payload)
        self.assertIn('total', payload)
        self.assertIn('items', payload)
        item = payload['items'][0]
        self.assertEqual(item['customer_name'], 'Conv: %s' % self.fallback_conversation.conversation_fm_id)
        self.assertEqual(item['tags'], [])

    def test_messages_are_oldest_to_newest_and_content_is_plain_text(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_messages,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(
            [item['id'] for item in payload['items']],
            [self.message_oldest.id, self.message_middle.id, self.message_newest.id],
        )
        self.assertEqual(payload['items'][0]['content_text'], 'Bao gio giao hang?')

    def test_attachments_are_normalized_and_raw_fields_are_hidden(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_messages,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        oldest_item = payload['items'][0]
        newest_item = payload['items'][-1]
        self.assertEqual(oldest_item['attachments'], [])
        self.assertEqual(len(newest_item['attachments']), 2)
        self.assertEqual(newest_item['attachments'][0]['name'], 'hoa-don.pdf')
        self.assertEqual(newest_item['attachments'][1]['thumb_url'], 'https://content.pancake.vn/thumb.jpg')
        self.assertNotIn('raw_msg', newest_item)
        self.assertNotIn('from', newest_item)
        self.assertNotIn('message_tags', newest_item)
        self.assertNotIn('edit_history', newest_item)
        self.assertNotIn('private_reply_conversation', newest_item)

    def test_context_returns_conversation_and_messages(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_context,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            limit=2,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['conversation']['id'], self.conversation.id)
        self.assertEqual(len(payload['data']['messages']), 2)

    def test_conversation_not_found_returns_404(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_context,
            99999999,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 404)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_orders_missing_and_invalid_key(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers={},
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers=self._headers('wrong-key'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

    def test_read_and_write_key_can_call_orders(self):
        for api_key in ('mcp-read-test-key', 'mcp-write-test-key'):
            payload, status_code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_orders,
                env=self.env,
                headers=self._headers(api_key),
                partner_id=self.partner.id,
            )
            self.assertEqual(status_code, 200)
            self.assertTrue(payload['ok'])
            self.assertGreaterEqual(payload['count'], 1)

    def test_orders_limit_is_capped_and_list_envelope_is_stable(self):
        for index in range(0, 101):
            self.env['sale.order'].create({
                'partner_id': self.partner.id,
                'user_id': self.owner_user.id,
                'client_order_ref': 'ORDER-CAP-%s-%s' % (self._testMethodName, index),
            })
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            partner_id=self.partner.id,
            limit=999,
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertIn('count', payload)
        self.assertIn('total', payload)
        self.assertIn('items', payload)
        self.assertEqual(payload['count'], 100)
        self.assertGreater(payload['total'], 100)

    def test_orders_include_lines_false_and_missing_fields_do_not_crash(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=self.conversation.id,
            include_lines='0',
        )
        self.assertEqual(status_code, 200)
        item = payload['items'][0]
        self.assertEqual(item['lines'], [])
        self.assertEqual(item['conversation']['id'], self.conversation.id)

        minimal_payload, minimal_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id='',
            partner_id=self.partner.id,
            limit=100,
        )
        self.assertEqual(minimal_status, 200)
        minimal_item = next(row for row in minimal_payload['items'] if row['id'] == self.order_minimal.id)
        # order_number falls back to name when the field is not explicitly set
        self.assertEqual(minimal_item['order_number'], self.order_minimal.name)
        self.assertIsNone(minimal_item['conversation'])
        self.assertIsNone(minimal_item['production_deadline'])

    def test_orders_include_lines_true_and_labels_are_normalized(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_orders,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            conversation_id=self.conversation.id,
            include_lines='1',
        )
        self.assertEqual(status_code, 200)
        item = payload['items'][0]
        self.assertTrue(item['lines'])
        main_line = next(line for line in item['lines'] if line['product_id'] == self.product.id)
        self.assertEqual(main_line['product_name'], self.product.display_name)
        self.assertEqual(main_line['uom'], self.product.uom_id.name)
        self.assertEqual(item['state_label'], dict(self.order_linked._fields['state'].selection).get(self.order_linked.state))
        self.assertEqual(
            item['order_state_custom_label'],
            dict(self.order_linked._fields['order_state_custom'].selection).get(self.order_linked.order_state_custom),
        )

    def test_order_detail_returns_data_with_lines_by_default(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_detail,
            self.order_linked.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['id'], self.order_linked.id)
        self.assertTrue(payload['data']['lines'])
        self.assertTrue(payload['data']['latest_deposit_invoice'])
        self.assertTrue(payload['data']['latest_deposit_payment'])

    def test_order_detail_not_found_returns_404(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_detail,
            99999999,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_conversation_orders_route_and_conversation_not_found(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_orders,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['items'][0]['id'], self.order_linked.id)

        missing_payload, missing_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_orders,
            99999999,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_payload['error']['code'], 'not_found')

    def test_order_output_hides_raw_internal_fields(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_order_detail,
            self.order_linked.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
        )
        self.assertEqual(status_code, 200)
        item = payload['data']
        self.assertNotIn('flags', item)
        self.assertNotIn('deposit', item)
        self.assertNotIn('company_id', item)
        self.assertNotIn('conversation_id', item)
        self.assertNotIn('pancake_conversation_id', item)
        self.assertNotIn('latest_deposit_invoice_id', item)
        self.assertNotIn('latest_deposit_payment_id', item)
        self.assertNotIn('order_lines', item)
