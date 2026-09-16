from datetime import date, datetime, timedelta
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.api_v2_controller import DataExportV2Controller


@tagged('standard', 'at_install')
class TestApiV2Filters(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = DataExportV2Controller()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.api_v2_write_key', 'api-v2-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models

        cls.group_user = cls.env.ref('base.group_user')
        cls.assignee_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'API V2 Assignee',
            'login': 'api_v2_assignee@example.com',
            'email': 'api_v2_assignee@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'API V2 Staff',
            'login': 'api_v2_staff@example.com',
            'email': 'api_v2_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.other_staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'API V2 Staff Other',
            'login': 'api_v2_staff_other@example.com',
            'email': 'api_v2_staff_other@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })

        cls.partner = cls.env['res.partner'].create({'name': 'API V2 Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'API V2 Page',
            'page_fm_id_str': 'api-v2-page-001',
        }) if cls.has_pancake_models else None
        cls.other_page = cls.env['page.fm.page'].create({
            'name': 'API V2 Page Other',
            'page_fm_id_str': 'api-v2-page-002',
        }) if cls.has_pancake_models else None

        cls.product = cls.env['product.product'].create({
            'name': 'API V2 Product',
            'type': 'service',
            'list_price': 5000.0,
        })
        cls.product_alt = cls.env['product.product'].create({
            'name': 'API V2 Product Alt',
            'type': 'service',
            'list_price': 6500.0,
        })
        cls.journal = cls.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)
        cls.sale_tax = cls.env['account.tax'].search([('type_tax_use', '=', 'sale')], limit=1)

    def setUp(self):
        super().setUp()
        if self.has_pancake_models:
            self._create_conversation_fixtures()
        self._create_order_fixtures()

    def _create_conversation_fixtures(self):
        suffix = self._testMethodName
        now = datetime.utcnow().replace(microsecond=0)
        customer_time = now - timedelta(hours=1)
        staff_before_time = now - timedelta(hours=2)
        customer_replied_time = now - timedelta(hours=3)
        staff_after_time = now - timedelta(hours=2, minutes=30)

        self.conv_unreplied = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'conv-unreplied-%s' % suffix,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Customer Unreplied',
            'owner_id': self.assignee_user.id,
            'participant_user_ids': [(6, 0, [self.assignee_user.id])],
            'platform_fm': 'facebook',
        })
        self.tag_consulting = self.env['page.fm.tag'].create({
            'name': 'Consulting',
            'tag_fm_id': '101',
            'page_id': self.page.id,
            'odoo_tag_code': 'CONSULTING',
        })
        self.tag_vip = self.env['page.fm.tag'].create({
            'name': 'VIP',
            'tag_fm_id': '102',
            'page_id': self.page.id,
            'odoo_tag_code': 'VIP',
        })
        self.conv_unreplied.write({
            'pancake_tag_ids': [(6, 0, [self.tag_consulting.id, self.tag_vip.id])],
        })
        self.env['page.fm.message'].create({
            'message_fm_id': 'msg-unreplied-staff-%s' % suffix,
            'conversation_id': self.conv_unreplied.id,
            'inserted_at_fm': staff_before_time,
            'staff': self.staff_user.id,
            'staff_name_fm': self.staff_user.name,
            'content_html': '<p>Xin chao</p>',
        })
        self.system_unreplied_message = self.env['page.fm.message'].create({
            'message_fm_id': 'msg-unreplied-system-%s' % suffix,
            'conversation_id': self.conv_unreplied.id,
            'inserted_at_fm': staff_before_time - timedelta(minutes=10),
            'content_html': '<p>Attachment image</p>',
            'type_content': 'image',
            'url_content': 'https://example.com/image.png',
        })
        self.customer_unreplied_message = self.env['page.fm.message'].create({
            'message_fm_id': 'msg-unreplied-customer-%s' % suffix,
            'conversation_id': self.conv_unreplied.id,
            'inserted_at_fm': customer_time,
            'sender_name_fm': 'Customer Unreplied',
            'content_html': '<p>Khach nhan tin</p>',
        })

        self.conv_replied = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'conv-replied-%s' % suffix,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Customer Replied',
            'owner_id': self.other_staff_user.id,
            'participant_user_ids': [(6, 0, [self.other_staff_user.id])],
            'platform_fm': 'zalo',
        })
        self.env['page.fm.message'].create({
            'message_fm_id': 'msg-replied-customer-%s' % suffix,
            'conversation_id': self.conv_replied.id,
            'inserted_at_fm': customer_replied_time,
            'sender_name_fm': 'Customer Replied',
            'content_html': '<p>Khach can tu van</p>',
        })
        self.env['page.fm.message'].create({
            'message_fm_id': 'msg-replied-staff-%s' % suffix,
            'conversation_id': self.conv_replied.id,
            'inserted_at_fm': staff_after_time,
            'staff': self.other_staff_user.id,
            'staff_name_fm': self.other_staff_user.name,
            'content_html': '<p>Da tra loi</p>',
        })
        self.conv_replied.write({
            'pancake_tag_ids': [(6, 0, [self.tag_consulting.id])],
        })

    def _create_order_fixtures(self):
        self.order_with_deposit = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_state_custom': 'deposit',
            'has_deposit': True,
            'deposit_amount': 1000.0,
        })
        self.env['sale.order.line'].create({
            'order_id': self.order_with_deposit.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 5000.0,
        })
        self.env['deposit.confirm.wizard'].with_context(
            active_id=self.order_with_deposit.id,
            active_model='sale.order',
        ).create({
            'journal_id': self.journal.id,
            'payment_date': date.today(),
        }).action_confirm()

        self.order_without_invoice = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_state_custom': 'deposit',
            'has_deposit': True,
            'deposit_amount': 700.0,
        })
        self.env['sale.order.line'].create({
            'order_id': self.order_without_invoice.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 3000.0,
        })

    def _create_write_test_order(self, state='quotation', with_protected_lines=False):
        order_vals = {
            'partner_id': self.partner.id,
            'order_state_custom': state,
            'note': 'Original note',
            'delivery_address': 'Original delivery',
        }
        if self.has_pancake_models:
            order_vals['conversation_id'] = self.conv_unreplied.id
        order = self.env['sale.order'].create(order_vals)
        line_a = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 2,
            'price_unit': 1000.0,
        })
        line_b = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_alt.id,
            'product_uom_qty': 1,
            'price_unit': 2000.0,
        })
        if with_protected_lines:
            order.add_deposit_order_line(500.0)
        return order, line_a, line_b

    def test_v2_conversations_unreplied_filters(self):
        if not self.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; conversation filters require Pancake models.")
        result = self.controller._get_v2_conversations_data(
            env=self.env,
            page_id=self.page.id,
            unreplied='1',
            unreplied_date='today',
            staff_user_id=self.staff_user.id,
        )

        self.assertEqual(result['count'], 1)
        self.assertEqual(result['items'][0]['id'], self.conv_unreplied.id)
        self.assertTrue(result['items'][0]['is_unreplied'])
        self.assertEqual(result['items'][0]['last_customer_message_at'], self.customer_unreplied_message.inserted_at_fm.isoformat())

        assignee_result = self.controller._get_v2_conversations_data(
            env=self.env,
            page_id=self.page.id,
            unreplied='1',
            unreplied_date='today',
            assignee_user_id=self.assignee_user.id,
        )
        self.assertEqual(assignee_result['count'], 1)
        self.assertEqual(assignee_result['items'][0]['id'], self.conv_unreplied.id)

    def test_v2_messages_cross_conversation_unreplied_and_sender_role(self):
        if not self.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; message filters require Pancake models.")
        result = self.controller._get_v2_messages_data(
            env=self.env,
            date='today',
            assignee_user_id=self.assignee_user.id,
            conversation_unreplied='1',
        )

        self.assertEqual(result['count'], 2)
        message_ids = {item['id'] for item in result['items']}
        self.assertIn(self.customer_unreplied_message.id, message_ids)
        self.assertTrue(all(item['conversation']['id'] == self.conv_unreplied.id for item in result['items']))

        roles_by_id = {item['id']: item['sender_role'] for item in result['items']}
        self.assertEqual(roles_by_id[self.customer_unreplied_message.id], 'customer')
        self.assertIn('staff', roles_by_id.values())

    def test_v2_messages_reject_unread_filter(self):
        if not self.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; message filters require Pancake models.")
        with self.assertRaises(ValueError):
            self.controller._get_v2_messages_data(
                env=self.env,
                unread='1',
            )

    def test_v2_conversations_platform_and_tag_filters(self):
        if not self.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; conversation filters require Pancake models.")
        platform_result = self.controller._get_v2_conversations_data(
            env=self.env,
            platform='facebook',
        )
        self.assertEqual(platform_result['count'], 1)
        self.assertEqual(platform_result['items'][0]['id'], self.conv_unreplied.id)

        tag_any_result = self.controller._get_v2_conversations_data(
            env=self.env,
            tag_code='CONSULTING,VIP',
            tag_mode='any',
        )
        self.assertGreaterEqual(tag_any_result['count'], 2)
        self.assertIn(self.conv_unreplied.id, [item['id'] for item in tag_any_result['items']])

        tag_all_result = self.controller._get_v2_conversations_data(
            env=self.env,
            tag_code='CONSULTING,VIP',
            tag_mode='all',
        )
        self.assertEqual(tag_all_result['count'], 1)
        self.assertEqual(tag_all_result['items'][0]['id'], self.conv_unreplied.id)

        with self.assertRaises(ValueError):
            self.controller._get_v2_conversations_data(
                env=self.env,
                tag_code='CONSULTING',
                tag_mode='invalid',
            )

    def test_v2_messages_extended_filters(self):
        if not self.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; message filters require Pancake models.")
        page_result = self.controller._get_v2_messages_data(
            env=self.env,
            page_id=self.page.id,
            sender_role='customer',
        )
        self.assertIn(self.customer_unreplied_message.id, [item['id'] for item in page_result['items']])
        self.assertTrue(all(item['sender_role'] == 'customer' for item in page_result['items']))

        page_fm_result = self.controller._get_v2_messages_data(
            env=self.env,
            page_fm_id_str=self.page.page_fm_id_str,
            sender_role='staff',
        )
        self.assertTrue(page_fm_result['count'] >= 2)
        self.assertTrue(all(item['sender_role'] == 'staff' for item in page_fm_result['items']))

        image_result = self.controller._get_v2_messages_data(
            env=self.env,
            type_content='image',
            platform='facebook',
            tag_code='VIP',
        )
        self.assertEqual(image_result['count'], 1)
        self.assertEqual(image_result['items'][0]['id'], self.system_unreplied_message.id)
        self.assertEqual(image_result['items'][0]['conversation']['page']['id'], self.page.id)

    def test_v2_orders_deposit_filters(self):
        invoice_result = self.controller._get_v2_orders_data(
            env=self.env,
            partner_id=self.partner.id,
            deposit_event='invoice_created',
            deposit_date='today',
        )
        self.assertEqual(invoice_result['count'], 1)
        invoice_item = invoice_result['items'][0]
        self.assertEqual(invoice_item['id'], self.order_with_deposit.id)
        self.assertGreaterEqual(invoice_item['deposit_invoice_count'], 1)
        self.assertTrue(invoice_item['latest_deposit_invoice_id'])
        self.assertTrue(invoice_item['latest_deposit_invoice_date'])

        payment_result = self.controller._get_v2_orders_data(
            env=self.env,
            partner_id=self.partner.id,
            deposit_event='payment_received',
            deposit_date='today',
        )
        self.assertEqual(payment_result['count'], 1)
        payment_item = payment_result['items'][0]
        self.assertEqual(payment_item['id'], self.order_with_deposit.id)
        self.assertGreaterEqual(payment_item['deposit_payment_count'], 1)
        self.assertTrue(payment_item['latest_deposit_payment_id'])
        self.assertTrue(payment_item['latest_deposit_payment_date'])

    def test_v2_write_api_key_validation(self):
        self.assertTrue(self.controller._ensure_v2_write_api_key(env=self.env, provided_key='api-v2-write-test-key'))
        with self.assertRaises(PermissionError):
            self.controller._ensure_v2_write_api_key(env=self.env, provided_key='wrong-key')
        with self.assertRaises(PermissionError):
            self.controller._ensure_v2_write_api_key(env=self.env, provided_key=None, headers={})

    def test_v2_create_order_with_lines(self):
        payload = {
            'partner_id': self.partner.id,
            'user_id': self.assignee_user.id,
            'client_order_ref': 'WRITE-001',
            'order_number': 'SO-WRITE-001',
            'note': 'Created from API',
            'delivery_address': '123 API Street',
            'installation_address': '456 Builder Lane',
            'has_deposit': True,
            'deposit_amount': 250.0,
            'production_deadline': date.today().isoformat(),
            'order_lines': [
                {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 3210.0,
                    'tax_ids': [self.sale_tax.id] if self.sale_tax else [],
                    'description': 'Main product',
                    'height': 10,
                    'width': 20,
                },
                {
                    'display_type': 'line_note',
                    'name': 'Customer note',
                    'description': 'Assembly details',
                },
            ],
        }
        if self.has_pancake_models:
            payload['conversation_id'] = self.conv_unreplied.id

        result = self.controller._create_v2_order(env=self.env, payload=payload)
        order = self.env['sale.order'].browse(result['id'])

        self.assertEqual(order.partner_id.id, self.partner.id)
        if self.has_pancake_models:
            self.assertEqual(order.conversation_id.id, self.conv_unreplied.id)
        self.assertEqual(order.user_id.id, self.assignee_user.id)
        self.assertEqual(order.client_order_ref, 'WRITE-001')
        self.assertEqual(order.order_number, 'SO-WRITE-001')
        self.assertIn('Created from API', str(order.note))
        self.assertEqual(order.delivery_address, '123 API Street')
        self.assertEqual(order.installation_address, '456 Builder Lane')
        self.assertEqual(order.deposit_amount, 250.0)
        self.assertEqual(len(result['order_lines']), 2)
        self.assertEqual(result['order_lines'][0]['product_id'], self.product.id)
        self.assertEqual(result['order_lines'][1]['display_type'], 'line_note')

    def test_v2_create_order_requires_partner_id(self):
        with self.assertRaises(ValueError):
            self.controller._create_v2_order(
                env=self.env,
                payload={
                    'note': 'Missing partner',
                },
            )

    def test_v2_update_order_core_fields_and_immutable_guards(self):
        order, _line_a, _line_b = self._create_write_test_order(state='completed')

        result = self.controller._update_v2_order(
            order.id,
            env=self.env,
            payload={
                'note': 'Updated note',
                'delivery_address': 'Updated delivery',
                'installation_address': 'Updated installation',
                'has_deposit': False,
                'deposit_amount': 0,
                'production_deadline': date.today().isoformat(),
            },
        )

        order.invalidate_recordset()
        self.assertIn('Updated note', str(order.note))
        self.assertEqual(order.delivery_address, 'Updated delivery')
        self.assertEqual(order.installation_address, 'Updated installation')
        self.assertFalse(order.has_deposit)
        self.assertEqual(order.deposit_amount, 0.0)
        self.assertIn('Updated note', str(result['note']))

        with self.assertRaises(ValueError):
            self.controller._update_v2_order(
                order.id,
                env=self.env,
                payload={
                    'partner_id': self.partner.id,
                },
            )
        with self.assertRaises(ValueError):
            self.controller._update_v2_order(
                order.id,
                env=self.env,
                payload={
                    'conversation_id': 999999,
                },
            )

    def test_v2_update_order_replace_lines_preserves_protected_lines(self):
        order, _line_a, _line_b = self._create_write_test_order(with_protected_lines=True)
        protected_lines_before = order.order_line.filtered(lambda line: self.controller._is_system_order_line(line))
        editable_lines_before = order.order_line.filtered(lambda line: not self.controller._is_system_order_line(line))
        self.assertTrue(protected_lines_before)
        self.assertEqual(len(editable_lines_before), 2)

        result = self.controller._update_v2_order(
            order.id,
            env=self.env,
            payload={
                'line_mode': 'replace',
                'order_lines': [
                    {
                        'product_id': self.product_alt.id,
                        'quantity': 5,
                        'price_unit': 4444.0,
                    }
                ],
            },
        )

        order.invalidate_recordset()
        protected_lines_after = order.order_line.filtered(lambda line: self.controller._is_system_order_line(line))
        editable_lines_after = order.order_line.filtered(lambda line: not self.controller._is_system_order_line(line))
        self.assertEqual(len(protected_lines_after), len(protected_lines_before))
        self.assertEqual(len(editable_lines_after), 1)
        self.assertEqual(editable_lines_after.product_id.id, self.product_alt.id)
        self.assertEqual(editable_lines_after.product_uom_qty, 5)
        self.assertTrue(any(line['product_id'] == self.product_alt.id for line in result['order_lines']))

    def test_v2_update_order_patch_lines(self):
        order, line_a, line_b = self._create_write_test_order()

        result = self.controller._update_v2_order(
            order.id,
            env=self.env,
            payload={
                'line_mode': 'patch',
                'order_lines': [
                    {
                        'id': line_a.id,
                        'action': 'upsert',
                        'price_unit': 3333.0,
                        'description': 'Patched line',
                    },
                    {
                        'action': 'upsert',
                        'display_type': 'line_note',
                        'name': 'Patch note',
                    },
                    {
                        'id': line_b.id,
                        'action': 'delete',
                    },
                ],
            },
        )

        order.invalidate_recordset()
        self.assertEqual(line_a.price_unit, 3333.0)
        self.assertEqual(line_a.description, 'Patched line')
        self.assertFalse(line_b.exists())
        self.assertTrue(order.order_line.filtered(lambda line: line.display_type == 'line_note' and line.name == 'Patch note'))
        self.assertEqual(len(result['order_lines']), 2)

    def test_v2_write_order_line_validation_guards(self):
        order, _line_a, _line_b = self._create_write_test_order(with_protected_lines=True)
        protected_line = order.order_line.filtered(lambda line: self.controller._is_system_order_line(line))[:1]

        with self.assertRaises(ValueError):
            self.controller._update_v2_order(
                order.id,
                env=self.env,
                payload={
                    'order_lines': [],
                },
            )

        with self.assertRaises(ValueError):
            self.controller._create_v2_order(
                env=self.env,
                payload={
                    'partner_id': self.partner.id,
                    'order_lines': [
                        {
                            'product_id': self.product.id,
                            'price_unit': -1,
                        }
                    ],
                },
            )

        with self.assertRaises(ValueError):
            self.controller._create_v2_order(
                env=self.env,
                payload={
                    'partner_id': self.partner.id,
                    'order_lines': [
                        {
                            'display_type': 'line_note',
                            'name': 'Khoản cọc nội bộ',
                        }
                    ],
                },
            )

        with self.assertRaises(ValueError):
            self.controller._update_v2_order(
                order.id,
                env=self.env,
                payload={
                    'line_mode': 'patch',
                    'order_lines': [
                        {
                            'id': protected_line.id,
                            'action': 'delete',
                        }
                    ],
                },
            )
