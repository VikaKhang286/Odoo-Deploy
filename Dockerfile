FROM odoo:18.0

USER root

COPY ./addons /mnt/extra-addons

COPY ./config/odoo.conf /etc/odoo/odoo.conf

RUN chown -R odoo:odoo /mnt/extra-addons \
    && chown odoo:odoo /etc/odoo/odoo.conf

USER odoo