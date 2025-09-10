# Étape 1: Utiliser une image Python officielle et légère
FROM python:3.11-slim

# Étape 2: Définir les variables d'environnement pour Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Étape 3: Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Étape 4: Copier le fichier des dépendances et les installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Étape 5: Copier tout le code de l'application dans le conteneur
COPY . .

# Étape 6: Rendre le script de démarrage exécutable
RUN chmod +x /app/entrypoint.sh

# Étape 7: Exécuter la commande collectstatic de Django
RUN python manage.py collectstatic --noinput

# Étape 8: Exposer le port que Cloud Run écoutera
EXPOSE 8080

# Étape 9: Définir le script de démarrage comme commande par défaut
CMD ["/app/entrypoint.sh"]

