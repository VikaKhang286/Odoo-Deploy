"""Test pancake_messaging service (HTTP + token + error cases)."""
from unittest import SkipTest
from unittest.mock import MagicMock, patch

import requests

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.services import pancake_messaging


@tagged('post_install', '-at_install')
class TestPhase3PancakeMessaging(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'page.fm.conversation' not in cls.env.registry.models:
            raise SkipTest("CRM_DAC not loaded")
        cls.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', 'main-tok-123')
        cls.partner = cls.env['res.partner'].create({'name': 'PM Partner'})
        cls.page = cls.env['page.fm.page'].create({
            'name': 'PM Page', 'page_fm_id_str': 'pm-page-id-001',
        })

    def setUp(self):
        super().setUp()
        self.conv = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'pm-conv-%s' % self._testMethodName,
            'page_fm_page_id': self.page.id,
            'partner_id': self.partner.id,
            'conv_page_fm_id': 'pm-page-id-001',
        })

    def test_missing_text_returns_invalid_text(self):
        result = pancake_messaging.send_pancake_message(self.env, self.conv, '')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'invalid_text')

    def test_missing_token_returns_token_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', '')
        result = pancake_messaging.send_pancake_message(self.env, self.conv, 'hi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'token_not_configured')

    def test_token_generation_failure(self):
        with patch.object(type(self.page), '_generate_page_specific_access_token',
                          return_value=None):
            result = pancake_messaging.send_pancake_message(self.env, self.conv, 'hi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'token_generation_failed')

    def test_success_returns_message_id(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"id":"msg-9999"}'
        mock_response.json.return_value = {'id': 'msg-9999'}
        with patch.object(type(self.page), '_generate_page_specific_access_token',
                          return_value='page-tok-xyz'):
            with patch('odoo.addons.dac_erp.services.pancake_messaging.requests.post',
                       return_value=mock_response) as mock_post:
                result = pancake_messaging.send_pancake_message(
                    self.env, self.conv, 'Xin chào')
        self.assertTrue(result['ok'])
        self.assertEqual(result['message_id'], 'msg-9999')
        self.assertEqual(result['http_status'], 200)
        # URL chứa page_fm_id_str + conversation_fm_id
        url = mock_post.call_args.args[0]
        self.assertIn('pm-page-id-001', url)
        self.assertIn(self.conv.conversation_fm_id, url)

    def test_http_error_returns_pancake_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'server boom'
        mock_response.json.side_effect = ValueError()
        with patch.object(type(self.page), '_generate_page_specific_access_token',
                          return_value='page-tok'):
            with patch('odoo.addons.dac_erp.services.pancake_messaging.requests.post',
                       return_value=mock_response):
                result = pancake_messaging.send_pancake_message(self.env, self.conv, 'hi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'pancake_api_error')
        self.assertEqual(result['http_status'], 500)

    def test_network_error(self):
        with patch.object(type(self.page), '_generate_page_specific_access_token',
                          return_value='page-tok'):
            with patch('odoo.addons.dac_erp.services.pancake_messaging.requests.post',
                       side_effect=requests.exceptions.Timeout()):
                result = pancake_messaging.send_pancake_message(self.env, self.conv, 'hi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'network_error')

    def test_with_attachments(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{}'
        mock_response.json.return_value = {}
        with patch.object(type(self.page), '_generate_page_specific_access_token',
                          return_value='page-tok'):
            with patch('odoo.addons.dac_erp.services.pancake_messaging.requests.post',
                       return_value=mock_response) as mock_post:
                result = pancake_messaging.send_pancake_message(
                    self.env, self.conv, 'hi',
                    attachment_urls=['https://x.com/a.jpg', 'https://x.com/b.jpg'])
        self.assertTrue(result['ok'])
        # Verify body có attachments
        import json
        body = json.loads(mock_post.call_args.kwargs['data'])
        self.assertEqual(len(body.get('attachments', [])), 2)
