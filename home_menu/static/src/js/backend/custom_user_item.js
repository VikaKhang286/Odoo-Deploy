/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";

const userMenuRegistry = registry.category("user_menuitems");
// Xóa các item mặc định
userMenuRegistry.remove("documentation");
userMenuRegistry.remove("support");
userMenuRegistry.remove("shortcuts");
userMenuRegistry.remove("install_pwa"); // Install App
userMenuRegistry.remove("odoo_account"); // My Odoo.com Account
userMenuRegistry.remove("log_out");

// Ghi đè hàm add để chặn Onboarding
const origAdd = userMenuRegistry.add;
userMenuRegistry.add = function (id, ...args) {
  if (id === "web_tour.tour_enabled") {
    return; // Không thêm Onboarding
  }
  return origAdd.call(this, id, ...args);
};

// Thêm lại "Logout"
userMenuRegistry.add("logout_custom", (env) => ({
  type: "item",
  id: "logout_custom",
  description: _t("Đăng xuất"),
  href: `${browser.location.origin}/web/session/logout`,
  callback: () => {
    browser.location.href = "/web/session/logout";
  },
  sequence: 100,
}));
