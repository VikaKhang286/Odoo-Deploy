# PLANNING.md — Odoo Antigravity

**Architecture, Design Principles, và Absolute Rules cho DAC ERP**

> File này được đọc bởi Claude Code khi bắt đầu session để đảm bảo phát triển nhất quán và chất lượng cao.

---

## 🏗️ Tầm nhìn dự án

Custom Odoo **18.0** ERP cho công ty in/thiết kế DAC. Quản lý đơn hàng, workflow đa-vai-trò
(sale → design → production → delivery), hóa đơn/thanh toán, tích hợp Pancake CRM + Page.fm
messaging + OpenClaw AI agent.

### Core Modules (9 addons)
| Module | Mục đích |
|--------|----------|
| `dac_erp` | Core: Sale orders, workflow, invoices |
| `dac_openclaw` | OpenClaw AI agent integration |
| `dac_attendance` | Chấm công, nghỉ phép, BXH |
| `CRM_DAC` | CRM với Page.fm messenger sync |
| `dac_report` | Báo cáo |
| `Chameleon` | OWL/Web client utilities |
| `sale_ai_invoice_reader` | AI đọc hóa đơn |

---

## 🧭 Nguyên tắc cốt lõi (SuperClaude-Inspired)

### 1. Evidence-Based Development
**Không đoán** — luôn xác minh với nguồn chính:
- Sử dụng Odoo official docs để kiểm tra API
- Sử dụng `rg`/`grep` để xác minh code hiện tại
- Chạy test trước khi kết luận "đã fix"

### 2. Confidence-First Implementation ⭐

**Kiểm tra confidence TRƯỚC KHI bắt đầu:**

| Confidence | Hành động |
|------------|-----------|
| **≥90%** | Tiến hành implement |
| **70-89%** | Trình bày alternatives, tiếp tục điều tra |
| **<70%** | **DỪNG** — hỏi câu hỏi, điều tra thêm |

**ROI**: Spend 100-200 tokens để tiết kiệm 5,000-50,000 tokens khi đi sai hướng.

### 3. Parallel-First Execution

**Pattern Wave → Checkpoint → Wave:**

```
Wave 1: [Read file1, Read file2, Read file3] (song song)
  → Checkpoint: Phân tích tất cả files cùng lúc
Wave 2: [Edit file1, Edit file2, Edit file3] (song song)
```

**Lợi ích**: 3.5x nhanh hơn sequential.

**Khi nào dùng:**
- ✅ Đọc nhiều files độc lập
- ✅ Batch transformations
- ✅ Grep across directories

**Khi KHÔNG dùng:**
- ❌ Operations có dependencies
- ❌ Sequential analysis cần build context

### 4. Token Efficiency

| Độ phức tạp | Token budget | Ví dụ |
|-------------|--------------|-------|
| Simple | ~200 | Typo fix |
| Medium | ~1,000 | Bug fix nhỏ |
| Complex | ~2,500 | Feature mới |

### 5. No Hallucinations

**4 Câu hỏi kiểm tra:**
1. Tất cả tests đang pass? (show output)
2. Tất cả requirements đã meet? (list items)
3. Không có assumptions không verify? (show docs)
4. Có evidence không? (test results, code changes)

**7 Red Flags:**
- "Tests pass" không có output
- "Everything works" không có evidence
- "Implementation complete" với failing tests
- Bỏ qua error messages
- Bỏ qua warnings
- Che giấu failures
- Ngôn ngữ "Probably works"

---

## 📜 Absolute Rules

### Docker & Container

1. **Container name thật**: `odoo-local-web` (KHÔNG phải `odoo-antigravity-web-1`)
2. **Database test**: `demodata`
3. **Database production**: `production_crm` — **KHÔNG BAO GIỜ sửa trực tiếp**

### Python / Odoo Development

1. **Sau mọi thay đổi Python/XML/CSV**: Upgrade module
   ```bash
   docker exec odoo-local-web odoo -d demodata -u MODULE --stop-after-init
   ```

2. **Batch operations**: `Model.create([...])` và `records.write({})` — không loop-create

3. **`sudo()` usage**:
   - Chỉ trong cron/webhook/wizard
   - LUÔN comment lý do
   - KHÔNG dùng trong `create/write/unlink` override

### Security

1. **Route inbound**: Phải xác thực secret/HMAC
   - Ngoại lệ: `/dac_erp/pancake_webhook` (tắt auth có chủ đích)
2. **Public export route**: `sudo()` theo thiết kế
3. **Model mới**: ACL cho Manager + `base.group_system`

### Integrations

1. **Idempotency**: Search `_fm_id` trước mọi inbound create
2. **Outbound HTTP**: `timeout=(10, 30)`, catch `requests.exceptions.RequestException`
3. **Cron**: Không raise — set `state='failed'` + error_message

---

## 🔧 Development Workflow

### Khi nhận task mới:

1. **Investigation Phase**:
   - Đọc CLAUDE.md, PLANNING.md
   - Kiểm tra duplicates (`rg` trong code)
   - Check DANGER_ZONES.md nếu sửa critical points
   - **Confidence check: ≥90% mới proceed**

2. **Implementation Phase**:
   - Tạo branch: `git checkout -b feature/feature-name`
   - Implement theo rules trong `.claude/rules/`
   - Chạy upgrade: `docker exec odoo-local-web odoo -d demodata -u MODULE --stop-after-init`

3. **Validation Phase**:
   - Tất cả tests pass?
   - Tất cả requirements met?
   - Không có breaking changes ở DANGER_ZONES?
   - Có evidence không?

4. **Documentation Phase**:
   - Update relevant docs nếu cần
   - Update CHANGELOG nếu public API thay đổi

### Khi fix Bug:

1. **Root Cause Analysis**:
   - Reproduce bug
   - Identify root cause (KHÔNG phải symptom)
   - Check KNOWLEDGE.md cho patterns tương tự

2. **Fix Implementation**:
   - Write failing test để reproduce bug
   - Implement fix
   - Verify test passes

3. **Prevention**:
   - Add regression test
   - Update KNOWLEDGE.md nếu cần

---

## 📂 Key Documentation Files

| File | Mục đích |
|------|----------|
| `CLAUDE.md` | Project context, quick reference |
| `PLANNING.md` | Architecture, absolute rules (file này) |
| `TASK.md` | Current tasks, sprint backlog |
| `KNOWLEDGE.md` | Accumulated insights, best practices |
| `.claude/rules/models.md` | ORM conventions |
| `.claude/rules/views.md` | View/XML conventions |
| `.claude/rules/security.md` | ACL/security conventions |
| `.claude/rules/integrations.md` | Pancake/Page.fm integration |
| `.claude/rules/tests.md` | Testing conventions |

---

## ⚠️ Danger Zones

> Sửa các điểm này → chạy `regression-checker` trước.

| File:line | Method | Rủi ro |
|-----------|--------|--------|
| `sale_order.py:768` | `sale.order.create()` | Mất event `order.created` sang OpenClaw |
| `sale_order.py:552` | `sale.order.write()` | Vòng lặp write↔task, mất flag `dac_skip_task_sync` |
| `dac_work_task.py:161/168` | `dac.work.task.create/write()` | Mất notification, vòng lặp sync ngược |
| `account_move.py:211` | `account.move.write()` | Sai trigger cọc/hoàn tất |
| `account_move.py:13/36/59` | `account.move.read/unlink` | Security breach |

---

*Document này được update khi có architectural decisions mới.*
*Last updated: 2026-07-08*
