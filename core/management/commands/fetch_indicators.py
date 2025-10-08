import logging
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, timedelta
from core.models import ConfigurationCabinet, ClientsOdoo, IndicateursHistoriques, ClientOdooStatus
from core.utils import decrypt_value, connect_odoo
from collections import defaultdict

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Extrait les indicateurs depuis les instances Odoo configurées et les sauvegarde en base de données.'

    # --- CONSTANTES POUR LA MAINTENANCE ---
    FIELD_COLLABORATOR_CABINET = 'x_collaborateur_1'
    FIELD_CLIENT_URL_CABINET = 'x_odoo_database'
    FIELD_FISCAL_YEAR_DAY = 'fiscalyear_last_day'
    FIELD_FISCAL_YEAR_MONTH = 'fiscalyear_last_month'
    FIELD_FISCAL_LOCK_DATE = 'fiscalyear_lock_date'
    FIELD_VAT_PERIODICITY = 'account_tax_periodicity'

    IND_ODOO_VERSION = "version odoo"
    IND_FISCAL_CLOSING = "date cloture annuelle"
    IND_PENDING_RECONCILIATION = "operations à qualifier"
    IND_DRAFT_PURCHASES = "achats à traiter"
    IND_LAST_FISCAL_LOCK_DATE = "derniere cloture fiscale"
    IND_ACTIVE_APPLICATIONS_COUNT = "nb modules actifs"
    IND_ACTIVE_USERS_COUNT = "nb utilisateurs actifs"
    IND_DB_ACTIVATION_DATE = "date activation base"
    IND_PROVISIONAL_RESULT = "resultat provisoire annee courante"
    IND_BASE_TYPE = "type de base"
    IND_HOSTING_TYPE = "type hebergement"
    IND_SUBSCRIPTION_CODE = "code abonnement"
    IND_ODOO_URL = "url odoo"
    IND_DB_NAME = "nom bdd"
    IND_EXPIRATION_DATE = "date expiration base"
    IND_COMPANY_COUNT = "nb societes"
    IND_INACTIVE_USERS_14D = "nb utilisateurs inactifs > 14j"
    # IND_CUSTOM_MODELS = "nb modeles personnalises (indicatif)"
    IND_CUSTOM_FIELDS = "nb champs personnalises"
    IND_SERVER_ERRORS = "erreurs serveur (24h)"
    IND_AUTOMATED_ACTIONS = "nb actions automatisées"
    IND_FAILED_EMAILS = "emails en erreur (30j)"
    IND_OVERDUE_ACTIVITIES = "nombre d'activités en retard"
    IND_CONTACTS_COUNT = "nombre de contacts"
    IND_DUPLICATE_CONTACTS = "contacts en doublon (sim > 90%)"
    IND_PRODUCTS_COUNT = "nombre de produits"
    IND_STOCKED_ZERO_COST = "produits stockés à coût 0"
    IND_NEGATIVE_STOCK = "produits en stock négatif"
    IND_PENDING_INVENTORY = "ajustements d'inventaire à appliquer"
    IND_RECENT_OPPORTUNITIES = "opportunités créées (30j)"
    IND_RECENT_QUOTATIONS = "devis créés (30j)"
    IND_RECENT_RFQ = "demandes de prix créées (30j)"
    IND_RECENT_INVOICES = "factures clients créées (30j)"
    IND_ORDERS_TO_INVOICE = "nombre de commandes à facturer"
    IND_LATE_ORDERS_TO_INVOICE = "commandes à facturer en retard"
    IND_PO_TO_INVOICE = "commandes d'achats à facturer"
    IND_LATE_PO_TO_INVOICE = "commandes d'achats à facturer en retard"
    IND_LATE_DELIVERIES = "nombre de livraisons en retard"
    IND_LATE_RECEIPTS = "nombre de réceptions en retard"
    IND_LATE_INVOICES = "nombre de factures en retard"
    IND_BANK_TO_RECONCILE = "transactions bancaires à rapprocher"
    IND_UNASSIGNED_TICKETS = "nombre de tickets non assignés"
    IND_ACCOUNT_MOVE_LINES_CURRENT_YEAR = "lignes ecritures annee courante"
    IND_ACCOUNT_MOVE_LINES_PREVIOUS_YEAR = "lignes ecritures annee precedente"

    # --- MAPPING DES NOMS DE CHAMPS PAR VERSION D'ODOO ---
    FIELD_MAPPING = {
        'default': {
            'product_qty_available': 'qty_available',
        },
        '17.0': {
            'product_qty_available': 'virtual_available',
        },
        '18.0': {
            'product_qty_available': 'virtual_available',
        }
    }


    # --- MÉTHODES HELPER POUR L'EXTRACTION ---

    def _execute_odoo_kw(self, object_proxy, db, uid, api_key, model, method, args=[], kwargs={}):
        """
        Wrapper de base pour les appels Odoo execute_kw.
        'args' est une liste pour les arguments positionnels.
        'kwargs' est un dict pour les arguments nommés.
        """
        return object_proxy.execute_kw(db, uid, api_key, model, method, args, kwargs)

    def _fetch_indicator(self, indicator_name, func, *args, **kwargs):
        """
        Helper générique qui exécute une fonction d'extraction, gère les logs et les erreurs.
        VERSION DE DÉBOGAGE : Affiche le traceback complet.
        """
        self.stdout.write(f"     - Recherche '{indicator_name}'...")
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            import traceback
            self.stderr.write(self.style.ERROR(f"     - Erreur extraction '{indicator_name}': {e}"))
            # LA LIGNE SUIVANTE EST CRUCIALE POUR LE DÉBOGAGE
            self.stderr.write(self.style.ERROR(traceback.format_exc()))
            return "Erreur" # On retourne "Erreur" pour que ce soit visible dans le dashboard

    def get_account_balance_sum_for_period(self, object_proxy, db, uid, api_key, account_prefixes, company_id, date_from_str, date_to_str):
        """
        Calcule la somme des soldes ('balance') via read_group.
        Attend les dates sous forme de chaînes 'YYYY-MM-DD'.
        """
        account_domain = ['|'] * (len(account_prefixes) - 1)
        for prefix in account_prefixes:
            account_domain.append(('account_id.code', '=like', f'{prefix}%'))

        domain = [
            ('company_id', '=', company_id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', date_from_str),
            ('date', '<=', date_to_str)
        ] + account_domain

        args = [domain, ['balance'], []]
        kwargs = {'lazy': False}
        grouped_data = self._execute_odoo_kw(object_proxy, db, uid, api_key, 'account.move.line', 'read_group', args, kwargs)

        total_balance = 0.0
        if grouped_data and grouped_data[0].get('balance') is not None:
            total_balance = grouped_data[0]['balance']
        
        return total_balance
    
    # --- MÉTHODE PRINCIPALE DE LA COMMANDE ---
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Début de l'extraction des indicateurs ---"))

        try:
            config_cabinet = ConfigurationCabinet.objects.first()
            if not config_cabinet:
                raise CommandError("Configuration du cabinet non trouvée.")
            self.stdout.write(f"Configuration cabinet trouvée: URL={config_cabinet.firm_odoo_url}")
        except Exception as e:
            raise CommandError(f"Erreur lors de la lecture de la configuration cabinet: {e}")

        firm_api_key = decrypt_value(config_cabinet.firm_odoo_encrypted_api_key)
        firm_uid, _, firm_object_proxy, _, firm_conn_error = (None, None, None, None, "Clé API non déchiffrable")
        if firm_api_key:
            firm_uid, _, firm_object_proxy, _, firm_conn_error = connect_odoo(
                config_cabinet.firm_odoo_url, config_cabinet.firm_odoo_db,
                config_cabinet.firm_odoo_api_user, firm_api_key
            )
        
        if not firm_uid:
            self.stderr.write(self.style.WARNING(f">>> Attention: Échec connexion Odoo cabinet: {firm_conn_error}."))
            firm_object_proxy = None
        else:
            self.stdout.write(self.style.SUCCESS("Connecté avec succès à l'Odoo du cabinet."))

        clients_config = ClientsOdoo.objects.all()
        if not clients_config.exists():
            self.stdout.write(self.style.WARNING("Aucun client Odoo n'est configuré."))
            return

        self.stdout.write(f"Traitement de {clients_config.count()} client(s) Odoo...")
        current_extraction_run_timestamp = timezone.now()

        for client_conf in clients_config:
            self.stdout.write(self.style.NOTICE(f"\n--- Traitement du client : {client_conf.client_name} ---"))
            indicators_data = {}
            last_attempt_time = timezone.now()
            
            client_api_key = decrypt_value(client_conf.client_odoo_encrypted_api_key)
            if not client_api_key:
                error_msg = "Impossible de déchiffrer la clé API."
                self.stderr.write(self.style.ERROR(f"{error_msg} pour {client_conf.client_name}."))
                ClientOdooStatus.objects.update_or_create(client=client_conf, defaults={'last_connection_attempt': last_attempt_time, 'connection_successful': False, 'last_error_message': error_msg})
                continue
            
            uid_client, _, object_proxy_client, odoo_version, conn_error = connect_odoo(
                client_conf.client_odoo_url, client_conf.client_odoo_db,
                client_conf.client_odoo_api_user, client_api_key
            )
            ClientOdooStatus.objects.update_or_create(client=client_conf, defaults={'last_connection_attempt': last_attempt_time, 'connection_successful': bool(uid_client), 'last_error_message': conn_error if conn_error else None})
            
            indicators_data[self.IND_ODOO_VERSION] = odoo_version if odoo_version else "Inconnue"
            self.stdout.write(self.style.SUCCESS(f"     - {self.IND_ODOO_VERSION}: OK ({indicators_data[self.IND_ODOO_VERSION]})"))
            
            # --- URL ET NOM DE BDD SONT TOUJOURS DISPONIBLES ---
            indicators_data[self.IND_ODOO_URL] = client_conf.client_odoo_url
            self.stdout.write(self.style.SUCCESS(f"     - {self.IND_ODOO_URL}: OK ({client_conf.client_odoo_url})"))
            indicators_data[self.IND_DB_NAME] = client_conf.client_odoo_db
            self.stdout.write(self.style.SUCCESS(f"     - {self.IND_DB_NAME}: OK ({client_conf.client_odoo_db})"))

            if not uid_client:
                self.stderr.write(self.style.ERROR(f">>> Échec authentification Odoo pour {client_conf.client_name}. {conn_error}"))
                # Sauvegarder les quelques indicateurs qu'on a pu récupérer
                for name, value in indicators_data.items():
                    IndicateursHistoriques.objects.create(client=client_conf, indicator_name=name, indicator_value=str(value), extraction_timestamp=current_extraction_run_timestamp, assigned_odoo_collaborator_id="0", assigned_collaborator_name="N/A")
                continue
            
            self.stdout.write(self.style.SUCCESS(f"Connecté avec succès à Odoo pour {client_conf.client_name} (UID: {uid_client})."))
            
            # --- DÉTERMINATION DES BONS NOMS DE CHAMPS ---
            major_version = ".".join(odoo_version.split('.')[:2]) if odoo_version and odoo_version != "Inconnue" else 'default'
            fields = self.FIELD_MAPPING.get(major_version, self.FIELD_MAPPING['default'])
            
            final_assigned_collab_id_str, collaborator_display_name = "0", "N/A"
            if firm_object_proxy:
                partner_domain = [(self.FIELD_CLIENT_URL_CABINET, '=', client_conf.client_odoo_url)]
                partner_ids = self._fetch_indicator("Recherche Partenaire", self._execute_odoo_kw, firm_object_proxy, config_cabinet.firm_odoo_db, firm_uid, firm_api_key, 'res.partner', 'search', args=[partner_domain], kwargs={'limit': 1})
                if partner_ids:
                    partner_data = self._fetch_indicator("Lecture Collaborateur", self._execute_odoo_kw, firm_object_proxy, config_cabinet.firm_odoo_db, firm_uid, firm_api_key, 'res.partner', 'read', args=[partner_ids, [self.FIELD_COLLABORATOR_CABINET]])
                    if partner_data and partner_data[0].get(self.FIELD_COLLABORATOR_CABINET):
                        collab_info = partner_data[0][self.FIELD_COLLABORATOR_CABINET]
                        final_assigned_collab_id_str = str(collab_info[0])
                        collaborator_display_name = collab_info[1]
                        self.stdout.write(self.style.SUCCESS(f"     - Collaborateur assigné: {collaborator_display_name}"))

            user_info = self._fetch_indicator("Company ID", self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'res.users', 'read', args=[[uid_client]], kwargs={'fields': ['company_id']})
            company_id = user_info[0]['company_id'][0] if user_info and user_info[0].get('company_id') else 1

            # --- VÉRIFICATION PRÉALABLE DES MODULES INSTALLÉS ---
            self.stdout.write("     - Vérification des modules clés installés...")
            modules_to_check = ['stock', 'purchase', 'sale', 'crm', 'helpdesk', 'account', 'data_cleaning', 'data_merge']
            is_module_installed = {}
            for module_name in modules_to_check:
                try:
                    count = self._execute_odoo_kw(
                        object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                        'ir.module.module', 'search_count',
                        args=[[('name', '=', module_name), ('state', '=', 'installed')]]
                    )
                    is_module_installed[module_name] = count > 0
                except Exception:
                    is_module_installed[module_name] = False # Précaution
            self.stdout.write(f"     - Statut modules: {is_module_installed}")

            # --- AJOUT DES INDICATEURS ---

            # Indicateur: Nombre de tickets non assignés
            if is_module_installed.get('helpdesk'):
                unassigned_tickets_domain = [('user_id', '=', False), ('stage_id.is_closed', '=', False)]
                unassigned_tickets_count = self._fetch_indicator(self.IND_UNASSIGNED_TICKETS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'helpdesk.ticket', 'search_count', args=[unassigned_tickets_domain])
                if unassigned_tickets_count is not None:
                    indicators_data[self.IND_UNASSIGNED_TICKETS] = unassigned_tickets_count
                    self.stdout.write(self.style.SUCCESS(f"     - {self.IND_UNASSIGNED_TICKETS}: OK ({unassigned_tickets_count})"))
            else:
                indicators_data[self.IND_UNASSIGNED_TICKETS] = "N/A"
                self.stdout.write(self.style.WARNING(f"     - {self.IND_UNASSIGNED_TICKETS}: Module Assistance non installé"))

            # --- INDICATEUR : Code d'Abonnement (logique robuste) ---
            try:
                self.stdout.write(f"     - Recherche '{self.IND_SUBSCRIPTION_CODE}'...")
                sub_code = "N/A" # Valeur par défaut

                # 1. Vérifier si le modèle 'sale.subscription' existe
                model_exists_count = self._execute_odoo_kw(
                    object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                    'ir.model', 'search_count', args=[[('model', '=', 'sale.subscription')]]
                )

                if model_exists_count == 0:
                    self.stdout.write(self.style.WARNING(f"          - Module 'Abonnements' non installé pour ce client."))
                    sub_code = "N/A (module absent)"
                else:
                    # 2. Si le module existe, rechercher l'abonnement
                    company_data = self._execute_odoo_kw(
                        object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                        'res.company', 'read', args=[[company_id]], kwargs={'fields': ['partner_id']}
                    )
                    if company_data and company_data[0].get('partner_id'):
                        company_partner_id = company_data[0]['partner_id'][0]
                        
                        subscription_domain = [
                            ('partner_id', '=', company_partner_id),
                        ]
                        subscriptions = self._execute_odoo_kw(
                            object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                            'sale.subscription', 'search_read',
                            args=[subscription_domain],
                            kwargs={'fields': ['name'], 'limit': 1, 'order': 'create_date desc'}
                        )
                        
                        if subscriptions:
                            sub_code = subscriptions[0]['name']
                        else:
                            sub_code = "Aucun abonnement actif"
                    else:
                        sub_code = "Partenaire société introuvable"

                indicators_data[self.IND_SUBSCRIPTION_CODE] = sub_code
                self.stdout.write(self.style.SUCCESS(f"     - {self.IND_SUBSCRIPTION_CODE}: OK ({sub_code})"))

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"     - Erreur extraction '{self.IND_SUBSCRIPTION_CODE}': {e}"))
                indicators_data[self.IND_SUBSCRIPTION_CODE] = "Erreur" # On stocke "Erreur" au lieu de None

            # Indicateur: Nombre de transactions bancaires à rapprocher
            bank_reconcile_domain = [('is_reconciled', '=', False)]
            bank_reconcile_count = self._fetch_indicator(self.IND_BANK_TO_RECONCILE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.bank.statement.line', 'search_count', args=[bank_reconcile_domain])
            if bank_reconcile_count is not None:
                indicators_data[self.IND_BANK_TO_RECONCILE] = bank_reconcile_count
            else:
                indicators_data[self.IND_BANK_TO_RECONCILE] = "N/A"

            # Indicateur: Nombre de factures en retard
            today_str = timezone.now().strftime('%Y-%m-%d')
            late_invoices_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']), ('invoice_date_due', '<', today_str)]
            late_invoices_count = self._fetch_indicator(self.IND_LATE_INVOICES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.move', 'search_count', args=[late_invoices_domain])
            if late_invoices_count is not None:
                indicators_data[self.IND_LATE_INVOICES] = late_invoices_count
                self.stdout.write(self.style.SUCCESS(f"     - {self.IND_LATE_INVOICES}: OK ({late_invoices_count})"))
            else:
                indicators_data[self.IND_LATE_INVOICES] = "N/A"
                self.stdout.write(self.style.WARNING(f"     - {self.IND_LATE_INVOICES}: Module Compta non installé ou erreur"))

            # --- Indicateurs liés au module STOCK ---
            if is_module_installed.get('stock'):
                today_dt_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                # Réceptions en retard
                late_receipts_domain = [('state', 'in', ['confirmed', 'waiting', 'assigned']), ('scheduled_date', '<', today_dt_str), ('picking_type_code', '=', 'incoming')]
                late_receipts_count = self._fetch_indicator(self.IND_LATE_RECEIPTS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'stock.picking', 'search_count', args=[late_receipts_domain])
                indicators_data[self.IND_LATE_RECEIPTS] = late_receipts_count if late_receipts_count is not None else 0

                # Livraisons en retard
                late_deliveries_domain = [('state', 'in', ['confirmed', 'waiting', 'assigned']), ('scheduled_date', '<', today_dt_str), ('picking_type_code', '=', 'outgoing')]
                late_deliveries_count = self._fetch_indicator(self.IND_LATE_DELIVERIES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'stock.picking', 'search_count', args=[late_deliveries_domain])
                indicators_data[self.IND_LATE_DELIVERIES] = late_deliveries_count if late_deliveries_count is not None else 0

                # Ajustements d'inventaire
                pending_inventory_count = None
                if major_version in ['17.0', '18.0']:
                    pending_inventory_domain = [('inventory_quantity_set', '=', True), ('inventory_date', '=', False)]
                    pending_inventory_count = self._fetch_indicator(self.IND_PENDING_INVENTORY, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'stock.quant', 'search_count', args=[pending_inventory_domain])
                else:
                    pending_inventory_domain = [('state', 'in', ['draft', 'confirm'])]
                    pending_inventory_count = self._fetch_indicator(self.IND_PENDING_INVENTORY, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'stock.inventory', 'search_count', args=[pending_inventory_domain])
                indicators_data[self.IND_PENDING_INVENTORY] = pending_inventory_count if pending_inventory_count is not None else 0
                
                # Stock négatif
                negative_stock_domain = [('type', '=', 'product'), (fields['product_qty_available'], '<', 0)]
                negative_stock_count = self._fetch_indicator(self.IND_NEGATIVE_STOCK, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'product.product', 'search_count', args=[negative_stock_domain])
                indicators_data[self.IND_NEGATIVE_STOCK] = negative_stock_count if negative_stock_count is not None else 0

                # Coût à 0
                zero_cost_domain = [('type', '=', 'product'), (fields['product_qty_available'], '>', 0), ('standard_price', '=', 0)]
                zero_cost_count = self._fetch_indicator(self.IND_STOCKED_ZERO_COST, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'product.product', 'search_count', args=[zero_cost_domain])
                indicators_data[self.IND_STOCKED_ZERO_COST] = zero_cost_count if zero_cost_count is not None else 0

            else:
                for ind in [self.IND_LATE_RECEIPTS, self.IND_LATE_DELIVERIES, self.IND_PENDING_INVENTORY, self.IND_NEGATIVE_STOCK, self.IND_STOCKED_ZERO_COST]:
                    indicators_data[ind] = "N/A"
                    self.stdout.write(self.style.WARNING(f"     - {ind}: Module Inventaire non installé"))
            
            # --- Indicateurs liés au module ACHATS ---
            if is_module_installed.get('purchase'):
                today_dt_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                # Commandes achats à facturer en retard
                late_po_to_invoice_domain = [('invoice_status', '=', 'to invoice'), ('date_planned', '<', today_dt_str)]
                late_po_to_invoice_count = self._fetch_indicator(self.IND_LATE_PO_TO_INVOICE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'purchase.order', 'search_count', args=[late_po_to_invoice_domain])
                indicators_data[self.IND_LATE_PO_TO_INVOICE] = late_po_to_invoice_count if late_po_to_invoice_count is not None else 0

                # Commandes achats à facturer
                po_to_invoice_domain = [('invoice_status', '=', 'to invoice')]
                po_to_invoice_count = self._fetch_indicator(self.IND_PO_TO_INVOICE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'purchase.order', 'search_count', args=[po_to_invoice_domain])
                indicators_data[self.IND_PO_TO_INVOICE] = po_to_invoice_count if po_to_invoice_count is not None else 0

                # Demandes de prix récentes
                time_30d_ago_str = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                recent_rfq_domain = [('create_date', '>=', time_30d_ago_str), ('state', 'in', ['draft', 'sent', 'to approve', 'purchase'])]
                recent_rfq_count = self._fetch_indicator(self.IND_RECENT_RFQ, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'purchase.order', 'search_count', args=[recent_rfq_domain])
                indicators_data[self.IND_RECENT_RFQ] = recent_rfq_count if recent_rfq_count is not None else 0

            else:
                for ind in [self.IND_LATE_PO_TO_INVOICE, self.IND_PO_TO_INVOICE, self.IND_RECENT_RFQ]:
                    indicators_data[ind] = "N/A"
                    self.stdout.write(self.style.WARNING(f"     - {ind}: Module Achats non installé"))

            # --- Indicateurs VENTES & CRM ---
            if is_module_installed.get('sale'):
                today_dt_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                # Commandes ventes à facturer en retard
                late_to_invoice_domain = [('invoice_status', '=', 'to invoice'), ('commitment_date', '<', today_dt_str)]
                late_to_invoice_count = self._fetch_indicator(self.IND_LATE_ORDERS_TO_INVOICE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'sale.order', 'search_count', args=[late_to_invoice_domain])
                indicators_data[self.IND_LATE_ORDERS_TO_INVOICE] = late_to_invoice_count if late_to_invoice_count is not None else 0
                
                # Commandes ventes à facturer
                to_invoice_domain = [('invoice_status', '=', 'to invoice')]
                to_invoice_count = self._fetch_indicator(self.IND_ORDERS_TO_INVOICE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'sale.order', 'search_count', args=[to_invoice_domain])
                indicators_data[self.IND_ORDERS_TO_INVOICE] = to_invoice_count if to_invoice_count is not None else 0
                
                time_30d_ago_str = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                recent_quotes_domain = [('create_date', '>=', time_30d_ago_str), ('state', 'in', ['draft', 'sent', 'sale'])]
                recent_quotes_count = self._fetch_indicator(self.IND_RECENT_QUOTATIONS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'sale.order', 'search_count', args=[recent_quotes_domain])
                indicators_data[self.IND_RECENT_QUOTATIONS] = recent_quotes_count if recent_quotes_count is not None else 0

            else:
                for ind in [self.IND_LATE_ORDERS_TO_INVOICE, self.IND_ORDERS_TO_INVOICE, self.IND_RECENT_QUOTATIONS]:
                    indicators_data[ind] = "N/A"
                    self.stdout.write(self.style.WARNING(f"     - {ind}: Module Ventes non installé"))
            
            if is_module_installed.get('crm'):
                # Opportunités récentes
                time_30d_ago_str = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                recent_opps_domain = [('create_date', '>=', time_30d_ago_str), ('type', '=', 'opportunity')]
                recent_opps_count = self._fetch_indicator(self.IND_RECENT_OPPORTUNITIES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'crm.lead', 'search_count', args=[recent_opps_domain])
                indicators_data[self.IND_RECENT_OPPORTUNITIES] = recent_opps_count if recent_opps_count is not None else 0
            else:
                indicators_data[self.IND_RECENT_OPPORTUNITIES] = "N/A"
                self.stdout.write(self.style.WARNING(f"     - {self.IND_RECENT_OPPORTUNITIES}: Module CRM non installé"))


            # Indicateur: Nombre de factures clients créées depuis 30 jours
            time_30d_ago_str = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
            recent_invoices_domain = [('create_date', '>=', time_30d_ago_str), ('move_type', '=', 'out_invoice')]
            recent_invoices_count = self._fetch_indicator(self.IND_RECENT_INVOICES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.move', 'search_count', args=[recent_invoices_domain])
            if recent_invoices_count is not None:
                indicators_data[self.IND_RECENT_INVOICES] = recent_invoices_count
            else:
                indicators_data[self.IND_RECENT_INVOICES] = 0

            # Indicateur: Nombre de produits
            products_count = self._fetch_indicator(self.IND_PRODUCTS_COUNT, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'product.product', 'search_count', args=[[]])
            if products_count is not None:
                indicators_data[self.IND_PRODUCTS_COUNT] = products_count
            else:
                indicators_data[self.IND_PRODUCTS_COUNT] = 0

            # --- DÉBUT BLOC CORRIGÉ ---
            
            # --- Indicateur: Nombre de contacts en doublon (Toutes sociétés, log. de groupement) ---
            
            # On vérifie si l'un des modules de déduplication est installé
            if is_module_installed.get('data_merge') or is_module_installed.get('data_cleaning'):
                try:
                    # Étape 1 : Domaine pour récupérer TOUS les doublons, toutes sociétés confondues (les 60)
                    model_to_use = 'data_merge.record'
                    duplicate_domain = [
                        ('res_model_id.model', '=', 'res.partner')
                        # Pas de filtre company_id pour avoir le total
                    ]

                    # Étape 2 : Récupérer les fiches avec leur 'group_id' pour le traitement en Python
                    all_duplicates_data = self._fetch_indicator(
                        "Lecture de toutes les fiches de doublons",
                        self._execute_odoo_kw,
                        object_proxy_client,
                        client_conf.client_odoo_db,
                        uid_client,
                        client_api_key,
                        model_to_use,
                        'search_read',
                        args=[duplicate_domain],
                        kwargs={'fields': ['group_id']}
                    )

                    final_count = 0
                    if all_duplicates_data and isinstance(all_duplicates_data, list):
                        # Étape 3 : Grouper les 60 fiches par leur group_id
                        groups = defaultdict(list)
                        for record in all_duplicates_data:
                            if record.get('group_id'):
                                group_id = record['group_id'][0]
                                groups[group_id].append(record)
                        
                        # Étape 4 : Compter uniquement les fiches dans les groupes ayant plus d'un membre
                        # C'est la logique "métier" d'Odoo pour ne montrer que les doublons "actifs".
                        valid_records_count = sum(
                            len(records_in_group) 
                            for records_in_group in groups.values() 
                            if len(records_in_group) > 1
                        )
                        final_count = valid_records_count
                    
                    indicator_value = str(final_count)
                    indicators_data[self.IND_DUPLICATE_CONTACTS] = indicator_value
                    self.stdout.write(self.style.SUCCESS(f"     - {self.IND_DUPLICATE_CONTACTS}: OK ({indicator_value})"))

                except Exception as e:
                    import traceback
                    self.stderr.write(self.style.ERROR(f"     - Erreur extraction complexe '{self.IND_DUPLICATE_CONTACTS}': {e}"))
                    self.stderr.write(self.style.ERROR(traceback.format_exc()))
                    indicators_data[self.IND_DUPLICATE_CONTACTS] = "Erreur"
            
            else:
                indicators_data[self.IND_DUPLICATE_CONTACTS] = "N/A"
                self.stdout.write(self.style.WARNING(f"     - {self.IND_DUPLICATE_CONTACTS}: Module de déduplication non installé"))

            # L'indentation de ce qui suit est maintenant correcte.
            # Tout ce code est au même niveau que le 'if' ci-dessus.
            
            # Indicateur: Nombre de contacts
            contacts_count = self._fetch_indicator(self.IND_CONTACTS_COUNT, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'res.partner', 'search_count', args=[[]])
            indicators_data[self.IND_CONTACTS_COUNT] = contacts_count if contacts_count is not None else 0

            # Indicateur: Nombre d'activités en retard
            overdue_activities_domain = [('date_deadline', '<', timezone.now().strftime('%Y-%m-%d'))]
            overdue_count = self._fetch_indicator(self.IND_OVERDUE_ACTIVITIES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'mail.activity', 'search_count', args=[overdue_activities_domain])
            indicators_data[self.IND_OVERDUE_ACTIVITIES] = overdue_count if overdue_count is not None else "N/A"

            # Indicateur: Nombre d’e-mails non envoyés/en erreur sur les 30 derniers jours
            time_30d_ago_str = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
            failed_emails_domain = [('state', 'in', ['exception', 'cancel']), ('create_date', '>=', time_30d_ago_str)]
            failed_email_count = self._fetch_indicator(self.IND_FAILED_EMAILS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'mail.mail', 'search_count', args=[failed_emails_domain])
            indicators_data[self.IND_FAILED_EMAILS] = failed_email_count if failed_email_count is not None else "N/A"

            # INDICATEUR : Nombre d'Actions Automatisées ---
            try:
                self.stdout.write(f"     - Recherche '{self.IND_AUTOMATED_ACTIONS}'...")
                
                domain = [('active', '=', True)]
                
                count = self._execute_odoo_kw(
                    object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                    'base.automation',
                    'search_count',
                    args=[domain]
                )
                
                indicators_data[self.IND_AUTOMATED_ACTIONS] = count if count is not None else 0
                self.stdout.write(self.style.SUCCESS(f"     - {self.IND_AUTOMATED_ACTIONS}: OK ({count})"))

            except Exception as e:
                if "base.automation" in str(e):
                    self.stdout.write(self.style.WARNING(f"     - {self.IND_AUTOMATED_ACTIONS}: Le modèle n'existe pas sur cette version d'Odoo."))
                    indicators_data[self.IND_AUTOMATED_ACTIONS] = "N/A"
                else:
                    import traceback
                    self.stderr.write(self.style.ERROR(f"     - Erreur extraction '{self.IND_AUTOMATED_ACTIONS}': {e}"))
                    self.stderr.write(self.style.ERROR(traceback.format_exc()))
                    indicators_data[self.IND_AUTOMATED_ACTIONS] = "Erreur"

            # Indicateur: Taux d'erreurs serveur (tracebacks) sur les dernières 24h
            time_24h_ago_str = (timezone.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
            server_errors_domain = [('create_date', '>=', time_24h_ago_str), ('level', '=', 'ERROR'), ('type', '=', 'server')]
            error_count = self._fetch_indicator(self.IND_SERVER_ERRORS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'ir.logging', 'search_count', args=[server_errors_domain])
            indicators_data[self.IND_SERVER_ERRORS] = error_count if error_count is not None else "N/A"

            # Indicateur: Nombre de champs personnalisés
            custom_fields_domain = [('name', '=like', 'x_%')]
            custom_fields_count = self._fetch_indicator(self.IND_CUSTOM_FIELDS, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'ir.model.fields', 'search_count', args=[custom_fields_domain])
            indicators_data[self.IND_CUSTOM_FIELDS] = custom_fields_count if custom_fields_count is not None else 0

            
            # --- INDICATEUR : Nombre d'utilisateurs inactifs > 14j (méthode login_date) ---
            try:
                self.stdout.write(f"     - Recherche '{self.IND_INACTIVE_USERS_14D}' (par date de connexion)...")
                
                date_14_days_ago = timezone.now() - timedelta(days=14)
                date_14_days_ago_str = date_14_days_ago.strftime('%Y-%m-%d %H:%M:%S')
                
                inactive_users_domain = [
                    ('share', '=', False), 
                    ('active', '=', True), 
                    '|', 
                        ('login_date', '=', False), 
                        ('login_date', '<', date_14_days_ago_str)
                ]
                
                inactive_users_data = self._execute_odoo_kw(
                    object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                    'res.users', 'search_read',
                    args=[inactive_users_domain],
                    kwargs={'fields': ['login']}
                )
                
                if inactive_users_data is not None:
                    external_inactive_users = [
                        user for user in inactive_users_data
                        if not (
                            user.get('login', '').lower().endswith('@lpde.pro') or
                            user.get('login', '').lower().endswith('@prelium.fr')
                        )
                    ]

                    count = len(external_inactive_users)
                    indicator_value = "0"
                    if count > 0:
                        logins = ', '.join([user['login'] for user in external_inactive_users[:5]])
                        if count > 5:
                            logins += f", et {count - 5} autre(s)..."
                        indicator_value = f"{count} ({logins})"
                    
                    indicators_data[self.IND_INACTIVE_USERS_14D] = indicator_value
                    self.stdout.write(self.style.SUCCESS(f"     - {self.IND_INACTIVE_USERS_14D}: OK ({indicator_value})"))
                else:
                    raise Exception("La requête Odoo a échoué (retour null)")

            except Exception as e:
                import traceback
                self.stderr.write(self.style.ERROR(f"     - Erreur extraction '{self.IND_INACTIVE_USERS_14D}': {e}"))
                self.stderr.write(self.style.ERROR(traceback.format_exc()))
                indicators_data[self.IND_INACTIVE_USERS_14D] = "Erreur"
            
            # Indicateur: Type d'hébergement (logique basée sur l'email de l'utilisateur API)
            try:
                user_email = (client_conf.client_odoo_api_user or "").strip().lower()
                is_internal_user = user_email.endswith('@lpde.pro') or user_email.endswith('@prelium.fr')
                if not is_internal_user:
                    hosting_type = 'Odoo.sh'
                elif 'odoo.com' in client_conf.client_odoo_url:
                    hosting_type = 'Odoo Online'
                else:
                    hosting_type = 'On-Premise'
                indicators_data[self.IND_HOSTING_TYPE] = hosting_type
            except Exception:
                indicators_data[self.IND_HOSTING_TYPE] = 'Inconnu'

            # --- Indicateurs basés sur la compta ---
            if is_module_installed.get('account'):
                # date cloture annuelle
                company_data = self._fetch_indicator(self.IND_FISCAL_CLOSING, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'res.company', 'read', args=[[company_id]], kwargs={'fields': [self.FIELD_FISCAL_YEAR_DAY, self.FIELD_FISCAL_YEAR_MONTH]})
                if company_data and company_data[0].get(self.FIELD_FISCAL_YEAR_DAY) and company_data[0].get(self.FIELD_FISCAL_YEAR_MONTH):
                    day, month = company_data[0][self.FIELD_FISCAL_YEAR_DAY], company_data[0][self.FIELD_FISCAL_YEAR_MONTH]
                    indicators_data[self.IND_FISCAL_CLOSING] = f"{int(day):02d}/{int(month):02d}"

                # operations à qualifier
                domain = [('account_id.code', '=like', '47%'), ('full_reconcile_id', '=', False), ('move_id.state', '=', 'posted')]
                count = self._fetch_indicator(self.IND_PENDING_RECONCILIATION, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.move.line', 'search_count', args=[domain])
                indicators_data[self.IND_PENDING_RECONCILIATION] = count if count is not None else 0

                # achats à traiter
                journal_ids = self._execute_odoo_kw(object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.journal', 'search', args=[[('type', '=', 'purchase'), ('company_id', '=', company_id)]])
                if journal_ids:
                    domain = [('journal_id', 'in', journal_ids), ('state', '=', 'draft'), ('move_type', '=', 'in_invoice')]
                    count = self._fetch_indicator(self.IND_DRAFT_PURCHASES, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.move', 'search_count', args=[domain])
                    indicators_data[self.IND_DRAFT_PURCHASES] = count if count is not None else 0
                else:
                    indicators_data[self.IND_DRAFT_PURCHASES] = 0

                # derniere cloture fiscale
                lock_data = self._fetch_indicator(self.IND_LAST_FISCAL_LOCK_DATE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'account.change.lock.date', 'search_read', args=[[]], kwargs={'fields': [self.FIELD_FISCAL_LOCK_DATE], 'limit': 1})
                if lock_data and lock_data[0].get(self.FIELD_FISCAL_LOCK_DATE):
                    indicators_data[self.IND_LAST_FISCAL_LOCK_DATE] = lock_data[0][self.FIELD_FISCAL_LOCK_DATE]
                
                # resultat provisoire
                today_obj = timezone.now().date()
                first_day_obj = today_obj.replace(month=1, day=1)
                income = -self.get_account_balance_sum_for_period(object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, ['7'], company_id, first_day_obj.strftime('%Y-%m-%d'), today_obj.strftime('%Y-%m-%d'))
                expense = self.get_account_balance_sum_for_period(object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, ['6'], company_id, first_day_obj.strftime('%Y-%m-%d'), today_obj.strftime('%Y-%m-%d'))
                indicators_data[self.IND_PROVISIONAL_RESULT] = f"{(income - expense):,.2f}"

                # Nombre de lignes d'écritures comptables année courante
                start_of_year = today_obj.replace(month=1, day=1).strftime('%Y-%m-%d')
                end_of_year = today_obj.replace(month=12, day=31).strftime('%Y-%m-%d')
                move_lines_domain = [('date', '>=', start_of_year), ('date', '<=', end_of_year)]
                move_lines_count = self._fetch_indicator(
                    self.IND_ACCOUNT_MOVE_LINES_CURRENT_YEAR,
                    self._execute_odoo_kw,
                    object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                    'account.move.line', 'search_count',
                    args=[move_lines_domain]
                )
                indicators_data[self.IND_ACCOUNT_MOVE_LINES_CURRENT_YEAR] = move_lines_count if move_lines_count is not None else 0

                # Nombre de lignes d'écritures comptables année précédente
                previous_year = today_obj.year - 1
                start_of_previous_year = datetime(previous_year, 1, 1).strftime('%Y-%m-%d')
                end_of_previous_year = datetime(previous_year, 12, 31).strftime('%Y-%m-%d')
                move_lines_domain_prev = [('date', '>=', start_of_previous_year), ('date', '<=', end_of_previous_year)]
                move_lines_count_prev = self._fetch_indicator(
                    self.IND_ACCOUNT_MOVE_LINES_PREVIOUS_YEAR,
                    self._execute_odoo_kw,
                    object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key,
                    'account.move.line', 'search_count',
                    args=[move_lines_domain_prev]
                )
                indicators_data[self.IND_ACCOUNT_MOVE_LINES_PREVIOUS_YEAR] = move_lines_count_prev if move_lines_count_prev is not None else 0

            # Indicateur: nb modules actifs
            count = self._fetch_indicator(self.IND_ACTIVE_APPLICATIONS_COUNT, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'ir.module.module', 'search_count', args=[[('state', '=', 'installed'), ('application', '=', True)]])
            indicators_data[self.IND_ACTIVE_APPLICATIONS_COUNT] = count if count is not None else 0
            
            # Indicateur: nb utilisateurs actifs
            count = self._fetch_indicator(self.IND_ACTIVE_USERS_COUNT, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'res.users', 'search_count', args=[[('active', '=', True), ('share', '=', False)]])
            indicators_data[self.IND_ACTIVE_USERS_COUNT] = count if count is not None else 0

            # Indicateur: date activation base
            module_data = self._fetch_indicator(self.IND_DB_ACTIVATION_DATE, self._execute_odoo_kw, object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'ir.module.module', 'search_read', args=[[]], kwargs={'fields': ['create_date'], 'limit': 1, 'order': 'create_date asc'})
            if module_data and isinstance(module_data[0].get('create_date'), str):
                dt_object = datetime.strptime(module_data[0]['create_date'], '%Y-%m-%d %H:%M:%S')
                indicators_data[self.IND_DB_ACTIVATION_DATE] = dt_object.strftime('%d/%m/%Y')

            # Indicateur: type de base
            studio_count = self._execute_odoo_kw(object_proxy_client, client_conf.client_odoo_db, uid_client, client_api_key, 'ir.module.module', 'search_count', args=[[('name', '=', 'web_studio'), ('state', '=', 'installed')]])
            if studio_count and studio_count > 0:
                base_type = "Personnalisé"
            elif indicators_data.get(self.IND_ACTIVE_APPLICATIONS_COUNT) == 1:
                base_type = "Gratuit"
            else:
                base_type = "Standard"
            indicators_data[self.IND_BASE_TYPE] = base_type
            self.stdout.write(self.style.SUCCESS(f"     - {self.IND_BASE_TYPE}: OK ({base_type})"))

            # 5. Sauvegarder les résultats en BDD
            saved_count, error_count = 0, 0
            for name, value in indicators_data.items():
                if value is not None:
                    try:
                        IndicateursHistoriques.objects.create(
                            client=client_conf, indicator_name=name, indicator_value=str(value),
                            extraction_timestamp=current_extraction_run_timestamp,
                            assigned_odoo_collaborator_id=final_assigned_collab_id_str,
                            assigned_collaborator_name=collaborator_display_name
                        )
                        saved_count += 1
                    except Exception as e_save:
                        self.stderr.write(self.style.ERROR(f"     - Erreur sauvegarde indicateur '{name}': {e_save}"))
                        error_count += 1
            
            if error_count > 0:
                self.stderr.write(self.style.ERROR(f"{saved_count} indicateur(s) sauvegardé(s), {error_count} erreur(s) pour {client_conf.client_name}."))
            elif saved_count > 0:
                self.stdout.write(self.style.SUCCESS(f"{saved_count} indicateur(s) sauvegardé(s) avec succès pour {client_conf.client_name}."))

        self.stdout.write(self.style.SUCCESS("\n--- Fin de l'extraction des indicateurs ---"))