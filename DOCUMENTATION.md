# Documentation - Connecteurs PSP Odoo (Stodoo API)

## 📌 Introduction

Cette application est un middleware permettant de synchroniser les paiements provenant de **Stripe** et **PayPlug** vers **Odoo** (v14/v15+). 
Elle est composée d'une API Backend (FastAPI) et d'une Interface Frontend (React).

L'application est conçue pour être déployée sur **Google Cloud Run** en mode serverless.

---

## 🏗 Architecture Technique

### Backend
- **Langage** : Python 3.9+
- **Framework** : FastAPI
- **Base de données** : Google Firestore (NoSQL)
- **Dépendances principales** : `stripe`, `xmlrpc` (Odoo), `firebase-admin`, `cryptography`
- **Sécurité** : Les clés API (Stripe, PayPlug) et mots de passe Odoo sont chiffrés en base (AES Fernet).

### Frontend
- **Langage** : TypeScript / React
- **Build Tool** : Vite
- **Styling** : Tailwind CSS
- **Hébergement** : Servi par le backend FastAPI via le dossier `static`.

### Infrastructure
- **Hébergement** : Google Cloud Run
- **Secrets** : Google Secret Manager (pour la `MASTER_ENCRYPTION_KEY`)
- **Authentification** : Firebase Auth (Frontend) + Middleware Auth custom (Backend)

---

## 👨‍💻 Guide Développeur

### 1. Prérequis
- Python 3.9+
- Node.js 18+
- Google Cloud SDK (`gcloud`) installé et authentifié.

### 2. Installation Locale

#### Backend
```bash
cd backend
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

#### Frontend
```bash
cd frontend
npm install
```

### 3. Configuration Locale (.env)
Pour faire tourner le backend localement, vous devez avoir accès à un projet Google Cloud configuré (Firestore) et définir la clé de chiffrement.

**Backend** :
Vous pouvez définir la variable d'environnement `MASTER_ENCRYPTION_KEY` ou utiliser une clé temporaire dans le code pour le dev.
L'authentification Google (Firestore) se fait via `gcloud auth application-default login`.

### 4. Lancer l'application

#### Mode Développement (Hot Reload)

**Terminal 1 - Backend :**
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Frontend :**
```bash
cd frontend
npm run dev
```
Le frontend sera accessible sur `http://localhost:5173` et tapera sur le backend `http://localhost:8000`.

---

## 🛠 Guide Administrateur

### 1. Gestion des Clients (Configuration)
La configuration des clients est stockée dans la collection **Firestore** `clients`.

Chaque document client contient :
- `client_name` : Nom lisible
- `active` : Booléen
- `odoo_config` : URL, DB, User, Password (chiffré), Journal Mapping (Devise -> ID Journal).
- `stripe_config` : Clé API (chiffrée).
- `payplug_config` : Token (chiffré), ID Journal spécifique.

**Note** : Il est recommandé de passer par l'interface Frontend pour créer/modifier les clients afin de garantir le chiffrement correct des secrets.

### 2. Déploiement en Production

Le déploiement est automatisé via le script PowerShell `deploy_prod.ps1` situé à la racine.

**Ce script effectue les actions suivantes :**
1. Build du Frontend (`npm run build`).
2. Copie des fichiers dist frontend vers `backend/app/static`.
3. Déploiement sur Google Cloud Run via `gcloud run deploy`.

**Commande de déploiement :**
```powershell
./deploy_prod.ps1
```

**Conditions requises :**
- Être authentifié (`gcloud auth login`).
- Avoir les droits sur le projet GCP `applications-480307`.

### 3. Monitoring et Logs
Les logs de l'application sont disponibles dans **Google Cloud Logging**.
- Filtrer par service : `connecteurs-psp-odoo`.
- Les erreurs de synchronisation (Odoo, Stripe, PayPlug) sont loguées avec des détails.

### 4. Scripts Utilitaires
Dans le dossier racine, des scripts Python permettent d'inspecter la base ou débugger :
- `inspect_firestore.py` : Liste les clients et leurs configurations (sans révéler les secrets chiffrés par défaut).
- `inspect_decadrages.py` (si présent) : Exemple de script pour cibler un client spécifique et tester le déchiffrement (nécessite la Master Key).

### 5. Gestion des Secrets
La **Master Key** de chiffrement est stockée dans Google Secret Manager sous le nom `stodoo-master-key`.
Elle est injectée en variable d'environnement lors du déploiement Cloud Run :
`--set-secrets "MASTER_ENCRYPTION_KEY=stodoo-master-key:latest"`

⚠️ **Attention** : Si cette clé est changée, toutes les configurations chiffrées en base deviendront illisibles.

### 6. Automatisation (Cloud Scheduler)
Pour activer la synchronisation automatique quotidienne :

1. Aller sur la console GCP > **Cloud Scheduler**.
2. **Créer un Job** :
   - **Nom** : `sync-all-clients-daily`
   - **Fréquence** : `0 3 * * *` (Tous les jours à 3h00)
   - **Fuseau horaire** : `Europe/Paris`
3. **Configuration de la cible** :
   - **Type** : HTTP
   - **URL** : `https://<VOTRE-URL-CLOUD-RUN>/api/cron/sync_all`
   - **Méthode** : POST
   - **Auth (Header)** : Ajouter le header `X-App-Engine-Cron: true` (Automatique par défaut avec App Engine, mais Cloud Scheduler ajoute aussi ses propres headers sécurisés. Pour plus de sécurité, vous pouvez définir une variable d'environnement `CRON_SECRET` et passer un header `CRON_SECRET: <valeur>` dans le job).
   - **Alternative Auth** : Sélectionner "Add OIDC Token", choisir le Service Account par défaut Compute, et mettre l'URL du service comme audience.

Seuls les clients ayant coché **"Activer la synchronisation automatique"** seront traités.
