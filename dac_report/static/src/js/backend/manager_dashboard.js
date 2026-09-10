/** @odoo-module **/

import {
  Component,
  useState,
  onWillStart,
  onMounted,
  onPatched,
  onWillUnmount,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ManagerDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");

    this.state = useState({
      // Dữ liệu dashboard
      data: {
        // KPI Cards - CẤU TRÚC MỚI
        total_revenue: 0, // Tổng doanh thu (đã hoàn thành)
        expected_revenue: 0, // Doanh thu dự kiến (SX → trước thu tiền)
        total_debt: 0, // Công nợ (cần thu tiền)
        quotation_revenue: 0, // Doanh số báo giá
        active_orders: 0, // Đơn đang hoạt động
        delayed_production: 0, // Đơn trễ hạn (dùng alert)

        // Pipeline data
        quotation_count: 0,
        quotation_amount: 0,
        deposit_count: 0,
        deposit_amount: 0,
        production_count: 0,
        production_amount: 0,
        installation_count: 0,
        installation_amount: 0,
        delivery_count: 0,
        delivery_amount: 0,
        payment_count: 0,
        payment_amount: 0,
        completed_count: 0,
        completed_amount: 0,

        // Action center - alerts
        alerts: [],

        // Performance tracking
        sales_performance: [],
        design_performance: [],
        production_performance: [],
      },

      // Filter state - NEW STRUCTURE
      filterMode: "month", // 'month', 'week', 'year', 'custom'
      selectedMonth: null, // 1-12
      selectedYear: null, // 2025, 2024...
      selectedWeek: null, // 1-5 (tuần trong tháng)
      pickerYear: new Date().getFullYear(), // Year hiển thị trong picker
      showPeriodPicker: false,
      showCustomRange: false,
      customDateFrom: null,
      customDateTo: null,

      // Legacy support (sẽ được tính từ filterMode)
      dateFilter: "month",
      dateFrom: null,
      dateTo: null,
      showCustomDatePicker: false,

      // UI state
      activeTab: "alerts",
      performanceTab: "sales",
      loading: true,
    });

    // Bind viewport methods
    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);

    // Initialize selected month/year to current
    const now = new Date();
    this.state.selectedMonth = now.getMonth() + 1;
    this.state.selectedYear = now.getFullYear();
    this.state.pickerYear = now.getFullYear();

    onWillStart(async () => {
      await this.loadDashboardData();
    });

    onMounted(() => {
      this.initializeDatePicker();

      // Apply viewport tweaks for scrolling
      document.body.classList.add("dac-dashboard-open", "dac-compact");
      const act =
        this.el?.closest?.(".o_action") || document.querySelector(".o_action");
      if (act) {
        this._hostAction = act;
        act.classList.add("dac-host");
      }
      this._raf1 = requestAnimationFrame(this._ensureViewportReady);
    });

    onPatched(() => {
      // Re-initialize date picker mỗi khi UI update (khi showCustomDatePicker thay đổi)
      this.initializeDatePicker();

      // 🔧 FIX: Re-apply viewport tweaks mỗi khi UI patch (đặc biệt sau loading → content)
      if (!this.state.loading && this._viewport) {
        this._applyViewportTweaks();
      }
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

  /**
   * Khởi tạo date picker khi chọn Custom
   */
  initializeDatePicker() {
    // Set locale cho date inputs trong custom dropdown
    const dateInputs = this.el?.querySelectorAll(
      '.custom-date-dropdown input[type="date"]'
    );
    if (dateInputs && dateInputs.length > 0) {
      dateInputs.forEach((input) => {
        // Set các attributes
        input.setAttribute("lang", "vi-VN");
        input.setAttribute("data-date-format", "dd/mm/yyyy");

        // Chuyển sang text input với placeholder dd/mm/yyyy khi không có giá trị
        const toggleInputType = () => {
          if (!input.value) {
            input.type = "text";
            input.placeholder = "dd/mm/yyyy";
            input.style.color = "#6c757d";
          }
        };

        // Event: chuyển về date khi focus
        input.addEventListener("focus", (e) => {
          e.target.type = "date";
          e.target.style.color = "";
        });

        // Event: chuyển về text nếu blur mà không có giá trị
        input.addEventListener("blur", (e) => {
          setTimeout(() => toggleInputType(), 100);
        });

        // Init state
        toggleInputType();
      });

      //console.log("✅ Date picker initialized with dd/mm/yyyy placeholder");
    }
  }

  /**
   * Format date từ YYYY-MM-DD sang DD/MM/YYYY
   */
  formatDateVN(dateString) {
    if (!dateString) return "";
    const [year, month, day] = dateString.split("-");
    return `${day}/${month}/${year}`;
  }

  /**
   * Parse date từ DD/MM/YYYY sang YYYY-MM-DD
   */
  parseDateVN(dateString) {
    if (!dateString) return "";
    const [day, month, year] = dateString.split("/");
    return `${year}-${month}-${day}`;
  }

  /**
   * Load dữ liệu dashboard từ backend
   */
  async loadDashboardData() {
    this.state.loading = true;
    try {
      const { dateFrom, dateTo } = this.getDateRange();

      //console.log("🔄 Loading Dashboard Data...");
      //console.log("📅 Date Range:", {
      //  dateFrom,
      //  dateTo,
      //  filter: this.state.dateFilter,
      //});
      //console.log("🔍 State values:", {
      //  dateFrom: this.state.dateFrom,
      //  dateTo: this.state.dateTo,
      //});

      const result = await this.orm.call(
        "sale.order",
        "dac_get_manager_dashboard",
        [],
        {
          date_from: dateFrom,
          date_to: dateTo,
          company_id: false, // Sử dụng company hiện tại
        }
      );

      //console.log("✅ Dashboard Data Loaded:", result);

      // Cập nhật state với dữ liệu mới
      Object.assign(this.state.data, result);
    } catch (error) {
      console.error("❌ Error loading dashboard data:", error);
    } finally {
      this.state.loading = false;

      // 🔧 FIX: Apply viewport tweaks sau khi data load xong
      // Dùng nextTick để đảm bảo DOM đã render xong
      setTimeout(() => {
        this._applyViewportTweaks();
      }, 100);
    }
  }

  /**
   * Lấy khoảng thời gian dựa trên filter - NEW LOGIC
   */
  getDateRange() {
    const formatDate = (date) => {
      if (!date) return null;
      if (typeof date === "string" && date.match(/^\d{4}-\d{2}-\d{2}$/)) {
        return date;
      }
      if (date instanceof Date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
      }
      return null;
    };

    let dateFrom, dateTo;

    if (this.state.filterMode === "custom") {
      // Custom range
      dateFrom = this.state.customDateFrom;
      dateTo = this.state.customDateTo;
    } else if (this.state.filterMode === "week") {
      // Specific week in month
      const year = this.state.selectedYear || new Date().getFullYear();
      const month = this.state.selectedMonth || new Date().getMonth() + 1;
      const week = this.state.selectedWeek || 1;

      // Tính ngày bắt đầu và kết thúc của tuần trong tháng
      const weekRange = this.getWeekRangeInMonth(year, month, week);
      dateFrom = formatDate(weekRange.start);
      dateTo = formatDate(weekRange.end);
    } else if (this.state.filterMode === "month") {
      // Specific month/year
      const year = this.state.selectedYear || new Date().getFullYear();
      const month = this.state.selectedMonth || new Date().getMonth() + 1;

      dateFrom = new Date(year, month - 1, 1);
      dateTo = new Date(year, month, 0); // Last day of month

      dateFrom = formatDate(dateFrom);
      dateTo = formatDate(dateTo);
    } else if (this.state.filterMode === "year") {
      // Full year
      const year = this.state.selectedYear || new Date().getFullYear();

      dateFrom = new Date(year, 0, 1);
      dateTo = new Date(year, 11, 31);

      dateFrom = formatDate(dateFrom);
      dateTo = formatDate(dateTo);
    } else {
      // Default: current month
      const today = new Date();
      dateFrom = new Date(today.getFullYear(), today.getMonth(), 1);
      dateTo = new Date(today.getFullYear(), today.getMonth() + 1, 0);

      dateFrom = formatDate(dateFrom);
      dateTo = formatDate(dateTo);
    }

    return { dateFrom, dateTo };
  }

  /**
   * Tính khoảng ngày của tuần thứ N trong tháng theo lịch thực tế
   * Tuần bắt đầu từ Thứ 2 (Monday) và kết thúc Chủ nhật (Sunday)
   * @param {number} year - Năm
   * @param {number} month - Tháng (1-12)
   * @param {number} weekNumber - Số tuần (1-5)
   * @returns {object} - {start: Date, end: Date}
   */
  getWeekRangeInMonth(year, month, weekNumber) {
    const firstDay = new Date(year, month - 1, 1);
    const lastDay = new Date(year, month, 0);

    // Tìm ngày Thứ 2 đầu tiên trong tháng
    const firstDayOfWeek = firstDay.getDay(); // 0=Sunday, 1=Monday, ..., 6=Saturday
    let firstMonday;

    if (firstDayOfWeek === 0) {
      // Nếu ngày 1 là Chủ nhật, Thứ 2 đầu tiên là ngày 2
      firstMonday = 2;
    } else if (firstDayOfWeek === 1) {
      // Nếu ngày 1 là Thứ 2, giữ nguyên
      firstMonday = 1;
    } else {
      // Nếu ngày 1 là Thứ 3-7, tìm Thứ 2 tiếp theo
      firstMonday = 9 - firstDayOfWeek; // 2-7 ngày để đến Thứ 2
    }

    // Tính ngày bắt đầu của tuần thứ weekNumber
    const startDay = firstMonday + (weekNumber - 1) * 7;
    const endDay = Math.min(startDay + 6, lastDay.getDate()); // +6 ngày (Thứ 2 → Chủ nhật)

    // Kiểm tra nếu startDay vượt quá số ngày trong tháng
    if (startDay > lastDay.getDate()) {
      // Trường hợp tuần này không tồn tại trong tháng
      return {
        start: lastDay,
        end: lastDay,
      };
    }

    return {
      start: new Date(year, month - 1, startDay),
      end: new Date(year, month - 1, endDay),
    };
  }

  /**
   * Lấy số tuần hiện tại trong tháng (theo lịch Thứ 2-CN)
   */
  getCurrentWeekInMonth() {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const dayOfMonth = now.getDate();

    // Tìm tuần chứa ngày hiện tại
    const weeks = this.getWeeksInMonth();
    for (let i = 0; i < weeks.length; i++) {
      const week = weeks[i];
      const range = this.getWeekRangeInMonth(year, month, week.number);
      if (
        dayOfMonth >= range.start.getDate() &&
        dayOfMonth <= range.end.getDate()
      ) {
        return week.number;
      }
    }

    return 1; // Fallback
  }

  /**
   * Chọn tuần này
   */
  async selectThisWeek() {
    const now = new Date();
    this.state.filterMode = "week";
    this.state.selectedYear = now.getFullYear();
    this.state.selectedMonth = now.getMonth() + 1;
    this.state.selectedWeek = this.getCurrentWeekInMonth();
    await this.loadDashboardData();
  }

  /**
   * Chọn tuần trước (theo lịch Thứ 2-CN)
   */
  async selectLastWeek() {
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;

    // Tìm tuần hiện tại
    const currentWeek = this.getCurrentWeekInMonth();

    if (currentWeek > 1) {
      // Tuần trước trong cùng tháng
      this.state.filterMode = "week";
      this.state.selectedYear = currentYear;
      this.state.selectedMonth = currentMonth;
      this.state.selectedWeek = currentWeek - 1;
    } else {
      // Tuần cuối tháng trước
      const lastMonthDate = new Date(currentYear, currentMonth - 1, 0); // Ngày cuối tháng trước
      const lastMonth = lastMonthDate.getMonth() + 1;
      const lastMonthYear = lastMonthDate.getFullYear();

      // Tính số tuần trong tháng trước
      this.state.selectedYear = lastMonthYear;
      this.state.selectedMonth = lastMonth;
      const weeksInLastMonth = this.getWeeksInMonth();

      this.state.filterMode = "week";
      this.state.selectedWeek = weeksInLastMonth.length; // Tuần cuối cùng
    }

    await this.loadDashboardData();
  }

  /**
   * Chọn tuần cụ thể từ dropdown
   */
  async selectWeekNumber(weekNumber) {
    this.state.filterMode = "week";
    this.state.selectedWeek = weekNumber;

    // Nếu chưa có tháng/năm, dùng tháng hiện tại
    if (!this.state.selectedMonth || !this.state.selectedYear) {
      const now = new Date();
      this.state.selectedMonth = now.getMonth() + 1;
      this.state.selectedYear = now.getFullYear();
    }

    await this.loadDashboardData();
  }

  /**
   * Lấy danh sách tuần trong tháng hiện tại (theo lịch Thứ 2-CN)
   */
  getWeeksInMonth() {
    const year = this.state.selectedYear || new Date().getFullYear();
    const month = this.state.selectedMonth || new Date().getMonth() + 1;

    const firstDay = new Date(year, month - 1, 1);
    const lastDay = new Date(year, month, 0);
    const firstDayOfWeek = firstDay.getDay();

    // Tìm Thứ 2 đầu tiên
    let firstMonday;
    if (firstDayOfWeek === 0) {
      firstMonday = 2;
    } else if (firstDayOfWeek === 1) {
      firstMonday = 1;
    } else {
      firstMonday = 9 - firstDayOfWeek;
    }

    // Đếm số tuần (mỗi tuần 7 ngày từ Thứ 2)
    const weeks = [];
    let weekNumber = 1;
    let currentMonday = firstMonday;

    while (currentMonday <= lastDay.getDate()) {
      const range = this.getWeekRangeInMonth(year, month, weekNumber);
      weeks.push({
        number: weekNumber,
        label: `Tuần ${weekNumber}`,
        range: `${range.start.getDate()}/${month} - ${range.end.getDate()}/${month}`,
      });

      weekNumber++;
      currentMonday += 7;
    }

    return weeks;
  }

  /**
   * Xử lý khi thay đổi date filter
   */
  async onDateFilterChange(ev) {
    this.state.dateFilter = ev.target.value;

    if (this.state.dateFilter === "custom") {
      this.state.showCustomDatePicker = true;
    } else {
      this.state.showCustomDatePicker = false;
      await this.loadDashboardData();
    }
  }

  /**
   * Xử lý khi focus vào date input
   */
  onDateInputFocus(ev) {
    const input = ev.target;
    // Chuyển sang type="date" để mở calendar
    input.type = "date";

    // Force set locale attributes
    input.setAttribute("lang", "vi");
    input.setAttribute("locale", "vi-VN");

    // Try to set the input's locale via JavaScript
    try {
      if (input.showPicker) {
        // Modern browsers
        setTimeout(() => input.showPicker(), 50);
      }
    } catch (e) {
      //console.log("Browser does not support showPicker()");
    }
  }

  /**
   * Xử lý khi blur khỏi date input
   */
  onDateInputBlur(ev) {
    const input = ev.target;
    // Nếu chưa chọn giá trị, chuyển về text với placeholder
    if (!input.value) {
      setTimeout(() => {
        input.type = "text";
        input.placeholder = "dd/mm/yyyy";
      }, 100);
    }
  }

  /**
   * Xử lý khi chọn custom date range
   */
  async onCustomDateApply() {
    if (this.state.dateFrom && this.state.dateTo) {
      await this.loadDashboardData();
      this.state.showCustomDatePicker = false;
    }
  }

  /**
   * Hủy chọn custom date
   */
  onCustomDateCancel() {
    this.state.showCustomDatePicker = false;
    this.state.dateFilter = "month"; // Reset về tháng này
  }

  /**
   * Format số tiền
   */
  formatCurrency(amount) {
    if (!amount) return "0đ";

    if (amount >= 1000000000) {
      return `${(amount / 1000000000).toFixed(1)} Tỷ`;
    } else if (amount >= 1000000) {
      return `${(amount / 1000000).toFixed(0)} Triệu`;
    } else {
      return `${amount.toLocaleString("vi-VN")}đ`;
    }
  }

  /**
   * Chuyển tab trong Action Center
   */
  switchTab(tab) {
    this.state.activeTab = tab;
  }

  /**
   * Chuyển tab trong Performance Tracking
   */
  switchPerformanceTab(tab) {
    this.state.performanceTab = tab;
  }

  /**
   * Mở form đơn hàng
   */
  async openOrder(orderId) {
    this.action.doAction({
      type: "ir.actions.act_window",
      res_model: "sale.order",
      res_id: orderId,
      views: [[false, "form"]],
      target: "current",
    });
  }

  /**
   * Mở danh sách đơn hàng theo trạng thái
   */
  async openOrdersByState(state) {
    // Lấy khoảng thời gian hiện tại từ dashboard
    const { dateFrom, dateTo } = this.getDateRange();

    // Domain với cả trạng thái VÀ khoảng thời gian
    const domain = [
      ["order_state_custom", "=", state],
      ["date", ">=", dateFrom],
      ["date", "<=", dateTo],
    ];
    
    // 🆕 Lọc bỏ đơn 0đ (cơ hội) khi xem Báo giá
    if (state === "quotation") {
      domain.push(["is_zero_amount", "=", false]);
    }

    // Tạo text hiển thị khoảng thời gian
    const periodText = this.getPeriodTextForTitle();

    this.action.doAction({
      type: "ir.actions.act_window",
      name: `Đơn hàng - ${this.getStateName(state)} (${periodText})`,
      res_model: "sale.order",
      views: [
        [false, "list"],
        [false, "form"],
      ],
      domain: domain,
      target: "current",
    });
  }

  /**
   * Get period text for action title
   */
  getPeriodTextForTitle() {
    if (this.state.filterMode === "custom") {
      if (this.state.customDateFrom && this.state.customDateTo) {
        const from = new Date(this.state.customDateFrom);
        const to = new Date(this.state.customDateTo);
        return `${from.getDate()}/${
          from.getMonth() + 1
        }/${from.getFullYear()} - ${to.getDate()}/${
          to.getMonth() + 1
        }/${to.getFullYear()}`;
      }
      return "Tùy chỉnh";
    }

    if (this.state.filterMode === "year") {
      return `Năm ${this.state.selectedYear}`;
    }

    if (this.state.filterMode === "week") {
      const monthNames = [
        "Tháng 1", "Tháng 2", "Tháng 3", "Tháng 4", "Tháng 5", "Tháng 6",
        "Tháng 7", "Tháng 8", "Tháng 9", "Tháng 10", "Tháng 11", "Tháng 12",
      ];
      const range = this.getWeekRangeInMonth(
        this.state.selectedYear,
        this.state.selectedMonth,
        this.state.selectedWeek
      );
      return `Tuần ${this.state.selectedWeek} - ${monthNames[this.state.selectedMonth - 1]} / ${this.state.selectedYear} (${range.start.getDate()}-${range.end.getDate()}/${this.state.selectedMonth})`;
    }

    if (this.state.filterMode === "month") {
      const monthNames = [
        "Tháng 1",
        "Tháng 2",
        "Tháng 3",
        "Tháng 4",
        "Tháng 5",
        "Tháng 6",
        "Tháng 7",
        "Tháng 8",
        "Tháng 9",
        "Tháng 10",
        "Tháng 11",
        "Tháng 12",
      ];
      return `${monthNames[this.state.selectedMonth - 1]} / ${
        this.state.selectedYear
      }`;
    }

    return "Tháng này";
  }

  /**
   * Lấy tên trạng thái tiếng Việt
   */
  getStateName(state) {
    const stateNames = {
      quotation: "Báo giá",
      deposit: "Đặt cọc",
      production: "Sản xuất",
      installation: "Thi công/Lắp đặt",
      delivery: "Giao hàng",
      payment: "Thu tiền",
      completed: "Hoàn thành",
    };
    return stateNames[state] || state;
  }

  /**
   * Xuất báo cáo
   */
  async exportReport() {
    // TODO: Implement export functionality
    //console.log("Exporting report...");
  }

  //--------------------------------------------------------------------
  // Viewport helpers (giống Sale Dashboard)
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
    setImp(v, "overflow", "visible");

    const cx = v.querySelector(".container-fluid");
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

  // ========== NEW PERIOD PICKER METHODS ==========

  /**
   * Get display text for current selected period
   */
  getPeriodDisplayText() {
    if (this.state.filterMode === "custom") {
      if (this.state.customDateFrom && this.state.customDateTo) {
        const from = new Date(this.state.customDateFrom);
        const to = new Date(this.state.customDateTo);
        return `${from.getDate()}/${
          from.getMonth() + 1
        }/${from.getFullYear()} - ${to.getDate()}/${
          to.getMonth() + 1
        }/${to.getFullYear()}`;
      }
      return "Tùy chỉnh khoảng thời gian";
    }

    if (this.state.filterMode === "year") {
      return `Năm ${this.state.selectedYear}`;
    }

    if (this.state.filterMode === "week") {
      const monthNames = [
        "Tháng 1",
        "Tháng 2",
        "Tháng 3",
        "Tháng 4",
        "Tháng 5",
        "Tháng 6",
        "Tháng 7",
        "Tháng 8",
        "Tháng 9",
        "Tháng 10",
        "Tháng 11",
        "Tháng 12",
      ];
      const range = this.getWeekRangeInMonth(
        this.state.selectedYear,
        this.state.selectedMonth,
        this.state.selectedWeek
      );
      return `Tuần ${this.state.selectedWeek} - ${
        monthNames[this.state.selectedMonth - 1]
      } / ${
        this.state.selectedYear
      } (${range.start.getDate()}-${range.end.getDate()}/${
        this.state.selectedMonth
      })`;
    }

    if (this.state.filterMode === "month") {
      const monthNames = [
        "Tháng 1",
        "Tháng 2",
        "Tháng 3",
        "Tháng 4",
        "Tháng 5",
        "Tháng 6",
        "Tháng 7",
        "Tháng 8",
        "Tháng 9",
        "Tháng 10",
        "Tháng 11",
        "Tháng 12",
      ];
      return `${monthNames[this.state.selectedMonth - 1]} / ${
        this.state.selectedYear
      }`;
    }

    return "Chọn thời gian";
  }

  /**
   * Toggle period picker dropdown
   */
  togglePeriodPicker() {
    this.state.showPeriodPicker = !this.state.showPeriodPicker;

    // Initialize picker year to current selection if opening
    if (this.state.showPeriodPicker) {
      this.state.pickerYear =
        this.state.selectedYear || new Date().getFullYear();
    }
  }

  /**
   * Navigate year in picker
   */
  navigateYear(delta) {
    this.state.pickerYear += delta;
  }

  /**
   * Get list of months for grid
   */
  getMonthsList() {
    return [
      { value: 1, label: "T1" },
      { value: 2, label: "T2" },
      { value: 3, label: "T3" },
      { value: 4, label: "T4" },
      { value: 5, label: "T5" },
      { value: 6, label: "T6" },
      { value: 7, label: "T7" },
      { value: 8, label: "T8" },
      { value: 9, label: "T9" },
      { value: 10, label: "T10" },
      { value: 11, label: "T11" },
      { value: 12, label: "T12" },
    ];
  }

  /**
   * Check if month is selected
   */
  isMonthSelected(month) {
    return (
      this.state.filterMode === "month" &&
      this.state.selectedMonth === month &&
      this.state.selectedYear === this.state.pickerYear
    );
  }

  /**
   * Select a month
   */
  selectMonth(month) {
    this.state.filterMode = "month";
    this.state.selectedMonth = month;
    this.state.selectedYear = this.state.pickerYear;
    this.state.showPeriodPicker = false;

    // Reload dashboard với month mới
    this.loadDashboardData();
  }

  /**
   * Select current picker year
   */
  selectYear() {
    this.state.filterMode = "year";
    this.state.selectedYear = this.state.pickerYear;
    this.state.showPeriodPicker = false;

    // Reload dashboard với year
    this.loadDashboardData();
  }

  /**
   * Open custom range modal
   */
  openCustomRange() {
    this.state.showPeriodPicker = false;
    this.state.showCustomRange = true;

    // Initialize với values hiện tại nếu có
    if (!this.state.customDateFrom) {
      const now = new Date();
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      this.state.customDateFrom = firstDay.toISOString().split("T")[0];
      this.state.customDateTo = now.toISOString().split("T")[0];
    }
  }

  /**
   * Close custom range modal
   */
  closeCustomRange() {
    this.state.showCustomRange = false;
  }

  /**
   * Apply custom date range
   */
  applyCustomRange() {
    if (!this.state.customDateFrom || !this.state.customDateTo) {
      alert("Vui lòng chọn đầy đủ khoảng thời gian");
      return;
    }

    this.state.filterMode = "custom";
    this.state.showCustomRange = false;

    // Reload dashboard
    this.loadDashboardData();
  }
}

ManagerDashboard.template = "dac_report.ManagerDashboard";

registry.category("actions").add("dac_manager_dashboard", ManagerDashboard);
