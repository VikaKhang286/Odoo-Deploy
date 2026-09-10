from datetime import datetime, timedelta
from types import MethodType
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpCustomerCareAutoRun(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; customer-care auto-run tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Auto Run Owner',
            'login': 'auto_run_owner@example.com',
            'email': 'auto_run_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Auto Run Participant',
            'login': 'auto_run_participant@example.com',
            'email': 'auto_run_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Auto Run Staff',
            'login': 'auto_run_staff@example.com',
            'email': 'auto_run_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Auto Run Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Auto Run Page',
            'page_fm_id_str': 'auto-run-page-001',
        })
        cls.conversation_model_id = cls.env['ir.model']._get_id('page.fm.conversation')
        cls.todo_activity_type = cls.env.ref('mail.mail_activity_data_todo')
        cls.call_activity_type = cls.env.ref('mail.mail_activity_data_call')
        cls.followup_activity_type = cls.env.ref('dac_erp.mail_activity_type_cskh_followup')

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp.customer_care.sla_minutes_default', '60')
        icp.set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '120')
        icp.set_param('dac_erp.mcp.customer_care.default_policy', 'standard')
        icp.set_param('dac_erp.mcp.activity_type.todo_xmlid', 'mail.mail_activity_data_todo')
        icp.set_param('dac_erp.mcp.activity_type.call_xmlid', 'mail.mail_activity_data_call')
        icp.set_param('dac_erp.mcp.activity_type.followup_xmlid', 'dac_erp.mail_activity_type_cskh_followup')
        icp.set_param('dac_erp.mcp.customer_care.urgent_activity_type', 'call')
        icp.set_param('dac_erp.mcp.customer_care.high_activity_type', 'followup')
        icp.set_param('dac_erp.mcp.customer_care.medium_activity_type', 'todo')
        icp.set_param('dac_erp.mcp.customer_care.low_activity_type', 'none')
        icp.set_param('dac_erp.mcp.working_hours.morning_start', '08:00')
        icp.set_param('dac_erp.mcp.working_hours.morning_end', '12:00')
        icp.set_param('dac_erp.mcp.working_hours.afternoon_start', '13:30')
        icp.set_param('dac_erp.mcp.working_hours.afternoon_end', '17:30')
        icp.set_param('dac_erp.mcp.working_hours.working_days', '1,2,3,4,5,6')
        icp.set_param('dac_erp.mcp.working_hours.timezone_mode', 'fixed')
        icp.set_param('dac_erp.mcp.working_hours.fixed_timezone', 'Asia/Ho_Chi_Minh')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_enabled', 'False')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_dry_run_default', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_batch_limit', '50')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_execute_followups', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_execute_notes', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_execute_triage', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_exclude_internal', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_allow_mark_read', 'False')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_allow_done', 'False')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_cron_enabled', 'False')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_cron_interval_minutes', '30')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_working_hours_only', 'True')

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'policy': 'standard',
            'batch_limit': 50,
            'dry_run': True,
            'execute_followups': True,
            'execute_notes': True,
            'execute_triage': True,
            'dedupe_existing_open_activity': True,
            'set_require_processing': True,
            'include_messages': False,
            'message_limit': 5,
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'reason': 'scheduled_customer_care_auto_run',
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
        status_state='new',
    ):
        participant_ids = []
        if participants:
            participant_ids = [self.participant_user.id]
            if owner:
                participant_ids.insert(0, self.owner_user.id)
        return self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'auto-run-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Auto Run Customer %s' % suffix,
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
            'message_fm_id': 'auto-run-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
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

    def _run_auto(self, payload, api_key='mcp-write-test-key'):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_auto_run,
            env=self.env,
            headers=self._headers(api_key),
            payload=payload,
        )

    def _run_report(self, run_id, api_key='mcp-read-test-key'):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_auto_run_report,
            run_id,
            env=self.env,
            headers=self._headers(api_key),
        )

    def _activities_for(self, conversation):
        return self.env['mail.activity'].search([
            ('res_model_id', '=', self.conversation_model_id),
            ('res_id', '=', conversation.id),
        ])

    def _ai_logs_for(self, conversation, action_type=None):
        domain = [('conversation_id', '=', conversation.id)]
        if action_type:
            domain.append(('action_type', '=', action_type))
        return self.env['page.fm.conversation.ai.log'].search(domain)

    def _get_auto_run_log(self, request_id):
        return self.env['dac_erp.mcp.auto.run.log'].search([('request_id', '=', request_id)], limit=1)

    def test_auth_and_validation(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_auto_run,
            env=self.env,
            headers={},
            payload=self._base_payload('auto-missing-001'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self._run_auto(self._base_payload('auto-read-001'), api_key='mcp-read-test-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

        payload, status_code = self._run_auto(self._base_payload('auto-invalid-001'), api_key='wrong-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        conversation = self._create_conversation('auth', is_unread=True)
        payload, status_code = self._run_auto(
            self._base_payload('auto-auth-001', conversation_ids=[conversation.id]),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])

        for extra in (
            {'request_id': ''},
            {'agent_name': ''},
            {'reason': ''},
            {'policy': 'invalid'},
            {'conversation_ids': list(range(1, 102))},
        ):
            payload_dict = self._base_payload('auto-validation-base')
            payload_dict.update(extra)
            payload, status_code = self._run_auto(payload_dict)
            self.assertEqual(status_code, 400)
            self.assertEqual(payload['error']['code'], 'validation_error')

    def test_config_defaults_and_batch_limit_cap(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp.customer_care.default_policy', 'urgent_only')
        icp.set_param('dac_erp.mcp.customer_care.sla_minutes_default', '45')
        icp.set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '90')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_dry_run_default', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_batch_limit', '40')
        conversation = self._create_conversation('config-defaults', is_unread=True)

        payload, status_code = self._run_auto({
            'conversation_ids': [conversation.id],
            'request_id': 'auto-config-defaults-001',
            'agent_name': 'OpenClaw',
            'reason': 'scheduled_customer_care_auto_run',
        })
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['data']['dry_run'])
        self.assertEqual(payload['data']['policy'], 'urgent_only')
        self.assertEqual(payload['data']['sla_minutes'], 45)
        self.assertEqual(payload['data']['urgent_minutes'], 90)

        for index in range(0, 105):
            self._create_conversation('cap-%s' % index, is_unread=True)
        payload, status_code = self._run_auto(self._base_payload(
            'auto-batch-cap-001',
            batch_limit=999,
        ))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['batch_limit'], 100)
        self.assertLessEqual(payload['data']['summary']['evaluated_count'], 100)

    def test_dry_run_creates_log_without_mutation(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('dry-run', is_unread=True, status_state='new')
        self._create_message(conversation, now - timedelta(minutes=135), sender='customer')
        before_activity_count = len(self._activities_for(conversation))
        before_ai_log_count = len(self._ai_logs_for(conversation))
        before_state = (conversation.require_processing, conversation.status_state, conversation.is_unread_fm)

        payload, status_code = self._run_auto(
            self._base_payload('auto-dry-run-001', conversation_ids=[conversation.id], dry_run=True),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['items'][0]['status'], 'would_execute')
        self.assertTrue(payload['data']['items'][0]['planned_actions'])
        self.assertEqual(payload['data']['summary']['followup_created_count'], 0)
        self.assertEqual(payload['data']['summary']['note_created_count'], 0)
        self.assertEqual(payload['data']['summary']['triage_updated_count'], 0)
        self.assertTrue(self._get_auto_run_log('auto-dry-run-001'))

        conversation.invalidate_recordset()
        self.assertEqual(len(self._activities_for(conversation)), before_activity_count)
        self.assertEqual(len(self._ai_logs_for(conversation)), before_ai_log_count)
        self.assertEqual((conversation.require_processing, conversation.status_state, conversation.is_unread_fm), before_state)

    def test_execute_urgent_high_and_medium_activity_mapping(self):
        now = datetime.utcnow().replace(microsecond=0)
        urgent = self._create_conversation('urgent', is_unread=True, status_state='new')
        high = self._create_conversation('high', is_unread=True, status_state='new')
        medium = self._create_conversation('medium', require_processing=True, status_state='new')
        self._create_message(urgent, now - timedelta(minutes=135), sender='customer')
        self._create_message(high, now - timedelta(minutes=30), sender='customer')

        payload, status_code = self._run_auto(
            self._base_payload(
                'auto-execute-001',
                dry_run=False,
                conversation_ids=[urgent.id, high.id, medium.id],
            ),
        )
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[urgent.id]['status'], 'executed')
        self.assertEqual(item_map[urgent.id]['activity_type']['code'], 'call')
        self.assertEqual(item_map[medium.id]['activity_type']['code'], 'todo')
        self.assertEqual(len(self._activities_for(urgent)), 1)
        self.assertEqual(self._activities_for(urgent).activity_type_id.id, self.call_activity_type.id)
        self.assertEqual(len(self._activities_for(high)), 1)
        self.assertEqual(self._activities_for(medium).activity_type_id.id, self.todo_activity_type.id)
        urgent.invalidate_recordset()
        high.invalidate_recordset()
        self.assertTrue(urgent.require_processing)
        self.assertEqual(urgent.status_state, 'recontact')
        self.assertTrue(high.is_unread_fm)
        self.assertNotEqual(urgent.status_state, 'done')

    def test_conservative_and_urgent_only_policies(self):
        now = datetime.utcnow().replace(microsecond=0)
        medium = self._create_conversation('conservative-medium', require_processing=True, status_state='new')
        urgent = self._create_conversation('urgent-only-urgent', status_state='new')
        non_urgent = self._create_conversation('urgent-only-medium', require_processing=True, status_state='new')
        self._create_message(urgent, now - timedelta(minutes=135), sender='customer')

        payload, status_code = self._run_auto(
            self._base_payload('auto-conservative-001', dry_run=False, conversation_ids=[medium.id], policy='conservative'),
        )
        self.assertEqual(status_code, 200)
        self.assertIn(payload['data']['items'][0]['status'], ('no_action', 'skipped'))
        self.assertFalse(self._activities_for(medium))

        payload, status_code = self._run_auto(
            self._base_payload(
                'auto-urgent-only-001',
                dry_run=False,
                conversation_ids=[urgent.id, non_urgent.id],
                policy='urgent_only',
            ),
        )
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[urgent.id]['status'], 'executed')
        self.assertIn(item_map[non_urgent.id]['status'], ('skipped', 'no_action'))
        self.assertFalse(self._activities_for(non_urgent))

    def test_existing_activity_no_assignee_internal_done_and_toggles(self):
        now = datetime.utcnow().replace(microsecond=0)
        with_activity = self._create_conversation('with-activity', status_state='new')
        no_assignee = self._create_conversation('no-assignee', owner=False, participants=False, status_state='new')
        internal = self._create_conversation('internal', is_unread=True, internal=True)
        done_conversation = self._create_conversation('done', is_unread=True, status_state='done')
        toggle_target = self._create_conversation('toggle-target', status_state='new')
        self._create_message(with_activity, now - timedelta(minutes=85), sender='customer')
        self._create_message(no_assignee, now - timedelta(minutes=85), sender='customer')
        self._create_message(internal, now - timedelta(minutes=85), sender='customer')
        self._create_message(done_conversation, now - timedelta(minutes=85), sender='customer')
        self._create_message(toggle_target, now - timedelta(minutes=85), sender='customer')
        existing = self.env['mail.activity'].create({
            'activity_type_id': self.todo_activity_type.id,
            'res_model_id': self.conversation_model_id,
            'res_id': with_activity.id,
            'user_id': self.owner_user.id,
            'summary': 'Phan hoi khach dang cho',
            'note': 'Existing open follow-up',
            'date_deadline': '2026-05-02',
        })

        payload, status_code = self._run_auto(
            self._base_payload(
                'auto-existing-001',
                dry_run=False,
                conversation_ids=[with_activity.id, no_assignee.id, internal.id, done_conversation.id],
            ),
        )
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[with_activity.id]['activity_id'], None)
        self.assertNotIn('create_followup', item_map[with_activity.id]['executed_actions'])
        self.assertEqual(len(self._activities_for(with_activity)), 1)
        self.assertEqual(self._activities_for(with_activity).id, existing.id)
        self.assertEqual(item_map[no_assignee.id]['skip_reason'], 'no_assigned_user')
        self.assertEqual(item_map[internal.id]['skip_reason'], 'internal_conversation')
        self.assertEqual(item_map[done_conversation.id]['skip_reason'], 'already_done')

        payload, status_code = self._run_auto(
            self._base_payload(
                'auto-toggles-001',
                dry_run=False,
                conversation_ids=[toggle_target.id],
                execute_followups=False,
                execute_notes=False,
                execute_triage=False,
            ),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['items'][0]['status'], 'skipped')
        self.assertEqual(payload['data']['items'][0]['skip_reason'], 'action_disabled_by_request')
        self.assertFalse(self._activities_for(toggle_target))

    def test_partial_failure_idempotency_and_report(self):
        now = datetime.utcnow().replace(microsecond=0)
        first = self._create_conversation('first', status_state='new')
        second = self._create_conversation('second', status_state='new')
        self._create_message(first, now - timedelta(minutes=85), sender='customer')
        self._create_message(second, now - timedelta(minutes=85), sender='customer')

        original = self.controller._process_customer_care_followup_item

        def patched(controller_self, env, conversation, queue_row, normalized_payload):
            if conversation.id == first.id:
                return controller_self._build_customer_care_followup_item_result(
                    conversation,
                    queue_row,
                    action='failed',
                    ok=False,
                    error={'code': 'unexpected_error', 'message': 'Simulated follow-up failure'},
                )
            return original(env, conversation, queue_row, normalized_payload)

        self.controller._process_customer_care_followup_item = MethodType(patched, self.controller)
        try:
            payload, status_code = self._run_auto(
                self._base_payload('auto-partial-001', dry_run=False, conversation_ids=[first.id, second.id]),
            )
        finally:
            self.controller._process_customer_care_followup_item = original

        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[first.id]['status'], 'failed')
        self.assertEqual(item_map[second.id]['status'], 'executed')
        self.assertEqual(payload['data']['summary']['failed_count'], 1)

        replay_payload, replay_status = self._run_auto(
            self._base_payload('auto-partial-001', dry_run=False, conversation_ids=[first.id, second.id]),
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(self.env['dac_erp.mcp.auto.run.log'].search_count([('request_id', '=', 'auto-partial-001')]), 1)

        conflict_payload, conflict_status = self._run_auto(
            self._base_payload('auto-partial-001', dry_run=False, conversation_ids=[first.id]),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'idempotency_conflict')

        run_id = replay_payload['data']['run_id']
        report_payload, report_status = self._run_report(run_id)
        self.assertEqual(report_status, 200)
        self.assertEqual(report_payload['data']['run_id'], run_id)
        self.assertEqual(report_payload['data']['request_id'], 'auto-partial-001')
        self.assertTrue(report_payload['data']['items'])

    def test_cron_noop_and_same_minute_idempotency(self):
        now = datetime(2026, 5, 2, 10, 0, 0)
        result = self.controller._run_customer_care_auto_run_cron(env=self.env, now_dt=now)
        self.assertEqual(result['status'], 'noop')
        self.assertEqual(result['reason'], 'disabled')

        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp.customer_care.auto_run_enabled', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_cron_enabled', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_dry_run_default', 'False')
        conversation = self._create_conversation('cron', status_state='new')
        self._create_message(conversation, datetime.utcnow().replace(microsecond=0) - timedelta(minutes=135), sender='customer')

        outside = self.controller._run_customer_care_auto_run_cron(
            env=self.env,
            now_dt=datetime(2026, 5, 2, 22, 0, 0),
        )
        self.assertEqual(outside['status'], 'noop')
        self.assertEqual(outside['reason'], 'outside_working_hours')

        first = self.controller._run_customer_care_auto_run_cron(env=self.env, now_dt=now)
        second = self.controller._run_customer_care_auto_run_cron(env=self.env, now_dt=now)
        self.assertFalse(first['idempotent_replay'])
        self.assertTrue(second['idempotent_replay'])
        self.assertEqual(self.env['dac_erp.mcp.auto.run.log'].search_count([('request_id', '=', 'oclaw-auto-cron-20260502-1000')]), 1)
