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

class ProductionDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({
      loading: true,
      data: null,
      error: null,
      tab: "my",
    });

    onWillStart(async () => {
      await this._load();
    });

    // ===== viewport helpers (giống Design) =====
    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);

    onMounted(() => {
      // gắn class để CSS toàn cục match (nếu bạn đang dùng trong dac_common.css)
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

  async _load() {
    this.state.loading = true;
    try {
      const data = await this.orm.call(
        "sale.order",
        "dac_get_dashboard_production",
        []
      );
      this.state.data = data || {
        kpi: {},
        lists: { my_tasks: [], all_tasks: [] },
        user_can_lead: false,
      };
      if (!this.state.data.user_can_lead) this.state.tab = "my";
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  setTab(t) {
    this.state.tab = t;
  }
  get myTasks() {
    return this.state.data?.lists?.my_tasks || [];
  }
  get allTasks() {
    return this.state.data?.lists?.all_tasks || [];
  }
  get finishedList() {
    return this.state.data?.lists?.finished || [];
  }
  get needMarkList() {
    return this.state.data?.lists?.need_mark || [];
  }

  async openOrder(so) {
    if (!so || !so.id) return;
    await this.action.doAction({
      type: "ir.actions.act_window",
      res_model: "sale.order",
      res_id: so.id,
      target: "current",
      views: [[false, "form"]],
    });
  }

  // ===== viewport helpers (copy từ Design) =====
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
      setImp(content, "overflow", "auto"); // CHÍNH: bật cuộn cho action
      setImp(content, "min-height", "0");
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
}

ProductionDashboard.template = "dac_erp.ProductionDashboard";
registry
  .category("actions")
  .add("dac_production_dashboard", ProductionDashboard);
