
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
]


def build_captcha():
    correct = random.choice(FRUITS)
    wrong = random.sample([f for f in FRUITS if f["name"] != correct["name"]], 5)
    choices = wrong + [correct]
    random.shuffle(choices)

    rows = []
    row = []

    for fruit in choices:
        row.append(
            InlineKeyboardButton(
                f'{fruit["emoji"]} {fruit["name"]}',
                callback_data=f'captcha:{fruit["name"]}'
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return correct["name"], InlineKeyboardMarkup(rows)


def admin_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Valider", callback_data=f"admin_approve:{user_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"admin_reject:{user_id}")
        ]
    ])


def join_button():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Rejoindre la liste d’attente",
                url="https://t.me/YOUR_BOT_USERNAME?start=waitlist"
            )
        ]
    ])
