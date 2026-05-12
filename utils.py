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
    # Fruit correct
    correct = random.choice(FRUITS)

    # 8 faux fruits
    wrong = random.sample(
        [f for f in FRUITS if f["name"] != correct["name"]],
        8
    )

    # Mélange
    choices = wrong + [correct]
    random.shuffle(choices)

    rows = []
    row = []

    # Construction du clavier
    for fruit in choices:

        # UNIQUEMENT L'EMOJI
        row.append(
            InlineKeyboardButton(
                fruit["emoji"],
                callback_data=f'captcha:{fruit["name"]}'
            )
        )

        # 3 boutons par ligne
        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return correct["name"], InlineKeyboardMarkup(rows)


def admin_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Valider",
                callback_data=f"admin_approve:{user_id}"
            ),
            InlineKeyboardButton(
                "❌ Refuser",
                callback_data=f"admin_reject:{user_id}"
            )
        ]
    ])


def join_button(bot_username="YOUR_BOT_USERNAME"):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚪 Rejoindre la liste d’attente",
                url=f"https://t.me/{bot_username}?start=waitlist"
            )
        ]
    ])
