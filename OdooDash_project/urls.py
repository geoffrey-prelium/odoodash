# odoo_dash_project/urls.py
from django.contrib import admin
# Assurez-vous que 'include' est bien importé
from django.urls import path, include
from django.views.generic import RedirectView
from core.views import CustomLoginView

urlpatterns = [
    # --- MODIFICATION ICI ---
    # On place votre vue personnalisée AVANT les 'auth.urls' pour qu'elle prenne le dessus
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    
    # Les URLs standards (pour logout, password reset, etc.)
    path('accounts/', include('django.contrib.auth.urls')),
    
    path('admin/', admin.site.urls),
    path('app/', include('core.urls', namespace='core')),
]
