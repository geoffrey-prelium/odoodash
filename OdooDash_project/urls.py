# OdooDash_project/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView # <--- IMPORT AJOUTÉ
from core.views import CustomLoginView 

urlpatterns = [
    # --- NOUVELLE LIGNE POUR LA RACINE ---
    # Redirige automatiquement l'URL vide '' vers la page de login
    path('', RedirectView.as_view(pattern_name='login', permanent=False)),

    # Vos URLs existantes
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    path('app/', include('core.urls', namespace='core')),
]