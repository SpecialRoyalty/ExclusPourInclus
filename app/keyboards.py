from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def url_kb(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]]
    )


def start_kb() -> InlineKeyboardMarkup:
    return kb([
        [("✅ Continuer", "start:continue")],
        [("❌ Pas intéressé", "start:not_interested")],
    ])


def not_interested_kb() -> InlineKeyboardMarkup:
    return kb([
        [("💬 Laisser un avis", "feedback:start")],
        [("⬅️ Retour", "start:home")],
    ])


def access_choice_kb(price: str) -> InlineKeyboardMarkup:
    return kb([
        [("🎬 Je suis auteur/producteur", "free:start")],
        [(f"💎 Accès Premium — {price}", "premium:start")],
        [("⬅️ Retour", "start:home")],
    ])


def author_confirmation_kb() -> InlineKeyboardMarkup:
    return kb([
        [("✅ Je confirme", "free:author_confirm")],
        [("❌ Je ne remplis pas ces conditions", "free:ineligible")],
        [("⬅️ Retour", "start:continue")],
    ])


def ineligible_kb(price: str) -> InlineKeyboardMarkup:
    return kb([
        [(f"💎 Voir l’accès Premium — {price}", "premium:start")],
        [("⬅️ Retour", "start:continue")],
    ])


def quota_confirmation_kb(quota: int) -> InlineKeyboardMarkup:
    return kb([
        [(f"✅ Confirmer {quota}", "free:quota_confirm")],
        [("✏️ Modifier", "free:quota_edit")],
        [("❌ Annuler", "start:continue")],
    ])


def rejected_application_kb(price: str, can_retry: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if can_retry:
        rows.append([("🔄 Recommencer une candidature", "free:start")])
    rows.append([(f"💎 Accès Premium — {price}", "premium:start")])
    return kb(rows)


def rules_kb() -> InlineKeyboardMarkup:
    return kb([[('✅ J’accepte les 4 règles', 'free:rules_accept')]])


def appeal_kb() -> InlineKeyboardMarkup:
    return kb([[('🧾 Demander un réexamen', 'appeal:start')]])


def request_new_link_kb() -> InlineKeyboardMarkup:
    return kb([[('🆘 Demander un nouveau lien', 'invite:request_new')]])


def resume_kb() -> InlineKeyboardMarkup:
    return kb([[('▶️ Reprendre', 'flow:resume')]])


def premium_info_kb(enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if enabled:
        rows.append([('📸 Envoyer ma preuve de paiement', 'premium:proof')])
    rows.append([('⬅️ Retour', 'start:continue')])
    return kb(rows)


def payment_rejected_kb() -> InlineKeyboardMarkup:
    return kb([
        [('📸 Envoyer une nouvelle preuve', 'premium:proof')],
        [('⬅️ Retour', 'premium:start')],
    ])


def payment_accept_kb() -> InlineKeyboardMarkup:
    return kb([[('✅ J’accepte et je récupère mon lien', 'premium:rules_accept')]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    return kb([
        [('📢 Publicité', 'admin:ad'), ('👋 Message d’accueil', 'admin:welcome')],
        [('🖼 Exemple galerie', 'admin:gallery'), ('👥 Groupes', 'admin:groups')],
        [('💳 Paiements', 'admin:payments'), ('📥 Modération', 'admin:moderation')],
        [('📊 Statistiques', 'admin:stats'), ('📣 Broadcast', 'admin:broadcast')],
        [('🩺 Santé du bot', 'admin:health'), ('⚙️ Réglages', 'admin:settings')],
    ])


def back_admin_kb() -> InlineKeyboardMarkup:
    return kb([[('⬅️ Retour au panneau', 'admin:home')]])


def content_menu_kb(kind: str, *, allow_video: bool, auto_enabled: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if kind != 'gallery':
        rows.append([('📝 Modifier le texte', f'content:text:{kind}')])
    rows.append([('🖼 Ajouter une photo', f'content:photo:{kind}')])
    if allow_video:
        rows.append([('🎬 Ajouter une vidéo', f'content:video:{kind}')])
    rows.extend([
        [('🗑 Supprimer le média', f'content:delete:{kind}')],
        [('👁 Prévisualiser', f'content:preview:{kind}')],
    ])
    if kind == 'ad':
        rows.extend([
            [('📢 Publier maintenant', 'ad:publish_now')],
            [(('🟢 Auto pub : ON' if auto_enabled else '🔴 Auto pub : OFF'), 'ad:auto_toggle')],
            [('🎯 Groupes ciblés', 'ad:targets')],
        ])
    rows.append([('⬅️ Retour au panneau', 'admin:home')])
    return kb(rows)


def groups_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [('🔄 Actualiser la liste', 'groups:list')],
        [('⬅️ Retour au panneau', 'admin:home')],
    ])


def group_actions_kb(chat_id: int, group_type: str, targeted: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if group_type == 'main':
        rows.append([('➖ Retirer le rôle principal', f'group:detected:{chat_id}')])
    else:
        rows.append([('⭐ Définir comme principal', f'group:main:{chat_id}')])
    if group_type == 'pub':
        rows.append([('➖ Retirer des publicités', f'group:detected:{chat_id}')])
        rows.append([(('☑ Groupe ciblé' if targeted else '☐ Groupe non ciblé'), f'group:target:{chat_id}')])
    elif group_type != 'main':
        rows.append([('📢 Définir comme publicitaire', f'group:pub:{chat_id}')])
    rows.append([('⬅️ Retour aux groupes', 'groups:list')])
    return kb(rows)


def application_decision_kb(application_id: int) -> InlineKeyboardMarkup:
    return kb([
        [('✅ Prévalider', f'app:approve:{application_id}')],
        [('❌ Refuser avec motif', f'app:reject:{application_id}')],
        [('🚫 Bannir', f'app:ban:{application_id}')],
    ])


def payment_decision_kb(payment_id: int) -> InlineKeyboardMarkup:
    return kb([
        [('✅ Valider le paiement', f'pay:approve:{payment_id}')],
        [('❌ Refuser avec motif', f'pay:reject:{payment_id}')],
    ])


def appeal_decision_kb(appeal_id: int) -> InlineKeyboardMarkup:
    return kb([
        [('✅ Accepter et réouvrir l’accès', f'appealdec:approve:{appeal_id}')],
        [('❌ Refuser avec motif', f'appealdec:reject:{appeal_id}')],
        [('🚫 Maintenir le bannissement', f'appealdec:ban:{appeal_id}')],
    ])


def payments_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [('💵 Prix Premium', 'setting:text:premium_price')],
        [('💸 PayPal', 'setting:text:paypal_link')],
        [('₮ USDT', 'setting:text:usdt_address')],
        [('📊 État des paiements', 'payments:status')],
        [('⬅️ Retour au panneau', 'admin:home')],
    ])


def moderation_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [('📥 Candidatures en attente', 'moderation:applications')],
        [('💎 Paiements en attente', 'moderation:payments')],
        [('🧾 Réexamens en attente', 'moderation:appeals')],
        [('🚫 Comptes bloqués', 'moderation:blocked')],
        [('🧾 Journaux récents', 'moderation:logs')],
        [('⬅️ Retour au panneau', 'admin:home')],
    ])


BROADCAST_CATEGORIES: tuple[tuple[str, str], ...] = (
    ('Tous les utilisateurs non bloqués', 'all_active'),
    ('Personnes ayant cliqué sur Continuer', 'continued'),
    ('Candidatures incomplètes', 'free_incomplete'),
    ('Candidatures en attente', 'applications_pending'),
    ('Candidatures refusées', 'applications_rejected'),
    ('Auteurs/producteurs validés', 'free_members'),
    ('Personnes intéressées par le Premium', 'premium_interested'),
    ('Paiements en attente', 'payments_pending'),
    ('Paiements refusés', 'payments_rejected'),
    ('Membres Premium', 'premium_members'),
    ('Personnes ayant abandonné', 'abandoned'),
    ('Bannis après 3 minutes', 'failed_first'),
    ('Bannis après 24 heures', 'failed_quota'),
    ('Demandes de réexamen', 'appeals'),
)


def broadcast_categories_kb() -> InlineKeyboardMarkup:
    rows = [[(label, f'broadcast:category:{code}')] for label, code in BROADCAST_CATEGORIES]
    rows.append([('⬅️ Retour au panneau', 'admin:home')])
    return kb(rows)


def broadcast_confirm_kb(broadcast_id: int) -> InlineKeyboardMarkup:
    return kb([
        [('✅ Confirmer l’envoi', f'broadcast:confirm:{broadcast_id}')],
        [('❌ Annuler', f'broadcast:cancel:{broadcast_id}')],
    ])


def settings_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [('🔢 Limite maximale', 'setting:text:max_declared_total')],
        [('⏱ Fréquence publicité', 'setting:text:auto_pub_interval_minutes')],
        [('⬅️ Retour au panneau', 'admin:home')],
    ])
