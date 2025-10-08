# core/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max, Q
from .models import IndicateursHistoriques, UserProfile, ClientsOdoo
from collections import defaultdict
import logging

from django.core.management import call_command
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

# --- DÉFINITION DES CATÉGORIES D'INDICATEURS (RÉORGANISÉES) ---
INDICATOR_CATEGORIES = {
    'Général': [
        'version odoo', 'type de base', 'type hebergement', 'code abonnement',
        'url odoo', 'nom bdd', 'date expiration base', 'nb societes'
    ],
    'Utilisateurs': [
        'nb utilisateurs actifs', 'nb utilisateurs inactifs > 14j', 'nb utilisateurs lpde'
    ],
    'Technique': [
        'nb modules actifs', 'date activation base',
        'nb champs personnalises', 'erreurs serveur (24h)', 'nb actions automatisées',
        'emails en erreur (30j)'
    ],
    'Comptabilité': [
        'date cloture annuelle', 'derniere cloture fiscale', 'periodicite tva',
        'operations à qualifier', 'achats à traiter', 'resultat provisoire annee courante',
        'transactions bancaires à rapprocher', 'nombre de factures en retard',
        'lignes ecritures annee courante', 'lignes ecritures annee precedente',
        'paiements orphelins', 'virements internes non soldés', 'solde virements internes',
        'pivot encaissement', 'marge brute 30j'
    ],
    'Ventes & CRM': [
        'opportunités créées (30j)', 'devis créés (30j)',
        'nombre de commandes à facturer', 'commandes à facturer en retard',
        'factures clients créées (30j)', 'nombre d\'activités en retard'
    ],
    'Achats & Stock': [
        'demandes de prix créées (30j)', 'commandes d\'achats à facturer',
        'commandes d\'achats à facturer en retard', 'nombre de produits',
        'produits stockés à coût 0', 'produits en stock négatif',
        'ajustements d\'inventaire à appliquer', 'nombre de livraisons en retard',
        'nombre de réceptions en retard'
    ],
    'Données': [
        'nombre de contacts', 'contacts en doublon (sim > 90%)'
    ],
    'Support': [
        'nombre de tickets non assignés'
    ],
    'Divers': []
}


@login_required
def search_clients_autocomplete(request):
    """
    Cette vue est appelée par JavaScript.
    Elle recherche les noms de clients qui correspondent au terme envoyé
    et les retourne au format JSON.
    """
    term = request.GET.get('term', '').strip()
    
    # On ne fait rien si la recherche est trop courte
    if len(term) < 2:
        return JsonResponse([], safe=False)

    # Base de la requête : on cherche les clients correspondant au terme
    # "icontains" signifie "contient, insensible à la casse"
    base_qs = ClientsOdoo.objects.filter(client_name__icontains=term)

    # On s'assure que les collaborateurs ne voient que leurs propres clients
    user = request.user
    profile = getattr(user, 'profile', None)
    if profile and profile.role == 'collaborateur' and profile.odoo_collaborator_id:
        # On récupère d'abord les IDs des clients autorisés pour ce collaborateur
        allowed_client_ids = IndicateursHistoriques.objects.filter(
            assigned_odoo_collaborator_id=str(profile.odoo_collaborator_id)
        ).values_list('client_id', flat=True).distinct()
        
        # On filtre notre recherche pour n'inclure que ces clients
        base_qs = base_qs.filter(id__in=allowed_client_ids)

    # On récupère les noms, en limitant à 10 résultats pour la performance
    client_names = list(base_qs.values_list('client_name', flat=True).distinct().order_by('client_name')[:10])

    return JsonResponse(client_names, safe=False)

@login_required
def dashboard_view(request):
    user = request.user
    profile = None
    user_role = None
    user_collab_id_str = None
    try:
        profile = user.profile
        user_role = profile.role
        user_collab_id_str = str(profile.odoo_collaborator_id) if profile.odoo_collaborator_id else None
    except UserProfile.DoesNotExist:
        logger.warning(f"Profil utilisateur non trouvé pour l'utilisateur {user.username}")

    # Récupération des filtres depuis l'URL
    selected_closing_date = request.GET.get('closing_date_filter', '')
    selected_collaborator_name = request.GET.get('collaborator_filter', '')
    selected_category = request.GET.get('category_filter', '')
    prelium_filter = request.GET.get('prelium_filter', '')
    search_query = request.GET.get('search', '') # <-- AJOUT : Récupère le terme de recherche

    base_qs_for_filter_options = IndicateursHistoriques.objects.all()
    if user_role == 'collaborateur' and user_collab_id_str:
        base_qs_for_filter_options = base_qs_for_filter_options.filter(assigned_odoo_collaborator_id=user_collab_id_str)
    elif user_role not in ['admin', 'super_admin']:
        base_qs_for_filter_options = IndicateursHistoriques.objects.none()

    closing_date_choices = base_qs_for_filter_options.filter(indicator_name__iexact='date cloture annuelle') \
        .exclude(indicator_value__isnull=True).exclude(indicator_value__exact='') \
        .values_list('indicator_value', flat=True) \
        .distinct().order_by('indicator_value')
        
    collaborator_choices = base_qs_for_filter_options.exclude(assigned_collaborator_name__isnull=True) \
        .exclude(assigned_collaborator_name='N/A') \
        .exclude(assigned_collaborator_name='') \
        .values_list('assigned_collaborator_name', flat=True) \
        .distinct().order_by('assigned_collaborator_name')

    category_choices_display = list(INDICATOR_CATEGORIES.keys())

    latest_indicators_qs = IndicateursHistoriques.objects.none()
    latest_run_timestamp = None
    clients_list = []
    client_indicators_dict = {}

    show_collaborator_column = False
    show_extraction_date_column = False

    current_data_qs = base_qs_for_filter_options
    if current_data_qs.exists():
        latest_run_agg = current_data_qs.aggregate(latest_run=Max('extraction_timestamp'))
        latest_run_timestamp = latest_run_agg.get('latest_run')

    if latest_run_timestamp:
        latest_indicators_qs = current_data_qs.filter(
            extraction_timestamp=latest_run_timestamp
        )

        # Application des filtres
        if selected_collaborator_name:
            latest_indicators_qs = latest_indicators_qs.filter(
                assigned_collaborator_name=selected_collaborator_name
            )
        if selected_closing_date:
            clients_with_closing_date = latest_indicators_qs.filter(
                indicator_name__iexact='date cloture annuelle',
                indicator_value=selected_closing_date
            ).values_list('client_id', flat=True).distinct()
            latest_indicators_qs = latest_indicators_qs.filter(client_id__in=clients_with_closing_date)
        
        if prelium_filter == 'on' and user_role == 'super_admin':
            latest_indicators_qs = latest_indicators_qs.filter(client__is_prelium=True)

        # <-- AJOUT : Application du filtre de recherche par nom ---
        if search_query:
            latest_indicators_qs = latest_indicators_qs.filter(client__client_name__icontains=search_query)
        # --- FIN DE L'AJOUT ---

        potential_indicator_names = list(set(
            name.strip().lower() for name in latest_indicators_qs.values_list('indicator_name', flat=True) if
            name and name.strip()
        ))

        available_indicators_set = set(potential_indicator_names)

        if selected_category and selected_category in INDICATOR_CATEGORIES:
            category_indicator_names = INDICATOR_CATEGORIES[selected_category]
            all_indicator_names_for_columns = [
                name for name in category_indicator_names if name in available_indicators_set
            ]
            show_collaborator_column = False
            show_extraction_date_column = False
        else:
            all_defined_indicators = []
            for category in INDICATOR_CATEGORIES.values():
                all_defined_indicators.extend(category)
            
            all_indicator_names_for_columns = [
                name for name in all_defined_indicators if name in available_indicators_set
            ]
            show_collaborator_column = True
            show_extraction_date_column = True

        if selected_category == "Divers":
            all_indicator_names_for_columns = []

        if all_indicator_names_for_columns or selected_category == "Divers":
            latest_indicators_qs = latest_indicators_qs.select_related('client').order_by('client__client_name', 'indicator_name')

            client_indicators_temp = defaultdict(list)
            clients_processed_temp = set()

            for indicator in latest_indicators_qs:
                client_indicators_temp[indicator.client].append(indicator)
                clients_processed_temp.add(indicator.client)

            client_indicators_dict = dict(client_indicators_temp)
            clients_list = sorted(list(clients_processed_temp), key=lambda c: c.client_name)
        else:
            clients_list = []
            client_indicators_dict = {}

    context = {
        'user_profile': profile,
        'user_role': user_role,
        'client_indicators': client_indicators_dict,
        'clients_list': clients_list,
        'all_indicator_names': all_indicator_names_for_columns,
        'latest_run_timestamp': latest_run_timestamp,
        'page_title': 'Tableau de bord OdooDash',
        'closing_date_choices': closing_date_choices,
        'collaborator_choices': collaborator_choices,
        'category_choices': category_choices_display,
        'selected_closing_date': selected_closing_date,
        'selected_collaborator_name': selected_collaborator_name,
        'selected_category': selected_category,
        'show_collaborator_column': show_collaborator_column,
        'show_extraction_date_column': show_extraction_date_column,
        'show_prelium_filter': user_role == 'super_admin',
        'prelium_filter_active': prelium_filter == 'on',
        'search_query': search_query, # <-- AJOUT : Passe la recherche au template
    }
    return render(request, 'core/dashboard.html', context)


@user_passes_test(lambda u: u.is_staff)
def trigger_fetch_indicators_view(request):
    if request.method == 'POST':
        try:
            logger.info(f"Lancement de fetch_indicators par l'utilisateur: {request.user.username}")
            call_command('fetch_indicators')
            messages.success(request,
                             "L'extraction des indicateurs a été lancée avec succès. Les données seront mises à jour sous peu.")
        except Exception as e:
            logger.error(f"Erreur lors du lancement de fetch_indicators via l'admin par {request.user.username}: {e}",
                         exc_info=True)
            messages.error(request, f"Une erreur est survenue lors du lancement de l'extraction : {e}")
    return redirect(reverse('admin:index'))


@csrf_exempt
def scheduler_fetch_indicators_view(request):
    """
    Vue sécurisée destinée à être appelée UNIQUEMENT par Google Cloud Scheduler.
    """
    if request.headers.get("X-CloudScheduler") != "true":
        logger.warning("Tentative d'accès non autorisée au déclencheur du scheduler.")
        return HttpResponseForbidden("Accès non autorisé.")

    if request.method == 'POST':
        try:
            logger.info("Lancement de fetch_indicators par le scheduler Cloud.")
            call_command('fetch_indicators')
            return HttpResponse("Extraction des indicateurs lancée avec succès par le scheduler.", status=200)
        except Exception as e:
            logger.error(f"Erreur lors du lancement de fetch_indicators via le scheduler: {e}", exc_info=True)
            return HttpResponse(f"Erreur lors du lancement de l'extraction : {e}", status=500)
    
    return HttpResponse("Cette URL ne peut être appelée qu'avec la méthode POST.", status=405)