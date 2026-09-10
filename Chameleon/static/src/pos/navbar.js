/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { useService } from "@web/core/utils/hooks";

patch(Navbar.prototype, {
  setup() {
    super.setup(...arguments);
    this.company = useService("company")
  },
});
