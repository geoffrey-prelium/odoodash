# core/templatetags/core_tags.py
from django import template

register = template.Library()

@register.filter(name='get_item') # Enregistre le filtre sous le nom 'get_item'
def get_item(dictionary, key):
    """
    Permet d'accéder à une clé d'un dictionnaire dans un template Django.
    Usage: {{ my_dictionary|get_item:my_key }}
    Retourne None si la clé n'existe pas.
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter(name='dict_from_list')
def dict_from_list(object_list, key_name):
    """
    Transforme une liste d'objets en dictionnaire, en utilisant la valeur
    d'un attribut spécifique de chaque objet comme clé.
    La clé est normalisée (minuscules, sans espaces superflus) pour correspondre
    à la logique de la vue.
    """
    if not object_list:
        return {}
        
    result_dict = {}
    for obj in object_list:
        if hasattr(obj, key_name):
            key_value = getattr(obj, key_name)
            # La ligne cruciale : on normalise la clé ici !
            if isinstance(key_value, str):
                normalized_key = key_value.strip().lower()
                result_dict[normalized_key] = obj
                
    return result_dict

# --- NOUVEAU FILTRE AJOUTÉ ---
@register.filter(name='format_collab_name')
def format_collab_name(value):
    """
    Transforme une chaîne comme "Nom Société, Prénom NOM" en "Prénom NOM".
    Si la chaîne ne contient pas de virgule, elle est retournée telle quelle.
    """
    if isinstance(value, str):
        parts = value.split(',', 1) # Sépare à la première virgule seulement
        if len(parts) > 1:
            return parts[1].strip() # Prend la partie après la virgule et enlève les espaces
    return value # Retourne la valeur originale si pas de virgule ou si ce n'est pas une chaîne
# --- FIN NOUVEAU FILTRE ---

# --- FILTRES POUR LES ALERTES INDICATEURS ---
@register.filter(name='make_alert_key')
def make_alert_key(client, indicator_name):
    """Construit une clé 'client_pk|indicator_name' pour vérifier les alertes."""
    return f"{client.pk}|{indicator_name}"

@register.filter(name='in_set')
def in_set(value, the_set):
    """Vérifie si une valeur est dans un ensemble."""
    return value in the_set
