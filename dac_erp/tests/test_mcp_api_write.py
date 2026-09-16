from unittest import SkipTest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpApiWrite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPReadController()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        cls.has_pancake_models = 'page.fm.page' in cls.env.registry.models and 'page.fm.conversation' in cls.env.registry.models
        if not cls.has_pancake_models:
            raise SkipTest("CRM_DAC is not loaded; MCP write tests require Pancake models.")

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Write Owner',
            'login': 'mcp_write_owner@example.com',
            'email': 'mcp_write_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MCP Write Participant',
            'login': 'mcp_write_participant@example.com',
            'email': 'mcp_write_participant@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'MCP Write Page',
            'page_fm_id_str': 'mcp-write-page-001',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'MCP Write Partner'})

    def setUp(self):
        super().setUp()
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'mcp-write-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'MCP Write Customer',
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id, self.participant_user.id])],
            'status_state': 'recontact',
            'require_processing': True,
            'is_unread_fm': True,
        })

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _base_payload(self, request_id, **extra):
        payload = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
        }
        payload.update(extra)
        return payload

    def _assert_log(self, request_id, action_type):
        log = self.env['page.fm.conversation.ai.log'].search([('request_id', '=', request_id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.action_type, action_type)
        return log

    def test_missing_key_and_invalid_key_and_read_key_cannot_write(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers={},
            payload=self._base_payload('missing-001', summary_text='Need follow up'),
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('wrong-key'),
            payload=self._base_payload('invalid-001', summary_text='Need follow up'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._base_payload('readonly-001', summary_text='Need follow up'),
        )
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

    def test_summary_requires_request_id_and_agent_name(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'agent_name': 'OpenClaw', 'summary_text': 'Need follow up'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload={'request_id': 'missing-agent-001', 'summary_text': 'Need follow up'},
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_conversation_not_found_returns_404(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            99999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('summary-404', summary_text='Need follow up'),
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_write_key_can_update_summary_and_create_audit_log(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'summary-001',
                summary_text='Customer asked for a callback',
                reason='follow_up',
                confidence=0.9,
            ),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.suggestion_note, 'Customer asked for a callback')
        log = self._assert_log('summary-001', 'summary_upsert')
        self.assertEqual(payload['data']['log_id'], log.id)

    def test_idempotency_replay_and_conflict(self):
        base_payload = self._base_payload('summary-002', summary_text='Stable summary')
        first_payload, first_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=base_payload,
        )
        self.assertEqual(first_status, 200)

        replay_payload, replay_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=base_payload,
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replay_payload['data']['idempotent_replay'])
        self.assertEqual(replay_payload['data']['log_id'], first_payload['data']['log_id'])

        conflict_payload, conflict_status = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_summary,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('summary-002', summary_text='Different summary'),
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload['error']['code'], 'conflict')

    def test_ai_note_posts_internal_message_without_overwriting_summary(self):
        self.conversation.write({'suggestion_note': 'Existing summary'})
        message_count_before = len(self.conversation.message_ids)
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_ai_note,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('note-001', note_text='Internal risk note', note_type='internal_note'),
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['data']['message_posted'])
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.suggestion_note, 'Existing summary')
        self.assertGreater(len(self.conversation.message_ids), message_count_before)
        self._assert_log('note-001', 'note_create')

    def test_activity_falls_back_to_owner_and_logs(self):
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_activity,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('activity-001', summary='Call customer', note='Need callback'),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['assigned_user_id'], self.owner_user.id)
        activity = self.env['mail.activity'].browse(payload['data']['activity_id'])
        self.assertTrue(activity.exists())
        self.assertEqual(activity.user_id.id, self.owner_user.id)
        self._assert_log('activity-001', 'activity_create')

    def test_activity_requires_valid_user_when_no_owner(self):
        self.conversation.write({'owner_id': False})
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_activity,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload('activity-002', summary='Call customer'),
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_triage_only_updates_allowed_fields(self):
        owner_id_before = self.conversation.owner_id.id
        participant_ids_before = self.conversation.participant_user_ids.ids
        partner_id_before = self.conversation.partner_id.id
        payload, status_code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_conversation_triage,
            self.conversation.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._base_payload(
                'triage-001',
                status_state='done',
                mark_read=True,
            ),
        )
        self.assertEqual(status_code, 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.status_state, 'done')
        self.assertFalse(self.conversation.require_processing)
        self.assertFalse(self.conversation.is_unread_fm)
        self.assertEqual(self.conversation.owner_id.id, owner_id_before)
        self.assertEqual(self.conversation.participant_user_ids.ids, participant_ids_before)
        self.assertEqual(self.conversation.partner_id.id, partner_id_before)
        self._assert_log('triage-001', 'triage_update')
