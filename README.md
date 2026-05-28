# Telegram Private Community Bot

Bot Telegram déployable sur Railway avec PostgreSQL.

## Fonctions incluses

- `/start` affiche une seule instance du parcours utilisateur.
- Si l’utilisateur est admin, `/start` ouvre directement le panneau admin.
- Images configurables depuis le panneau admin : publicité, accueil, preuve, premium.
- Publicité avec image + texte + bouton vers le bot.
- Groupes publicité ciblables.
- Auto-publication ON/OFF.
- Candidature utilisateur avec quota et preuve.
- Validation / refus / ban par admin.
- Lien unique vers le groupe principal.
- Suppression automatique des liens dans le groupe principal.
- Comptage médias valides.
- Détection doublons via `file_unique_id` et pHash image.
- Première tentative : kick si aucune publication valide après 4h, kick si quota incomplet après 24h.
- Deuxième tentative : quota complet sous 1h sinon ban définitif.
- Propositions communautaires : nom + lien, validation admin, vote public.
- Cagnotte globale déclarable par admin.

## Variables Railway

```env
BOT_TOKEN=123456:ABCDEF
DATABASE_URL=postgresql://user:password@host:5432/railway
ADMIN_IDS=123456789,987654321
AUTO_MIGRATE=1
```

`PUBLIC_BASE_URL` n’est pas nécessaire dans cette version.

## Déploiement Railway

1. Créer un projet Railway.
2. Ajouter PostgreSQL.
3. Ajouter ce repo ou uploader le projet.
4. Configurer les variables d’environnement.
5. Lancer le service.

## Configuration Telegram

Dans BotFather :

- Désactiver la privacy si le bot doit lire les médias/messages de groupe.
- Ajouter le bot admin dans le groupe principal.
- Ajouter le bot admin dans les groupes publicité.

Dans le groupe principal :

```text
/set_main_group
```

Dans chaque groupe publicité :

```text
/add_pub_group
```

## Images

Depuis `/start` avec un admin :

```text
Panneau admin → Images
```

Puis choisir :

- Image publicité
- Image accueil bot
- Image exemple preuve
- Image campagne premium

Envoyer ensuite une photo au bot. Le bot stocke le `file_id` Telegram en base.

## Publicité

Depuis le panneau admin :

```text
Publicité → Publier maintenant
```

Pour l’auto-publication :

```text
Publicité → Activer auto pub
```

## Cagnotte

Déclarer le montant officiel disponible :

```text
/set_pot 0
/set_pot 120
```

## Proposition membre

Un membre validé peut proposer :

```text
/proposer
```

Le bot demande :

- nom
- lien plateforme

Les admins reçoivent la proposition et peuvent publier le vote.
