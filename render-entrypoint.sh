#!/bin/bash

set -e

cat >> /etc/odoo/odoo.conf <<EOF

db_host = ${DB_HOST}
db_port = ${DB_PORT:-5432}
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
EOF

exec odoo \
    -c /etc/odoo/odoo.conf \
    --http-port="${PORT:-8069}"
