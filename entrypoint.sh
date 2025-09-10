#!/bin/sh

# Ce script s'assure que la base de données est prête et qu'un admin existe.

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Creating initial superuser if it does not exist..."
python manage.py create_initial_superuser

echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 OdooDash_project.wsgi

