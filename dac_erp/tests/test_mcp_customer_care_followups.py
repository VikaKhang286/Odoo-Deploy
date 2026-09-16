from datetime import datetime, timedelta
from types import MethodType
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpCustomerCareFollowups(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; customer care follow-up tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Care Followup Owner',
            'login': 'care_followup_owner@example.com',
            'email': 'care_followup_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Care Followup Participant',
            'login': 'care_followup_participant@example.com',
            'email': 'care_followup_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Care Followup Staff',
            'login': 'care_followup_staff@example.com',
            'email': 'care_followup_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Care Followup Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Care Followup Page',
            'page_fm_id_str': 'care-followup-page-001',
        })
        cls.conversation_model_id = cls.env['ir.model']._get_id('page.fm.conversation')
        cls.todo_activity_type = cls.env.ref('mail.mail_activity_data_todo')

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'conversation_ids': [],
            'default_deadline_date': '2026-05-02',
            'summary_template': 'Phan hoi khach dang cho',
            'note_template': 'Khach cho {waiting_minutes} phut. Uu tien: {care_priority}.',
            'sla_minutes': 60,
            'dedupe_existing_open_activity': True,
            'revalidate_queue': True,
            'set_require_processing': True,
            'dry_run': False,
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'reason': 'bulk_customer_care_reminder',
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
            'conversation_fm_id': 'care-followup-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Followup Customer %s' % suffix,
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
            'message_fm_id': 'care-followup-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
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
            self.controller._dispatch_mcp_customer_care_create_followups,
            env=self.env,
            headers=self._headers(api_key),
            payload=payload,
        )

    def _activities_for(self, conversation):
        return self.env['mail.activity'].search([
            ('res_model_id', '=', self.conversation_model_id),
            ('res_id', '=', conversation.id),
        ])

    def _assert_bulk_log(self, request_id, status='success'):
        log = self.env['dac_erp.mcp.bulk.log'].search([('request_id', '=', request_id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.status, status)
        return log

    def test_missing_invalid_and_write_key_auth(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_create_followups,
            env=self.env,
            headers={},
            payload=self._base_payload('bulk-missing-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self._run_bulk(self._base_payload('bulk-readonly-001'), api_key='mcp-read-test-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        conversation = self._create_conversation('auth', is_unread=True)
        payload, status_code = self._run_bulk(
            self._base_payload('bulk-auth-001', conversation_ids=[conversation.id], dry_run=True),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])

    def test_validation_rules(self):
        cases = [
            ({'conversation_ids': None}, 'validation_error'),
            ({'conversation_ids': []}, 'validation_error'),
            ({'conversation_ids': list(range(1, 52))}, 'validation_error'),
            ({'conversation_ids': [1], 'request_id': ''}, 'validation_error'),
            ({'conversation_ids': [1], 'agent_name': ''}, 'validation_error'),
            ({'conversation_ids': [1], 'reason': ''}, 'validation_error'),
            ({'conversation_ids': [1], 'activity_type_xmlid': 'dac_erp.missing_xmlid'}, 'validation_error'),
        ]
        for index, (extra, expected_code) in enumerate(cases):
            payload = self._base_payload('bulk-validation-%s' % index)
            payload.update(extra)
            result_payload, status_code = self._run_bulk(payload)
            self.assertEqual(status_code, 400)
            self.assertEqual(result_payload['error']['code'], expected_code)

    def test_dry_run_does_not_create_activity_and_returns_would_create(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('dry-run')
        self._create_message(conversation, now - timedelta(minutes=90), sender='customer')

        payload, status_code = self._run_bulk(
            self._base_payload('bulk-dry-run-001', conversation_ids=[conversation.id], dry_run=True),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['created_count'], 0)
        self.assertEqual(payload['data']['failed_count'], 0)
        self.assertTrue(payload['data']['dry_run'])
        self.assertEqual(payload['data']['items'][0]['action'], 'would_create')
        self.assertFalse(self._activities_for(conversation))
        self._assert_bulk_log('bulk-dry-run-001')

    def test_queue_risk_conversations_create_activity_for_owner(self):
        now = datetime.utcnow().replace(microsecond=0)
        unreplied = self._create_conversation('unreplied')
        self._create_message(unreplied, now - timedelta(minutes=85), sender='customer')
        unread = self._create_conversation('unread', is_unread=True)
        require_processing = self._create_conversation('processing', require_processing=True)

        payload, status_code = self._run_bulk(
            self._base_payload(
                'bulk-create-001',
                conversation_ids=[unreplied.id, unread.id, require_processing.id],
            ),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['created_count'], 3)
        self.assertEqual(payload['data']['skipped_count'], 0)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        for conversation in (unreplied, unread, require_processing):
            activity = self._activities_for(conversation)
            self.assertEqual(len(activity), 1)
            self.assertEqual(activity.user_id.id, self.owner_user.id)
            self.assertEqual(item_map[conversation.id]['action'], 'created')
            self.assertEqual(item_map[conversation.id]['assigned_user_id'], self.owner_user.id)
            self.assertTrue(item_map[conversation.id]['log_id'])

    def test_revalidate_queue_and_no_assignee_and_internal_skips(self):
        not_in_queue = self._create_conversation('not-in-queue', owner=True, participants=True, status_state='waiting')
        no_assignee = self._create_conversation('no-assignee', is_unread=True, owner=False, participants=False)
        internal = self._create_conversation('internal', is_unread=True, internal=True)

        payload, status_code = self._run_bulk(
            self._base_payload(
                'bulk-skips-001',
                conversation_ids=[not_in_queue.id, no_assignee.id, internal.id],
            ),
        )
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[not_in_queue.id]['skip_reason'], 'not_in_customer_care_queue')
        self.assertEqual(item_map[no_assignee.id]['skip_reason'], 'no_assigned_user')
        self.assertEqual(item_map[internal.id]['skip_reason'], 'invalid_conversation_state')

    def test_existing_open_activity_is_skipped_and_dedupe_false_allows_new(self):
        conversation = self._create_conversation('dedupe', is_unread=True)
        existing = self.env['mail.activity'].create({
            'activity_type_id': self.todo_activity_type.id,
            'res_model_id': self.conversation_model_id,
            'res_id': conversation.id,
            'user_id': self.owner_user.id,
            'summary': 'Phan hoi khach dang cho',
            'note': 'Existing open follow-up',
            'date_deadline': '2026-05-02',
        })

        payload, status_code = self._run_bulk(
            self._base_payload('bulk-dedupe-001', conversation_ids=[conversation.id]),
        )
        self.assertEqual(status_code, 200)
        item = payload['data']['items'][0]
        self.assertEqual(item['action'], 'skipped')
        self.assertEqual(item['skip_reason'], 'open_activity_exists')
        self.assertEqual(item['existing_activity_id'], existing.id)
        self.assertEqual(len(self._activities_for(conversation)), 1)

        payload, status_code = self._run_bulk(
            self._base_payload(
                'bulk-dedupe-002',
                conversation_ids=[conversation.id],
                dedupe_existing_open_activity=False,
            ),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['items'][0]['action'], 'created')
        self.assertEqual(len(self._activities_for(conversation)), 2)

    def test_set_require_processing_true_does_not_mark_read_or_set_done(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('triage', require_processing=False, is_unread=True, status_state='new')
        self._create_message(conversation, now - timedelta(minutes=70), sender='customer')

        payload, status_code = self._run_bulk(
            self._base_payload('bulk-triage-001', conversation_ids=[conversation.id]),
        )
        self.assertEqual(status_code, 200)
        conversation.invalidate_recordset()
        self.assertTrue(conversation.require_processing)
        self.assertTrue(conversation.is_unread_fm)
        self.assertNotEqual(conversation.status_state, 'done')

    def test_idempotency_replay_and_conflict(self):
        conversation = self._create_conversation('idempotency', is_unread=True)
        payload = self._base_payload('bulk-idempotency-001', conversation_ids=[conversation.id])

        first_payload, first_status = self._run_bulk(payload)
        self.assertEqual(first_status, 200)
        activity_count_after_first = len(self._activities_for(conversation))

        replay_payload, replay_status = self._run_bulk(payload)
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(len(self._activities_for(conversation)), activity_count_after_first)

        conflict_payload, conflict_status = self._run_bulk(
            self._base_payload('bulk-idempotency-001', conversation_ids=[conversation.id], summary_template='Khac'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'idempotency_conflict')

    def test_one_item_fail_does_not_fail_whole_batch(self):
        first = self._create_conversation('fail-first', is_unread=True)
        second = self._create_conversation('fail-second', is_unread=True)
        original = self.controller._create_customer_care_followup_activity_result

        def patched(controller_self, env, conversation, assigned_user, normalized_payload, queue_row):
            if conversation.id == first.id:
                raise ValueError('Simulated item failure')
            return original(env, conversation, assigned_user, normalized_payload, queue_row)

        self.controller._create_customer_care_followup_activity_result = MethodType(patched, self.controller)
        try:
            payload, status_code = self._run_bulk(
                self._base_payload('bulk-partial-failure-001', conversation_ids=[first.id, second.id]),
            )
        finally:
            self.controller._create_customer_care_followup_activity_result = original

        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['created_count'], 1)
        self.assertEqual(payload['data']['failed_count'], 1)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[first.id]['action'], 'failed')
        self.assertEqual(item_map[first.id]['error']['code'], 'validation_error')
        self.assertEqual(item_map[second.id]['action'], 'created')
        self.assertEqual(len(self._activities_for(first)), 0)
        self.assertEqual(len(self._activities_for(second)), 1)

    def test_all_missing_conversations_returns_404(self):
        payload, status_code = self._run_bulk(
            self._base_payload('bulk-missing-conversations-001', conversation_ids=[99999901, 99999902]),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')
