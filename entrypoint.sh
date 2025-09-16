#!/bin/sh

# Ce script s'assure que la base de données est prête et qu'un admin existe.

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Creating/Updating initial superuser..."
python manage.py create_initial_superuser

echo "Starting Gunicorn server with increased timeout..."
# Ajout du paramètre --timeout 300 pour autoriser des requêtes jusqu'à 5 minutes
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 300 OdooDash_project.wsgi

