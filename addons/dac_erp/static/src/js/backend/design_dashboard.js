/** @odoo-module **/
import {
  Component,
  useState,
  useRef,
  onWillStart,
  onMounted,
  onPatched,
  onWillUnmount,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const _DESIGN_H = "dac_design_list_h";

class DesignDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({ loading: true, data: null, error: null, filter: null });
    this.designScrollRef = useRef("designScroll");

    onWillStart(async () => {
      await this.reload();
    });

    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);

    onMounted(() => {
      document.body.classList.add("dac-dashboard-open", "dac-compact");
      const act =
        this.el?.closest?.(".o_action") || document.querySelector(".o_action");
      if (act) {
        this._hostAction = act;
        act.classList.add("dac-host");
      }
      this._raf1 = requestAnimationFrame(this._ensureViewportReady);
      this._refreshTimer = setInterval(() => this._silentReload(), 30_000);
    });

    onPatched(() => {
      const h = localStorage.getItem(_DESIGN_H);
      if (h && this.designScrollRef.el) {
        this._setScrollH(this.designScrollRef.el, parseInt(h, 10));
      }
    });

    onWillUnmount(() => {
      if (this._raf1) cancelAnimationFrame(this._raf1);
      if (this._raf2) cancelAnimationFrame(this._raf2);
      if (this._retryTimer) clearTimeout(this._retryTimer);
      if (this._refreshTimer) clearInterval(this._refreshTimer);
      window.removeEventListener("resize", this._applyViewportTweaks);
      if (this._hostAction) this._hostAction.classList.remove("dac-host");
      document.body.classList.remove("dac-dashboard-open", "dac-compact");
      this._restoreViewportTweaks();
    });
  }

  _setScrollH(el, h) {
    el.style.setProperty("height", h + "px", "important");
    el.style.setProperty("max-height", h + "px", "important");
    el.style.setProperty("min-height", "0", "important");
  }

  startResizeDesign(ev) {
    this._startDrag(ev, this.designScrollRef.el, _DESIGN_H);
  }

  _startDrag(ev, scrollEl, storageKey) {
    if (!scrollEl) return;
    const startY = ev.clientY;
    const startH = scrollEl.getBoundingClientRect().height;
    const handle = ev.currentTarget;
    handle.classList.add("is-dragging");
    document.body.style.userSelect = "none";

    const onMove = (e) => {
      const newH = Math.max(60, startH + (e.clientY - startY));
      this._setScrollH(scrollEl, newH);
    };

    const onUp = (e) => {
      handle.classList.remove("is-dragging");
      document.body.style.userSelect = "";
      const finalH = Math.max(60, startH + (e.clientY - startY));
      this._setScrollH(scrollEl, finalH);
      localStorage.setItem(storageKey, String(finalH));
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  async _silentReload() {
    try {
      const data = await this.orm.call("sale.order", "dac_get_dashboard_design", []);
      if (data) this.state.data = data;
    } catch (e) {
      console.error("[design_dashboard] silent reload failed:", e);
    }
  }

  async reload() {
    this.state.loading = true;
    this.state.error = null;
    try {
      const data = await this.orm.call(
        "sale.order",
        "dac_get_dashboard_design",
        []
      );
      this.state.data = data || { task_stats: {}, design_tasks: [] };
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  get taskStats() {
    return this.state.data?.task_stats || {};
  }
  get designTasks() {
    return this.state.data?.design_tasks || [];
  }
  get overdueCount() {
    return this.designTasks.filter((t) => t.is_overdue).length;
  }

  setFilter(key) {
    this.state.filter = (key === 'total' || this.state.filter === key) ? null : key;
  }

  _applyFilter(tasks) {
    const f = this.state.filter;
    if (f === 'overdue')  return tasks.filter(t => t.is_overdue);
    if (f === 'due_soon') return tasks.filter(t => !t.is_overdue && t.days_left !== false && t.days_left <= 1);
    if (f === 'urgent')   return tasks.filter(t => t.priority === 'urgent');
    return tasks;
  }

  get filteredDesignTasks() {
    return this._applyFilter(this.designTasks);
  }

  get filterLabel() {
    return { overdue: 'Quá hạn', due_soon: 'Sắp đến hạn', urgent: 'Khẩn cấp' }[this.state.filter] || '';
  }

  async openTaskOrOrder(task) {
    if (!task || !task.id) return;
    if (task.order_id) {
      await this.action.doAction({
        type: "ir.actions.act_window",
        res_model: "sale.order",
        res_id: task.order_id,
        target: "current",
        views: [[false, "form"]],
      });
    } else {
      await this.action.doAction({
        type: "ir.actions.act_window",
        res_model: "dac.work.task",
        res_id: task.id,
        target: "current",
        views: [[false, "form"]],
      });
    }
  }

  async markTaskDone(task) {
    if (!task || !task.id) return;
    try {
      await this.orm.write("dac.work.task", [task.id], { state: "done" });
      await this.reload();
    } catch (e) {
      this.notification.add(
        (e && e.message) || "Không thể cập nhật task",
        { type: "danger" }
      );
    }
  }

  // ==== viewport helpers ====
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
    window.addEventListener("resize", this._applyViewportTweaks, { passive: true });
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
      setImp(content, "min-height", "0");
    }
    const ctrl = act?.querySelector(
      ".o_controller_with_control_panel, .o_view_controller"
    );
    if (ctrl) setImp(ctrl, "padding", "0");
    setImp(v, "position", "static");
    setImp(v, "overflow", "visible");
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

DesignDashboard.template = "dac_erp.DesignDashboard";
registry.category("actions").add("dac_design_dashboard", DesignDashboard);
