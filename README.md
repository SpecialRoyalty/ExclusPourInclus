
# Bot Telegram Waitlist V4

Version corrigée selon le flow final :

- Captcha avec 3 tentatives
- Choix principal :
  - Créé par moi-même
  - Acheté sur les plateformes
  - Je ne possède aucun contenu exclusif
- Plus de branche "J’ai accès à du contenu privé"
- Si aucun contenu -> question VIP
- Si VIP Oui -> liste d’attente VIP directe
- Si VIP Non -> bloqué
- Premier refus admin -> seconde demande possible
- Deuxième refus admin -> dernière chance VIP
- Si dernière chance VIP Oui -> liste d’attente VIP
- Si dernière chance VIP Non -> bloqué définitivement
- Panel admin avec boutons
- Publicités image + texte
- Broadcast par liste

## Variables Railway

BOT_TOKEN=
DATABASE_URL=
ADMIN_IDS=123456789,987654321
WELCOME_IMAGE_URL=https://...

## Commandes

Utilisateur : /start
Admin : /admin
