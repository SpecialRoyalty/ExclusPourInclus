from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def start_kb():
    return kb([[('✅ Je suis intéressé', 'start:interested')], [('❌ Pas intéressé', 'start:not_interested')]])


def languages_kb():
    return kb([[('🇫🇷 Français', 'lang:fr'), ('🇬🇧 English', 'lang:en')], [('🇪🇸 Español', 'lang:es'), ('🇮🇹 Italiano', 'lang:it')], [('🇷🇺 Русский', 'lang:ru'), ('🇸🇦 عربي', 'lang:ar')]])


def profile_kb():
    return kb([[('📦 Fournisseur / Créateur', 'profile:supplier')], [('💾 Amateur / Collectionneur', 'profile:collector')], [('❌ Je n’ai pas de contenu', 'profile:none')]])


def ok_kb(tag='ok'):
    return kb([[('✅ J’ai compris', tag)]])


def confirm_kb():
    return kb([[('✅ Confirmer', 'quota:confirm')], [('✏️ Modifier', 'quota:edit')]])


def admin_application_kb(app_id: int, user_id: int):
    return kb([[('✅ Valider', f'app:approve:{app_id}:{user_id}'), ('❌ Refuser', f'app:reject:{app_id}:{user_id}')], [('🚫 Bannir', f'app:ban:{app_id}:{user_id}')]])


def admin_panel_kb():
    return kb([
        [('📢 Publier pub', 'admin:pub_now'), ('🔁 Auto pub ON/OFF', 'admin:autopub')],
        [('👥 Groupes', 'admin:groups'), ('📥 Candidatures', 'admin:apps')],
        [('💰 Cagnotte', 'admin:pot'), ('📊 Stats', 'admin:stats')],
        [('🗳 Propositions', 'admin:proposals'), ('🚫 Blacklist', 'admin:blacklist')],
    ])


def rules_kb(n: int):
    return kb([[('✅ J’ai compris', f'rule:{n}')]])


def proposal_admin_kb(pid: int):
    return kb([[('✅ Publier vote', f'prop:publish:{pid}'), ('❌ Refuser', f'prop:reject:{pid}')]])


def proposal_vote_kb(pid: int):
    return kb([[('✅ Oui', f'voteprop:{pid}:yes'), ('❌ Non', f'voteprop:{pid}:no')]])
