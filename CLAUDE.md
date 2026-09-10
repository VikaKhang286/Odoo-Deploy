# CLAUDE.md — Odoo Antigravity

## Dự án là gì
Custom Odoo **18.0** ERP cho công ty in/thiết kế DAC. Quản lý đơn hàng, workflow đa-vai-trò
(sale → design → production → delivery), hóa đơn/thanh toán, tích hợp Pancake CRM + Page.fm
messaging + OpenClaw AI agent. **9 addon** (lõi: `dac_erp`).

> **Trước khi bắt đầu bất kỳ tác vụ nào:** đọc bảng "Đi đâu tìm gì" bên dưới rồi load đúng tài liệu.

---

## Đi đâu tìm gì

| Câu hỏi | File |
|---|---|
| Addon này làm gì? Phụ thuộc ai? | [`docs/MODULE_REGISTRY.md`](docs/MODULE_REGISTRY.md) |
| Luồng nghiệp vụ đi qua những file nào? | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **Điểm dễ vỡ — ĐỌC TRƯỚC KHI SỬA** | [`docs/DANGER_ZONES.md`](docs/DANGER_ZONES.md) |
| Chỗ bất thường / nghi nợ kỹ thuật | [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) |
| Quy ước model/field/ORM | [`.claude/rules/models.md`](.claude/rules/models.md) |
| Quy ước view/XML | [`.claude/rules/views.md`](.claude/rules/views.md) |
| Quy ước security/ACL/record rule | [`.claude/rules/security.md`](.claude/rules/security.md) |
| Quy ước tích hợp Pancake/Page.fm | [`.claude/rules/integrations.md`](.claude/rules/integrations.md) |
| Quy ước test | [`.claude/rules/tests.md`](.claude/rules/tests.md) |
| Làm việc trong addon nhạy cảm | CLAUDE.md trong thư mục addon đó |
| **Mục tiêu + OKR dự án** | [`docs/GOALS.md`](docs/GOALS.md) |
| **Cảnh báo critical + accepted risks** | [`docs/WARNINGS.md`](docs/WARNINGS.md) |
| **Việc cần làm theo sprint** | [`docs/SPRINT_BACKLOG.md`](docs/SPRINT_BACKLOG.md) |
| Cách vibecode hiệu quả | [`docs/VIBECODE_GUIDE.md`](docs/VIBECODE_GUIDE.md) |

---

## Thư viện tài liệu

> 4 anchor docs ở trên (MODULE_REGISTRY, ARCHITECTURE, DANGER_ZONES, OPEN_QUESTIONS) là **nguồn
> sự thật chính** — xác minh từ file thật, kèm path:line. Các docs dưới đây bổ trợ theo ngữ cảnh.

### B — API Reference (nạp khi sửa controller / route / tích hợp)
| File | Nội dung |
|---|---|
| [`docs/DAC_ERP_CURRENT_API_REFERENCE.md`](docs/DAC_ERP_CURRENT_API_REFERENCE.md) | Toàn bộ Odoo HTTP routes (as of 2026-04-30) |
| [`docs/MCP_V2_API.md`](docs/MCP_V2_API.md) | MCP v2 API chi tiết |
| [`docs/OPENCLAW_MCP_API_QUICKREF.md`](docs/OPENCLAW_MCP_API_QUICKREF.md) | **Bắt đầu ở đây** — index 50+ endpoint + dòng trong full spec |
| [`docs/OPENCLAW_MCP_API_REFERENCE.md`](docs/OPENCLAW_MCP_API_REFERENCE.md) | OpenClaw MCP full spec (**⚠ 3900 dòng** — dùng quickref để đọc đúng đoạn) |
| [`docs/OPENCLAW_TASK_API.md`](docs/OPENCLAW_TASK_API.md) | Task API — **nguồn sự thật** cho task endpoints (có `remind_at`, idempotency) |
| [`docs/OPENCLAW_MCP_TASK_API_SPEC.md`](docs/OPENCLAW_MCP_TASK_API_SPEC.md) | Task design spec — xem khi cần webhook events, cron job names, model references |
| [`docs/OPENCLAW_MCP_MESSAGE_API_SPEC.md`](docs/OPENCLAW_MCP_MESSAGE_API_SPEC.md) | Message endpoint spec |
| [`docs/PANCAKE_TOKEN_FLOW.md`](docs/PANCAKE_TOKEN_FLOW.md) | Pancake auth / token flow |
| [`docs/MESSENGER_API_REFERENCE.md`](docs/MESSENGER_API_REFERENCE.md) | Facebook Messenger Platform API (Graph v25.0) — Send/Webhook/Conversations/Templates |

### C — Ops / Deploy (nạp khi deploy hoặc kiểm tra staging)
| File | Nội dung |
|---|---|
| [`docs/OPENCLAW_MCP_PRODUCTION_RUNBOOK.md`](docs/OPENCLAW_MCP_PRODUCTION_RUNBOOK.md) | Production runbook |
| [`docs/OPENCLAW_MCP_STAGING_SMOKE_TEST_CHECKLIST.md`](docs/OPENCLAW_MCP_STAGING_SMOKE_TEST_CHECKLIST.md) | Smoke test checklist |
| [`docs/OPENCLAW_MCP_TOOL_CATALOG.md`](docs/OPENCLAW_MCP_TOOL_CATALOG.md) | Danh sách MCP tools |

### G — AI & DevOps (nạp khi deploy hoặc xem xét AI tooling)
| File | Nội dung |
|---|---|
| [`docs/ai/AI_TOOLING_RECOMMENDATION.md`](docs/ai/AI_TOOLING_RECOMMENDATION.md) | Đánh giá 14 AI tool, lộ trình P0→P3, combo khuyến nghị |
| [`docs/VIBECODE_GUIDE.md`](docs/VIBECODE_GUIDE.md) | Session start/end, skills, git workflow, ripgrep patterns |
| [`.claude/skills/deploy.md`](.claude/skills/deploy.md) | **Dùng `/deploy`** — workflow subtree push → backup → upgrade production |

### D — Design / Chiến lược (đọc khi lên kế hoạch tính năng mới)
| File | Nội dung |
|---|---|
| [`docs/OPENCLAW_MCP_AGENT_POLICY.md`](docs/OPENCLAW_MCP_AGENT_POLICY.md) | Chính sách OpenClaw agent |
| [`docs/OPENCLAW_MCP_MESSAGE_AGENT_PLAYBOOK.md`](docs/OPENCLAW_MCP_MESSAGE_AGENT_PLAYBOOK.md) | Playbook gửi tin nhắn |
| [`docs/openclaw_integration_workflow.md`](docs/openclaw_integration_workflow.md) | Luồng tích hợp OpenClaw |
| [`docs/message_sync_simplification/04_pancake_api_usage_contract.md`](docs/message_sync_simplification/04_pancake_api_usage_contract.md) | Pancake API contract (verified) |
| [`docs/message_sync_simplification/`](docs/message_sync_simplification/) | Chiến lược sync Pancake (4 file) |

### E — Đánh giá / Rủi ro (bổ sung; cũ hơn anchor docs — xác minh lại trước khi tin)
| Thư mục | Nội dung |
|---|---|
| [`docs/system_evaluation/`](docs/system_evaluation/) | Đánh giá toàn diện 2026-05-26; `10_risk_register_v2.md` hữu ích cho regression-checker |
| [`docs/odoo_system_overview/`](docs/odoo_system_overview/) | System overview 15 files (có thể lạc hậu ở một số điểm) |

### E.2 — Architectural Decision Records (đọc khi gặp pattern "lạ" có chủ đích)
| Thư mục | Nội dung |
|---|---|
| [`docs/decisions/`](docs/decisions/) | ADR cho 4 quirk có chủ đích: Pancake auth off, MCP log read-only, no multi-company, sync flags |

### F — Lịch sử / Audit (read-only, chỉ đọc khi truy vết lỗi cũ)
| Thư mục | Nội dung |
|---|---|
| [`docs/0.1.0_pancake_pos_order_investigation/`](docs/0.1.0_pancake_pos_order_investigation/) | Audit Pancake POS order linkage |
| [`docs/openclaw_mcp_phase_outputs/`](docs/openclaw_mcp_phase_outputs/) | Phase outputs khi xây MCP |
| [`docs/audit_2-6.md`](docs/audit_2-6.md) | Audit MCP v2 — 8 fix từ commit ced0244 (null serialization, envelope contract, care queue) |

---

## Dev Commands
```bash
# Start / stop
docker compose up -d
docker compose down

# Upgrade module (PHẢI chạy sau mọi thay đổi Python/XML/CSV)
docker exec odoo-antigravity-web-1 odoo -d demodata -u MODULE --stop-after-init

# Test toàn bộ module
docker exec odoo-antigravity-web-1 odoo -d demodata --stop-after-init \
  --test-enable --test-tags /MODULE

# Test file cụ thể
docker exec odoo-antigravity-web-1 odoo -d demodata --stop-after-init \
  --test-enable --test-tags /MODULE/tests/test_file_name

# Tail logs
docker logs -f odoo-antigravity-web-1
```
**Databases:** `demodata` (test) · `production_crm` (**KHÔNG BAO GIỜ sửa trực tiếp**).

---

## Luật bất di bất dịch

**An toàn dữ liệu**
- Không sửa `production_crm`.
- Route inbound mới **phải** xác thực secret/HMAC — `/dac_erp/pancake_webhook` đang tắt auth là ngoại lệ có chủ đích, không được làm theo.
- Public export route: `sudo()` theo thiết kế — không mở rộng scope field.

**ORM & Model**
- Batch: `Model.create([...])` và `records.write({})` — không bao giờ loop-create.
- `sudo()` chỉ trong cron/webhook/wizard — luôn comment lý do.
- Không `sudo()` trong `create/write/unlink` override.
- Model mới: `models/__init__.py` + `__manifest__.py` data + ACL CSV + `sudo()` comment nếu dùng.

**Security**
- Mọi model mới: ACL cho ít nhất Manager + `base.group_system`.
- Role mới (sale/design/production): cần record rule domain-limited, không dùng ACL đơn thuần.
- Multi-company không dùng — không thêm `company_id` suy đoán.

**Tích hợp**
- Idempotency: search `_fm_id` trước mọi inbound create.
- Outbound HTTP: `timeout=(10, 30)`, catch `requests.exceptions.RequestException`.
- Cron: không raise — set `state='failed'` + error_message.
- External ID: `Char` + `index=True`, pattern `*_fm_id`.

**Trước khi sửa điểm trong `docs/DANGER_ZONES.md`**
→ Chạy agent `regression-checker` (`.claude/agents/regression-checker.md`).
→ Dùng skill phù hợp: [`odoo-extend-model`](.claude/skills/odoo-extend-model.md) · [`odoo-add-view`](.claude/skills/odoo-add-view.md) · [`odoo-add-access`](.claude/skills/odoo-add-access.md).

---

## After Changes Checklist
| Loại thay đổi | Hành động bắt buộc |
|---|---|
| Python model/logic | `-u MODULE` |
| XML view / security / data | `-u MODULE` |
| Model mới | `__init__.py` + ACL CSV + manifest + `-u MODULE` |
| Cron mới | Upgrade + kiểm tra active trong Technical → Scheduled Actions |
| Route mới | Kiểm tra auth; kiểm tra `sudo()` scope |

---

## Compaction Guidance
Khi tóm tắt phiên dài, giữ lại:
- Tất cả file đã thay đổi và mục đích
- Root cause của bug đã điều tra
- Command đã chạy và kết quả
- Mọi `sudo()` thêm vào với lý do
- Rủi ro chưa giải quyết / câu hỏi mở

---

## Danger Zones — Quick Reference

> Sửa các dòng này → chạy `regression-checker` trước. Chi tiết đầy đủ: `docs/DANGER_ZONES.md`.
> ⚠ Khi line numbers thay đổi do refactor → cập nhật bảng này đồng thời.

| File:line | Method | Vỡ ở đâu nếu sai | Test bắt buộc |
|---|---|---|---|
| `sale_order.py:768` | `sale.order.create()` | OpenClaw hook `sale_order_hooks.py:42` mất event `order.created` | `/dac_erp` + `/dac_openclaw` |
| `sale_order.py:552` | `sale.order.write()` | Vòng lặp write↔task nếu mất flag `dac_skip_task_sync`; mất event `stage_changed` | `/dac_erp` (idempotency) |
| `dac_work_task.py:161/168` | `dac.work.task.create/write()` | Mất notification `task_assigned/completed`; vòng lặp sync ngược order | `/dac_erp` |
| `account_move.py:211` | `account.move.write()` | Sai trigger cọc/hoàn tất khi `payment_state='paid'` | `/dac_erp` (workflow + payment) |
| `account_move.py:13/36/59` | `account.move.read/unlink` | Lộ hóa đơn cho Design/Production hoặc chặn nhầm | test security |
| `page_fm_conversation_models.py` | `page.fm.conversation.write()` | Mất event `conversation.assigned/status_changed` sang OpenClaw | `/CRM_DAC` + `/dac_openclaw` |

**Context flags không được xóa:**
- `dac_skip_task_sync` — guard vòng lặp `sale.order ↔ dac.work.task`
- `dac_skip_order_sync` — guard chiều ngược lại
- Pancake webhook auth tắt tại `/dac_erp/pancake_webhook` là **có chủ đích** — không "fix"

---

## Anti-Hallucination Rules

**Trước khi thêm/sửa field:**
```bash
# Xác minh model định nghĩa ở đâu
rg "_name\s*=\s*'sale.order'" addons/ --type py -n
# Kiểm tra field đã tồn tại chưa (kể cả ở parent model qua _inherit)
rg "field_name\s*=" addons/ --type py -n
# Tìm tất cả _fm_id đã có để tránh đặt trùng tên
rg "_fm_id" addons/ --type py -l
```

**Trước khi thêm route:**
```bash
# Kiểm tra route tồn tại chưa (thay /dac_erp/mcp bằng path thực tế)
rg "@http.route" addons/ --type py -n | rg "/dac_erp/mcp"
# Đọc docs/DAC_ERP_CURRENT_API_REFERENCE.md trước khi tạo route mới
```

**Trước khi dùng group/ACL:**
```bash
# Xác minh group tồn tại — không assume
rg "group_dac_erp_" addons/dac_erp/security/ -n
# Kiểm tra ACL CSV thực tế
cat addons/MODULE/security/ir.model.access.csv
```

**Quy tắc không được đoán:**
- Không thêm `company_id` — multi-company **không dùng** trong dự án này
- Không tự "fix" Pancake webhook auth — tắt là có chủ đích
- Không xóa context flags `dac_skip_*_sync` — đây là bidirectional sync guard
- `mcp_*_log` models: Manager **chỉ có Read** là có chủ đích — không mở rộng ACL
- Thiếu ACL `page.fm.conversation` / `page.fm.message` là known gap — xem `docs/OPEN_QUESTIONS.md §8`
