#!/bin/bash
set -e

# Exécuter les migrations
echo "--- Exécution des migrations ---"
python manage.py migrate --noinput
echo "--- Migrations terminées ---"

# Lancer la commande passée en argument (gunicorn)
exec "$@"
