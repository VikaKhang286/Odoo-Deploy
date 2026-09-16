from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('standard', 'at_install')
class TestPancakePageSelection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Page = cls.env['page.fm.page']
        cls.Conversation = cls.env['page.fm.conversation']
        cls.Job = cls.env['pancake.message.sync.job']
        cls.Task = cls.env['pancake.message.sync.task']
        cls.BulkDashboard = cls.env['pancake.bulk.sync.dashboard']
        cls.page_a = cls.Page.create({
            'name': 'Bulk Selected Page A',
            'page_fm_id_str': 'bulk-selected-page-a',
            'sync_enabled': True,
            'active': True,
        })
        cls.page_b = cls.Page.create({
            'name': 'Bulk Selected Page B',
            'page_fm_id_str': 'bulk-selected-page-b',
            'sync_enabled': False,
            'active': True,
        })

    def _open_dashboard(self):
        return self.BulkDashboard._get_dashboard_record()

    def test_dashboard_rebuilds_page_lines_from_active_pages(self):
        dashboard = self._open_dashboard()
        lines = dashboard.page_line_ids.filtered(lambda line: line.page_id in (self.page_a | self.page_b))

        self.assertEqual(len(lines), 2)
        line_a = lines.filtered(lambda line: line.page_id == self.page_a)
        line_b = lines.filtered(lambda line: line.page_id == self.page_b)
        self.assertTrue(line_a)
        self.assertTrue(line_a.sync_enabled)
        self.assertTrue(line_b)
        self.assertFalse(line_b.sync_enabled)

    def test_action_save_configuration_writes_page_line_selection_back_to_pages(self):
        dashboard = self._open_dashboard()
        line_a = dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_a)
        line_b = dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_b)

        line_a.sync_enabled = False
        line_b.sync_enabled = True
        dashboard.action_save_configuration()

        self.page_a.invalidate_recordset()
        self.page_b.invalidate_recordset()
        self.assertFalse(self.page_a.sync_enabled)
        self.assertTrue(self.page_b.sync_enabled)

    def test_action_start_bulk_sync_creates_tasks_only_for_selected_pages(self):
        dashboard = self._open_dashboard()
        dashboard.page_line_ids.write({'sync_enabled': False})
        line_a = dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_a)
        line_b = dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_b)
        line_a.sync_enabled = True
        line_b.sync_enabled = False

        with patch.object(type(self.Page), '_check_main_access_token', return_value={'status': 'valid', 'message': 'ok', 'page_count': 2}), \
             patch.object(type(self.Job), '_get_running_job', return_value=False), \
             patch.object(type(self.Job), '_nudge_runner_cron', return_value=None):
            dashboard.action_start_bulk_sync()

        job = self.Job.search([], order='id desc', limit=1)
        self.assertTrue(job)
        self.assertEqual(job.sync_scope, 'selected_pages')
        self.assertEqual(job.selected_page_count, 1)
        self.assertEqual(job.task_ids.mapped('page_id').ids, [self.page_a.id])
        self.assertEqual(set(job.task_ids.mapped('task_type')), {'page_scan'})

    def test_action_start_bulk_sync_only_retires_legacy_full_sync_cron(self):
        dashboard = self._open_dashboard()
        dashboard.page_line_ids.write({'sync_enabled': False})
        line_a = dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_a)
        line_a.sync_enabled = True

        legacy_full_sync = self.env.ref('CRM_DAC.cron_pancake_full_sync')
        continuous_crons = [
            self.env.ref('CRM_DAC.cron_pancake_quick_sync'),
            self.env.ref('CRM_DAC.cron_pancake_smart_message_sync'),
            self.env.ref('CRM_DAC.cron_pancake_deep_sync_continuous'),
        ]
        legacy_full_sync.write({'active': True})
        for cron in continuous_crons:
            cron.write({'active': True})

        with patch.object(type(self.Page), '_check_main_access_token', return_value={'status': 'valid', 'message': 'ok', 'page_count': 2}), \
             patch.object(type(self.Job), '_get_running_job', return_value=False), \
             patch.object(type(self.Job), '_nudge_runner_cron', return_value=None):
            dashboard.action_start_bulk_sync()

        self.assertFalse(legacy_full_sync.active)
        self.assertTrue(all(cron.active for cron in continuous_crons))

    def test_manual_full_job_keeps_selected_page_snapshot_after_selection_changes(self):
        dashboard = self._open_dashboard()
        dashboard.page_line_ids.write({'sync_enabled': False})
        dashboard.page_line_ids.filtered(lambda line: line.page_id == self.page_a).sync_enabled = True

        with patch.object(type(self.Page), '_check_main_access_token', return_value={'status': 'valid', 'message': 'ok', 'page_count': 2}), \
             patch.object(type(self.Job), '_get_running_job', return_value=False), \
             patch.object(type(self.Job), '_nudge_runner_cron', return_value=None):
            dashboard.action_start_bulk_sync()

        job = self.Job.search([], order='id desc', limit=1)
        self.page_a.write({'sync_enabled': False})
        self.page_b.write({'sync_enabled': True})

        self.assertEqual(job._selected_page_ids(), [self.page_a.id])
        self.assertEqual(job.selected_page_count, 1)
        self.assertEqual(job.task_ids.mapped('page_id').ids, [self.page_a.id])

    def test_action_sync_messages_rejects_conversation_outside_job_scope(self):
        self.env['ir.config_parameter'].sudo().set_param('page_fm.access_token', 'dummy-token')
        conversation = self.Conversation.create({
            'conversation_fm_id': 'bulk-scope-outside-conversation',
            'page_fm_page_id': self.page_b.id,
        })

        result = conversation.action_sync_messages(
            return_stats=True,
            allowed_page_ids=[self.page_a.id],
            sync_scope='selected_pages',
        )

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'page_outside_job_scope')
