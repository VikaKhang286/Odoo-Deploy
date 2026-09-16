"""Test token-bucket rate limit service."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.services import mcp_rate_limit


@tagged('post_install', '-at_install')
class TestPhase4RateLimit(TransactionCase):

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_rate_limit_enabled', 'true')
        icp.set_param('dac_erp.mcp_rate_limit_capacity', '5')
        icp.set_param('dac_erp.mcp_rate_limit_refill_per_sec', '1')
        # Clear any existing buckets
        self.env['dac_erp.mcp.rate.limit.bucket'].sudo().search([]).unlink()

    def test_disabled_always_allows(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.mcp_rate_limit_enabled', 'false')
        for _ in range(100):
            allowed, retry = mcp_rate_limit.check_rate_limit(self.env, 'any-key')
            self.assertTrue(allowed)
            self.assertEqual(retry, 0)

    def test_first_request_allowed_creates_bucket(self):
        allowed, retry = mcp_rate_limit.check_rate_limit(self.env, 'k1')
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)
        b = self.env['dac_erp.mcp.rate.limit.bucket'].sudo().search(
            [('total_requests', '>', 0)], limit=1)
        self.assertTrue(b)
        self.assertEqual(b.total_requests, 1)

    def test_burst_allowed_up_to_capacity(self):
        # capacity=5, consume 5 → all allowed
        for i in range(5):
            allowed, _ = mcp_rate_limit.check_rate_limit(self.env, 'k-burst')
            self.assertTrue(allowed, "Request %s should be allowed" % i)

    def test_over_capacity_rejected(self):
        # Consume capacity, next call → reject
        for _ in range(5):
            mcp_rate_limit.check_rate_limit(self.env, 'k-over')
        allowed, retry = mcp_rate_limit.check_rate_limit(self.env, 'k-over')
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)

    def test_separate_keys_separate_buckets(self):
        # k-a consume tới hết
        for _ in range(5):
            mcp_rate_limit.check_rate_limit(self.env, 'k-a')
        allowed_a, _ = mcp_rate_limit.check_rate_limit(self.env, 'k-a')
        self.assertFalse(allowed_a)
        # k-b vẫn còn full token
        allowed_b, _ = mcp_rate_limit.check_rate_limit(self.env, 'k-b')
        self.assertTrue(allowed_b)

    def test_no_key_allowed(self):
        allowed, _ = mcp_rate_limit.check_rate_limit(self.env, '')
        self.assertTrue(allowed)

    def test_hash_keys_not_stored_plaintext(self):
        mcp_rate_limit.check_rate_limit(self.env, 'sensitive-secret-key')
        buckets = self.env['dac_erp.mcp.rate.limit.bucket'].sudo().search([])
        for b in buckets:
            self.assertNotIn('sensitive-secret-key', b.api_key_hash)
            self.assertEqual(len(b.api_key_hash), 64)  # SHA256 hex
