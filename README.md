
# Bot Telegram Waitlist Complet

Bot Telegram Python prêt pour Railway avec PostgreSQL.

## Fonctions incluses

- Message d'accueil avec image
- Captcha fruit aléatoire
- Nettoyage des anciens messages du bot au `/start`
- Formulaire utilisable une seule fois
- Blocage des utilisateurs non éligibles
- Retry limité
- Validation/refus par admin
- Listes d'attente par catégorie
- Détection des groupes où le bot est ajouté
- Envoi de publicité dans un groupe choisi
- Base PostgreSQL avec SQLAlchemy
- Déploiement Railway

## Installation locale

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Variables d'environnement

```env
BOT_TOKEN=
DATABASE_URL=
ADMIN_IDS=123456789,987654321
WELCOME_IMAGE_URL=
```

## Commandes

### Utilisateur

```text
/start
```

### Admin

```text
/admin
/groups
/waitlist
/pending
/ad
```

## Déploiement Railway

1. Crée un projet Railway
2. Ajoute PostgreSQL
3. Ajoute les variables d'environnement
4. Déploie le repo
5. Railway lance `python main.py`
