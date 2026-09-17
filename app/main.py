from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import load_config
from .db import Database
from .keyboards import (
    access_choice_kb,
    admin_panel_kb,
    appeal_decision_kb,
    appeal_kb,
    application_decision_kb,
    author_confirmation_kb,
    back_admin_kb,
    broadcast_categories_kb,
    broadcast_confirm_kb,
    content_menu_kb,
    group_actions_kb,
    groups_menu_kb,
    ineligible_kb,
    moderation_menu_kb,
    not_interested_kb,
    payment_accept_kb,
    payment_decision_kb,
    payment_rejected_kb,
    payments_menu_kb,
    premium_info_kb,
    quota_confirmation_kb,
    rejected_application_kb,
    request_new_link_kb,
    resume_kb,
    rules_kb,
    settings_menu_kb,
    start_kb,
    url_kb,
)
from . import texts
from .utils import contains_external_reference, next_progress_milestone, parse_money, parse_positive_int, truncate


config = load_config()
db = Database(config.database_url, config.db_pool_min, config.db_pool_max)
bot = Bot(config.bot_token)
dp = Dispatcher(disable_fsm=True)
router = Router()
dp.include_router(router)

PARIS = ZoneInfo("Europe/Paris")

LOCKED_ACCESS_STATUSES = {
    "application_pending",
    "rules_waiting",
    "free_invite",
    "appeal_invite",
    "temporary_member",
    "member_validated",
    "payment_pending",
    "premium_rules",
    "premium_invite",
    "premium_member",
    "premium_left",
    "failure_processing",
}

FLOW_LABELS = {
    "feedback": "Laisser un avis",
    "free_count": "Déclaration du nombre de médias",
    "free_quota_confirm": "Confirmation du quota",
    "free_gallery": "Capture de galerie",
    "free_sample": "Média de vérification",
    "payment_proof": "Preuve de paiement",
    "appeal_text": "Motif du réexamen",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_datetime(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.astimezone(PARIS).strftime("%d/%m/%Y à %H:%M")


def is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


def access_is_locked(row) -> bool:
    return bool(row and (row["banned"] or row["status"] in LOCKED_ACCESS_STATUSES))


def json_object(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def ensure_user(user, source: str | None = None):
    return await db.fetchrow(
        """
        INSERT INTO users(telegram_id,username,first_name,ad_source)
        VALUES($1,$2,$3,$4)
        ON CONFLICT(telegram_id) DO UPDATE SET
          username=EXCLUDED.username,
          first_name=EXCLUDED.first_name,
          ad_source=COALESCE(users.ad_source, EXCLUDED.ad_source),
          updated_at=now()
        RETURNING *
        """,
        user.id,
        user.username,
        user.first_name,
        source,
    )


async def get_user(user_id: int):
    return await db.fetchrow("SELECT * FROM users WHERE telegram_id=$1", user_id)


async def set_user_flow(
    user_id: int,
    flow_state: str | None,
    data: dict | None = None,
    *,
    status: str | None = None,
    replace_data: bool = False,
) -> None:
    row = await get_user(user_id)
    current = {} if replace_data or not row else json_object(row["flow_data"])
    if data:
        current.update(data)
    await db.execute(
        """
        UPDATE users SET
          flow_state=$2,
          flow_data=$3::jsonb,
          status=COALESCE($4,status),
          abandonment_state=NULL,
          updated_at=now()
        WHERE telegram_id=$1
        """,
        user_id,
        flow_state,
        json.dumps(current, ensure_ascii=False),
        status,
    )


async def clear_user_flow(user_id: int, *, status: str | None = None) -> None:
    await db.execute(
        """
        UPDATE users SET flow_state=NULL,flow_data='{}'::jsonb,
          status=COALESCE($2,status),abandonment_state=NULL,updated_at=now()
        WHERE telegram_id=$1
        """,
        user_id,
        status,
    )


async def set_admin_session(admin_id: int, state: str | None, data: dict | None = None) -> None:
    await db.execute(
        """
        INSERT INTO admin_sessions(admin_id,state,data,updated_at)
        VALUES($1,$2,$3::jsonb,now())
        ON CONFLICT(admin_id) DO UPDATE SET state=EXCLUDED.state,data=EXCLUDED.data,updated_at=now()
        """,
        admin_id,
        state,
        json.dumps(data or {}, ensure_ascii=False),
    )


async def get_admin_session(admin_id: int):
    return await db.fetchrow("SELECT state,data FROM admin_sessions WHERE admin_id=$1", admin_id)


async def clear_admin_session(admin_id: int) -> None:
    await db.execute("DELETE FROM admin_sessions WHERE admin_id=$1", admin_id)


async def notify_admins(message: str, reply_markup=None) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, message, reply_markup=reply_markup)
        except Exception as exc:
            await db.log(
                "notify_admin_failed",
                telegram_id=admin_id,
                data={"error": str(exc)},
                level="warning",
            )


async def safe_send(user_id: int, message: str, reply_markup=None) -> bool:
    try:
        await bot.send_message(user_id, message, reply_markup=reply_markup)
        return True
    except Exception as exc:
        await db.log("private_send_failed", telegram_id=user_id, data={"error": str(exc)}, level="warning")
        return False


async def send_media_message(
    chat_id: int,
    text: str,
    reply_markup=None,
    *,
    media_file_id: str = "",
    media_type: str = "",
):
    if media_file_id and media_type in {"photo", "video"}:
        if len(text) <= 1024:
            if media_type == "photo":
                sent = await bot.send_photo(chat_id, media_file_id, caption=text, reply_markup=reply_markup)
            else:
                sent = await bot.send_video(chat_id, media_file_id, caption=text, reply_markup=reply_markup)
            return sent, None
        if media_type == "photo":
            media_message = await bot.send_photo(chat_id, media_file_id)
        else:
            media_message = await bot.send_video(chat_id, media_file_id)
        text_message = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return text_message, media_message
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    return sent, None


async def configured_message(chat_id: int, kind: str, reply_markup=None):
    if kind == "ad":
        text = await db.get_setting("ad_text", texts.DEFAULT_AD_TEXT)
    else:
        text = await db.get_setting("welcome_text", texts.DEFAULT_WELCOME_TEXT)
    file_id = await db.get_setting(f"{kind}_media_file_id", "")
    media_type = await db.get_setting(f"{kind}_media_type", "")
    return await send_media_message(
        chat_id,
        text,
        reply_markup,
        media_file_id=file_id,
        media_type=media_type,
    )


async def replace_callback_message(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        if callback.message and callback.message.text:
            await callback.message.edit_text(text, reply_markup=reply_markup)
            return
        if callback.message:
            await callback.message.delete()
    except TelegramBadRequest:
        pass
    if callback.message:
        await bot.send_message(callback.message.chat.id, text, reply_markup=reply_markup)


async def delete_callback_message(callback: CallbackQuery) -> None:
    try:
        if callback.message:
            await callback.message.delete()
    except Exception:
        pass


async def show_home(chat_id: int) -> None:
    await configured_message(chat_id, "welcome", start_kb())


async def show_access_choice(chat_id: int, user_id: int) -> None:
    price = await db.get_setting("premium_price", "30 €")
    await db.event("continued", telegram_id=user_id)
    await bot.send_message(chat_id, texts.access_choice(price), reply_markup=access_choice_kb(price))


async def send_gallery_prompt(chat_id: int) -> None:
    example_file_id = await db.get_setting("gallery_example_file_id", "")
    if example_file_id:
        await bot.send_photo(chat_id, example_file_id, caption=texts.GALLERY_PROMPT)
    else:
        await bot.send_message(chat_id, texts.GALLERY_PROMPT)


async def register_group(chat) -> None:
    if getattr(chat, "type", None) not in {"group", "supergroup"}:
        return
    await db.execute(
        """
        INSERT INTO groups(chat_id,title,type,active,targeted)
        VALUES($1,$2,'detected',true,false)
        ON CONFLICT(chat_id) DO UPDATE SET title=EXCLUDED.title,active=true,updated_at=now()
        """,
        chat.id,
        chat.title or "",
    )


async def main_group_id() -> int | None:
    raw = await db.get_setting("main_group", "")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def schedule_delete(chat_id: int, message_id: int, seconds: int) -> None:
    await db.execute(
        """
        INSERT INTO scheduled_deletions(chat_id,message_id,delete_at)
        VALUES($1,$2,now()+($3 * interval '1 second'))
        ON CONFLICT(chat_id,message_id) DO UPDATE SET delete_at=EXCLUDED.delete_at,attempts=0
        """,
        chat_id,
        message_id,
        seconds,
    )


async def revoke_active_invites(user_id: int) -> None:
    rows = await db.fetch(
        "SELECT id,chat_id,invite_link FROM invite_links WHERE telegram_id=$1 AND status='active'",
        user_id,
    )
    for row in rows:
        try:
            await bot.revoke_chat_invite_link(int(row["chat_id"]), row["invite_link"])
        except Exception:
            pass
        await db.execute(
            "UPDATE invite_links SET status='revoked',revoked_at=now() WHERE id=$1",
            row["id"],
        )


async def revoke_chat_invites(chat_id: int) -> None:
    rows = await db.fetch(
        """
        SELECT id,telegram_id,invite_link FROM invite_links
        WHERE chat_id=$1 AND status='active'
        """,
        chat_id,
    )
    for row in rows:
        try:
            await bot.revoke_chat_invite_link(chat_id, row["invite_link"])
        except Exception:
            pass
        await db.execute(
            "UPDATE invite_links SET status='revoked',revoked_at=now() WHERE id=$1",
            row["id"],
        )
        if row["telegram_id"]:
            await safe_send(
                int(row["telegram_id"]),
                texts.INVITE_EXPIRED,
                request_new_link_kb(),
            )


async def create_personal_invite(user_id: int, access_kind: str, hours: int) -> str:
    chat_id = await main_group_id()
    if not chat_id:
        raise RuntimeError("Le groupe principal n’est pas configuré")
    await revoke_active_invites(user_id)
    expires_at = utcnow() + timedelta(hours=hours)
    invite = await bot.create_chat_invite_link(
        chat_id,
        name=f"{access_kind}-{user_id}"[:32],
        expire_date=expires_at,
        creates_join_request=True,
    )
    await db.execute(
        """
        INSERT INTO invite_links(
          telegram_id,chat_id,invite_link,expected_user_id,access_kind,status,expires_at
        ) VALUES($1,$2,$3,$1,$4,'active',$5)
        """,
        user_id,
        chat_id,
        invite.invite_link,
        access_kind,
        expires_at,
    )
    await db.event("invite_created", telegram_id=user_id, data={"kind": access_kind, "hours": hours})
    return invite.invite_link


async def active_invite(user_id: int):
    return await db.fetchrow(
        """
        SELECT invite_link,access_kind,expires_at FROM invite_links
        WHERE telegram_id=$1 AND status='active' AND expires_at>now()
        ORDER BY created_at DESC LIMIT 1
        """,
        user_id,
    )


async def ban_from_chat(chat_id: int, user_id: int, event: str) -> None:
    try:
        await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
        await db.log(event, telegram_id=user_id, chat_id=chat_id)
    except Exception as exc:
        await db.log(
            f"{event}_failed",
            telegram_id=user_id,
            chat_id=chat_id,
            data={"error": str(exc)},
            level="error",
        )


async def ban_from_publicity_groups(user_id: int, reason: str) -> None:
    rows = await db.fetch("SELECT chat_id,title FROM groups WHERE type='pub' AND active=true")
    failures: list[str] = []
    for row in rows:
        try:
            member = await bot.get_chat_member(int(row["chat_id"]), user_id)
            if member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}:
                failures.append(f"{row['title'] or row['chat_id']}: propriétaire/admin")
                continue
        except Exception:
            pass
        try:
            await bot.ban_chat_member(int(row["chat_id"]), user_id, revoke_messages=False)
        except Exception as exc:
            failures.append(f"{row['title'] or row['chat_id']}: {exc}")
    await db.log(reason, telegram_id=user_id, data={"pub_failures": failures})
    if failures:
        await notify_admins(
            f"⚠️ Bannissement partiel pour {user_id}\n\n" + "\n".join(failures[:10])
        )


async def apply_ban_side_effects(user_id: int, status: str, reason: str, *, include_main: bool) -> None:
    if include_main:
        main = await main_group_id()
        if main:
            await ban_from_chat(main, user_id, f"main_{reason}")
    await ban_from_publicity_groups(user_id, reason)
    await db.event(status, telegram_id=user_id)


async def mark_banned(user_id: int, status: str, reason: str, *, include_main: bool) -> None:
    await db.execute(
        """
        UPDATE users SET banned=true,status=$2,flow_state=NULL,flow_data='{}'::jsonb,
          appeal_available=$3,updated_at=now() WHERE telegram_id=$1
        """,
        user_id,
        status,
        status in {"failed_no_activity", "failed_quota"},
    )
    await apply_ban_side_effects(user_id, status, reason, include_main=include_main)


async def unban_configured_groups(user_id: int) -> None:
    rows = await db.fetch("SELECT chat_id FROM groups WHERE active=true AND type IN ('main','pub')")
    for row in rows:
        try:
            await bot.unban_chat_member(int(row["chat_id"]), user_id, only_if_banned=True)
        except Exception as exc:
            await db.log(
                "unban_failed",
                telegram_id=user_id,
                chat_id=int(row["chat_id"]),
                data={"error": str(exc)},
                level="warning",
            )


class BannedCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data):
        user = event.from_user
        if user and not is_admin(user.id):
            row = await get_user(user.id)
            allowed = event.data in {"appeal:start", "invite:request_new", "start:home"}
            if row and row["banned"] and not allowed:
                await event.answer("Accès bloqué.", show_alert=True)
                return None
        return await handler(event, data)


router.callback_query.middleware(BannedCallbackMiddleware())


async def resume_user(chat_id: int, row) -> None:
    user_id = int(row["telegram_id"])
    state = row["flow_state"]
    status = row["status"]
    price = await db.get_setting("premium_price", "30 €")

    if row["banned"]:
        markup = appeal_kb() if row["appeal_available"] else None
        await bot.send_message(chat_id, texts.BLOCKED_ACCOUNT, reply_markup=markup)
        return
    if status == "premium_left":
        await bot.send_message(chat_id, texts.PREMIUM_LEFT, reply_markup=request_new_link_kb())
        return
    if status in {"member_validated", "premium_member", "temporary_member"}:
        await bot.send_message(chat_id, texts.ALREADY_MEMBER)
        return
    if status == "application_pending":
        await bot.send_message(chat_id, texts.APPLICATION_PENDING)
        return
    if status == "payment_pending":
        await bot.send_message(chat_id, texts.PAYMENT_PENDING)
        return
    if status == "rules_waiting":
        await bot.send_message(chat_id, texts.rules_text(int(row["declared_total"] or 0)), reply_markup=rules_kb())
        return
    if status == "premium_rules":
        await bot.send_message(chat_id, texts.PAYMENT_ACCEPTED, reply_markup=payment_accept_kb())
        return
    if status in {"free_invite", "premium_invite", "appeal_invite"}:
        invite = await active_invite(user_id)
        if invite:
            if invite["access_kind"] == "premium":
                body = texts.PREMIUM_INVITE_READY
            else:
                body = texts.free_invite_ready(int(row["declared_total"] or 0))
            await bot.send_message(chat_id, body, reply_markup=url_kb("🔗 Demander à rejoindre le groupe", invite["invite_link"]))
            return
        await bot.send_message(chat_id, texts.INVITE_EXPIRED, reply_markup=request_new_link_kb())
        return
    if status == "attempts_exhausted":
        await bot.send_message(
            chat_id,
            texts.attempts_exhausted(price),
            reply_markup=rejected_application_kb(price, False),
        )
        return
    if state in FLOW_LABELS:
        await bot.send_message(chat_id, texts.resume_flow(FLOW_LABELS[state]), reply_markup=resume_kb())
        return
    await show_home(chat_id)


async def send_current_flow_step(chat_id: int, row) -> bool:
    state = row["flow_state"]
    data = json_object(row["flow_data"])
    if state == "feedback":
        await bot.send_message(chat_id, texts.FEEDBACK_PROMPT)
    elif state == "free_count":
        await bot.send_message(chat_id, texts.MEDIA_COUNT_PROMPT)
    elif state == "free_quota_confirm":
        quota = int(data.get("quota") or row["declared_total"] or 0)
        await bot.send_message(chat_id, texts.quota_confirmation(quota), reply_markup=quota_confirmation_kb(quota))
    elif state == "free_gallery":
        await send_gallery_prompt(chat_id)
    elif state == "free_sample":
        await bot.send_message(chat_id, texts.SAMPLE_PROMPT)
    elif state == "payment_proof":
        await bot.send_message(chat_id, texts.PAYMENT_PROOF_PROMPT)
    elif state == "appeal_text":
        await bot.send_message(chat_id, texts.APPEAL_PROMPT)
    else:
        return False
    return True


@router.message(Command("start"), F.chat.type == "private")
async def start_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    source = parts[1].strip() if len(parts) > 1 else None
    row = await ensure_user(message.from_user, source)
    if source and source.startswith("ad"):
        await db.event("ad_start", telegram_id=message.from_user.id, source=source)
    if is_admin(message.from_user.id):
        await clear_admin_session(message.from_user.id)
        await bot.send_message(message.chat.id, "Panneau administrateur\n\nChoisissez une section.", reply_markup=admin_panel_kb())
        return
    await resume_user(message.chat.id, row)


@router.message(Command("admin"), F.chat.type == "private")
async def admin_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await clear_admin_session(message.from_user.id)
    await bot.send_message(message.chat.id, "Panneau administrateur\n\nChoisissez une section.", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "start:home")
async def start_home(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await delete_callback_message(callback)
        await resume_user(callback.message.chat.id, row)
        await callback.answer()
        return
    await delete_callback_message(callback)
    await show_home(callback.message.chat.id)
    await callback.answer()


@router.callback_query(F.data == "start:continue")
async def start_continue(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await delete_callback_message(callback)
        await resume_user(callback.message.chat.id, row)
        await callback.answer()
        return
    await delete_callback_message(callback)
    await show_access_choice(callback.message.chat.id, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "start:not_interested")
async def start_not_interested(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await callback.answer("Votre situation actuelle ne permet pas cette action.", show_alert=True)
        return
    await clear_user_flow(callback.from_user.id, status="not_interested")
    await replace_callback_message(callback, texts.NOT_INTERESTED, not_interested_kb())
    await db.event("not_interested", telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "flow:resume")
async def flow_resume(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    await delete_callback_message(callback)
    if not await send_current_flow_step(callback.message.chat.id, row):
        await resume_user(callback.message.chat.id, row)
    await callback.answer()


@router.callback_query(F.data == "feedback:start")
async def feedback_start(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await callback.answer("Votre situation actuelle ne permet pas cette action.", show_alert=True)
        return
    if row["feedback_at"]:
        await callback.answer("Un avis a déjà été envoyé.", show_alert=True)
        return
    await set_user_flow(callback.from_user.id, "feedback", status="feedback_waiting")
    await replace_callback_message(callback, texts.FEEDBACK_PROMPT)
    await callback.answer()


@router.callback_query(F.data == "free:start")
async def free_start(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await callback.answer("Votre situation actuelle ne permet pas cette action.", show_alert=True)
        return
    if int(row["attempts"] or 0) >= 2:
        price = await db.get_setting("premium_price", "30 €")
        await clear_user_flow(callback.from_user.id, status="attempts_exhausted")
        await replace_callback_message(callback, texts.attempts_exhausted(price), rejected_application_kb(price, False))
        await callback.answer()
        return
    await clear_user_flow(callback.from_user.id, status="author_confirmation")
    await replace_callback_message(callback, texts.AUTHOR_CONFIRMATION, author_confirmation_kb())
    await db.event("free_selected", telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "free:ineligible")
async def free_ineligible(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if row["status"] != "author_confirmation":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    price = await db.get_setting("premium_price", "30 €")
    await clear_user_flow(callback.from_user.id, status="free_ineligible")
    await replace_callback_message(callback, texts.free_ineligible(price), ineligible_kb(price))
    await db.event("free_ineligible", telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "free:author_confirm")
async def free_author_confirm(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if row["status"] != "author_confirmation":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    await set_user_flow(callback.from_user.id, "free_count", {}, status="free_count", replace_data=True)
    await replace_callback_message(callback, texts.MEDIA_COUNT_PROMPT)
    await callback.answer()


@router.callback_query(F.data == "free:quota_edit")
async def free_quota_edit(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row or row["flow_state"] != "free_quota_confirm":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    await set_user_flow(callback.from_user.id, "free_count", status="free_count")
    await replace_callback_message(callback, texts.MEDIA_COUNT_PROMPT)
    await callback.answer()


@router.callback_query(F.data == "free:quota_confirm")
async def free_quota_confirm(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row or row["flow_state"] != "free_quota_confirm":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    data = json_object(row["flow_data"])
    quota = int(data.get("quota") or row["declared_total"] or 0)
    await db.execute("UPDATE users SET declared_total=$2 WHERE telegram_id=$1", callback.from_user.id, quota)
    await set_user_flow(callback.from_user.id, "free_gallery", {"quota": quota}, status="free_gallery")
    await delete_callback_message(callback)
    await send_gallery_prompt(callback.message.chat.id)
    await callback.answer()


@router.callback_query(F.data == "free:rules_accept")
async def free_rules_accept(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row or row["status"] != "rules_waiting":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    try:
        invite = await create_personal_invite(callback.from_user.id, "free", 24)
    except Exception as exc:
        await db.log("free_invite_failed", telegram_id=callback.from_user.id, data={"error": str(exc)}, level="error")
        await callback.answer("Le lien n’a pas pu être créé. Un administrateur a été prévenu.", show_alert=True)
        await notify_admins(f"❌ Création du lien gratuit impossible pour {callback.from_user.id}\n\n{exc}")
        return
    await clear_user_flow(callback.from_user.id, status="free_invite")
    await replace_callback_message(
        callback,
        texts.free_invite_ready(int(row["declared_total"] or 0)),
        url_kb("🔗 Demander à rejoindre le groupe", invite),
    )
    await callback.answer()


async def send_application_to_admins(application_id: int, user, quota: int, gallery_file_id: str, sample_type: str, sample_file_id: str, attempt: int) -> None:
    card = (
        "📥 Nouvelle candidature auteur/producteur\n\n"
        f"Utilisateur : @{user.username or '-'}\n"
        f"Identifiant : {user.id}\n"
        f"Nom : {user.first_name or '-'}\n"
        f"Quota déclaré : {quota} médias\n"
        f"Tentative : {attempt}/2\n\n"
        "Deux éléments vont suivre : capture de galerie et média réel de vérification."
    )
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, card)
            await bot.send_photo(admin_id, gallery_file_id, caption="1/2 — Capture de galerie")
            markup = application_decision_kb(application_id)
            if sample_type == "photo":
                await bot.send_photo(admin_id, sample_file_id, caption="2/2 — Média réel de vérification", reply_markup=markup)
            else:
                await bot.send_video(admin_id, sample_file_id, caption="2/2 — Média réel de vérification", reply_markup=markup)
        except Exception as exc:
            await db.log(
                "application_admin_delivery_failed",
                telegram_id=user.id,
                data={"admin_id": admin_id, "application_id": application_id, "error": str(exc)},
                level="error",
            )


async def send_payment_to_admins(payment_id: int, user, price: str, proof_type: str, file_id: str) -> None:
    caption = (
        "💎 Nouvelle preuve de paiement Premium\n\n"
        f"Utilisateur : @{user.username or '-'}\n"
        f"Identifiant : {user.id}\n"
        f"Montant attendu : {price}\n"
        f"Paiement : #{payment_id}"
    )
    for admin_id in config.admin_ids:
        try:
            markup = payment_decision_kb(payment_id)
            if proof_type == "photo":
                await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(admin_id, file_id, caption=caption, reply_markup=markup)
        except Exception as exc:
            await db.log(
                "payment_admin_delivery_failed",
                telegram_id=user.id,
                data={"admin_id": admin_id, "payment_id": payment_id, "error": str(exc)},
                level="error",
            )


async def handle_user_private_message(message: Message, row) -> None:
    state = row["flow_state"]
    user_id = message.from_user.id
    data = json_object(row["flow_data"])

    if row["banned"] and state != "appeal_text":
        markup = appeal_kb() if row["appeal_available"] else None
        await message.answer(texts.BLOCKED_ACCOUNT, reply_markup=markup)
        return

    if state == "feedback":
        value = truncate(message.text or message.caption, 500)
        if not value:
            await message.answer("Merci d’envoyer un message texte.")
            return
        await db.execute(
            "UPDATE users SET feedback_text=$2,feedback_at=now(),updated_at=now() WHERE telegram_id=$1",
            user_id,
            value,
        )
        await clear_user_flow(user_id, status="not_interested_feedback_sent")
        await db.event("feedback_sent", telegram_id=user_id)
        await message.answer(texts.FEEDBACK_RECEIVED)
        return

    if state == "free_count":
        try:
            maximum = int(await db.get_setting("max_declared_total", "100"))
        except ValueError:
            maximum = 100
        maximum = max(1, min(100, maximum))
        value, error = parse_positive_int(message.text or "", maximum)
        if error == "not_number":
            await message.answer(texts.COUNT_NOT_NUMBER)
            return
        if error == "too_small":
            await message.answer(texts.COUNT_TOO_SMALL)
            return
        if error == "too_large":
            await message.answer(texts.count_too_large(maximum))
            return
        await db.execute("UPDATE users SET declared_total=$2,updated_at=now() WHERE telegram_id=$1", user_id, value)
        await set_user_flow(user_id, "free_quota_confirm", {"quota": value}, status="free_quota_confirm", replace_data=True)
        await message.answer(texts.quota_confirmation(value), reply_markup=quota_confirmation_kb(value))
        return

    if state == "free_gallery":
        if not message.photo or message.media_group_id:
            await message.answer(texts.GALLERY_INVALID)
            return
        photo = message.photo[-1]
        data.update({"gallery_file_id": photo.file_id, "gallery_unique_id": photo.file_unique_id})
        await set_user_flow(user_id, "free_sample", data, status="free_sample", replace_data=True)
        await db.event("gallery_received", telegram_id=user_id)
        await message.answer(texts.GALLERY_RECEIVED)
        await message.answer(texts.SAMPLE_PROMPT)
        return

    if state == "free_sample":
        if message.media_group_id:
            await message.answer(texts.SAMPLE_INVALID)
            return
        sample_type = None
        sample_file_id = None
        sample_unique_id = None
        if message.photo:
            sample_type = "photo"
            sample_file_id = message.photo[-1].file_id
            sample_unique_id = message.photo[-1].file_unique_id
        elif message.video:
            sample_type = "video"
            sample_file_id = message.video.file_id
            sample_unique_id = message.video.file_unique_id
        if not sample_type:
            await message.answer(texts.SAMPLE_INVALID)
            return
        gallery_file_id = data.get("gallery_file_id")
        if not gallery_file_id:
            await set_user_flow(user_id, "free_gallery", {}, status="free_gallery", replace_data=True)
            await send_gallery_prompt(message.chat.id)
            return
        async with db.transaction() as connection:
            locked = await connection.fetchrow("SELECT * FROM users WHERE telegram_id=$1 FOR UPDATE", user_id)
            if not locked or locked["flow_state"] != "free_sample":
                await message.answer(texts.SAMPLE_ALREADY_RECEIVED)
                return
            attempt = int(locked["attempts"] or 0) + 1
            application_id = await connection.fetchval(
                """
                INSERT INTO applications(
                  telegram_id,status,gallery_file_id,gallery_unique_id,
                  sample_file_id,sample_unique_id,sample_type,attempt_number
                ) VALUES($1,'pending',$2,$3,$4,$5,$6,$7) RETURNING id
                """,
                user_id,
                gallery_file_id,
                data.get("gallery_unique_id"),
                sample_file_id,
                sample_unique_id,
                sample_type,
                attempt,
            )
            await connection.execute(
                """
                UPDATE users SET attempts=$2,status='application_pending',flow_state=NULL,
                  flow_data='{}'::jsonb,updated_at=now() WHERE telegram_id=$1
                """,
                user_id,
                attempt,
            )
        await message.answer(texts.SAMPLE_RECEIVED)
        await message.answer(texts.application_complete(int(row["declared_total"] or data.get("quota") or 0)))
        await db.event("application_submitted", telegram_id=user_id, data={"application_id": application_id})
        await send_application_to_admins(
            application_id,
            message.from_user,
            int(row["declared_total"] or data.get("quota") or 0),
            gallery_file_id,
            sample_type,
            sample_file_id,
            attempt,
        )
        return

    if state == "payment_proof":
        proof_type = None
        file_id = None
        if message.photo:
            proof_type = "photo"
            file_id = message.photo[-1].file_id
        elif message.document:
            mime = (message.document.mime_type or "").lower()
            if mime.startswith("image/") or mime == "application/pdf":
                proof_type = "document"
                file_id = message.document.file_id
        if not file_id or message.media_group_id:
            await message.answer(texts.PAYMENT_PROOF_INVALID)
            return
        price = await db.get_setting("premium_price", "30 €")
        amount = parse_money(price)
        async with db.transaction() as connection:
            locked = await connection.fetchrow("SELECT flow_state FROM users WHERE telegram_id=$1 FOR UPDATE", user_id)
            if not locked or locked["flow_state"] != "payment_proof":
                await message.answer(texts.PAYMENT_PENDING)
                return
            payment_id = await connection.fetchval(
                """
                INSERT INTO payments(telegram_id,amount,status,proof_file_id,proof_type)
                VALUES($1,$2,'pending',$3,$4) RETURNING id
                """,
                user_id,
                amount,
                file_id,
                proof_type,
            )
            await connection.execute(
                "UPDATE users SET status='payment_pending',flow_state=NULL,flow_data='{}'::jsonb,updated_at=now() WHERE telegram_id=$1",
                user_id,
            )
        await message.answer(texts.payment_proof_received(price))
        await db.event("payment_proof_submitted", telegram_id=user_id, data={"payment_id": payment_id})
        await send_payment_to_admins(payment_id, message.from_user, price, proof_type, file_id)
        return

    if state == "appeal_text":
        value = truncate(message.text or message.caption, 500)
        if not value:
            await message.answer("Merci d’envoyer un message texte.")
            return
        failure_reason = str(data.get("failure_reason") or row["status"] or "blocage")
        async with db.transaction() as connection:
            locked = await connection.fetchrow("SELECT appeal_available FROM users WHERE telegram_id=$1 FOR UPDATE", user_id)
            if not locked or not locked["appeal_available"]:
                await message.answer("Aucun réexamen n’est disponible pour cet incident.")
                return
            appeal_id = await connection.fetchval(
                "INSERT INTO appeals(telegram_id,failure_reason,appeal_text,status) VALUES($1,$2,$3,'pending') RETURNING id",
                user_id,
                failure_reason,
                value,
            )
            await connection.execute(
                "UPDATE users SET flow_state=NULL,flow_data='{}'::jsonb,appeal_available=false,updated_at=now() WHERE telegram_id=$1",
                user_id,
            )
        await message.answer(texts.APPEAL_SENT)
        admin_text = (
            "🧾 Nouvelle demande de réexamen\n\n"
            f"Utilisateur : @{message.from_user.username or '-'}\n"
            f"Identifiant : {user_id}\n"
            f"Incident : {failure_reason}\n"
            f"Progression : {row['valid_media_count'] or 0}/{row['declared_total'] or 0}\n\n"
            "Motif envoyé par l’utilisateur :\n"
            f"{value}"
        )
        await notify_admins(admin_text, appeal_decision_kb(appeal_id))
        await db.event("appeal_submitted", telegram_id=user_id)
        return

    await message.answer("Utilisez /start pour afficher votre situation actuelle.")


@router.message(F.chat.type == "private")
async def private_messages(message: Message) -> None:
    if is_admin(message.from_user.id):
        if await handle_admin_private_message(message):
            return
    row = await ensure_user(message.from_user)
    await handle_user_private_message(message, row)


@router.callback_query(F.data.startswith("app:"))
async def application_decision(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Admin uniquement", show_alert=True)
        return
    _, action, raw_id = callback.data.split(":", 2)
    application_id = int(raw_id)
    application = await db.fetchrow("SELECT * FROM applications WHERE id=$1", application_id)
    if not application or application["status"] != "pending":
        await callback.answer("Cette demande a déjà été traitée.", show_alert=True)
        return
    user_id = int(application["telegram_id"])
    if action == "approve":
        async with db.transaction() as connection:
            decided = await connection.fetchrow(
                """
                UPDATE applications SET status='approved',admin_decision_by=$2,decision_at=now(),updated_at=now()
                WHERE id=$1 AND status='pending' RETURNING telegram_id
                """,
                application_id,
                callback.from_user.id,
            )
            if not decided:
                await callback.answer("Cette demande a déjà été traitée.", show_alert=True)
                return
            await connection.execute(
                "UPDATE users SET status='rules_waiting',flow_state=NULL,flow_data='{}'::jsonb,updated_at=now() WHERE telegram_id=$1",
                user_id,
            )
        user = await get_user(user_id)
        await safe_send(user_id, texts.rules_text(int(user["declared_total"] or 0)), rules_kb())
        await db.event("application_approved", telegram_id=user_id, data={"admin_id": callback.from_user.id})
        await delete_callback_message(callback)
        await callback.answer("Candidature prévalidée.", show_alert=True)
        return
    if action == "reject":
        await set_admin_session(
            callback.from_user.id,
            "application_reject_reason",
            {
                "application_id": application_id,
                "decision_chat_id": callback.message.chat.id,
                "decision_message_id": callback.message.message_id,
            },
        )
        await callback.message.answer("Envoyez le motif du refus. Ce texte sera transmis à l’utilisateur. Maximum : 500 caractères.")
        await callback.answer()
        return
    if action == "ban":
        updated = await db.fetchrow(
            """
            UPDATE applications SET status='banned',admin_decision_by=$2,decision_at=now(),updated_at=now()
            WHERE id=$1 AND status='pending' RETURNING telegram_id
            """,
            application_id,
            callback.from_user.id,
        )
        if not updated:
            await callback.answer("Cette demande a déjà été traitée.", show_alert=True)
            return
        await mark_banned(user_id, "admin_banned", "application_admin_ban", include_main=False)
        await safe_send(user_id, texts.ADMIN_BANNED)
        await delete_callback_message(callback)
        await callback.answer("Utilisateur banni.", show_alert=True)


@router.callback_query(F.data == "premium:start")
async def premium_start(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if access_is_locked(row):
        await callback.answer("Votre situation actuelle ne permet pas cette action.", show_alert=True)
        return
    price = await db.get_setting("premium_price", "30 €")
    paypal = await db.get_setting("paypal_link", "")
    usdt = await db.get_setting("usdt_address", "")
    enabled = bool(paypal or usdt)
    await clear_user_flow(callback.from_user.id, status="premium_interested")
    await replace_callback_message(
        callback,
        texts.premium_presentation(price, paypal or "non configuré", usdt or "non configuré") if enabled else texts.NO_PAYMENT_METHOD,
        premium_info_kb(enabled),
    )
    await db.event("premium_selected", telegram_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "premium:proof")
async def premium_proof(callback: CallbackQuery) -> None:
    row = await ensure_user(callback.from_user)
    if row["status"] not in {"premium_interested", "payment_rejected", "payment_proof"}:
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    paypal = await db.get_setting("paypal_link", "")
    usdt = await db.get_setting("usdt_address", "")
    if not paypal and not usdt:
        await callback.answer("Aucun moyen de paiement n’est configuré.", show_alert=True)
        return
    await set_user_flow(callback.from_user.id, "payment_proof", {}, status="payment_proof", replace_data=True)
    await replace_callback_message(callback, texts.PAYMENT_PROOF_PROMPT)
    await callback.answer()


@router.callback_query(F.data == "premium:rules_accept")
async def premium_rules_accept(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row or row["status"] != "premium_rules":
        await callback.answer("Cette étape a expiré.", show_alert=True)
        return
    try:
        invite = await create_personal_invite(callback.from_user.id, "premium", 48)
    except Exception as exc:
        await db.log("premium_invite_failed", telegram_id=callback.from_user.id, data={"error": str(exc)}, level="error")
        await notify_admins(f"❌ Création du lien Premium impossible pour {callback.from_user.id}\n\n{exc}")
        await callback.answer("Le lien n’a pas pu être créé. Un administrateur a été prévenu.", show_alert=True)
        return
    await clear_user_flow(callback.from_user.id, status="premium_invite")
    await replace_callback_message(
        callback,
        texts.PREMIUM_INVITE_READY,
        url_kb("🔗 Demander à rejoindre le groupe", invite),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay:"))
async def payment_decision(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Admin uniquement", show_alert=True)
        return
    _, action, raw_id = callback.data.split(":", 2)
    payment_id = int(raw_id)
    payment = await db.fetchrow("SELECT * FROM payments WHERE id=$1", payment_id)
    if not payment or payment["status"] != "pending":
        await callback.answer("Ce paiement a déjà été traité.", show_alert=True)
        return
    user_id = int(payment["telegram_id"])
    if action == "approve":
        async with db.transaction() as connection:
            updated = await connection.fetchrow(
                """
                UPDATE payments SET status='validated',admin_decision_by=$2,decided_at=now()
                WHERE id=$1 AND status='pending' RETURNING amount,telegram_id
                """,
                payment_id,
                callback.from_user.id,
            )
            if not updated:
                await callback.answer("Ce paiement a déjà été traité.", show_alert=True)
                return
            amount = Decimal(updated["amount"] or 0)
            if amount > 0:
                await connection.execute(
                    "INSERT INTO pot_transactions(amount,reason,created_by) VALUES($1,$2,$3)",
                    amount,
                    f"premium_payment_{payment_id}",
                    callback.from_user.id,
                )
            await connection.execute(
                "UPDATE users SET status='premium_rules',flow_state=NULL,flow_data='{}'::jsonb,banned=false,updated_at=now() WHERE telegram_id=$1",
                user_id,
            )
        await safe_send(user_id, texts.PAYMENT_ACCEPTED, payment_accept_kb())
        await db.event("payment_approved", telegram_id=user_id, data={"admin_id": callback.from_user.id})
        await delete_callback_message(callback)
        await callback.answer("Paiement validé.", show_alert=True)
        return
    if action == "reject":
        await set_admin_session(
            callback.from_user.id,
            "payment_reject_reason",
            {
                "payment_id": payment_id,
                "decision_chat_id": callback.message.chat.id,
                "decision_message_id": callback.message.message_id,
            },
        )
        await callback.message.answer("Envoyez le motif du refus. Ce texte sera transmis à l’utilisateur. Maximum : 500 caractères.")
        await callback.answer()


async def remove_stored_admin_message(data: dict) -> None:
    try:
        await bot.delete_message(int(data["decision_chat_id"]), int(data["decision_message_id"]))
    except Exception:
        pass


async def handle_admin_private_message(message: Message) -> bool:
    session = await get_admin_session(message.from_user.id)
    if not session or not session["state"]:
        return False
    state = session["state"]
    data = json_object(session["data"])

    if state == "application_reject_reason":
        reason = truncate(message.text or message.caption, 500)
        if not reason:
            await message.answer("Envoyez un motif texte valide.")
            return True
        application_id = int(data["application_id"])
        async with db.transaction() as connection:
            application = await connection.fetchrow(
                """
                UPDATE applications SET status='rejected',admin_decision_by=$2,rejection_reason=$3,
                  decision_at=now(),updated_at=now()
                WHERE id=$1 AND status='pending' RETURNING telegram_id
                """,
                application_id,
                message.from_user.id,
                reason,
            )
            if not application:
                await clear_admin_session(message.from_user.id)
                await message.answer("Cette candidature a déjà été traitée.")
                return True
            user_id = int(application["telegram_id"])
            attempts = await connection.fetchval("SELECT attempts FROM users WHERE telegram_id=$1", user_id) or 0
            new_status = "attempts_exhausted" if attempts >= 2 else "application_rejected"
            await connection.execute(
                "UPDATE users SET status=$2,flow_state=NULL,flow_data='{}'::jsonb,updated_at=now() WHERE telegram_id=$1",
                user_id,
                new_status,
            )
        price = await db.get_setting("premium_price", "30 €")
        await safe_send(
            user_id,
            texts.application_rejected(reason, max(0, 2 - int(attempts))),
            rejected_application_kb(price, attempts < 2),
        )
        await db.event("application_rejected", telegram_id=user_id, data={"admin_id": message.from_user.id})
        await remove_stored_admin_message(data)
        await clear_admin_session(message.from_user.id)
        await message.answer("✅ Refus envoyé à l’utilisateur.", reply_markup=back_admin_kb())
        return True

    if state == "payment_reject_reason":
        reason = truncate(message.text or message.caption, 500)
        if not reason:
            await message.answer("Envoyez un motif texte valide.")
            return True
        payment_id = int(data["payment_id"])
        payment = await db.fetchrow(
            """
            UPDATE payments SET status='rejected',admin_decision_by=$2,rejection_reason=$3,decided_at=now()
            WHERE id=$1 AND status='pending' RETURNING telegram_id
            """,
            payment_id,
            message.from_user.id,
            reason,
        )
        if not payment:
            await clear_admin_session(message.from_user.id)
            await message.answer("Ce paiement a déjà été traité.")
            return True
        user_id = int(payment["telegram_id"])
        await clear_user_flow(user_id, status="payment_rejected")
        await safe_send(user_id, texts.payment_rejected(reason), payment_rejected_kb())
        await db.event("payment_rejected", telegram_id=user_id, data={"admin_id": message.from_user.id})
        await remove_stored_admin_message(data)
        await clear_admin_session(message.from_user.id)
        await message.answer("✅ Refus envoyé à l’utilisateur.", reply_markup=back_admin_kb())
        return True

    if state == "appeal_reject_reason":
        reason = truncate(message.text or message.caption, 500)
        if not reason:
            await message.answer("Envoyez un motif texte valide.")
            return True
        appeal_id = int(data["appeal_id"])
        appeal = await db.fetchrow(
            """
            UPDATE appeals SET status='rejected',admin_decision_by=$2,rejection_reason=$3,decided_at=now()
            WHERE id=$1 AND status='pending' RETURNING telegram_id
            """,
            appeal_id,
            message.from_user.id,
            reason,
        )
        if not appeal:
            await clear_admin_session(message.from_user.id)
            await message.answer("Ce réexamen a déjà été traité.")
            return True
        user_id = int(appeal["telegram_id"])
        await safe_send(user_id, texts.appeal_rejected(reason))
        await db.event("appeal_rejected", telegram_id=user_id, data={"admin_id": message.from_user.id})
        await remove_stored_admin_message(data)
        await clear_admin_session(message.from_user.id)
        await message.answer("✅ Refus envoyé à l’utilisateur.", reply_markup=back_admin_kb())
        return True

    if state == "content_text":
        value = truncate(message.text or message.caption, 1000)
        if not value:
            await message.answer("Envoyez un texte valide.")
            return True
        kind = str(data["kind"])
        key = "ad_text" if kind == "ad" else "welcome_text"
        await db.set_setting(key, value)
        await clear_admin_session(message.from_user.id)
        await message.answer("✅ Texte enregistré.", reply_markup=back_admin_kb())
        return True

    if state == "content_media":
        kind = str(data["kind"])
        expected = str(data["expected"])
        file_id = None
        media_type = None
        if expected == "photo" and message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif expected == "video" and message.video:
            file_id = message.video.file_id
            media_type = "video"
        if not file_id:
            await message.answer(f"Envoyez une {expected == 'photo' and 'photo' or 'vidéo'} correspondant au format demandé.")
            return True
        if kind == "gallery":
            await db.set_setting("gallery_example_file_id", file_id)
        else:
            await db.set_setting(f"{kind}_media_file_id", file_id)
            await db.set_setting(f"{kind}_media_type", media_type)
        await clear_admin_session(message.from_user.id)
        await message.answer("✅ Média enregistré.", reply_markup=back_admin_kb())
        return True

    if state == "setting_text":
        key = str(data["key"])
        value = truncate(message.text or message.caption, 500)
        if not value and key not in {"paypal_link", "usdt_address"}:
            await message.answer("Envoyez une valeur valide.")
            return True
        if key == "max_declared_total":
            try:
                number = int(value)
                if number < 1 or number > 100:
                    raise ValueError
            except ValueError:
                await message.answer("Envoyez un nombre entier compris entre 1 et 100.")
                return True
            value = str(number)
        elif key == "auto_pub_interval_minutes":
            try:
                number = int(value)
                if number < 1 or number > 10080:
                    raise ValueError
            except ValueError:
                await message.answer("Envoyez un nombre entier compris entre 1 et 10080 minutes.")
                return True
            value = str(number)
        elif key == "premium_price":
            if len(value) > 30 or parse_money(value) <= 0:
                await message.answer("Envoyez un prix valide de 30 caractères maximum, par exemple : 30 €")
                return True
        await db.set_setting(key, value)
        await clear_admin_session(message.from_user.id)
        await message.answer(f"✅ Réglage enregistré : {key}", reply_markup=back_admin_kb())
        return True

    if state == "broadcast_message":
        category = str(data["category"])
        targets = await broadcast_target_ids(category)
        broadcast_id = await db.fetchval(
            """
            INSERT INTO broadcasts(admin_id,category,source_chat_id,source_message_id,total_targets,status)
            VALUES($1,$2,$3,$4,$5,'draft') RETURNING id
            """,
            message.from_user.id,
            category,
            message.chat.id,
            message.message_id,
            len(targets),
        )
        await clear_admin_session(message.from_user.id)
        await message.answer(
            f"📣 Aperçu du broadcast\n\nCatégorie : {category}\nDestinataires : {len(targets)}\n\nConfirmer l’envoi ?",
            reply_markup=broadcast_confirm_kb(broadcast_id),
        )
        return True

    return False


@router.callback_query(F.data == "appeal:start")
async def appeal_start(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row or not row["appeal_available"]:
        await callback.answer("Aucun réexamen n’est disponible pour cet incident.", show_alert=True)
        return
    await set_user_flow(
        callback.from_user.id,
        "appeal_text",
        {"failure_reason": row["status"]},
        status=row["status"],
        replace_data=True,
    )
    await replace_callback_message(callback, texts.APPEAL_PROMPT)
    await callback.answer()


@router.callback_query(F.data.startswith("appealdec:"))
async def appeal_decision(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Admin uniquement", show_alert=True)
        return
    _, action, raw_id = callback.data.split(":", 2)
    appeal_id = int(raw_id)
    appeal = await db.fetchrow("SELECT * FROM appeals WHERE id=$1", appeal_id)
    if not appeal or appeal["status"] != "pending":
        await callback.answer("Ce réexamen a déjà été traité.", show_alert=True)
        return
    user_id = int(appeal["telegram_id"])
    if action == "approve":
        updated = await db.fetchrow(
            """
            UPDATE appeals SET status='approved',admin_decision_by=$2,decided_at=now()
            WHERE id=$1 AND status='pending' RETURNING telegram_id
            """,
            appeal_id,
            callback.from_user.id,
        )
        if not updated:
            await callback.answer("Ce réexamen a déjà été traité.", show_alert=True)
            return
        await unban_configured_groups(user_id)
        await db.execute(
            """
            UPDATE users SET banned=false,status='appeal_invite',flow_state=NULL,flow_data='{}'::jsonb,
              joined_main_at=NULL,first_media_at=NULL,valid_media_count=0,progress_milestone=0,
              first_warning_sent=false,quota_warning_sent=false,appeal_available=false,updated_at=now()
            WHERE telegram_id=$1
            """,
            user_id,
        )
        user = await get_user(user_id)
        try:
            invite = await create_personal_invite(user_id, "appeal", 24)
            await safe_send(
                user_id,
                texts.appeal_accepted(int(user["declared_total"] or 0)),
                url_kb("🔗 Demander à rejoindre le groupe", invite),
            )
        except Exception as exc:
            await notify_admins(f"❌ Lien de réexamen impossible pour {user_id}\n\n{exc}")
        await db.event("appeal_approved", telegram_id=user_id, data={"admin_id": callback.from_user.id})
        await delete_callback_message(callback)
        await callback.answer("Réexamen accepté.", show_alert=True)
        return
    if action == "reject":
        await set_admin_session(
            callback.from_user.id,
            "appeal_reject_reason",
            {
                "appeal_id": appeal_id,
                "decision_chat_id": callback.message.chat.id,
                "decision_message_id": callback.message.message_id,
            },
        )
        await callback.message.answer("Envoyez le motif du refus. Ce texte sera transmis à l’utilisateur. Maximum : 500 caractères.")
        await callback.answer()
        return
    if action == "ban":
        updated = await db.fetchrow(
            """
            UPDATE appeals SET status='banned',admin_decision_by=$2,rejection_reason='Maintien du bannissement',decided_at=now()
            WHERE id=$1 AND status='pending' RETURNING telegram_id
            """,
            appeal_id,
            callback.from_user.id,
        )
        if updated:
            await safe_send(user_id, texts.appeal_rejected("Maintien du bannissement"))
        await delete_callback_message(callback)
        await callback.answer("Bannissement maintenu.", show_alert=True)


@router.callback_query(F.data == "invite:request_new")
async def request_new_invite(callback: CallbackQuery) -> None:
    row = await get_user(callback.from_user.id)
    if not row:
        await callback.answer("Compte introuvable.", show_alert=True)
        return
    status = str(row["status"])
    if status in {"premium_left", "premium_invite"}:
        kind = "premium"
    elif status in {"free_invite", "appeal_invite"}:
        kind = "free"
    else:
        await callback.answer("Votre situation ne permet pas de demander un nouveau lien.", show_alert=True)
        return
    request_id = await db.fetchval(
        """
        INSERT INTO new_link_requests(telegram_id,kind,status)
        VALUES($1,$2,'pending')
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        callback.from_user.id,
        kind,
    )
    if not request_id:
        await replace_callback_message(callback, texts.NEW_LINK_REQUESTED)
        await callback.answer("Une demande est déjà en attente.", show_alert=True)
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Envoyer un nouveau lien", callback_data=f"newlink:approve:{request_id}")],
        [InlineKeyboardButton(text="❌ Refuser", callback_data=f"newlink:reject:{request_id}")],
    ])
    await notify_admins(
        f"🆘 Demande de nouveau lien\n\nUtilisateur : @{callback.from_user.username or '-'}\nID : {callback.from_user.id}\nType : {kind}",
        markup,
    )
    await replace_callback_message(callback, texts.NEW_LINK_REQUESTED)
    await db.event("new_link_requested", telegram_id=callback.from_user.id, data={"kind": kind})
    await callback.answer()


@router.callback_query(F.data.startswith("newlink:"))
async def new_link_decision(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Admin uniquement", show_alert=True)
        return
    _, action, raw_request_id = callback.data.split(":", 2)
    request_id = int(raw_request_id)
    if action == "approve":
        request_row = await db.fetchrow(
            """
            UPDATE new_link_requests SET status='processing',admin_decision_by=$2,processing_at=now()
            WHERE id=$1 AND status='pending'
            RETURNING telegram_id,kind
            """,
            request_id,
            callback.from_user.id,
        )
        if not request_row:
            await callback.answer("Cette demande a déjà été traitée.", show_alert=True)
            return
        user_id = int(request_row["telegram_id"])
        kind = str(request_row["kind"])
        user = await get_user(user_id)
        allowed_statuses = {
            "premium": {"premium_left", "premium_invite"},
            "free": {"free_invite", "appeal_invite"},
        }
        if not user or user["banned"] or user["status"] not in allowed_statuses.get(kind, set()):
            await db.execute(
                "UPDATE new_link_requests SET status='rejected',decided_at=now(),processing_at=NULL WHERE id=$1",
                request_id,
            )
            await delete_callback_message(callback)
            await callback.answer("La situation de cet utilisateur a changé.", show_alert=True)
            return
        hours = 48 if kind == "premium" else 24
        try:
            invite = await create_personal_invite(user_id, kind, hours)
            if kind == "premium":
                await db.execute("UPDATE users SET status='premium_invite',banned=false,updated_at=now() WHERE telegram_id=$1", user_id)
                body = texts.PREMIUM_INVITE_READY
            else:
                await db.execute("UPDATE users SET status='free_invite',banned=false,updated_at=now() WHERE telegram_id=$1", user_id)
                body = texts.free_invite_ready(int(user["declared_total"] or 0))
            await db.execute(
                "UPDATE new_link_requests SET status='completed',decided_at=now(),processing_at=NULL WHERE id=$1",
                request_id,
            )
            await safe_send(user_id, body, url_kb("🔗 Demander à rejoindre le groupe", invite))
            await db.event(
                "new_link_approved",
                telegram_id=user_id,
                data={"admin_id": callback.from_user.id, "kind": kind},
            )
            await delete_callback_message(callback)
            await callback.answer("Nouveau lien envoyé.", show_alert=True)
        except Exception as exc:
            await db.execute(
                """
                UPDATE new_link_requests SET status='pending',admin_decision_by=NULL,processing_at=NULL
                WHERE id=$1 AND status='processing'
                """,
                request_id,
            )
            await callback.answer(f"Erreur : {exc}", show_alert=True)
        return
    rejected = await db.fetchrow(
        """
        UPDATE new_link_requests SET status='rejected',admin_decision_by=$2,decided_at=now(),processing_at=NULL
        WHERE id=$1 AND status='pending' RETURNING telegram_id
        """,
        request_id,
        callback.from_user.id,
    )
    if not rejected:
        await callback.answer("Cette demande a déjà été traitée.", show_alert=True)
        return
    await safe_send(int(rejected["telegram_id"]), texts.NEW_LINK_REJECTED)
    await db.event(
        "new_link_rejected",
        telegram_id=int(rejected["telegram_id"]),
        data={"admin_id": callback.from_user.id},
    )
    await delete_callback_message(callback)
    await callback.answer("Demande refusée.", show_alert=True)


async def show_admin_panel(chat_id: int) -> None:
    await bot.send_message(chat_id, "Panneau administrateur\n\nChoisissez une section.", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    await clear_admin_session(callback.from_user.id)
    await replace_callback_message(callback, "Panneau administrateur\n\nChoisissez une section.", admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data.in_({"admin:ad", "admin:welcome", "admin:gallery"}))
async def admin_content_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    kind = callback.data.split(":", 1)[1]
    enabled = await db.get_setting("auto_pub_enabled", "0") == "1"
    labels = {
        "ad": "📢 Configuration de la publicité\n\nTexte et photo/vidéo configurables.",
        "welcome": "👋 Configuration du message d’accueil\n\nTexte et photo/vidéo configurables.",
        "gallery": "🖼 Configuration de l’exemple de galerie\n\nUne photo uniquement.",
    }
    await replace_callback_message(
        callback,
        labels[kind],
        content_menu_kb(kind, allow_video=kind in {"ad", "welcome"}, auto_enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("content:"))
async def content_action(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, action, kind = callback.data.split(":", 2)
    if kind not in {"ad", "welcome", "gallery"}:
        await callback.answer("Type inconnu.", show_alert=True)
        return
    if action == "text":
        if kind == "gallery":
            await callback.answer("Aucun texte configurable pour cet élément.", show_alert=True)
            return
        await set_admin_session(callback.from_user.id, "content_text", {"kind": kind})
        await replace_callback_message(callback, "Envoyez maintenant le nouveau texte complet.")
        await callback.answer()
        return
    if action in {"photo", "video"}:
        if kind == "gallery" and action != "photo":
            await callback.answer("L’exemple de galerie doit être une photo.", show_alert=True)
            return
        await set_admin_session(callback.from_user.id, "content_media", {"kind": kind, "expected": action})
        await replace_callback_message(callback, f"Envoyez maintenant {'une photo' if action == 'photo' else 'une vidéo'}.")
        await callback.answer()
        return
    if action == "delete":
        if kind == "gallery":
            await db.set_setting("gallery_example_file_id", "")
        else:
            await db.set_setting(f"{kind}_media_file_id", "")
            await db.set_setting(f"{kind}_media_type", "")
        await callback.answer("Média supprimé.", show_alert=True)
        return
    if action == "preview":
        if kind == "gallery":
            file_id = await db.get_setting("gallery_example_file_id", "")
            if file_id:
                await bot.send_photo(callback.message.chat.id, file_id, caption=texts.GALLERY_PROMPT)
            else:
                await callback.answer("Aucune image d’exemple configurée.", show_alert=True)
                return
        elif kind == "welcome":
            await configured_message(callback.message.chat.id, "welcome", start_kb())
        else:
            me = await bot.get_me()
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔗 Demander un accès", url=f"https://t.me/{me.username}?start=ad_preview")
            ]])
            await configured_message(callback.message.chat.id, "ad", markup)
        await callback.answer("Prévisualisation envoyée.")


async def publish_ad(chat_id: int, username: str) -> None:
    previous = await db.fetchrow(
        "SELECT last_ad_message_id,last_ad_extra_message_id FROM groups WHERE chat_id=$1",
        chat_id,
    )
    previous_ids = [] if not previous else [
        previous["last_ad_message_id"],
        previous["last_ad_extra_message_id"],
    ]
    for previous_id in filter(None, previous_ids):
        try:
            await bot.delete_message(chat_id, int(previous_id))
        except Exception as exc:
            await db.log(
                "previous_ad_delete_failed",
                chat_id=chat_id,
                data={"message_id": int(previous_id), "error": str(exc)},
                level="warning",
            )
    source = f"ad_{chat_id}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔗 Demander un accès", url=f"https://t.me/{username}?start={source}")
    ]])
    sent, extra = await configured_message(chat_id, "ad", markup)
    await db.execute(
        """
        UPDATE groups SET last_ad_message_id=$2,last_ad_extra_message_id=$3,
          last_ad_at=now(),updated_at=now() WHERE chat_id=$1
        """,
        chat_id,
        sent.message_id,
        extra.message_id if extra else None,
    )
    await db.event("ad_published", source=str(chat_id))


async def publish_all_ads() -> tuple[int, int]:
    rows = await db.fetch("SELECT chat_id FROM groups WHERE type='pub' AND active=true AND targeted=true")
    if not rows:
        await db.set_setting("last_auto_pub_at", utcnow().isoformat())
        return 0, 0
    me = await bot.get_me()
    sent = 0
    failed = 0
    for row in rows:
        try:
            await publish_ad(int(row["chat_id"]), me.username)
            sent += 1
        except Exception as exc:
            failed += 1
            await db.log("ad_publish_failed", chat_id=int(row["chat_id"]), data={"error": str(exc)}, level="error")
    # Mémoriser aussi un cycle sans cible afin de ne pas solliciter Telegram
    # toutes les 30 secondes lorsque l'auto-publicité est activée trop tôt.
    await db.set_setting("last_auto_pub_at", utcnow().isoformat())
    return sent, failed


@router.callback_query(F.data == "ad:publish_now")
async def ad_publish_now(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    sent, failed = await publish_all_ads()
    await callback.answer(f"Envoyées : {sent} — Échecs : {failed}", show_alert=True)


@router.callback_query(F.data == "ad:auto_toggle")
async def ad_auto_toggle(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    enabled = await db.get_setting("auto_pub_enabled", "0") == "1"
    await db.set_setting("auto_pub_enabled", "0" if enabled else "1")
    await replace_callback_message(
        callback,
        "📢 Configuration de la publicité\n\nTexte et photo/vidéo configurables.",
        content_menu_kb("ad", allow_video=True, auto_enabled=not enabled),
    )
    await callback.answer("Publicité automatique désactivée." if enabled else "Publicité automatique activée.", show_alert=True)


async def render_ad_targets(callback: CallbackQuery) -> None:
    rows = await db.fetch("SELECT chat_id,title,targeted FROM groups WHERE type='pub' ORDER BY title")
    if not rows:
        await replace_callback_message(callback, "Aucun groupe publicitaire configuré.", groups_menu_kb())
        return
    keyboard = [
        [InlineKeyboardButton(
            text=f"{'☑' if row['targeted'] else '☐'} {row['title'] or row['chat_id']}",
            callback_data=f"adtarget:{row['chat_id']}",
        )]
        for row in rows
    ]
    keyboard.append([InlineKeyboardButton(text="⬅️ Retour publicité", callback_data="admin:ad")])
    await replace_callback_message(callback, "🎯 Groupes ciblés", InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "ad:targets")
async def ad_targets(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    await render_ad_targets(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("adtarget:"))
async def ad_target_toggle(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    chat_id = int(callback.data.split(":", 1)[1])
    await db.execute("UPDATE groups SET targeted=NOT targeted,updated_at=now() WHERE chat_id=$1 AND type='pub'", chat_id)
    await render_ad_targets(callback)
    await callback.answer()


async def render_groups_list(callback: CallbackQuery) -> None:
    rows = await db.fetch(
        "SELECT chat_id,title,type,targeted FROM groups ORDER BY CASE type WHEN 'main' THEN 0 WHEN 'pub' THEN 1 ELSE 2 END,title"
    )
    if not rows:
        text = "Aucun groupe détecté. Ajoutez le bot dans un groupe Telegram pour qu’il soit enregistré automatiquement."
        await replace_callback_message(callback, text, groups_menu_kb())
        return
    keyboard = []
    for row in rows:
        icon = "⭐" if row["type"] == "main" else ("📢" if row["type"] == "pub" else "⚪")
        target = " ☑" if row["type"] == "pub" and row["targeted"] else ""
        keyboard.append([InlineKeyboardButton(
            text=f"{icon} {row['title'] or row['chat_id']}{target}",
            callback_data=f"group:open:{row['chat_id']}",
        )])
    keyboard.append([InlineKeyboardButton(text="⬅️ Retour au panneau", callback_data="admin:home")])
    await replace_callback_message(callback, "👥 Groupes détectés", InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "admin:groups")
@router.callback_query(F.data == "groups:list")
async def groups_list(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    await render_groups_list(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("group:"))
async def group_action(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, action, raw_chat_id = callback.data.split(":", 2)
    chat_id = int(raw_chat_id)
    if action == "open":
        row = await db.fetchrow("SELECT chat_id,title,type,targeted FROM groups WHERE chat_id=$1", chat_id)
        if not row:
            await callback.answer("Groupe introuvable.", show_alert=True)
            return
        await replace_callback_message(
            callback,
            f"👥 {row['title'] or row['chat_id']}\n\nRôle : {row['type']}\nCiblé publicité : {'oui' if row['targeted'] else 'non'}",
            group_actions_kb(chat_id, row["type"], bool(row["targeted"])),
        )
        await callback.answer()
        return
    current_main = await main_group_id()
    changes_main = (
        (action == "main" and current_main is not None and current_main != chat_id)
        or (action in {"pub", "detected"} and current_main == chat_id)
    )
    if changes_main:
        active_members = await db.fetchval(
            "SELECT count(*) FROM users WHERE status='temporary_member'"
        ) or 0
        if active_members:
            await callback.answer(
                f"Impossible : {active_members} quota(s) sont actuellement en cours.",
                show_alert=True,
            )
            return
        await revoke_chat_invites(int(current_main))
    if action == "main":
        await db.execute("UPDATE groups SET type='detected',targeted=false,updated_at=now() WHERE type='main'")
        await db.execute("UPDATE groups SET type='main',active=true,targeted=false,updated_at=now() WHERE chat_id=$1", chat_id)
        await db.set_setting("main_group", str(chat_id))
    elif action == "pub":
        if await main_group_id() == chat_id:
            await db.set_setting("main_group", "")
        await db.execute("UPDATE groups SET type='pub',active=true,targeted=true,updated_at=now() WHERE chat_id=$1", chat_id)
    elif action == "detected":
        if await main_group_id() == chat_id:
            await db.set_setting("main_group", "")
        await db.execute("UPDATE groups SET type='detected',targeted=false,updated_at=now() WHERE chat_id=$1", chat_id)
    elif action == "target":
        await db.execute("UPDATE groups SET targeted=NOT targeted,updated_at=now() WHERE chat_id=$1 AND type='pub'", chat_id)
    await render_groups_list(callback)
    await callback.answer("Configuration enregistrée.", show_alert=True)


@router.callback_query(F.data == "admin:payments")
async def admin_payments(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    price = await db.get_setting("premium_price", "30 €")
    paypal = await db.get_setting("paypal_link", "")
    usdt = await db.get_setting("usdt_address", "")
    pot = await db.fetchval("SELECT COALESCE(sum(amount),0) FROM pot_transactions") or 0
    await replace_callback_message(
        callback,
        f"💳 Paiements\n\nPrix Premium : {price}\nPayPal : {paypal or 'non configuré'}\nUSDT : {usdt or 'non configuré'}\nCagnotte statistique : {pot} €",
        payments_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "payments:status")
async def payments_status(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    pending = await db.fetchval("SELECT count(*) FROM payments WHERE status='pending'") or 0
    validated = await db.fetchval("SELECT count(*) FROM payments WHERE status='validated'") or 0
    rejected = await db.fetchval("SELECT count(*) FROM payments WHERE status='rejected'") or 0
    await replace_callback_message(
        callback,
        f"📊 État des paiements\n\nEn attente : {pending}\nValidés : {validated}\nRefusés : {rejected}",
        payments_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("setting:text:"))
async def setting_text_start(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.split(":", 2)[2]
    allowed = {"premium_price", "paypal_link", "usdt_address", "max_declared_total", "auto_pub_interval_minutes"}
    if key not in allowed:
        await callback.answer("Réglage inconnu.", show_alert=True)
        return
    await set_admin_session(callback.from_user.id, "setting_text", {"key": key})
    await replace_callback_message(callback, f"Envoyez la nouvelle valeur pour : {key}")
    await callback.answer()


@router.callback_query(F.data == "admin:settings")
async def admin_settings(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    maximum = await db.get_setting("max_declared_total", "100")
    interval = await db.get_setting("auto_pub_interval_minutes", "60")
    await replace_callback_message(
        callback,
        f"⚙️ Réglages\n\nLimite maximale : {maximum}\nFréquence publicité : {interval} minute(s)",
        settings_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:moderation")
async def admin_moderation(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    applications = await db.fetchval("SELECT count(*) FROM applications WHERE status='pending'") or 0
    payments = await db.fetchval("SELECT count(*) FROM payments WHERE status='pending'") or 0
    appeals = await db.fetchval("SELECT count(*) FROM appeals WHERE status='pending'") or 0
    blocked = await db.fetchval("SELECT count(*) FROM users WHERE banned=true") or 0
    await replace_callback_message(
        callback,
        f"📥 Modération\n\nCandidatures : {applications}\nPaiements : {payments}\nRéexamens : {appeals}\nComptes bloqués : {blocked}",
        moderation_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("moderation:"))
async def moderation_list(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    action = callback.data.split(":", 1)[1]
    if action == "applications":
        rows = await db.fetch(
            """
            SELECT a.id,u.telegram_id,u.username,u.declared_total,a.created_at
            FROM applications a JOIN users u ON u.telegram_id=a.telegram_id
            WHERE a.status='pending' ORDER BY a.created_at DESC LIMIT 20
            """
        )
        title = "📥 Candidatures en attente"
        lines = [f"#{r['id']} — @{r['username'] or '-'} — {r['declared_total']} médias — ID {r['telegram_id']}" for r in rows]
    elif action == "payments":
        rows = await db.fetch(
            """
            SELECT p.id,u.telegram_id,u.username,p.amount,p.created_at
            FROM payments p JOIN users u ON u.telegram_id=p.telegram_id
            WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 20
            """
        )
        title = "💎 Paiements en attente"
        lines = [f"#{r['id']} — @{r['username'] or '-'} — {r['amount']} — ID {r['telegram_id']}" for r in rows]
    elif action == "appeals":
        rows = await db.fetch(
            """
            SELECT a.id,u.telegram_id,u.username,a.failure_reason,a.created_at
            FROM appeals a JOIN users u ON u.telegram_id=a.telegram_id
            WHERE a.status='pending' ORDER BY a.created_at DESC LIMIT 20
            """
        )
        title = "🧾 Réexamens en attente"
        lines = [f"#{r['id']} — @{r['username'] or '-'} — {r['failure_reason']} — ID {r['telegram_id']}" for r in rows]
    elif action == "blocked":
        rows = await db.fetch(
            "SELECT telegram_id,username,status,updated_at FROM users WHERE banned=true ORDER BY updated_at DESC LIMIT 30"
        )
        title = "🚫 Comptes bloqués"
        lines = [f"@{r['username'] or '-'} — {r['telegram_id']} — {r['status']}" for r in rows]
    else:
        rows = await db.fetch(
            "SELECT level,event,telegram_id,chat_id,created_at FROM logs ORDER BY created_at DESC LIMIT 20"
        )
        title = "🧾 Journaux récents"
        lines = [f"{r['level']} — {r['event']} — user:{r['telegram_id'] or '-'} — chat:{r['chat_id'] or '-'}" for r in rows]
    body = title + "\n\n" + ("\n".join(lines) if lines else "Aucun élément.")
    await replace_callback_message(callback, body[:4000], moderation_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    user_stats = await db.fetchrow(
        """
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE abandonment_state IS NOT NULL) AS abandoned,
          count(*) FILTER (WHERE status='application_pending') AS applications_pending,
          count(*) FILTER (WHERE status IN ('member_validated','temporary_member')) AS free_members,
          count(*) FILTER (WHERE status='premium_member') AS premium_members,
          count(*) FILTER (WHERE status='failed_no_activity') AS failed_first,
          count(*) FILTER (WHERE status='failed_quota') AS failed_quota
        FROM users
        """
    )
    event_rows = await db.fetch(
        """
        SELECT event,count(*) AS total,count(DISTINCT telegram_id) AS users
        FROM analytics_events GROUP BY event
        """
    )
    events = {row["event"]: int(row["users"] or row["total"] or 0) for row in event_rows}
    ad_starts = events.get("ad_start", 0)
    joined = events.get("main_joined", 0)
    application_submitted = events.get("application_submitted", 0)
    premium_selected = events.get("premium_selected", 0)
    conversion = (joined / ad_starts * 100) if ad_starts else 0
    text = (
        "📊 Statistiques\n\n"
        f"Utilisateurs : {user_stats['total']}\n"
        f"Démarrages depuis une publicité : {ad_starts}\n"
        f"Clics sur Continuer : {events.get('continued', 0)}\n"
        f"Candidatures gratuites commencées : {events.get('free_selected', 0)}\n"
        f"Captures de galerie reçues : {events.get('gallery_received', 0)}\n"
        f"Candidatures complètes : {application_submitted}\n"
        f"Candidatures acceptées : {events.get('application_approved', 0)}\n"
        f"Candidatures refusées : {events.get('application_rejected', 0)}\n"
        f"Intéressés Premium : {premium_selected}\n"
        f"Preuves de paiement : {events.get('payment_proof_submitted', 0)}\n"
        f"Paiements validés : {events.get('payment_approved', 0)}\n"
        f"Entrées dans le groupe : {joined}\n"
        f"Quotas complétés : {events.get('quota_completed', 0)}\n"
        f"Bannis après 3 minutes : {user_stats['failed_first']}\n"
        f"Bannis après 24 heures : {user_stats['failed_quota']}\n"
        f"Abandons détectés : {user_stats['abandoned']}\n\n"
        f"Taux de conversion publicité → groupe : {conversion:.1f} %"
    )
    await replace_callback_message(callback, text, back_admin_kb())
    await callback.answer()


async def broadcast_target_ids(category: str) -> list[int]:
    queries = {
        "all_active": "SELECT telegram_id FROM users WHERE banned=false",
        "continued": "SELECT DISTINCT telegram_id FROM analytics_events WHERE event='continued' AND telegram_id IS NOT NULL",
        "free_incomplete": "SELECT telegram_id FROM users WHERE banned=false AND flow_state LIKE 'free_%'",
        "applications_pending": "SELECT DISTINCT telegram_id FROM applications WHERE status='pending'",
        "applications_rejected": "SELECT telegram_id FROM users WHERE status IN ('application_rejected','attempts_exhausted')",
        "free_members": "SELECT telegram_id FROM users WHERE status IN ('temporary_member','member_validated')",
        "premium_interested": "SELECT telegram_id FROM users WHERE status IN ('premium_interested','payment_proof','payment_pending','payment_rejected','premium_rules','premium_invite')",
        "payments_pending": "SELECT DISTINCT telegram_id FROM payments WHERE status='pending' AND telegram_id IS NOT NULL",
        "payments_rejected": "SELECT DISTINCT telegram_id FROM payments WHERE status='rejected' AND telegram_id IS NOT NULL",
        "premium_members": "SELECT telegram_id FROM users WHERE status IN ('premium_member','premium_left')",
        "abandoned": "SELECT telegram_id FROM users WHERE abandonment_state IS NOT NULL AND banned=false",
        "failed_first": "SELECT telegram_id FROM users WHERE status='failed_no_activity'",
        "failed_quota": "SELECT telegram_id FROM users WHERE status='failed_quota'",
        "appeals": "SELECT DISTINCT telegram_id FROM appeals WHERE status='pending'",
    }
    query = queries.get(category)
    if not query:
        return []
    rows = await db.fetch(query)
    return [
        int(row["telegram_id"])
        for row in rows
        if int(row["telegram_id"]) not in config.admin_ids
    ]


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    await replace_callback_message(callback, "📣 Broadcast par catégorie\n\nChoisissez les destinataires.", broadcast_categories_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:category:"))
async def broadcast_category(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    category = callback.data.split(":", 2)[2]
    targets = await broadcast_target_ids(category)
    await set_admin_session(callback.from_user.id, "broadcast_message", {"category": category})
    await replace_callback_message(
        callback,
        f"📣 Catégorie : {category}\nDestinataires actuels : {len(targets)}\n\nEnvoyez maintenant le message à diffuser. Texte, photo, vidéo ou document accepté.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:cancel:"))
async def broadcast_cancel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    broadcast_id = int(callback.data.rsplit(":", 1)[1])
    await db.execute("UPDATE broadcasts SET status='cancelled',completed_at=now() WHERE id=$1 AND status='draft'", broadcast_id)
    await replace_callback_message(callback, "Broadcast annulé.", back_admin_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("broadcast:confirm:"))
async def broadcast_confirm(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    broadcast_id = int(callback.data.rsplit(":", 1)[1])
    row = await db.fetchrow("SELECT * FROM broadcasts WHERE id=$1", broadcast_id)
    if not row or row["status"] != "draft":
        await callback.answer("Ce broadcast a déjà été traité.", show_alert=True)
        return
    targets = await broadcast_target_ids(row["category"])
    updated = await db.fetchrow(
        "UPDATE broadcasts SET status='sending',total_targets=$2 WHERE id=$1 AND status='draft' RETURNING id",
        broadcast_id,
        len(targets),
    )
    if not updated:
        await callback.answer("Ce broadcast a déjà été traité.", show_alert=True)
        return
    await replace_callback_message(callback, f"📣 Envoi en cours…\n\nDestinataires : {len(targets)}")
    sent = 0
    failed = 0
    for user_id in targets:
        try:
            await bot.copy_message(user_id, int(row["source_chat_id"]), int(row["source_message_id"]))
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.2)
            try:
                await bot.copy_message(user_id, int(row["source_chat_id"]), int(row["source_message_id"]))
                sent += 1
            except Exception:
                failed += 1
        except Exception as exc:
            failed += 1
            await db.log("broadcast_delivery_failed", telegram_id=user_id, data={"broadcast_id": broadcast_id, "error": str(exc)}, level="warning")
        await asyncio.sleep(0.05)
    await db.execute(
        "UPDATE broadcasts SET status='completed',sent_count=$2,failed_count=$3,completed_at=now() WHERE id=$1",
        broadcast_id,
        sent,
        failed,
    )
    await db.event("broadcast_completed", telegram_id=callback.from_user.id, data={"sent": sent, "failed": failed, "category": row["category"]})
    await bot.send_message(callback.message.chat.id, f"✅ Broadcast terminé.\n\nEnvoyés : {sent}\nÉchecs : {failed}", reply_markup=back_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:health")
async def admin_health(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    checks: list[str] = []
    try:
        await db.fetchval("SELECT 1")
        checks.append("✅ PostgreSQL")
    except Exception as exc:
        checks.append(f"❌ PostgreSQL : {exc}")
    try:
        me = await bot.get_me()
        checks.append(f"✅ Telegram : @{me.username}")
    except Exception as exc:
        checks.append(f"❌ Telegram : {exc}")
    checks.append(f"{'✅' if config.admin_ids else '❌'} Administrateurs : {len(config.admin_ids)}")
    main = await main_group_id()
    checks.append(f"{'✅' if main else '❌'} Groupe principal : {main or 'non configuré'}")
    if main:
        try:
            main_chat = await bot.get_chat(main)
            checks.append(
                f"{'✅' if not main_chat.username else '❌'} Groupe principal privé"
            )
        except Exception as exc:
            checks.append(f"❌ Lecture du groupe principal : {exc}")
    pub_count = await db.fetchval("SELECT count(*) FROM groups WHERE type='pub' AND active=true") or 0
    checks.append(f"{'✅' if pub_count else '⚠️'} Groupes publicitaires : {pub_count}")
    groups = await db.fetch("SELECT chat_id,title,type FROM groups WHERE active=true ORDER BY type,title LIMIT 20")
    for group in groups:
        try:
            member = await bot.get_chat_member(int(group["chat_id"]), bot.id)
            checks.append(
                f"{'✅' if getattr(member, 'can_delete_messages', False) else '❌'} Suppression — {group['title'] or group['chat_id']}"
            )
            checks.append(
                f"{'✅' if getattr(member, 'can_restrict_members', False) else '❌'} Bannissement — {group['title'] or group['chat_id']}"
            )
            if group["type"] == "main":
                checks.append(
                    f"{'✅' if getattr(member, 'can_invite_users', False) else '❌'} Invitations — {group['title'] or group['chat_id']}"
                )
        except Exception as exc:
            checks.append(f"❌ Groupe inaccessible — {group['title'] or group['chat_id']} : {exc}")
    for label, key in (
        ("Texte publicitaire", "ad_text"),
        ("Message d’accueil", "welcome_text"),
        ("Image exemple galerie", "gallery_example_file_id"),
        ("Prix Premium", "premium_price"),
    ):
        checks.append(f"{'✅' if await db.get_setting(key, '') else '❌'} {label}")
    paypal = await db.get_setting("paypal_link", "")
    usdt = await db.get_setting("usdt_address", "")
    checks.append(f"{'✅' if paypal or usdt else '❌'} Moyen de paiement")
    heartbeat = await db.get_setting("scheduler_heartbeat", "")
    healthy_scheduler = False
    try:
        healthy_scheduler = utcnow() - datetime.fromisoformat(heartbeat) < timedelta(minutes=3)
    except (ValueError, TypeError):
        pass
    checks.append(f"{'✅' if healthy_scheduler else '❌'} Planificateur")
    checks.append("⚠️ Mode confidentialité BotFather : vérification manuelle nécessaire")
    auto_enabled = await db.get_setting("auto_pub_enabled", "0") == "1"
    checks.append(f"{'✅' if auto_enabled else '⚠️'} Publicité automatique : {'active' if auto_enabled else 'inactive'}")
    errors = await db.fetchval("SELECT count(*) FROM logs WHERE level='error' AND created_at>now()-interval '24 hours'") or 0
    checks.append(f"{'✅' if not errors else '⚠️'} Erreurs sur 24 h : {errors}")
    overall = "✅ Tous les contrôles sont opérationnels." if not any(line.startswith("❌") for line in checks) else "⚠️ Un ou plusieurs contrôles nécessitent votre attention."
    body = "🩺 Santé du bot\n\n" + overall + "\n\n" + "\n".join(checks)
    await replace_callback_message(callback, body[:4000], back_admin_kb())
    await callback.answer()


@router.callback_query()
async def expired_callback(callback: CallbackQuery) -> None:
    await callback.answer(texts.EXPIRED_ACTION, show_alert=True)


@router.my_chat_member()
async def bot_membership_changed(update: ChatMemberUpdated) -> None:
    try:
        if update.new_chat_member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}:
            await register_group(update.chat)
            await notify_admins(
                f"👥 Groupe détecté automatiquement\n\n{update.chat.title or '-'}\nID : {update.chat.id}\n\nAttribuez son rôle depuis le panneau Groupes."
            )
        elif update.new_chat_member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
            await db.execute(
                "UPDATE groups SET active=false,updated_at=now() WHERE chat_id=$1",
                update.chat.id,
            )
    except Exception as exc:
        await db.log("group_detection_failed", chat_id=update.chat.id, data={"error": str(exc)}, level="warning")


@router.chat_join_request()
async def chat_join_request(request: ChatJoinRequest) -> None:
    await register_group(request.chat)
    main = await main_group_id()
    if not main or request.chat.id != main:
        return
    await ensure_user(request.from_user)
    link_value = request.invite_link.invite_link if request.invite_link else None
    invite = None
    if link_value:
        invite = await db.fetchrow(
            """
            SELECT * FROM invite_links
            WHERE invite_link=$1 AND chat_id=$2 AND status='active' AND expires_at>now()
            """,
            link_value,
            request.chat.id,
        )
    if invite and int(invite["expected_user_id"]) == request.from_user.id:
        user = await get_user(request.from_user.id)
        expected_status = {
            "free": "free_invite",
            "appeal": "appeal_invite",
            "premium": "premium_invite",
        }
        if (
            user
            and not user["banned"]
            and user["status"] == expected_status.get(invite["access_kind"])
        ):
            await bot.approve_chat_join_request(request.chat.id, request.from_user.id)
            await db.execute(
                """
                UPDATE invite_links SET status='used',used_by=$2,used_at=now()
                WHERE id=$1 AND status='active'
                """,
                invite["id"],
                request.from_user.id,
            )
            try:
                await bot.revoke_chat_invite_link(request.chat.id, invite["invite_link"])
                await db.execute("UPDATE invite_links SET revoked_at=now() WHERE id=$1", invite["id"])
            except Exception:
                pass
            await safe_send(request.from_user.id, texts.JOIN_APPROVED)
            await db.event("join_request_approved", telegram_id=request.from_user.id, data={"kind": invite["access_kind"]})
            return
    await bot.decline_chat_join_request(request.chat.id, request.from_user.id)
    if invite and int(invite["expected_user_id"]) != request.from_user.id and not is_admin(request.from_user.id):
        await mark_banned(request.from_user.id, "invite_abuse", "wrong_personal_invite", include_main=False)
        await safe_send(request.from_user.id, texts.WRONG_INVITE)
        await notify_admins(
            "🚨 Utilisation d’un lien personnel par le mauvais compte\n\n"
            f"Compte sanctionné : @{request.from_user.username or '-'}\n"
            f"ID : {request.from_user.id}\n"
            f"Propriétaire attendu : {invite['expected_user_id']}"
        )
        await db.event(
            "wrong_invite_sanction",
            telegram_id=request.from_user.id,
            data={"expected_user_id": int(invite["expected_user_id"])},
        )
    else:
        await db.log("unknown_join_request_declined", telegram_id=request.from_user.id, chat_id=request.chat.id)


async def handle_main_join(chat_id: int, user) -> None:
    main = await main_group_id()
    if not main or chat_id != main or user.is_bot:
        return
    if is_admin(user.id):
        return
    row = await get_user(user.id)
    if not row or row["banned"]:
        await ban_from_chat(chat_id, user.id, "unauthorized_main_join")
        return
    status = row["status"]
    if status in {"member_validated", "premium_member"}:
        return
    if status == "temporary_member" and row["joined_main_at"]:
        return
    display_name = f"@{user.username}" if user.username else user.first_name
    if status == "premium_invite":
        claimed = await db.fetchval(
            """
            UPDATE users SET status='premium_member',joined_main_at=now(),first_media_at=NULL,
              valid_media_count=0,updated_at=now()
            WHERE telegram_id=$1 AND status='premium_invite'
            RETURNING telegram_id
            """,
            user.id,
        )
        if not claimed:
            return
        await safe_send(user.id, texts.PREMIUM_JOIN_PRIVATE)
        public = await bot.send_message(chat_id, texts.premium_join_public(display_name))
        await schedule_delete(chat_id, public.message_id, 180)
        await db.event("main_joined", telegram_id=user.id, data={"kind": "premium"})
        return
    if status in {"free_invite", "appeal_invite"}:
        joined = utcnow()
        first_deadline = joined + timedelta(minutes=3)
        quota_deadline = joined + timedelta(hours=24)
        claimed = await db.fetchval(
            """
            UPDATE users SET status='temporary_member',joined_main_at=$2,first_media_at=NULL,
              valid_media_count=0,progress_milestone=0,first_warning_sent=false,
              quota_warning_sent=false,appeal_available=false,updated_at=now()
            WHERE telegram_id=$1 AND status=$3
            RETURNING telegram_id
            """,
            user.id,
            joined,
            status,
        )
        if not claimed:
            return
        await safe_send(
            user.id,
            texts.free_join_private(
                int(row["declared_total"] or 0),
                format_datetime(joined),
                format_datetime(first_deadline),
                format_datetime(quota_deadline),
            ),
        )
        public = await bot.send_message(chat_id, texts.free_join_public(display_name, int(row["declared_total"] or 0)))
        await schedule_delete(chat_id, public.message_id, 180)
        await db.event("main_joined", telegram_id=user.id, data={"kind": "free" if status == "free_invite" else "appeal"})
        return
    await ban_from_chat(chat_id, user.id, "unauthorized_main_join")


@router.message(F.new_chat_members)
async def new_members_message(message: Message) -> None:
    main = await main_group_id()
    if not main or message.chat.id != main:
        return
    try:
        await message.delete()
    except Exception:
        pass
    for member in message.new_chat_members:
        await handle_main_join(message.chat.id, member)


@router.chat_member()
async def chat_member_changed(update: ChatMemberUpdated) -> None:
    main = await main_group_id()
    if not main or update.chat.id != main:
        return
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status
    user = update.new_chat_member.user
    if new_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        await handle_main_join(update.chat.id, user)
        return
    if new_status == ChatMemberStatus.LEFT and old_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and not user.is_bot:
        row = await get_user(user.id)
        if not row:
            return
        if row["status"] == "premium_member":
            await db.execute(
                "UPDATE users SET status='premium_left',left_access_lost_at=now(),updated_at=now() WHERE telegram_id=$1",
                user.id,
            )
            await revoke_active_invites(user.id)
            await safe_send(user.id, texts.PREMIUM_LEFT, request_new_link_kb())
            await db.event("premium_left", telegram_id=user.id)
        elif row["status"] in {"temporary_member", "member_validated"}:
            await db.execute(
                "UPDATE users SET status='free_left',banned=true,left_access_lost_at=now(),updated_at=now() WHERE telegram_id=$1",
                user.id,
            )
            await revoke_active_invites(user.id)
            await ban_from_publicity_groups(user.id, "free_member_left")
            await safe_send(user.id, "Vous avez quitté le groupe principal. Votre accès est maintenant perdu.")
            await db.event("free_member_left", telegram_id=user.id)


def group_media(message: Message) -> tuple[str | None, str | None, str | None]:
    if message.photo:
        photo = message.photo[-1]
        return "photo", photo.file_id, photo.file_unique_id
    if message.video:
        return "video", message.video.file_id, message.video.file_unique_id
    return None, None, None


async def temporary_group_notice(message: Message, text: str, seconds: int = 20) -> None:
    try:
        notice = await message.reply(text)
        await schedule_delete(message.chat.id, notice.message_id, seconds)
    except Exception:
        pass


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_messages(message: Message) -> None:
    await register_group(message.chat)
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    row = await get_user(user_id)
    group_type = await db.fetchval("SELECT type FROM groups WHERE chat_id=$1", message.chat.id)
    if row and row["banned"] and not is_admin(user_id):
        try:
            await message.delete()
        except Exception:
            pass
        if group_type in {"pub", "main"}:
            await ban_from_chat(message.chat.id, user_id, "blocked_user_in_configured_group")
        return
    main = await main_group_id()
    if not main or message.chat.id != main:
        return
    if not is_admin(user_id) and (
        contains_external_reference(message.text, message.entities)
        or contains_external_reference(message.caption, message.caption_entities)
    ):
        try:
            await message.delete()
        except Exception:
            pass
        now = utcnow()
        if not row or not row["last_link_warning_at"] or now - row["last_link_warning_at"] >= timedelta(hours=1):
            await safe_send(user_id, texts.LINK_WARNING)
            await db.execute("UPDATE users SET last_link_warning_at=now() WHERE telegram_id=$1", user_id)
        await db.event("link_deleted", telegram_id=user_id)
        return
    if not row or row["status"] not in {"temporary_member", "member_validated", "premium_member"}:
        return
    media_type, _, unique_id = group_media(message)
    if not media_type:
        if row["status"] == "temporary_member" and any(
            (message.document, message.animation, message.sticker, message.video_note, message.voice)
        ):
            await temporary_group_notice(message, texts.FORMAT_NOT_COUNTED)
        return
    if row["status"] == "temporary_member" and row["joined_main_at"]:
        received_at = message.date or utcnow()
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        first_deadline = row["joined_main_at"] + timedelta(minutes=3)
        quota_deadline = row["joined_main_at"] + timedelta(hours=24)
        if not row["first_media_at"] and received_at >= first_deadline:
            # Ne jamais compter un envoi tardif. Le planificateur applique la
            # sanction quelques secondes plus tard, ce qui laisse terminer un
            # éventuel événement Telegram reçu juste avant la limite.
            return
        if int(row["valid_media_count"] or 0) < int(row["declared_total"] or 0) and received_at >= quota_deadline:
            return
    inserted = await db.fetchval(
        """
        INSERT INTO media_hashes(telegram_id,chat_id,message_id,file_unique_id,media_type,counted)
        VALUES($1,$2,$3,$4,$5,true)
        ON CONFLICT(file_unique_id) DO NOTHING RETURNING id
        """,
        user_id,
        message.chat.id,
        message.message_id,
        unique_id,
        media_type,
    )
    if not inserted:
        if row["status"] == "temporary_member":
            current = await get_user(user_id)
            await temporary_group_notice(
                message,
                texts.duplicate_media(int(current["valid_media_count"] or 0), int(current["declared_total"] or 0)),
            )
        await db.event("duplicate_media", telegram_id=user_id)
        return
    if row["status"] != "temporary_member":
        return
    updated = await db.fetchrow(
        """
        UPDATE users SET valid_media_count=valid_media_count+1,
          first_media_at=COALESCE(first_media_at,now()),updated_at=now()
        WHERE telegram_id=$1 AND status='temporary_member'
        RETURNING valid_media_count,declared_total,joined_main_at,progress_milestone
        """,
        user_id,
    )
    if not updated:
        return
    valid = int(updated["valid_media_count"] or 0)
    quota = int(updated["declared_total"] or 0)
    deadline = updated["joined_main_at"] + timedelta(hours=24)
    if valid == 1:
        await safe_send(user_id, texts.first_media_accepted(valid, quota, format_datetime(deadline)))
    milestone = next_progress_milestone(valid, quota, int(updated["progress_milestone"] or 0))
    if milestone:
        changed = await db.fetchval(
            """
            UPDATE users SET progress_milestone=$2 WHERE telegram_id=$1 AND progress_milestone<$2
            RETURNING progress_milestone
            """,
            user_id,
            milestone,
        )
        if changed:
            await safe_send(user_id, texts.progress_update(valid, quota, format_datetime(deadline)))
    if quota and valid >= quota:
        completed = await db.fetchval(
            """
            UPDATE users SET status='member_validated',updated_at=now()
            WHERE telegram_id=$1 AND status='temporary_member' RETURNING telegram_id
            """,
            user_id,
        )
        if completed:
            await safe_send(user_id, texts.quota_complete(valid, quota))
            display_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
            public = await bot.send_message(message.chat.id, f"✅ {display_name} a complété son quota.")
            await schedule_delete(message.chat.id, public.message_id, 120)
            await db.event("quota_completed", telegram_id=user_id, data={"quota": quota, "valid": valid})


async def process_scheduled_deletions() -> None:
    rows = await db.fetch(
        "SELECT id,chat_id,message_id,attempts FROM scheduled_deletions WHERE delete_at<=now() ORDER BY delete_at LIMIT 100"
    )
    for row in rows:
        try:
            await bot.delete_message(int(row["chat_id"]), int(row["message_id"]))
            await db.execute("DELETE FROM scheduled_deletions WHERE id=$1", row["id"])
        except (TelegramBadRequest, TelegramForbiddenError):
            await db.execute("DELETE FROM scheduled_deletions WHERE id=$1", row["id"])
        except Exception:
            if int(row["attempts"] or 0) >= 2:
                await db.execute("DELETE FROM scheduled_deletions WHERE id=$1", row["id"])
            else:
                await db.execute(
                    "UPDATE scheduled_deletions SET attempts=attempts+1,delete_at=now()+interval '1 minute' WHERE id=$1",
                    row["id"],
                )


async def process_quota_deadlines() -> None:
    rows = await db.fetch(
        """
        SELECT telegram_id,joined_main_at,first_media_at,declared_total,valid_media_count,
          first_warning_sent,quota_warning_sent
        FROM users
        WHERE status='temporary_member' AND joined_main_at IS NOT NULL
          AND (
            (first_media_at IS NULL AND joined_main_at<=now()-interval '2 minutes')
            OR
            (valid_media_count<declared_total AND joined_main_at<=now()-interval '23 hours')
          )
        """
    )
    now = utcnow()
    for row in rows:
        user_id = int(row["telegram_id"])
        joined = row["joined_main_at"]
        valid = int(row["valid_media_count"] or 0)
        quota = int(row["declared_total"] or 0)
        first_deadline = joined + timedelta(minutes=3)
        quota_deadline = joined + timedelta(hours=24)
        if not row["first_media_at"]:
            if now >= joined + timedelta(minutes=2) and now < first_deadline and not row["first_warning_sent"]:
                claimed = await db.fetchval(
                    """
                    UPDATE users SET first_warning_sent=true WHERE telegram_id=$1
                    AND status='temporary_member' AND first_warning_sent=false RETURNING telegram_id
                    """,
                    user_id,
                )
                if claimed:
                    await safe_send(user_id, texts.first_deadline_warning(format_datetime(first_deadline)))
            # Cinq secondes laissent finir un média reçu juste avant l'échéance.
            # Le gestionnaire de médias compare toujours l'heure Telegram exacte
            # et refuse donc immédiatement un envoi réellement tardif.
            if now >= first_deadline + timedelta(seconds=5):
                claimed = await db.fetchval(
                    """
                    UPDATE users SET status='failed_no_activity',banned=true,
                      flow_state=NULL,flow_data='{}'::jsonb,appeal_available=true,updated_at=now()
                    WHERE telegram_id=$1 AND status='temporary_member'
                      AND first_media_at IS NULL
                      AND joined_main_at+interval '3 minutes'<=now()
                    RETURNING telegram_id
                    """,
                    user_id,
                )
                if claimed:
                    await safe_send(user_id, texts.NO_FIRST_MEDIA, appeal_kb())
                    await apply_ban_side_effects(
                        user_id,
                        "failed_no_activity",
                        "no_first_media_3min",
                        include_main=True,
                    )
                continue
        if valid < quota and now >= quota_deadline - timedelta(hours=1) and now < quota_deadline and not row["quota_warning_sent"]:
            claimed = await db.fetchval(
                """
                UPDATE users SET quota_warning_sent=true WHERE telegram_id=$1
                AND status='temporary_member' AND quota_warning_sent=false RETURNING telegram_id
                """,
                user_id,
            )
            if claimed:
                await safe_send(user_id, texts.quota_warning(valid, quota, format_datetime(quota_deadline)))
        if valid < quota and now >= quota_deadline + timedelta(seconds=5):
            claimed = await db.fetchval(
                """
                UPDATE users SET status='failed_quota',banned=true,
                  flow_state=NULL,flow_data='{}'::jsonb,appeal_available=true,updated_at=now()
                WHERE telegram_id=$1 AND status='temporary_member'
                  AND valid_media_count<declared_total
                  AND joined_main_at+interval '24 hours'<=now()
                RETURNING telegram_id
                """,
                user_id,
            )
            if claimed:
                await safe_send(user_id, texts.quota_failed(valid, quota), appeal_kb())
                await apply_ban_side_effects(
                    user_id,
                    "failed_quota",
                    "quota_24h_failed",
                    include_main=True,
                )


async def expire_invites() -> None:
    rows = await db.fetch(
        "SELECT id,chat_id,invite_link FROM invite_links WHERE status='active' AND expires_at<=now() LIMIT 100"
    )
    for row in rows:
        try:
            await bot.revoke_chat_invite_link(int(row["chat_id"]), row["invite_link"])
        except Exception:
            pass
        await db.execute("UPDATE invite_links SET status='expired',revoked_at=now() WHERE id=$1", row["id"])


async def detect_abandonments() -> None:
    rows = await db.fetch(
        """
        SELECT telegram_id,flow_state FROM users
        WHERE flow_state IS NOT NULL AND updated_at<now()-interval '5 hours'
          AND (abandonment_state IS NULL OR abandonment_state<>flow_state)
        LIMIT 100
        """
    )
    for row in rows:
        await db.execute("UPDATE users SET abandonment_state=$2 WHERE telegram_id=$1", row["telegram_id"], row["flow_state"])
        await db.event("abandoned", telegram_id=int(row["telegram_id"]), data={"flow_state": row["flow_state"]})


async def recover_stale_admin_actions() -> None:
    await db.execute(
        """
        UPDATE new_link_requests
        SET status='pending',admin_decision_by=NULL,processing_at=NULL
        WHERE status='processing' AND processing_at<now()-interval '5 minutes'
        """
    )


async def process_auto_ad() -> None:
    if await db.get_setting("auto_pub_enabled", "0") != "1":
        return
    try:
        interval = max(1, int(await db.get_setting("auto_pub_interval_minutes", "60")))
    except ValueError:
        interval = 60
    raw_last = await db.get_setting("last_auto_pub_at", "")
    last = None
    try:
        last = datetime.fromisoformat(raw_last) if raw_last else None
    except ValueError:
        pass
    if not last or utcnow() - last >= timedelta(minutes=interval):
        await publish_all_ads()


async def cleanup_old_data() -> None:
    raw = await db.get_setting("last_cleanup_at", "")
    try:
        last = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        last = None
    if last and utcnow() - last < timedelta(hours=24):
        return
    await db.execute("DELETE FROM logs WHERE level='info' AND created_at<now()-interval '30 days'")
    await db.execute("DELETE FROM logs WHERE level IN ('warning','error') AND created_at<now()-interval '90 days'")
    await db.execute("DELETE FROM analytics_events WHERE created_at<now()-interval '365 days'")
    await db.execute("DELETE FROM scheduled_deletions WHERE delete_at<now()-interval '7 days'")
    await db.execute(
        """
        UPDATE payments SET proof_file_id=NULL
        WHERE proof_file_id IS NOT NULL AND decided_at IS NOT NULL
          AND (
            (status='rejected' AND decided_at<now()-interval '30 days')
            OR
            (status='validated' AND decided_at<now()-interval '90 days')
          )
        """
    )
    await db.execute(
        """
        UPDATE applications SET gallery_file_id=NULL,gallery_unique_id=NULL,
          sample_file_id=NULL,sample_unique_id=NULL
        WHERE status IN ('approved','rejected','banned')
          AND (gallery_file_id IS NOT NULL OR sample_file_id IS NOT NULL)
          AND decision_at<now()-interval '30 days'
        """
    )
    await db.execute(
        """
        DELETE FROM invite_links
        WHERE status<>'active'
          AND COALESCE(revoked_at,used_at,expires_at,created_at)<now()-interval '90 days'
        """
    )
    await db.execute(
        """
        DELETE FROM new_link_requests
        WHERE status IN ('completed','rejected')
          AND decided_at<now()-interval '90 days'
        """
    )
    await db.set_setting("last_cleanup_at", utcnow().isoformat())


async def scheduler_loop() -> None:
    while True:
        try:
            await db.set_setting("scheduler_heartbeat", utcnow().isoformat())
            await process_scheduled_deletions()
            await process_quota_deadlines()
            await expire_invites()
            await detect_abandonments()
            await recover_stale_admin_actions()
            await process_auto_ad()
            await cleanup_old_data()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await db.log("scheduler_error", data={"error": str(exc)}, level="error")
            except Exception:
                pass
        await asyncio.sleep(config.scheduler_interval_seconds)


async def main() -> None:
    await db.connect()
    if config.auto_migrate:
        await db.migrate()
    me = await bot.get_me()
    await bot.delete_webhook(drop_pending_updates=False)
    await db.log("bot_started", data={"username": me.username, "scheduler_interval": config.scheduler_interval_seconds})
    scheduler = asyncio.create_task(scheduler_loop(), name="single-scheduler")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.cancel()
        try:
            await scheduler
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
