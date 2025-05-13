# core/management/commands/fetch_indicators.py

import xmlrpc.client
import logging
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings  # Pour accéder à FERNET_KEY
from datetime import datetime, timedelta

# Importer les modèles Django
from core.models import ConfigurationCabinet, ClientsOdoo, IndicateursHistoriques, \
    ClientOdooStatus  # <-- AJOUT ClientOdooStatus
# Importer les fonctions de chiffrement/déchiffrement
from core.utils import decrypt_value

logger = logging.getLogger(__name__)


def connect_odoo(url, db, username, password):
    """
    Tente de se connecter à Odoo.
    Retourne uid, common_proxy, object_proxy, error_message.
    error_message est None si la connexion réussit, sinon une chaîne d'erreur.
    """
    error_message = None
    try:
        common_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        version = common_proxy.version()
        logger.info(f"Connecté à Odoo {url} (Version: {version.get('server_version')})")

        uid = common_proxy.authenticate(db, username, password, {})
        if not uid:
            error_message = f"Échec de l'authentification Odoo pour {username} sur {db}@{url}"
            logger.error(error_message)
            return None, None, None, error_message

        object_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        logger.info(f"Authentification réussie pour {username} (UID: {uid})")
        return uid, common_proxy, object_proxy, None  # Pas d'erreur

    except xmlrpc.client.Fault as e:
        error_message = f"Erreur XML-RPC Odoo ({url}): {e.faultCode} - {e.faultString}"
        logger.error(error_message)
        return None, None, None, error_message
    except ConnectionRefusedError as e:
        error_message = f"Connexion refusée par le serveur Odoo ({url}): {e}"
        logger.error(error_message)
        return None, None, None, error_message
    except Exception as e:
        error_message = f"Erreur de connexion Odoo inattendue ({url}): {e}"
        logger.error(error_message, exc_info=True)
        return None, None, None, error_message


class Command(BaseCommand):
    help = 'Extrait les indicateurs depuis les instances Odoo configurées et les sauvegarde en base de données.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Début de l'extraction des indicateurs ---"))

        # 1. Récupérer la configuration de l'Odoo Cabinet
        try:
            config_cabinet = ConfigurationCabinet.objects.first()
            if not config_cabinet:
                raise CommandError("Configuration du cabinet non trouvée. Veuillez la configurer via l'admin.")
            self.stdout.write(
                f"Configuration cabinet trouvée: URL={config_cabinet.firm_odoo_url}, DB={config_cabinet.firm_odoo_db}")
        except Exception as e:
            raise CommandError(f"Erreur lors de la lecture de la configuration cabinet: {e}")

        # 2. Déchiffrer la clé API du cabinet
        firm_api_key = decrypt_value(config_cabinet.firm_odoo_encrypted_api_key)
        firm_uid = None
        firm_object_proxy = None
        if not firm_api_key:
            self.stderr.write(self.style.WARNING(
                f"Impossible de déchiffrer la clé API pour la config cabinet. La récupération des collaborateurs échouera."))
        else:
            self.stdout.write(self.style.SUCCESS("Clé API du cabinet déchiffrée avec succès."))
            firm_uid, _, firm_object_proxy, firm_conn_error = connect_odoo(
                config_cabinet.firm_odoo_url,
                config_cabinet.firm_odoo_db,
                config_cabinet.firm_odoo_api_user,
                firm_api_key
            )
            if not firm_uid:
                self.stderr.write(self.style.WARNING(
                    f">>> Attention: Échec de la connexion à l'Odoo du cabinet: {firm_conn_error}. La récupération des collaborateurs assignés échouera."))
                firm_object_proxy = None
            else:
                self.stdout.write(self.style.SUCCESS("Connecté avec succès à l'Odoo du cabinet."))

        clients_config = ClientsOdoo.objects.all()
        if not clients_config:
            self.stdout.write(self.style.WARNING("Aucun client Odoo n'est configuré."))
            self.stdout.write(self.style.SUCCESS("--- Fin de l'extraction (aucun client) ---"))
            return

        self.stdout.write(f"Traitement de {clients_config.count()} client(s) Odoo configuré(s)...")
        current_extraction_run_timestamp = timezone.now()
        self.stdout.write(f"Timestamp pour cette exécution : {current_extraction_run_timestamp}")

        current_year = current_extraction_run_timestamp.year
        first_day_of_year = datetime(current_year, 1, 1).strftime('%Y-%m-%d')
        date_30_days_ago = (current_extraction_run_timestamp.date() - timedelta(days=30)).strftime('%Y-%m-%d')

        for client_conf in clients_config:
            self.stdout.write(self.style.NOTICE(f"\n--- Traitement du client : {client_conf.client_name} ---"))
            client_api_key = decrypt_value(client_conf.client_odoo_encrypted_api_key)

            last_attempt_time = timezone.now()  # Timestamp pour la tentative de connexion

            if not client_api_key:
                error_msg = "Impossible de déchiffrer la clé API."
                self.stderr.write(self.style.ERROR(f"{error_msg} pour {client_conf.client_name}. Skipping..."))
                ClientOdooStatus.objects.update_or_create(
                    client=client_conf,
                    defaults={
                        'last_connection_attempt': last_attempt_time,
                        'connection_successful': False,
                        'last_error_message': error_msg
                    }
                )
                continue
            self.stdout.write(f"Clé API déchiffrée pour {client_conf.client_name}.")

            self.stdout.write(
                f"Tentative de connexion à {client_conf.client_odoo_url} (DB: {client_conf.client_odoo_db})...")

            uid_client, _, object_proxy_client, connection_error_msg = connect_odoo(
                client_conf.client_odoo_url,
                client_conf.client_odoo_db,
                client_conf.client_odoo_api_user,
                client_api_key
            )

            # Enregistrer/Mettre à jour le statut de la connexion
            status_defaults = {
                'last_connection_attempt': last_attempt_time,
                'connection_successful': bool(uid_client),
                'last_error_message': connection_error_msg if connection_error_msg else None
            }
            status_obj, created = ClientOdooStatus.objects.update_or_create(
                client=client_conf,  # Le champ OneToOneField est nommé 'client' dans ClientOdooStatus
                defaults=status_defaults
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"   - Statut de connexion initialisé pour {client_conf.client_name}."))
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"   - Statut de connexion mis à jour pour {client_conf.client_name}."))

            if not uid_client:
                self.stderr.write(self.style.ERROR(
                    f">>> Échec connexion Odoo pour {client_conf.client_name}. {connection_error_msg if connection_error_msg else ''} Skipping indicateurs..."))
                continue

            self.stdout.write(
                self.style.SUCCESS(f"Connecté avec succès à Odoo pour {client_conf.client_name} (UID: {uid_client})."))

            # ... (Section 5c pour récupérer le collaborateur - code inchangé) ...
            assigned_collab_id = None
            collaborator_display_name = "N/A"
            final_assigned_collab_id_str = "0"
            if firm_uid and firm_object_proxy:
                try:
                    self.stdout.write(
                        f"   - Recherche du partenaire client '{client_conf.client_name}' dans l'Odoo cabinet via son URL...")
                    technical_field_name_for_client_url = 'x_odoo_database'
                    partner_domain = [(technical_field_name_for_client_url, '=', client_conf.client_odoo_url)]
                    partner_ids = firm_object_proxy.execute_kw(config_cabinet.firm_odoo_db, firm_uid, firm_api_key,
                                                               'res.partner', 'search', [partner_domain], {'limit': 1})
                    if partner_ids:
                        partner_id = partner_ids[0]
                        self.stdout.write(
                            f"   - Partenaire client trouvé (ID: {partner_id}). Lecture du champ collaborateur...")
                        partner_data = firm_object_proxy.execute_kw(config_cabinet.firm_odoo_db, firm_uid, firm_api_key,
                                                                    'res.partner', 'read', [[partner_id]],
                                                                    {'fields': ['x_collaborateur_1']})
                        collaborator_info = partner_data[0].get('x_collaborateur_1') if partner_data else None
                        if collaborator_info and isinstance(collaborator_info, (list, tuple)) and len(
                                collaborator_info) >= 1:
                            assigned_collab_id = collaborator_info[0];
                            collaborator_display_name = collaborator_info[1]
                            self.stdout.write(self.style.SUCCESS(
                                f"   - Collaborateur (partenaire) lié trouvé (ID: {assigned_collab_id}, Nom: {collaborator_display_name})"))
                        else:
                            self.stdout.write(self.style.WARNING(
                                f"   - Champ collaborateur 'x_collaborateur_1' vide sur la fiche partenaire (ID: {partner_id})."))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"   - Partenaire client avec URL '{client_conf.client_odoo_url}' (via champ '{technical_field_name_for_client_url}') non trouvé dans l'Odoo cabinet."))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"   - Erreur lors de la récupération du collaborateur depuis l'Odoo cabinet: {e}"))
            else:
                self.stdout.write(self.style.WARNING(
                    "   - Connexion à l'Odoo cabinet non disponible, impossible de récupérer le collaborateur assigné."))
            if assigned_collab_id is not None:
                final_assigned_collab_id_str = str(assigned_collab_id)
            else:
                final_assigned_collab_id_str = "0"
            self.stdout.write(
                f"Collaborateur assigné -> ID Partenaire: {final_assigned_collab_id_str}, Nom Affiché: {collaborator_display_name}")

            indicators_data = {}
            self.stdout.write(f"Début extraction indicateurs pour {client_conf.client_name}...")
            # ... (Logique d'extraction des indicateurs : date_cloture_annuelle, nb_lignes_ecritures_annee_courante, etc. - code inchangé) ...
            company_id = 1
            try:
                user_info = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client, client_api_key,
                                                           'res.users', 'read', [[uid_client]],
                                                           {'fields': ['company_id']})
                if user_info and user_info[0].get('company_id'): company_id = user_info[0]['company_id'][0]
            except Exception:
                logger.warning(
                    f"Impossible de récupérer company_id pour client {client_conf.client_name}, utilisation de l'ID 1 par défaut.")
            indicator_name_fiscal_closing = "date_cloture_annuelle"
            try:
                self.stdout.write(f"   - Recherche '{indicator_name_fiscal_closing}' depuis res.company...")
                company_data_closing = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client,
                                                                      client_api_key, 'res.company', 'read',
                                                                      [[company_id]], {'fields': ['fiscalyear_last_day',
                                                                                                  'fiscalyear_last_month']})
                if company_data_closing and company_data_closing[0].get('fiscalyear_last_day') and company_data_closing[
                    0].get('fiscalyear_last_month'):
                    day_str = company_data_closing[0].get('fiscalyear_last_day');
                    month_str = company_data_closing[0].get('fiscalyear_last_month')
                    if day_str is not None and month_str is not None and day_str is not False and month_str is not False:
                        try:
                            day = int(day_str); month = int(month_str); closing_date_str = f"{day:02d}/{month:02d}";
                            indicators_data[indicator_name_fiscal_closing] = closing_date_str; self.stdout.write(
                                self.style.SUCCESS(f"   - {indicator_name_fiscal_closing}: OK ({closing_date_str})"))
                        except (ValueError, TypeError) as conversion_error:
                            self.stderr.write(self.style.ERROR(
                                f"   - Erreur conversion jour/mois pour '{indicator_name_fiscal_closing}': {conversion_error} (valeurs reçues: jour='{day_str}', mois='{month_str}')"));
                            indicators_data[indicator_name_fiscal_closing] = None
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"   - {indicator_name_fiscal_closing}: Valeurs jour/mois vides ou False reçues de res.company ID {company_id}."));
                        indicators_data[indicator_name_fiscal_closing] = None
                else:
                    self.stdout.write(self.style.WARNING(
                        f"   - {indicator_name_fiscal_closing}: Champs jour/mois ('fiscalyear_last_day'/'month') non trouvés ou vides sur res.company ID {company_id}."));
                    indicators_data[indicator_name_fiscal_closing] = None
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"   - Erreur extraction '{indicator_name_fiscal_closing}': {e}"));
                indicators_data[indicator_name_fiscal_closing] = None
            indicator_name_move_lines_current_year = "nb_lignes_ecritures_annee_courante"
            try:
                self.stdout.write(
                    f"   - Recherche '{indicator_name_move_lines_current_year}' (depuis {first_day_of_year})...")
                domain_move_lines = [('date', '>=', first_day_of_year), ('move_id.state', '=', 'posted')]
                count = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client, client_api_key,
                                                       'account.move.line', 'search_count', [domain_move_lines])
                indicators_data[indicator_name_move_lines_current_year] = count
                self.stdout.write(self.style.SUCCESS(f"   - {indicator_name_move_lines_current_year}: OK ({count})"))
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"   - Erreur extraction '{indicator_name_move_lines_current_year}': {e}"));
                indicators_data[indicator_name_move_lines_current_year] = None
            indicator_name_quotes_30d = "nb_devis_envoyes_30j"
            try:
                self.stdout.write(f"   - Recherche '{indicator_name_quotes_30d}'...")
                domain_quotes = [('state', '=', 'sent'), ('date_order', '>=', date_30_days_ago)]
                count = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client, client_api_key,
                                                       'sale.order', 'search_count', [domain_quotes])
                indicators_data[indicator_name_quotes_30d] = count
                self.stdout.write(self.style.SUCCESS(f"   - {indicator_name_quotes_30d}: OK ({count})"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"   - Erreur extraction '{indicator_name_quotes_30d}': {e}"));
                indicators_data[indicator_name_quotes_30d] = None
            indicator_name_receivables = "total_fact_clients_attente_paiement"
            try:
                self.stdout.write(f"   - Recherche '{indicator_name_receivables}'...")
                domain_receivables = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                                      ('payment_state', '!=', 'paid')]
                receivables_data = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client,
                                                                  client_api_key, 'account.move', 'read_group',
                                                                  [domain_receivables, ['amount_residual_signed'],
                                                                   ['move_type']], {'lazy': False})
                if receivables_data and receivables_data[0].get('amount_residual_signed') is not None:
                    total_amount = receivables_data[0]['amount_residual_signed']
                    indicators_data[indicator_name_receivables] = f"{total_amount:,.2f}";
                    self.stdout.write(self.style.SUCCESS(
                        f"   - {indicator_name_receivables}: OK ({indicators_data[indicator_name_receivables]})"))
                else:
                    indicators_data[indicator_name_receivables] = "0.00"; self.stdout.write(self.style.WARNING(
                        f"   - {indicator_name_receivables}: Aucune facture client en attente ou montant nul."))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"   - Erreur extraction '{indicator_name_receivables}': {e}"));
                indicators_data[indicator_name_receivables] = None
            indicator_name_payables = "total_fact_fourn_attente_paiement"
            try:
                self.stdout.write(f"   - Recherche '{indicator_name_payables}'...")
                domain_payables = [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                                   ('payment_state', '!=', 'paid')]
                payables_data = object_proxy_client.execute_kw(client_conf.client_odoo_db, uid_client, client_api_key,
                                                               'account.move', 'read_group',
                                                               [domain_payables, ['amount_residual_signed'],
                                                                ['move_type']], {'lazy': False})
                if payables_data and payables_data[0].get('amount_residual_signed') is not None:
                    total_amount = abs(payables_data[0]['amount_residual_signed'])
                    indicators_data[indicator_name_payables] = f"{total_amount:,.2f}";
                    self.stdout.write(self.style.SUCCESS(
                        f"   - {indicator_name_payables}: OK ({indicators_data[indicator_name_payables]})"))
                else:
                    indicators_data[indicator_name_payables] = "0.00"; self.stdout.write(self.style.WARNING(
                        f"   - {indicator_name_payables}: Aucune facture fournisseur en attente ou montant nul."))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"   - Erreur extraction '{indicator_name_payables}': {e}"));
                indicators_data[indicator_name_payables] = None

            # 5e. Sauvegarder les résultats en BDD
            # ... (code inchangé pour la sauvegarde) ...
            saved_count = 0;
            error_count = 0
            self.stdout.write(f"Sauvegarde des indicateurs trouvés...")
            for name, value in indicators_data.items():
                if value is not None:
                    try:
                        IndicateursHistoriques.objects.create(
                            client=client_conf, indicator_name=name, indicator_value=str(value),
                            extraction_timestamp=current_extraction_run_timestamp,
                            assigned_odoo_collaborator_id=final_assigned_collab_id_str,
                            assigned_collaborator_name=collaborator_display_name)
                        saved_count += 1
                    except Exception as e:
                        self.stderr.write(self.style.ERROR(
                            f"   - Erreur sauvegarde indicateur '{name}' pour {client_conf.client_name}: {e}")); error_count += 1
            if error_count > 0:
                self.stderr.write(self.style.ERROR(
                    f"{saved_count} indicateur(s) sauvegardé(s), {error_count} erreur(s) de sauvegarde pour {client_conf.client_name}."))
            elif saved_count > 0:
                self.stdout.write(self.style.SUCCESS(
                    f"{saved_count} indicateur(s) sauvegardé(s) avec succès pour {client_conf.client_name}."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"Aucun nouvel indicateur trouvé ou à sauvegarder pour {client_conf.client_name}."))

        self.stdout.write(self.style.SUCCESS("\n--- Fin de l'extraction des indicateurs ---"))
