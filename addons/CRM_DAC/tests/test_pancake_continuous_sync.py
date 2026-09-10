import pytz
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.CRM_DAC.models import page_fm_conversation_models as conversation_models
from odoo.addons.CRM_DAC.models import page_fm_models
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('standard', 'at_install')
class TestPancakeContinuousSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Page = cls.env['page.fm.page']
        cls.Conversation = cls.env['page.fm.conversation']
        cls.Job = cls.env['pancake.message.sync.job']
        cls.Log = cls.env['pancake.message.sync.log']
        cls.Dashboard = cls.env['pancake.sync.dashboard']
        cls.MessageDashboard = cls.env['pancake.message.dashboard']
        cls.Message = cls.env['page.fm.message']
        cls.page = cls.Page.create({
            'name': 'Continuous Sync Test Page',
            'page_fm_id_str': 'continuous-sync-test-page',
            'sync_enabled': True,
            'active': True,
        })
        cls.conversation = cls.Conversation.create({
            'conversation_fm_id': 'continuous-sync-test-conversation',
            'page_fm_page_id': cls.page.id,
            'customer_fm_id': 'continuous-sync-test-customer',
        })
        cls.internal_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Pancake Internal User',
            'login': 'pancake_internal_user',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def setUp(self):
        super().setUp()
        self.Job.search([('state', 'in', ['running', 'stopping'])]).write({
            'state': 'cancelled',
            'phase': 'done',
            'finished_at': fields.Datetime.now(),
            'stop_requested': False,
            'runner_claim_token': False,
            'runner_claimed_at': False,
        })

    def test_toggle_continuous_sync_updates_all_internal_crons(self):
        dashboard = self.Dashboard._get_dashboard_record()
        quick = self.env.ref('CRM_DAC.cron_pancake_quick_sync')
        smart = self.env.ref('CRM_DAC.cron_pancake_smart_message_sync')
        deep = self.env.ref('CRM_DAC.cron_pancake_deep_sync_continuous')
        retired_full = self.env.ref('CRM_DAC.cron_pancake_full_sync')

        dashboard.write({'continuous_sync_active': False})
        dashboard._write_cron_configuration()
        self.assertFalse(quick.active)
        self.assertFalse(smart.active)
        self.assertFalse(deep.active)
        self.assertFalse(retired_full.active)

        dashboard.action_toggle_continuous_sync()
        self.assertTrue(quick.active)
        self.assertTrue(smart.active)
        self.assertTrue(deep.active)
        self.assertFalse(retired_full.active)

        dashboard.action_toggle_continuous_sync()
        self.assertFalse(quick.active)
        self.assertFalse(smart.active)
        self.assertFalse(deep.active)
        self.assertFalse(retired_full.active)

    def test_run_continuous_sync_now_is_blocked_when_manual_full_sync_is_running(self):
        dashboard = self.Dashboard._get_dashboard_record()
        self.Job.create({
            'name': 'Running Manual Full Sync',
            'state': 'running',
            'phase': 'page_scan',
            'started_at': fields.Datetime.now(),
        })

        with self.assertRaises(UserError):
            dashboard.action_run_continuous_sync_now()

    def test_run_continuous_sync_now_runs_candidate_refresh_and_same_day_only(self):
        dashboard = self.Dashboard._get_dashboard_record()

        with patch.object(type(self.Page), 'cron_quick_sync_conversations', return_value=True) as quick_mock, \
             patch.object(type(self.Conversation), 'cron_smart_message_sync', return_value=True) as same_day_mock, \
             patch.object(type(self.Conversation), 'cron_sync_conversations_batch_with_circuit_breaker', return_value=True) as nightly_mock:
            dashboard.action_run_continuous_sync_now()

        quick_mock.assert_called_once()
        same_day_mock.assert_called_once()
        nightly_mock.assert_not_called()

    def test_continuous_crons_skip_while_manual_full_sync_is_running(self):
        self.Job.create({
            'name': 'Running Manual Full Sync For Cron Guard',
            'state': 'running',
            'phase': 'message_sync',
            'started_at': fields.Datetime.now(),
        })

        with patch.object(type(self.Page), '_check_main_access_token', side_effect=AssertionError('quick sync should not run')):
            self.assertFalse(self.Page.cron_quick_sync_conversations())
        self.assertFalse(self.Conversation.cron_smart_message_sync())
        self.assertFalse(self.Conversation.cron_sync_conversations_batch_with_circuit_breaker())

    def test_save_configuration_maps_same_day_interval_and_nightly_schedule(self):
        dashboard = self.Dashboard._get_dashboard_record()
        quick = self.env.ref('CRM_DAC.cron_pancake_quick_sync')
        smart = self.env.ref('CRM_DAC.cron_pancake_smart_message_sync')
        deep = self.env.ref('CRM_DAC.cron_pancake_deep_sync_continuous')

        dashboard.write({
            'continuous_sync_active': True,
            'same_day_sync_interval_minutes': 45,
            'nightly_two_day_sync_time': '23:30',
            'continuous_sync_timezone': 'Asia/Ho_Chi_Minh',
            'sync_log_retention_days': 30,
            'sync_batch_size': 25,
            'smart_recent_days': 3,
            'deep_recent_days': 7,
            'circuit_breaker_pause_minutes': 15,
        })
        dashboard.action_save_configuration()

        self.assertEqual(quick.interval_number, 45)
        self.assertEqual(quick.interval_type, 'minutes')
        self.assertEqual(smart.interval_number, 45)
        self.assertEqual(smart.interval_type, 'minutes')
        self.assertEqual(deep.interval_number, 1)
        self.assertEqual(deep.interval_type, 'days')

        nextcall_local = pytz.UTC.localize(fields.Datetime.to_datetime(deep.nextcall)).astimezone(
            pytz.timezone('Asia/Ho_Chi_Minh')
        )
        self.assertEqual(nextcall_local.hour, 23)
        self.assertEqual(nextcall_local.minute, 30)

    def test_fetch_message_batch_stops_at_window_floor(self):
        response_payload = {
            'messages': [
                {'id': 'msg-old', 'inserted_at': '2026-05-03T23:50:00Z', 'message': 'old'},
                {'id': 'msg-mid', 'inserted_at': '2026-05-04T10:00:00Z', 'message': 'mid'},
                {'id': 'msg-new', 'inserted_at': '2026-05-04T12:00:00Z', 'message': 'new'},
            ]
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return response_payload

            def raise_for_status(self):
                return None

        self.conversation.last_message_id = False
        window_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=pytz.UTC)

        with patch.object(conversation_models.requests, 'get', return_value=FakeResponse()):
            should_continue, batch = self.conversation._fetch_message_batch(
                'page-token',
                0,
                window_start=window_start,
            )

        self.assertFalse(should_continue)
        self.assertEqual([msg['id'] for msg in batch], ['msg-mid', 'msg-new'])

    def test_fetch_message_batch_stops_at_saved_frontier_with_oldest_first_api_order(self):
        response_payload = {
            'messages': [
                {'id': 'msg-old', 'inserted_at': '2026-05-03T23:50:00Z', 'message': 'old'},
                {'id': 'msg-frontier', 'inserted_at': '2026-05-04T10:00:00Z', 'message': 'frontier'},
                {'id': 'msg-new', 'inserted_at': '2026-05-04T12:00:00Z', 'message': 'new'},
            ]
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return response_payload

            def raise_for_status(self):
                return None

        self.conversation.last_message_id = 'msg-frontier'

        with patch.object(conversation_models.requests, 'get', return_value=FakeResponse()):
            should_continue, batch = self.conversation._fetch_message_batch(
                'page-token',
                0,
            )

        self.assertFalse(should_continue)
        self.assertEqual([msg['id'] for msg in batch], ['msg-new'])

    def test_fetch_all_messages_orders_newest_first_and_updates_frontier(self):
        batch_calls = [
            (
                True,
                [
                    {'id': 'msg-old', 'inserted_at': '2026-05-04T10:00:00Z', 'message': 'old'},
                    {'id': 'msg-new', 'inserted_at': '2026-05-05T10:00:00Z', 'message': 'new'},
                ],
            ),
            (
                False,
                [
                    {'id': 'msg-newest', 'inserted_at': '2026-05-06T10:00:00Z', 'message': 'newest'},
                ],
            ),
        ]

        with patch.object(type(self.conversation), '_fetch_message_batch', side_effect=batch_calls):
            messages = self.conversation._fetch_all_messages('page-token')

        self.assertEqual([msg['id'] for msg in messages], ['msg-newest', 'msg-new', 'msg-old'])
        self.assertEqual(self.conversation.last_message_id, 'msg-newest')

    def test_fetch_conversation_candidates_continues_pagination_without_hardcoded_page_size(self):
        payloads = [
            {
                'success': True,
                'conversations': [
                    {
                        'id': 'conv-page-1-a',
                        'customer_id': 'cust-a',
                        'from': {'name': 'Cust A', 'id': 'fb_a'},
                        'snippet': 'hello',
                        'updated_at': '2026-05-04T10:00:00Z',
                        'seen': False,
                        'page_id': self.page.page_fm_id_str,
                    },
                    {
                        'id': 'conv-page-1-b',
                        'customer_id': 'cust-b',
                        'from': {'name': 'Cust B', 'id': 'fb_b'},
                        'snippet': 'hi',
                        'updated_at': '2026-05-04T10:05:00Z',
                        'seen': True,
                        'page_id': self.page.page_fm_id_str,
                    },
                ],
            },
            {
                'success': True,
                'conversations': [
                    {
                        'id': 'conv-page-2-c',
                        'customer_id': 'cust-c',
                        'from': {'name': 'Cust C', 'id': 'fb_c'},
                        'snippet': 'follow up',
                        'updated_at': '2026-05-04T10:10:00Z',
                        'seen': False,
                        'page_id': self.page.page_fm_id_str,
                    },
                ],
            },
            {
                'success': True,
                'conversations': [],
            },
        ]

        class FakeResponse:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        request_calls = []

        def fake_get(_url, headers=None, params=None, timeout=None):
            request_calls.append(dict(params or {}))
            return FakeResponse(payloads[len(request_calls) - 1])

        with patch.object(type(self.page), '_generate_page_specific_access_token', return_value='page-token'), \
             patch.object(page_fm_models.requests, 'get', side_effect=fake_get):
            conversations = self.page._fetch_conversations_for_page_record('main-token')

        self.assertEqual(len(conversations), 3)
        self.assertEqual(request_calls[1]['last_conversation_id'], 'conv-page-1-b')

    def test_action_sync_messages_raises_when_message_fetch_fails(self):
        self.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', 'main-token')

        with patch.object(type(self.page), '_generate_page_specific_access_token', return_value='page-token'), \
             patch.object(type(self.conversation), '_fetch_all_messages', side_effect=RuntimeError('api timeout')):
            with self.assertRaisesRegex(RuntimeError, 'api timeout'):
                self.conversation.action_sync_messages(return_stats=True)

        self.conversation.invalidate_recordset(['last_message_sync_fm'])
        self.assertFalse(self.conversation.last_message_sync_fm)

    def test_windowed_candidates_prioritize_conversations_not_recently_synced(self):
        synced_conversation = self.Conversation.create({
            'conversation_fm_id': 'continuous-synced-first',
            'page_fm_page_id': self.page.id,
            'customer_fm_id': 'cust-synced',
            'updated_at_fm': fields.Datetime.to_datetime('2026-05-05 05:00:00'),
            'last_message_sync_fm': fields.Datetime.to_datetime('2026-05-05 05:10:00'),
        })
        stale_conversation = self.Conversation.create({
            'conversation_fm_id': 'continuous-stale-second',
            'page_fm_page_id': self.page.id,
            'customer_fm_id': 'cust-stale',
            'updated_at_fm': fields.Datetime.to_datetime('2026-05-05 04:59:00'),
            'last_message_sync_fm': False,
        })

        with patch.object(type(self.Conversation), '_compute_sync_window_stats', return_value={
            'window_start_str': '2026-05-05 00:00:00',
            'window_end_str': '2026-05-05 23:59:59',
            'window_start': datetime(2026, 5, 5, 0, 0, 0, tzinfo=pytz.UTC),
            'window_end': datetime(2026, 5, 5, 23, 59, 59, tzinfo=pytz.UTC),
            'window_start_epoch': 0,
            'window_end_epoch': 0,
        }):
            conversations, _stats = self.Conversation._get_windowed_conversation_candidates('same_day', limit=1)

        self.assertEqual(conversations.ids, stale_conversation.ids)
        self.assertNotEqual(conversations.ids, synced_conversation.ids)

    def test_dashboard_exposes_sync_log_action_and_retention_setting(self):
        dashboard = self.Dashboard._get_dashboard_record()
        dashboard.write({
            'continuous_sync_active': True,
            'same_day_sync_interval_minutes': 30,
            'nightly_two_day_sync_time': '23:30',
            'continuous_sync_timezone': 'Asia/Ho_Chi_Minh',
            'sync_log_retention_days': 21,
            'sync_batch_size': 50,
            'smart_recent_days': 3,
            'deep_recent_days': 7,
            'circuit_breaker_pause_minutes': 15,
            'quick_sync_interval_number': 30,
            'smart_sync_interval_number': 30,
            'deep_sync_interval_number': 1,
        })
        dashboard.action_save_configuration()

        action = dashboard.action_open_sync_logs()

        self.assertEqual(action['res_model'], 'pancake.message.sync.log')
        self.assertEqual(action['context'], {})
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('pancake.message_sync_log_retention_days'),
            '21',
        )

    def test_log_cleanup_uses_configured_retention_days(self):
        self.env['ir.config_parameter'].sudo().set_param('pancake.message_sync_log_retention_days', '5')
        recent_log = self.Log.create({
            'source_type': 'continuous',
            'continuous_layer': 'same_day',
            'level': 'error',
            'message': 'Recent continuous error',
            'logged_at': fields.Datetime.now(),
        })
        old_log = self.Log.create({
            'source_type': 'continuous',
            'continuous_layer': 'same_day',
            'level': 'error',
            'message': 'Old continuous error',
            'logged_at': fields.Datetime.now() - timedelta(days=6),
        })

        deleted_count = self.Log.cron_cleanup_old_logs()

        self.assertGreaterEqual(deleted_count, 1)
        self.assertTrue(recent_log.exists())
        self.assertFalse(old_log.exists())

    def test_message_dashboard_opens_for_internal_user_and_selects_conversation(self):
        action = self.MessageDashboard.with_user(self.internal_user).action_open_dashboard(conversation_id=self.conversation.id)
        dashboard = self.MessageDashboard.with_user(self.internal_user).browse(action['res_id'])

        self.assertEqual(action['res_model'], 'pancake.message.dashboard')
        self.assertEqual(dashboard.selected_conversation_id, self.conversation)
        self.assertIn(self.conversation, dashboard.conversation_preview_ids)
        self.assertFalse(dashboard.access_token)

    def test_internal_user_can_see_all_conversations(self):
        another_conversation = self.Conversation.create({
            'conversation_fm_id': 'continuous-other-conversation',
            'page_fm_page_id': self.page.id,
            'customer_fm_id': 'continuous-other-customer',
        })

        visible_ids = self.Conversation.with_user(self.internal_user).search([]).ids

        self.assertIn(self.conversation.id, visible_ids)
        self.assertIn(another_conversation.id, visible_ids)

    def test_manual_window_sync_creates_summary_log(self):
        self.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', 'main-token')
        self.conversation.write({'updated_at_fm': fields.Datetime.now()})

        with patch.object(type(self.Conversation), '_refresh_windowed_conversation_candidates', return_value={
            'has_token': True,
            'page_count': 1,
            'conversation_count': 1,
            'error_count': 0,
        }), patch.object(type(self.Conversation), '_get_windowed_conversation_candidates', return_value=(
            self.conversation,
            self.Conversation._compute_recent_hours_window_stats(72),
        )), patch.object(type(self.conversation), 'action_sync_messages', return_value={
            'status': 'ok',
            'created_messages': 2,
            'existing_messages': 1,
            'fetched_messages': 3,
        }):
            result = self.Conversation.with_context(skip_cursor_commit=True).action_run_recent_72h_manual_window_sync()

        summary_log = self.Log.search([
            ('source_type', '=', 'manual_window'),
            ('continuous_layer', '=', 'manual_recent_72h'),
            ('event_code', '=', 'manual_window_summary'),
        ], order='id desc', limit=1)

        self.assertEqual(result['messages_created'], 2)
        self.assertEqual(result['messages_existing'], 1)
        self.assertEqual(result['messages_fetched'], 3)
        self.assertTrue(summary_log)

    def test_windowed_sync_retries_transient_conversation_error(self):
        self.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', 'main-token')
        self.conversation.write({'updated_at_fm': fields.Datetime.now()})
        sync_stats = self.Conversation._compute_recent_hours_window_stats(72)
        transient_error = RuntimeError('could not serialize access due to concurrent update')

        with patch.object(type(self.Conversation), '_refresh_windowed_conversation_candidates', return_value={
            'has_token': True,
            'page_count': 1,
            'conversation_count': 1,
            'error_count': 0,
        }), patch.object(type(self.Conversation), '_get_windowed_conversation_candidates', return_value=(
            self.conversation,
            sync_stats,
        )), patch.object(type(self.conversation), 'action_sync_messages', side_effect=[
            transient_error,
            {
                'status': 'ok',
                'created_messages': 1,
                'existing_messages': 0,
                'fetched_messages': 1,
            },
        ]) as sync_mock, patch.object(conversation_models.time, 'sleep', return_value=None):
            result = self.Conversation.with_context(skip_cursor_commit=True)._run_windowed_message_sync(
                'manual_recent_72h',
                sync_stats=sync_stats,
                source_type='manual_window',
                sync_origin='manual_window',
                record_layer_stats=False,
            )

        self.assertEqual(sync_mock.call_count, 2)
        self.assertEqual(result['checked_count'], 1)
        self.assertEqual(result['messages_created'], 1)
        self.assertEqual(result['error_count'], 0)

    def test_dashboard_daily_metrics_count_successful_syncs(self):
        now_value = fields.Datetime.now()
        self.conversation.write({
            'last_successful_message_sync_at': now_value,
            'last_message_sync_origin': 'continuous',
        })
        self.Message.create({
            'message_fm_id': 'dashboard-metric-message',
            'conversation_id': self.conversation.id,
            'inserted_at_fm': now_value,
            'raw_json_message': '{}',
            'sync_origin': 'continuous',
        })

        values = self.Dashboard._get_log_values()

        self.assertGreaterEqual(values['conversations_synced_today'], 1)
        self.assertGreaterEqual(values['messages_synced_today'], 1)
        self.assertTrue(values['latest_successful_sync_at'])
