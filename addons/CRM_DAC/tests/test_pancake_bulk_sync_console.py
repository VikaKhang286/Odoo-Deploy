from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('standard', 'at_install')
class TestPancakeBulkSyncConsole(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Page = cls.env['page.fm.page']
        cls.Job = cls.env['pancake.message.sync.job']
        cls.Task = cls.env['pancake.message.sync.task']
        cls.JobLog = cls.env['pancake.message.sync.log']
        cls.BulkDashboard = cls.env['pancake.bulk.sync.dashboard']
        cls.page = cls.Page.create({
            'name': 'Bulk Console Page',
            'page_fm_id_str': 'bulk-console-page',
            'active': True,
            'sync_enabled': True,
        })

    def setUp(self):
        super().setUp()
        self.Job.search([('state', 'in', ['running', 'stopping'])]).write({
            'state': 'cancelled',
            'phase': 'done',
            'finished_at': fields.Datetime.now(),
            'stop_requested': False,
            'runner_claim_token': False,
            'runner_claimed_at': False,
        })

    def test_live_snapshot_uses_fast_poll_while_running(self):
        job = self.Job.create({
            'name': 'Running Queue Job',
            'state': 'running',
            'phase': 'page_scan',
            'started_at': fields.Datetime.now(),
        })
        job._refresh_runtime_metrics()
        dashboard = self.BulkDashboard._get_dashboard_record()

        payload = dashboard.get_live_bulk_sync_snapshot()

        self.assertEqual(payload['poll_seconds'], 2)
        self.assertIn('job', payload['sections'])
        self.assertIn('scope', payload['sections'])

    def test_live_snapshot_for_current_user_returns_idle_poll_when_no_running_job(self):
        dashboard = self.BulkDashboard._get_dashboard_record()
        payload = dashboard.get_live_bulk_sync_snapshot_for_current_user()

        self.assertTrue(payload['record_id'])
        self.assertGreaterEqual(payload['poll_seconds'], 15)
        self.assertIn('live_feed', payload['sections'])

    def test_report_snapshot_uses_idle_poll_30_seconds(self):
        dashboard = self.BulkDashboard._get_dashboard_record()

        payload = dashboard.get_bulk_sync_report_snapshot()

        self.assertEqual(payload['poll_seconds'], 30)
        self.assertIn('report_24h', payload['sections'])
        self.assertIn('history', payload['sections'])
        self.assertIn('Báo cáo 24 giờ qua', payload['sections']['report_24h'])
        self.assertIn('Báo cáo 7 ngày qua', payload['sections']['report_7d'])

    def test_live_snapshot_overview_uses_selected_page_kpis_not_job_24h(self):
        dashboard = self.BulkDashboard._get_dashboard_record()

        payload = dashboard.get_live_bulk_sync_snapshot()

        self.assertIn('Page đã chọn', payload['sections']['overview'])
        self.assertNotIn('Job 24h', payload['sections']['overview'])
        self.assertNotIn('Lỗi 24h', payload['sections']['overview'])

    def test_claim_next_runnable_job_recovers_stale_job(self):
        self.env.cr.execute(
            """
            UPDATE pancake_message_sync_job
               SET state = 'cancelled',
                   runner_claim_token = NULL,
                   runner_claimed_at = NULL,
                   stop_requested = FALSE
             WHERE state IN ('running', 'stopping')
            """
        )
        job = self.Job.create({
            'name': 'Stale Queue Job',
            'state': 'running',
            'phase': 'message_sync',
            'started_at': fields.Datetime.now() - timedelta(minutes=25),
            'last_heartbeat_at': fields.Datetime.now() - timedelta(minutes=25),
            'stale_timeout_minutes': 5,
        })

        claimed_job, claim_token = self.Job._claim_next_runnable_job()

        self.assertEqual(claimed_job, job)
        self.assertTrue(claim_token)
        self.assertEqual(job.resume_count, 1)
        self.assertTrue(self.JobLog.search_count([('job_id', '=', job.id), ('event_code', '=', 'job_resumed_after_stale')]))

    def test_message_task_timeout_is_retried_with_backoff(self):
        job = self.Job.create({
            'name': 'Retry Queue Job',
            'state': 'running',
            'phase': 'message_sync',
            'started_at': fields.Datetime.now(),
        })
        task = self.Task.create({
            'job_id': job.id,
            'task_type': 'message_sync',
            'page_id': self.page.id,
            'state': 'pending',
            'priority': 100,
            'next_run_at': fields.Datetime.now(),
            'max_attempts': 4,
        })
        task.write({
            'state': 'running',
            'attempt_count': 1,
            'started_at': fields.Datetime.now(),
            'claimed_at': fields.Datetime.now(),
            'claim_token': 'retry-claim',
        })

        with patch.object(type(task), '_run_message_sync', side_effect=ValueError('timeout while calling API')):
            result = task.run_claimed_task()

        job.invalidate_recordset()
        task.invalidate_recordset()
        self.assertEqual(result['status'], 'retry')
        self.assertEqual(task.state, 'retry')
        self.assertTrue(task.next_run_at)
        self.assertGreaterEqual(job.pending_task_count, 1)

    def test_message_task_business_error_fails_once_without_killing_job(self):
        job = self.Job.create({
            'name': 'Business Error Queue Job',
            'state': 'running',
            'phase': 'message_sync',
            'started_at': fields.Datetime.now(),
        })
        task = self.Task.create({
            'job_id': job.id,
            'task_type': 'message_sync',
            'page_id': self.page.id,
            'state': 'pending',
            'priority': 100,
            'next_run_at': fields.Datetime.now(),
            'max_attempts': 2,
        })
        task.write({
            'state': 'running',
            'attempt_count': 1,
            'started_at': fields.Datetime.now(),
            'claimed_at': fields.Datetime.now(),
            'claim_token': 'fail-claim',
        })

        with patch.object(type(task), '_run_message_sync', side_effect=ValueError('missing_page_access_token')):
            result = task.run_claimed_task()

        job.invalidate_recordset()
        task.invalidate_recordset()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(task.state, 'failed')
        self.assertEqual(job.state, 'running')
        self.assertGreaterEqual(job.failed_task_count, 1)

    def test_mark_done_uses_done_with_warnings_when_failed_tasks_exist(self):
        job = self.Job.create({
            'name': 'Warning Completion Job',
            'state': 'running',
            'phase': 'message_sync',
            'started_at': fields.Datetime.now(),
            'failed_task_count': 1,
        })

        job._mark_done('completed with warnings')

        self.assertEqual(job.state, 'done_with_warnings')

    def test_phase_progress_and_weighted_progress_follow_job_phases(self):
        job = self.Job.create({
            'name': 'Phase Progress Job',
            'state': 'running',
            'phase': 'page_scan',
            'started_at': fields.Datetime.now(),
        })
        page_two = self.Page.create({
            'name': 'Phase Progress Page 2',
            'page_fm_id_str': 'phase-progress-page-2',
            'active': True,
            'sync_enabled': True,
        })
        conversation = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'phase-progress-conversation',
            'page_fm_page_id': self.page.id,
        })
        conversation_two = self.env['page.fm.conversation'].create({
            'conversation_fm_id': 'phase-progress-conversation-2',
            'page_fm_page_id': page_two.id,
        })

        self.Task.create({
            'job_id': job.id,
            'task_type': 'page_scan',
            'page_id': self.page.id,
            'state': 'done',
            'priority': 300,
            'next_run_at': fields.Datetime.now(),
        })
        self.Task.create({
            'job_id': job.id,
            'task_type': 'page_scan',
            'page_id': page_two.id,
            'state': 'done',
            'priority': 300,
            'next_run_at': fields.Datetime.now(),
        })
        message_done = self.Task.create({
            'job_id': job.id,
            'task_type': 'message_sync',
            'page_id': self.page.id,
            'conversation_id': conversation.id,
            'state': 'done',
            'priority': 200,
            'next_run_at': fields.Datetime.now(),
        })
        message_pending = self.Task.create({
            'job_id': job.id,
            'task_type': 'message_sync',
            'page_id': page_two.id,
            'conversation_id': conversation_two.id,
            'state': 'pending',
            'priority': 200,
            'next_run_at': fields.Datetime.now(),
        })

        job._refresh_runtime_metrics()
        self.assertEqual(job.phase, 'message_sync')
        self.assertEqual(job.phase_done_count, 1)
        self.assertEqual(job.phase_total_count, 2)
        self.assertEqual(job.phase_progress_percent, 50.0)
        self.assertEqual(job.progress_percent, 62.5)

        message_pending.write({'state': 'done'})
        job._refresh_runtime_metrics()
        self.assertEqual(job.phase, 'finalize')
        self.assertEqual(job.phase_done_count, 0)
        self.assertEqual(job.phase_total_count, 1)
        self.assertEqual(job.phase_progress_percent, 0.0)
        self.assertEqual(job.progress_percent, 95.0)

        job.write({'state': 'done'})
        job._refresh_runtime_metrics()
        self.assertEqual(job.phase, 'done')
        self.assertEqual(job.phase_done_count, 1)
        self.assertEqual(job.phase_total_count, 1)
        self.assertEqual(job.phase_progress_percent, 100.0)
        self.assertEqual(job.progress_percent, 100.0)

    def test_cleanup_old_logs_keeps_recent_entries(self):
        old_log = self.JobLog.create({
            'job_id': self.Job.create({
                'name': 'Cleanup Job',
                'state': 'done',
                'phase': 'done',
            }).id,
            'level': 'info',
            'phase': 'done',
            'message': 'Old log',
        })
        old_log.sudo().write({'logged_at': fields.Datetime.now() - timedelta(days=40)})

        recent_log = self.JobLog.create({
            'job_id': self.Job.create({
                'name': 'Recent Cleanup Job',
                'state': 'done',
                'phase': 'done',
            }).id,
            'level': 'info',
            'phase': 'done',
            'message': 'Recent log',
        })

        removed_count = self.JobLog.cron_cleanup_old_logs()

        self.assertEqual(removed_count, 1)
        self.assertFalse(old_log.exists())
        self.assertTrue(recent_log.exists())
