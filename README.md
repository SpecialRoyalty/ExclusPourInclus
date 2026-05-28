# Telegram Private Community Bot — version actuelle

Bot Telegram déployable sur Railway avec PostgreSQL.

## Fonctionnalités incluses

- Panneau admin détecté automatiquement via `ADMIN_IDS`.
- Une seule instance `/start` par utilisateur : l’ancien écran start est remplacé.
- Groupes détectés automatiquement quand le bot est ajouté ou reçoit un message.
- Choix depuis le panel admin : groupe publicité ou groupe principal.
- Publicité avec image configurable + texte configurable + bouton vers le bot.
- Images configurables : publicité, accueil, exemple preuve.
- Parcours utilisateur simplifié : langue, profil, déclaration du nombre total de médias, rappel exclusivité, preuve.
- Langue française uniquement pour le moment : autres langues refusées + ban des groupes configurés.
- Cas “pas de contenu” : accès premium avec preuve de paiement ou “je possède un VIP”.
- Validation admin des candidatures : valider, refuser, bannir. La carte admin disparaît après décision.
- Lien unique vers le groupe principal après validation.
- Dans le groupe principal : suppression des liens/URL/@ externes.
- Comptage des médias valides.
- Anti-doublons via `file_unique_id` Telegram + perceptual hash pour images.
- Vérification silencieuse :
  - si aucun média valide après 30 min : ban définitif + blacklist ;
  - si quota total non complété après 24h : ban + blacklist ;
  - pas de deuxième tentative pour le moment.

## Variables Railway

```env
BOT_TOKEN=123456:ABCDEF
DATABASE_URL=postgresql://user:password@host:5432/railway
ADMIN_IDS=123456789,987654321
AUTO_MIGRATE=1
```

Le fichier `runtime.txt` force Python 3.12 pour éviter les problèmes de build avec `asyncpg`.

## Déploiement Railway

1. Créer un projet Railway.
2. Ajouter PostgreSQL.
3. Déployer ce dossier.
4. Configurer les variables d’environnement.
5. Vérifier que le bot est admin dans les groupes publicité et le groupe principal.
6. Faire `/start` en privé avec un compte admin.
7. Configurer les groupes et images dans le panel.
