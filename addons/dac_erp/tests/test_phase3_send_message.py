"""Test Phase 3 send-message route via MCP."""
from unittest import SkipTest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp_phase3_extension import MCPPhase3ExtensionController


@tagged('post_install', '-at_install')
class TestPhase3SendMessage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.controller = MCPPhase3ExtensionController()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_read_key', 'mcp-read-test-key')
        icp.set_param('dac_erp.mcp_write_key', 'mcp-write-test-key')
        icp.set_param('page_fm.access_token', 'fake-main-token')

        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")

        cls.partner = cls.env['res.partner'].create({'name': 'Phase3 SendMsg Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'Phase3 Page', 'page_fm_id_str': 'phase3-page-001',
        })

    def setUp(self):
        super().setUp()
        self.conv = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'phase3-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'customer_name_fm': 'Test Customer',
            'conv_page_fm_id': 'phase3-page-001',
        })

    def _headers(self, key):
        return {'X-MCP-API-KEY': key}

    def _payload(self, request_id, **extra):
        body = {
            'request_id': request_id,
            'agent_name': 'OpenClaw',
            'text': 'Xin chào quý khách',
        }
        body.update(extra)
        return body

    def _mock_pancake_ok(self, message_id='pm-12345'):
        return {
            'ok': True,
            'http_status': 200,
            'message_id': message_id,
            'raw_response': '{"id":"' + message_id + '"}',
        }

    def _mock_pancake_fail(self, code='pancake_api_error', msg='HTTP 500',
                            http_status=500):
        return {
            'ok': False,
            'http_status': http_status,
            'error_code': code,
            'error_message': msg,
            'raw_response': 'server error',
        }

    def test_send_message_success(self):
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message',
                   return_value=self._mock_pancake_ok()):
            payload, code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-001'),
            )
        self.assertEqual(code, 200, payload)
        self.assertEqual(payload['data']['action'], 'message_send')
        self.assertEqual(payload['data']['pancake_message_id'], 'pm-12345')
        log = self.env['dac_erp.mcp.conversation.message.log'].search(
            [('request_id', '=', 'send-001')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.status, 'success')

    def test_send_message_with_attachments(self):
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message',
                   return_value=self._mock_pancake_ok()) as mock_send:
            payload, code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-att-001',
                                       attachment_urls=['https://example.com/a.jpg']),
            )
        self.assertEqual(code, 200, payload)
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs['attachment_urls'], ['https://example.com/a.jpg'])

    def test_send_message_missing_text(self):
        body = {
            'request_id': 'send-missing-001',
            'agent_name': 'OpenClaw',
        }
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_send_message,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_send_message_invalid_via(self):
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_send_message,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('send-via-001', via='telegram'),
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')

    def test_send_message_conversation_not_found(self):
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_send_message,
            999999999,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=self._payload('send-404-001'),
        )
        self.assertEqual(code, 404)
        self.assertEqual(payload['error']['code'], 'not_found')

    def test_send_message_pancake_api_failure(self):
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message',
                   return_value=self._mock_pancake_fail()):
            payload, code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-fail-001'),
            )
        self.assertEqual(code, 502)
        self.assertEqual(payload['error']['code'], 'pancake_api_error')
        log = self.env['dac_erp.mcp.conversation.message.log'].search(
            [('request_id', '=', 'send-fail-001')], limit=1)
        self.assertEqual(log.status, 'failed')

    def test_send_message_token_not_configured(self):
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message',
                   return_value={'ok': False, 'error_code': 'token_not_configured',
                                  'error_message': 'token missing'}):
            payload, code = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-notoken-001'),
            )
        self.assertEqual(code, 503)
        self.assertEqual(payload['error']['code'], 'config_missing')

    def test_send_message_replay(self):
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message',
                   return_value=self._mock_pancake_ok('replay-msg-id')):
            first, c1 = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-replay-001'),
            )
        self.assertEqual(c1, 200)
        # Second call with same request_id — không gọi lại Pancake
        with patch('odoo.addons.dac_erp.services.pancake_messaging.send_pancake_message') as mock:
            second, c2 = self.controller._run_mcp_handler(
                self.controller._dispatch_mcp_send_message,
                self.conv.id,
                env=self.env,
                headers=self._headers('mcp-write-test-key'),
                payload=self._payload('send-replay-001'),
            )
        self.assertEqual(c2, 200)
        self.assertTrue(second['data']['idempotent_replay'])
        mock.assert_not_called()

    def test_send_message_read_key_rejected(self):
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_send_message,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-read-test-key'),
            payload=self._payload('send-readk-001'),
        )
        self.assertEqual(code, 403)
        self.assertEqual(payload['error']['code'], 'insufficient_permission')

    def test_send_message_unknown_field(self):
        body = self._payload('send-unknown-001')
        body['weird_field'] = 'x'
        payload, code = self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_send_message,
            self.conv.id,
            env=self.env,
            headers=self._headers('mcp-write-test-key'),
            payload=body,
        )
        self.assertEqual(code, 400)
        self.assertEqual(payload['error']['code'], 'validation_error')
