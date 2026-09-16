/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const NAV_ITEMS = [
    {
        key: "dashboard",
        label: "Dashboard",
        icon: "fa fa-home",
        actionXmlId: "dac_report.dac_sale_dashboard_action",
    },
    {
        key: "orders",
        label: "Đơn hàng",
        icon: "fa fa-list-ul",
        actionXmlId: "dac_erp.dac_sale_order_custom_action",
    },
    {
        key: "new_order",
        label: "Tạo đơn",
        icon: "fa fa-plus-circle",
        actionXmlId: null,
    },
    {
        key: "customers",
        label: "Khách hàng",
        icon: "fa fa-users",
        actionXmlId: "dac_erp.dac_res_partner_customer_action_sale",
    },
];

const CREATE_OPTIONS = [
    {
        key: "image",
        label: "Tạo từ ảnh",
        icon: "fa fa-camera",
        desc: "AI đọc hoá đơn",
    },
    {
        key: "pancake",
        label: "Pancake",
        icon: "fa fa-comments",
        desc: "Từ hội thoại khách",
    },
    {
        key: "blank",
        label: "Đơn mới",
        icon: "fa fa-file-text-o",
        desc: "Tạo trắng",
    },
];

export class DacMobileNavBar extends Component {
    static template = "dac_erp.DacMobileNavBar";
    static props = {};

    setup() {
        this.state = useState({ visible: false, showCreateMenu: false });
        this.navItems = NAV_ITEMS;
        this.createOptions = CREATE_OPTIONS;

        const action = useService("action");
        this._action = action;

        onWillStart(async () => {
            const isSale = await user.hasGroup("dac_erp.group_dac_erp_sale");
            const isManager = await user.hasGroup("dac_erp.group_dac_erp_manager");
            this.state.visible = isSale || isManager;
        });

        onMounted(() => {
            if (this.state.visible) {
                document.body.classList.add("dac-has-mobile-nav");
            }
        });

        onWillUnmount(() => {
            document.body.classList.remove("dac-has-mobile-nav");
        });
    }

    // Arrow function properties — this luôn được bind đúng
    onNavItemClick = (item) => {
        if (item.key === "new_order") {
            this.state.showCreateMenu = !this.state.showCreateMenu;
            return;
        }
        this.state.showCreateMenu = false;
        if (item.actionXmlId) {
            this._action.doAction(item.actionXmlId);
        }
    };

    closeCreateMenu = () => {
        this.state.showCreateMenu = false;
    };

    onCreateOptionClick = (optKey) => {
        this.state.showCreateMenu = false;
        if (optKey === "image") {
            // Mở InvoiceUploadDialog — client action đã registered trong JS registry
            this._action.doAction({
                type: "ir.actions.client",
                tag: "sale_ai_invoice_reader.open_upload_dialog",
                params: { order_id: false },
            });
        } else if (optKey === "pancake") {
            this._action.doAction("CRM_DAC.action_page_fm_conversation_queue");
        } else if (optKey === "blank") {
            this._action.doAction({
                type: "ir.actions.act_window",
                res_model: "sale.order",
                views: [[false, "form"]],
                target: "current",
            });
        }
    };
}

registry.category("main_components").add("DacMobileNavBar", {
    Component: DacMobileNavBar,
});
