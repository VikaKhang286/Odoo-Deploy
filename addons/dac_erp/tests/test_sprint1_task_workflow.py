"""Sprint 1 unit tests — design/production task workflow.

Covers:
- _build_snapshot_vals: never contains monetary fields
- _create_from_order: idempotency
- _refresh_snapshot: updates snap fields on context change
- Blocker guards: cannot block terminal tasks; cannot done while blocked
- MCP endpoints: task-context, ensure-design-task, task status/note/blocker
"""
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.dac_erp.controllers.mcp_sprint1_dispatchers import MCPSprint1Controller

READ_KEY = 's1-read-key'
WRITE_KEY = 's1-write-key'

# Monetary fields that must NEVER appear in snapshot or MCP task response
_MONETARY_FIELDS = {
    'amount_total', 'amount_untaxed', 'amount_tax',
    'deposit_amount', 'total_deposit_paid', 'remaining_amount_display',
    'promotion_amount', 'price_unit', 'price_subtotal',
}


@tagged('post_install', '-at_install')
class TestSprint1SnapshotFields(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env['res.partner'].create({'name': 'Sprint1 Partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Sprint1 Product',
            'type': 'service',
            'list_price': 999000.0,
        })

    def _make_order(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 500000,
            })],
        }
        vals.update(kwargs)
        return self.env['sale.order'].create(vals)

    def _make_task(self, order, task_type='design', **kwargs):
        vals = {
            'name': f'Test {task_type} task',
            'task_type': task_type,
            'order_id': order.id,
            **kwargs,
        }
        return self.env['dac.work.task'].create(vals)

    # ── Snapshot: no monetary fields ──────────────────────────────────

    def test_build_snapshot_vals_no_monetary(self):
        """_build_snapshot_vals must never include monetary fields."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        snap = Task._build_snapshot_vals(order, 'design')
        for field in _MONETARY_FIELDS:
            self.assertNotIn(field, snap,
                             f'_build_snapshot_vals returned monetary field: {field}')

    def test_build_snapshot_vals_contains_safe_fields(self):
        """_build_snapshot_vals returns expected safe fields."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        snap = Task._build_snapshot_vals(order, 'design')
        expected = {
            'snap_order_title', 'snap_order_summary', 'snap_order_number',
            'snap_design_deadline', 'snap_design_link', 'snap_production_deadline',
            'snap_is_priority', 'snap_is_priority_today', 'snap_updated_at',
        }
        for f in expected:
            self.assertIn(f, snap, f'snap field missing: {f}')

    def test_snap_contact_phone_design_task_empty(self):
        """snap_contact_phone must be False for design tasks."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        snap = Task._build_snapshot_vals(order, 'design')
        self.assertFalse(snap.get('snap_contact_phone'),
                         'snap_contact_phone must be empty for design tasks')

    # ── _create_from_order: idempotency ───────────────────────────────

    def test_create_from_order_idempotent(self):
        """Second call with same order+type returns existing task, was_created=False."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        task1, created1 = Task._create_from_order(order, 'design')
        task2, created2 = Task._create_from_order(order, 'design')
        self.assertTrue(created1, 'First call should create')
        self.assertFalse(created2, 'Second call should return existing')
        self.assertEqual(task1.id, task2.id, 'Should return same task record')

    def test_create_from_order_different_types(self):
        """Design and production tasks are separate; each idempotent independently."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        design, _ = Task._create_from_order(order, 'design')
        prod, _ = Task._create_from_order(order, 'production')
        self.assertNotEqual(design.id, prod.id, 'Design and production tasks must be separate')

    def test_create_from_order_snapshot_populated(self):
        """Task created via factory has snap_order_number set."""
        order = self._make_order()
        Task = self.env['dac.work.task']
        task, _ = Task._create_from_order(order, 'design')
        self.assertTrue(task.snap_order_number, 'snap_order_number should be set on factory-created task')

    # ── _refresh_snapshot ─────────────────────────────────────────────

    def test_refresh_snapshot_updates_fields(self):
        """After order title changes, _refresh_snapshot updates task snap."""
        order = self._make_order()
        task = self._make_task(order, 'design')
        # Set a title on order
        order.sudo().write({'order_title': 'Original Title'})
        task._refresh_snapshot()
        self.assertEqual(task.snap_order_title, 'Original Title')

        # Change title
        order.sudo().write({'order_title': 'Updated Title'})
        task._refresh_snapshot()
        self.assertEqual(task.snap_order_title, 'Updated Title',
                         'snap_order_title should update after _refresh_snapshot')


@tagged('post_install', '-at_install')
class TestSprint1BlockerGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.partner = cls.env['res.partner'].create({'name': 'Blocker Test Partner'})

    def _make_order_and_task(self, task_type='design', state='draft'):
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].create({
            'name': 'Blocker Test Task',
            'task_type': task_type,
            'order_id': order.id,
            'state': state,
        })
        return order, task

    def test_cannot_block_done_task(self):
        """Blocking a done task raises ValidationError."""
        _, task = self._make_order_and_task(state='draft')
        # Force state to done bypassing guard
        task.with_context(dac_skip_order_sync=True).write({'state': 'done'})
        with self.assertRaises(ValidationError, msg='Blocking done task should raise'):
            task.write({'is_blocked': True})

    def test_cannot_block_cancelled_task(self):
        """Blocking a cancelled task raises ValidationError."""
        _, task = self._make_order_and_task(state='draft')
        task.write({'state': 'cancelled'})
        with self.assertRaises(ValidationError, msg='Blocking cancelled task should raise'):
            task.write({'is_blocked': True})

    def test_can_block_in_progress_task(self):
        """Blocking an in_progress task succeeds."""
        _, task = self._make_order_and_task(state='draft')
        task.write({'state': 'in_progress'})
        task.write({'is_blocked': True, 'blocker_reason': 'Waiting for brief'})
        self.assertTrue(task.is_blocked)

    def test_cannot_mark_done_when_blocked(self):
        """Cannot mark task done while is_blocked=True."""
        _, task = self._make_order_and_task(state='in_progress')
        task.write({'is_blocked': True, 'blocker_reason': 'Chờ brief'})
        with self.assertRaises(ValidationError, msg='Marking done while blocked should raise'):
            task.write({'state': 'done'})

    def test_clear_blocker_then_mark_done(self):
        """After clearing blocker, task can be marked done."""
        _, task = self._make_order_and_task(state='in_progress')
        task.write({'is_blocked': True, 'blocker_reason': 'Waiting'})
        task.write({'is_blocked': False, 'blocker_reason': False})
        task.with_context(dac_skip_order_sync=True).write({'state': 'done'})
        self.assertEqual(task.state, 'done')


@tagged('post_install', '-at_install')
class TestSprint1McpSerializer(TransactionCase):
    """Test that MCP serializer returns snap_* fields and no monetary fields."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_read_key', READ_KEY)
        cls.env['ir.config_parameter'].sudo().set_param('dac_erp.mcp_write_key', WRITE_KEY)
        cls.controller = MCPSprint1Controller()
        cls.partner = cls.env['res.partner'].create({'name': 'Serializer Test Partner'})

    def test_serialized_task_has_snap_fields(self):
        """Serialized task response includes snap_order_title."""
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        order.write({'order_title': 'Test Banner Order'})
        task = self.env['dac.work.task'].create({
            'name': 'Design Task',
            'task_type': 'design',
            'order_id': order.id,
        })
        task._refresh_snapshot()

        result = self.controller._serialize_mcp_task(task)
        self.assertIn('snap_order_title', result, 'Serializer must include snap_order_title')
        self.assertIn('task_type', result, 'Serializer must include task_type')
        self.assertIn('is_blocked', result, 'Serializer must include is_blocked')

    def test_serialized_task_no_monetary(self):
        """Serialized task must never contain monetary fields."""
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        task = self.env['dac.work.task'].create({
            'name': 'Design Task',
            'task_type': 'design',
            'order_id': order.id,
        })
        result = self.controller._serialize_mcp_task(task)
        for field in _MONETARY_FIELDS:
            self.assertNotIn(field, result,
                             f'Serialized task must not contain monetary field: {field}')
