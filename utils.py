import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

FRUITS = [
    {"name": "Pomme", "emoji": "🍎"},
    {"name": "Banane", "emoji": "🍌"},
    {"name": "Raisin", "emoji": "🍇"},
    {"name": "Fraise", "emoji": "🍓"},
    {"name": "Orange", "emoji": "🍊"},
    {"name": "Citron", "emoji": "🍋"},
    {"name": "Pastèque", "emoji": "🍉"},
    {"name": "Cerise", "emoji": "🍒"},
    {"name": "Ananas", "emoji": "🍍"},
    {"name": "Kiwi", "emoji": "🥝"},
    {"name": "Mangue", "emoji": "🥭"},
    {"name": "Poire", "emoji": "🍐"},
    {"name": "Noix de coco", "emoji": "🥥"},
]


def build_captcha():
    correct = random.choice(FRUITS)
    wrong = random.sample([f for f in FRUITS if f["name"] != correct["name"]], 8)
    choices = wrong + [correct]
    random.shuffle(choices)

    rows, row = [], []
    for fruit in choices:
        row.append(InlineKeyboardButton(fruit["emoji"], callback_data=f"captcha:{fruit['name']}"))
        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return correct["name"], InlineKeyboardMarkup(rows)


def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Publicités", callback_data="admin:ads")],
        [InlineKeyboardButton("👥 Groupes connectés", callback_data="admin:groups")],
        [InlineKeyboardButton("⏳ Demandes en attente", callback_data="admin:pending")],
        [InlineKeyboardButton("✅ Listes d’attente", callback_data="admin:waitlists")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin:stats")],
    ])


def back_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Retour panel admin", callback_data="admin:home")]
    ])


def application_review_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Valider", callback_data=f"review:approve:{user_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"review:reject:{user_id}")
        ],
        [InlineKeyboardButton("✍️ Refuser avec motif", callback_data=f"review:reject_reason:{user_id}")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="admin:pending")]
    ])


def ad_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Créer une publicité", callback_data="ad:create")],
        [InlineKeyboardButton("📂 Mes publicités", callback_data="ad:list")],
        [InlineKeyboardButton("🚀 Publier dans un groupe", callback_data="ad:publish")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="admin:home")]
    ])


def broadcast_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Liste globale validée", callback_data="broadcast:target:all")],
        [InlineKeyboardButton("🎨 Créés par eux-mêmes", callback_data="broadcast:target:creator")],
        [InlineKeyboardButton("💳 Achetés sur plateformes", callback_data="broadcast:target:bought")],
        [InlineKeyboardButton("👑 VIP Telegram", callback_data="broadcast:target:vip")],
        [InlineKeyboardButton("🚪 Formulaires abandonnés", callback_data="broadcast:target:unfinished")],
        [InlineKeyboardButton("⛔ Utilisateurs bloqués", callback_data="broadcast:target:blocked")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="admin:home")]
    ])


def join_waitlist_keyboard(bot_username):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Rejoindre la liste d’attente", url=f"https://t.me/{bot_username}?start=waitlist")]
    ])


def vip_question_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Oui", callback_data="vip:yes"),
            InlineKeyboardButton("Non", callback_data="vip:no")
        ]
    ])
