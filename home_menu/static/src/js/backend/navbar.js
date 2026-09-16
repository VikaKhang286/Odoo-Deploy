/** @odoo-module **/
import { NavBar } from "@web/webclient/navbar/navbar";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { Component, onWillStart, useState, xml } from "@odoo/owl";
import { usePopover } from "@web/core/popover/popover_hook";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";

// Keep the existing DAC-branded button; render its menu through Odoo's overlay.
class HomeAppsMenu extends Component {
  static props = {
    apps: Array,
    getHref: Function,
    onSelect: Function,
  };
  static template = xml`
    <div class="o_home_apps_menu py-1" style="max-height: 80vh; overflow-y: auto;">
      <a t-foreach="props.apps" t-as="app" t-key="app.id"
         class="dropdown-item o_app" role="menuitem"
         t-att-href="props.getHref(app)"
         t-att-data-menu-xmlid="app.xmlid" t-att-data-section="app.id"
         t-on-click="(event) => this.selectApp(event, app)">
        <t t-esc="app.name"/>
      </a>
    </div>`;

  selectApp(event, app) {
    // Preserve the browser's open-in-new-tab behavior.
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    this.props.onSelect(app);
  }
}

patch(NavBar.prototype, {
  setup() {
    super.setup(...arguments);
    this.state = useState({
      ...this.state,
      isMenuBlocked: false,
      rootMenuActionID: 0,
    });
    this.homeAppsPopover = usePopover(HomeAppsMenu, {
      position: "bottom-start",
      arrow: false,
      popoverClass: "o-dropdown--menu dropdown-menu d-block",
      popoverRole: "menu",
      closeOnEscape: true,
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
      callback: (event) => this.onHomeButtonClick(event),
    };
  },

  onHomeButtonClick(event) {
    if (this.homeAppsPopover.isOpen) {
      this.homeAppsPopover.close();
      return;
    }
    // currentTarget is the branded button, even when its icon was clicked.
    const target = event?.currentTarget;
    if (!target) return;
    this.homeAppsPopover.open(target, {
      apps: this.menuService.getApps(),
      getHref: (app) => this.getMenuItemHref(app),
      onSelect: (app) => {
        this.homeAppsPopover.close();
        this.onNavBarDropdownItemSelection(app);
      },
    });
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
