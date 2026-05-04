# Stodoo - Documentation Utilisateur

## 1. Introduction

**Stodoo** est une solution de middleware conçue pour automatiser la remontée des flux de paiement provenant de **Stripe** et **PayPlug** directement dans votre comptabilité **Odoo** (versions 14, 15 et supérieures).

L'application permet d'éviter la saisie manuelle des transactions en créant automatiquement des lignes de relevé bancaire ("Bank Statement Lines") dans les journaux appropriés, tout en gérant les frais de transaction et les remboursements.

---

## 2. Accès à l'Interface

1.  Ouvrez votre navigateur et accédez à l'URL de l'application (ex: `https://connecteurs-psp-odoo.prelium.fr`).
2.  Connectez-vous avec vos identifiants (E-mail et Mot de passe).
3.  Vous accédez au **Tableau de Bord** principal.

---

## 3. Le Tableau de Bord

Le tableau de bord est divisé en deux sections principales accessibles via les onglets en haut de page :
*   **Onglet Stripe** : Affiche les connexions configurées pour Stripe.
*   **Onglet PayPlug** : Affiche les connexions configurées pour PayPlug.

### 3.1. Liste des Clients
Chaque carte représente une connexion active entre un compte de paiement (Stripe/PayPlug) et une instance Odoo.
*   **Nom du Client** : Identifie l'entreprise ou le dossier.
*   **Statut (Actif/Inactif)** : Indique si la synchronisation automatique est autorisée pour ce client.
*   **Dernière synchro** : Date de la dernière exécution réussie.
*   **Bouton "Lancer Synchro"** : Permet de déclencher une mise à jour manuelle.

---

## 4. Configuration d'une Nouvelle Connexion

Pour ajouter un client, cliquez sur le bouton **"Ajouter Stripe"** ou **"Ajouter PayPlug"**.

### 4.1. Paramètres Généraux
*   **Nom du Client** : Nom lisible pour l'interface.
*   **Activer ce client** : Doit être coché pour que les synchronisations fonctionnent.
*   **Synchronisation Automatique** : Si coché, le client sera traité lors de la passe quotidienne (généralement à 3h du matin).

### 4.2. Configuration Odoo
*   **URL Odoo** : L'adresse de votre instance (ex: `https://ma-societe.odoo.com`).
*   **Base de données** : Le nom technique de la base (souvent le sous-domaine).
*   **Utilisateur** : L'email d'un compte Odoo ayant les droits de création en comptabilité.
*   **Mot de passe / Clé API** : Le mot de passe de l'utilisateur (ou une clé API Odoo recommandée).
*   **Mapping des Journaux** : 
    *   Vous devez définir quel journal Odoo (de type Banque) reçoit les flux.
    *   Pour Stripe, vous pouvez mapper par devise (ex: EUR -> Journal Stripe EUR).
    *   Testez la connexion via le bouton **"Tester la connexion"** pour récupérer automatiquement la liste des journaux disponibles dans votre Odoo.

### 4.3. Configuration du Connecteur (Stripe / PayPlug)
*   **Stripe** : Saisissez votre **Clé Secrète API** (commençant par `sk_live_...`).
*   **PayPlug** : 
    *   Saisissez votre **Token API**.
    *   **Auto-map Order** : Tente de retrouver la référence de commande dans les métadonnées pour remplir la référence de paiement Odoo.
    *   **Auto-map Partner** : Tente de lier automatiquement la transaction à un client Odoo existant via l'adresse email.

---

## 5. Lancer une Synchronisation Manuelle

Si vous ne souhaitez pas attendre la synchronisation automatique :
1.  Cliquez sur **"Lancer Synchro"** sur la carte du client.
2.  Une fenêtre de confirmation s'ouvre.
3.  **Optionnel** : Vous pouvez "Forcer une date de début". Si vous laissez vide, le système récupèrera uniquement les transactions depuis la dernière synchronisation réussie.
4.  Cliquez sur **"Confirmer"**.
5.  Une fois terminée, les lignes apparaîtront dans Odoo dans le menu **Comptabilité > Opérations de banque**.

---

## 6. Comprendre les données dans Odoo

L'application crée des **"Lignes de relevé"** (Statement Lines) :
*   **Paiements Clients** : Montant positif. La référence contient souvent le numéro de commande Stripe/PayPlug.
*   **Frais de Transaction** : Montant négatif. Créé sur une ligne séparée (souvent liée au compte de frais bancaires 6278).
*   **Remboursements** : Montant négatif.
*   **Virements (Payouts)** : Lignes de transfert vers votre compte bancaire réel (souvent liées au compte de virement interne 58).

---

## 7. FAQ & Support

**Pourquoi mes transactions ne remontent pas ?**
*   Vérifiez que le client est marqué comme "Actif".
*   Vérifiez que les clés API n'ont pas expiré.
*   Vérifiez dans Odoo si le journal configuré n'est pas "verrouillé" pour la période concernée.

**Comme sont gérés les doublons ?**
L'application vérifie l'ID unique de chaque transaction Stripe/PayPlug avant de créer une ligne dans Odoo. Si l'ID est déjà présent dans la référence ou la narration d'une ligne existante, elle est ignorée.
