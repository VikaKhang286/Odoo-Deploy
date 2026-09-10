import json
from datetime import datetime, timedelta
from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpCustomerCareActionPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; customer care action-plan tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Action Plan Owner',
            'login': 'action_plan_owner@example.com',
            'email': 'action_plan_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Action Plan Participant',
            'login': 'action_plan_participant@example.com',
            'email': 'action_plan_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Action Plan Staff',
            'login': 'action_plan_staff@example.com',
            'email': 'action_plan_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Action Plan Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Action Plan Page',
            'page_fm_id_str': 'action-plan-page-001',
        })
        cls.conversation_model_id = cls.env['ir.model']._get_id('page.fm.conversation')
        cls.todo_activity_type = cls.env.ref('mail.mail_activity_data_todo')

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, **extra):
        payload = {
            'sla_minutes': 60,
            'limit': 50,
            'offset': 0,
            'include_messages': False,
            'message_limit': 10,
            'include_existing_activity_check': True,
            'policy': 'standard',
            'default_deadline_date': '2026-05-02',
            'templates': {
                'followup_summary': 'Phan hoi khach dang cho',
                'followup_note': 'Khach dang cho {waiting_minutes} phut. Uu tien: {care_priority}.',
                'internal_note': 'OpenClaw review: {care_priority} - {care_reason}. Khach cho {waiting_minutes} phut.',
            },
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
        platform='facebook',
    ):
        participant_ids = []
        if participants:
            participant_ids = [self.participant_user.id]
            if owner:
                participant_ids.insert(0, self.owner_user.id)
        conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'action-plan-%s-%s' % (self._testMethodName, suffix),
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Action Plan Customer %s' % suffix,
            'owner_id': self.owner_user.id if owner else False,
            'participant_user_ids': [(6, 0, participant_ids)],
            'platform_fm': platform,
            'status_state': status_state,
            'require_processing': require_processing,
            'is_unread_fm': is_unread,
            'is_internal_conversation': internal,
        })
        conversation.sudo().write({
            'owner_id': self.owner_user.id if owner else False,
            'participant_user_ids': [(6, 0, participant_ids)],
            'status_state': status_state,
            'require_processing': require_processing,
            'is_unread_fm': is_unread,
            'is_internal_conversation': internal,
        })
        return conversation

    def _create_message(self, conversation, inserted_at, sender='customer', content_html=None):
        vals = {
            'message_fm_id': 'action-plan-msg-%s-%s' % (conversation.id, int(inserted_at.timestamp())),
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

    def _run_plan(self, payload=None, api_key='mcp-read-test-key'):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_action_plan,
            env=self.env,
            headers=self._headers(api_key),
            payload=payload,
        )

    def _steps_by_type(self, item):
        return {step['type']: step for step in item.get('recommended_steps') or []}

    def _serialize_steps(self, item):
        return json.dumps(item.get('recommended_steps') or [], ensure_ascii=False, sort_keys=True)

    def test_missing_invalid_read_and_write_key_auth(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_action_plan,
            env=self.env,
            headers={},
            payload={},
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self._run_plan({}, api_key='wrong-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        conversation = self._create_conversation('auth', is_unread=True)
        for api_key in ('mcp-read-test-key', 'mcp-write-test-key'):
            payload, status_code = self._run_plan({'conversation_ids': [conversation.id]}, api_key=api_key)
            self.assertEqual(status_code, 200)
            self.assertTrue(payload['ok'])

    def test_default_queue_plan_and_limit_caps(self):
        self._create_conversation('default-seed', is_unread=True)
        for index in range(0, 120):
            self._create_conversation('queue-%s' % index, is_unread=True)

        payload, status_code = self._run_plan({})
        self.assertEqual(status_code, 200)
        self.assertGreaterEqual(payload['data']['count'], 1)

        payload, status_code = self._run_plan(self._base_payload(limit=999))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['count'], 100)
        self.assertGreaterEqual(payload['data']['total'], 120)
        self.assertEqual(payload['data']['policy'], 'standard')
        self.assertEqual(payload['data']['sla_minutes'], 60)

    def test_conversation_ids_filter_message_cap_and_include_messages_toggle(self):
        now = datetime.utcnow().replace(microsecond=0)
        selected = self._create_conversation('selected')
        ignored = self._create_conversation('ignored', is_unread=True)
        for index in range(25):
            self._create_message(
                selected,
                now - timedelta(minutes=25 - index),
                sender='customer' if index % 2 == 0 else 'staff',
                content_html='<div>Message %s</div>' % index,
            )

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[selected.id],
            include_messages=False,
        ))
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['count'], 1)
        self.assertEqual(payload['data']['total'], 1)
        self.assertEqual(payload['data']['items'][0]['conversation_id'], selected.id)
        self.assertEqual(payload['data']['items'][0]['messages'], [])
        self.assertNotIn(ignored.id, [item['conversation_id'] for item in payload['data']['items']])

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[selected.id],
            include_messages=True,
            message_limit=999,
        ))
        self.assertEqual(status_code, 200)
        messages = payload['data']['items'][0]['messages']
        self.assertEqual(len(messages), 20)
        self.assertLess(messages[0]['id'], messages[-1]['id'])
        self.assertIn('content_text', messages[0])
        self.assertNotIn('raw_msg', messages[0])

    def test_conversation_ids_validation_cap(self):
        payload, status_code = self._run_plan(self._base_payload(conversation_ids=list(range(1, 52))))
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_standard_policy_waiting_customer_recommends_followup_and_reviewed_action(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('standard', status_state='new')
        self._create_message(conversation, now - timedelta(minutes=85), sender='customer')
        conversation.sudo().write({'require_processing': False, 'is_unread_fm': False, 'status_state': 'new'})

        before_activity_count = self.env['mail.activity'].search_count([])
        before_log_count = self.env['page.fm.conversation.ai.log'].search_count([])
        before_state = (conversation.require_processing, conversation.status_state, conversation.is_unread_fm)

        payload, status_code = self._run_plan(self._base_payload(conversation_ids=[conversation.id]))
        self.assertEqual(status_code, 200)
        item = payload['data']['items'][0]
        steps = self._steps_by_type(item)

        self.assertEqual(item['status'], 'action_recommended')
        self.assertIn(item['care_priority'], ('high', 'urgent'))
        self.assertIn('create_followup', steps)
        self.assertIn('apply_reviewed_actions', steps)
        self.assertEqual(
            steps['create_followup']['payload_template']['request_id'],
            self.controller.MCP_CUSTOMER_CARE_PLAN_REQUEST_ID_PLACEHOLDER,
        )
        self.assertEqual(
            steps['apply_reviewed_actions']['payload_template']['request_id'],
            self.controller.MCP_CUSTOMER_CARE_PLAN_REQUEST_ID_PLACEHOLDER,
        )
        reviewed_item = steps['apply_reviewed_actions']['payload_template']['items'][0]
        self.assertEqual(reviewed_item['triage_preset'], 'needs_staff_reply')
        serialized_steps = self._serialize_steps(item)
        self.assertNotIn('mcp-read-test-key', serialized_steps)
        self.assertNotIn('mcp-write-test-key', serialized_steps)

        conversation.invalidate_recordset()
        self.assertEqual(self.env['mail.activity'].search_count([]), before_activity_count)
        self.assertEqual(self.env['page.fm.conversation.ai.log'].search_count([]), before_log_count)
        self.assertEqual((conversation.require_processing, conversation.status_state, conversation.is_unread_fm), before_state)

    def test_conservative_medium_recommends_read_more_only(self):
        conversation = self._create_conversation('conservative', is_unread=True, status_state='new')

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[conversation.id],
            policy='conservative',
            include_messages=False,
        ))
        self.assertEqual(status_code, 200)
        item = payload['data']['items'][0]
        step_types = [step['type'] for step in item['recommended_steps']]
        self.assertEqual(item['status'], 'read_more')
        self.assertEqual(step_types, ['read_context'])

    def test_urgent_only_only_recommends_urgent(self):
        now = datetime.utcnow().replace(microsecond=0)
        urgent = self._create_conversation('urgent')
        medium = self._create_conversation('medium', is_unread=True, status_state='new')
        self._create_message(urgent, now - timedelta(minutes=130), sender='customer')
        urgent.sudo().write({'require_processing': False, 'is_unread_fm': False})
        medium.sudo().write({'require_processing': False, 'is_unread_fm': True, 'status_state': 'new'})

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[urgent.id, medium.id],
            policy='urgent_only',
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}
        self.assertEqual(item_map[urgent.id]['status'], 'action_recommended')
        self.assertIn('create_followup', self._steps_by_type(item_map[urgent.id]))
        self.assertEqual(item_map[medium.id]['skip_reason'], 'skipped_by_policy')

    def test_existing_activity_no_assignee_internal_and_done_rules(self):
        now = datetime.utcnow().replace(microsecond=0)
        with_activity = self._create_conversation('activity', status_state='new')
        no_assignee = self._create_conversation('no-assignee', owner=False, participants=False, status_state='new')
        internal = self._create_conversation('internal', is_unread=True, internal=True)
        done_conversation = self._create_conversation('done', is_unread=True, status_state='done')
        self._create_message(with_activity, now - timedelta(minutes=95), sender='customer')
        self._create_message(no_assignee, now - timedelta(minutes=95), sender='customer')
        self._create_message(internal, now - timedelta(minutes=95), sender='customer')
        self._create_message(done_conversation, now - timedelta(minutes=95), sender='customer')
        existing = self.env['mail.activity'].create({
            'activity_type_id': self.todo_activity_type.id,
            'res_model_id': self.conversation_model_id,
            'res_id': with_activity.id,
            'user_id': self.owner_user.id,
            'summary': 'Phan hoi khach dang cho',
            'note': 'Existing open follow-up',
            'date_deadline': '2026-05-02',
        })

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[with_activity.id, no_assignee.id, internal.id, done_conversation.id],
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}

        self.assertTrue(item_map[with_activity.id]['existing_open_activity'])
        self.assertEqual(item_map[with_activity.id]['existing_activity_id'], existing.id)
        self.assertNotIn('create_followup', self._steps_by_type(item_map[with_activity.id]))

        self.assertEqual(item_map[no_assignee.id]['status'], 'manual_review')
        self.assertEqual(item_map[no_assignee.id]['recommended_steps'][0]['type'], 'manual_assignment_review')

        self.assertEqual(item_map[internal.id]['status'], 'skipped')
        self.assertEqual(item_map[internal.id]['skip_reason'], 'internal_conversation')

        self.assertEqual(item_map[done_conversation.id]['status'], 'manual_review')
        self.assertNotIn('apply_reviewed_actions', self._steps_by_type(item_map[done_conversation.id]))
        self.assertNotIn('create_followup', self._steps_by_type(item_map[done_conversation.id]))

    def test_staff_replied_safe_presets_are_recommended(self):
        now = datetime.utcnow().replace(microsecond=0)
        unread_safe = self._create_conversation('waiting-customer', is_unread=True, status_state='recontact')
        processing_safe = self._create_conversation('clear-processing', require_processing=True, status_state='recontact')
        self._create_message(unread_safe, now - timedelta(minutes=50), sender='customer')
        self._create_message(unread_safe, now - timedelta(minutes=10), sender='staff')
        self._create_message(processing_safe, now - timedelta(minutes=60), sender='customer')
        self._create_message(processing_safe, now - timedelta(minutes=5), sender='staff')
        unread_safe.sudo().write({'require_processing': False, 'is_unread_fm': True, 'status_state': 'recontact'})
        processing_safe.sudo().write({'require_processing': True, 'is_unread_fm': False, 'status_state': 'recontact'})

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[unread_safe.id, processing_safe.id],
            default_deadline_date=None,
        ))
        self.assertEqual(status_code, 200)
        item_map = {item['conversation_id']: item for item in payload['data']['items']}

        unread_payload = self._steps_by_type(item_map[unread_safe.id])['apply_reviewed_actions']['payload_template']
        processing_payload = self._steps_by_type(item_map[processing_safe.id])['apply_reviewed_actions']['payload_template']
        self.assertIn(
            unread_payload['items'][0]['triage_preset'],
            ('waiting_customer', 'clear_processing_after_staff_reply'),
        )
        self.assertEqual(processing_payload['items'][0]['triage_preset'], 'clear_processing_after_staff_reply')

    def test_route_is_read_only_for_mail_activity_ai_logs_and_conversation_fields(self):
        now = datetime.utcnow().replace(microsecond=0)
        conversation = self._create_conversation('readonly', require_processing=True, is_unread=True, status_state='recontact')
        self._create_message(conversation, now - timedelta(minutes=75), sender='customer')
        before_activity_count = self.env['mail.activity'].search_count([])
        before_ai_log_count = self.env['page.fm.conversation.ai.log'].search_count([])
        before_values = (conversation.require_processing, conversation.status_state, conversation.is_unread_fm)

        payload, status_code = self._run_plan(self._base_payload(
            conversation_ids=[conversation.id],
            include_messages=True,
        ))
        self.assertEqual(status_code, 200)

        conversation.invalidate_recordset()
        self.assertEqual(self.env['mail.activity'].search_count([]), before_activity_count)
        self.assertEqual(self.env['page.fm.conversation.ai.log'].search_count([]), before_ai_log_count)
        self.assertEqual((conversation.require_processing, conversation.status_state, conversation.is_unread_fm), before_values)
