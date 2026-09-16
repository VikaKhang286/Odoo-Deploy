from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.api_v2_controller import DataExportV2Controller
from odoo.addons.dac_erp.controllers.api_v3_conversation_controller import ConversationAIV3Controller


@tagged('standard', 'at_install')
class TestOpenClawMessageApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.v2 = DataExportV2Controller()
        cls.v3 = ConversationAIV3Controller()
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.api_v3_ai_write_key', 'api-v3-ai-test-key')

        cls.group_user = cls.env.ref('base.group_user')
        cls.owner_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OpenClaw Owner',
            'login': 'openclaw_owner@example.com',
            'email': 'openclaw_owner@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.staff_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OpenClaw Staff',
            'login': 'openclaw_staff@example.com',
            'email': 'openclaw_staff@example.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })
        cls.page = cls.env['page.fm.page'].create({
            'name': 'OpenClaw Page',
            'page_fm_id_str': 'openclaw-page-001',
            'active': True,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'OpenClaw Customer'})
        cls.tag_consulting = cls.env['page.fm.tag'].create({
            'name': 'Consulting',
            'tag_fm_id': '301',
            'page_id': cls.page.id,
            'odoo_tag_code': 'CONSULTING',
        })
        cls.tag_vip = cls.env['page.fm.tag'].create({
            'name': 'VIP',
            'tag_fm_id': '302',
            'page_id': cls.page.id,
            'odoo_tag_code': 'VIP',
        })
        cls.tag_done = cls.env['page.fm.tag'].create({
            'name': 'Done',
            'tag_fm_id': '303',
            'page_id': cls.page.id,
            'odoo_tag_code': 'DONE',
        })

    def setUp(self):
        super().setUp()
        now = datetime.utcnow().replace(microsecond=0)
        self.conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'openclaw-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'OpenClaw Customer',
            'owner_id': self.owner_user.id,
            'participant_user_ids': [(6, 0, [self.owner_user.id])],
            'platform_fm': 'facebook',
            'conv_page_fm_id': self.page.page_fm_id_str,
            'pancake_tag_ids': [(6, 0, [self.tag_consulting.id, self.tag_vip.id])],
        })
        self.staff_message = self.env['page.fm.message'].create({
            'message_fm_id': 'openclaw-staff-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(hours=2),
            'staff': self.staff_user.id,
            'staff_name_fm': self.staff_user.name,
            'content_html': '<p>Xin chao</p>',
        })
        self.customer_message = self.env['page.fm.message'].create({
            'message_fm_id': 'openclaw-customer-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(hours=1),
            'sender_name_fm': 'OpenClaw Customer',
            'content_html': '<p>Can cap nhat tien do</p>',
        })
        self.image_message = self.env['page.fm.message'].create({
            'message_fm_id': 'openclaw-image-%s' % self._testMethodName,
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now - timedelta(hours=3),
            'content_html': '<p>Image</p>',
            'type_content': 'image',
            'url_content': 'https://example.com/test.png',
        })

    def _payload(self, request_id, **extra):
        payload = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
        }
        payload.update(extra)
        return payload

    def test_v2_extended_filters_runtime(self):
        conversation_result = self.v2._get_v2_conversations_data(
            env=self.env,
            platform='facebook',
            tag_code='CONSULTING,VIP',
            tag_mode='all',
        )
        self.assertEqual(conversation_result['count'], 1)
        self.assertEqual(conversation_result['items'][0]['id'], self.conversation.id)

        message_result = self.v2._get_v2_messages_data(
            env=self.env,
            page_id=self.page.id,
            sender_role='customer',
            tag_code='VIP',
            platform='facebook',
        )
        self.assertEqual(message_result['count'], 1)
        self.assertEqual(message_result['items'][0]['id'], self.customer_message.id)

        image_result = self.v2._get_v2_messages_data(
            env=self.env,
            type_content='image',
            page_fm_id_str=self.page.page_fm_id_str,
        )
        self.assertEqual(image_result['count'], 1)
        self.assertEqual(image_result['items'][0]['id'], self.image_message.id)

    def test_v3_summary_and_triage_runtime(self):
        summary_result = self.v3._run_v3_action(
            action_type='summary_upsert',
            conversation_id=self.conversation.id,
            payload=self._payload('runtime-summary', summary_text='Khach dang cho phan hoi', confidence=0.9),
            executor=self.v3._update_conversation_ai_summary,
            replay_message='Replayed AI summary request',
            env=self.env,
        )
        self.assertEqual(summary_result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.suggestion_note, 'Khach dang cho phan hoi')

        triage_result = self.v3._run_v3_action(
            action_type='triage_update',
            conversation_id=self.conversation.id,
            payload=self._payload('runtime-triage', status_state='done', mark_read=True),
            executor=self.v3._update_conversation_triage,
            replay_message='Replayed AI triage request',
            env=self.env,
        )
        self.assertEqual(triage_result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.status_state, 'done')
        self.assertFalse(self.conversation.require_processing)
        self.assertFalse(self.conversation.is_unread_fm)

    def test_v3_activity_and_tag_replace_runtime(self):
        activity_result = self.v3._run_v3_action(
            action_type='activity_create',
            conversation_id=self.conversation.id,
            payload=self._payload('runtime-activity', summary='Call customer', note='Need update'),
            executor=self.v3._create_conversation_followup_activity,
            replay_message='Replayed AI activity request',
            env=self.env,
        )
        self.assertEqual(activity_result['status_code'], 200)
        activity = self.env['mail.activity'].browse(activity_result['data']['activity_id'])
        self.assertTrue(activity.exists())

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
            tag_result = self.v3._run_v3_action(
                action_type='tag_replace',
                conversation_id=self.conversation.id,
                payload=self._payload('runtime-tags', tag_codes=['DONE']),
                executor=self.v3._replace_conversation_tags,
                replay_message='Replayed AI tag request',
                env=self.env,
            )
        self.assertEqual(tag_result['status_code'], 200)
        self.conversation.invalidate_recordset()
        self.assertEqual(self.conversation.pancake_tag_ids.mapped('odoo_tag_code'), ['DONE'])
