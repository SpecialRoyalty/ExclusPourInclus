from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, ContextTypes, filters
)

from config import BOT_TOKEN, ADMIN_IDS, WELCOME_IMAGE_URL
from database import init_db, db_session
from models import User, Group, Application, BotMessage, Advertisement, Broadcast
from utils import (
    build_captcha, admin_main_keyboard, back_admin_keyboard,
    application_review_keyboard, ad_menu_keyboard, broadcast_menu_keyboard,
    join_waitlist_keyboard, vip_question_keyboard
)


UNFINISHED_STATES = [
    "captcha", "intro", "france", "category", "bought_confirm",
    "bought_name", "creator_details", "waiting_proof", "pending", "vip_question"
]

BLOCK_REASON_LABELS = {
    "bot_blocked": "Bot bloqué par l’utilisateur",
    "captcha_failed": "Captcha raté",
    "intro_no": "Pas intéressé",
    "not_france": "Pas en France",
    "vip_no": "Pas de VIP",
    "admin_second_reject": "Double refus admin",
}


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
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        db.commit()

    return user


def remember_bot_message(db, telegram_id, chat_id, message_id):
    db.add(BotMessage(
        telegram_id=telegram_id,
        chat_id=chat_id,
        message_id=message_id
    ))
    db.commit()


def block_user(db, user, reason):
    user.blocked = True
    user.state = "blocked"
    if hasattr(user, "block_reason"):
        user.block_reason = reason
    db.commit()


def get_pending_application(db, telegram_id):
    return (
        db.query(Application)
        .filter(Application.telegram_id == telegram_id)
        .filter(Application.status == "pending")
        .order_by(Application.id.desc())
        .first()
    )


async def safe_reply_text(message, text, reply_markup=None, parse_mode=None):
    try:
        return await message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def safe_reply_photo(message, photo, caption=None, reply_markup=None, parse_mode=None):
    try:
        return await message.reply_photo(
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def safe_reply_video(message, video, caption=None, reply_markup=None, parse_mode=None):
    try:
        return await message.reply_video(
            video=video,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def safe_send_photo(bot, chat_id, photo, caption=None, reply_markup=None, parse_mode=None):
    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def safe_send_video(bot, chat_id, video, caption=None, reply_markup=None, parse_mode=None):
    try:
        return await bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except (Forbidden, BadRequest):
        return None


async def delete_old_bot_messages(context, db, telegram_id):
    messages = db.query(BotMessage).filter(BotMessage.telegram_id == telegram_id).all()

    for msg in messages:
        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except Exception:
            pass

        db.delete(msg)

    db.commit()


async def send_and_remember(update, context, db, text, reply_markup=None, parse_mode=None):
    message = await safe_reply_text(
        update.effective_message,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )

    if not message:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        if user:
            block_user(db, user, "bot_blocked")
        return None

    remember_bot_message(
        db,
        update.effective_user.id,
        update.effective_chat.id,
        message.message_id
    )

    return message


async def send_vip_question_from_query(query, db, user, reason_text=None):
    user.state = "vip_question"
    user.category = "vip"
    db.commit()

    prefix = ""
    if reason_text:
        prefix = reason_text + "\n\n"

    await safe_reply_text(
        query.message,
        prefix + "Possédez-vous un VIP Telegram que vous avez payé ?",
        reply_markup=vip_question_keyboard()
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)

    if is_admin(tg_user.id):
        await safe_reply_text(
            update.message,
            "👑 Panel Admin",
            reply_markup=admin_main_keyboard()
        )
        db.close()
        return

    pending_app = get_pending_application(db, tg_user.id)
    if user.state == "pending" or pending_app:
        await send_and_remember(
            update, context, db,
            "⏳ Votre demande est déjà en attente de validation.\n\n"
            "Vous ne pouvez pas soumettre un second formulaire tant que les admins n’ont pas traité votre demande."
        )
        db.close()
        return

    await delete_old_bot_messages(context, db, tg_user.id)

    if user.blocked:
        await send_and_remember(
            update, context, db,
            "⛔ Vous n’êtes plus éligible à la liste d’attente."
        )
        db.close()
        return

    if user.completed:
        await send_and_remember(
            update, context, db,
            "✅ Votre demande a déjà été enregistrée."
        )
        db.close()
        return

    if user.rejected_count == 1:
        warning = (
            "⚠️ Vous utilisez votre seconde et dernière demande classique.\n"
            "Si celle-ci est refusée, il restera uniquement la dernière chance VIP.\n\n"
        )
    elif user.rejected_count >= 2:
        user.state = "vip_question"
        user.category = "vip"
        db.commit()

        await send_and_remember(
            update, context, db,
            "⚠️ Vos deux demandes ont été refusées.\n\n"
            "Dernière chance : possédez-vous un VIP Telegram que vous avez payé ?",
            reply_markup=vip_question_keyboard()
        )
        db.close()
        return
    else:
        warning = ""

    intro = (
        warning +
        "🚪 *Bienvenue dans le groupe privé*\n\n"
        "Vous êtes les bienvenus si vous en avez marre des groupes "
        "qui proposent toujours le même contenu.\n\n"
        "🔥 Ici, place à l’exclusivité.\n"
        "Du contenu proposé par vous, pour vous.\n\n"
        "✅ Contenu amateur jamais vu\n"
        "✅ Contenu rare et non repartagé partout\n"
        "✅ Une vraie sélection, pas du contenu recyclé\n\n"
        "⚠️ Toutes les autres demandes ne seront pas acceptées."
    )

    msg = await safe_reply_photo(
        update.message,
        photo=WELCOME_IMAGE_URL,
        caption=intro,
        parse_mode="Markdown"
    )

    if msg:
        remember_bot_message(db, tg_user.id, update.effective_chat.id, msg.message_id)
    else:
        result = await send_and_remember(update, context, db, intro, parse_mode="Markdown")
        if result is None:
            db.close()
            return

    answer, keyboard = build_captcha()
    user.captcha_answer = answer
    user.captcha_attempts = 0
    user.state = "captcha"
    if hasattr(user, "block_reason"):
        user.block_reason = None
    db.commit()

    await send_and_remember(
        update, context, db,
        f"🧠 *Captcha de sécurité*\n\nSélectionne uniquement ce fruit : *{answer}*",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    db.close()


async def user_flow_callback(update, context, db, user, data):
    query = update.callback_query
    tg_user = query.from_user

    async def reply(text, keyboard=None):
        msg = await safe_reply_text(query.message, text, reply_markup=keyboard)
        if msg:
            remember_bot_message(db, tg_user.id, query.message.chat_id, msg.message_id)
        return msg

    if user.blocked:
        await reply("⛔ Accès bloqué.")
        return

    if user.completed:
        await reply("✅ Votre demande a déjà été enregistrée.")
        return

    pending_app = get_pending_application(db, user.telegram_id)
    if pending_app:
        await reply("⏳ Votre demande est déjà en attente de validation.\n\nVous ne pouvez pas soumettre un second formulaire.")
        return

    if data.startswith("captcha:"):
        selected = data.split(":", 1)[1]

        if selected != user.captcha_answer:
            user.captcha_attempts = (user.captcha_attempts or 0) + 1

            if user.captcha_attempts >= 3:
                block_user(db, user, "captcha_failed")
                await reply("❌ Trop de captchas incorrects. Accès bloqué.")
                return

            answer, keyboard = build_captcha()
            user.captcha_answer = answer
            db.commit()

            await reply(
                f"❌ Mauvais fruit. Tentative {user.captcha_attempts}/3.\n\n"
                f"Sélectionne uniquement ce fruit : {answer}",
                keyboard
            )
            return

        user.state = "intro"
        user.captcha_attempts = 0
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="intro:yes"),
                InlineKeyboardButton("Non", callback_data="intro:no")
            ]
        ])

        await reply(
            "Tu en as marre d’entrer dans des groupes, de participer, et que les autres profitent sans rien apporter ?",
            keyboard
        )
        return

    if data == "intro:no":
        block_user(db, user, "intro_no")
        await reply("D’accord. Le formulaire s’arrête ici.")
        return

    if data == "intro:yes":
        user.state = "france"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="france:yes"),
                InlineKeyboardButton("Non", callback_data="france:no")
            ]
        ])

        await reply("Habites tu en France ?", keyboard)
        return

    if data == "france:no":
        block_user(db, user, "not_france")
        await reply("Vous ne pouvez pas être ajouté à la liste d’attente.")
        return

    if data == "france:yes":
        user.state = "category"
        db.commit()

        text = (
            "🚪 *Bienvenue dans le groupe privé*\n\n"
            "Ici, vous êtes les bienvenus si vous avez du contenu à partager.\n\n"
            "✅ Vous êtes les bienvenus si :\n"
            "- vous avez du contenu amateur qui n’a jamais tourné ;\n"
            "- vous avez du contenu MYM / OnlyFans que vous avez acheté vous-même "
            "et que vous n’avez jamais partagé.\n\n"
            "⚠️ Toutes les autres demandes ne seront pas acceptées."
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Créé par moi-même ou mes proches (amateur)", callback_data="cat:creator")],
            [InlineKeyboardButton("Acheté sur les plateformes MYM/OnlyFans", callback_data="cat:bought")],
            [InlineKeyboardButton("Je ne possède aucun contenu exclusif", callback_data="cat:none")]
        ])

        await reply(text, keyboard)
        return

    if data == "cat:none":
        await send_vip_question_from_query(query, db, user)
        return

    if data == "vip:no":
        block_user(db, user, "vip_no")
        await reply("Vous n’êtes pas éligible à la liste d’attente.")
        return

    if data == "vip:yes":
        user.category = "vip"
        user.completed = True
        user.blocked = False
        user.state = "completed"

        app = Application(
            telegram_id=user.telegram_id,
            username=user.username,
            category="vip",
            creator_name="VIP Telegram payé",
            status="accepted"
        )

        db.add(app)
        db.commit()

        await reply("✅ Votre profil a été ajouté à la liste d’attente VIP.")
        return

    if data == "cat:creator":
        user.category = "creator"
        user.state = "creator_details"
        db.commit()

        await reply(
            "Expliquez les détails d’obtention du média.\n\n"
            "Exemple : comment vous l’avez obtenu, pourquoi il est exclusif, et pourquoi il apporte de la valeur au groupe."
        )
        return

    if data == "cat:bought":
        user.category = "bought"
        user.state = "bought_confirm"
        db.commit()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Oui", callback_data="bought_confirm:yes"),
                InlineKeyboardButton("Non", callback_data="bought_confirm:no")
            ]
        ])

        await reply(
            "Êtes-vous certain que ce contenu n’est pas déjà largement diffusé sur Telegram, Discord, Leakmedia ou d’autres plateformes publiques ?",
            keyboard
        )
        return

    if data == "bought_confirm:no":
        await send_vip_question_from_query(
            query, db, user,
            "Dernière chance"
        )
        return

    if data == "bought_confirm:yes":
        user.state = "bought_name"
        db.commit()

        await reply(
            "Envoyez le nom de la créatrice ou du contenu acheté.\n\n"
            "Ensuite, le bot vous demandera une preuve en photo ou vidéo."
        )
        return


async def get_stats_text(db):
    total_users = db.query(User).count()
    accepted = db.query(Application).filter(Application.status == "accepted").count()
    pending = db.query(Application).filter(Application.status == "pending").count()
    rejected = db.query(Application).filter(Application.status == "rejected").count()
    blocked = db.query(User).filter(User.blocked == True).count()

    unfinished = (
        db.query(User)
        .filter(User.completed == False)
        .filter(User.blocked == False)
        .filter(User.state.in_(UNFINISHED_STATES))
        .count()
    )

    broadcasts = db.query(Broadcast).all()
    sent_total = sum([b.sent_count or 0 for b in broadcasts])
    failed_total = sum([b.failed_count or 0 for b in broadcasts])

    text = (
        "📊 Statistiques du bot\n\n"
        f"👥 Utilisateurs ayant lancé le bot : {total_users}\n"
        f"✅ Utilisateurs acceptés : {accepted}\n"
        f"⏳ Demandes en attente : {pending}\n"
        f"❌ Demandes refusées : {rejected}\n"
        f"⛔ Utilisateurs bloqués : {blocked}\n"
        f"🚪 Formulaires non terminés : {unfinished}\n\n"
        f"📣 Broadcasts envoyés : {len(broadcasts)}\n"
        f"📨 Messages broadcast envoyés : {sent_total}\n"
        f"⚠️ Échecs broadcast : {failed_total}\n"
    )

    if blocked > 0 and hasattr(User, "block_reason"):
        rows = db.query(User.block_reason).filter(User.blocked == True).all()
        counts = {}
        for row in rows:
            reason = row[0] or "unknown"
            counts[reason] = counts.get(reason, 0) + 1
        text += "\n⛔ Raisons de blocage :\n"
        for reason, count in counts.items():
            pct = round((count / blocked) * 100)
            label = BLOCK_REASON_LABELS.get(reason, reason)
            text += f"- {label} : {pct}% ({count})\n"

    return text


async def admin_callback(update, context, db, user, data):
    query = update.callback_query
    admin_id = query.from_user.id

    if not is_admin(admin_id):
        await safe_reply_text(query.message, "Commande réservée aux admins.")
        return

    if data == "admin:home":
        await safe_reply_text(query.message, "👑 Panel Admin", reply_markup=admin_main_keyboard())
        return

    if data == "admin:stats":
        text = await get_stats_text(db)
        await safe_reply_text(query.message, text[:3900], reply_markup=back_admin_keyboard())
        return

    if data == "admin:ads":
        await safe_reply_text(query.message, "📢 Menu publicités", reply_markup=ad_menu_keyboard())
        return

    if data == "admin:groups":
        groups = db.query(Group).filter(Group.active == True).order_by(Group.id.asc()).all()

        if not groups:
            await safe_reply_text(query.message, "Aucun groupe connecté.", reply_markup=back_admin_keyboard())
            return

        text = "👥 Groupes connectés :\n\n"
        for g in groups:
            text += f"{g.id}. {g.title or 'Sans titre'}\nID : {g.chat_id}\nStatut : actif\n\n"

        await safe_reply_text(query.message, text[:3900], reply_markup=back_admin_keyboard())
        return

    if data == "admin:waitlists":
        apps = db.query(Application).filter(Application.status == "accepted").order_by(Application.category.asc()).all()

        if not apps:
            await safe_reply_text(query.message, "Aucune personne validée.", reply_markup=back_admin_keyboard())
            return

        text = "✅ Listes d’attente :\n\n"
        for app in apps:
            username = f"@{app.username}" if app.username else str(app.telegram_id)
            text += f"- {username} | {app.category} | {app.creator_name or ''}\n"

        await safe_reply_text(query.message, text[:3900], reply_markup=back_admin_keyboard())
        return

    if data == "admin:pending":
        pending = db.query(Application).filter(Application.status == "pending").order_by(Application.id.asc()).first()

        if not pending:
            await safe_reply_text(query.message, "Aucune demande en attente.", reply_markup=back_admin_keyboard())
            return

        text = (
            "⏳ Demande en attente\n\n"
            f"Utilisateur : @{pending.username or pending.telegram_id}\n"
            f"ID : {pending.telegram_id}\n"
            f"Catégorie : {pending.category}\n"
            f"Détails : {pending.creator_name or 'Non renseigné'}\n"
            f"Preuve : {pending.proof_type}"
        )

        keyboard = application_review_keyboard(pending.telegram_id)

        if pending.proof_type == "photo":
            sent = await safe_reply_photo(query.message, pending.proof_file_id, caption=text, reply_markup=keyboard)
            if not sent:
                await safe_reply_text(query.message, text, reply_markup=keyboard)
        elif pending.proof_type == "video":
            sent = await safe_reply_video(query.message, pending.proof_file_id, caption=text, reply_markup=keyboard)
            if not sent:
                await safe_reply_text(query.message, text, reply_markup=keyboard)
        else:
            await safe_reply_text(query.message, text, reply_markup=keyboard)

        return

    if data == "admin:broadcast":
        await safe_reply_text(query.message, "📣 Choisissez une liste :", reply_markup=broadcast_menu_keyboard())
        return


async def ad_callback(update, context, db, user, data):
    query = update.callback_query
    admin_id = query.from_user.id

    if not is_admin(admin_id):
        await safe_reply_text(query.message, "Commande réservée aux admins.")
        return

    if data == "ad:create":
        user.state = "admin_waiting_ad_image"
        db.commit()
        await safe_reply_text(query.message, "Envoyez maintenant l’image de la publicité.")
        return

    if data == "ad:list":
        ads = db.query(Advertisement).order_by(Advertisement.id.desc()).limit(10).all()

        if not ads:
            await safe_reply_text(query.message, "Aucune publicité enregistrée.", reply_markup=ad_menu_keyboard())
            return

        text = "📂 Publicités enregistrées :\n\n"
        for ad in ads:
            text += f"Pub #{ad.id}\n{ad.caption[:120]}\n\n"

        await safe_reply_text(query.message, text[:3900], reply_markup=ad_menu_keyboard())
        return

    if data == "ad:publish":
        groups = db.query(Group).filter(Group.active == True).order_by(Group.id.asc()).all()

        if not groups:
            await safe_reply_text(query.message, "Aucun groupe connecté.", reply_markup=ad_menu_keyboard())
            return

        rows = [
            [InlineKeyboardButton(g.title or str(g.chat_id), callback_data=f"ad:select_group:{g.id}")]
            for g in groups
        ]
        rows.append([InlineKeyboardButton("⬅️ Retour", callback_data="admin:ads")])

        await safe_reply_text(
            query.message,
            "Choisissez le groupe où publier :",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("ad:select_group:"):
        group_id = int(data.split(":")[-1])
        ads = db.query(Advertisement).order_by(Advertisement.id.desc()).limit(20).all()

        if not ads:
            await safe_reply_text(
                query.message,
                "Aucune publicité enregistrée. Créez d’abord une publicité.",
                reply_markup=ad_menu_keyboard()
            )
            return

        rows = [
            [InlineKeyboardButton(f"Pub #{ad.id}", callback_data=f"ad:send:{group_id}:{ad.id}")]
            for ad in ads
        ]
        rows.append([InlineKeyboardButton("⬅️ Retour", callback_data="ad:publish")])

        await safe_reply_text(
            query.message,
            "Choisissez la publicité à envoyer :",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    if data.startswith("ad:send:"):
        _, _, group_id, ad_id = data.split(":")
        group = db.query(Group).filter(Group.id == int(group_id)).first()
        ad = db.query(Advertisement).filter(Advertisement.id == int(ad_id)).first()

        if not group or not ad:
            await safe_reply_text(query.message, "Groupe ou publicité introuvable.", reply_markup=ad_menu_keyboard())
            return

        bot_username = (await context.bot.get_me()).username
        keyboard = join_waitlist_keyboard(bot_username)

        if ad.image_file_id:
            sent = await safe_send_photo(
                context.bot,
                chat_id=group.chat_id,
                photo=ad.image_file_id,
                caption=ad.caption,
                reply_markup=keyboard
            )
        else:
            sent = await safe_send_message(
                context.bot,
                chat_id=group.chat_id,
                text=ad.caption,
                reply_markup=keyboard
            )

        if sent:
            await safe_reply_text(query.message, "✅ Publicité publiée dans le groupe.", reply_markup=ad_menu_keyboard())
        else:
            await safe_reply_text(query.message, "Erreur publication : impossible d’envoyer dans ce groupe.", reply_markup=ad_menu_keyboard())

        return


async def reject_application(context, db, target, app, admin_id, reason):
    current_app = db.query(Application).filter(Application.id == app.id).first()
    if not current_app or current_app.status != "pending":
        return False

    target.rejected_count = (target.rejected_count or 0) + 1

    current_app.status = "rejected"
    current_app.refusal_reason = reason
    current_app.reviewed_by = admin_id

    if target.rejected_count >= 2:
        target.blocked = False
        target.completed = False
        target.state = "vip_question"
        target.category = "vip"

        message = (
            "❌ Votre seconde demande a été refusée.\n\n"
            f"Motif : {reason}\n\n"
            "Dernière chance : possédez-vous un VIP Telegram que vous avez payé ?\n\n"
            "Répondez avec /start pour accéder à la dernière question."
        )
    else:
        target.blocked = False
        target.completed = False
        target.state = "new"
        target.category = None
        target.captcha_answer = None
        target.captcha_attempts = 0

        message = (
            "❌ Votre demande a été refusée.\n\n"
            f"Motif : {reason}\n\n"
            "Vous pouvez faire une dernière demande classique avec /start. "
            "Attention : si elle est refusée, c'est terminé."
        )

    db.commit()
    await safe_send_message(context.bot, target.telegram_id, message)
    return True


async def review_callback(update, context, db, user, data):
    query = update.callback_query
    admin_id = query.from_user.id

    if not is_admin(admin_id):
        await safe_reply_text(query.message, "Commande réservée aux admins.")
        return

    parts = data.split(":")
    action = parts[1]
    target_id = int(parts[2])

    target = db.query(User).filter(User.telegram_id == target_id).first()
    app = (
        db.query(Application)
        .filter(Application.telegram_id == target_id)
        .order_by(Application.id.desc())
        .first()
    )

    if not target or not app:
        await safe_reply_text(query.message, "Demande introuvable.")
        return

    if app.status != "pending":
        await safe_reply_text(query.message, "⚠️ Décision déjà prise par un autre admin.", reply_markup=back_admin_keyboard())
        return

    if action == "approve":
        target.completed = True
        target.blocked = False
        target.state = "completed"

        app.status = "accepted"
        app.reviewed_by = admin_id

        db.commit()

        await safe_send_message(
            context.bot,
            chat_id=target_id,
            text="✅ Votre demande a été acceptée. Vous êtes sur la liste d’attente."
        )

        await safe_reply_text(query.message, "Utilisateur validé.", reply_markup=back_admin_keyboard())
        return

    if action == "reject":
        ok = await reject_application(context, db, target, app, admin_id, "Demande refusée par l’équipe.")
        if ok:
            await safe_reply_text(query.message, "Utilisateur refusé.", reply_markup=back_admin_keyboard())
        else:
            await safe_reply_text(query.message, "⚠️ Décision déjà prise par un autre admin.", reply_markup=back_admin_keyboard())
        return

    if action == "reject_reason":
        user.state = f"admin_waiting_refusal_reason:{target_id}"
        db.commit()
        await safe_reply_text(query.message, "Écrivez maintenant le motif du refus.")
        return


async def broadcast_callback(update, context, db, user, data):
    query = update.callback_query
    admin_id = query.from_user.id

    if not is_admin(admin_id):
        await safe_reply_text(query.message, "Commande réservée aux admins.")
        return

    if data.startswith("broadcast:target:"):
        target = data.split(":")[-1]
        user.state = f"admin_waiting_broadcast:{target}"
        db.commit()

        await safe_reply_text(query.message, f"Écrivez maintenant le message à envoyer à : {target}")
        return


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    db = db_session()
    tg_user = query.from_user
    user = get_or_create_user(db, tg_user)
    data = query.data

    try:
        if data.startswith("admin:"):
            await admin_callback(update, context, db, user, data)
        elif data.startswith("ad:"):
            await ad_callback(update, context, db, user, data)
        elif data.startswith("review:"):
            await review_callback(update, context, db, user, data)
        elif data.startswith("broadcast:"):
            await broadcast_callback(update, context, db, user, data)
        else:
            await user_flow_callback(update, context, db, user, data)
    finally:
        db.close()


async def get_broadcast_targets(db, target):
    if target == "all":
        apps = db.query(Application).filter(Application.status == "accepted").all()
        return list({app.telegram_id for app in apps})

    if target in ["creator", "bought", "vip"]:
        apps = (
            db.query(Application)
            .filter(Application.status == "accepted")
            .filter(Application.category == target)
            .all()
        )
        return list({app.telegram_id for app in apps})

    if target == "unfinished":
        users = (
            db.query(User)
            .filter(User.completed == False)
            .filter(User.blocked == False)
            .filter(User.state.in_(UNFINISHED_STATES))
            .all()
        )
        return list({u.telegram_id for u in users})

    if target == "blocked":
        users = db.query(User).filter(User.blocked == True).all()
        return list({u.telegram_id for u in users})

    return []


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)
    text = update.message.text.strip()

    try:
        if is_admin(tg_user.id) and user.state.startswith("admin_waiting_refusal_reason:"):
            target_id = int(user.state.split(":")[1])
            target = db.query(User).filter(User.telegram_id == target_id).first()
            app = (
                db.query(Application)
                .filter(Application.telegram_id == target_id)
                .order_by(Application.id.desc())
                .first()
            )

            if not target or not app:
                await safe_reply_text(update.message, "Demande introuvable.", reply_markup=back_admin_keyboard())
                return

            if app.status != "pending":
                user.state = "new"
                db.commit()
                await safe_reply_text(update.message, "⚠️ Décision déjà prise par un autre admin.", reply_markup=back_admin_keyboard())
                return

            ok = await reject_application(context, db, target, app, tg_user.id, text)
            user.state = "new"
            db.commit()

            if ok:
                await safe_reply_text(update.message, "Refus envoyé avec motif.", reply_markup=back_admin_keyboard())
            else:
                await safe_reply_text(update.message, "⚠️ Décision déjà prise par un autre admin.", reply_markup=back_admin_keyboard())

            return

        if is_admin(tg_user.id) and user.state == "admin_waiting_ad_caption":
            ad = (
                db.query(Advertisement)
                .filter(Advertisement.created_by == tg_user.id)
                .filter(Advertisement.caption == "__DRAFT__")
                .order_by(Advertisement.id.desc())
                .first()
            )

            if not ad:
                await safe_reply_text(update.message, "Brouillon de publicité introuvable.", reply_markup=ad_menu_keyboard())
                return

            ad.caption = text
            user.state = "new"
            db.commit()

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Publier dans un groupe", callback_data="ad:publish")],
                [InlineKeyboardButton("📢 Menu publicités", callback_data="admin:ads")]
            ])

            sent = await safe_reply_photo(
                update.message,
                photo=ad.image_file_id,
                caption=f"Prévisualisation :\n\n{text}",
                reply_markup=keyboard
            )

            if not sent:
                await safe_reply_text(update.message, f"Prévisualisation :\n\n{text}", reply_markup=keyboard)

            return

        if is_admin(tg_user.id) and user.state.startswith("admin_waiting_broadcast:"):
            target = user.state.split(":")[1]
            target_ids = await get_broadcast_targets(db, target)

            sent, failed = 0, 0

            for telegram_id in target_ids:
                result = await safe_send_message(context.bot, telegram_id, text)
                if result:
                    sent += 1
                else:
                    failed += 1

            db.add(Broadcast(
                created_by=tg_user.id,
                target_category=target,
                message=text,
                sent_count=sent,
                failed_count=failed
            ))

            user.state = "new"
            db.commit()

            await safe_reply_text(
                update.message,
                f"📣 Broadcast terminé.\n\nEnvoyés : {sent}\nÉchecs : {failed}",
                reply_markup=back_admin_keyboard()
            )
            return

        if get_pending_application(db, user.telegram_id):
            await send_and_remember(
                update, context, db,
                "⏳ Votre demande est déjà en attente de validation."
            )
            return

        if user.state == "creator_details":
            db.add(Application(
                telegram_id=user.telegram_id,
                username=user.username,
                category="creator",
                creator_name=text,
                status="draft"
            ))

            user.state = "waiting_proof"
            db.commit()

            await send_and_remember(
                update,
                context,
                db,
                "Parfait. Envoyez maintenant une preuve en photo ou vidéo.\n\n"
                "⚠️ Votre demande sera examinée automatiquement par nos algorithmes, "
                "notre IA, nos bases de données et les comparaisons effectuées sur internet.\n\n"
                "Tout média non conforme sera refusé."
            )
            return

        if user.state == "bought_name":
            db.add(Application(
                telegram_id=user.telegram_id,
                username=user.username,
                category="bought",
                creator_name=text,
                status="draft"
            ))

            user.state = "waiting_proof"
            db.commit()

            await send_and_remember(
                update,
                context,
                db,
                "Parfait. Envoyez maintenant une preuve en photo ou vidéo.\n\n"
                "⚠️ Votre demande sera examinée automatiquement par nos algorithmes, "
                "notre IA, nos bases de données et les comparaisons effectuées sur internet.\n\n"
                "Tout média non conforme sera refusé."
            )
            return

    finally:
        db.close()


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    tg_user = update.effective_user
    user = get_or_create_user(db, tg_user)

    try:
        if is_admin(tg_user.id) and user.state == "admin_waiting_ad_image":
            if not update.message.photo:
                await safe_reply_text(update.message, "Envoyez une image/photo.")
                return

            file_id = update.message.photo[-1].file_id

            db.add(Advertisement(
                created_by=tg_user.id,
                image_file_id=file_id,
                caption="__DRAFT__"
            ))

            user.state = "admin_waiting_ad_caption"
            db.commit()

            await safe_reply_text(update.message, "Image reçue. Envoyez maintenant le texte de la publicité.")
            return

        if user.state != "waiting_proof":
            return

        existing_pending = get_pending_application(db, user.telegram_id)
        if existing_pending:
            await send_and_remember(
                update, context, db,
                "⏳ Votre demande est déjà en attente de validation."
            )
            return

        file_id, proof_type = None, None

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            proof_type = "photo"
        elif update.message.video:
            file_id = update.message.video.file_id
            proof_type = "video"

        if not file_id:
            await send_and_remember(update, context, db, "Veuillez envoyer une photo ou une vidéo.")
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
                status="draft"
            )
            db.add(app)

        app.proof_file_id = file_id
        app.proof_type = proof_type
        app.status = "pending"

        user.state = "pending"
        db.commit()

        caption = (
            "⏳ Nouvelle demande à valider\n\n"
            f"Utilisateur : @{user.username or user.telegram_id}\n"
            f"ID : {user.telegram_id}\n"
            f"Catégorie : {user.category}\n"
            f"Détails : {app.creator_name or 'Non renseigné'}\n"
            f"Preuve : {proof_type}\n"
            f"Refus précédents : {user.rejected_count}"
        )

        for admin_id in ADMIN_IDS:
            if proof_type == "photo":
                await safe_send_photo(
                    context.bot,
                    chat_id=admin_id,
                    photo=file_id,
                    caption=caption,
                    reply_markup=application_review_keyboard(user.telegram_id)
                )
            else:
                await safe_send_video(
                    context.bot,
                    chat_id=admin_id,
                    video=file_id,
                    caption=caption,
                    reply_markup=application_review_keyboard(user.telegram_id)
                )

        await send_and_remember(
            update, context, db,
            "Nos bots utilisent l’IA, nos bases de données et des bases de données publiques, "
            "pour vérifier si vos médias n’ont pas déjà été publiés sur le web."
        )

    finally:
        db.close()


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await safe_reply_text(update.message, "Commande réservée aux admins.")
        return

    await safe_reply_text(update.message, "👑 Panel Admin", reply_markup=admin_main_keyboard())


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if not chat or chat.type not in ["group", "supergroup", "channel"]:
        return

    db = db_session()

    try:
        status = update.my_chat_member.new_chat_member.status
        active = status in ["member", "administrator"]

        group = db.query(Group).filter(Group.chat_id == chat.id).first()

        if not group:
            group = Group(
                chat_id=chat.id,
                title=chat.title,
                username=chat.username,
                active=active
            )
            db.add(group)
        else:
            group.title = chat.title
            group.username = chat.username
            group.active = active

        db.commit()
    finally:
        db.close()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Empêche Railway de spammer des erreurs non gérées.
    error = context.error
    if isinstance(error, (Forbidden, BadRequest)):
        return
    print(f"Erreur non gérée : {error}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant.")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("Bot V4 lancé.")
    app.run_polling()


if __name__ == "__main__":
    main()
