/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

export class SaleOrderNoteEditableListController extends ListController {
  createRecord() {
    window.location.assign("/odoo/sales/new");
  }
}

/**
 * Keep the note column inline-editable while preserving the standard
 * click-to-open behavior everywhere else in the native Sales list.
 */
export class SaleOrderNoteEditableListRenderer extends ListRenderer {
  async onCellClicked(record, column, ev) {
    if (column.type === "field" && column.name === "list_note") {
      return super.onCellClicked(record, column, ev);
    }

    if (ev.target.special_click) {
      return;
    }

    return this.props.openRecord(record);
  }
}

registry.category("views").add("dac_sale_note_editable_list", {
  ...listView,
  Controller: SaleOrderNoteEditableListController,
  Renderer: SaleOrderNoteEditableListRenderer,
});
