from odoo import models, fields
from datetime import datetime, timezone
import logging
_logger = logging.getLogger(__name__)

class ConversationMessageSyncWizard(models.TransientModel):
    _name = 'page.fm.conversation.message.sync.wizard'
    _description = 'Sync Messages for Conversations (by date range)'

    date_from = fields.Datetime(string="From (UTC)")
    date_to   = fields.Datetime(string="To (UTC)")
    unread_only = fields.Boolean(string="Unread first", default=False)

    def action_sync(self):
        convs = self.env['page.fm.conversation'].browse(self._context.get('active_ids', []))
        for c in convs:
            try:
                c.action_sync_messages(date_from=self.date_from, date_to=self.date_to, unread_first=self.unread_only)
            except Exception as e:
                _logger.exception("Sync messages failed for %s: %s", c.display_name, e)
        return {'type': 'ir.actions.act_window_close'}