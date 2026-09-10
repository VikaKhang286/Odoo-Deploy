from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home


class DacLoginController(Home):

    @http.route('/web/login', type='http', auth='none', sitemap=False)
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)
        if not hasattr(response, 'qcontext'):
            return response
        try:
            module = request.env['ir.module.module'].sudo().search(
                [('name', '=', 'dac_erp'), ('state', '=', 'installed')],
                limit=1,
            )
            version = module.installed_version or ''
        except Exception:
            version = ''
        response.qcontext['dac_version'] = version
        return response
