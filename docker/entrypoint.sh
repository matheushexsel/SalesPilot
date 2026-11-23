#!/bin/bash
# Inicializa o banco do piloto na primeira execução e depois sobe o Odoo normalmente.
# Usa as mesmas variáveis da imagem oficial (HOST/USER/PASSWORD) para checar se o banco existe,
# em vez de um arquivo-marcador: assim, recriar só o volume do PostgreSQL refaz a instalação.
set -e
DB="${SALESPILOT_DB:-salespilot}"
DB_HOST="${HOST:-db}"
DB_USER="${USER:-odoo}"
DB_PASSWORD="${PASSWORD:-odoo}"

echo ">>> SalesPilot: aguardando o PostgreSQL em $DB_HOST..."
for i in $(seq 1 30); do
  if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d postgres -c "select 1" >/dev/null 2>&1; then break; fi
  sleep 2
done

if ! PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d postgres -lqt 2>/dev/null | cut -d '|' -f1 | grep -qw "$DB"; then
  echo ">>> SalesPilot: criando banco '$DB' em pt-BR e instalando módulos (primeira execução, ~2 min)..."
  odoo -c /etc/odoo/odoo.conf --db_host="$DB_HOST" --db_user="$DB_USER" --db_password="$DB_PASSWORD" -d "$DB" \
       -i salespilot_restaurant,salespilot_demo \
       --without-demo=all --load-language=pt_BR --stop-after-init
  echo ">>> SalesPilot: banco pronto."
fi

exec odoo -c /etc/odoo/odoo.conf --db_host="$DB_HOST" --db_user="$DB_USER" --db_password="$DB_PASSWORD" -d "$DB"
