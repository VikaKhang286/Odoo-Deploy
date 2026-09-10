/** @odoo-module **/
import { registry } from "@web/core/registry";

/* Gắn màu cho badge theo trạng thái */
function applyStateBadgeClasses(root = document) {
  const map = {
    // giá trị chuẩn (model)
    quotation: "dac-state-quotation",
    deposit: "dac-state-deposit",
    production: "dac-state-production",
    delivery: "dac-state-delivery",
    payment: "dac-state-payment",
    completed: "dac-state-completed",
    cancel: "dac-state-cancel",
    // nhãn hiển thị (VN)
    "Báo giá": "dac-state-quotation",
    "Đặt cọc": "dac-state-deposit",
    "Sản xuất": "dac-state-production",
    "Giao hàng": "dac-state-delivery",
    "Thu tiền": "dac-state-payment",
    "Hoàn thành": "dac-state-completed",
    Hủy: "dac-state-cancel",
  };

  root
    .querySelectorAll('div.o_field_badge[name="order_state_custom"] span.badge')
    .forEach((el) => {
      const label = (el.textContent || "").trim();
      const cls = map[label] || map[el.getAttribute("data-value")];
      if (!cls) return;
      el.classList.remove("text-bg-100", "text-bg-200", "text-bg-300");
      el.classList.add("dac-state-badge", cls);
    });
}

/* Service đúng chuẩn: start(env, services) */
const dacStateBadgeColor = {
  start(env /*, services */) {
    // lần đầu vào bất kỳ view
    applyStateBadgeClasses();

    // sau mỗi action (mở list/form, back, chuyển view…)
    env.bus.addEventListener("ACTION_MANAGER:AFTER", () =>
      setTimeout(applyStateBadgeClasses, 0)
    );

    // khi DOM thay đổi (paging, reload dữ liệu list…)
    const ob = new MutationObserver(() => applyStateBadgeClasses());
    ob.observe(document.body, { childList: true, subtree: true });
  },
};

registry.category("services").add("dac_state_badge_color", dacStateBadgeColor);
