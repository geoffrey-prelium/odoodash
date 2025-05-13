# core/utils.py
import xmlrpc.client
import logging
import base64 # Nécessaire pour encrypt_value et decrypt_value
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken # Nécessaire pour encrypt/decrypt

# Importer ConfigurationCabinet pour get_odoo_cabinet_collaborators
# et potentiellement pour connect_odoo si on veut y lire la config
from .models import ConfigurationCabinet

logger = logging.getLogger(__name__)

# Fonction de connexion Odoo (peut être utilisée par d'autres modules/commandes)
def connect_odoo(url, db, username, password):
    """Tente de se connecter à Odoo et retourne l'UID et les proxies."""
    try:
        common_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        version = common_proxy.version()
        # logger.info(f"Connexion Odoo (utils): {url} (Version: {version.get('server_version')})")
        uid = common_proxy.authenticate(db, username, password, {})
        if not uid:
            logger.error(f"Échec Auth Odoo (utils): {username} sur {db}@{url}")
            return None, None, None
        object_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        # logger.info(f"Auth Odoo OK (utils) pour {username} (UID: {uid})")
        return uid, common_proxy, object_proxy
    except xmlrpc.client.Fault as e:
        logger.error(f"Erreur XML-RPC Odoo (utils) ({url}): {e.faultCode} - {e.faultString}")
        return None, None, None
    except Exception as e:
        logger.error(f"Erreur connexion Odoo (utils) inattendue ({url}): {e}", exc_info=False)
        return None, None, None

# --- FONCTION ENCRYPT_VALUE (S'assurer qu'elle est bien ici) ---
def encrypt_value(plain_text_value):
    """Chiffre une valeur en utilisant la clé Fernet des settings."""
    if not settings.FERNET_KEY:
        logger.error("FERNET_KEY non configurée pour le chiffrement.")
        raise ValueError("Clé de chiffrement (FERNET_KEY) non configurée.")
    if not plain_text_value: # Si la valeur est vide, on retourne une chaîne vide
        return ""
    try:
        f = Fernet(settings.FERNET_KEY.encode())
        encrypted_value = f.encrypt(plain_text_value.encode('utf-8'))
        # Retourner des bytes encodés en base64 (plus sûr pour stockage TEXT)
        return base64.urlsafe_b64encode(encrypted_value).decode('utf-8')
    except Exception as e:
        logger.error(f"Erreur lors du chiffrement: {e}", exc_info=True)
        # Il est important de ne pas laisser passer une erreur de chiffrement silencieusement
        raise ValueError(f"Erreur de chiffrement: {e}")
# --- FIN FONCTION ENCRYPT_VALUE ---

def decrypt_value(encrypted_b64_value):
    """Déchiffre une valeur (encodée en base64) en utilisant la clé Fernet."""
    if not settings.FERNET_KEY:
        logger.error("FERNET_KEY non configurée pour le déchiffrement.")
        return None # Ou lever une exception
    if not encrypted_b64_value: # Si la valeur chiffrée est vide
        return ""
    try:
        f = Fernet(settings.FERNET_KEY.encode())
        encrypted_value_bytes = base64.urlsafe_b64decode(encrypted_b64_value.encode('utf-8'))
        decrypted_value = f.decrypt(encrypted_value_bytes)
        return decrypted_value.decode('utf-8')
    except (InvalidToken, TypeError, ValueError, base64.binascii.Error) as e: # Ajout de b64.binascii.Error
        logger.warning(f"Impossible de déchiffrer la valeur (utils): {e}. Valeur reçue: '{encrypted_b64_value[:20]}...'")
        return None # Retourne None en cas d'échec de déchiffrement
    except Exception as e:
        logger.error(f"Erreur inattendue lors du déchiffrement (utils): {e}", exc_info=True)
        return None


def get_odoo_cabinet_collaborators():
    """
    Récupère la liste des partenaires considérés comme collaborateurs
    depuis l'instance Odoo Cabinet configurée.
    Retourne une liste de tuples [(id_str, name_str), ...] ou une liste vide.
    """
    collaborators_choices = []
    try:
        config = ConfigurationCabinet.objects.first()
        if not config:
            logger.error("Configuration Odoo Cabinet non trouvée (get_odoo_cabinet_collaborators).")
            return collaborators_choices

        api_key = decrypt_value(config.firm_odoo_encrypted_api_key)
        if not api_key: # Si decrypt_value retourne None ou ""
            logger.error("Impossible de déchiffrer la clé API du cabinet (get_odoo_cabinet_collaborators).")
            return collaborators_choices

        uid, _, object_proxy = connect_odoo(
            config.firm_odoo_url,
            config.firm_odoo_db,
            config.firm_odoo_api_user,
            api_key
        )

        if uid and object_proxy:
            domain = [("partner_share", "=", False)] # Filtre pour les collaborateurs
            fields = ['name'] # 'id' est inclus par défaut
            order = 'name'

            collaborator_data = object_proxy.execute_kw(
                config.firm_odoo_db, uid, api_key,
                'res.partner', 'search_read',
                [domain],
                {'fields': fields, 'order': order, 'limit': 200} # Ajout d'une limite par sécurité
            )

            collaborators_choices = [(str(c['id']), c['name']) for c in collaborator_data]
            # logger.info(f"{len(collaborators_choices)} collaborateurs potentiels récupérés depuis Odoo Cabinet.")
        else:
            logger.warning("Connexion à Odoo Cabinet échouée, impossible de récupérer la liste des collaborateurs.")

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des collaborateurs Odoo Cabinet: {e}", exc_info=True)

    return collaborators_choices
