/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

const SALE_ORDER_XXL_MIN_WIDTH = 1024;

patch(FormController.prototype, {
  get className() {
    const className = { ...super.className };

    // if (this.props.resModel !== "sale.order" || this.env.inDialog) {
    //   return className;
    // }

    // Odoo normally enables this layout only at its XXL breakpoint. Sales
    // orders need the wide form/chatter layout from 1024px instead.
    if (window.innerWidth >= SALE_ORDER_XXL_MIN_WIDTH) {
      className["o_xxl_form_view"] = true;
    } else {
      delete className["o_xxl_form_view"];
    }

    return className;
  },
});
