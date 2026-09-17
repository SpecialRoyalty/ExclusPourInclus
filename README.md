# ExclusPourInclus V2

Bot Telegram en français servant de sas d’entrée, de paiement manuel et de
modération pour une communauté privée.

Les formulations du parcours utilisateur sont centralisées dans
`app/texts.py`. Elles reprennent les tournures validées et peuvent être relues
ou modifiées à un seul endroit.

## Parcours inclus

- Accès gratuit réservé aux auteurs/producteurs.
- Déclaration d’un quota compris entre 1 et 100 médias.
- Une capture de galerie, puis exactement une photo ou vidéo de vérification.
- Décision manuelle d’un administrateur : prévalidation, refus motivé ou ban.
- Lien personnel de 24 heures avec demande d’adhésion Telegram.
- Premier média valide sous 3 minutes et quota complet sous 24 heures.
- Deux candidatures gratuites au maximum.
- Réexamen par motif texte, sans renvoi massif de médias en privé.
- Accès Premium avec preuve de paiement vérifiée manuellement, lien de 48
  heures et aucun quota.
- Un membre Premium qui quitte le groupe n’est pas blacklisté et peut demander
  un nouveau lien.

## Administration

Le panneau `/admin` permet notamment de :

- configurer le texte et la photo/vidéo de la publicité ;
- configurer le texte et la photo/vidéo de l’accueil ;
- configurer l’image d’exemple de la galerie ;
- détecter les groupes et choisir le groupe principal ou les groupes
  publicitaires ;
- modifier le prix Premium, PayPal et l’adresse USDT ;
- valider les candidatures, paiements et réexamens ;
- publier une publicité immédiatement ou automatiquement ;
- consulter le tunnel, les abandons et les conversions ;
- envoyer un broadcast par catégorie ;
- vérifier PostgreSQL, Telegram, les droits du bot, les réglages et le
  planificateur depuis le bouton **Santé du bot**.

## Sécurité et consommation Railway

- Aucun GPU et aucune bibliothèque d’image.
- Aucun téléchargement de média : seuls les identifiants Telegram sont
  conservés.
- Détection des doublons exacts avec `file_unique_id`.
- Un seul processus asynchrone, un pool PostgreSQL de 1 à 3 connexions et un
  seul planificateur toutes les 30 secondes.
- Les étapes utilisateur et administrateur sont conservées dans PostgreSQL et
  survivent aux redémarrages.
- Les invitations utilisent les demandes d’adhésion et sont liées à
  l’identifiant Telegram attendu. Le mauvais compte est refusé, blacklisté et
  banni des groupes publicitaires configurés.
- Les migrations sont additives : le démarrage n’exécute aucun `DROP TABLE` ou
  `DROP COLUMN`.
- Les preuves refusées anciennes, les journaux et les invitations terminées
  font l’objet d’un nettoyage périodique.

Les paiements restent entièrement manuels : le bot ne contacte ni PayPal, ni
une blockchain. La cagnotte affichée est un compteur statistique, pas un solde
financier.

## Variables d’environnement

Copier `.env.example` en `.env` pour un lancement local, ou créer ces variables
dans Railway :

```env
BOT_TOKEN=123456789:token_botfather
DATABASE_URL=postgresql://user:password@host:5432/railway
ADMIN_IDS=123456789,987654321
AUTO_MIGRATE=1
DB_POOL_MIN=1
DB_POOL_MAX=3
SCHEDULER_INTERVAL_SECONDS=30
```

`ADMIN_IDS` accepte plusieurs identifiants séparés par des virgules. Le bot
refuse de démarrer si le token, la base ou la liste des administrateurs manque.

## Déploiement sur Railway

1. Créer un nouveau projet Railway et lui ajouter PostgreSQL.
2. Déployer le contenu de ce dossier.
3. Ajouter `BOT_TOKEN`, `DATABASE_URL` et `ADMIN_IDS` dans les variables du
   service.
4. Vérifier que Railway utilise la commande `python -m app.main`.
5. Dans BotFather, désactiver le mode confidentialité du bot avec
   `/setprivacy`. Sans cela, Telegram ne lui transmet pas tous les médias du
   groupe.
6. Ajouter le bot comme administrateur dans le groupe principal avec les droits
   d’inviter, supprimer les messages et bannir les membres. Le groupe principal
   doit rester privé afin que l’entrée passe bien par une demande d’adhésion.
7. Ajouter le bot comme administrateur dans les groupes publicitaires avec le
   droit de publier et de supprimer ses anciennes publicités.
8. Envoyer `/admin` en privé, ouvrir **Groupes**, puis attribuer les rôles.
9. Configurer les médias, le texte d’accueil, la publicité et les moyens de
   paiement.
10. Ouvrir **Santé du bot** et corriger chaque contrôle marqué en erreur avant
    de diffuser le lien.

Avant de connecter cette V2 à une base issue d’une ancienne version, effectuer
une sauvegarde PostgreSQL. La migration fournie préserve les anciennes tables
et colonnes.

## Lancement local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q app
```

Le test final avec un vrai bot Telegram et une vraie base PostgreSQL reste
indispensable avant la mise en production, notamment pour les permissions de
groupe et les demandes d’adhésion.
