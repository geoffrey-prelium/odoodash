# core/management/commands/push_to_bigquery.py
import os
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand
import pandas as pd
from google.cloud import bigquery
from sqlalchemy import create_engine
import sqlalchemy

class Command(BaseCommand):
    help = 'Extrait toutes les tables de la base de données et les pousse vers BigQuery.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Début de la synchronisation de toutes les tables vers BigQuery ---"))

        db_conf = settings.DATABASES['default']
        
        # Construit l'URL de connexion pour SQLAlchemy en utilisant le socket du proxy Cloud SQL
        db_url = f"postgresql+psycopg2://{db_conf['USER']}:{db_conf['PASSWORD']}@/{db_conf['NAME']}?host={db_conf['OPTIONS']['host']}"

        try:
            engine = create_engine(db_url)
            
            with engine.connect() as connection:
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

                    # --- CORRECTION FINALE ---
                    # On convertit toutes les colonnes de type UUID en chaînes de caractères
                    for col in df.columns:
                        # On ne traite que les colonnes qui contiennent des objets (potentiellement des UUID)
                        if pd.api.types.is_object_dtype(df[col]):
                            
                            # On retire les valeurs nulles pour inspecter le premier élément
                            col_non_null = df[col].dropna()

                            # On vérifie que la colonne n'est pas entièrement vide avant d'accéder au premier élément
                            if not col_non_null.empty:
                                first_valid = col_non_null.iloc[0]
                                if isinstance(first_valid, uuid.UUID):
                                    self.stdout.write(f"Conversion de la colonne UUID '{col}' en string...")
                                    df[col] = df[col].astype(str)
                    # --- FIN DE LA CORRECTION ---

                    table_id = f"{project_id}.{dataset_id}.{table_name}"
                    self.stdout.write(f"Chargement vers BigQuery (table: {table_id})...")
                    
                    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
                    job = bigquery_client.load_table_from_dataframe(df, table_id, job_config=job_config)
                    job.result()
                    
                    self.stdout.write(self.style.SUCCESS(f"Table '{table_name}' synchronisée avec succès ({job.output_rows} lignes écrites)."))

            self.stdout.write(self.style.SUCCESS("\nSynchronisation de toutes les tables terminée !"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Une erreur est survenue : {e}"))