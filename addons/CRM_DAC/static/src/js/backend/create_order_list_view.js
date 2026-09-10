/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";

/**
 * List view sale.order với 2 dropdown thao tác trên header control panel:
 *   - "Tạo đơn"  → Đơn khách vãn lai (đơn mới trắng) | Đơn khách Pancake (wizard)
 *   - "Nhập đơn" → Nhập đơn thủ công (wizard gõ tay) | Nhập đơn từ ảnh (AI)
 * Thay cho các nút header phẳng cũ. Kích hoạt qua js_class="dac_create_order_list".
 */
export class DacCreateOrderListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async _doServerAction(method) {
        const action = await this.orm.call("sale.order", method, [[]]);
        if (action) {
            this.action.doAction(action);
        }
    }

    onCreateWalkIn() {
        // Đơn khách vãn lai = đơn mới trắng (thay nút "Mới" mặc định)
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            views: [[false, "form"]],
            target: "current",
        });
    }

    onCreatePancake() {
        this._doServerAction("action_open_create_order_wizard_from_list");
    }

    onImportManual() {
        this._doServerAction("action_open_manual_import_wizard");
    }

    onImportImage() {
        this._doServerAction("action_open_invoice_upload_from_list");
    }
}

DacCreateOrderListController.template = "CRM_DAC.DacCreateOrderListView";
DacCreateOrderListController.components = {
    ...ListController.components,
    Dropdown,
    DropdownItem,
};

registry.category("views").add("dac_create_order_list", {
    ...listView,
    Controller: DacCreateOrderListController,
});
