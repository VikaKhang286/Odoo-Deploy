FROM odoo:18.0

USER root

COPY ./addons /mnt/extra-addons
COPY ./config/odoo.conf /etc/odoo/odoo.conf
COPY ./render-entrypoint.sh /render-entrypoint.sh

RUN chmod +x /render-entrypoint.sh \
    && chown -R odoo:odoo /mnt/extra-addons \
    && chown odoo:odoo /etc/odoo/odoo.conf \
    && chown odoo:odoo /render-entrypoint.sh

USER odoo

ENTRYPOINT ["/render-entrypoint.sh"]
