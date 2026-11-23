#!/bin/bash
# Roda o piloto sem Docker, a partir do código-fonte do Odoo 18 Community.
# Pré-requisitos: PostgreSQL local com usuário odoo/odoo (createdb), Python 3.10-3.12 com venv (python3-venv), git,
# e as libs de build do Odoo (libpq-dev, libxml2-dev, libxslt1-dev, libjpeg-dev, zlib1g-dev).
#   ./scripts/run_local.sh            # cria o banco (1ª vez) e sobe em http://localhost:8069
#   ./scripts/run_local.sh --reset    # apaga e recria o banco com os dados de demonstração
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ODOO_SRC="${ODOO_SRC:-$ROOT/../odoo18}"
VENV="${VENV:-$ROOT/../odoo-venv}"
DB="${SALESPILOT_DB:-salespilot}"
CONF="$ROOT/.odoo-local.conf"

if [ ! -d "$ODOO_SRC" ]; then
  echo ">>> Clonando Odoo 18 Community em $ODOO_SRC"
  git clone --depth 1 --branch 18.0 https://github.com/odoo/odoo.git "$ODOO_SRC"
fi
if [ ! -d "$VENV" ]; then
  echo ">>> Criando virtualenv em $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip wheel
  grep -v "^psycopg2\|^python-ldap" "$ODOO_SRC/requirements.txt" > /tmp/sp-req.txt
  "$VENV/bin/pip" install -q -r /tmp/sp-req.txt psycopg2-binary
fi
cat > "$CONF" <<CFG
[options]
addons_path = $ODOO_SRC/addons,$ROOT/addons
data_dir = $ROOT/.odoo-data
db_host = localhost
db_port = 5432
db_user = odoo
db_password = odoo
http_port = 8069
workers = 0
CFG

if [ "$1" == "--reset" ]; then
  echo ">>> Apagando banco $DB"
  if PGPASSWORD=odoo psql -h localhost -U odoo -lqt | cut -d '|' -f1 | grep -qw "$DB"; then
    PGPASSWORD=odoo dropdb -h localhost -U odoo "$DB" || { echo "!!! Não foi possível apagar o banco (ainda há um Odoo conectado?)"; exit 1; }
  fi
fi
if ! PGPASSWORD=odoo psql -h localhost -U odoo -lqt 2>/dev/null | cut -d '|' -f1 | grep -qw "$DB"; then
  echo ">>> Criando banco $DB e instalando módulos (leva ~1 min)"
  "$VENV/bin/python" "$ODOO_SRC/odoo-bin" -c "$CONF" -d "$DB" -i salespilot_restaurant,salespilot_demo \
      --without-demo=all --load-language=pt_BR --stop-after-init
fi
echo ">>> Subindo Odoo em http://localhost:8069 (admin / admin)"
exec "$VENV/bin/python" "$ODOO_SRC/odoo-bin" -c "$CONF" -d "$DB"
