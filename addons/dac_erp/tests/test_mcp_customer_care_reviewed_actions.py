from datetime import datetime, timedelta
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpCustomerCareReviewedActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; reviewed customer care tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reviewed Care Owner',
            'login': 'reviewed_care_owner@example.com',
            'email': 'reviewed_care_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reviewed Care Participant',
            'login': 'reviewed_care_participant@example.com',
            'email': 'reviewed_care_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reviewed Care Staff',
            'login': 'reviewed_care_staff@example.com',
            'email': 'reviewed_care_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Reviewed Care Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Reviewed Care Page',
            'page_fm_id_str': 'reviewed-care-page-001',
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'items': [],
            'default_note_template': 'OpenClaw review: {care_priority} - {care_reason}. Khach cho {waiting_minutes} phut. {triage_preset}',
            'revalidate_queue': True,
            'dry_run': False,
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'reason': 'reviewed_customer_care_actions',
        }
        payload.update(extra)
        return payload

    def _create_conversation(
        self,
        suffix,
        require_processing=False,
        is_unread=False,
        owner=True,
        participants=True,
        internal=False,
        status_state='recontact',
    ):
        participant_ids = []
        if participants:
            participant_ids = [self.participant_user.id]
            if owner:
                participant_ids.insert(0, self.owner_user.id)
        return self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'reviewed-care-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Reviewed Customer %s' % suffix,
            'owner_id': self.owner_user.id if owner else False,
            'participant_user_ids': [(6, 0, participant_ids)],
            'platform_fm': 'facebook',
            'status_state': status_state,
            'require_processing': require_processing,
            'is_unread_fm': is_unread,
            'is_internal_conversation': internal,
        })

    def _create_message(self, conversation, inserted_at, sender='customer', content_html=None):
        vals = {
            'message_fm_id': 'reviewed-care-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
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
            vals.update({'sender_name_fm': 'Customer Sender'})
        return self.env['page.fm.message'].create(vals)

    def _run_bulk(self, payload, api_key='mcp-write-test-key'):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_apply_reviewed_actions,
            env=self.env,
            headers=self._headers(api_key),
            payload=payload,
        )

    def _ai_logs(self, conversation, action_type=None):
        domain = [('conversation_id', '=', conversation.id)]
        if action_type:
            domain.append(('action_type', '=', action_type))
        return self.env['page.fm.conversation.ai.log'].search(domain, order='id asc')

    def _bulk_log(self, request_id):
        return self.env['dac_erp.mcp.bulk.log'].search([('request_id', '=', request_id)], limit=1)

    def test_auth_and_request_validation(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_apply_reviewed_actions,
            env=self.env,
            headers={},
            payload=self._base_payload('reviewed-missing-key-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self._run_bulk(self._base_payload('reviewed-read-key-001'), api_key='mcp-read-test-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        cases = [
            ({'items': None}, 'validation_error'),
            ({'items': []}, 'validation_error'),
            ({'items': [{}] * 51}, 'validation_error'),
            ({'request_id': ''}, 'validation_error'),
            ({'agent_name': ''}, 'validation_error'),
            ({'reason': ''}, 'validation_error'),
        ]
        for index, (extra, expected_code) in enumerate(cases):
            payload = self._base_payload('reviewed-validation-%s' % index)
            payload.update(extra)
            result_payload, result_status = self._run_bulk(payload)
            self.assertEqual(result_status, 400)
            self.assertEqual(result_payload['error']['code'], expected_code)

    def test_item_level_failures_and_partial_batch(self):
        valid = self._create_conversation('partial', is_unread=True)
        valid.sudo().write({'require_processing': False, 'is_unread_fm': True})

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-partial-001',
            default_note_template=False,
            items=[
                {'note_text': 'missing conversation'},
                {'conversation_id': valid.id, 'triage_preset': 'keep_processing'},
                {'conversation_id': valid.id, 'note_text': '', 'triage_preset': False},
            ],
        ))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['processed_count'], 3)
        self.assertEqual(payload['data']['failed_count'], 1)
        self.assertEqual(payload['data']['skipped_count'], 2)
        self.assertEqual(payload['data']['items'][0]['action'], 'failed')
        self.assertIn(payload['data']['items'][1]['action'], ('triage_updated', 'skipped'))
        self.assertEqual(payload['data']['items'][2]['skip_reason'], 'no_action_requested')

    def test_dry_run_returns_expected_action_without_mutation(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('dry-run', is_unread=True, status_state='new')
        self._create_message(conversation, now - timedelta(minutes=95), sender='customer')
        before_values = (conversation.require_processing, conversation.status_state, conversation.is_unread_fm)

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-dry-run-001',
            dry_run=True,
            default_note_template=False,
            items=[{
                'conversation_id': conversation.id,
                'note_text': 'Can phan hoi ngay',
                'triage_preset': 'needs_staff_reply',
            }],
        ))
        self.assertEqual(status_code, 200)
        item = payload['data']['items'][0]
        self.assertEqual(item['action'], 'would_create_note_and_update_triage')
        self.assertEqual(payload['data']['note_created_count'], 0)
        self.assertEqual(payload['data']['triage_updated_count'], 0)
        conversation.invalidate_recordset()
        self.assertFalse(self._ai_logs(conversation))
        self.assertEqual((conversation.require_processing, conversation.status_state, conversation.is_unread_fm), before_values)

    def test_note_text_creates_internal_note_and_template_renders(self):
        now = datetime.utcnow().replace(microsecond=0)
        explicit = self._create_conversation('note-explicit', is_unread=True)
        template_conv = self._create_conversation('note-template', is_unread=True)
        self._create_message(explicit, now - timedelta(minutes=80), sender='customer')
        self._create_message(template_conv, now - timedelta(minutes=70), sender='customer')

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-notes-001',
            items=[
                {
                    'conversation_id': explicit.id,
                    'note_text': 'Khach da hoi lai ve lich giao hang.',
                    'note_type': 'internal_note',
                },
                {
                    'conversation_id': template_conv.id,
                    'triage_preset': 'note_only',
                },
            ],
        ))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['note_created_count'], 2)
        explicit_log = self._ai_logs(explicit, 'note_create')[-1]
        template_log = self._ai_logs(template_conv, 'note_create')[-1]
        self.assertIn('Khach da hoi lai ve lich giao hang.', explicit_log.note_text or '')
        self.assertIn('OpenClaw review:', template_log.note_text or '')
        self.assertIn('note_only', template_log.note_text or '')

    def test_needs_staff_reply_waiting_customer_and_internal_review_presets(self):
        now = datetime.utcnow().replace(microsecond=0)
        needs_reply = self._create_conversation('needs-reply', status_state='new')
        waiting_customer = self._create_conversation('waiting-customer', require_processing=True, status_state='recontact')
        internal_review = self._create_conversation('internal-review', status_state='new')
        self._create_message(needs_reply, now - timedelta(minutes=85), sender='customer')
        self._create_message(waiting_customer, now - timedelta(minutes=50), sender='customer')
        self._create_message(waiting_customer, now - timedelta(minutes=10), sender='staff')
        self._create_message(internal_review, now - timedelta(minutes=130), sender='customer')

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-presets-001',
            default_note_template=False,
            items=[
                {
                    'conversation_id': needs_reply.id,
                    'note_text': 'Can nhan vien phan hoi trong hom nay.',
                    'triage_preset': 'needs_staff_reply',
                },
                {
                    'conversation_id': waiting_customer.id,
                    'triage_preset': 'waiting_customer',
                },
                {
                    'conversation_id': internal_review.id,
                    'note_text': 'Can quan ly xem lai.',
                    'note_type': 'warning',
                    'triage_preset': 'needs_internal_review',
                },
            ],
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        needs_reply.invalidate_recordset()
        waiting_customer.invalidate_recordset()
        internal_review.invalidate_recordset()

        self.assertEqual(item_map[needs_reply.id]['action'], 'note_created_and_triage_updated')
        self.assertEqual(needs_reply.status_state, 'recontact')
        self.assertTrue(needs_reply.require_processing)

        self.assertEqual(item_map[waiting_customer.id]['action'], 'triage_updated')
        self.assertEqual(waiting_customer.status_state, 'waiting')
        self.assertFalse(waiting_customer.require_processing)

        self.assertEqual(item_map[internal_review.id]['action'], 'note_created_and_triage_updated')
        self.assertEqual(internal_review.status_state, 'recontact')
        self.assertTrue(internal_review.require_processing)
        self.assertEqual(self._ai_logs(internal_review, 'note_create')[-1].note_text, 'Can quan ly xem lai.')

    def test_waiting_customer_and_clear_processing_unsafe_skips(self):
        now = datetime.utcnow().replace(microsecond=0)
        waiting_unsafe = self._create_conversation('waiting-unsafe', status_state='recontact')
        clear_unsafe = self._create_conversation('clear-unsafe', require_processing=True, status_state='recontact')
        self._create_message(waiting_unsafe, now - timedelta(minutes=20), sender='staff')
        self._create_message(waiting_unsafe, now - timedelta(minutes=5), sender='customer')
        self._create_message(clear_unsafe, now - timedelta(minutes=15), sender='staff')
        self._create_message(clear_unsafe, now - timedelta(minutes=2), sender='customer')

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-unsafe-001',
            default_note_template=False,
            items=[
                {'conversation_id': waiting_unsafe.id, 'triage_preset': 'waiting_customer'},
                {'conversation_id': clear_unsafe.id, 'triage_preset': 'clear_processing_after_staff_reply'},
            ],
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[waiting_unsafe.id]['skip_reason'], 'unsafe_waiting_customer_preset')
        self.assertEqual(item_map[clear_unsafe.id]['skip_reason'], 'unsafe_clear_processing')

    def test_keep_processing_and_no_mark_read_or_done(self):
        conversation = self._create_conversation('keep-processing', require_processing=False, is_unread=True, status_state='new')
        conversation.sudo().write({'require_processing': False, 'is_unread_fm': True, 'status_state': 'new'})

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-keep-processing-001',
            default_note_template=False,
            items=[{'conversation_id': conversation.id, 'triage_preset': 'keep_processing'}],
        ))
        self.assertEqual(status_code, 200)
        self.assertIn(payload['data']['items'][0]['action'], ('triage_updated', 'skipped'))
        conversation.invalidate_recordset()
        self.assertTrue(conversation.require_processing)
        self.assertTrue(conversation.is_unread_fm)
        self.assertNotEqual(conversation.status_state, 'done')

    def test_internal_done_and_not_found_skips(self):
        now = datetime.utcnow().replace(microsecond=0)
        internal = self._create_conversation('internal', is_unread=True, internal=True)
        done_conversation = self._create_conversation('done', is_unread=True, status_state='done')
        self._create_message(internal, now - timedelta(minutes=75), sender='customer')
        self._create_message(done_conversation, now - timedelta(minutes=70), sender='customer')

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-skip-001',
            default_note_template=False,
            items=[
                {'conversation_id': internal.id, 'triage_preset': 'keep_processing'},
                {'conversation_id': done_conversation.id, 'triage_preset': 'needs_staff_reply'},
                {'conversation_id': 99999991, 'triage_preset': 'keep_processing'},
            ],
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[internal.id]['skip_reason'], 'internal_conversation')
        self.assertEqual(item_map[done_conversation.id]['skip_reason'], 'already_done')
        self.assertEqual(item_map[99999991]['skip_reason'], 'not_found')

    def test_idempotency_replay_and_conflict(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('idempotency', status_state='new')
        self._create_message(conversation, now - timedelta(minutes=88), sender='customer')
        payload = self._base_payload(
            'reviewed-idempotency-001',
            default_note_template=False,
            items=[{
                'conversation_id': conversation.id,
                'note_text': 'Can follow-up',
                'triage_preset': 'needs_staff_reply',
            }],
        )

        first_payload, first_status = self._run_bulk(payload)
        self.assertEqual(first_status, 200)
        note_log_count = len(self._ai_logs(conversation, 'note_create'))
        triage_log_count = len(self._ai_logs(conversation, 'triage_update'))

        replay_payload, replay_status = self._run_bulk(payload)
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(len(self._ai_logs(conversation, 'note_create')), note_log_count)
        self.assertEqual(len(self._ai_logs(conversation, 'triage_update')), triage_log_count)

        conflict_payload, conflict_status = self._run_bulk(self._base_payload(
            'reviewed-idempotency-001',
            default_note_template=False,
            items=[{
                'conversation_id': conversation.id,
                'note_text': 'Noi dung khac',
                'triage_preset': 'needs_staff_reply',
            }],
        ))
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'idempotency_conflict')

    def test_all_missing_conversations_returns_404_and_bulk_log_written(self):
        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-missing-conversations-001',
            default_note_template=False,
            items=[
                {'conversation_id': 99999901, 'triage_preset': 'keep_processing'},
                {'conversation_id': 99999902, 'triage_preset': 'keep_processing'},
            ],
        ))
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_bulk_log_and_response_counts(self):
        now = datetime.utcnow().replace(microsecond=0)
        create_both = self._create_conversation('counts-both', status_state='new')
        skip_conv = self._create_conversation('counts-skip', status_state='waiting')
        self._create_message(create_both, now - timedelta(minutes=77), sender='customer')

        payload, status_code = self._run_bulk(self._base_payload(
            'reviewed-counts-001',
            default_note_template=False,
            items=[
                {
                    'conversation_id': create_both.id,
                    'note_text': 'Can xu ly',
                    'triage_preset': 'needs_staff_reply',
                },
                {
                    'conversation_id': skip_conv.id,
                    'triage_preset': 'keep_processing',
                },
            ],
        ))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['processed_count'], 2)
        self.assertEqual(payload['data']['note_created_count'], 1)
        self.assertEqual(payload['data']['triage_updated_count'], 1)
        self.assertEqual(payload['data']['skipped_count'], 1)
        self.assertEqual(payload['data']['failed_count'], 0)
        log = self._bulk_log('reviewed-counts-001')
        self.assertTrue(log)
        self.assertEqual(log.action_type, 'customer_care_apply_reviewed_actions')
