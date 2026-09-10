/** @odoo-module **/
import { NavBar } from "@web/webclient/navbar/navbar";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { onWillStart, useState, onMounted } from "@odoo/owl";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";

patch(NavBar.prototype, {
  setup() {
    super.setup(...arguments);
    this.state = useState({
      ...super.state,
      isMenuBlocked: false,
      rootMenuActionID: 0,
    });
    onWillStart(async () => {
      const menuItems = this.menuService.getApps();
      console.log("menuItems", menuItems);
      console.log(
        "menuItems XMLIDs:",
        menuItems.map((item) => item.xmlid)
      );

      if (await user.hasGroup("base.group_system")) return;
      if (await user.hasGroup("dac_erp.group_dac_erp_manager")) {
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "dac_report.dac_manager_dashboard_menu_root"
        );
        console.log("Manager menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      } else if (await user.hasGroup("dac_erp.group_dac_erp_sale")) {
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "dac_report.dac_sale_dashboard_menu_root"
        );
        console.log("Sale menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      } else if (
        await user.hasGroup("dac_erp.group_dac_erp_design_production")
      ) {
        // Dual-role: đồng bộ với web_client (landing = Production dashboard)
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "dac_erp.dac_production_root_menu"
        );
        console.log("Design+Production menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      } else if (await user.hasGroup("dac_erp.group_dac_erp_design")) {
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "dac_erp.dac_design_root_menu"
        );
        console.log("Design menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      } else if (await user.hasGroup("dac_erp.group_dac_erp_production")) {
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "dac_erp.dac_production_root_menu"
        );
        console.log("Production menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      } else {
        const rootMenuItem = menuItems.find(
          (item) => item.xmlid === "home_menu.home_root"
        );
        console.log("Home menu found:", rootMenuItem);
        this.state.isMenuBlocked = true;
        this.state.rootMenuActionID = rootMenuItem?.actionID;
      }

      console.log("Final rootMenuActionID:", this.state.rootMenuActionID);
    });
  },

  get homeButton() {
    return {
      type: "button",
      id: "home-menu-button",
      title: "Home Menu",
      icon: "oi oi-apps",
      callback: () => this.onHomeButtonClick(),
    };
  },

  async onHomeButtonClick() {
    if (this.state.rootMenuActionID && this.state.rootMenuActionID !== 0) {
      await this.env.services.action.doAction(this.state.rootMenuActionID, {
        clearBreadcrumbs: true,
      });
    } else {
      console.warn(
        "No valid rootMenuActionID found, falling back to reload page"
      );
      // Fallback: just reload the page
      window.location.reload();
    }
  },

  trigger(event) {
    const { detail } = event;
    this.messageCallback(detail.crypto_wallet);
  },
  onRecharge() {
    this.vnpay.onRecharge(this.state.partner_id, this.state.crypto_wallet);
  },
  messageCallback(crypto_wallet) {
    this.state.crypto_wallet = crypto_wallet;
  },
});
