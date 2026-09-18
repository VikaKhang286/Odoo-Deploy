# TASK.md — Odoo Antigravity Sprint Backlog

> Theo dõi tasks hiện tại, priorities, và progress.
> Last updated: 2026-07-08

---

## 🚨 Critical / P0

### Đang thực hiện

| Task | Module | Ghi chú |
|------|--------|---------|
| Hoàn thiện `quick_complete_wizard` | dac_erp | Batch complete orders |
| Fix sale order workflow states | dac_erp | Theo commit history |

### Chưa bắt đầu

| Task | Module | Priority |
|------|--------|----------|
| Regression test cho DANGER_ZONES | dac_erp | CRITICAL - chạy trước mọi thay đổi |
| Audit `page.fm.conversation` ACL | dac_erp | Known gap từ OPEN_QUESTIONS |

---

## 📋 High / P1

### dac_erp

- [ ] Thêm unit tests cho `sale.order.workflow`
- [ ] Hoàn thiện `QuickCompleteWizard` flow
- [ ] Test batch action buttons (pancake button)
- [ ] Kiểm tra `dac_skip_task_sync` / `dac_skip_order_sync` guards

### dac_attendance

- [ ] Review dashboard UI (`manager_dashboard.xml`, `employee_dashboard.xml`)
- [ ] Test attendance calculation với edge cases (part-time, quên checkout)

### dac_openclaw

- [ ] Review OpenClaw task sync flows
- [ ] Test webhook delivery với retry logic

---

## 📝 Medium / P2

### dac_erp

- [ ] Thêm `company_id` field validation (ensure NOT added - multi-company disabled)
- [ ] Review tất cả `sudo()` usages - đảm bảo có comments
- [ ] Tạo test coverage report

### dac_openclaw

- [ ] Review MCP log models - đảm bảo Manager read-only (có chủ đích)
- [ ] Test message sync với large volumes

### Documentation

- [ ] Cập nhật ARCHITECTURE.md với latest changes
- [ ] Cập nhật DANGER_ZONES.md line numbers sau refactor
- [ ] Hoàn thiện MODULE_REGISTRY.md

---

## 📖 Low / P3

- [ ] Review tất cả external ID patterns (`*_fm_id`)
- [ ] Tạo integration test suite
- [ ] Performance audit: identify N+1 queries
- [ ] Security audit: review tất cả public routes

---

## ✅ Recently Completed

| Date | Task | Module |
|------|------|--------|
| 2026-07-08 | Tách root app menus sang `menu_roots.xml` | dac_erp |
| 2026-07-08 | Pancake column + inline status dropdown | dac_erp |
| 2026-07-08 | Attendance system với BXH, phép lũy kế | dac_attendance |

---

## 🔄 Recurring Tasks

| Task | Frequency | Owner |
|------|-----------|-------|
| Backup production | Daily | CI/CD |
| Review error logs | Weekly | Dev team |
| Update dependencies | Monthly | Dev team |
| Security patch review | As released | Dev team |

---

## 📊 Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Test coverage | >60% | ~30% |
| DANGER_ZONES regression tests | 100% | 0% |
| Response time (MCP) | <500ms | N/A |
| Uptime | >99.5% | N/A |

---

## 🔗 Linked Documents

- [PLANNING.md](PLANNING.md) — Architecture & rules
- [KNOWLEDGE.md](KNOWLEDGE.md) — Accumulated insights
- [docs/SPRINT_BACKLOG.md](docs/SPRINT_BACKLOG.md) — Detailed sprint backlog

---

*Format: `- [ ]` = chưa làm, `- [x]` = hoàn thành, `- [~]` = in progress*
