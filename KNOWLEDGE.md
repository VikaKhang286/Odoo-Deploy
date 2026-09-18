# KNOWLEDGE.md — Odoo Antigravity Insights

> Accumulated insights, best practices, troubleshooting, và lessons learned.
> Updated: 2026-07-08

---

## 💡 Key Insights

### Confidence Check ROI

Pre-execution confidence checking có exceptional ROI:
- Spend 100-200 tokens cho confidence check → tiết kiệm 5,000-50,000 tokens khi đi sai hướng
- **Ví dụ thực tế**: 2 phút research vs 2 giờ làm duplicate feature work

### Hallucination Detection

**94% accuracy** với 4 câu hỏi:
1. Are all tests passing? (verify actual output)
2. Are all requirements met? (list each)
3. No assumptions without verification? (show documentation)
4. Is there evidence? (provide test results)

### Parallel Execution Pattern

**3.5x speedup**: Wave → Checkpoint → Wave
- 10 file reads: 30s sequential → 3s parallel

---

## 🔧 Common Pitfalls

### 1. Implement Before Checking Duplicates

**Anti-pattern**: Tìm thấy code tương tự SAU khi implement xong.

**Prevention**:
```bash
# Luôn làm trước khi implement
rg "feature_name" addons/ --type py -n
rg "field_name" addons/ --type py -n
```

### 2. Assuming Architecture Without Verification

**Anti-pattern**: Implement dựa trên giả định về code structure.

**Prevention**:
```bash
# Đọc CLAUDE.md và PLANNING.md TRƯỚC
# Check actual code structure
rg "_name\s*=" addons/dac_erp/models/ --type py -n
```

### 3. Skipping Test Output Display

**Anti-pattern**: Nói "tests pass" mà không show output.

**Prevention**: Luôn paste actual test output khi báo cáo.

### 4. Missing Regression Tests for DANGER_ZONES

**Anti-pattern**: Sửa code ở DANGER_ZONES mà không có regression test.

**Prevention**: Chạy `regression-checker` agent trước khi sửa.

---

## 🛠️ Troubleshooting Guide

### Docker Container Issues

**Container name chính xác**: `odoo-local-web` (KHÔNG `odoo-antigravity-web-1`)

```bash
# Kiểm tra container status
docker ps | grep odoo

# Xem logs
docker logs -f odoo-local-web

# Restart (cần thiết khi đổi SCSS/JS/OWL)
docker restart odoo-local-web
```

### Odoo Upgrade Issues

```bash
# Upgrade module
docker exec odoo-local-web odoo -d demodata -u MODULE --stop-after-init

# Full upgrade (sau khi thêm model mới)
docker exec odoo-local-web odoo -d demodata -u base --stop-after-init
```

### Import/Module Not Found

1. Kiểm tra `__manifest__.py` có trong addon directory
2. Kiểm tra `__init__.py` có import models
3. Chạy full upgrade: `-u base`

### Asset Reload (SCSS/JS/OWL)

**QUAN TRỌNG**: Chỉ `-u` KHÔNG đủ cho assets!
```bash
docker restart odoo-local-web
```

---

## 📝 Lessons Learned

### 2026-07-08: SuperClaude Framework Integration

**Pattern**: Confidence-First Implementation
- ✅ Thêm PLANNING.md với confidence check guidelines
- ✅ Thêm TASK.md với sprint backlog
- ✅ Thêm KNOWLEDGE.md với accumulated insights
- ✅ Áp dụng Wave → Checkpoint → Wave pattern

**Pattern**: Evidence-Based Development
- ✅ Anti-hallucination rules trong CLAUDE.md
- ✅ 4 câu hỏi kiểm tra trước khi kết luận

### 2026-07-07: Sale Order Batch Actions

**Issue**: Batch complete orders cần wizard để chọn lý do/comment.

**Solution**: Tạo `QuickCompleteWizard` với:
- Wizard form để nhập lý do
- Batch `write()` với context flag

**Learnings**:
- Luôn kiểm tra `dac_skip_task_sync` khi batch-writing orders
- Test với edge cases: orders ở various states

### 2026-06: OpenClaw MCP Integration

**Issue**: Message sync có potential race conditions.

**Solution**: Implement idempotency với `external_message_id` uniqueness.

**Learnings**:
- Luôn search `_fm_id` trước khi create
- Outbound HTTP: `timeout=(10, 30)` là best practice

---

## 📚 Resources

### Official Documentation
- [Odoo 18 Developer Documentation](https://www.odoo.com/documentation/18.0/)
- [Odoo ORM API](https://www.odoo.com/documentation/18.0/developer/reference/backend/orm.html)

### Internal Documentation
- [CLAUDE.md](CLAUDE.md) — Project context
- [PLANNING.md](PLANNING.md) — Architecture rules
- [TASK.md](TASK.md) — Current tasks

---

## 🏷️ Tags / Quick Reference

| Tag | Mô tả |
|-----|--------|
| `#confidence-check` | Task cần confidence assessment trước |
| `#danger-zone` | Task touch DANGER_ZONES — chạy regression-checker |
| `#parallel` | Task có thể parallelize được |
| `#evidence-required` | Cần show test output / evidence |
| `#sudo-needed` | Task cần sudo() — cần comment rõ ràng |

---

*Document này được update khi có insights mới.*
*Pattern: `# Tag` = topic, `## YYYY-MM-DD` = dated entries*
