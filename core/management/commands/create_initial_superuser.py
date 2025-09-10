import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    """
    Crée un super-utilisateur de manière non-interactive à partir des variables d'environnement.
    Idéal pour les déploiements automatisés (comme sur Cloud Run).
    """
    help = 'Creates a superuser from environment variables if one does not exist.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

        if not all([username, email, password]):
            self.stdout.write(self.style.ERROR('Erreur : Les variables d\'environnement DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, et DJANGO_SUPERUSER_PASSWORD doivent être définies.'))
            return

        if not User.objects.filter(username=username).exists():
            self.stdout.write(self.style.SUCCESS(f"Création du super-utilisateur '{username}'..."))
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS("Super-utilisateur créé avec succès !"))
        else:
            self.stdout.write(self.style.WARNING(f"Le super-utilisateur '{username}' existe déjà. Aucune action n'est nécessaire."))
