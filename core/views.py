# core/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max, Q
from .models import IndicateursHistoriques, UserProfile, ClientsOdoo
from collections import defaultdict
import logging

# --- AJOUTS POUR LE BOUTON ADMIN ---
from django.core.management import call_command
from django.contrib import messages
from django.urls import reverse

# --- FIN AJOUTS ---

logger = logging.getLogger(__name__)


@login_required
def dashboard_view(request):
    # ... (votre code existant pour dashboard_view reste ici) ...
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

    selected_closing_date = request.GET.get('closing_date_filter', '')
    selected_collaborator_name = request.GET.get('collaborator_filter', '')

    base_qs_for_filters = IndicateursHistoriques.objects.all()
    if user_role == 'collaborateur' and user_collab_id_str:
        base_qs_for_filters = base_qs_for_filters.filter(assigned_odoo_collaborator_id=user_collab_id_str)
    elif user_role != 'admin':
        base_qs_for_filters = IndicateursHistoriques.objects.none()

    closing_date_choices = base_qs_for_filters.filter(indicator_name='date_cloture_annuelle') \
        .values_list('indicator_value', flat=True) \
        .distinct().order_by('indicator_value')
    collaborator_choices = base_qs_for_filters.exclude(assigned_collaborator_name__isnull=True) \
        .exclude(assigned_collaborator_name='N/A') \
        .exclude(assigned_collaborator_name='') \
        .values_list('assigned_collaborator_name', flat=True) \
        .distinct().order_by('assigned_collaborator_name')

    latest_indicators_qs = IndicateursHistoriques.objects.none()
    latest_run_timestamp = None
    all_indicator_names = []
    clients_list = []
    client_indicators_dict = {}

    current_data_qs = base_qs_for_filters
    if current_data_qs.exists():
        latest_run_agg = current_data_qs.aggregate(latest_run=Max('extraction_timestamp'))
        latest_run_timestamp = latest_run_agg.get('latest_run')

    if latest_run_timestamp:
        latest_indicators_qs = current_data_qs.filter(
            extraction_timestamp=latest_run_timestamp
        )
        if selected_collaborator_name:
            latest_indicators_qs = latest_indicators_qs.filter(
                assigned_collaborator_name=selected_collaborator_name
            )
        if selected_closing_date:
            clients_with_closing_date = latest_indicators_qs.filter(
                indicator_name='date_cloture_annuelle',
                indicator_value=selected_closing_date
            ).values_list('client_id', flat=True).distinct()
            latest_indicators_qs = latest_indicators_qs.filter(client_id__in=clients_with_closing_date)

        latest_indicators_qs = latest_indicators_qs.select_related('client').order_by('client__client_name',
                                                                                      'indicator_name')

        client_indicators = defaultdict(list)
        clients_processed = set()
        indicator_names_in_run = set()

        for indicator in latest_indicators_qs:
            client_indicators[indicator.client].append(indicator)
            clients_processed.add(indicator.client)
            indicator_names_in_run.add(indicator.indicator_name)

        client_indicators_dict = dict(client_indicators)
        clients_list = sorted(list(clients_processed), key=lambda c: c.client_name)
        all_indicator_names = sorted(list(indicator_names_in_run)) if indicator_names_in_run else \
            IndicateursHistoriques.objects.filter(extraction_timestamp=latest_run_timestamp) \
                .values_list('indicator_name', flat=True).distinct().order_by('indicator_name')
    context = {
        'user_profile': profile,
        'user_role': user_role,
        'client_indicators': client_indicators_dict,
        'clients_list': clients_list,
        'all_indicator_names': all_indicator_names,
        'latest_run_timestamp': latest_run_timestamp,
        'page_title': 'Tableau de Bord OdooDash',
        'closing_date_choices': closing_date_choices,
        'collaborator_choices': collaborator_choices,
        'selected_closing_date': selected_closing_date,
        'selected_collaborator_name': selected_collaborator_name,
    }
    return render(request, 'core/dashboard.html', context)


# --- NOUVELLE VUE POUR EXÉCUTER LA COMMANDE ---
@user_passes_test(lambda u: u.is_staff and u.is_superuser)  # Seuls les superutilisateurs peuvent exécuter
def trigger_fetch_indicators_view(request):
    """
    Vue pour déclencher la commande de gestion 'fetch_indicators'.
    """
    if request.method == 'POST':  # S'assurer que c'est bien une requête POST pour l'action
        try:
            # Appelle la commande de gestion
            # Vous pouvez passer des arguments à call_command si votre commande en accepte
            # Par exemple: call_command('fetch_indicators', '--verbosity=0')
            call_command('fetch_indicators')
            messages.success(request, "L'extraction des indicateurs a été lancée avec succès.")
        except Exception as e:
            logger.error(f"Erreur lors du lancement de fetch_indicators via l'admin: {e}", exc_info=True)
            messages.error(request, f"Une erreur est survenue lors du lancement de l'extraction : {e}")

        # Rediriger vers la page d'accueil de l'admin après l'exécution
        return redirect(reverse('admin:index'))
    else:
        # Si ce n'est pas POST, rediriger simplement (ou afficher une page de confirmation)
        # Pour plus de sécurité, on pourrait vouloir une page de confirmation avec un bouton POST
        messages.info(request, "Veuillez confirmer l'action via un formulaire POST.")
        return redirect(reverse('admin:index'))

# --- FIN NOUVELLE VUE ---
