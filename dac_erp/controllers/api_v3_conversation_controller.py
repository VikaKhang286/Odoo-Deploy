# -*- coding: utf-8 -*-
import hashlib
import json
import logging

from odoo import fields, http
from odoo.http import request

from odoo.addons.CRM_DAC.models.page_fm_conversation_models import PancakeTagSyncError
from .api_v2_controller import DataExportV2Controller

_logger = logging.getLogger(__name__)


class ConversationAIV3Controller(DataExportV2Controller):
    V3_WRITE_API_KEY_PARAM = 'dac_erp.api_v3_ai_write_key'

    def _get_v3_write_env(self, env=None):
        env = self._get_env(env)
        return env(user=env.ref('base.user_admin').id)

    def _ensure_v3_write_api_key(self, env=None, headers=None, provided_key=None):
        env = self._get_v3_write_env(env)
        expected_key = env['ir.config_parameter'].sudo().get_param(self.V3_WRITE_API_KEY_PARAM)
        if not expected_key:
            raise RuntimeError("AI write API key is not configured in ir.config_parameter")
        if provided_key is None:
            if headers is None:
                headers = getattr(getattr(request, 'httprequest', None), 'headers', {})
            provided_key = headers.get('X-API-KEY')
        if not provided_key or provided_key != expected_key:
            raise PermissionError("Unauthorized: Invalid or missing X-API-KEY")
        return True

    def _get_v3_json_payload(self, payload=None):
        return self._get_v2_json_payload(payload=payload)

    def _find_v3_conversation_or_404(self, conversation_id, env=None):
        env = self._get_v3_write_env(env)
        conversation = env['page.fm.conversation'].sudo().browse(int(conversation_id))
        if not conversation.exists():
            raise LookupError("Conversation %s was not found" % conversation_id)
        return conversation

    def _dump_json_text(self, value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _normalize_v3_request_payload(self, action_type, payload):
        payload = self._get_v3_json_payload(payload=payload)
        if 'request_id' not in payload or not isinstance(payload.get('request_id'), str) or not payload.get('request_id').strip():
            raise ValueError("request_id is required")
        if 'agent_name' not in payload or not isinstance(payload.get('agent_name'), str) or not payload.get('agent_name').strip():
            raise ValueError("agent_name is required")

        request_id = payload['request_id'].strip()
        agent_name = payload['agent_name'].strip()
        model_name = payload.get('model_name')
        if model_name not in (None, False):
            if not isinstance(model_name, str):
                raise ValueError("model_name must be a string")
            model_name = model_name.strip() or False

        normalized = {
            'request_id': request_id,
            'agent_name': agent_name,
            'model_name': model_name or False,
        }

        if action_type == 'summary_upsert':
            summary_text = payload.get('summary_text')
            if not isinstance(summary_text, str) or not summary_text.strip():
                raise ValueError("summary_text is required")
            normalized['summary_text'] = summary_text.strip()
            reason = payload.get('reason')
            if reason not in (None, False):
                if not isinstance(reason, str):
                    raise ValueError("reason must be a string")
                normalized['reason'] = reason.strip() or False
            else:
                normalized['reason'] = False
            confidence = payload.get('confidence')
            if confidence not in (None, ''):
                confidence_value = self._as_float(confidence, 'confidence')
                if confidence_value < 0 or confidence_value > 1:
                    raise ValueError("confidence must be between 0 and 1")
                normalized['confidence'] = confidence_value
            else:
                normalized['confidence'] = False
        elif action_type == 'note_create':
            note_text = payload.get('note_text')
            if not isinstance(note_text, str) or not note_text.strip():
                raise ValueError("note_text is required")
            normalized['note_text'] = note_text.strip()
            note_type = payload.get('note_type', 'internal_note')
            if not isinstance(note_type, str) or not note_type.strip():
                raise ValueError("note_type must be a non-empty string")
            normalized['note_type'] = note_type.strip()
        elif action_type == 'activity_create':
            allowed_fields = {
                'summary',
                'note',
                'user_id',
                'deadline_date',
                'activity_type_xmlid',
                'request_id',
                'agent_name',
                'model_name',
                'reason',
            }
            unknown_fields = sorted(set(payload) - allowed_fields)
            if unknown_fields:
                raise ValueError("Unsupported activity fields: %s" % ', '.join(unknown_fields))
            summary = payload.get('summary')
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("summary is required")
            normalized['summary'] = summary.strip()
            note = payload.get('note')
            if note not in (None, False):
                if not isinstance(note, str):
                    raise ValueError("note must be a string")
                normalized['note'] = note.strip()
            else:
                normalized['note'] = False
            user_id = payload.get('user_id')
            normalized['user_id'] = self._coerce_nullable_int(user_id, 'user_id')
            deadline_date = payload.get('deadline_date')
            normalized['deadline_date'] = self._coerce_nullable_date(deadline_date, 'deadline_date')
            activity_type_xmlid = payload.get('activity_type_xmlid')
            if activity_type_xmlid not in (None, False):
                if not isinstance(activity_type_xmlid, str) or not activity_type_xmlid.strip():
                    raise ValueError("activity_type_xmlid must be a non-empty string")
                normalized['activity_type_xmlid'] = activity_type_xmlid.strip()
            else:
                normalized['activity_type_xmlid'] = False
        elif action_type == 'triage_update':
            allowed_fields = {'status_state', 'require_processing', 'mark_read', 'reason', 'request_id', 'agent_name', 'model_name'}
            unknown_fields = sorted(set(payload) - allowed_fields)
            if unknown_fields:
                raise ValueError("Unsupported triage fields: %s" % ', '.join(unknown_fields))
            if 'status_state' not in payload and 'require_processing' not in payload and 'mark_read' not in payload:
                raise ValueError("At least one of status_state, require_processing, mark_read is required")
            if 'status_state' in payload:
                status_state = payload.get('status_state')
                if status_state not in ('new', 'recontact', 'waiting', 'done'):
                    raise ValueError("status_state must be one of new,recontact,waiting,done")
                normalized['status_state'] = status_state
            if 'require_processing' in payload:
                require_processing = self._as_bool(payload.get('require_processing'), 'require_processing')
                if require_processing is None:
                    raise ValueError("require_processing must be one of 1,0,true,false")
                normalized['require_processing'] = require_processing
            if 'mark_read' in payload:
                mark_read = self._as_bool(payload.get('mark_read'), 'mark_read')
                if mark_read is None:
                    raise ValueError("mark_read must be one of 1,0,true,false")
                normalized['mark_read'] = mark_read
            reason = payload.get('reason')
            if reason not in (None, False):
                if not isinstance(reason, str):
                    raise ValueError("reason must be a string")
                normalized['reason'] = reason.strip() or False
            else:
                normalized['reason'] = False
        elif action_type == 'tag_replace':
            allowed_tag_fields = {
                'tag_codes', 'mode', 'dry_run', 'reason', 'evidence',
                'confidence', 'needs_review', 'do_not_apply_reason',
                'request_id', 'agent_name', 'model_name',
            }
            unknown_tag_fields = sorted(set(payload) - allowed_tag_fields)
            if unknown_tag_fields:
                raise ValueError("Unsupported tag fields: %s" % ', '.join(unknown_tag_fields))

            tag_codes = payload.get('tag_codes')
            if not isinstance(tag_codes, list):
                raise ValueError("tag_codes must be a list")
            cleaned_codes = []
            seen_codes = set()
            for index, code_value in enumerate(tag_codes):
                if not isinstance(code_value, str):
                    raise ValueError("tag_codes[%s] must be a string" % index)
                code = code_value.strip()
                if not code:
                    raise ValueError("tag_codes[%s] cannot be empty" % index)
                if code in seen_codes:
                    raise ValueError("tag_codes cannot contain duplicates")
                seen_codes.add(code)
                cleaned_codes.append(code)
            normalized['tag_codes'] = cleaned_codes

            # mode
            mode = payload.get('mode', 'replace_ai_scope')
            if mode not in ('replace_ai_scope', 'add', 'remove', 'replace_all'):
                raise ValueError("mode must be one of replace_ai_scope, add, remove, replace_all")
            normalized['mode'] = mode

            # dry_run
            dry_run_raw = payload.get('dry_run', False)
            dry_run_val = self._as_bool(dry_run_raw, 'dry_run')
            normalized['dry_run'] = bool(dry_run_val)

            # evidence
            evidence = payload.get('evidence')
            if evidence not in (None, False):
                if not isinstance(evidence, list):
                    raise ValueError("evidence must be a list of strings")
                for ei, ev in enumerate(evidence):
                    if not isinstance(ev, str):
                        raise ValueError("evidence[%s] must be a string" % ei)
                normalized['evidence'] = evidence
            else:
                normalized['evidence'] = []

            # confidence
            confidence = payload.get('confidence')
            if confidence not in (None, ''):
                confidence_value = self._as_float(confidence, 'confidence')
                if confidence_value < 0 or confidence_value > 1:
                    raise ValueError("confidence must be between 0 and 1")
                normalized['confidence'] = confidence_value
            else:
                normalized['confidence'] = False

            # needs_review
            needs_review_raw = payload.get('needs_review', False)
            if needs_review_raw not in (None, False):
                nr = self._as_bool(needs_review_raw, 'needs_review')
                if nr is None:
                    raise ValueError("needs_review must be boolean")
                normalized['needs_review'] = bool(nr)
            else:
                normalized['needs_review'] = False

            # do_not_apply_reason
            do_not_apply_reason = payload.get('do_not_apply_reason')
            if do_not_apply_reason not in (None, False):
                if not isinstance(do_not_apply_reason, str):
                    raise ValueError("do_not_apply_reason must be a string")
                normalized['do_not_apply_reason'] = do_not_apply_reason.strip() or False
            else:
                normalized['do_not_apply_reason'] = False

            # reason
            reason = payload.get('reason')
            if reason not in (None, False):
                if not isinstance(reason, str):
                    raise ValueError("reason must be a string")
                normalized['reason'] = reason.strip() or False
            else:
                normalized['reason'] = False
        else:
            raise ValueError("Unsupported action_type %s" % action_type)
        return normalized

    def _compute_payload_fingerprint(self, normalized_payload):
        return hashlib.sha256(self._dump_json_text(normalized_payload).encode('utf-8')).hexdigest()

    def _status_code_for_log(self, log_record):
        mapping = {
            'success': 200,
            'replayed': 200,
            'failed': 500,
            'conflict': 409,
        }
        return mapping.get(log_record.status, 200)

    def _handle_idempotency_or_raise(self, env=None, request_id=None, payload_fingerprint=None):
        env = self._get_v3_write_env(env)
        log_record = env['page.fm.conversation.ai.log'].sudo().search([('request_id', '=', request_id)], limit=1)
        if not log_record:
            return None
        if log_record.payload_fingerprint != payload_fingerprint:
            raise ValueError("request_id already used with a different payload")
        return log_record

    def _serialize_v3_tag_snapshot(self, conversation):
        return conversation.sudo()._serialize_ai_tag_snapshot()

    def _serialize_v3_conversation_snapshot(self, conversation):
        conversation = conversation.sudo()
        owner = None
        if conversation.owner_id:
            owner = {
                'id': conversation.owner_id.id,
                'name': conversation.owner_id.name,
            }
        return {
            'id': conversation.id,
            'conversation_fm_id': conversation.conversation_fm_id,
            'status_state': conversation.status_state,
            'require_processing': bool(conversation.require_processing),
            'is_unread': bool(conversation.is_unread_fm),
            'last_suggestion_at': self._serialize_value(conversation.last_suggestion_at),
            'suggestion_note': conversation.suggestion_note,
            'owner': owner,
            'participants_count': len(conversation.participant_user_ids),
            'tags': self._serialize_v3_tag_snapshot(conversation),
        }

    def _create_ai_log(self, env=None, conversation=None, action_type=None, normalized_payload=None, payload_fingerprint=None,
                       old_value=None, new_value=None, response_data=None, status='success', activity=None):
        env = self._get_v3_write_env(env)
        normalized_payload = normalized_payload or {}
        response_data = response_data or {}
        create_vals = {
            'conversation_id': conversation.id,
            'action_type': action_type,
            'request_id': normalized_payload.get('request_id'),
            'request_payload_json': self._dump_json_text(normalized_payload),
            'payload_fingerprint': payload_fingerprint,
            'agent_name': normalized_payload.get('agent_name'),
            'model_name': normalized_payload.get('model_name') or False,
            'confidence': normalized_payload.get('confidence') or False,
            'old_value_json': self._dump_json_text(old_value or {}),
            'new_value_json': self._dump_json_text(new_value or {}),
            'response_json': self._dump_json_text(response_data),
            'status': status,
            'activity_id': activity.id if activity else False,
            'reason': normalized_payload.get('reason') or False,
            'summary_text': normalized_payload.get('summary_text') or False,
            'note_text': normalized_payload.get('note_text') or normalized_payload.get('note') or False,
        }
        return env['page.fm.conversation.ai.log'].sudo().create(create_vals)

    def _build_replayed_response_data(self, log_record, conversation):
        data = {}
        try:
            data = json.loads(log_record.response_json) if log_record.response_json else {}
        except Exception:
            data = {}
        data = dict(data or {})
        data['conversation_id'] = conversation.id
        data['log_id'] = log_record.id
        data['idempotent_replay'] = True
        if 'conversation' not in data:
            data['conversation'] = self._serialize_v3_conversation_snapshot(conversation)
        return data

    def _run_v3_action(self, action_type, conversation_id, payload, executor, replay_message, env=None):
        env = self._get_v3_write_env(env)
        normalized_payload = self._normalize_v3_request_payload(action_type, payload)
        conversation = self._find_v3_conversation_or_404(conversation_id, env=env)

        # dry_run requests skip idempotency entirely (no side effects to deduplicate)
        if normalized_payload.get('dry_run'):
            result = executor(env, conversation, normalized_payload, None)
            return {
                'message': result['message'],
                'status_code': result.get('status_code', 200),
                'data': result['data'],
            }

        payload_fingerprint = self._compute_payload_fingerprint(normalized_payload)
        existing_log = self._handle_idempotency_or_raise(
            env=env, request_id=normalized_payload['request_id'], payload_fingerprint=payload_fingerprint,
        )
        if existing_log:
            response_data = self._build_replayed_response_data(existing_log, conversation)
            return {
                'message': replay_message,
                'status_code': self._status_code_for_log(existing_log),
                'data': response_data,
            }

        result = executor(env, conversation, normalized_payload, payload_fingerprint)
        return {
            'message': result['message'],
            'status_code': result.get('status_code', 200),
            'data': result['data'],
        }

    def _update_conversation_ai_summary(self, env, conversation, normalized_payload, payload_fingerprint):
        old_value = {
            'suggestion_note': conversation.suggestion_note,
            'last_suggestion_at': self._serialize_value(conversation.last_suggestion_at),
        }
        with env.cr.savepoint():
            conversation.with_context(skip_auto_bump_require_processing=True).sudo().write({
                'suggestion_note': normalized_payload['summary_text'],
            })
        response_data = {
            'conversation_id': conversation.id,
            'changed_fields': {
                'suggestion_note': conversation.suggestion_note,
                'last_suggestion_at': self._serialize_value(conversation.last_suggestion_at),
            },
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
        }
        log_record = self._create_ai_log(
            env=env,
            conversation=conversation,
            action_type='summary_upsert',
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=old_value,
            new_value=response_data['changed_fields'],
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        response_data['idempotent_replay'] = False
        log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
        return {
            'message': 'Conversation AI summary updated successfully',
            'data': response_data,
        }

    def _create_conversation_ai_note(self, env, conversation, normalized_payload, payload_fingerprint):
        response_data = {
            'conversation_id': conversation.id,
            'changed_fields': {
                'note_text': normalized_payload['note_text'],
                'note_type': normalized_payload['note_type'],
            },
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
        }
        log_record = self._create_ai_log(
            env=env,
            conversation=conversation,
            action_type='note_create',
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value={},
            new_value=response_data['changed_fields'],
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        response_data['idempotent_replay'] = False
        log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
        return {
            'message': 'Conversation AI note logged successfully',
            'data': response_data,
        }

    def _create_conversation_followup_activity(self, env, conversation, normalized_payload, payload_fingerprint):
        user_id = normalized_payload.get('user_id') or (conversation.owner_id.id if conversation.owner_id else False)
        if not user_id:
            raise ValueError("user_id is required when conversation has no owner")
        user = self._ensure_record_exists(env, 'res.users', user_id, 'user_id')
        deadline_date = normalized_payload.get('deadline_date') or fields.Date.context_today(env.user)
        activity_type_xmlid = normalized_payload.get('activity_type_xmlid') or 'mail.mail_activity_data_todo'
        try:
            activity_type = env.ref(activity_type_xmlid)
        except Exception as exc:
            raise ValueError("activity_type_xmlid does not reference an existing mail.activity.type") from exc
        activity = env['mail.activity'].sudo().create({
            'activity_type_id': activity_type.id,
            'res_model_id': env['ir.model']._get_id('page.fm.conversation'),
            'res_id': conversation.id,
            'user_id': user.id,
            'summary': normalized_payload['summary'],
            'note': normalized_payload.get('note') or '',
            'date_deadline': deadline_date,
        })
        response_data = {
            'conversation_id': conversation.id,
            'activity_id': activity.id,
            'assigned_user_id': user.id,
            'deadline_date': self._serialize_value(deadline_date),
            'changed_fields': {
                'activity_id': activity.id,
                'assigned_user_id': user.id,
                'deadline_date': self._serialize_value(deadline_date),
                'activity_type_xmlid': activity_type_xmlid,
            },
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
        }
        log_record = self._create_ai_log(
            env=env,
            conversation=conversation,
            action_type='activity_create',
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value={},
            new_value=response_data['changed_fields'],
            response_data=response_data,
            status='success',
            activity=activity,
        )
        response_data['log_id'] = log_record.id
        response_data['idempotent_replay'] = False
        log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
        return {
            'message': 'Conversation follow-up activity created successfully',
            'data': response_data,
        }

    def _update_conversation_triage(self, env, conversation, normalized_payload, payload_fingerprint):
        old_value = {
            'status_state': conversation.status_state,
            'require_processing': bool(conversation.require_processing),
            'is_unread_fm': bool(conversation.is_unread_fm),
            'status_set_at': self._serialize_value(conversation.status_set_at),
        }
        write_vals = {}
        if 'status_state' in normalized_payload:
            write_vals['status_state'] = normalized_payload['status_state']
            write_vals['status_set_by_id'] = env.ref('base.user_admin').id
            write_vals['status_set_at'] = fields.Datetime.now()
            if normalized_payload['status_state'] == 'done' and 'require_processing' not in normalized_payload:
                write_vals['require_processing'] = False
        if 'require_processing' in normalized_payload:
            write_vals['require_processing'] = normalized_payload['require_processing']
        if 'mark_read' in normalized_payload:
            write_vals['is_unread_fm'] = not normalized_payload['mark_read']

        with env.cr.savepoint():
            conversation.with_context(skip_auto_bump_require_processing=True).sudo().write(write_vals)

        changed_fields = {
            key: value for key, value in {
                'status_state': conversation.status_state if 'status_state' in write_vals else None,
                'require_processing': bool(conversation.require_processing) if 'require_processing' in write_vals else None,
                'is_unread_fm': bool(conversation.is_unread_fm) if 'is_unread_fm' in write_vals else None,
                'status_set_at': self._serialize_value(conversation.status_set_at) if 'status_set_at' in write_vals else None,
            }.items() if value is not None
        }
        response_data = {
            'conversation_id': conversation.id,
            'changed_fields': changed_fields,
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
        }
        log_record = self._create_ai_log(
            env=env,
            conversation=conversation,
            action_type='triage_update',
            normalized_payload=normalized_payload,
            payload_fingerprint=payload_fingerprint,
            old_value=old_value,
            new_value=changed_fields,
            response_data=response_data,
            status='success',
        )
        response_data['log_id'] = log_record.id
        response_data['idempotent_replay'] = False
        log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
        return {
            'message': 'Conversation triage updated successfully',
            'data': response_data,
        }

    def _replace_conversation_tags(self, env, conversation, normalized_payload, payload_fingerprint):
        mode = normalized_payload.get('mode', 'replace_ai_scope')
        dry_run = bool(normalized_payload.get('dry_run', False))
        evidence = normalized_payload.get('evidence') or []
        needs_review = bool(normalized_payload.get('needs_review', False))
        do_not_apply_reason = normalized_payload.get('do_not_apply_reason') or None

        old_value = {'tags': conversation._serialize_ai_tag_snapshot()}

        try:
            with env.cr.savepoint():
                tag_result = conversation.sudo()._ai_replace_tags_by_codes(
                    normalized_payload['tag_codes'],
                    mode=mode,
                    dry_run=dry_run,
                    request_context={
                        'request_id': normalized_payload['request_id'],
                        'agent_name': normalized_payload['agent_name'],
                    },
                    evidence=evidence,
                    needs_review=needs_review,
                    do_not_apply_reason=do_not_apply_reason,
                )
        except PancakeTagSyncError as exc:
            response_data = {
                'conversation_id': conversation.id,
                'mode': mode,
                'dry_run': dry_run,
                'applied': False,
                'error': str(exc),
                'tag_sync_results': exc.sync_results,
                'conversation': self._serialize_v3_conversation_snapshot(conversation),
            }
            if payload_fingerprint:
                log_record = self._create_ai_log(
                    env=env, conversation=conversation, action_type='tag_replace',
                    normalized_payload=normalized_payload, payload_fingerprint=payload_fingerprint,
                    old_value=old_value, new_value={}, response_data=response_data, status='failed',
                )
                response_data['log_id'] = log_record.id
                log_record.sudo().write({'response_json': self._dump_json_text(response_data)})
            response_data['idempotent_replay'] = False
            return {'message': 'Conversation tags update failed', 'status_code': 500, 'data': response_data}

        applied = tag_result.get('applied', not dry_run)
        sync_results = tag_result.get('tag_sync_results', [])
        local_skip_count = sum(1 for r in sync_results if r.get('skipped'))

        response_data = {
            'conversation_id': conversation.id,
            'mode': mode,
            'dry_run': dry_run,
            'applied': applied,
            'requested_tag_codes': tag_result.get('requested_tag_codes', []),
            'applied_tag_codes': tag_result.get('applied_tag_codes', []),
            'would_add': tag_result.get('would_add', []),
            'would_remove': tag_result.get('would_remove', []),
            'added_tag_codes': tag_result.get('added_tag_codes', []),
            'removed_tag_codes': tag_result.get('removed_tag_codes', []),
            'kept_manual_tag_codes': tag_result.get('kept_manual_tag_codes', []),
            'not_ai_managed_codes': tag_result.get('not_ai_managed_codes', []),
            'not_applied_reason': tag_result.get('not_applied_reason') or False,
            'pancake_sync': {
                'enabled': True,
                'synced': applied and not dry_run,
                'results': [r for r in sync_results if not r.get('skipped')],
                'local_tags_skipped': local_skip_count,
            },
            'conversation': self._serialize_v3_conversation_snapshot(conversation),
        }

        # Save audit log only for real (non-dry_run) requests
        if payload_fingerprint:
            log_extra = {
                'mode': mode, 'dry_run': dry_run, 'applied': applied,
                'needs_review': needs_review, 'do_not_apply_reason': do_not_apply_reason or False,
                'evidence_json': self._dump_json_text(evidence) if evidence else False,
            }
            log_record = self._create_ai_log(
                env=env, conversation=conversation, action_type='tag_replace',
                normalized_payload=normalized_payload, payload_fingerprint=payload_fingerprint,
                old_value=old_value,
                new_value={
                    'mode': mode, 'tags': tag_result.get('tags', []),
                    'applied_tag_codes': tag_result.get('applied_tag_codes', []),
                    'added_tag_codes': tag_result.get('added_tag_codes', []),
                    'removed_tag_codes': tag_result.get('removed_tag_codes', []),
                },
                response_data=response_data, status='success',
            )
            log_record.sudo().write({'response_json': self._dump_json_text(response_data), **log_extra})
            response_data['log_id'] = log_record.id

        response_data['idempotent_replay'] = False
        msg = 'Conversation tags dry_run preview' if dry_run else 'Conversation tags updated successfully'
        return {'message': msg, 'data': response_data}

    def _handle_v3_route(self, action_type, conversation_id, executor, replay_message, payload=None):
        try:
            self._ensure_v3_write_api_key()
            result = self._run_v3_action(
                action_type=action_type,
                conversation_id=conversation_id,
                payload=self._get_v3_json_payload(payload=payload),
                executor=executor,
                replay_message=replay_message,
            )
            payload = {
                'success': result['status_code'] < 400,
                'message': result['message'],
                'status_code': result['status_code'],
                'data': result['data'],
            }
            if result['status_code'] >= 400:
                payload['error'] = result['data'].get('error') or result['message']
            return self._raw_json_response(payload, status_code=result['status_code'])
        except PermissionError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=401)
        except ValueError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=400)
        except LookupError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=404)
        except Exception as exc:
            _logger.error("Error in AI v3 route %s: %s", action_type, exc, exc_info=True)
            return self._write_json_response(success=False, message="Lỗi khi xử lý AI v3 request", error=str(exc), status_code=500)

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/ai-summary', type='http', auth='public', csrf=False, methods=['POST'])
    def v3_conversation_ai_summary(self, conversation_id, **kwargs):
        del kwargs
        return self._handle_v3_route(
            action_type='summary_upsert',
            conversation_id=conversation_id,
            executor=self._update_conversation_ai_summary,
            replay_message='Replayed AI summary request',
        )

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/ai-note', type='http', auth='public', csrf=False, methods=['POST'])
    def v3_conversation_ai_note(self, conversation_id, **kwargs):
        del kwargs
        return self._handle_v3_route(
            action_type='note_create',
            conversation_id=conversation_id,
            executor=self._create_conversation_ai_note,
            replay_message='Replayed AI note request',
        )

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/activities', type='http', auth='public', csrf=False, methods=['POST'])
    def v3_conversation_activity(self, conversation_id, **kwargs):
        del kwargs
        return self._handle_v3_route(
            action_type='activity_create',
            conversation_id=conversation_id,
            executor=self._create_conversation_followup_activity,
            replay_message='Replayed AI activity request',
        )

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/triage', type='http', auth='public', csrf=False, methods=['PATCH'])
    def v3_conversation_triage(self, conversation_id, **kwargs):
        del kwargs
        return self._handle_v3_route(
            action_type='triage_update',
            conversation_id=conversation_id,
            executor=self._update_conversation_triage,
            replay_message='Replayed AI triage request',
        )

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/tags', type='http', auth='public', csrf=False, methods=['PUT'])
    def v3_conversation_tags(self, conversation_id, **kwargs):
        del kwargs
        return self._handle_v3_route(
            action_type='tag_replace',
            conversation_id=conversation_id,
            executor=self._replace_conversation_tags,
            replay_message='Replayed AI tag request',
        )

    # ── GET: list tags for a conversation ──────────────────────────────────

    @http.route('/dac_erp/api/v3/conversations/<int:conversation_id>/tags', type='http', auth='public', csrf=False, methods=['GET'])
    def v3_conversation_tags_get(self, conversation_id, **kwargs):
        """Return the current Pancake tags on a conversation."""
        del kwargs
        try:
            self._ensure_v3_write_api_key()
            env = self._get_v3_write_env()
            conversation = self._find_v3_conversation_or_404(conversation_id, env=env)
            tags = conversation.sudo().pancake_tag_ids
            tag_list = [
                {
                    'id': t.id,
                    'tag_fm_id': t.tag_fm_id,
                    'name': t.name,
                    'odoo_tag_code': t.odoo_tag_code or False,
                    'managed_by_ai': bool(t.managed_by_ai),
                    'active': bool(t.active),
                }
                for t in tags
            ]
            return self._raw_json_response({
                'success': True,
                'conversation_id': conversation_id,
                'tags': tag_list,
                'tags_count': len(tag_list),
            })
        except PermissionError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=401)
        except LookupError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=404)
        except Exception as exc:
            _logger.error("Error in GET conversation tags %s: %s", conversation_id, exc, exc_info=True)
            return self._write_json_response(success=False, message="Error fetching conversation tags", error=str(exc), status_code=500)

    # ── GET: list all available tags for a page ─────────────────────────────

    @http.route('/dac_erp/api/v3/tags', type='http', auth='public', csrf=False, methods=['GET'])
    def v3_tags_list(self, **kwargs):
        """Return available page.fm.tag records, optionally filtered by page_id or scope.

        Query params:
          page_id (int)   — filter by page.fm.page.id
          scope           — 'ai_managed' to return only managed_by_ai=True tags
        """
        try:
            self._ensure_v3_write_api_key()
            env = self._get_v3_write_env()
            Tag = env['page.fm.tag'].sudo()

            page_id_raw = kwargs.get('page_id')
            scope = (kwargs.get('scope') or '').strip()

            domain = [('active', '=', True)]
            if page_id_raw:
                try:
                    domain.append(('page_id', '=', int(page_id_raw)))
                except (ValueError, TypeError):
                    return self._write_json_response(success=False, message="page_id must be an integer", error="invalid_page_id", status_code=400)
            if scope == 'ai_managed':
                domain.append(('managed_by_ai', '=', True))

            tags = Tag.search(domain, order='page_id, name')
            tag_list = [
                {
                    'id': t.id,
                    'page_id': t.page_id.id,
                    'page_name': t.page_id.name,
                    'tag_fm_id': t.tag_fm_id,
                    'name': t.name,
                    'odoo_tag_code': t.odoo_tag_code or False,
                    'odoo_tag_label': t.odoo_tag_label or False,
                    'managed_by_ai': bool(t.managed_by_ai),
                    'fm_color_hex': t.fm_color_hex or False,
                    'active': bool(t.active),
                }
                for t in tags
            ]
            return self._raw_json_response({
                'success': True,
                'tags': tag_list,
                'tags_count': len(tag_list),
                'filters': {'page_id': page_id_raw, 'scope': scope or None},
            })
        except PermissionError as exc:
            return self._write_json_response(success=False, message=str(exc), error=str(exc), status_code=401)
        except Exception as exc:
            _logger.error("Error in GET /v3/tags: %s", exc, exc_info=True)
            return self._write_json_response(success=False, message="Error fetching tags", error=str(exc), status_code=500)
