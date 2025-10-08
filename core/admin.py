# core/admin.py
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages

# Importez vos modèles
from .models import UserProfile, ConfigurationCabinet, ClientsOdoo, IndicateursHistoriques, ClientOdooStatus
# Importez les fonctions utilitaires
from .utils import encrypt_value, get_odoo_cabinet_collaborators


# --- Gestion User et UserProfile (Intégrée) ---

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profil OdooDash'
    fk_name = 'user'
    
    # Utilise un formulaire personnalisé pour le champ collaborateur
    class UserProfileForm(forms.ModelForm):
        odoo_collaborator_id = forms.ChoiceField(
            label="Collaborateur Odoo Cabinet (Partenaire)",
            required=False,
            help_text="Sélectionnez le partenaire correspondant dans l'Odoo du cabinet."
        )
        class Meta:
            model = UserProfile
            fields = ('role', 'odoo_collaborator_id')

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            collaborator_choices_from_odoo = get_odoo_cabinet_collaborators()
            choices = [('', '---------')] + collaborator_choices_from_odoo
            # Assure que la valeur actuelle est toujours dans la liste même si le collaborateur est archivé dans Odoo
            if self.instance and self.instance.pk and self.instance.odoo_collaborator_id:
                current_id_value = self.instance.odoo_collaborator_id
                if not any(choice[0] == current_id_value for choice in collaborator_choices_from_odoo):
                    choices.append((current_id_value, f"ID Actuel: {current_id_value} (vérifier)"))
            self.fields['odoo_collaborator_id'].choices = choices

    form = UserProfileForm


class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_role')
    list_select_related = ('profile',)

    @admin.display(description='Rôle OdooDash', ordering='profile__role')
    def get_role(self, instance):
        if hasattr(instance, 'profile'):
            return instance.profile.get_role_display()
        return 'N/A'

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# --- Configuration Cabinet (Singleton) ---

@admin.register(ConfigurationCabinet)
class ConfigurationCabinetAdmin(admin.ModelAdmin):
    
    class ConfigurationCabinetForm(forms.ModelForm):
        plain_api_key = forms.CharField(
            label="Nouvelle Clé API (en clair)",
            required=False,
            widget=forms.PasswordInput(render_value=False),
            help_text="Laissez vide pour ne pas modifier la clé existante."
        )
        class Meta:
            model = ConfigurationCabinet
            fields = '__all__'

    form = ConfigurationCabinetForm
    list_display = ('firm_odoo_url', 'firm_odoo_db', 'display_api_key_status')
    readonly_fields = ('firm_odoo_encrypted_api_key',)

    @admin.display(description="Statut Clé API")
    def display_api_key_status(self, obj):
        return "Définie" if obj.firm_odoo_encrypted_api_key else "Non définie"

    def save_model(self, request, obj, form, change):
        plain_key = form.cleaned_data.get('plain_api_key')
        if plain_key:
            try:
                obj.firm_odoo_encrypted_api_key = encrypt_value(plain_key)
                self.message_user(request, "La clé API du cabinet a été chiffrée et sauvegardée.", messages.SUCCESS)
            except ValueError as e:
                self.message_user(request, f"Erreur lors du chiffrement : {e}", messages.ERROR)
                return
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return not ConfigurationCabinet.objects.exists()


# --- Clients Odoo ---

@admin.register(ClientsOdoo)
class ClientsOdooAdmin(admin.ModelAdmin):
    
    class ClientsOdooForm(forms.ModelForm):
        plain_api_key = forms.CharField(
            label="Nouvelle Clé API (en clair)",
            required=False,
            widget=forms.PasswordInput(render_value=False),
            help_text="Laissez vide pour ne pas modifier la clé existante."
        )
        class Meta:
            model = ClientsOdoo
            fields = '__all__'

    form = ClientsOdooForm
    list_display = ('client_name', 'client_odoo_db', 'display_api_key_status', 'is_prelium')
    list_filter = ('is_prelium',)
    search_fields = ('client_name', 'client_odoo_url', 'client_odoo_db')
    list_per_page = 20
    readonly_fields = ('client_odoo_encrypted_api_key',)
    fieldsets = (
        (None, {
            'fields': (
                'client_name', 
                'client_odoo_url', 
                'client_odoo_db', 
                'client_odoo_api_user', 
                'is_prelium',
                'client_contact_email' # <-- AJOUT
            )
        }),
        ('Gestion de la Clé API', {
            'fields': ('plain_api_key', 'client_odoo_encrypted_api_key')
        }),
    )

    @admin.display(description="Statut Clé API")
    def display_api_key_status(self, obj):
        return "Définie" if obj.client_odoo_encrypted_api_key else "Non définie"

    def save_model(self, request, obj, form, change):
        plain_key = form.cleaned_data.get('plain_api_key')
        if plain_key:
            try:
                obj.client_odoo_encrypted_api_key = encrypt_value(plain_key)
                self.message_user(request, f"La clé API pour le client '{obj.client_name}' a été chiffrée et sauvegardée.", messages.SUCCESS)
            except ValueError as e:
                self.message_user(request, f"Erreur lors du chiffrement : {e}", messages.ERROR)
                return
        super().save_model(request, obj, form, change)


# --- Indicateurs Historiques (Lecture seule) ---

@admin.register(IndicateursHistoriques)
class IndicateursHistoriquesAdmin(admin.ModelAdmin):
    list_display = ('client', 'indicator_name', 'indicator_value', 'extraction_timestamp', 'assigned_collaborator_name')
    list_filter = ('client__client_name', 'indicator_name', 'extraction_timestamp', 'assigned_collaborator_name')
    search_fields = ('indicator_name', 'indicator_value', 'client__client_name', 'assigned_collaborator_name')
    readonly_fields = [field.name for field in IndicateursHistoriques._meta.fields]
    list_per_page = 50
    date_hierarchy = 'extraction_timestamp'

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False # Mettre à True si vous voulez permettre l'édition, mais non recommandé
    def has_delete_permission(self, request, obj=None):
        return True # Permet de nettoyer des données si besoin


# --- Statuts Connexion Clients Odoo (Supervision) ---

@admin.register(ClientOdooStatus)
class ClientOdooStatusAdmin(admin.ModelAdmin):
    list_display = ('get_client_name', 'connection_successful', 'last_connection_attempt', 'last_error_message_summary')
    list_filter = ('connection_successful', 'client__client_name')
    search_fields = ('client__client_name', 'last_error_message')
    readonly_fields = ('client', 'connection_successful', 'last_connection_attempt', 'last_error_message')
    list_per_page = 25
    date_hierarchy = 'last_connection_attempt'

    @admin.display(description='Client Odoo', ordering='client__client_name')
    def get_client_name(self, obj):
        return obj.client.client_name

    @admin.display(description="Résumé Erreur")
    def last_error_message_summary(self, obj):
        if obj.last_error_message:
            return (obj.last_error_message[:75] + '...') if len(obj.last_error_message) > 75 else obj.last_error_message
        return "-"

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False