# -*- coding: utf-8 -*-
"""Token-bucket rate limit storage cho MCP v2.

Mỗi API key có 1 bucket. Token refill mỗi giây. Bucket capacity và refill rate
config qua ICP:
  - dac_erp.mcp_rate_limit_capacity (default 60 — burst)
  - dac_erp.mcp_rate_limit_refill_per_sec (default 2 — 120/phút)

Khi consume:
  - Nếu token > 0, trừ 1 và cho qua
  - Nếu token = 0, return 429 với Retry-After header
"""
from odoo import fields, models


class DacErpMcpRateLimitBucket(models.Model):
    _name = 'dac_erp.mcp.rate.limit.bucket'
    _description = 'DAC MCP Rate Limit Token Bucket'
    _rec_name = 'api_key_hash'

    api_key_hash = fields.Char(required=True, index=True,
                                help='SHA256 hash của API key — không lưu key plaintext')
    tokens = fields.Float(required=True, default=0.0)
    last_refill_at = fields.Datetime(required=True, default=fields.Datetime.now)
    total_requests = fields.Integer(default=0)
    total_rejected = fields.Integer(default=0)

    _sql_constraints = [
        ('uniq_api_key_hash', 'unique(api_key_hash)', 'One bucket per API key.'),
    ]
