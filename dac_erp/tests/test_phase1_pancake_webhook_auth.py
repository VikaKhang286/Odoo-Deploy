"""Test HMAC/api_key auth cho /dac_erp/pancake_webhook."""
import hashlib
import hmac
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers import pancake_webhook_controller


@tagged('post_install', '-at_install')
class TestPhase1PancakeWebhookAuth(TransactionCase):

    def _mock_request(self, env, headers=None):
        mock_req = MagicMock()
        mock_req.env = env
        mock_httpreq = MagicMock()
        mock_httpreq.headers = headers or {}
        mock_req.httprequest = mock_httpreq
        # make_response giả lập
        def _make_response(body, headers=None, status=200):
            resp = MagicMock()
            resp.body = body
            resp.status_code = status
            return resp
        mock_req.make_response = _make_response
        return mock_req

    def test_disabled_mode_allows_request(self):
        """Mode disabled (default) cho qua, chỉ log warning."""
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'disabled')
        mock_req = self._mock_request(self.env)
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{}')
        self.assertIsNone(result)

    def test_api_key_mode_missing_header(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'api_key')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'pk-secret')
        mock_req = self._mock_request(self.env, headers={})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{}')
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 401)

    def test_api_key_mode_wrong_key(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'api_key')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'pk-secret')
        mock_req = self._mock_request(self.env, headers={'X-API-KEY': 'wrong'})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{}')
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 403)

    def test_api_key_mode_correct(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'api_key')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'pk-secret')
        mock_req = self._mock_request(self.env, headers={'X-API-KEY': 'pk-secret'})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{}')
        self.assertIsNone(result)

    def test_hmac_mode_missing_signature(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'hmac')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'hmac-secret')
        mock_req = self._mock_request(self.env, headers={})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{"event":"order"}')
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 401)

    def test_hmac_mode_wrong_signature(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'hmac')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'hmac-secret')
        mock_req = self._mock_request(self.env, headers={'X-Pancake-Signature': 'deadbeef'})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{"event":"order"}')
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 403)

    def test_hmac_mode_correct_signature(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'hmac')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'hmac-secret')
        body = b'{"event":"order","id":123}'
        sig = hmac.new(b'hmac-secret', body, hashlib.sha256).hexdigest()
        mock_req = self._mock_request(self.env, headers={'X-Pancake-Signature': sig})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(body)
        self.assertIsNone(result)

    def test_hmac_mode_sha256_prefix_accepted(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'hmac')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', 'hmac-secret')
        body = b'{"event":"order","id":123}'
        sig = hmac.new(b'hmac-secret', body, hashlib.sha256).hexdigest()
        mock_req = self._mock_request(self.env, headers={'X-Pancake-Signature': 'sha256=' + sig})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(body)
        self.assertIsNone(result)

    def test_hmac_mode_missing_secret_returns_503(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_auth_mode', 'hmac')
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.pancake_webhook_secret', '')
        mock_req = self._mock_request(self.env, headers={'X-Pancake-Signature': 'sha256=abc'})
        with patch.object(pancake_webhook_controller, 'request', mock_req):
            result = pancake_webhook_controller._verify_pancake_webhook_auth(b'{}')
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, 503)
