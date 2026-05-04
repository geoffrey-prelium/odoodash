#!/bin/bash
# Script de déploiement OdooDash sur Google Cloud Run

gcloud run deploy odoodash \
  --source . \
  --region=europe-west9 \
  --allow-unauthenticated \
  --add-cloudsql-instances=odoodash:europe-west9:odoodash-instance \
  --update-env-vars="SETTINGS_NAME=django-settings" \
  --command="./entrypoint.sh" \
  --args="gunicorn,--bind=0.0.0.0:8080,--timeout=900,OdooDash_project.wsgi"
