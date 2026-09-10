/** @odoo-module **/
import { WebClient } from "@web/webclient/webclient";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { onWillStart, useState, onMounted } from "@odoo/owl";
patch(WebClient.prototype, {
  setup() {
    super.setup();
  },

  async _loadDefaultApp() {
    // Selects the first root menu if any
    let root;
    let firstApp;
    if (await user.hasGroup("base.group_system"))
      return super._loadDefaultApp();

    if (await user.hasGroup("dac_erp.group_dac_erp_manager")) {
      const filteredArray = this.menuService
        .getApps()
        .filter(
          (item) => item.xmlid === "dac_report.dac_manager_dashboard_menu_root"
        );
      root = filteredArray[0];
      firstApp = root?.appID;
    } else if (await user.hasGroup("dac_erp.group_dac_erp_sale")) {
      const filteredArray = this.menuService
        .getApps()
        .filter(
          (item) => item.xmlid === "dac_report.dac_sale_dashboard_menu_root"
        );
      root = filteredArray[0];
      firstApp = root?.appID;
    } else if (await user.hasGroup("dac_erp.group_dac_erp_design")) {
      const filteredArray = this.menuService
        .getApps()
        .filter((item) => item.xmlid === "dac_erp.dac_design_root_menu");
      root = filteredArray[0];
      firstApp = root?.appID;
    } else if (await user.hasGroup("dac_erp.group_dac_erp_production")) {
      const filteredArray = this.menuService
        .getApps()
        .filter((item) => item.xmlid === "dac_erp.dac_production_root_menu");
      root = filteredArray[0];
      firstApp = root?.appID;
    } else {
      const filteredArray = this.menuService
        .getApps()
        .filter((item) => item.xmlid === "home_menu.home_root");
      root = filteredArray[0];
      firstApp = root?.appID;
    }

    if (firstApp) {
      return this.menuService.selectMenu(firstApp);
    }
    // const filteredArray = this.menuService
    //   .getApps()
    //   .filter((item) => item.xmlid === "home_menu.home_root");
    // const root = filteredArray[0];
    // const firstApp = root?.appID;
    // if (firstApp) {
    //   return this.menuService.selectMenu(firstApp);
    // }
  },
});
