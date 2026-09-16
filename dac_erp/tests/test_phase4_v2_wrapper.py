"""Test MCP v2 wrapper: response format {ok, _envelope_type, meta}.

Dùng HttpCase với GET only — url_open() trong Odoo 18 không hỗ trợ method override.
"""
import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged('post_install', '-at_install')
class TestPhase4V2WrapperFormat(HttpCase):

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_read_key', 'v2-read-key')
        icp.set_param('dac_erp.mcp_write_key', 'v2-write-key')
        icp.set_param('dac_erp.mcp_rate_limit_enabled', 'false')

    def _get(self, path, headers=None):
        return self.url_open(self.base_url() + path, headers=headers or {},
                              timeout=30)

    def test_health_returns_v2_format(self):
        resp = self._get('/dac_erp/mcp/v2/health',
                          headers={'X-MCP-API-KEY': 'v2-read-key'})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertIn('data', body)
        self.assertEqual(body['_envelope_type'], 'detail')
        self.assertIn('meta', body)
        self.assertIn('trace_id', body['meta'])
        self.assertIn('took_ms', body['meta'])
        self.assertTrue(resp.headers.get('X-MCP-Trace-Id'))

    def test_missing_key_returns_v2_error_format(self):
        resp = self._get('/dac_erp/mcp/v2/health')
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['_envelope_type'], 'error')
        self.assertEqual(body['error']['code'], 'missing_api_key')
        self.assertIn('trace_id', body['meta'])

    def test_trace_id_echoed_from_request(self):
        resp = self._get('/dac_erp/mcp/v2/health',
                          headers={'X-MCP-API-KEY': 'v2-read-key',
                                    'X-Trace-Id': 'caller-trace-001'})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body['meta']['trace_id'], 'caller-trace-001')
        self.assertEqual(resp.headers.get('X-MCP-Trace-Id'), 'caller-trace-001')

    def test_rate_limit_429_returns_v2_format(self):
        # Enable rate limit với capacity=1 để dễ trigger
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp_rate_limit_enabled', 'true')
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp_rate_limit_capacity', '1')
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp_rate_limit_refill_per_sec', '0.1')
        # Clear buckets từ test trước
        self.env['dac_erp.mcp.rate.limit.bucket'].sudo().search([]).unlink()
        # Force commit so HTTP request sees the ICP + cleared buckets
        # (HttpCase shares cursor but different env — invalidate cache)
        self.env.invalidate_all()

        # 1st request OK
        resp1 = self._get('/dac_erp/mcp/v2/health',
                           headers={'X-MCP-API-KEY': 'v2-read-key'})
        self.assertEqual(resp1.status_code, 200)
        # 2nd request → 429
        resp2 = self._get('/dac_erp/mcp/v2/health',
                           headers={'X-MCP-API-KEY': 'v2-read-key'})
        self.assertEqual(resp2.status_code, 429, resp2.text)
        body = resp2.json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['_envelope_type'], 'error')
        self.assertEqual(body['error']['code'], 'rate_limit_exceeded')
        self.assertTrue(resp2.headers.get('Retry-After'))
        # Disable lại để không ảnh hưởng test khác
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp_rate_limit_enabled', 'false')
