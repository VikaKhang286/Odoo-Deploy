from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPancakeRawConversationLinking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.SaleOrder = cls.env['sale.order']
        cls.has_pancake_models = (
            'page.fm.page' in cls.env.registry.models
            and 'page.fm.conversation' in cls.env.registry.models
        )
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; Pancake conversation link tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.company = cls.env.company
        cls.team = cls.env['crm.team'].create({
            'name': 'Raw Conversation Link Team',
            'company_id': cls.company.id,
        })
        cls.creator_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Raw Conversation Creator',
            'login': 'raw_conversation_creator@example.com',
            'email': 'raw_conversation_creator@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        if 'pancake_id' in cls.creator_user._fields:
            cls.creator_user.pancake_id = 'creator-raw-conv-001'

        cls.page = cls.env['page.fm.page'].create({
            'name': 'Raw Conversation Page',
            'page_fm_id_str': 'raw-conv-page-001',
            'sync_enabled': True,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Raw Conversation Partner',
            'phone': '0901000001',
            'company_id': cls.company.id,
            'pancake_id': 'customer-raw-conv-001',
        })

    def _build_payload(self, order_id, conversation_id=None, page_id=None, customer_id=None):
        return {
            'id': str(order_id),
            'status': '1',
            'status_name': 'New',
            'status_history': [{'status': '1'}],
            'inserted_at': '2026-05-07T09:00:00.000000',
            'updated_at': '2026-05-07T09:00:00.000000',
            'order_currency': self.company.currency_id.name,
            'note': 'raw conversation link test',
            'link_confirm_order': 'https://example.com/order/%s' % order_id,
            'items': [],
            'tags': [],
            'shipping_address': {},
            'creator': {
                'id': 'creator-raw-conv-001',
                'name': self.creator_user.name,
                'email': self.creator_user.login,
            },
            'assigning_seller': {},
            'customer': {
                'id': customer_id or self.partner.pancake_id,
                'name': self.partner.name,
                'phone_numbers': [self.partner.phone],
                'emails': ['customer-raw-conv@example.com'],
                'notes': [],
                'fb_id': 'fb-customer-raw-conv-001',
            },
            'conversation_id': conversation_id,
            'page_id': page_id or self.page.page_fm_id_str,
        }

    def _make_conversation(self, conversation_fm_id, partner=None, phone=None):
        partner = partner or self.partner
        return self.env['page.fm.conversation'].create({
            'conversation_fm_id': conversation_fm_id,
            'page_fm_page_id': self.page.id,
            'partner_id': partner.id if partner else False,
            'phone': phone or partner.phone,
            'customer_fm_id': 'customer-fm-%s' % conversation_fm_id,
            'is_internal_conversation': False,
        })

    def _make_pancake_order(self, pancake_order_id, raw_payload, conversation=None, partner=None):
        vals = {
            'partner_id': (partner or self.partner).id,
            'company_id': self.company.id,
            'pancake_order_id': pancake_order_id,
            'pancake_raw_data': raw_payload,
        }
        order = self.SaleOrder.create(vals)
        if conversation:
            self._set_order_conversation_id(order, conversation)
        return order

    def _set_order_conversation_id(self, order, conversation):
        self.env.cr.execute(
            "UPDATE sale_order SET conversation_id = %s WHERE id = %s",
            [conversation.id if conversation else False, order.id],
        )
        order.invalidate_recordset(['conversation_id'])

    def _get_order_conversation_id(self, order):
        self.env.cr.execute("SELECT conversation_id FROM sale_order WHERE id = %s", [order.id])
        row = self.env.cr.fetchone()
        return row[0] if row else False

    def test_sync_single_links_order_when_raw_conversation_exists(self):
        conversation = self._make_conversation('raw-sync-single-001')
        payload = self._build_payload(
            order_id='raw-sync-single-001',
            conversation_id=conversation.conversation_fm_id,
        )

        resolution = self.SaleOrder._resolve_safe_pancake_conversation_link(payload)
        self.assertEqual(resolution['status'], 'safe_to_link')
        self.assertEqual(resolution['conversation'].id, conversation.id)
        self.assertEqual(resolution['raw_conversation_id'], conversation.conversation_fm_id)

    def test_sync_single_preserves_existing_link_when_raw_conversation_not_found(self):
        existing_conversation = self._make_conversation('raw-existing-001')
        self._make_conversation('raw-other-001')
        existing_order = self._make_pancake_order(
            pancake_order_id='raw-sync-preserve-001',
            raw_payload=str({'conversation_id': 'raw-existing-001', 'page_id': self.page.page_fm_id_str}),
            conversation=existing_conversation,
        )

        payload = self._build_payload(
            order_id='raw-sync-preserve-001',
            conversation_id='raw-missing-001',
        )
        existing_order.write({'pancake_raw_data': str(payload)})
        summary = existing_order.action_backfill_pancake_conversation_links_from_raw_payload(dry_run=False)

        self.assertEqual(summary['no_conversation_match'], 1)
        self.assertEqual(summary['linked'], 0)
        self.assertEqual(self._get_order_conversation_id(existing_order), existing_conversation.id)

    def test_duplicate_partner_phone_still_uses_raw_conversation_id(self):
        other_partner = self.env['res.partner'].create({
            'name': 'Raw Conversation Partner 2',
            'phone': self.partner.phone,
            'company_id': self.company.id,
        })
        raw_conversation = self._make_conversation('raw-dup-001', partner=self.partner, phone=self.partner.phone)
        self._make_conversation('raw-dup-002', partner=other_partner, phone=self.partner.phone)

        order = self._make_pancake_order(
            pancake_order_id='raw-dup-order-001',
            raw_payload=str({
                'conversation_id': raw_conversation.conversation_fm_id,
                'page_id': self.page.page_fm_id_str,
            }),
            conversation=False,
            partner=self.partner,
        )

        summary = order.action_backfill_pancake_conversation_links_from_raw_payload(dry_run=False)

        self.assertEqual(summary['safe_to_link'], 1)
        self.assertEqual(summary['linked'], 1)
        self.assertEqual(self._get_order_conversation_id(order), raw_conversation.id)

    def test_backfill_dry_run_does_not_write(self):
        conversation = self._make_conversation('raw-dry-run-001')
        order = self._make_pancake_order(
            pancake_order_id='raw-dry-run-order-001',
            raw_payload=str({
                'conversation_id': conversation.conversation_fm_id,
                'page_id': self.page.page_fm_id_str,
            }),
        )

        summary = order.action_backfill_pancake_conversation_links_from_raw_payload(dry_run=True)

        self.assertEqual(summary['total_checked'], 1)
        self.assertEqual(summary['safe_to_link'], 1)
        self.assertEqual(summary['linked'], 0)
        self.assertFalse(self._get_order_conversation_id(order))

    def test_backfill_execute_links_only_safe_exact(self):
        safe_conversation = self._make_conversation('raw-exec-safe-001')
        safe_order = self._make_pancake_order(
            pancake_order_id='raw-exec-safe-order-001',
            raw_payload=str({
                'conversation_id': safe_conversation.conversation_fm_id,
                'page_id': self.page.page_fm_id_str,
            }),
        )
        missing_order = self._make_pancake_order(
            pancake_order_id='raw-exec-missing-order-001',
            raw_payload=str({
                'conversation_id': 'raw-not-found-001',
                'page_id': self.page.page_fm_id_str,
            }),
        )

        summary = (safe_order | missing_order).action_backfill_pancake_conversation_links_from_raw_payload(dry_run=False)

        self.assertEqual(summary['total_checked'], 2)
        self.assertEqual(summary['safe_to_link'], 1)
        self.assertEqual(summary['linked'], 1)
        self.assertEqual(summary['no_conversation_match'], 1)
        self.assertEqual(self._get_order_conversation_id(safe_order), safe_conversation.id)
        self.assertFalse(self._get_order_conversation_id(missing_order))

    def test_backfill_existing_conflict_is_not_overwritten(self):
        current_conversation = self._make_conversation('raw-conflict-current-001')
        raw_conversation = self._make_conversation('raw-conflict-target-001')
        order = self._make_pancake_order(
            pancake_order_id='raw-conflict-order-001',
            raw_payload=str({
                'conversation_id': raw_conversation.conversation_fm_id,
                'page_id': self.page.page_fm_id_str,
            }),
            conversation=current_conversation,
        )

        summary = order.action_backfill_pancake_conversation_links_from_raw_payload(dry_run=False)

        self.assertEqual(summary['total_checked'], 1)
        self.assertEqual(summary['existing_conflict'], 1)
        self.assertEqual(summary['linked'], 0)
        self.assertEqual(self._get_order_conversation_id(order), current_conversation.id)
