"""Test API key enforcement cho export endpoints — chỉ test logic _check_export_api_key."""
from unittest.mock import patch, MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.data_export_controller import DataExportController


@tagged('post_install', '-at_install')
class TestPhase1ExportSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = DataExportController()

    def _mock_request(self, env, headers=None):
        """Tạo mock request object cho _check_export_api_key."""
        mock_req = MagicMock()
        mock_req.env = env
        mock_httpreq = MagicMock()
        mock_httpreq.headers = headers or {}
        mock_req.httprequest = mock_httpreq
        return mock_req

    def test_config_missing_returns_503(self):
        # ICP không có key → 503
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.export_api_key', '')
        mock_req = self._mock_request(self.env, headers={'X-API-KEY': 'whatever'})
        with patch('odoo.addons.dac_erp.controllers.data_export_controller.request', mock_req):
            response = self.controller._check_export_api_key()
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 503)

    def test_missing_header_returns_401(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.export_api_key', 'exp-secret-123')
        mock_req = self._mock_request(self.env, headers={})
        with patch('odoo.addons.dac_erp.controllers.data_export_controller.request', mock_req):
            response = self.controller._check_export_api_key()
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 401)

    def test_wrong_key_returns_403(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.export_api_key', 'exp-secret-123')
        mock_req = self._mock_request(self.env, headers={'X-API-KEY': 'wrong'})
        with patch('odoo.addons.dac_erp.controllers.data_export_controller.request', mock_req):
            response = self.controller._check_export_api_key()
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_correct_key_returns_none(self):
        self.env['ir.config_parameter'].sudo().set_param('dac_erp.export_api_key', 'exp-secret-123')
        mock_req = self._mock_request(self.env, headers={'X-API-KEY': 'exp-secret-123'})
        with patch('odoo.addons.dac_erp.controllers.data_export_controller.request', mock_req):
            response = self.controller._check_export_api_key()
        self.assertIsNone(response)
