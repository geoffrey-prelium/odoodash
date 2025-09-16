"""
Django settings for OdooDash_project project.
Version finale et robuste pour le déploiement sur Cloud Run et le développement local.
"""
import os
import io
import dj_database_url
from pathlib import Path
import traceback
import sys

# ==============================================================================
#  1. DÉTECTION DE L'ENVIRONNEMENT ET CHARGEMENT DES SECRETS
# ==============================================================================
# La variable 'K_SERVICE' est une variable standard et fiable définie par Google Cloud Run.
IS_PRODUCTION = "K_SERVICE" in os.environ

if IS_PRODUCTION:
    # En production, on charge TOUT depuis Google Secret Manager.
    print("--- MODE PRODUCTION DÉTECTÉ ---", file=sys.stderr)
    try:
        import google.auth
        from google.cloud import secretmanager
        from dotenv import load_dotenv

        _, project_id = google.auth.default()
        client = secretmanager.SecretManagerServiceClient()
        
        settings_name = os.environ.get("SETTINGS_NAME", "django-settings")
        name = f"projects/{project_id}/secrets/{settings_name}/versions/latest"
        
        print(f"INFO: Chargement du secret '{name}'...", file=sys.stderr)
        payload = client.access_secret_version(name=name).payload.data.decode("UTF-8")
        
        load_dotenv(stream=io.StringIO(payload))
        print("INFO: Secrets chargés avec succès.", file=sys.stderr)

    except Exception as e:
        print("="*80, file=sys.stderr)
        print("ERREUR CRITIQUE : Échec du chargement des secrets depuis Secret Manager.", file=sys.stderr)
        print(f"Exception: {type(e).__name__} - {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("="*80, file=sys.stderr)
        raise RuntimeError("Impossible de charger la configuration de production.") from e
else:
    # En local, on charge simplement depuis le fichier .env
    print("--- MODE DÉVELOPPEMENT LOCAL DÉTECTÉ ---", file=sys.stderr)
    from dotenv import load_dotenv
    load_dotenv()


# ==============================================================================
#  2. CONFIGURATION DJANGO
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Paramètres de base (flexibles pour le local, stricts pour la prod) ---
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-for-local-dev-only')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
FERNET_KEY = os.getenv('FERNET_KEY')

# --- Validation des clés critiques ---
if not FERNET_KEY and not DEBUG:
    raise ValueError("La clé de chiffrement FERNET_KEY est manquante en production.")
elif not FERNET_KEY and DEBUG:
    print("ATTENTION: FERNET_KEY n'est pas définie dans .env. Le chiffrement échouera.", file=sys.stderr)


# --- Hôtes et Sécurité ---
ALLOWED_HOSTS = []
CSRF_TRUSTED_ORIGINS = []

if IS_PRODUCTION:
    # --- CORRECTION ---
    # Autorise toutes les URLs se terminant par .run.app, ce qui est la méthode
    # recommandée et la plus robuste pour Cloud Run.
    ALLOWED_HOSTS.append('.run.app')
    # Pour la protection CSRF, on autorise toutes les URLs sécurisées de Cloud Run.
    CSRF_TRUSTED_ORIGINS.append('https://*.run.app')
    
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
else:
    ALLOWED_HOSTS.extend(['localhost', '127.0.0.1'])


# --- Applications et Middlewares ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'OdooDash_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'OdooDash_project.wsgi.application'

# --- Base de données ---
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', 'sqlite:///' + str(BASE_DIR / 'db.sqlite3')),
        conn_max_age=600
    )
}

# --- Validation des Mots de Passe ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Internationalisation ---
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# --- Fichiers Statiques ---
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Paramètres d'Authentification ---
LOGIN_REDIRECT_URL = '/app/dashboard/'
LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

