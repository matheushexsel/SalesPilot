#!/bin/bash
# Inicializa o banco do piloto na primeira execução e depois sobe o Odoo normalmente.
set -e
DB="${SALESPILOT_DB:-salespilot}"
MARK="/var/lib/odoo/.salespilot_${DB}_initialized"

if [ ! -f "$MARK" ]; then
  echo ">>> SalesPilot: criando banco '$DB' em pt-BR e instalando módulos (primeira execução)..."
  odoo -c /etc/odoo/odoo.conf -d "$DB" \
       -i salespilot_restaurant,salespilot_demo \
       --without-demo=all --load-language=pt_BR --stop-after-init
  touch "$MARK"
  echo ">>> SalesPilot: banco pronto."
fi

exec odoo -c /etc/odoo/odoo.conf -d "$DB" "$@"
