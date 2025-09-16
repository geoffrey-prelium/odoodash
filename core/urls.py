from django.urls import path
from .views import dashboard_view, trigger_fetch_indicators_view, scheduler_fetch_indicators_view

app_name = 'core'

urlpatterns = [
    # URL pour l'affichage du tableau de bord
    path('dashboard/', dashboard_view, name='dashboard'),
    
    # URL pour le bouton "Mettre à jour" dans l'interface d'administration
    path('trigger-fetch/', trigger_fetch_indicators_view, name='trigger_fetch_indicators'),
    
    # URL sécurisée pour le planificateur Google Cloud Scheduler
    path('tasks/trigger-fetch/', scheduler_fetch_indicators_view, name='scheduler_trigger_fetch'),
]

