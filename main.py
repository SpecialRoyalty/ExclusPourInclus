
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, ADMIN_IDS, WELCOME_IMAGE_URL
from database import init_db, db_session
from models import User, Group, Application, BotMessage, Advertisement
from utils import build_captcha, admin_keyboard


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_or_create_user(db, tg_user) -> User:
    user = db.query(User).filter(User.telegram_id == tg_user.id).first()

    if not user:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


def remember_bot_message(db, telegram_id, chat_id, message_id):
    msg = BotMessage(
        telegram_id=telegram_id,
        chat_id=chat_id,
        message_id=message_id,
    )
    db.add(msg)
    db.commit()


async def delete_old_bot_messages(context, db, telegram_id):
    messages = db.query(BotMessage).filter(BotMessage.telegram_id == telegram_id).all()

    for msg in messages:
        try:
            await context.bot.delete_message(
                chat_id=msg.chat_id,
                message_id=msg.message_id,
            )
        except Exception:
            pass

        db.delete(msg)

    db.commit()


async def send_and_remember(update, context, db, text, reply_markup=None, parse_mode=None):
    message = await update.effective_message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
    remember_bot_message(
        db,
        update.effective_user.id,
        update.effective_chat.id,
        message.message_id,
    )
    return message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)

    await delete_old_bot_messages(context, db, tg_user.id)

    if user.blocked:
        await send_and_remember(
            update,
            context,
            db,
            "⛔ Vous n’êtes plus éligible à la liste d’attente."
        )
        db.close()
        return

    if user.completed:
        await send_and_remember(
            update,
            context,
            db,
            "✅ Votre demande a déjà été enregistrée. Vous ne pouvez répondre qu’une seule fois."
        )
        db.close()
        return

    intro = (
        "🚪 *Bienvenue dans le groupe privé*\n\n"
        "Ici, vous êtes les bienvenus si vous avez du contenu à partager.\n\n"
        "✅ Vous êtes les bienvenus si :\n"
        "- vous avez du contenu amateur qui n’a jamais tourné ;\n"
        "- vous avez du contenu MYM / OnlyFans que vous avez acheté vous-même "
        "et que vous n’avez jamais partagé.\n\n"
        "⚠️ Toutes les autres demandes ne seront pas acceptées."
    )

    try:
        msg = await update.message.reply_photo(
            photo=WELCOME_IMAGE_URL,
            caption=intro,
            parse_mode="Markdown",
        )
        remember_bot_message(db, tg_user.id, update.effective_chat.id, msg.message_id)
    except Exception:
        await send_and_remember(update, context, db, intro, parse_mode="Markdown")

    answer, keyboard = build_captcha()
    user.captcha_answer = answer
    user.state = "captcha"
    db.commit()

    await send_and_remember(
        update,
        context,
        db,
        f"🧠 *Captcha de sécurité*\n\nSélectionne uniquement ce fruit : *{answer}*",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

    db.close()


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    db = db_session()
    tg_user = query.from_user
    user = get_or_create_user(db, tg_user)
    data = query.data

    async def reply(text, keyboard=None):
        msg = await query.message.reply_text(text, reply_markup=keyboard)
        remember_bot_message(db, tg_user.id, query.message.chat_id, msg.message_id)

    if data.startswith("captcha:"):
        selected = data.split(":", 1)[1]

        if selected != user.captcha_answer:
            user.blocked = True
            user.state = "blocked"
            db.commit()
            await reply("❌ Captcha incorrect. Accès bloqué.")
            db.close()
            return

        user.state = "intro"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="intro:yes"),
                InlineKeyboardButton("Non", callback_data="intro:no"),
            ]
        ])

        await reply(
            "Tu en as marre d’entrer dans des groupes, de participer, et que les autres profitent sans rien apporter ?",
            keyboard
        )

    elif data == "intro:yes":
        user.state = "france"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="france:yes"),
                InlineKeyboardButton("Non", callback_data="france:no"),
            ]
        ])

        await reply("Habitez-vous en France ?", keyboard)

    elif data == "intro:no":
        user.blocked = True
        user.state = "blocked"
        db.commit()
        await reply("D’accord. Le formulaire s’arrête ici.")

    elif data == "france:no":
        user.blocked = True
        user.state = "blocked"
        db.commit()
        await reply("Vous ne pouvez pas être ajouté à la liste d’attente.")

    elif data == "france:yes":
        user.state = "category"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Créé par moi-même", callback_data="cat:creator")],
            [InlineKeyboardButton("Acheté légalement", callback_data="cat:bought")],
            [InlineKeyboardButton("Les deux", callback_data="cat:both")],
            [InlineKeyboardButton("VIP Telegram payé", callback_data="cat:vip")],
            [InlineKeyboardButton("Je n’ai aucun contenu exclusif", callback_data="cat:none")],
        ])

        await reply("Possédez-vous du contenu exclusif ou un accès vérifiable ?", keyboard)

    elif data == "cat:none":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="vip:yes"),
                InlineKeyboardButton("Non", callback_data="vip:no"),
            ]
        ])
        await reply("Possédez-vous un VIP Telegram que vous avez payé ?", keyboard)

    elif data == "vip:no":
        user.blocked = True
        user.state = "blocked"
        db.commit()
        await reply("Vous n’êtes pas éligible à la liste d’attente.")

    elif data == "vip:yes":
        user.category = "vip"
        user.completed = True
        user.state = "completed"

        app = Application(
            telegram_id=user.telegram_id,
            username=user.username,
            category="vip",
            status="accepted",
        )

        db.add(app)
        db.commit()

        await reply("✅ Votre profil a été ajouté à la liste d’attente VIP.")

    elif data.startswith("cat:"):
        category = data.split(":", 1)[1]
        user.category = category
        user.state = "rights_confirm"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="rights:yes"),
                InlineKeyboardButton("Non", callback_data="rights:no"),
            ]
        ])

        await reply(
            "Confirmez-vous posséder les droits nécessaires ou l’autorisation de partager ce contenu ?",
            keyboard
        )

    elif data == "rights:no":
        user.retry_count += 1

        if user.retry_count > 1:
            user.blocked = True
            user.state = "blocked"
            text = "Vous avez déjà utilisé votre seconde chance. Accès bloqué."
        else:
            user.state = "new"
            text = "Vous pouvez vérifier vos informations puis recommencer une seule fois avec /start."

        db.commit()
        await reply(text)

    elif data == "rights:yes":
        user.state = "waiting_creator_name"
        db.commit()

        await reply(
            "Envoyez le nom de la créatrice ou du contenu.\n\n"
            "Ensuite, le bot vous demandera une preuve en photo ou vidéo."
        )

    elif data.startswith("admin_approve:") or data.startswith("admin_reject:"):
        if not is_admin(tg_user.id):
            await reply("Commande réservée aux admins.")
            db.close()
            return

        target_id = int(data.split(":", 1)[1])
        target = db.query(User).filter(User.telegram_id == target_id).first()
        pending = (
            db.query(Application)
            .filter(Application.telegram_id == target_id)
            .filter(Application.status == "pending")
            .order_by(Application.id.desc())
            .first()
        )

        if not target or not pending:
            await reply("Demande introuvable.")
            db.close()
            return

        if data.startswith("admin_approve:"):
            target.completed = True
            target.state = "completed"
            pending.status = "accepted"
            pending.reviewed_by = tg_user.id
            db.commit()

            await context.bot.send_message(
                chat_id=target_id,
                text="✅ Votre demande a été acceptée. Vous êtes sur la liste d’attente."
            )
            await reply(f"Utilisateur {target_id} validé.")

        else:
            target.blocked = True
            target.state = "blocked"
            pending.status = "rejected"
            pending.reviewed_by = tg_user.id
            db.commit()

            await context.bot.send_message(
                chat_id=target_id,
                text="❌ Votre demande a été refusée."
            )
            await reply(f"Utilisateur {target_id} refusé.")

    db.close()


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)

    if user.state != "waiting_creator_name":
        db.close()
        return

    creator_name = update.message.text.strip()

    existing = (
        db.query(Application)
        .filter(Application.telegram_id == user.telegram_id)
        .filter(Application.status == "draft")
        .first()
    )

    if not existing:
        existing = Application(
            telegram_id=user.telegram_id,
            username=user.username,
            category=user.category,
            creator_name=creator_name,
            status="draft",
        )
        db.add(existing)
    else:
        existing.creator_name = creator_name

    user.state = "waiting_proof"
    db.commit()

    await send_and_remember(
        update,
        context,
        db,
        "Parfait. Envoyez maintenant une preuve en photo ou vidéo.\n\n"
        "Votre demande sera examinée automatiquement et/ou manuellement."
    )

    db.close()


async def proof_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)

    if user.state != "waiting_proof":
        db.close()
        return

    file_id = None
    proof_type = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        proof_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        proof_type = "video"
    else:
        await send_and_remember(update, context, db, "Veuillez envoyer une photo ou une vidéo.")
        db.close()
        return

    app = (
        db.query(Application)
        .filter(Application.telegram_id == user.telegram_id)
        .filter(Application.status == "draft")
        .order_by(Application.id.desc())
        .first()
    )

    if not app:
        app = Application(
            telegram_id=user.telegram_id,
            username=user.username,
            category=user.category,
        )
        db.add(app)

    app.proof_file_id = file_id
    app.proof_type = proof_type
    app.status = "pending"
    user.state = "pending"
    db.commit()

    caption = (
        f"Nouvelle demande à valider\n\n"
        f"Utilisateur : {user.telegram_id}\n"
        f"Username : @{user.username}\n"
        f"Catégorie : {user.category}\n"
        f"Nom contenu/créatrice : {app.creator_name}\n"
        f"Type preuve : {proof_type}"
    )

    for admin_id in ADMIN_IDS:
        try:
            if proof_type == "photo":
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=caption,
                    reply_markup=admin_keyboard(user.telegram_id),
                )
            else:
                await context.bot.send_video(
                    chat_id=admin_id,
                    video=file_id,
                    caption=caption,
                    reply_markup=admin_keyboard(user.telegram_id),
                )
        except Exception:
            pass

    await send_and_remember(
        update,
        context,
        db,
        "Votre demande a été envoyée aux administrateurs. Vous serez notifié après vérification."
    )

    db.close()


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["group", "supergroup", "channel"]:
        return

    db = db_session()

    group = db.query(Group).filter(Group.chat_id == chat.id).first()

    if not group:
        group = Group(
            chat_id=chat.id,
            title=chat.title,
            username=chat.username,
            active=True,
        )
        db.add(group)
    else:
        group.title = chat.title
        group.username = chat.username
        group.active = True

    db.commit()
    db.close()


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Commande réservée aux admins.")
        return

    text = (
        "👑 Panel admin\n\n"
        "/groups - voir les groupes connectés\n"
        "/waitlist - voir les listes d’attente\n"
        "/pending - voir les demandes en attente\n"
        "/ad - créer une publicité"
    )

    await update.message.reply_text(text)


async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    db = db_session()
    groups_list = db.query(Group).filter(Group.active == True).all()

    if not groups_list:
        await update.message.reply_text("Aucun groupe détecté.")
        db.close()
        return

    text = "Groupes connectés :\n\n"
    for g in groups_list:
        text += f"{g.id}. {g.title} | chat_id: {g.chat_id}\n"

    await update.message.reply_text(text)
    db.close()


async def waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    db = db_session()

    accepted = (
        db.query(Application)
        .filter(Application.status == "accepted")
        .order_by(Application.category)
        .all()
    )

    if not accepted:
        await update.message.reply_text("Aucun utilisateur validé.")
        db.close()
        return

    text = "Listes d’attente validées :\n\n"

    for app in accepted:
        username = f"@{app.username}" if app.username else str(app.telegram_id)
        text += f"- {username} | {app.category} | {app.creator_name or ''}\n"

    await update.message.reply_text(text[:3900])
    db.close()


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    db = db_session()

    pending_apps = (
        db.query(Application)
        .filter(Application.status == "pending")
        .order_by(Application.created_at.desc())
        .all()
    )

    if not pending_apps:
        await update.message.reply_text("Aucune demande en attente.")
        db.close()
        return

    text = "Demandes en attente :\n\n"

    for app in pending_apps:
        username = f"@{app.username}" if app.username else str(app.telegram_id)
        text += f"- {username} | {app.category} | {app.creator_name or ''}\n"

    await update.message.reply_text(text[:3900])
    db.close()


async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    db = db_session()
    groups_list = db.query(Group).filter(Group.active == True).all()

    if not groups_list:
        await update.message.reply_text("Aucun groupe connecté.")
        db.close()
        return

    text = (
        "Pour envoyer une pub, réponds avec :\n\n"
        "/sendad ID_DU_GROUPE Texte de la publicité\n\n"
        "Exemple :\n"
        "/sendad 1 Liste d’attente privée ouverte. Clique pour rejoindre."
    )

    text += "\n\nGroupes :\n"
    for g in groups_list:
        text += f"{g.id}. {g.title}\n"

    await update.message.reply_text(text)
    db.close()


async def send_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("Format : /sendad ID_GROUPE texte")
        return

    group_id = int(context.args[0])
    caption = " ".join(context.args[1:])

    db = db_session()
    group = db.query(Group).filter(Group.id == group_id).first()

    if not group:
        await update.message.reply_text("Groupe introuvable.")
        db.close()
        return

    bot_username = (await context.bot.get_me()).username

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Rejoindre la liste d’attente",
                url=f"https://t.me/{bot_username}?start=waitlist"
            )
        ]
    ])

    await context.bot.send_message(
        chat_id=group.chat_id,
        text=caption,
        reply_markup=keyboard,
    )

    ad = Advertisement(
        created_by=update.effective_user.id,
        caption=caption,
    )
    db.add(ad)
    db.commit()

    await update.message.reply_text("Publicité envoyée.")
    db.close()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant.")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("groups", groups))
    app.add_handler(CommandHandler("waitlist", waitlist))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("ad", ad_command))
    app.add_handler(CommandHandler("sendad", send_ad))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, proof_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot lancé.")
    app.run_polling()


if __name__ == "__main__":
    main()
