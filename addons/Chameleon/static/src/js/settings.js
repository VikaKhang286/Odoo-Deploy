/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

patch(WebClient.prototype, {
  /**
   * @override
   */
  setup() {
    super.setup();
    this.rpc = rpc;
    this.updateTitle();
    this.updateLogo();
  },

  async updateTitle() {
    const title = await this.rpc(
      "/web/dataset/call_kw/ir.config_parameter/get_param",
      {
        model: "ir.config_parameter",
        method: "get_param",
        args: ["change_odoo_theme_header_color.website_title"],
        kwargs: {},
      }
    );

    this.title.setParts({ zopenerp: title || "" });
  },

  async updateLogo() {
    const image_1024 = await this.rpc(
      "/web/dataset/call_kw/ir.config_parameter/get_param",
      {
        model: "ir.config_parameter",
        method: "get_param",
        args: ["change_odoo_theme_header_color.image_1024"],
        kwargs: {},
      }
    );
    const backendIconEl = document.querySelector("link[rel~='icon']");
    // Save initial backend values.
    backendIconEl.href = "data:image/png;base64," + image_1024;
  },
});
