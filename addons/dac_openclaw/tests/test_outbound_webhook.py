"""Test outbound webhook service: enqueue, HMAC signing, retry, giveup."""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestOutboundWebhook(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.WebhookLog = cls.env['dac_openclaw.outbound.webhook.log']

    def setUp(self):
        super().setUp()
        # Reset config for each test
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_openclaw.webhook_url', 'https://openclaw.example.com/events')
        icp.set_param('dac_openclaw.webhook_secret', 'test-secret')
        icp.set_param('dac_openclaw.webhook_enabled', 'true')
        icp.set_param('dac_openclaw.webhook_max_retry', '3')

    def test_enqueue_creates_pending_log_with_signature(self):
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created',
            data={'order_id': 42, 'amount': 1000},
        )
        self.assertEqual(log.state, 'pending')
        self.assertEqual(log.event_type, 'order.created')
        self.assertTrue(log.event_id)
        self.assertTrue(log.signature)
        # Verify signature manually
        expected = hmac.new(b'test-secret', log.payload_json.encode('utf-8'),
                            hashlib.sha256).hexdigest()
        self.assertEqual(log.signature, expected)
        # Payload chứa event_id và event
        payload = json.loads(log.payload_json)
        self.assertEqual(payload['event'], 'order.created')
        self.assertEqual(payload['data']['order_id'], 42)

    def test_enqueue_disabled_marks_skipped(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_openclaw.webhook_enabled', 'false')
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={},
        )
        self.assertEqual(log.state, 'skipped')

    def test_event_id_uniqueness(self):
        log1 = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={}, event_id='fixed-id-001')
        self.assertEqual(log1.event_id, 'fixed-id-001')
        # Tạo lại với cùng event_id → integrity error
        from psycopg2 import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.WebhookLog.sudo().enqueue_event(
                    event_type='order.created', data={}, event_id='fixed-id-001')

    def test_send_one_success(self):
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={'order_id': 1},
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok":true}'
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post',
                   return_value=mock_response) as mock_post:
            result = log._send_one()
        self.assertTrue(result)
        self.assertEqual(log.state, 'sent')
        self.assertEqual(log.http_status_code, 200)
        # Verify call args
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(mock_post.call_args.args[0], 'https://openclaw.example.com/events')
        headers = call_kwargs['headers']
        self.assertTrue(headers['X-OpenClaw-Signature'].startswith('sha256='))
        self.assertEqual(headers['X-OpenClaw-Event-Type'], 'order.created')

    def test_send_one_http_error_schedules_retry(self):
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={'order_id': 1},
        )
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'server error'
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post',
                   return_value=mock_response):
            log._send_one()
        self.assertEqual(log.state, 'failed')
        self.assertEqual(log.retry_count, 1)
        self.assertEqual(log.http_status_code, 500)
        self.assertTrue(log.next_retry_at)

    def test_send_one_connection_error_schedules_retry(self):
        import requests
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={},
        )
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post',
                   side_effect=requests.exceptions.ConnectionError("DNS fail")):
            log._send_one()
        self.assertEqual(log.state, 'failed')
        self.assertEqual(log.retry_count, 1)
        self.assertIn('RequestException', log.error_message)
        self.assertIn('DNS fail', log.error_message)

    def test_giveup_after_max_retry(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_openclaw.webhook_max_retry', '2')
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={},
        )
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'fail'
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post',
                   return_value=mock_response):
            log._send_one()  # retry_count=1
            log._send_one()  # retry_count=2
            log._send_one()  # retry_count=3 > max=2 → giveup
        self.assertEqual(log.state, 'giveup')
        self.assertEqual(log.retry_count, 3)

    def test_send_with_no_url_marks_failed(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_openclaw.webhook_url', '')
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={},
        )
        result = log._send_one()
        self.assertFalse(result)
        self.assertEqual(log.state, 'failed')
        self.assertIn('URL not configured', log.error_message)

    def test_cron_dispatch_picks_up_pending(self):
        log1 = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={'order_id': 1})
        log2 = self.WebhookLog.sudo().enqueue_event(
            event_type='task.created', data={'task_id': 2})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'ok'
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post',
                   return_value=mock_response):
            self.WebhookLog.sudo().cron_dispatch_pending_webhooks()
        log1.invalidate_recordset()
        log2.invalidate_recordset()
        self.assertEqual(log1.state, 'sent')
        self.assertEqual(log2.state, 'sent')

    def test_cron_skips_when_disabled(self):
        log = self.WebhookLog.sudo().enqueue_event(
            event_type='order.created', data={})
        # Skipped đã từ enqueue khi disabled — đảm bảo cron không cố process
        self.env['ir.config_parameter'].sudo().set_param('dac_openclaw.webhook_enabled', 'false')
        with patch('odoo.addons.dac_openclaw.services.outbound_webhook_service.requests.post') as mock_post:
            self.WebhookLog.sudo().cron_dispatch_pending_webhooks()
        mock_post.assert_not_called()
        # Log gốc đã ở 'pending' từ enqueue lúc enabled, cron tắt nên không động vào
        log.invalidate_recordset()
        self.assertEqual(log.state, 'pending')
