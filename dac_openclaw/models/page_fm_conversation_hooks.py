# -*- coding: utf-8 -*-
"""Hooks vào page.fm.conversation để fire outbound webhook events.

Events:
- conversation.assigned: khi owner_id thay đổi
- conversation.status_changed: khi status_state thay đổi
"""
import logging

from odoo import models


_logger = logging.getLogger(__name__)


def _build_conversation_payload(conv):
    return {
        'conversation_id': conv.id,
        'conversation_fm_id': conv.conversation_fm_id or None,
        'platform': conv.platform_fm or None,
        'status_state': conv.status_state,
        'require_processing': conv.require_processing,
        'customer_name': conv.customer_name_fm or None,
        'partner_id': conv.partner_id.id if conv.partner_id else None,
        'owner_user_id': conv.owner_id.id if conv.owner_id else None,
        'owner_user_name': conv.owner_id.name if conv.owner_id else None,
        'last_message_snippet': (conv.last_message_snippet or '')[:200],
        'last_message_at_fm': conv.last_message_at_fm.isoformat() if conv.last_message_at_fm else None,
    }


class PageFmConversationOpenclawHook(models.Model):
    _inherit = 'page.fm.conversation'

    def write(self, vals):
        # Snapshot fields trước write
        before_owner = {rec.id: rec.owner_id.id for rec in self}
        before_status = {rec.id: rec.status_state for rec in self}
        result = super().write(vals)
        webhook_model = self.env['dac_openclaw.outbound.webhook.log']
        if 'owner_id' in vals:
            for conv in self:
                old_owner = before_owner.get(conv.id)
                new_owner = conv.owner_id.id if conv.owner_id else None
                if old_owner == new_owner:
                    continue
                try:
                    data = _build_conversation_payload(conv)
                    data['old_owner_user_id'] = old_owner
                    data['new_owner_user_id'] = new_owner
                    webhook_model.sudo().enqueue_event(
                        event_type='conversation.assigned',
                        data=data,
                        conversation_id=conv.id,
                    )
                except Exception as exc:
                    _logger.warning("Failed to enqueue conversation.assigned for %s: %s",
                                    conv.id, exc)
        if 'status_state' in vals:
            for conv in self:
                old_status = before_status.get(conv.id)
                new_status = conv.status_state
                if old_status == new_status:
                    continue
                try:
                    data = _build_conversation_payload(conv)
                    data['old_status_state'] = old_status
                    data['new_status_state'] = new_status
                    webhook_model.sudo().enqueue_event(
                        event_type='conversation.status_changed',
                        data=data,
                        conversation_id=conv.id,
                    )
                except Exception as exc:
                    _logger.warning("Failed to enqueue conversation.status_changed for %s: %s",
                                    conv.id, exc)
        return result
