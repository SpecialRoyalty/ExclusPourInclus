
import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x
]

user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🍎 Pomme", callback_data="wrong"),
            InlineKeyboardButton("🍌 Banane", callback_data="banana"),
        ],
        [
            InlineKeyboardButton("🍇 Raisin", callback_data="wrong"),
        ]
    ]

    await update.message.reply_text(
        "Captcha : sélectionne la banane.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "banana":
        user_states[user_id] = "intro"

        keyboard = [
            [
                InlineKeyboardButton("Oui", callback_data="intro_yes"),
                InlineKeyboardButton("Non", callback_data="intro_no"),
            ]
        ]

        await query.message.reply_text(
            "Tu en as marre d’entrer dans des groupes où seuls quelques-uns apportent de la valeur ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "intro_yes":
        user_states[user_id] = "france"

        keyboard = [
            [
                InlineKeyboardButton("Oui", callback_data="fr_yes"),
                InlineKeyboardButton("Non", callback_data="fr_no"),
            ]
        ]

        await query.message.reply_text(
            "Habitez-vous en France ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "intro_no":
        await query.message.reply_text("Accès refusé.")
        user_states[user_id] = "blocked"

    elif query.data == "fr_yes":
        keyboard = [
            [InlineKeyboardButton("Créé par moi-même", callback_data="cat_creator")],
            [InlineKeyboardButton("Acheté légalement", callback_data="cat_bought")],
            [InlineKeyboardButton("VIP Telegram payé", callback_data="cat_vip")],
        ]

        await query.message.reply_text(
            "Quel type d’accès possédez-vous ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "fr_no":
        await query.message.reply_text(
            "Vous n’êtes pas éligible à la liste d’attente."
        )
        user_states[user_id] = "blocked"

    elif query.data.startswith("cat_"):
        category = query.data.replace("cat_", "")
        user_states[user_id] = category

        await query.message.reply_text(
            "Envoyez maintenant une preuve (photo ou vidéo)."
        )


async def proof_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_states:
        return

    if not update.message.photo:
        await update.message.reply_text(
            "Veuillez envoyer une photo."
        )
        return

    photo = update.message.photo[-1].file_id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Valider",
                callback_data=f"approve_{user_id}"
            ),
            InlineKeyboardButton(
                "❌ Refuser",
                callback_data=f"reject_{user_id}"
            )
        ]
    ])

    for admin_id in ADMIN_IDS:
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=photo,
            caption=f"Nouvelle demande utilisateur : {user_id}",
            reply_markup=keyboard
        )

    await update.message.reply_text(
        "Votre demande a été envoyée aux administrateurs."
    )


async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("approve_"):
        user_id = int(data.split("_")[1])

        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Votre demande a été acceptée. Vous êtes sur la liste d’attente."
        )

        await query.message.reply_text(
            f"Utilisateur {user_id} validé."
        )

    elif data.startswith("reject_"):
        user_id = int(data.split("_")[1])

        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Votre demande a été refusée."
        )

        await query.message.reply_text(
            f"Utilisateur {user_id} refusé."
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(admin_review, pattern="^(approve_|reject_)"))
    app.add_handler(MessageHandler(filters.PHOTO, proof_handler))

    print("Bot lancé...")
    app.run_polling()


if __name__ == "__main__":
    main()
