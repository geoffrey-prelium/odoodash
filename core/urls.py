from django.urls import path
from .views import dashboard_view, trigger_fetch_indicators_view, scheduler_fetch_indicators_view, scheduler_check_alerts_view
from . import views

app_name = 'core'

urlpatterns = [
    # URL pour l'affichage du tableau de bord
    path('dashboard/', dashboard_view, name='dashboard'),
    
    # URL pour le bouton "Mettre à jour" dans l'interface d'administration
    path('trigger-fetch/', trigger_fetch_indicators_view, name='trigger_fetch_indicators'),
    
    path('tasks/trigger-fetch/', scheduler_fetch_indicators_view, name='scheduler_trigger_fetch'),

    # URL pour le Cloud Scheduler - vérification des alertes (appeler 20min après l'extraction)
    path('tasks/check-alerts/', scheduler_check_alerts_view, name='scheduler_check_alerts'),

    # Cette URL sera appelée par notre JavaScript pour obtenir les suggestions
    path('api/search-clients/', views.search_clients_autocomplete, name='api-search-clients'),

    path('portal/', views.client_portal_view, name='client_portal'),
    
    path('dispatch/', views.dispatch_login_view, name='dispatch_login'),

    path('api/save-preferences/', views.save_client_preferences, name='save_preferences'),

    # TEMPORAIRE : test email
    path('test-email/', views.test_email_view, name='test_email'),
    
    # TEMPORAIRE : test alertes
    path('test-alerts/', views.test_alerts_view, name='test_alerts'),

]

