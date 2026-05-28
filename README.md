# Telegram Private Community Bot — Railway + PostgreSQL

Bot Telegram prêt à déployer sur Railway avec PostgreSQL.

## Fonctions incluses

- Onboarding utilisateur en privé
- Candidature avec quota déclaré
- Envoi de preuve
- Validation / refus / ban admin
- Lien d'invitation unique vers groupe principal
- Suivi automatique des publications après entrée
- Kick si aucune contribution valide après 4h
- Deuxième chance unique
- Deuxième tentative stricte : quota complet sous 1h, sinon ban
- Anti-liens dans groupe principal
- Anti-doublons simple via hash `file_unique_id` Telegram + hash perceptuel image quand possible
- Panneau admin Telegram
- Groupes publicité, groupe principal
- Publicité manuelle et automatique
- Propositions de campagne : nom + lien plateforme
- Vote de proposition simple
- Cagnotte globale alimentée par paiements premium validés
- Logs admin

## Déploiement Railway

1. Crée un bot avec @BotFather et récupère `BOT_TOKEN`.
2. Crée un projet Railway.
3. Ajoute un service PostgreSQL.
4. Ajoute les variables :
   - `BOT_TOKEN`
   - `DATABASE_URL` est fourni par Railway PostgreSQL
   - `ADMIN_IDS` = IDs Telegram admins séparés par virgule
5. Déploie ce dossier sur Railway.
6. Lance `/migrate` en privé avec le bot depuis un compte admin.
7. Ajoute le bot comme admin dans :
   - groupes publicité
   - groupe principal
8. Dans le groupe principal, envoie `/set_main_group`.
9. Dans chaque groupe publicité, envoie `/add_pub_group`.

## Commandes admin principales

- `/admin` : panneau admin
- `/migrate` : crée/met à jour la base
- `/set_main_group` : définit le groupe actuel comme groupe principal
- `/add_pub_group` : ajoute le groupe actuel comme groupe pub
- `/pub_now` : publier la publicité dans les groupes activés

## Important

Le bot contient une règle minimale de conformité dans les textes. Ne supprime pas les garde-fous : tout contenu problématique doit être supprimé et signalé par les admins.
