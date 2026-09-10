from unittest import SkipTest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.api_v3_conversation_controller import ConversationAIV3Controller


@tagged('standard', 'at_install')
class TestApiV3ConversationWrite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = ConversationAIV3Controller()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.api_v3_ai_write_key', 'api-v3-ai-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; AI write tests require Pancake models.")
        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'AI Owner',
            'login': 'ai_owner@example.com',
            'email': 'ai_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'AI Write Page',
            'page_fm_id_str': 'ai-write-page-001',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'AI Write Partner'})
        cls.tag_consulting = cls.env['page.fm.tag'].create({
            'name': 'Consulting',
            'tag_fm_id': '201',
            'page_id': cls.page.id,
            'odoo_tag_code': 'CONSULTING',
        })
        cls.tag_vip = cls.env['page.fm.tag'].create({
            'name': 'VIP',
            'tag_fm_id': '202',
            'page_id': cls.page.id,
            'odoo_tag_code': 'VIP',
        })
        cls.tag_done = cls.env['page.fm.tag'].create({
            'name': 'Done',
            'tag_fm_id': '203',
            'page_id': cls.page.id,
            'odoo_tag_code': 'DONE',
        })

    def setUp(self):
        super().setUp()
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'ai-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'AI Customer',
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id])],
            'conv_page_fm_id': self.page.page_fm_id_str,
        })

    def _payload(self, request_id, **extra):
        payload = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
        }
        payload.update(extra)
        return payload

    def _assert_replay(self, result):
        self.assertEqual(result['status_code'], 200)
        self.assertTrue(result['data']['idempotent_replay'])

    def test_v3_write_api_key_validation(self):
        self.assertTrue(self.controller._ensure_v3_write_api_key(env=self.env, provided_key='api-v3-ai-test-key'))
        with self.assertRaises(PermissionError):
            self.controller._ensure_v3_write_api_key(env=self.env, provided_key='wrong-key')
        with self.assertRaises(PermissionError):
            self.controller._ensure_v3_write_api_key(env=self.env, provided_key=None, headers={})

    def test_ai_summary_write_and_replay(self):
        payload = self._payload('summary-001', summary_text='Need follow up', reason='customer_follow_up', confidence=0.8)
        result = self.controller._run_v3_action(
            action_type='summary_upsert',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._update_conversation_ai_summary,
            replay_message='Replayed AI summary request',
            env=self.env,
        )
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.suggestion_note, 'Need follow up')
        self.assertTrue(self.conversation.last_suggestion_at)
        self.assertEqual(result['status_code'], 200)
        log = self.env['page.fm.conversation.ai.log'].search([('request_id', '=', 'summary-001')], limit=1)
        self.assertTrue(log)
        replay = self.controller._run_v3_action(
            action_type='summary_upsert',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._update_conversation_ai_summary,
            replay_message='Replayed AI summary request',
            env=self.env,
        )
        self._assert_replay(replay)

    def test_ai_note_creates_audit_log_only(self):
        payload = self._payload('note-001', note_text='Internal risk note', note_type='internal_note')
        result = self.controller._run_v3_action(
            action_type='note_create',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._create_conversation_ai_note,
            replay_message='Replayed AI note request',
            env=self.env,
        )
        self.assertEqual(result['status_code'], 200)
        self.assertFalse(self.conversation.suggestion_note)
        log = self.env['page.fm.conversation.ai.log'].search([('request_id', '=', 'note-001')], limit=1)
        self.assertEqual(log.action_type, 'note_create')

    def test_activity_create_falls_back_to_owner(self):
        payload = self._payload('activity-001', summary='Call customer', note='Customer waiting')
        result = self.controller._run_v3_action(
            action_type='activity_create',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._create_conversation_followup_activity,
            replay_message='Replayed AI activity request',
            env=self.env,
        )
        self.assertEqual(result['status_code'], 200)
        activity = self.env['mail.activity'].browse(result['data']['activity_id'])
        self.assertTrue(activity.exists())
        self.assertEqual(activity.user_id.id, self.owner_user.id)
        replay = self.controller._run_v3_action(
            action_type='activity_create',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._create_conversation_followup_activity,
            replay_message='Replayed AI activity request',
            env=self.env,
        )
        self._assert_replay(replay)

    def test_activity_create_requires_user_when_no_owner(self):
        self.conversation.write({'owner_id': False})
        payload = self._payload('activity-002', summary='Call customer')
        with self.assertRaises(ValueError):
            self.controller._run_v3_action(
                action_type='activity_create',
                conversation_id=self.conversation.id,
                payload=payload,
                executor=self.controller._create_conversation_followup_activity,
                replay_message='Replayed AI activity request',
                env=self.env,
            )

    def test_triage_updates_fields_and_done_forces_processing_false(self):
        self.conversation.write({'is_unread_fm': True, 'require_processing': True, 'status_state': 'recontact'})
        payload = self._payload('triage-001', status_state='done', mark_read=True)
        result = self.controller._run_v3_action(
            action_type='triage_update',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._update_conversation_triage,
            replay_message='Replayed AI triage request',
            env=self.env,
        )
        self.assertEqual(result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.status_state, 'done')
        self.assertFalse(self.conversation.require_processing)
        self.assertFalse(self.conversation.is_unread_fm)

    def test_triage_rejects_unknown_request_field(self):
        payload = self._payload('triage-002', bad_field=True)
        with self.assertRaises(ValueError):
            self.controller._normalize_v3_request_payload('triage_update', payload)

    def test_triage_duplicate_request_id_conflict(self):
        payload = self._payload('triage-003', status_state='waiting')
        self.controller._run_v3_action(
            action_type='triage_update',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._update_conversation_triage,
            replay_message='Replayed AI triage request',
            env=self.env,
        )
        conflict_payload = self._payload('triage-003', status_state='recontact')
        with self.assertRaises(ValueError):
            self.controller._run_v3_action(
                action_type='triage_update',
                conversation_id=self.conversation.id,
                payload=conflict_payload,
                executor=self.controller._update_conversation_triage,
                replay_message='Replayed AI triage request',
                env=self.env,
            )

    def test_tag_replace_success_and_replay(self):
        payload = self._payload('tags-001', tag_codes=['CONSULTING', 'VIP'], reason='tagging')
        with patch.object(type(self.conversation), '_build_ai_tag_sync_http_context', return_value={'api_url': 'http://example.com', 'headers': {}, 'params': {}}), \
             patch.object(type(self.conversation), '_sync_single_pancake_tag_action', side_effect=lambda http_context, tag, action: {
                 'action': action,
                 'tag_code': tag.odoo_tag_code,
                 'tag_name': tag.name,
                 'tag_fm_id': tag.tag_fm_id,
                 'ok': True,
                 'status_code': 200,
                 'response_text': 'ok',
             }):
            result = self.controller._run_v3_action(
                action_type='tag_replace',
                conversation_id=self.conversation.id,
                payload=payload,
                executor=self.controller._replace_conversation_tags,
                replay_message='Replayed AI tag request',
                env=self.env,
            )
        self.assertEqual(result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(set(self.conversation.pancake_tag_ids.mapped('odoo_tag_code')), {'CONSULTING', 'VIP'})
        replay = self.controller._run_v3_action(
            action_type='tag_replace',
            conversation_id=self.conversation.id,
            payload=payload,
            executor=self.controller._replace_conversation_tags,
            replay_message='Replayed AI tag request',
            env=self.env,
        )
        self._assert_replay(replay)

    def test_tag_replace_clear_and_validation(self):
        self.conversation.write({'pancake_tag_ids': [(6, 0, [self.tag_consulting.id, self.tag_vip.id])]})
        with patch.object(type(self.conversation), '_build_ai_tag_sync_http_context', return_value={'api_url': 'http://example.com', 'headers': {}, 'params': {}}), \
             patch.object(type(self.conversation), '_sync_single_pancake_tag_action', side_effect=lambda http_context, tag, action: {
                 'action': action,
                 'tag_code': tag.odoo_tag_code,
                 'tag_name': tag.name,
                 'tag_fm_id': tag.tag_fm_id,
                 'ok': True,
                 'status_code': 200,
                 'response_text': 'ok',
             }):
            result = self.controller._run_v3_action(
                action_type='tag_replace',
                conversation_id=self.conversation.id,
                payload=self._payload('tags-002', tag_codes=[]),
                executor=self.controller._replace_conversation_tags,
                replay_message='Replayed AI tag request',
                env=self.env,
            )
        self.assertEqual(result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertFalse(self.conversation.pancake_tag_ids)

        with self.assertRaises(ValueError):
            self.controller._run_v3_action(
                action_type='tag_replace',
                conversation_id=self.conversation.id,
                payload=self._payload('tags-003', tag_codes=['UNKNOWN']),
                executor=self.controller._replace_conversation_tags,
                replay_message='Replayed AI tag request',
                env=self.env,
            )

    def test_tag_replace_failure_does_not_change_local_tags(self):
        self.conversation.write({'pancake_tag_ids': [(6, 0, [self.tag_consulting.id])]})
        payload = self._payload('tags-004', tag_codes=['DONE'])
        with patch.object(type(self.conversation), '_build_ai_tag_sync_http_context', return_value={'api_url': 'http://example.com', 'headers': {}, 'params': {}}), \
             patch.object(type(self.conversation), '_sync_single_pancake_tag_action', return_value={
                 'action': 'add',
                 'tag_code': 'DONE',
                 'tag_name': 'Done',
                 'tag_fm_id': '203',
                 'ok': False,
                 'status_code': 500,
                 'response_text': 'failed',
             }):
            result = self.controller._run_v3_action(
                action_type='tag_replace',
                conversation_id=self.conversation.id,
                payload=payload,
                executor=self.controller._replace_conversation_tags,
                replay_message='Replayed AI tag request',
                env=self.env,
            )
        self.assertEqual(result['status_code'], 500)
        self.conversation.invalidate_recordset()
        self.assertEqual(set(self.conversation.pancake_tag_ids.mapped('odoo_tag_code')), {'CONSULTING'})
        log = self.env['page.fm.conversation.ai.log'].search([('request_id', '=', 'tags-004')], limit=1)
        self.assertEqual(log.status, 'failed')

    def test_request_validation_guards(self):
        with self.assertRaises(ValueError):
            self.controller._normalize_v3_request_payload(
                'summary_upsert',
                self._payload('invalid-001', summary_text='Text', confidence=2),
            )
        with self.assertRaises(ValueError):
            self.controller._normalize_v3_request_payload(
                'activity_create',
                self._payload('invalid-002', summary='Call', deadline_date='2026/04/29'),
            )
