# core/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max, Q
from .models import IndicateursHistoriques, UserProfile, ClientsOdoo, AlerteIndicateur
from collections import defaultdict
import logging
import json  # <--- AJOUTÉ : Nécessaire pour client_portal_view

from django.core.management import call_command
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy

import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from .models import IndicateursHistoriques, UserProfile
from .models import ClientPreference
from datetime import timedelta
from django.views.decorators.http import require_POST
from django.utils import timezone

# from .views import INDICATOR_CATEGORIES

logger = logging.getLogger(__name__)

# --- DÉFINITION DES CATÉGORIES D'INDICATEURS (RÉORGANISÉES) ---
INDICATOR_CATEGORIES = {
    'Général': [
        'version odoo', 'type de base', 'type hebergement', 'code abonnement',
        'url odoo', 'nom bdd', 'date expiration base', 'nb societes'
    ],
    'Utilisateurs': [
        'nb utilisateurs actifs', 'nb utilisateurs lpde'
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
    search_query = request.GET.get('search', '')

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

    # --- INITIALISATION DES VARIABLES (CORRECTION UnboundLocalError) ---
    # On initialise tout ici pour être sûr que les variables existent même si latest_run_timestamp est None
    latest_indicators_qs = IndicateursHistoriques.objects.none()
    latest_run_timestamp = None
    clients_list = []
    client_indicators_dict = {}
    all_indicator_names_for_columns = []
    show_collaborator_column = False
    show_extraction_date_column = False

    current_data_qs = base_qs_for_filter_options
    if current_data_qs.exists():
        latest_run_agg = current_data_qs.aggregate(latest_run=Max('extraction_timestamp'))
        latest_run_timestamp = latest_run_agg.get('latest_run')

    # MODIFICATION : On affiche des données si on en a, peu importe si elles datent un peu pour certains clients
    if current_data_qs.exists():
        # Au lieu de : latest_indicators_qs = current_data_qs.filter(extraction_timestamp=latest_run_timestamp)
        # On utilise une sous-requête pour prendre la dernière date DISPONIBLE pour CHAQUE client.
        
        from django.db.models import OuterRef, Subquery
        
        latest_date_subquery = IndicateursHistoriques.objects.filter(
            client=OuterRef('client')
        ).order_by('-extraction_timestamp').values('extraction_timestamp')[:1]

        latest_indicators_qs = current_data_qs.filter(
            extraction_timestamp=Subquery(latest_date_subquery)
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

        # Filtre de recherche par nom
        if search_query:
            latest_indicators_qs = latest_indicators_qs.filter(client__client_name__icontains=search_query)

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

    # --- DÉTECTION DES ALERTES ---
    alerted_cells = set()  # Contiendra des clés "client_pk|indicator_name"
    try:
        active_alerts = AlerteIndicateur.objects.filter(is_active=True).select_related('client')
        for alert in active_alerts:
            # Chercher la valeur actuelle de cet indicateur pour ce client
            client_indicators = client_indicators_dict.get(alert.client, [])
            for indicator in client_indicators:
                if indicator.indicator_name.strip().lower() == alert.indicator_name.strip().lower():
                    if alert.check_threshold(indicator.indicator_value):
                        alerted_cells.add(f"{alert.client.pk}|{alert.indicator_name}")
                    break
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des alertes: {e}")

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
        'search_query': search_query,
        'alerted_cells': alerted_cells,
    }
    return render(request, 'core/dashboard.html', context)


@user_passes_test(lambda u: u.is_staff)
def trigger_fetch_indicators_view(request):
    if request.method == 'POST':
        import threading

        def run_extraction_and_alerts():
            try:
                call_command('fetch_indicators')
            except Exception as e:
                logger.error(f"Erreur fetch_indicators (background): {e}", exc_info=True)
            try:
                call_command('check_alerts')
            except Exception as e:
                logger.error(f"Erreur check_alerts (background): {e}", exc_info=True)

        logger.info(f"Lancement de fetch_indicators + check_alerts en arrière-plan par: {request.user.username}")
        thread = threading.Thread(target=run_extraction_and_alerts, daemon=False)
        thread.start()
        messages.success(request,
                         "L'extraction des indicateurs a été lancée en arrière-plan. Les données et alertes seront traitées sous peu.")
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
            return HttpResponse("Extraction des indicateurs terminée.", status=200)
        except Exception as e:
            logger.error(f"Erreur fetch_indicators via scheduler: {e}", exc_info=True)
            return HttpResponse(f"Erreur extraction: {e}", status=500)
    
    return HttpResponse("Méthode POST requise.", status=405)


@csrf_exempt
def scheduler_check_alerts_view(request):
    """
    Vue sécurisée pour vérifier les alertes. Appelée par un Cloud Scheduler séparé,
    après l'extraction des indicateurs.
    """
    if request.headers.get("X-CloudScheduler") != "true":
        logger.warning("Tentative d'accès non autorisée au check_alerts scheduler.")
        return HttpResponseForbidden("Accès non autorisé.")

    if request.method == 'POST':
        try:
            logger.info("Lancement de check_alerts par le scheduler Cloud.")
            call_command('check_alerts')
            return HttpResponse("Vérification des alertes terminée.", status=200)
        except Exception as e:
            logger.error(f"Erreur check_alerts via scheduler: {e}", exc_info=True)
            return HttpResponse(f"Erreur check_alerts: {e}", status=500)
    
    return HttpResponse("Méthode POST requise.", status=405)

# Fonction utilitaire pour nettoyer les valeurs numériques (ex: "1 200,50 €" -> 1200.50)
def clean_numeric_value(value):
    if not value:
        return 0
    try:
        # On garde chiffres, points et signes moins. On vire les virgules et espaces.
        clean_str = str(value).replace(',', '').replace(' ', '').replace('€', '').strip()
        return float(clean_str)
    except ValueError:
        return 0

@login_required
def client_portal_view(request):
    user = request.user
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return render(request, 'core/error.html', {'message': "Profil non trouvé."})

    if profile.role != 'client' or not profile.client_odoo_link:
        return redirect('core:dashboard')

    client_obj = profile.client_odoo_link

    # --- GESTION DE LA PÉRIODE ---
    # On récupère le paramètre GET 'days' (défaut: 30 jours)
    try:
        days_range = int(request.GET.get('days', 30))
    except ValueError:
        days_range = 30
    
    # Date limite pour les graphiques
    date_threshold = timezone.now() - timedelta(days=days_range)

    # --- GESTION DES PRÉFÉRENCES ---
    # Liste de TOUS les graphiques possibles (Nom technique : Titre affiché)
    ALL_AVAILABLE_CHARTS = {
        'nb utilisateurs actifs': 'Utilisateurs Actifs',
        'operations à qualifier': 'Opérations à Qualifier',
        'nombre de commandes à facturer': 'Commandes à Facturer',
        'resultat provisoire annee courante': 'Résultat Provisoire',
        'nombre de factures en retard': 'Factures en Retard',
        'opportunités créées (30j)': 'Opportunités Commerciales'
    }

    # Récupérer les préférences de l'utilisateur
    try:
        user_pref = ClientPreference.objects.get(user=profile)
        selected_indicators = user_pref.visible_indicators
        # Si la liste est vide (premier passage), on met tout par défaut
        if not selected_indicators:
            selected_indicators = list(ALL_AVAILABLE_CHARTS.keys())
    except ClientPreference.DoesNotExist:
        # Pas de préférences ? On montre tout par défaut
        selected_indicators = list(ALL_AVAILABLE_CHARTS.keys())

    # 1. RÉCUPÉRER LES DERNIÈRES DONNÉES (KPIs - Toujours affichés)
    latest_run = IndicateursHistoriques.objects.filter(client=client_obj).aggregate(Max('extraction_timestamp'))['extraction_timestamp__max']
    latest_indicators = {}
    if latest_run:
        qs_latest = IndicateursHistoriques.objects.filter(client=client_obj, extraction_timestamp=latest_run)
        for ind in qs_latest:
            latest_indicators[ind.indicator_name] = ind.indicator_value

    # 2. PRÉPARER LES DONNÉES GRAPHIQUES (Filtrées par période et préférences)
    charts_data = {}
    
    # On détermine d'abord les dates communes basées sur la période choisie
    # On prend un indicateur stable pour définir l'axe X
    base_qs = IndicateursHistoriques.objects.filter(
        client=client_obj, 
        indicator_name='nb utilisateurs actifs',
        extraction_timestamp__gte=date_threshold # <-- Filtre de date
    ).order_by('extraction_timestamp')
    
    dates = [d.strftime('%d/%m') for d in base_qs.values_list('extraction_timestamp', flat=True)]

    # On ne génère les données QUE pour les indicateurs choisis par l'utilisateur
    for indicator in selected_indicators:
        if indicator in ALL_AVAILABLE_CHARTS: # Sécurité
            qs = IndicateursHistoriques.objects.filter(
                client=client_obj, 
                indicator_name=indicator,
                extraction_timestamp__gte=date_threshold
            ).order_by('extraction_timestamp')
            
            values = [clean_numeric_value(v) for v in qs.values_list('indicator_value', flat=True)]
            charts_data[indicator] = json.dumps(values)

    context = {
        'client': client_obj,
        'kpis': latest_indicators,
        'latest_run_date': latest_run,
        'chart_dates': json.dumps(dates),
        'charts_data': charts_data,
        'categories': INDICATOR_CATEGORIES,
        'page_title': f"Mon Espace - {client_obj.client_name}",
        
        # Nouvelles variables pour le template
        'current_days': days_range,
        'available_charts': ALL_AVAILABLE_CHARTS, # Pour le menu de config
        'selected_charts': selected_indicators,   # Pour cocher les cases
    }
    return render(request, 'core/client_portal.html', context)

@login_required
def dispatch_login_view(request):
    user = request.user
    print(f"--> PASSAGE DANS DISPATCH pour : {user.username}")  # <--- LOG IMPORTANT
    try:
        profile = user.profile
        print(f"--> Rôle détecté : {profile.role}") # <--- LOG IMPORTANT
        
        if profile.role == 'client':
            print("--> Décision : Redirection PORTAIL")
            return redirect('core:client_portal')
        else:
            print("--> Décision : Redirection DASHBOARD")
            return redirect('core:dashboard')
    except UserProfile.DoesNotExist:
        print("--> ERREUR : Pas de profil")
        return redirect('core:dashboard')
    
class CustomLoginView(LoginView):
    def get_success_url(self):
        user = self.request.user
        
        # 1. Logique Prioritaire pour les Clients
        try:
            if hasattr(user, 'profile') and user.profile.role == 'client':
                print(f"DEBUG: Login Client détecté ({user.username}) -> Force Portail")
                return reverse_lazy('core:client_portal')
        except Exception as e:
            print(f"DEBUG: Erreur profil au login: {e}")

        # 2. Logique Standard pour les autres (Admin/Collaborateurs)
        # Cela respectera le ?next= s'il existe, ou ira vers LOGIN_REDIRECT_URL
        return super().get_success_url()
    
@login_required
@require_POST
def save_client_preferences(request):
    try:
        data = json.loads(request.body)
        indicators = data.get('indicators', [])

        # On récupère ou crée l'objet de préférence
        pref, created = ClientPreference.objects.get_or_create(user=request.user.profile)
        pref.visible_indicators = indicators
        pref.save()

        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# --- VUE DE TEST EMAIL (TEMPORAIRE) ---
@user_passes_test(lambda u: u.is_staff)
def test_email_view(request):
    from django.core.mail import send_mail
    from django.conf import settings as s
    try:
        send_mail(
            '[OdooDash] Test Email',
            'Ceci est un email de test depuis OdooDash.',
            s.DEFAULT_FROM_EMAIL,
            [s.EMAIL_HOST_USER],
            fail_silently=False,
        )
        return HttpResponse(
            f"Email envoyé avec succès !<br>"
            f"HOST: {s.EMAIL_HOST}<br>"
            f"PORT: {s.EMAIL_PORT}<br>"
            f"USER: {s.EMAIL_HOST_USER}<br>"
            f"FROM: {s.DEFAULT_FROM_EMAIL}<br>"
            f"PASSWORD: {'***' + s.EMAIL_HOST_PASSWORD[-4:] if s.EMAIL_HOST_PASSWORD else 'VIDE'}"
        )
    except Exception as e:
        return HttpResponse(
            f"ERREUR: {e}<br><br>"
            f"HOST: {s.EMAIL_HOST}<br>"
            f"PORT: {s.EMAIL_PORT}<br>"
            f"USER: {s.EMAIL_HOST_USER}<br>"
            f"FROM: {s.DEFAULT_FROM_EMAIL}<br>"
            f"PASSWORD: {'***' + s.EMAIL_HOST_PASSWORD[-4:] if s.EMAIL_HOST_PASSWORD else 'VIDE'}",
            status=500
        )


# --- VUE DE TEST ALERTES (TEMPORAIRE) ---
@user_passes_test(lambda u: u.is_staff)
def test_alerts_view(request):
    from django.utils import timezone
    from datetime import timedelta
    from django.core.mail import send_mail
    from django.conf import settings as s
    from .models import AlerteIndicateur, IndicateursHistoriques

    output = ["<h2>Test des Alertes Indicateurs</h2>"]
    output.append(f"<p>SMTP: {s.EMAIL_HOST}:{s.EMAIL_PORT} | USER: {s.EMAIL_HOST_USER} | FROM: {s.DEFAULT_FROM_EMAIL}</p>")
    output.append("<hr>")

    try:
        active_alerts = AlerteIndicateur.objects.filter(is_active=True).select_related('client')
        output.append(f"<p><b>Alertes actives: {active_alerts.count()}</b></p>")

        for alert in active_alerts:
            output.append(f"<h3>Alerte: {alert.client.client_name} | {alert.indicator_name} {alert.get_comparator_display()} {alert.threshold}</h3>")
            output.append(f"<p>Email: {alert.collaborator_email} | last_alert_sent: {alert.last_alert_sent}</p>")

            latest_indicator = IndicateursHistoriques.objects.filter(
                client=alert.client,
                indicator_name__iexact=alert.indicator_name
            ).order_by('-extraction_timestamp').first()

            if not latest_indicator:
                output.append("<p style='color:orange'>Aucun indicateur trouvé en BDD pour ce nom.</p>")
                # Chercher des noms approchants
                similar = IndicateursHistoriques.objects.filter(
                    client=alert.client,
                    indicator_name__icontains=alert.indicator_name.split()[0]
                ).values_list('indicator_name', flat=True).distinct()[:10]
                output.append(f"<p>Noms approchants: {list(similar)}</p>")
                continue

            output.append(f"<p>Valeur en BDD: '{latest_indicator.indicator_value}' (extraction: {latest_indicator.extraction_timestamp})</p>")

            threshold_breached = alert.check_threshold(latest_indicator.indicator_value)
            output.append(f"<p>Seuil franchi: <b style='color:{'red' if threshold_breached else 'green'}'>{threshold_breached}</b></p>")

            if threshold_breached:
                should_send = False
                if alert.last_alert_sent is None:
                    should_send = True
                    output.append("<p>last_alert_sent est None → devrait envoyer</p>")
                else:
                    time_since = timezone.now() - alert.last_alert_sent
                    should_send = time_since > timedelta(hours=48)
                    output.append(f"<p>Temps depuis dernier mail: {time_since} → {'envoyer' if should_send else 'ignoré (< 48h)'}</p>")

                if should_send and request.GET.get('send') == '1':
                    try:
                        send_mail(
                            f'[OdooDash] Alerte TEST: {alert.indicator_name} pour {alert.client.client_name}',
                            f'Valeur: {latest_indicator.indicator_value}\nSeuil: {alert.get_comparator_display()} {alert.threshold}',
                            s.DEFAULT_FROM_EMAIL,
                            [alert.collaborator_email],
                            fail_silently=False,
                        )
                        output.append("<p style='color:green'><b>EMAIL ENVOYÉ AVEC SUCCÈS !</b></p>")
                    except Exception as e_mail:
                        output.append(f"<p style='color:red'><b>ERREUR ENVOI: {e_mail}</b></p>")
                elif should_send:
                    output.append("<p>Ajoutez <b>?send=1</b> à l'URL pour envoyer le mail de test.</p>")

    except Exception as e:
        output.append(f"<p style='color:red'>ERREUR: {e}</p>")
        import traceback
        output.append(f"<pre>{traceback.format_exc()}</pre>")

    return HttpResponse("\n".join(output))