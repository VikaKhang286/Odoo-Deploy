import json
import os
from datetime import datetime, timedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp import MCPReadController


@tagged('post_install', '-at_install')
class TestMcpPhase4CHardening(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = MCPReadController()
        cls.repo_root = '/mnt/project'
        cls.read_key = 'mcp-read-test-key'
        cls.write_key = 'mcp-write-test-key'

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dac_erp.mcp_read_key', self.read_key)
        icp.set_param('dac_erp.mcp_write_key', self.write_key)
        icp.set_param('dac_erp.mcp.customer_care.sla_minutes_default', '60')
        icp.set_param('dac_erp.mcp.customer_care.urgent_minutes_default', '120')
        icp.set_param('dac_erp.mcp.customer_care.default_policy', 'standard')
        icp.set_param('dac_erp.mcp.activity_type.todo_xmlid', 'mail.mail_activity_data_todo')
        icp.set_param('dac_erp.mcp.activity_type.call_xmlid', 'mail.mail_activity_data_call')
        icp.set_param('dac_erp.mcp.activity_type.followup_xmlid', 'dac_erp.mail_activity_type_cskh_followup')
        icp.set_param('dac_erp.mcp.conversation.allow_internal_read', 'True')
        icp.set_param('dac_erp.mcp.order.money_change_confirmation_required', 'True')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_enabled', 'False')
        icp.set_param('dac_erp.mcp.customer_care.auto_run_cron_enabled', 'False')
        icp.set_param('dac_erp.mcp.max_batch_limit_default', '100')
        icp.set_param('dac_erp.mcp.auto_run_min_interval_seconds', '60')

    def _headers(self, api_key):
        return {'X-MCP-API-KEY': api_key}

    def _run_health(self, api_key=None):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_health,
            env=self.env,
            headers=self._headers(api_key) if api_key else {},
        )

    def _run_capabilities(self, api_key=None):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_capabilities,
            env=self.env,
            headers=self._headers(api_key) if api_key else {},
        )

    def _run_runs_list(self, api_key=None, **params):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_auto_run_runs,
            env=self.env,
            headers=self._headers(api_key) if api_key else {},
            **params
        )

    def _run_run_detail(self, run_id, api_key=None):
        return self.controller._run_mcp_handler(
            self.controller._dispatch_mcp_customer_care_auto_run_report,
            run_id,
            env=self.env,
            headers=self._headers(api_key) if api_key else {},
        )

    def _create_auto_run_log(self, request_id, status='success', dry_run=True, mode='manual_api', summary=None, response_snapshot=None, started_at=None):
        started_at = started_at or datetime.utcnow().replace(microsecond=0)
        summary = summary or {
            'evaluated_count': 1,
            'actionable_count': 1,
            'followup_created_count': 0,
            'note_created_count': 0,
            'triage_updated_count': 0,
            'skipped_count': 0,
            'failed_count': 0,
        }
        response_snapshot = response_snapshot or {
            'request_id': request_id,
            'summary': summary,
            'items': [{'conversation_id': 1, 'status': 'would_execute'}],
        }
        return self.env['dac_erp.mcp.auto.run.log'].create({
            'name': 'Phase4C Run %s' % request_id,
            'request_id': request_id,
            'payload_fingerprint': 'fp-%s' % request_id,
            'mode': mode,
            'dry_run': dry_run,
            'policy': 'standard',
            'sla_minutes': 60,
            'urgent_minutes': 120,
            'batch_limit': 50,
            'filters_json': json.dumps({'owner_id': 17}),
            'request_payload_json': json.dumps({'request_id': request_id, 'items': ['big-payload-hidden']}),
            'response_snapshot_json': json.dumps(response_snapshot),
            'summary_json': json.dumps(summary),
            'item_results_json': json.dumps(response_snapshot['items']),
            'status': status,
            'agent_name': 'OpenClaw',
            'model_name': 'gpt-5',
            'reason': 'scheduled_customer_care_auto_run',
            'started_at': started_at,
            'finished_at': started_at + timedelta(seconds=2),
            'duration_ms': 2000,
        })

    def test_health_auth_and_warning_behavior(self):
        payload, status_code = self._run_health()
        self.assertEqual(status_code, 401)
        self.assertEqual(payload['error']['code'], 'missing_api_key')

        payload, status_code = self._run_health('wrong-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        for key in (self.read_key, self.write_key):
            payload, status_code = self._run_health(key)
            self.assertEqual(status_code, 200)
            self.assertTrue(payload['ok'])
            self.assertIn('service', payload['data'])

        health_json = json.dumps(payload)
        self.assertNotIn(self.read_key, health_json)
        self.assertNotIn(self.write_key, health_json)

        self.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', '')
        payload, status_code = self._run_health(self.read_key)
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['status'], 'warning')
        self.assertIn('mcp_write_key_missing', payload['data']['warnings'])
        self.assertFalse(payload['data']['config']['write_key_configured'])
        self.assertNotIn(self.read_key, json.dumps(payload))

    def test_capabilities_manifest(self):
        payload, status_code = self._run_capabilities(self.read_key)
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        capabilities_json = json.dumps(payload)
        self.assertNotIn(self.read_key, capabilities_json)
        self.assertNotIn(self.write_key, capabilities_json)

        tools = {tool['name']: tool for tool in payload['data']['tools']}
        self.assertIn('customer_care_auto_run', tools)
        self.assertIn('mcp_health', tools)
        self.assertIn('mcp_capabilities', tools)
        self.assertIn('customer_care_auto_run_runs', tools)
        self.assertIn('create_order', tools)
        self.assertIn('update_order', tools)
        self.assertIn('confirm_final_payment', tools)
        self.assertIn('list_internal_conversations', tools)
        self.assertTrue(tools['create_order']['requires_employee_confirmation'])
        self.assertTrue(tools['update_order']['requires_employee_confirmation'])
        self.assertFalse(tools['confirm_final_payment']['safe_for_auto_mode'])
        self.assertFalse(tools['list_internal_conversations']['safe_for_auto_mode'])

    def test_auto_run_run_list_and_detail(self):
        base_dt = datetime.utcnow().replace(microsecond=0)
        oldest = self._create_auto_run_log('phase4c-run-001', status='replayed', dry_run=True, started_at=base_dt)
        middle = self._create_auto_run_log('phase4c-run-002', status='success', dry_run=True, started_at=base_dt + timedelta(minutes=1))
        newest = self._create_auto_run_log('phase4c-run-003', status='failed', dry_run=False, started_at=base_dt + timedelta(minutes=2))
        self.assertTrue(newest.id > middle.id > oldest.id)

        payload, status_code = self._run_runs_list(self.read_key)
        self.assertEqual(status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertGreaterEqual(payload['count'], 3)
        self.assertEqual(payload['items'][0]['run_id'], newest.id)
        self.assertNotIn('request_payload_json', payload['items'][0])
        self.assertNotIn('item_results_json', payload['items'][0])

        payload, status_code = self._run_runs_list(self.write_key, dry_run='1')
        self.assertEqual(status_code, 200)
        self.assertTrue(all(item['dry_run'] for item in payload['items']))

        payload, status_code = self._run_runs_list(self.read_key, status='failed')
        self.assertEqual(status_code, 200)
        self.assertTrue(all(item['status'] == 'failed' for item in payload['items']))

        payload, status_code = self._run_runs_list(self.read_key, limit='999')
        self.assertEqual(status_code, 200)
        self.assertLessEqual(payload['count'], 100)

        payload, status_code = self._run_runs_list('wrong-key')
        self.assertEqual(status_code, 403)
        self.assertEqual(payload['error']['code'], 'invalid_api_key')

        payload, status_code = self._run_run_detail(newest.id, self.read_key)
        self.assertEqual(status_code, 200)
        self.assertEqual(payload['data']['run_id'], newest.id)
        self.assertIn('summary', payload['data'])
        self.assertIn('items', payload['data'])

    def test_docs_exist_and_tool_catalog_mentions_new_endpoints(self):
        expected_files = [
            'docs/OPENCLAW_MCP_AGENT_POLICY.md',
            'docs/OPENCLAW_MCP_STAGING_SMOKE_TEST_CHECKLIST.md',
            'docs/OPENCLAW_MCP_PRODUCTION_RUNBOOK.md',
        ]
        for relative_path in expected_files:
            absolute_path = os.path.join(self.repo_root, relative_path)
            self.assertTrue(os.path.exists(absolute_path), '%s should exist' % relative_path)

        tool_catalog_path = os.path.join(self.repo_root, 'docs/OPENCLAW_MCP_TOOL_CATALOG.md')
        with open(tool_catalog_path, 'r', encoding='utf-8') as handle:
            catalog_text = handle.read()
        self.assertIn('`mcp_health`', catalog_text)
        self.assertIn('`mcp_capabilities`', catalog_text)
        self.assertIn('`customer_care_auto_run_runs`', catalog_text)
        self.assertIn('`customer_care_auto_run_report`', catalog_text)
