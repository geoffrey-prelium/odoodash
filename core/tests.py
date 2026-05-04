# core/tests.py
"""
Suite de tests unitaires et d'intégration pour OdooDash.
Couvre : chiffrement, connexion Odoo, modèles, vues, template tags, alertes.
"""
import uuid
from unittest.mock import patch, MagicMock
from datetime import timedelta
from io import StringIO

from django.test import TestCase, RequestFactory, override_settings, Client as DjangoClient
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.core import mail

from cryptography.fernet import Fernet

from core.models import (
    UserProfile, ConfigurationCabinet, ClientsOdoo,
    IndicateursHistoriques, ClientOdooStatus, ClientPreference,
    AlerteIndicateur,
)
from core.templatetags.core_tags import (
    get_item, dict_from_list, format_collab_name, make_alert_key, in_set,
)

# Clé Fernet valide générée pour les tests uniquement
TEST_FERNET_KEY = Fernet.generate_key().decode()


# =============================================================================
#  1. TESTS CHIFFREMENT (utils.encrypt_value / decrypt_value)
# =============================================================================
@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class EncryptionTests(TestCase):
    """Teste le cycle complet chiffrement → déchiffrement Fernet AES-256."""

    def test_encrypt_then_decrypt_returns_original(self):
        from core.utils import encrypt_value, decrypt_value
        original = "ma-clé-api-secrète-12345"
        encrypted = encrypt_value(original)
        self.assertNotEqual(encrypted, original)
        self.assertEqual(decrypt_value(encrypted), original)

    def test_encrypt_empty_string_returns_empty(self):
        from core.utils import encrypt_value
        self.assertEqual(encrypt_value(""), "")

    def test_decrypt_empty_string_returns_empty(self):
        from core.utils import decrypt_value
        self.assertEqual(decrypt_value(""), "")

    def test_decrypt_invalid_token_returns_none(self):
        from core.utils import decrypt_value
        result = decrypt_value("Y2VjaS1uZXN0LXBhcy12YWxpZGU=")
        self.assertIsNone(result)

    def test_encrypt_unicode_characters(self):
        from core.utils import encrypt_value, decrypt_value
        original = "clé-spéciale-àéîöü-日本語"
        encrypted = encrypt_value(original)
        self.assertEqual(decrypt_value(encrypted), original)

    @override_settings(FERNET_KEY="")
    def test_encrypt_without_key_raises_error(self):
        from core.utils import encrypt_value
        with self.assertRaises(ValueError):
            encrypt_value("test")

    @override_settings(FERNET_KEY="")
    def test_decrypt_without_key_returns_none(self):
        from core.utils import decrypt_value
        result = decrypt_value("some-encrypted-data")
        self.assertIsNone(result)


# =============================================================================
#  2. TESTS CONNEXION ODOO (utils.connect_odoo — mocké)
# =============================================================================
class ConnectOdooTests(TestCase):
    """Teste la logique de connexion XML-RPC Odoo avec des mocks."""

    @patch('core.utils.xmlrpc.client.ServerProxy')
    def test_successful_connection(self, MockServerProxy):
        from core.utils import connect_odoo
        mock_common = MagicMock()
        mock_common.version.return_value = {'server_version': '17.0', 'server_serie': '17.0'}
        mock_common.authenticate.return_value = 42
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = [{'latest_version': '17.0.1.2.0'}]
        MockServerProxy.side_effect = [mock_common, mock_object]

        uid, common, obj, version, error = connect_odoo(
            'https://test.odoo.com', 'test_db', 'admin', 'password'
        )
        self.assertEqual(uid, 42)
        self.assertIsNotNone(obj)
        self.assertIsNone(error)
        self.assertIn('17.0', version)

    @patch('core.utils.xmlrpc.client.ServerProxy')
    def test_auth_failure_returns_none_uid(self, MockServerProxy):
        from core.utils import connect_odoo
        mock_common = MagicMock()
        mock_common.version.return_value = {'server_version': '17.0', 'server_serie': '17.0'}
        mock_common.authenticate.return_value = None
        MockServerProxy.return_value = mock_common

        uid, _, _, version, error = connect_odoo(
            'https://test.odoo.com', 'test_db', 'admin', 'wrong'
        )
        self.assertIsNone(uid)
        self.assertIsNotNone(error)
        self.assertIn('17.0', version)

    @patch('core.utils.xmlrpc.client.ServerProxy')
    def test_connection_refused(self, MockServerProxy):
        from core.utils import connect_odoo
        MockServerProxy.side_effect = ConnectionRefusedError("Connection refused")

        uid, _, _, version, error = connect_odoo(
            'https://down.odoo.com', 'db', 'admin', 'pass'
        )
        self.assertIsNone(uid)
        self.assertIn("Connexion refus", error)
        self.assertEqual(version, "Inconnue")

    @patch('core.utils.xmlrpc.client.ServerProxy')
    def test_saas_version_detection(self, MockServerProxy):
        from core.utils import connect_odoo
        mock_common = MagicMock()
        mock_common.version.return_value = {
            'server_version': 'saas~17.3+e',
            'server_serie': '17.0'
        }
        mock_common.authenticate.return_value = 1
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = []
        MockServerProxy.side_effect = [mock_common, mock_object]

        uid, _, _, version, error = connect_odoo(
            'https://saas.odoo.com', 'db', 'admin', 'pass'
        )
        self.assertEqual(uid, 1)
        self.assertEqual(version, '17.3')


# =============================================================================
#  3. TESTS NETTOYAGE VALEURS (views.clean_numeric_value)
# =============================================================================
class CleanNumericValueTests(TestCase):
    """Teste la fonction utilitaire de nettoyage des valeurs numériques."""

    def test_standard_float(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("1200.50"), 1200.50)

    def test_value_with_euro_sign(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("1200.50€"), 1200.50)

    def test_value_with_euro_and_space(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("1200.50 €"), 1200.50)

    def test_value_with_spaces_and_commas(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("1,200.50"), 1200.50)

    def test_none_returns_zero(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value(None), 0)

    def test_empty_string_returns_zero(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value(""), 0)

    def test_non_numeric_returns_zero(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("N/A"), 0)

    def test_negative_value(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("-500.25"), -500.25)

    def test_integer_value(self):
        from core.views import clean_numeric_value
        self.assertEqual(clean_numeric_value("42"), 42.0)


# =============================================================================
#  4. TESTS MODÈLE AlerteIndicateur.check_threshold()
# =============================================================================
@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class AlerteIndicateurCheckThresholdTests(TestCase):
    """Teste la logique de comparaison des seuils d'alerte."""

    @classmethod
    def setUpTestData(cls):
        from core.utils import encrypt_value
        cls.odoo_client = ClientsOdoo.objects.create(
            client_name="Client Test Alertes",
            client_odoo_url="https://test.odoo.com",
            client_odoo_db="test_db",
            client_odoo_api_user="admin",
            client_odoo_encrypted_api_key=encrypt_value("fake-key"),
        )

    def _create_alert(self, comparator, threshold):
        return AlerteIndicateur(
            client=self.odoo_client,
            indicator_name="test_indicator",
            comparator=comparator,
            threshold=threshold,
            collaborator_email="test@prelium.fr",
        )

    def test_gt_threshold_breached(self):
        alert = self._create_alert('gt', 10.0)
        self.assertTrue(alert.check_threshold("15"))

    def test_gt_threshold_not_breached(self):
        alert = self._create_alert('gt', 10.0)
        self.assertFalse(alert.check_threshold("5"))

    def test_gt_exact_value_not_breached(self):
        alert = self._create_alert('gt', 10.0)
        self.assertFalse(alert.check_threshold("10"))

    def test_gte_exact_value_breached(self):
        alert = self._create_alert('gte', 10.0)
        self.assertTrue(alert.check_threshold("10"))

    def test_lt_threshold_breached(self):
        alert = self._create_alert('lt', 5.0)
        self.assertTrue(alert.check_threshold("3"))

    def test_lt_threshold_not_breached(self):
        alert = self._create_alert('lt', 5.0)
        self.assertFalse(alert.check_threshold("10"))

    def test_lte_exact_value_breached(self):
        alert = self._create_alert('lte', 5.0)
        self.assertTrue(alert.check_threshold("5"))

    def test_non_numeric_value_returns_false(self):
        alert = self._create_alert('gt', 10.0)
        self.assertFalse(alert.check_threshold("N/A"))

    def test_none_value_returns_false(self):
        alert = self._create_alert('gt', 10.0)
        self.assertFalse(alert.check_threshold(None))

    def test_value_with_formatting(self):
        """Vérifie que les valeurs formatées (espaces, virgules) sont nettoyées."""
        alert = self._create_alert('gt', 1000.0)
        self.assertTrue(alert.check_threshold("1 500,50 €"))


# =============================================================================
#  5. TESTS TEMPLATE TAGS (core_tags.py)
# =============================================================================
class TemplateTagsTests(TestCase):
    """Teste les filtres de template personnalisés."""

    def test_get_item_existing_key(self):
        d = {'a': 1, 'b': 2}
        self.assertEqual(get_item(d, 'a'), 1)

    def test_get_item_missing_key(self):
        d = {'a': 1}
        self.assertIsNone(get_item(d, 'z'))

    def test_get_item_non_dict_returns_none(self):
        self.assertIsNone(get_item("not a dict", 'key'))

    def test_get_item_none_returns_none(self):
        self.assertIsNone(get_item(None, 'key'))

    def test_dict_from_list_basic(self):
        class FakeObj:
            def __init__(self, name):
                self.indicator_name = name
        objs = [FakeObj("  Version Odoo  "), FakeObj("Nb Modules")]
        result = dict_from_list(objs, 'indicator_name')
        self.assertIn('version odoo', result)
        self.assertIn('nb modules', result)

    def test_dict_from_list_empty(self):
        self.assertEqual(dict_from_list([], 'name'), {})

    def test_dict_from_list_none(self):
        self.assertEqual(dict_from_list(None, 'name'), {})

    def test_format_collab_name_with_company(self):
        self.assertEqual(format_collab_name("Prelium, Geoffrey LECLUSE"), "Geoffrey LECLUSE")

    def test_format_collab_name_without_comma(self):
        self.assertEqual(format_collab_name("Geoffrey LECLUSE"), "Geoffrey LECLUSE")

    def test_format_collab_name_non_string(self):
        self.assertEqual(format_collab_name(42), 42)

    def test_in_set_true(self):
        s = {"abc|test", "def|other"}
        self.assertTrue(in_set("abc|test", s))

    def test_in_set_false(self):
        s = {"abc|test"}
        self.assertFalse(in_set("xyz|missing", s))

    def test_make_alert_key(self):
        class FakeClient:
            pk = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        result = make_alert_key(FakeClient(), "nb modules actifs")
        self.assertEqual(result, "12345678-1234-1234-1234-123456789abc|nb modules actifs")


# =============================================================================
#  6. TESTS MODÈLES (création, relations, __str__)
# =============================================================================
@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class ModelCreationTests(TestCase):
    """Teste la création des modèles et leurs relations."""

    @classmethod
    def setUpTestData(cls):
        from core.utils import encrypt_value
        cls.user = User.objects.create_user('testuser', 'test@test.com', 'pass1234')
        cls.odoo_client = ClientsOdoo.objects.create(
            client_name="SARL Test",
            client_odoo_url="https://test.odoo.com",
            client_odoo_db="test_db",
            client_odoo_api_user="admin",
            client_odoo_encrypted_api_key=encrypt_value("test-api-key"),
        )

    def test_user_profile_creation(self):
        profile = UserProfile.objects.create(user=self.user, role='collaborateur')
        self.assertEqual(str(profile), "Profil de testuser (Collaborateur)")
        self.assertEqual(profile.get_role_display(), "Collaborateur")

    def test_client_odoo_str(self):
        self.assertEqual(str(self.odoo_client), "SARL Test")

    def test_indicateur_creation_and_index(self):
        ind = IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="nb utilisateurs actifs",
            indicator_value="15",
            extraction_timestamp=timezone.now(),
        )
        self.assertIn("nb utilisateurs actifs", str(ind))

    def test_client_odoo_status(self):
        status = ClientOdooStatus.objects.create(
            client=self.odoo_client,
            connection_successful=True,
        )
        self.assertIn("Réussie", str(status))

    def test_client_preference_json(self):
        profile = UserProfile.objects.create(user=self.user, role='client')
        pref = ClientPreference.objects.create(
            user=profile,
            visible_indicators=["nb utilisateurs actifs", "resultat provisoire"],
            default_period=60,
        )
        self.assertEqual(len(pref.visible_indicators), 2)
        self.assertEqual(pref.default_period, 60)

    def test_alerte_str(self):
        alert = AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="operations à qualifier",
            comparator='gt',
            threshold=50.0,
            collaborator_email="test@prelium.fr",
        )
        self.assertIn("operations à qualifier", str(alert))
        self.assertIn("SARL Test", str(alert))

    def test_cascade_delete_client_removes_indicators(self):
        from core.utils import encrypt_value
        temp_client = ClientsOdoo.objects.create(
            client_name="Temp Client",
            client_odoo_url="https://temp.odoo.com",
            client_odoo_db="temp_db",
            client_odoo_api_user="admin",
            client_odoo_encrypted_api_key=encrypt_value("key"),
        )
        IndicateursHistoriques.objects.create(
            client=temp_client, indicator_name="test",
            indicator_value="1", extraction_timestamp=timezone.now(),
        )
        self.assertEqual(IndicateursHistoriques.objects.filter(client=temp_client).count(), 1)
        client_pk = temp_client.pk
        temp_client.delete()
        self.assertEqual(IndicateursHistoriques.objects.filter(client_id=client_pk).count(), 0)


# =============================================================================
#  7. TESTS VUES SCHEDULER (sécurité des endpoints)
# =============================================================================
@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class SchedulerViewSecurityTests(TestCase):
    """Teste la sécurité des vues déclenchées par Cloud Scheduler."""

    def test_fetch_without_header_returns_403(self):
        response = self.client.post(reverse('core:scheduler_trigger_fetch'))
        self.assertEqual(response.status_code, 403)

    def test_fetch_with_get_method_returns_405(self):
        response = self.client.get(
            reverse('core:scheduler_trigger_fetch'),
            HTTP_X_CLOUDSCHEDULER='true',
        )
        self.assertEqual(response.status_code, 405)

    @patch('core.views.call_command')
    def test_fetch_with_valid_header_returns_200(self, mock_cmd):
        response = self.client.post(
            reverse('core:scheduler_trigger_fetch'),
            HTTP_X_CLOUDSCHEDULER='true',
        )
        self.assertEqual(response.status_code, 200)
        mock_cmd.assert_called_once_with('fetch_indicators')

    def test_alerts_without_header_returns_403(self):
        response = self.client.post(reverse('core:scheduler_check_alerts'))
        self.assertEqual(response.status_code, 403)

    @patch('core.views.call_command')
    def test_alerts_with_valid_header_returns_200(self, mock_cmd):
        response = self.client.post(
            reverse('core:scheduler_check_alerts'),
            HTTP_X_CLOUDSCHEDULER='true',
        )
        self.assertEqual(response.status_code, 200)
        mock_cmd.assert_called_once_with('check_alerts')


# =============================================================================
#  8. TESTS VUES AUTHENTIFIÉES (dashboard, portail, dispatch)
# =============================================================================
@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class AuthenticatedViewTests(TestCase):
    """Teste les vues protégées par @login_required."""

    @classmethod
    def setUpTestData(cls):
        from core.utils import encrypt_value
        cls.admin_user = User.objects.create_user('admin_test', 'a@t.com', 'pass1234')
        cls.client_user = User.objects.create_user('client_test', 'c@t.com', 'pass1234')
        cls.odoo_client = ClientsOdoo.objects.create(
            client_name="Mon Dossier",
            client_odoo_url="https://test.odoo.com",
            client_odoo_db="test_db",
            client_odoo_api_user="admin",
            client_odoo_encrypted_api_key=encrypt_value("key"),
        )
        UserProfile.objects.create(user=cls.admin_user, role='admin')
        UserProfile.objects.create(
            user=cls.client_user, role='client',
            client_odoo_link=cls.odoo_client,
        )

    def test_dashboard_redirects_anonymous(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_dashboard_accessible_for_admin(self):
        self.client.login(username='admin_test', password='pass1234')
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dispatch_redirects_client_to_portal(self):
        self.client.login(username='client_test', password='pass1234')
        response = self.client.get(reverse('core:dispatch_login'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('portal', response.url)

    def test_dispatch_redirects_admin_to_dashboard(self):
        self.client.login(username='admin_test', password='pass1234')
        response = self.client.get(reverse('core:dispatch_login'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('dashboard', response.url)

    def test_portal_accessible_for_client(self):
        self.client.login(username='client_test', password='pass1234')
        response = self.client.get(reverse('core:client_portal'))
        self.assertEqual(response.status_code, 200)

    def test_portal_redirects_admin_to_dashboard(self):
        self.client.login(username='admin_test', password='pass1234')
        response = self.client.get(reverse('core:client_portal'))
        self.assertEqual(response.status_code, 302)

    def test_save_preferences_api(self):
        self.client.login(username='client_test', password='pass1234')
        import json
        response = self.client.post(
            reverse('core:save_preferences'),
            data=json.dumps({'indicators': ['nb utilisateurs actifs']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        pref = ClientPreference.objects.get(user=self.client_user.profile)
        self.assertEqual(pref.visible_indicators, ['nb utilisateurs actifs'])

    def test_search_autocomplete_requires_min_chars(self):
        self.client.login(username='admin_test', password='pass1234')
        response = self.client.get(reverse('core:api-search-clients'), {'term': 'M'})
        self.assertEqual(response.json(), [])

    def test_search_autocomplete_returns_results(self):
        self.client.login(username='admin_test', password='pass1234')
        response = self.client.get(reverse('core:api-search-clients'), {'term': 'Mon'})
        self.assertIn("Mon Dossier", response.json())


# =============================================================================
#  9. TESTS COMMANDE check_alerts (envoi email)
# =============================================================================
@override_settings(
    FERNET_KEY=TEST_FERNET_KEY,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='test@odoodash.com',
)
class CheckAlertsCommandTests(TestCase):
    """Teste la commande de gestion check_alerts avec envoi d'emails."""

    @classmethod
    def setUpTestData(cls):
        from core.utils import encrypt_value
        cls.odoo_client = ClientsOdoo.objects.create(
            client_name="Client Alerte Test",
            client_odoo_url="https://test.odoo.com",
            client_odoo_db="test_db",
            client_odoo_api_user="admin",
            client_odoo_encrypted_api_key=encrypt_value("key"),
        )

    def test_alert_sends_email_when_threshold_breached(self):
        """Vérifie qu'un email est envoyé quand le seuil est dépassé."""
        IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="operations à qualifier",
            indicator_value="100",
            extraction_timestamp=timezone.now(),
        )
        AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="operations à qualifier",
            comparator='gt',
            threshold=50.0,
            collaborator_email="collab@prelium.fr",
            is_active=True,
        )
        from django.core.management import call_command
        out = StringIO()
        call_command('check_alerts', stdout=out, stderr=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("operations à qualifier", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["collab@prelium.fr"])

    def test_alert_not_sent_when_below_threshold(self):
        """Vérifie qu'aucun email n'est envoyé quand le seuil n'est pas atteint."""
        IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="nombre de factures en retard",
            indicator_value="3",
            extraction_timestamp=timezone.now(),
        )
        AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="nombre de factures en retard",
            comparator='gt',
            threshold=10.0,
            collaborator_email="collab@prelium.fr",
            is_active=True,
        )
        from django.core.management import call_command
        out = StringIO()
        call_command('check_alerts', stdout=out, stderr=out)

        self.assertEqual(len(mail.outbox), 0)

    def test_deduplication_48h(self):
        """Vérifie que l'alerte n'est pas renvoyée dans les 48h."""
        IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="test_dedup",
            indicator_value="100",
            extraction_timestamp=timezone.now(),
        )
        AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="test_dedup",
            comparator='gt',
            threshold=50.0,
            collaborator_email="collab@prelium.fr",
            is_active=True,
            last_alert_sent=timezone.now() - timedelta(hours=24),
        )
        from django.core.management import call_command
        out = StringIO()
        call_command('check_alerts', stdout=out, stderr=out)

        self.assertEqual(len(mail.outbox), 0)

    def test_alert_reset_when_value_returns_below(self):
        """Vérifie que last_alert_sent est reset quand la valeur revient sous le seuil."""
        IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="test_reset",
            indicator_value="10",
            extraction_timestamp=timezone.now(),
        )
        alert = AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="test_reset",
            comparator='gt',
            threshold=50.0,
            collaborator_email="collab@prelium.fr",
            is_active=True,
            last_alert_sent=timezone.now() - timedelta(hours=72),
        )
        from django.core.management import call_command
        out = StringIO()
        call_command('check_alerts', stdout=out, stderr=out)

        alert.refresh_from_db()
        self.assertIsNone(alert.last_alert_sent)

    def test_inactive_alert_is_ignored(self):
        """Vérifie que les alertes désactivées sont ignorées."""
        IndicateursHistoriques.objects.create(
            client=self.odoo_client,
            indicator_name="test_inactive",
            indicator_value="100",
            extraction_timestamp=timezone.now(),
        )
        AlerteIndicateur.objects.create(
            client=self.odoo_client,
            indicator_name="test_inactive",
            comparator='gt',
            threshold=50.0,
            collaborator_email="collab@prelium.fr",
            is_active=False,
        )
        from django.core.management import call_command
        out = StringIO()
        call_command('check_alerts', stdout=out, stderr=out)

        self.assertEqual(len(mail.outbox), 0)
