/** @odoo-module **/
import { WebClient } from "@web/webclient/webclient";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(WebClient.prototype, {
  setup() {
    super.setup();
    this.actionService = useService("action");
  },

  async _loadDefaultApp() {
    if (await user.hasGroup("base.group_system")) {
      return super._loadDefaultApp();
    }
    if (await user.hasGroup("dac_erp.group_dac_erp_manager")) {
      return this.actionService.doAction("dac_report.dac_manager_dashboard_action");
    }
    if (await user.hasGroup("dac_erp.group_dac_erp_sale")) {
      return this.actionService.doAction("dac_report.dac_sale_dashboard_action");
    }
    if (await user.hasGroup("dac_erp.group_dac_erp_design_production")) {
      return this.actionService.doAction("dac_erp.dac_production_dashboard_action");
    }
    if (await user.hasGroup("dac_erp.group_dac_erp_design")) {
      return this.actionService.doAction("dac_erp.dac_design_dashboard_action");
    }
    if (await user.hasGroup("dac_erp.group_dac_erp_production")) {
      return this.actionService.doAction("dac_erp.dac_production_dashboard_action");
    }
    return super._loadDefaultApp();
  },
});
