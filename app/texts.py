"""Textes utilisateur V2.

Les formulations ci-dessous reprennent la version validée par le propriétaire du
bot. Elles ne doivent pas être reformulées sans validation explicite.
"""


DEFAULT_AD_TEXT = """🔒 Communauté privée francophone

🎬 Accès gratuit réservé aux auteurs et producteurs de leurs propres contenus.

💎 Accès Premium disponible sans quota de contribution.

🛡 Chaque demande est vérifiée manuellement afin de protéger la communauté."""


DEFAULT_WELCOME_TEXT = """Bienvenue 👋

Ce bot gère l’accès à une communauté privée francophone.

L’accès gratuit est réservé aux auteurs et producteurs capables de partager leurs propres photos ou vidéos.

Un accès Premium sans quota de contribution est également disponible après vérification manuelle du paiement.

Souhaitez-vous continuer ?"""


NOT_INTERESTED = """Aucun problème.

Votre demande n’a pas été commencée. Vous pourrez revenir plus tard avec la commande /start."""


FEEDBACK_PROMPT = """Vous pouvez envoyer un seul message pour nous indiquer pourquoi vous ne souhaitez pas continuer.

Maximum : 500 caractères."""

FEEDBACK_RECEIVED = "✅ Merci. Votre avis a bien été transmis."


def access_choice(price: str) -> str:
    return f"""Choisissez votre parcours :

🎬 Candidature gratuite

Réservée aux auteurs et producteurs de leurs propres contenus.

💎 Accès Premium — {price}

Je ne possède pas de contenu exclu mais je veux rentrer dans le groupe."""


AUTHOR_CONFIRMATION = """Pour demander l’accès gratuit, vous devez être l’auteur ou le producteur des contenus que vous comptez publier.

En continuant, vous confirmez :

• ne pas envoyer de contenu récupéré, échangé, acheté ou republié.Uniquement du contenu exclu

Une fausse déclaration peut entraîner le refus ou le bannissement de votre compte."""


def free_ineligible(price: str) -> str:
    return """L’accès gratuit est réservé aux auteurs et producteurs de leurs propres contenus.

Votre compte n’est pas banni.

Vous pouvez choisir l’accès vu que vous n’avez pas des médias exclu . Vous retrouverez les médias dans le groupe"""


MEDIA_COUNT_PROMPT = """Combien de photos et vidéos personnelles pouvez-vous publier dans le groupe ?

Exemple : 120"""

COUNT_NOT_NUMBER = """Merci d’envoyer uniquement un nombre entier.

Exemple : 120"""

COUNT_TOO_SMALL = "Le nombre doit être supérieur à zéro."


def count_too_large(maximum: int) -> str:
    return f"""Le nombre indiqué est trop élevé.

Merci d’envoyer une estimation réaliste comprise entre 1 et {maximum}."""


def quota_confirmation(quota: int) -> str:
    return f"""Récapitulatif de votre candidature :

📦 Quota déclaré : {quota} médias

⏱ Première publication : sous 3 minutes après votre entrée

🕒 Quota complet : sous 24 heures après votre entrée

Les doublons et les médias déjà enregistrés ne seront pas comptés.

Confirmez-vous ce nombre ?"""


GALLERY_PROMPT = """Étape 1 sur 2 — Capture de galerie

Envoyez maintenant une seule capture d’écran de votre galerie montrant les contenus correspondant à votre déclaration."""

GALLERY_RECEIVED = """✅ Capture de galerie reçue.

Passez maintenant à l’étape 2 sur 2."""

GALLERY_INVALID = """Cette étape attend une seule capture d’écran de votre galerie, envoyée comme photo.

Les vidéos, GIF, albums, documents et autres fichiers ne sont pas acceptés ici."""


SAMPLE_PROMPT = """Étape 2 sur 2 — Média de vérification

Envoyez maintenant un seul média réel visible dans la galerie transmise.

Formats acceptés :

• une photo ;

• une vidéo.

Les GIF, animations, documents, albums, liens, stickers, notes vidéo et messages vocaux sont refusés.

Un seul média est demandé."""

SAMPLE_RECEIVED = """✅ Média de vérification reçu.

Votre capture de galerie et votre média vont être transmis aux administrateurs pour une vérification manuelle."""

SAMPLE_INVALID = """Format refusé.

Envoyez exactement une photo ou une vidéo directement dans Telegram.

Les GIF, documents, albums et autres formats ne sont pas acceptés."""

SAMPLE_ALREADY_RECEIVED = """Un média de vérification a déjà été reçu.

Un seul média est autorisé pour cette candidature."""


def application_complete(quota: int) -> str:
    return f"""✅ Votre candidature est complète et a été envoyée aux administrateurs.

📦 Quota déclaré : {quota} médias

Vous recevrez la décision directement dans cette conversation.

Il est inutile de renvoyer votre capture ou votre média."""


APPLICATION_PENDING = """Votre candidature est déjà en cours de vérification.

Merci d’attendre la décision des administrateurs.

Vous serez automatiquement averti dès qu’une décision sera prise."""


def application_rejected(reason: str, remaining_attempts: int) -> str:
    return f"""❌ Votre candidature gratuite a été refusée.

Motif : {reason}

Tentatives gratuites restantes : {remaining_attempts}

Si vous n’avez pas de média exclusif vous pouvez passer a la caisse"""


def attempts_exhausted(price: str) -> str:
    return """Vous avez utilisé vos deux tentatives de candidature gratuite.

Vous ne pouvez plus recommencer le parcours gratuit.

Vous pouvez toujours demander un accès Premium , vous n’avez pas de média exclu"""


ADMIN_BANNED = """Votre accès a été bloqué par un administrateur.

Vous ne pouvez plus commencer une nouvelle candidature."""


def rules_text(quota: int) -> str:
    return f"""✅ Votre candidature a été prévalidée.

Avant de recevoir votre lien, vous devez accepter les quatre règles suivantes :

1. Publier un premier média valide sous 3 minutes après votre entrée dans le groupe.

2. Publier la totalité des {quota} médias déclarés sous 24 heures.

3. Ne jamais partager votre lien d’invitation. Il est personnel et lié à votre compte Telegram.

4. Ne publier aucun lien externe, publicité ou mention destinée à rediriger les membres.

Le non-respect des délais entraîne le retrait automatique de l’accès."""


def free_invite_ready(quota: int) -> str:
    return f"""🎉 Votre accès est prêt.

Ce lien est :

• personnel ;

• lié à votre compte Telegram ;

• valable 24 heures ;

• révoqué automatiquement après votre admission.

Après votre entrée, vous aurez 3 minutes pour publier un premier média valide et 24 heures pour atteindre votre quota de {quota} médias."""


JOIN_APPROVED = """✅ Votre compte Telegram a été vérifié.

Votre demande d’adhésion est approuvée."""


WRONG_INVITE = """Cette invitation ne correspond pas à votre compte Telegram.

Votre demande d’adhésion a été refusée."""


INVITE_EXPIRED = """Ce lien a expiré ou a déjà été utilisé.

Utilisez le bouton ci-dessous pour demander un nouveau lien aux administrateurs."""

NEW_LINK_REQUESTED = "✅ Votre demande de nouveau lien a été transmise aux administrateurs."

NEW_LINK_REJECTED = "Votre demande de nouveau lien a été refusée par un administrateur."


def free_join_private(quota: int, joined_at: str, first_deadline: str, quota_deadline: str) -> str:
    return f"""✅ Vous venez d’entrer dans le groupe principal.

Le compteur a commencé à {joined_at}.

📦 Objectif : {quota} médias

⏱ Premier média avant : {first_deadline}

🕒 Quota complet avant : {quota_deadline}

Publiez vos photos ou vidéos directement dans le groupe principal.

Le média envoyé pendant votre candidature ne compte pas dans ce quota."""


def free_join_public(display_name: str, quota: int) -> str:
    return f"""Bienvenue {display_name} 👋

📦 Quota : {quota} médias

⏱ Première publication sous 3 minutes

🕒 Quota complet sous 24 heures"""


def first_deadline_warning(deadline: str) -> str:
    return f"""⏳ Il vous reste environ une minute pour publier votre premier média valide.

Sans publication avant {deadline}, votre accès sera retiré automatiquement."""


def first_media_accepted(valid: int, quota: int, deadline: str) -> str:
    return f"""✅ Première contribution détectée à temps.

Progression : {valid}/{quota}

Date limite du quota : {deadline}"""


def progress_update(valid: int, quota: int, deadline: str) -> str:
    return f"""📊 Progression : {valid}/{quota} médias

Date limite : {deadline}"""


def duplicate_media(valid: int, quota: int) -> str:
    return f"""⚠️ Ce média a déjà été enregistré et ne compte pas dans votre quota.

Progression : {valid}/{quota}"""


FORMAT_NOT_COUNTED = """Ce format ne compte pas dans votre quota.

Publiez une photo ou une vidéo directement dans Telegram.

Les GIF, stickers, documents génériques, notes vidéo et messages vocaux ne sont pas comptabilisés."""


NO_FIRST_MEDIA = """❌ Aucun média valide n’a été détecté dans le délai de 3 minutes.

Votre accès au groupe a été retiré et votre compte a été placé sur la liste de blocage.

Si vous pensez qu’il s’agit d’une erreur, vous pouvez demander un réexamen."""


def quota_warning(valid: int, quota: int, deadline: str) -> str:
    return f"""⏳ Il vous reste environ une heure pour compléter votre quota.

Progression : {valid}/{quota}

Date limite : {deadline}"""


def quota_complete(valid: int, quota: int) -> str:
    return f"""✅ Quota complété : {valid}/{quota} médias.

Votre accès est maintenant validé définitivement.

Merci pour votre contribution."""


def quota_failed(valid: int, quota: int) -> str:
    return f"""❌ Votre quota n’a pas été complété dans le délai de 24 heures.

Progression finale : {valid}/{quota}

Votre accès a été retiré et votre compte a été placé sur la liste de blocage.

Si vous pensez qu’il s’agit d’une erreur, vous pouvez demander un réexamen."""


LINK_WARNING = """⚠️ Votre message a été supprimé.

Les liens externes, publicités et redirections par @mention ne sont pas autorisés dans le groupe principal.

Cet avertissement est envoyé au maximum une fois par heure."""


APPEAL_PROMPT = """Expliquez brièvement pourquoi vous demandez un réexamen.

Envoyez un seul message de 500 caractères maximum.

Votre demande sera transmise aux administrateurs."""

APPEAL_SENT = """✅ Votre demande de réexamen a été envoyée aux administrateurs.

Une seule demande de réexamen est autorisée pour cet incident.

Vous recevrez leur décision ici."""


def appeal_accepted(quota: int) -> str:
    return f"""✅ Votre demande de réexamen a été acceptée.

Votre accès est rétabli avec le même quota de {quota} médias.

Les délais de 3 minutes et 24 heures recommenceront lors de votre prochaine entrée.

Votre nouveau lien personnel est valable 24 heures."""


def appeal_rejected(reason: str) -> str:
    return f"""❌ Votre demande de réexamen a été refusée.

Motif : {reason}

Votre compte reste bloqué."""


def premium_presentation(price: str, paypal: str, usdt: str) -> str:
    return f"""💎 Accès Premium

Prix : {price}

L’accès Premium permet de rejoindre le groupe sans quota de contribution.

Moyens de paiement disponibles :

PayPal : {paypal}

USDT TRC20 : {usdt}

Les paiements sont vérifiés manuellement par un administrateur."""


NO_PAYMENT_METHOD = """Aucun moyen de paiement n’est configuré pour le moment.

Merci de revenir plus tard ou de contacter un administrateur."""

PAYMENT_PROOF_PROMPT = """Envoyez maintenant une seule preuve de paiement.

Formats acceptés :

• une photo ;

• une image envoyée comme document ;

• un document PDF.

Vérifiez que le montant, la date et la référence du paiement sont lisibles.

Vous pouvez masquer les informations personnelles qui ne sont pas nécessaires à la vérification."""

PAYMENT_PROOF_INVALID = """Format refusé.

Envoyez une photo, une image ou un document PDF correspondant à votre preuve de paiement."""


def payment_proof_received(price: str) -> str:
    return f"""✅ Votre preuve de paiement a été transmise aux administrateurs.

Montant attendu : {price}

Vous recevrez leur décision ici après vérification manuelle.

Il est inutile de renvoyer plusieurs fois la même preuve."""


PAYMENT_PENDING = """Votre preuve de paiement est déjà en cours de vérification.

Merci d’attendre la décision des administrateurs."""


def payment_rejected(reason: str) -> str:
    return f"""❌ Votre preuve de paiement a été refusée.

Motif : {reason}

Vous pouvez envoyer une nouvelle preuve si votre paiement est régulier."""


PAYMENT_ACCEPTED = """✅ Votre paiement a été validé.

Avant de rejoindre le groupe, vous confirmez que :

• votre lien est strictement personnel ;

• les publicités et liens externes sont interdits ;

• vous ne publierez que des contenus dont vous détenez les droits.

Votre accès Premium ne comporte aucun quota de contribution."""


PREMIUM_INVITE_READY = """🎉 Votre accès Premium est prêt.

Votre lien est :

• personnel ;

• lié à votre compte Telegram ;

• valable 48 heures ;

• révoqué automatiquement après votre admission.

Vous êtes exempté du quota de contribution."""


PREMIUM_JOIN_PRIVATE = """✅ Bienvenue dans le groupe principal.

Votre accès Premium est actif.

Vous êtes exempté du quota de contribution.

Les règles relatives aux liens, à la publicité et aux droits sur les contenus restent applicables."""


def premium_join_public(display_name: str) -> str:
    return f"""Bienvenue {display_name} 👋

✅ Accès Premium validé."""


PREMIUM_LEFT = """Vous avez quitté le groupe principal.

Votre paiement reste enregistré et votre compte n’est pas blacklisté.

Si vous souhaitez revenir, vous pouvez demander un nouveau lien aux administrateurs."""

ALREADY_MEMBER = """✅ Votre accès est déjà actif.

Vous ne pouvez pas recommencer une nouvelle candidature."""


def resume_flow(step: str) -> str:
    return f"""Votre parcours précédent a été retrouvé.

Vous allez reprendre à l’étape suivante :

{step}"""


TEMPORARY_ERROR = """Une erreur temporaire est survenue.

Votre progression a été conservée.

Merci de réessayer dans quelques instants."""

EXPIRED_ACTION = """Ce bouton a expiré ou cette demande a déjà été traitée.

Utilisez /start pour afficher votre situation actuelle."""

BLOCKED_ACCOUNT = """Votre accès est actuellement bloqué.

Vous ne pouvez pas commencer une nouvelle candidature."""
