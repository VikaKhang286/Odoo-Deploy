# -*- coding: utf-8 -*-
from odoo import fields, models


class PageFmConversationAiLog(models.Model):
    _name = 'page.fm.conversation.ai.log'
    _description = 'Conversation AI Audit Log'
    _order = 'id desc'

    conversation_id = fields.Many2one(
        'page.fm.conversation',
        required=True,
        index=True,
        ondelete='cascade',
        string='Conversation',
    )
    action_type = fields.Selection(
        [
            ('summary_upsert', 'Summary Upsert'),
            ('note_create', 'Note Create'),
            ('triage_update', 'Triage Update'),
            ('activity_create', 'Activity Create'),
            ('tag_replace', 'Tag Replace'),
        ],
        required=True,
        index=True,
    )
    request_id = fields.Char(required=True, index=True)
    request_payload_json = fields.Text(required=True)
    payload_fingerprint = fields.Char(required=True, index=True)
    agent_name = fields.Char(required=True)
    model_name = fields.Char()
    confidence = fields.Float()
    old_value_json = fields.Text()
    new_value_json = fields.Text()
    response_json = fields.Text()
    status = fields.Selection(
        [
            ('success', 'Success'),
            ('replayed', 'Replayed'),
            ('conflict', 'Conflict'),
            ('failed', 'Failed'),
        ],
        required=True,
        default='success',
        index=True,
    )
    activity_id = fields.Many2one('mail.activity', string='Activity', readonly=True)
    reason = fields.Char()
    summary_text = fields.Text()
    note_text = fields.Text()

    # Tag-specific fields (action_type = tag_replace)
    mode = fields.Char(help="Tag update mode: replace_ai_scope / add / remove / replace_all")
    dry_run = fields.Boolean(default=False, help="True = dry_run request, no actual mutation")
    applied = fields.Boolean(default=True, help="False = skipped due to needs_review or do_not_apply_reason")
    needs_review = fields.Boolean(default=False)
    do_not_apply_reason = fields.Char(help="Reason AI chose not to apply tags (blind spot, missing evidence, etc.)")
    evidence_json = fields.Text(help="JSON list of evidence strings provided by AI")

    _sql_constraints = [
        ('uniq_request_id', 'unique(request_id)', 'AI request_id must be unique.'),
    ]
