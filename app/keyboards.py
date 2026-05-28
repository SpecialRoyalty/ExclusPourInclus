from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows
    ])


def url_kb(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


def start_kb():
    return kb([[('✅ Je suis intéressé', 'start:interested')], [('❌ Pas intéressé', 'start:not_interested')]])


def languages_kb():
    return kb([
        [('🇫🇷 Français', 'lang:fr'), ('🇬🇧 English', 'lang:en')],
        [('🇪🇸 Español', 'lang:es'), ('🇮🇹 Italiano', 'lang:it')],
        [('🇷🇺 Русский', 'lang:ru'), ('🇸🇦 عربي', 'lang:ar')],
    ])


def profile_kb():
    return kb([
        [('📦 Fournisseur / Créateur', 'profile:supplier')],
        [('💾 Amateur / Collectionneur', 'profile:collector')],
        [('❌ Je n’ai pas de contenu', 'profile:none')],
        [('⬅️ Retour', 'start:interested')],
    ])


def ok_kb(callback='ok'):
    return kb([[('✅ J’ai compris', callback)], [('⬅️ Retour', 'go:profile')]])


def continue_kb(callback='go:profile'):
    return kb([[('➡ Continuer', callback)], [('⬅️ Retour', 'start:interested')]])


def confirm_kb():
    return kb([[('✅ Confirmer', 'quota:confirm')], [('✏️ Modifier', 'quota:edit')]])


def rules_kb(next_id: int):
    if next_id <= 4:
        return kb([[('✅ J’ai compris', f'rule:{next_id}')]])
    return kb([[('✅ J’ai compris', 'rules:done')]])


def admin_panel_kb():
    return kb([
        [('📢 Publicité', 'admin:pub'), ('🖼 Images', 'admin:images')],
        [('👥 Groupes', 'admin:groups'), ('💳 Paiements', 'admin:payments')],
        [('📥 Modération', 'admin:moderation'), ('⚙️ Réglages', 'admin:settings')],
        [('ℹ️ Info / Vérification', 'admin:info')],
    ])


def back_admin_kb():
    return kb([[('⬅️ Retour panel', 'admin:home')]])


def pub_menu_kb(auto_enabled: bool):
    auto_label = '🟢 Auto pub : ON' if auto_enabled else '🔴 Auto pub : OFF'
    return kb([
        [('📢 Publier maintenant', 'pub:now')],
        [(auto_label, 'pub:auto_toggle')],
        [('👁 Voir groupes publicité', 'pub:targets')],
        [('📝 Modifier texte pub', 'text:set:ad_text')],
        [('⬅️ Retour panel', 'admin:home')],
    ])


def images_menu_kb():
    return kb([
        [('🖼 Image publicité', 'image:set:ad_image_file_id')],
        [('👋 Image accueil bot', 'image:set:welcome_image_file_id')],
        [('✅ Image exemple preuve', 'image:set:proof_example_image_file_id')],
        [('💰 Image campagne premium', 'image:set:premium_image_file_id')],
        [('👁 Prévisualiser images', 'image:preview')],
        [('🗑 Supprimer image', 'image:delete_menu')],
        [('⬅️ Retour panel', 'admin:home')],
    ])


def image_delete_kb():
    return kb([
        [('🗑 Pub', 'image:delete:ad_image_file_id'), ('🗑 Accueil', 'image:delete:welcome_image_file_id')],
        [('🗑 Preuve', 'image:delete:proof_example_image_file_id'), ('🗑 Premium', 'image:delete:premium_image_file_id')],
        [('⬅️ Retour images', 'admin:images')],
    ])


def groups_menu_kb():
    return kb([
        [('🔎 Voir groupes détectés', 'group:list')],
        [('⬅️ Retour panel', 'admin:home')],
    ])


def group_row_kb(chat_id: int, is_pub: bool, is_main: bool, targeted: bool):
    rows = []
    if not is_main:
        rows.append([('⭐ Définir principal', f'group:set_main:{chat_id}')])
    if is_pub:
        rows.append([('➖ Retirer des pubs', f'group:remove_pub:{chat_id}')])
        rows.append([(('☑ Ciblé pub' if targeted else '☐ Non ciblé'), f'group:toggle_target:{chat_id}')])
    else:
        rows.append([('➕ Définir comme pub', f'group:add_pub:{chat_id}')])
    rows.append([('⬅️ Retour groupes', 'group:list')])
    return kb(rows)


def admin_application_kb(app_id: int, user_id: int):
    return kb([
        [('✅ Valider', f'app:approve:{app_id}:{user_id}'), ('❌ Refuser', f'app:reject:{app_id}:{user_id}')],
        [('🚫 Bannir', f'app:ban:{app_id}:{user_id}')],
    ])


def proposal_admin_kb(pid: int):
    return kb([[('✅ Publier vote', f'prop:publish:{pid}'), ('❌ Refuser', f'prop:reject:{pid}')]])


def proposal_vote_kb(pid: int):
    return kb([[('✅ Oui', f'voteprop:{pid}:yes'), ('❌ Non', f'voteprop:{pid}:no')]])



def payments_menu_kb():
    return kb([
        [('💵 Prix premium', 'text:set:premium_price')],
        [('💸 PayPal', 'text:set:paypal_link')],
        [('₮ USDT', 'text:set:usdt_address')],
        [('📊 Statut paiements', 'payments:status')],
        [('⬅️ Retour panel', 'admin:home')],
    ])


def moderation_menu_kb():
    return kb([
        [('📥 Candidatures en attente', 'admin:apps')],
        [('🚫 Blacklist', 'admin:blacklist')],
        [('🧾 Logs récents', 'admin:logs')],
        [('⬅️ Retour panel', 'admin:home')],
    ])

def no_content_kb():
    return kb([
        [('💰 Accès premium', 'premium:access')],
        [('🎟 Je possède un VIP', 'premium:vip')],
        [('⬅️ Retour', 'go:profile')],
    ])

def premium_info_kb():
    return kb([[('💳 Continuer', 'premium:continue')], [('⬅️ Retour', 'profile:none')]])

def vip_info_kb():
    return kb([[('💳 Continuer', 'vip:continue')], [('⬅️ Retour', 'profile:none')]])
