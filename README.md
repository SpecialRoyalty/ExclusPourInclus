# Telegram Private Community Bot — version modifiée

Bot Telegram déployable sur Railway avec PostgreSQL.

## Fonctionnalités incluses

- Panneau admin détecté automatiquement via `ADMIN_IDS`.
- Groupes détectés automatiquement quand le bot est ajouté ou reçoit un message.
- Choix depuis le panel admin : groupe `pub`, groupe `main`, ou groupe seulement détecté.
- Publicité avec image configurable + texte configurable + bouton vers le bot.
- Auto-publicité configurable en minutes avec suppression de l’ancienne publicité avant la nouvelle.
- Images configurables : publicité, accueil, exemple preuve.
- Parcours utilisateur : langue, profil, déclaration du nombre total de médias, rappel exclusivité, preuve unique.
- Langue française uniquement : autres langues refusées + blacklist + ban uniquement des groupes `pub`.
- Bouton “Pas intéressé” avec possibilité d’envoyer un feedback unique.
- Limite globale : 2 formulaires gratuits maximum.
- Cas “pas de contenu” : accès premium avec preuve de paiement ou parcours VIP.
- Accès premium : PayPal/USDT/prix configurables, preuve de paiement envoyée aux admins, motif obligatoire en cas de refus.
- Parcours VIP : demande “chez qui le VIP a été payé”, nombre de médias, puis contact admin pour extraction.
- Candidature contenu :
  - Acheteur : filtre “acheteur régulier OF/MYM ?”, puis total médias.
  - Amateur/collectionneur : origine des médias, puis total médias.
- Validation admin des candidatures : valider, refuser, bannir. La carte admin disparaît après décision.
- Après pré-validation : l’utilisateur doit envoyer au bot 50% du volume déclaré, transmis aux admins pour validation de cohérence.
- Après validation des 50% : règles obligatoires puis lien unique vers le groupe principal, valable 24h.
- Accès premium : lien unique vers le groupe principal, valable 48h, sans quota de contribution.
- Dans le groupe principal : message de bienvenue public + message privé à l’entrée.
- Premium validé : exempté du quota de contribution.
- Contribution gratuite : si aucun média valide après 10 minutes dans le groupe principal, ban définitif.
- Si quota total non complété après 24h, ban définitif.
- Si un membre quitte volontairement le groupe principal, son accès est perdu.
- Anti-liens : suppression des liens/URL/@ externes dans le groupe principal.
- Comptage des médias valides.
- Anti-doublons via `file_unique_id` Telegram + perceptual hash pour images.
- Relance premium unique après 5h si un formulaire est abandonné.
- Logs récents et vérification admin.

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
7. Configurer les groupes, images, paiements et fréquence pub dans le panel.

## Broadcast VIP coupe-file

Depuis le panel admin :

`📥 Modération` → `🎟 Broadcast VIP coupe-file`

Le bot cible les utilisateurs non bannis ayant demandé un accès VIP coupe-file et dont le statut est :

- `vip_provider_waiting`
- `vip_media_count_waiting`
- `vip_waiting`
- `vip_rejected`

L'admin envoie un message texte, confirme l'envoi, puis le bot diffuse en privé et affiche le nombre d'envois réussis/échoués.
