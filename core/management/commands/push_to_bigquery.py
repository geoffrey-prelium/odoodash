# core/management/commands/push_to_bigquery.py
import os
from django.conf import settings
from django.core.management.base import BaseCommand
import pandas as pd
from google.cloud import bigquery
from sqlalchemy import create_engine

class Command(BaseCommand):
    help = 'Extrait toutes les tables de la base de données et les pousse vers BigQuery.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Début de la synchronisation de toutes les tables vers BigQuery ---"))

        db_conf = settings.DATABASES['default']
        
        # Construit l'URL de connexion pour SQLAlchemy
        db_url = (
            f"postgresql+psycopg2://{db_conf['USER']}:{db_conf['PASSWORD']}"
            f"@{db_conf.get('HOST', 'localhost')}:{db_conf.get('PORT', 5432)}/{db_conf['NAME']}"
        )
        
        # Pour Cloud SQL, on utilise le socket
        if 'host' in db_conf.get('OPTIONS', {}):
             db_url = f"postgresql+psycopg2://{db_conf['USER']}:{db_conf['PASSWORD']}@/{db_conf['NAME']}?host={db_conf['OPTIONS']['host']}"

        try:
            engine = create_engine(db_url)
            
            with engine.connect() as connection:
                # Requête pour lister les tables
                inspector = sqlalchemy.inspect(engine)
                all_tables = inspector.get_table_names(schema='public')

                tables_to_ignore = [
                    'django_migrations', 'django_content_type', 'auth_group', 'auth_group_permissions',
                    'auth_permission', 'auth_user', 'auth_user_groups', 'auth_user_user_permissions',
                    'django_admin_log', 'django_session',
                ]
                tables_to_sync = [table for table in all_tables if table not in tables_to_ignore]
                self.stdout.write(f"Tables à synchroniser : {', '.join(tables_to_sync)}")

                project_id = os.environ.get("PROJECT_ID", "odoodash")
                dataset_id = "odoodash_dataset"
                bigquery_client = bigquery.Client()

                for table_name in tables_to_sync:
                    self.stdout.write(f"--- Traitement de la table '{table_name}' ---")
                    
                    df = pd.read_sql_table(table_name, connection)
                    self.stdout.write(f"{len(df)} lignes lues.")
                    
                    table_id = f"{project_id}.{dataset_id}.{table_name}"
                    self.stdout.write(f"Chargement vers BigQuery (table: {table_id})...")
                    
                    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
                    job = bigquery_client.load_table_from_dataframe(df, table_id, job_config=job_config)
                    job.result()
                    
                    self.stdout.write(self.style.SUCCESS(f"Table '{table_name}' synchronisée avec succès ({job.output_rows} lignes écrites)."))

            self.stdout.write(self.style.SUCCESS("\nSynchronisation de toutes les tables terminée !"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Une erreur est survenue : {e}"))