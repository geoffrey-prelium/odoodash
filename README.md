# OdooDash 🚀

OdooDash est une application web développée avec le framework Django. Son objectif est de fournir un tableau de bord centralisé qui agrège et affiche des indicateurs de performance clés (KPIs) extraits en temps réel des bases de données Odoo des clients d'un cabinet comptable.

---

## ✨ Fonctionnalités

* **Tableau de Bord Centralisé** : Vue d'ensemble de tous les clients avec des indicateurs clés.
* **Extraction de Données via API** : Se connecte aux instances Odoo via XML-RPC pour récupérer les données.
* **Filtres Dynamiques** : Permet de filtrer les clients par collaborateur assigné, catégorie d'indicateur ou date de clôture.
* **Gestion des Permissions** : Rôles intégrés (Collaborateur, Admin, Super Admin) pour restreindre l'accès aux données.
* **Segmentation des Clients** : Possibilité de marquer des clients comme "Prelium" et de filtrer la vue en conséquence.
* **Sécurité** : Chiffrement des clés API Odoo avant leur stockage en base de données.
* **Prêt pour le Déploiement** : Configuré pour un déploiement simple sur Google Cloud Run.

---

## 🛠️ Stack Technique

* **Backend** : Django, Python
* **Frontend** : HTML, Tailwind CSS
* **Base de Données** : SQLite (développement), PostgreSQL (production)
* **Déploiement** : Google Cloud Run, Gunicorn
* **Librairies Principales** : `dj-database-url`, `python-dotenv`, `cryptography`

---

## 🚀 Installation et Lancement

Suivez ces étapes pour mettre en place un environnement de développement local.

### Prérequis

* Python 3.10+
* Git

### Étapes

1.  **Cloner le dépôt**
    ```bash
    git clone [https://github.com/geoffrey-prelium/odoodash.git](https://github.com/geoffrey-prelium/odoodash.git)
    cd oodash
    ```

2.  **Créer et activer un environnement virtuel**
    ```bash
    # Pour Linux / macOS
    python3 -m venv venv
    source venv/bin/activate

    # Pour Windows
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Installer les dépendances**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurer les variables d'environnement**
    Copiez le fichier d'exemple et remplissez-le avec vos propres clés.
    ```bash
    cp env.example .env
    ```
    Modifiez ensuite le fichier `.env` :
    ```env
    SECRET_KEY=VOTRE_CLE_SECRETE_DJANGO
    FERNET_KEY=VOTRE_CLE_DE_CHIFFREMENT
    DATABASE_URL= # Laissez vide pour utiliser SQLite en local
    ```

5.  **Appliquer les migrations de la base de données**
    ```bash
    python manage.py migrate
    ```

6.  **Créer un super utilisateur**
    Pour accéder à l'interface d'administration (`/admin`), créez un compte administrateur.
    ```bash
    python manage.py createsuperuser
    ```

---

## ⚙️ Utilisation

### Lancer le serveur de développement

Une fois l'installation terminée, lancez le serveur pour voir l'application.
```bash
python manage.py runserver
```
L'application sera accessible à l'adresse `http://127.0.0.1:8000/`.

### Lancer le script d'extraction

Pour peupler le dashboard avec les données des instances Odoo, exécutez la commande de management suivante. Assurez-vous d'avoir configuré les clients dans l'interface d'administration au préalable.
```bash
python manage.py fetch_indicators
```

---

## ☁️ Déploiement

Ce projet est configuré pour être déployé sur **Google Cloud Run**.

La commande pour déployer les changements est :
```bash
gcloud run deploy odoodash --source .
```
Les secrets (variables d'environnement) doivent être configurés directement dans Cloud Run, de préférence en utilisant Secret Manager ou l'option `--set-env-vars`.

---

## 📄 Licence

Ce projet est privé et tous les droits sont réservés.