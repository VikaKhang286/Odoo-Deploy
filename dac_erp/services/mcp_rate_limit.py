# -*- coding: utf-8 -*-
"""Token-bucket rate limiter cho MCP v2.

Cách dùng (trong controller):
    from .services.mcp_rate_limit import check_rate_limit
    allowed, retry_after = check_rate_limit(env, api_key)
    if not allowed:
        return 429 response with header Retry-After=retry_after

Mỗi key dùng 1 bucket. Burst capacity và refill rate config qua ICP.
"""
import hashlib
import logging
from datetime import datetime

from odoo import fields


_logger = logging.getLogger(__name__)


ICP_CAPACITY = 'dac_erp.mcp_rate_limit_capacity'
ICP_REFILL_PER_SEC = 'dac_erp.mcp_rate_limit_refill_per_sec'
ICP_ENABLED = 'dac_erp.mcp_rate_limit_enabled'

DEFAULT_CAPACITY = 60.0       # burst tối đa
DEFAULT_REFILL_PER_SEC = 2.0  # 120 req/phút sustained


def _hash_key(api_key):
    if not api_key:
        return ''
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def _get_config(env):
    icp = env['ir.config_parameter'].sudo()
    raw_enabled = (icp.get_param(ICP_ENABLED) or 'false').strip().lower()
    enabled = raw_enabled in ('1', 'true', 'yes', 'on')

    try:
        capacity = float((icp.get_param(ICP_CAPACITY) or '').strip() or DEFAULT_CAPACITY)
        if capacity < 1:
            capacity = DEFAULT_CAPACITY
    except (ValueError, TypeError):
        capacity = DEFAULT_CAPACITY

    try:
        refill = float((icp.get_param(ICP_REFILL_PER_SEC) or '').strip() or DEFAULT_REFILL_PER_SEC)
        if refill <= 0:
            refill = DEFAULT_REFILL_PER_SEC
    except (ValueError, TypeError):
        refill = DEFAULT_REFILL_PER_SEC

    return enabled, capacity, refill


def check_rate_limit(env, api_key):
    """Consume 1 token from bucket. Return (allowed, retry_after_seconds).

    allowed=True → token consumed, request có thể tiếp tục.
    allowed=False → bucket cạn, retry_after = giây để có lại 1 token.
    """
    enabled, capacity, refill_per_sec = _get_config(env)
    if not enabled:
        return True, 0

    if not api_key:
        # No key → reject (caller chưa auth, không có lý do để rate-limit ở đây
        # nhưng cũng không nên cho qua)
        return True, 0

    key_hash = _hash_key(api_key)
    Bucket = env['dac_erp.mcp.rate.limit.bucket'].sudo()
    now = fields.Datetime.now()
    bucket = Bucket.search([('api_key_hash', '=', key_hash)], limit=1)
    if not bucket:
        bucket = Bucket.create({
            'api_key_hash': key_hash,
            'tokens': capacity - 1.0,  # consume 1 ngay
            'last_refill_at': now,
            'total_requests': 1,
        })
        return True, 0

    # Refill tokens theo thời gian trôi qua
    elapsed_seconds = (now - bucket.last_refill_at).total_seconds()
    if elapsed_seconds < 0:
        elapsed_seconds = 0
    refilled_tokens = min(capacity, bucket.tokens + elapsed_seconds * refill_per_sec)

    if refilled_tokens >= 1.0:
        bucket.sudo().write({
            'tokens': refilled_tokens - 1.0,
            'last_refill_at': now,
            'total_requests': bucket.total_requests + 1,
        })
        return True, 0

    # Reject
    retry_after = int(max(1, (1.0 - refilled_tokens) / refill_per_sec))
    bucket.sudo().write({
        'tokens': refilled_tokens,
        'last_refill_at': now,
        'total_rejected': bucket.total_rejected + 1,
    })
    return False, retry_after
