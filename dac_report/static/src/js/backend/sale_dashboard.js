/** @odoo-module **/
import {
  Component,
  useState,
  onWillStart,
  onMounted,
  onWillUnmount,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

class DacSaleDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({ loading: true, data: null, error: null });

    onWillStart(async () => {
      await this._load();
    });

    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);

    // --- OWL hooks (thay cho mounted()/willUnmount())
    onMounted(() => {
      // gắn class để CSS match
      document.body.classList.add("dac-dashboard-open", "dac-compact");
      const act =
        this.el?.closest?.(".o_action") || document.querySelector(".o_action");
      if (act) {
        this._hostAction = act;
        act.classList.add("dac-host");
      }
      // đợi DOM ổn rồi tinh chỉnh viewport
      this._raf1 = requestAnimationFrame(this._ensureViewportReady);
    });

    onWillUnmount(() => {
      if (this._raf1) cancelAnimationFrame(this._raf1);
      if (this._raf2) cancelAnimationFrame(this._raf2);
      if (this._retryTimer) clearTimeout(this._retryTimer);
      window.removeEventListener("resize", this._applyViewportTweaks);
      if (this._hostAction) this._hostAction.classList.remove("dac-host");
      document.body.classList.remove("dac-dashboard-open", "dac-compact");
      this._restoreViewportTweaks();
    });
  }

  //--------------------------------------------------------------------
  // Data Loading
  //--------------------------------------------------------------------
  async _load() {
    this.state.loading = true;
    try {
      const data = await this.orm.call("sale.order", "dac_get_dashboard", []);
      this.state.data = data || {};
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  async refresh() {
    await this._load();
  }

  //--------------------------------------------------------------------
  // UI Helpers
  //--------------------------------------------------------------------
  // Helpers: đọc dữ liệu linh hoạt theo nhiều key khác nhau
  getTitle(it) {
    let rawTitle =
      it.partner_name ||
      it.customer_name ||
      it.name ||
      it.title ||
      it.display_name ||
      "—";

    // Làm sạch title
    return this.cleanText(rawTitle);
  }

  getSnippet(it) {
    // Ưu tiên: note (suggestion từ AI/n8n) > snippet (tin nhắn cuối) > các field khác
    let rawText =
      it.note ||
      it.suggestion_note ||
      it.last_message_snippet ||
      it.snippet ||
      it.last_message ||
      "";

    // Làm sạch HTML tags và format đặc biệt, sau đó cắt ngắn cho dashboard
    let cleanedText = this.cleanText(rawText);
    return this.truncateText(cleanedText, 100); // Cắt ngắn tối đa 100 ký tự cho dashboard
  }

  // Hàm cắt ngắn text với "..."
  truncateText(text, maxLength = 100) {
    if (!text) return "";
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength).trim() + "...";
  }

  // Hàm làm sạch text - loại bỏ HTML tags, stickers, format đặc biệt
  cleanText(text) {
    if (!text) return "";

    return (
      text
        // Loại bỏ HTML tags
        .replace(/<[^>]*>/g, " ")
        // Loại bỏ stickers và emojis trong []
        .replace(/\[sticker\]/gi, "[Sticker]")
        .replace(/\[emoji\]/gi, "[Emoji]")
        .replace(/\[.*?\]/g, "")
        // Loại bỏ các ký tự đặc biệt liên tiếp
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        // Loại bỏ khoảng trắng thừa
        .replace(/\s+/g, " ")
        .trim()
    );
  }

  getExternalUrl(it) {
    return it.external_url || it.pancake_url || it.url || null;
  }

  getStatusKey(it) {
    // ưu tiên trường server tính sẵn
    if (it.status_state) return it.status_state; // 'new' | 'recontact' | 'waiting' | 'done' ...
    // suy luận đơn giản nếu không có:
    if (it.is_unread_fm || it.is_unread) return "new";
    if (it.checklist_ok) return "done";
    return ""; // không add class trạng thái
  }

  getStatusClass(item) {
    const st = item.status_state || item.care_status || item.consult_status;
    if (st === "new" || st === "recontact" || st === "red")
      return "badge bg-danger";
    if (st === "waiting" || st === "pending" || st === "yellow")
      return "badge bg-warning text-dark";
    return "badge bg-success";
  }

  //--------------------------------------------------------------------
  // Actions
  //--------------------------------------------------------------------

  // Text trạng thái hiển thị một dòng (đỏ/vàng/xám)
  getStateText(it) {
    // 1) quyết định theo trạng thái tính được
    const st = this.getStatusKey(it); // 'new' | 'waiting' | 'done' | ...
    if (st === "new") return "Có tin nhắn mới";
    if (st === "recontact") return "Chăm lại khách";
    if (st === "waiting") return "Cần liên hệ lại";
    if (st === "done") return "Đã xử lý";
    // 2) nếu không suy ra được thì mới dùng label server gửi
    return it.status_label || "";
  }

  // Mở form cuộc hội thoại trong Odoo
  openConversation(item, ev) {
    ev && ev.stopPropagation();
    return this.openForm("page.fm.conversation", item.id);
  }

  // Mở record bất kỳ (method generic)
  async openRecord(model, resId, ev) {
    if (ev) ev.stopPropagation();
    return this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: resId,
      target: "current",
      views: [[false, "form"]],
    });
  }

  // Xử lý click vào receivables - có thể là hóa đơn hoặc đơn hàng
  openReceivable(item, ev) {
    if (ev) ev.stopPropagation();

    if (item.source_type === "order") {
      // Mở đơn hàng
      return this.openRecord("sale.order", item.order_id, ev);
    } else {
      // Mở hóa đơn (logic cũ)
      return this.openRecord("account.move", item.move_id, ev);
    }
  }

  // Mở Pancake trên tab mới (không chặn click vào card)
  openPancake(item, ev) {
    ev && ev.stopPropagation();
    const url = this.getExternalUrl(item);
    if (url) window.open(url, "_blank", "noopener");
  }

  // Toggle checklist -> server set 'done' + mark read
  async toggleChecklist(item, ev) {
    ev && ev.stopPropagation();
    try {
      const res = await this.orm.call(
        "page.fm.conversation",
        "action_toggle_require_processing",
        [item.id]
      );

      // Cập nhật item với response từ server
      Object.assign(item, res);

      // Trigger OWL update bằng cách thay đổi object state gốc
      this.state.data = { ...this.state.data };
    } catch (err) {
      console.error("toggleChecklist failed:", err);
      this.notification.add(_t("Không cập nhật được trạng thái xử lý."), {
        type: "danger",
      });
    }
  }

  openForm(model, id) {
    return this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      views: [[false, "form"]],
      target: "current",
    });
  }

  //--------------------------------------------------------------------
  // Viewport helpers
  //--------------------------------------------------------------------
  _ensureViewportReady() {
    let v = this.el?.classList?.contains("dac-viewport")
      ? this.el
      : document.querySelector(".dac-viewport");
    if (!v) {
      this._retryTimer = setTimeout(this._ensureViewportReady, 0);
      return;
    }
    this._viewport = v;

    this._applyViewportTweaks();
    this._raf2 = requestAnimationFrame(this._applyViewportTweaks);
    window.addEventListener("resize", this._applyViewportTweaks, {
      passive: true,
    });
  }

  _applyViewportTweaks() {
    const v = this._viewport || document.querySelector(".dac-viewport");
    if (!v) return;

    this._bak = this._bak || new Map();
    const setImp = (node, prop, value) => {
      if (!node) return;
      if (!this._bak.has(node)) this._bak.set(node, {});
      const rec = this._bak.get(node);
      if (!(prop in rec)) rec[prop] = node.style.getPropertyValue(prop);
      node.style.setProperty(prop, value, "important");
    };

    const act = v.closest?.(".o_action") || document.querySelector(".o_action");
    const content = act?.querySelector(".o_content");
    if (content) {
      setImp(content, "padding", "0");
      setImp(content, "overflow", "auto");
    }
    const ctrl = act?.querySelector(
      ".o_controller_with_control_panel, .o_view_controller"
    );
    if (ctrl) setImp(ctrl, "padding", "0");

    setImp(v, "position", "static");
    setImp(v, "overflow", "visible"); // không tạo scroll host lồng

    const cx = v.querySelector(".container-xxl");
    if (cx) {
      setImp(cx, "padding-left", "0");
      setImp(cx, "padding-right", "0");
      setImp(cx, "margin-left", "auto");
      setImp(cx, "margin-right", "auto");
    }
  }

  _restoreViewportTweaks() {
    if (!this._bak) return;
    this._bak.forEach((styles, node) => {
      if (!node) return;
      Object.entries(styles).forEach(([prop, value]) => {
        if (value) node.style.setProperty(prop, value);
        else node.style.removeProperty(prop);
      });
    });
    this._bak.clear();
  }

  // mở list theo box, bật filter tương ứng
  openListByBox(type) {
    const header = this.state.data?.header || {};
    const isManager = !!header.is_manager;
    const actXmlId = isManager
      ? "dac_erp.dac_sale_order_manager_action"
      : "dac_erp.dac_sale_order_custom_action";

    let ctx = {};
    if (type === "quotation") {
      // dùng filter gộp đã tạo trong search view
      ctx.search_default_quote_or_deposit = 1; // <— đã báo giá hoặc đặt cọc
    } else if (type === "production") {
      ctx.search_default_production = 1; // chỉ trạng thái sản xuất
    } else if (type === "completed") {
      ctx.search_default_completed = 1; // chỉ đơn đã hoàn thành
    }
    // … (các box khác làm sau)

    this.env.services.action.doAction(actXmlId, { additionalContext: ctx });
  }
}

DacSaleDashboard.template = "dac_sale_dashboard.Dashboard";
registry.category("actions").add("dac_sale_dashboard", DacSaleDashboard);
