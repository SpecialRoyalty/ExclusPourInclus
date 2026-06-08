import asyncio
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from PIL import Image
import imagehash

from .config import load_config
from .db import Database
from .keyboards import *

config = load_config()
db = Database(config.database_url)
bot = Bot(config.bot_token)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

URL_RE = re.compile(r'(https?://|t\.me/|telegram\.me/|www\.|@[A-Za-z0-9_]{4,})', re.I)

class BlockBannedMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        if user and not is_admin(user.id):
            try:
                row = await db.fetchrow('SELECT banned,status FROM users WHERE telegram_id=$1', user.id)
                if row and row['banned']:
                    # Exception contrôlée : les utilisateurs bannis pour absence/quota peuvent répondre
                    # à une relance d'appel, mais uniquement via le bouton/message dédié.
                    if isinstance(event, CallbackQuery) and event.data == 'appeal:start':
                        return await handler(event, data)
                    if isinstance(event, Message) and event.chat.type == 'private' and row['status'] == 'appeal_required':
                        return await handler(event, data)
                    if isinstance(event, CallbackQuery):
                        await event.answer('Accès bloqué.', show_alert=True)
                        return
                    if isinstance(event, Message) and event.chat.type == 'private':
                        await event.answer('Votre accès est bloqué.')
                        return
                    # En groupe, on laisse passer pour que le handler puisse supprimer/bannir.
            except Exception:
                pass
        return await handler(event, data)

class Apply(StatesGroup):
    language = State()
    profile = State()
    buyer_regular = State()
    origin = State()
    creators = State()
    total = State()
    proof = State()

class Feedback(StatesGroup):
    waiting_text = State()

class HalfUpload(StatesGroup):
    waiting_media = State()

class VipFlow(StatesGroup):
    provider = State()
    media_count = State()

class AdminMedia(StatesGroup):
    waiting_photo = State()

class AdminText(StatesGroup):
    waiting_text = State()

class AdminBroadcast(StatesGroup):
    waiting_vip_broadcast_text = State()


class PaymentProof(StatesGroup):
    waiting_proof = State()

class PaymentReject(StatesGroup):
    waiting_reason = State()


def is_admin(uid: int) -> bool:
    return uid in config.admin_ids

router.callback_query.middleware(BlockBannedMiddleware())
router.message.middleware(BlockBannedMiddleware())

async def ensure_user(obj: Message | CallbackQuery):
    u = obj.from_user
    await db.execute('''
        INSERT INTO users(telegram_id, username, first_name) VALUES($1,$2,$3)
        ON CONFLICT (telegram_id) DO UPDATE SET username=$2, first_name=$3, updated_at=now()
    ''', u.id, u.username, u.first_name)

async def get_setting(key: str, default: str = '') -> str:
    val = await db.fetchval('SELECT value FROM settings WHERE key=$1', key)
    return val if val is not None else default

async def set_setting(key: str, value: str):
    await db.execute('''
        INSERT INTO settings(key,value,updated_at) VALUES($1,$2,now())
        ON CONFLICT(key) DO UPDATE SET value=$2, updated_at=now()
    ''', key, value)

async def notify_admins(text: str, **kwargs):
    for aid in config.admin_ids:
        try:
            await bot.send_message(aid, text, **kwargs)
        except Exception:
            pass

async def delete_previous_flow_message(user_id: int):
    row = await db.fetchrow('SELECT flow_chat_id, flow_message_id FROM users WHERE telegram_id=$1', user_id)
    if not row or not row['flow_chat_id'] or not row['flow_message_id']:
        return
    try:
        await bot.delete_message(int(row['flow_chat_id']), int(row['flow_message_id']))
    except Exception:
        pass

async def send_flow(user_id: int, chat_id: int, text: str, reply_markup=None, image_setting: str | None = None, replace: bool = False):
    # replace=True sert uniquement aux écrans persistants (/start ou panel admin).
    # Les autres messages du bot ne sont plus supprimés automatiquement.
    if replace:
        await delete_previous_flow_message(user_id)
    image_file_id = await get_setting(image_setting, '') if image_setting else ''
    if image_file_id:
        msg = await bot.send_photo(chat_id, image_file_id, caption=text, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    if replace:
        await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', user_id, chat_id, msg.message_id)
    return msg

async def update_flow(c: CallbackQuery, text: str, reply_markup=None, image_setting: str | None = None):
    image_file_id = await get_setting(image_setting, '') if image_setting else ''
    if image_file_id:
        await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup, image_setting, replace=True)
        return
    try:
        if c.message.photo:
            await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup, replace=True)
        else:
            await c.message.edit_text(text, reply_markup=reply_markup)
            await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', c.from_user.id, c.message.chat.id, c.message.message_id)
    except TelegramBadRequest:
        await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup, replace=True)

async def user_status(uid: int) -> str:
    return await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', uid) or 'new'

async def clean_user_message(m: Message):
    try:
        await m.delete()
    except Exception:
        pass

async def show_admin_panel(chat_id: int, user_id: int):
    await send_flow(user_id, chat_id, 'Panneau admin', reply_markup=admin_panel_kb(), replace=True)


async def register_detected_group(chat):
    if getattr(chat, 'type', None) not in {'group', 'supergroup'}:
        return
    existing = await db.fetchrow('SELECT type FROM groups WHERE chat_id=$1', chat.id)
    if existing:
        await db.execute('UPDATE groups SET title=$2, updated_at=now() WHERE chat_id=$1', chat.id, chat.title or '')
    else:
        await db.execute("INSERT INTO groups(chat_id,title,type,active,targeted) VALUES($1,$2,'detected',true,false)", chat.id, chat.title or '')

# ---------- START / ONBOARDING ----------

@router.message(Command('start'))
async def start(m: Message, state: FSMContext):
    await ensure_user(m)
    await clean_user_message(m)
    await state.clear()
    u = await db.fetchrow('SELECT banned,status FROM users WHERE telegram_id=$1', m.from_user.id)
    if u and u['banned']:
        await send_flow(m.from_user.id, m.chat.id, 'Votre accès est bloqué.', replace=True)
        return
    if is_admin(m.from_user.id):
        await show_admin_panel(m.chat.id, m.from_user.id)
        return

    status = u['status'] if u else 'new'
    attempts = await db.fetchval('SELECT attempts FROM users WHERE telegram_id=$1', m.from_user.id) or 0

    # Un membre déjà accepté ne peut pas relancer le formulaire.
    if status in {'member_validated', 'premium_validated', 'vip_validated', 'temporary_member'}:
        await send_flow(
            m.from_user.id,
            m.chat.id,
            '✅ Votre accès est déjà validé.\n\nVous êtes déjà intégré au groupe principal. Il n’est pas possible de recommencer le formulaire.',
            replace=True,
        )
        return

    # Candidature déjà validée mais règles/lien pas encore terminés : on reprend au bon endroit.
    if status == 'validated':
        await send_flow(
            m.from_user.id,
            m.chat.id,
            'Votre candidature est déjà validée.\n\nVeuillez terminer l’acceptation des règles pour recevoir votre lien.',
            reply_markup=rules_kb(1),
            replace=True,
        )
        return

    if status == 'half_required':
        half_required = await db.fetchval('SELECT half_required FROM users WHERE telegram_id=$1', m.from_user.id) or 1
        half_count = await db.fetchval('SELECT half_media_count FROM users WHERE telegram_id=$1', m.from_user.id) or 0
        await send_flow(m.from_user.id, m.chat.id, f'Votre candidature est pré-validée.\n\nEnvoyez ici vos médias pour atteindre le minimum immédiat demandé.\n\nProgression : {half_count}/{half_required}', replace=False)
        return

    # Une candidature ou preuve paiement déjà en cours ne doit pas créer une nouvelle instance.
    if status in {'proof_sent', 'premium_payment_pending', 'premium_payment_proof_waiting', 'half_review_pending'}:
        await send_flow(
            m.from_user.id,
            m.chat.id,
            'Votre demande est déjà en cours de vérification.\n\nMerci d’attendre la décision des admins.',
            replace=True,
        )
        return

    # Limite globale : 2 formulaires maximum.
    if attempts >= 2:
        await send_flow(
            m.from_user.id,
            m.chat.id,
            'Vous avez déjà utilisé vos 2 tentatives de formulaire.\n\nVous ne pouvez plus recommencer une candidature gratuite.',
            reply_markup=no_content_kb(),
            replace=True,
        )
        return

    await send_flow(
        m.from_user.id,
        m.chat.id,
        'Bienvenue.\n\nVous êtes sur le point de rejoindre une communauté privée réservée aux profils capables d’apporter du contenu inédit.\n\nLe processus d’accès est sélectif afin de préserver la qualité du groupe.',
        reply_markup=start_kb(),
        image_setting='welcome_image_file_id',
        replace=False,
    )

@router.callback_query(F.data == 'start:not_interested')
async def not_interested(c: CallbackQuery):
    await ensure_user(c)
    await db.execute("UPDATE users SET status='not_interested', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Aucun problème.\n\nUn accès premium peut être disponible si vous changez d’avis.\n\nVous pouvez aussi laisser un feedback si vous le souhaitez.', reply_markup=not_interested_kb())
    await c.answer()

@router.callback_query(F.data == 'feedback:start')
async def feedback_start(c: CallbackQuery, state: FSMContext):
    already = await db.fetchval('SELECT feedback_at FROM users WHERE telegram_id=$1', c.from_user.id)
    if already:
        await c.answer('Feedback déjà reçu.', show_alert=True)
        return
    await db.execute("UPDATE users SET status='feedback_waiting', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Vous pouvez envoyer un seul message pour expliquer pourquoi vous n’êtes pas intéressé.')
    await state.set_state(Feedback.waiting_text)
    await c.answer()

@router.message(Feedback.waiting_text)
async def feedback_receive(m: Message, state: FSMContext):
    text = (m.text or m.caption or '').strip()[:1000]
    if not text:
        await m.answer('Merci d’envoyer un message texte.')
        return
    await db.execute("UPDATE users SET status='not_interested_feedback_sent', feedback_text=$2, feedback_at=now(), updated_at=now() WHERE telegram_id=$1", m.from_user.id, text)
    await db.log('not_interested_feedback', telegram_id=m.from_user.id, data={'text': text})
    await m.answer('✅ Merci pour votre retour.')
    await state.clear()

@router.callback_query(F.data == 'start:interested')
async def interested(c: CallbackQuery, state: FSMContext):
    await ensure_user(c)
    u = await db.fetchrow('SELECT status,attempts FROM users WHERE telegram_id=$1', c.from_user.id)
    status = u['status'] if u else 'new'
    attempts = u['attempts'] if u else 0
    if status in {'member_validated', 'premium_validated', 'vip_validated', 'temporary_member', 'validated'}:
        await update_flow(c, '✅ Votre accès est déjà validé.\n\nIl n’est pas possible de recommencer le formulaire.')
        await c.answer()
        return
    if attempts >= 2:
        await update_flow(c, 'Vous avez déjà utilisé vos 2 tentatives de formulaire.\n\nVous ne pouvez plus recommencer une candidature gratuite.', reply_markup=no_content_kb())
        await c.answer()
        return
    await db.execute("UPDATE users SET status='interested' WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Veuillez choisir votre langue.', reply_markup=languages_kb())
    await state.set_state(Apply.language)
    await c.answer()

@router.callback_query(F.data.startswith('lang:'))
async def language(c: CallbackQuery, state: FSMContext):
    lang = c.data.split(':', 1)[1]
    await db.execute("UPDATE users SET language=$2,status='language_chosen', updated_at=now() WHERE telegram_id=$1", c.from_user.id, lang)
    if lang != 'fr':
        messages = {
            'en': 'Only French users are accepted for now.',
            'es': 'Por ahora solo se aceptan personas francesas.',
            'it': 'Per il momento sono accettate solo persone francesi.',
            'ru': 'На данный момент принимаются только французы.',
            'ar': 'حالياً يتم قبول الأشخاص الفرنسيين فقط.',
        }
        await update_flow(c, messages.get(lang, 'Uniquement les personnes françaises sont acceptées pour le moment.'))
        await ban_user(c.from_user.id, reason='non_french_language')
        await state.clear()
        await c.answer('Accès refusé.')
        return
    await update_flow(c, 'Cette communauté est principalement francophone.\n\nMerci de répondre sérieusement aux prochaines étapes afin de préserver la qualité des accès.', reply_markup=continue_kb())
    await c.answer()

@router.callback_query(F.data == 'go:profile')
async def go_profile(c: CallbackQuery, state: FSMContext):
    await db.execute("UPDATE users SET status='profile_selecting', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Quel profil correspond le mieux au vôtre ?', reply_markup=profile_kb())
    await state.set_state(Apply.profile)
    await c.answer()

@router.callback_query(F.data.startswith('profile:'))
async def choose_profile(c: CallbackQuery, state: FSMContext):
    attempts = await db.fetchval('SELECT attempts FROM users WHERE telegram_id=$1', c.from_user.id) or 0
    if attempts >= 2:
        await update_flow(c, 'Vous avez déjà utilisé vos 2 tentatives de formulaire.\n\nVous ne pouvez plus recommencer une candidature gratuite.', reply_markup=no_content_kb())
        await state.clear()
        await c.answer()
        return
    p = c.data.split(':', 1)[1]
    await db.execute('UPDATE users SET profile_type=$2, updated_at=now() WHERE telegram_id=$1', c.from_user.id, p)
    if p == 'none':
        await db.execute("UPDATE users SET status='premium_proposed', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
        await update_flow(c, 'Les accès gratuits sont réservés aux membres capables de contribuer à la communauté.\n\nCertaines places premium payantes peuvent être ouvertes ultérieurement.', reply_markup=no_content_kb())
        await c.answer()
        return
    await state.update_data(profile_type=p)
    if p == 'supplier':
        await db.execute("UPDATE users SET status='buyer_regular_question', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
        await update_flow(c, 'Êtes-vous acheteur régulier de vidéos OF/MYM ?', reply_markup=buyer_regular_kb())
        await state.set_state(Apply.buyer_regular)
    else:
        await db.execute("UPDATE users SET status='origin_waiting', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
        await update_flow(c, 'Les médias obtenus uniquement par échange ne seront pas acceptés.\n\nQuelle est l’origine de vos médias ?')
        await state.set_state(Apply.origin)
    await c.answer()

@router.callback_query(F.data.startswith('buyer:'))
async def buyer_regular_answer(c: CallbackQuery, state: FSMContext):
    ans = c.data.split(':', 1)[1]
    if ans == 'no':
        attempts = await db.fetchval('SELECT attempts FROM users WHERE telegram_id=$1', c.from_user.id) or 0
        await db.execute("UPDATE users SET attempts=$2, status='rejected_not_regular_buyer', updated_at=now() WHERE telegram_id=$1", c.from_user.id, attempts + 1)
        remaining = max(0, 2 - (attempts + 1))
        await update_flow(c, f'Les accès gratuits sont réservés aux profils capables de contribuer réellement.\n\nTentatives restantes : {remaining}', reply_markup=no_content_kb())
        await state.clear()
        await c.answer()
        return
    await db.execute("UPDATE users SET status='total_waiting', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Combien de médias possédez-vous au total ?')
    await state.set_state(Apply.total)
    await c.answer()

@router.message(Apply.origin)
async def apply_origin(m: Message, state: FSMContext):
    origin = (m.text or '').strip()[:1000]
    if len(origin) < 3:
        await m.answer('Merci de préciser brièvement l’origine de vos médias.')
        return
    await state.update_data(origin=origin)
    await db.execute("UPDATE users SET origin_text=$2, status='total_waiting', updated_at=now() WHERE telegram_id=$1", m.from_user.id, origin)
    await send_flow(m.from_user.id, m.chat.id, 'Combien de médias exclusifs possédez-vous approximativement ?')
    await state.set_state(Apply.total)

@router.message(Apply.creators)
async def apply_creators(m: Message, state: FSMContext):
    await state.update_data(creators=m.text.strip())
    await send_flow(m.from_user.id, m.chat.id, 'Combien de médias exclusifs possédez-vous au total ?')
    await state.set_state(Apply.total)

async def parse_positive_int(m: Message) -> int | None:
    raw = (m.text or '').strip().replace(' ', '')
    if not raw.isdigit():
        await m.answer('Merci d’envoyer uniquement un nombre.')
        return None
    n = int(raw)
    if n <= 0:
        await m.answer('Le nombre doit être supérieur à 0.')
        return None
    if n > 10000:
        await m.answer('Nombre trop élevé. Merci d’envoyer une estimation réaliste.')
        return None
    return n

@router.message(Apply.total)
async def apply_total(m: Message, state: FSMContext):
    n = await parse_positive_int(m)
    if n is None:
        return
    await state.update_data(total=n)
    data = await state.get_data()
    await db.execute(
        "UPDATE users SET declared_total=$2, status='profile_filled', updated_at=now() WHERE telegram_id=$1",
        m.from_user.id, n,
    )
    await send_flow(
        m.from_user.id,
        m.chat.id,
        '⚠ Important\n\nLa communauté est principalement destinée aux contenus considérés comme exclusifs ou peu diffusés.\n\nLes médias déjà largement partagés, repostés ou facilement trouvables risquent d’être refusés.\n\nLes médias déjà présents dans la base du groupe peuvent être automatiquement détectés, non comptabilisés, et vous pouvez être banni.',
        reply_markup=ok_kb('quota:recap'),
    )

@router.callback_query(F.data == 'quota:recap')
async def quota_recap(c: CallbackQuery):
    u = await db.fetchrow('SELECT declared_total FROM users WHERE telegram_id=$1', c.from_user.id)
    await update_flow(c, f"Récapitulatif :\n\n📦 Médias déclarés : {u['declared_total']}\n\nConfirmez-vous ces informations ?", reply_markup=confirm_kb())
    await c.answer()

@router.callback_query(F.data == 'quota:edit')
async def quota_edit(c: CallbackQuery, state: FSMContext):
    await update_flow(c, 'Combien de médias exclusifs possédez-vous approximativement ?')
    await state.set_state(Apply.total)
    await c.answer()

@router.callback_query(F.data == 'quota:confirm')
async def quota_confirm(c: CallbackQuery, state: FSMContext):
    proof_img = await get_setting('proof_example_image_file_id')
    text = 'Pour protéger les membres de la communauté, une vérification est nécessaire.\n\nVeuillez envoyer UNE SEULE image/capture correspondant à l’exemple fourni par les admins.\n\n⚠ Confirmez que les informations déclarées sont exactes : une fausse déclaration, un repost ou une preuve incohérente peut entraîner un bannissement définitif.'
    await update_flow(c, text, image_setting='proof_example_image_file_id' if proof_img else None)
    await state.set_state(Apply.proof)
    await c.answer()

@router.message(Apply.proof)
async def apply_proof(m: Message, state: FSMContext):
    current_status = await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', m.from_user.id)
    if current_status == 'proof_sent':
        await m.answer('La preuve a déjà été reçue. Merci d’attendre la décision des admins.')
        await state.clear()
        return
    attempts = await db.fetchval('SELECT attempts FROM users WHERE telegram_id=$1', m.from_user.id) or 0
    if attempts >= 2:
        await send_flow(m.from_user.id, m.chat.id, 'Vous avez déjà utilisé vos 2 tentatives de formulaire.\n\nVous ne pouvez plus envoyer une nouvelle candidature gratuite.', reply_markup=no_content_kb())
        await state.clear()
        return
    file_id = None
    proof_type = 'photo'
    if m.photo:
        file_id = m.photo[-1].file_id
        proof_type = 'photo'
    elif m.document and (m.document.mime_type or '').startswith('image/'):
        file_id = m.document.file_id
        proof_type = 'document'
    if not file_id:
        await m.answer('Merci d’envoyer une seule image/capture comme preuve.')
        return
    app_id = await db.fetchval(
        "INSERT INTO applications(telegram_id,status,proof_file_id,proof_type) VALUES($1,'pending_admin',$2,$3) RETURNING id",
        m.from_user.id, file_id, proof_type,
    )
    await db.execute("UPDATE users SET status='proof_sent', attempts=attempts+1, updated_at=now() WHERE telegram_id=$1", m.from_user.id)
    u = await db.fetchrow('SELECT declared_total FROM users WHERE telegram_id=$1', m.from_user.id)
    caption = f"📥 Nouvelle candidature\n\n👤 Utilisateur : @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\n\n📦 Déclaré : {u['declared_total']} médias"
    for aid in config.admin_ids:
        try:
            if proof_type == 'photo':
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=admin_application_kb(app_id, m.from_user.id))
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=admin_application_kb(app_id, m.from_user.id))
        except Exception:
            await bot.send_message(aid, caption, reply_markup=admin_application_kb(app_id, m.from_user.id))
    await send_flow(m.from_user.id, m.chat.id, 'Votre candidature a été envoyée aux admins. Vous serez notifié après décision.')
    await state.clear()


def parse_money_value(raw: str) -> float:
    if not raw:
        return 0.0
    cleaned = raw.replace(',', '.').replace('€', '').replace('$', '').strip()
    match = re.search(r'\d+(?:\.\d+)?', cleaned)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except Exception:
        return 0.0

async def premium_text() -> str:
    price = await get_setting('premium_price', '25€')
    paypal = await get_setting('paypal_link', '')
    usdt = await get_setting('usdt_address', '')
    lines = [
        '💰 Accès premium',
        '',
        f'Prix : {price or '25€'}',
        '',
        'Paiement :',
    ]
    if paypal:
        lines.append(f'PayPal : {paypal}')
    if usdt:
        lines.append(f'USDT TRC20 : {usdt}')
    if not paypal and not usdt:
        lines.append('Aucun moyen de paiement configuré pour le moment.')
    lines += [
        '',
        'Après paiement, cliquez sur le bouton ci-dessous et envoyez une capture/preuve de paiement.',
    ]
    return '\n'.join(lines)

@router.callback_query(F.data == 'premium:access')
async def premium_access(c: CallbackQuery):
    await db.execute("UPDATE users SET status='premium_requested' WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, await premium_text(), reply_markup=premium_info_kb())
    await c.answer()

@router.callback_query(F.data == 'premium:proof')
async def premium_proof(c: CallbackQuery, state: FSMContext):
    await db.execute("UPDATE users SET status='premium_payment_proof_waiting' WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Envoyez maintenant votre preuve de paiement : capture d’écran, image ou document.\n\nUn admin vérifiera ensuite votre paiement.')
    await state.set_state(PaymentProof.waiting_proof)
    await c.answer()

@router.message(PaymentProof.waiting_proof)
async def receive_payment_proof(m: Message, state: FSMContext):
    file_id = None
    proof_type = 'photo'
    if m.photo:
        file_id = m.photo[-1].file_id
        proof_type = 'photo'
    elif m.document:
        file_id = m.document.file_id
        proof_type = 'document'
    if not file_id:
        await m.answer('Merci d’envoyer une image ou un document comme preuve de paiement.')
        return

    price = await get_setting('premium_price', '')
    amount = parse_money_value(price)
    payment_id = await db.fetchval(
        "INSERT INTO payments(telegram_id,amount,status,proof_file_id,proof_type) VALUES($1,$2,'pending',$3,$4) RETURNING id",
        m.from_user.id, amount, file_id, proof_type,
    )
    await db.execute("UPDATE users SET status='premium_payment_pending' WHERE telegram_id=$1", m.from_user.id)

    caption = (
        f"💰 Preuve de paiement premium\n\n"
        f"👤 Utilisateur : @{m.from_user.username or '-'}\n"
        f"🆔 ID : {m.from_user.id}\n"
        f"💵 Prix : {price or 'non configuré'}\n"
        f"🧾 Paiement ID : {payment_id}"
    )
    for aid in config.admin_ids:
        try:
            if proof_type == 'photo':
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=admin_payment_kb(payment_id, m.from_user.id))
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=admin_payment_kb(payment_id, m.from_user.id))
        except Exception:
            await bot.send_message(aid, caption, reply_markup=admin_payment_kb(payment_id, m.from_user.id))

    await send_flow(m.from_user.id, m.chat.id, '✅ Votre preuve de paiement a été envoyée aux admins. Vous serez notifié après vérification.')
    await state.clear()

@router.callback_query(F.data.startswith('pay:'))
async def payment_decision(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True); return
    _, action, payment_id, user_id = c.data.split(':')
    payment_id, user_id = int(payment_id), int(user_id)
    current_status = await db.fetchval('SELECT status FROM payments WHERE id=$1', payment_id)
    if current_status != 'pending':
        await c.answer('Paiement déjà traité.', show_alert=True)
        await safe_mark_admin_message(c, f'ℹ️ Déjà traité : {current_status}')
        return
    if action == 'approve':
        await db.execute("UPDATE payments SET status='validated', decided_at=now() WHERE id=$1", payment_id)
        amount = await db.fetchval('SELECT amount FROM payments WHERE id=$1', payment_id) or 0
        if float(amount) > 0:
            await db.execute('INSERT INTO pot_transactions(amount, reason, created_by) VALUES($1,$2,$3)', amount, f'premium_payment_{payment_id}', c.from_user.id)
            old = parse_money_value(await get_setting('pot_balance', '0'))
            await set_setting('pot_balance', str(round(old + float(amount), 2)))
        await grant_premium_access(user_id)
        await safe_mark_admin_message(c, '✅ Paiement validé')
        await c.answer('Paiement validé.', show_alert=True)
    elif action == 'reject':
        await state.update_data(payment_id=payment_id, user_id=user_id, admin_message_chat_id=c.message.chat.id, admin_message_id=c.message.message_id)
        await c.message.answer('Motif du refus ? Envoyez le message à transmettre à l’utilisateur.')
        await state.set_state(PaymentReject.waiting_reason)
        await c.answer()

@router.message(PaymentReject.waiting_reason)
async def payment_reject_reason(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    data = await state.get_data()
    payment_id = int(data.get('payment_id'))
    user_id = int(data.get('user_id'))
    reason = (m.text or '').strip() or 'Preuve de paiement refusée.'
    await db.execute("UPDATE payments SET status='rejected', decided_at=now() WHERE id=$1", payment_id)
    await db.execute("UPDATE users SET status='premium_payment_rejected' WHERE telegram_id=$1", user_id)
    try:
        await bot.send_message(user_id, f'❌ Votre preuve de paiement a été refusée.\n\nMotif : {reason}\n\nVous pouvez renvoyer une nouvelle preuve si nécessaire.', reply_markup=no_content_kb())
    except Exception:
        pass
    try:
        await bot.delete_message(int(data.get('admin_message_chat_id')), int(data.get('admin_message_id')))
    except Exception:
        pass
    await m.answer('✅ Refus envoyé à l’utilisateur.')
    await state.clear()

async def grant_premium_access(user_id: int, status: str = 'premium_validated'):
    main = await get_setting('main_group', '')
    await db.execute("UPDATE users SET status=$2, updated_at=now() WHERE telegram_id=$1", user_id, status)
    if not main:
        try:
            await bot.send_message(user_id, '✅ Paiement validé. Le groupe principal n’est pas encore configuré, un admin vous recontactera.')
        except Exception:
            pass
        return
    try:
        invite = await bot.create_chat_invite_link(
            int(main),
            member_limit=1,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
            creates_join_request=False,
        )
        await db.execute('INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)', user_id, int(main), invite.invite_link, user_id, datetime.now(timezone.utc)+timedelta(hours=48))
        await bot.send_message(user_id, '✅ Paiement validé.\n\nVoici votre lien personnel, limité à un seul usage et valable 48h.', reply_markup=url_kb('🔗 Rejoindre le groupe principal', invite.invite_link))
    except Exception as e:
        await db.log('premium_invite_failed', telegram_id=user_id, data={'error': str(e)}, level='error')
        try:
            await bot.send_message(user_id, '✅ Paiement validé, mais le lien n’a pas pu être généré automatiquement. Un admin vous recontactera.')
        except Exception:
            pass

@router.callback_query(F.data == 'premium:vip')
async def vip_access(c: CallbackQuery, state: FSMContext):
    await db.execute("UPDATE users SET status='vip_provider_waiting', updated_at=now() WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Vous avez déjà payé un VIP sur Telegram ?\n\nChez qui avez-vous payé ce VIP ?')
    await state.set_state(VipFlow.provider)
    await c.answer()

@router.message(VipFlow.provider)
async def vip_provider(m: Message, state: FSMContext):
    provider = (m.text or '').strip()[:500]
    if len(provider) < 2:
        await m.answer('Merci d’indiquer chez qui vous avez payé le VIP.')
        return
    await state.update_data(vip_provider=provider)
    await db.execute("UPDATE users SET status='vip_media_count_waiting', updated_at=now() WHERE telegram_id=$1", m.from_user.id)
    await m.answer('Combien de médias environ contient ce VIP ?')
    await state.set_state(VipFlow.media_count)

@router.message(VipFlow.media_count)
async def vip_media_count(m: Message, state: FSMContext):
    n = await parse_positive_int(m)
    if n is None:
        return
    data = await state.get_data()
    provider = data.get('vip_provider', '')

    # Nouveau flow VIP simplifié : pas de validation admin, pas de lien VIP généré.
    # L'utilisateur contacte directement @op75x15 pour l'extraction.
    # On garde le statut vip_waiting pour permettre le broadcast VIP coupe-file plus tard.
    await db.execute("UPDATE users SET status='vip_waiting', updated_at=now() WHERE telegram_id=$1", m.from_user.id)
    await db.log('vip_request_recorded', telegram_id=m.from_user.id, data={'provider': provider, 'media_count': n})

    await m.answer(
        "✅ Informations reçues.\n\n"
        "🎟 Vérification VIP\n\n"
        "Pour finaliser la vérification, contactez directement @op75x15 afin de réaliser une extraction.\n\n"
        f"VIP indiqué : {provider}\n"
        f"Médias annoncés : {n}\n\n"
        "C'est trop long ? Vous pouvez aussi rejoindre immédiatement via l'accès premium.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💰 Accès premium (25€)', callback_data='premium:access')],
            [InlineKeyboardButton(text='⬅️ Retour', callback_data='profile:none')],
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith('vipdec:'))
async def vip_decision_disabled(c: CallbackQuery):
    # Ancien système VIP désactivé : il n'y a plus de validation VIP dans le bot.
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True)
        return
    await safe_mark_admin_message(c, 'ℹ️ Ancien bouton VIP désactivé. Le VIP se traite hors bot via @op75x15.')
    await c.answer('Le système VIP est maintenant hors bot.', show_alert=True)

@router.callback_query(F.data == 'vip:continue')
async def vip_continue(c: CallbackQuery):
    await c.answer('Contactez @op75x15 pour la vérification VIP.', show_alert=True)

# ---------- ADMIN PANEL ----------

@router.callback_query(F.data == 'admin:home')
async def admin_home(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True); return
    await state.clear()
    await update_flow(c, 'Panneau admin', reply_markup=admin_panel_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:pub')
async def admin_pub(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    enabled = await get_setting('auto_pub_enabled', '0') == '1'
    await update_flow(c, '📢 Publicité\n\n• Publier la publicité maintenant\n• Activer/désactiver l’auto-publication\n• Voir et cibler les groupes publicité\n• Modifier le texte de publicité', reply_markup=pub_menu_kb(enabled))
    await c.answer()

@router.callback_query(F.data == 'admin:images')
async def admin_images(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    await update_flow(c, '🖼 Gestion des images\n\nChoisissez quelle image modifier. Envoyez ensuite une photo au bot.', reply_markup=images_menu_kb())
    await c.answer()

@router.callback_query(F.data.startswith('image:set:'))
async def image_set(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id): return
    key = c.data.split(':', 2)[2]
    labels = {
        'ad_image_file_id': 'publicité',
        'welcome_image_file_id': 'accueil bot',
        'proof_example_image_file_id': 'exemple preuve',
    }
    await state.update_data(setting_key=key)
    await update_flow(c, f'Envoyez maintenant l’image à utiliser pour : {labels.get(key, key)}.')
    await state.set_state(AdminMedia.waiting_photo)
    await c.answer()

@router.message(AdminMedia.waiting_photo)
async def receive_admin_image(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    if not m.photo:
        await m.answer('Envoyez une photo, pas un texte ni un fichier.')
        return
    data = await state.get_data()
    key = data.get('setting_key')
    if not key:
        await state.clear(); return
    await set_setting(key, m.photo[-1].file_id)
    await send_flow(m.from_user.id, m.chat.id, f'✅ Image enregistrée pour `{key}`.', reply_markup=images_menu_kb())
    await state.clear()

@router.callback_query(F.data == 'image:delete_menu')
async def image_delete_menu(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    await update_flow(c, 'Quelle image supprimer ?', reply_markup=image_delete_kb())
    await c.answer()

@router.callback_query(F.data.startswith('image:delete:'))
async def image_delete(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    key = c.data.split(':', 2)[2]
    await db.execute('DELETE FROM settings WHERE key=$1', key)
    await update_flow(c, f'✅ Image supprimée : {key}', reply_markup=images_menu_kb())
    await c.answer()

@router.callback_query(F.data == 'image:preview')
async def image_preview(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    keys = [
        ('Image publicité', 'ad_image_file_id'),
        ('Image accueil', 'welcome_image_file_id'),
        ('Image preuve', 'proof_example_image_file_id'),
    ]
    sent = 0
    for label, key in keys:
        fid = await get_setting(key, '')
        if fid:
            try:
                await bot.send_photo(c.message.chat.id, fid, caption=label)
                sent += 1
            except Exception:
                pass
    if sent == 0:
        await c.answer('Aucune image configurée.', show_alert=True)
    else:
        await c.answer(f'{sent} image(s) envoyée(s).')

@router.callback_query(F.data == 'admin:groups')
async def admin_groups(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    await update_flow(c, '👥 Groupes\n\nLe bot détecte automatiquement les groupes dans lesquels il reçoit un message ou dans lesquels il est ajouté. Choisissez ensuite le rôle de chaque groupe ici.', reply_markup=groups_menu_kb())
    await c.answer()

async def render_group_list(c: CallbackQuery):
    rows = await db.fetch("SELECT chat_id,title,type,active,targeted FROM groups ORDER BY CASE type WHEN 'main' THEN 0 WHEN 'pub' THEN 1 ELSE 2 END, title")
    if not rows:
        await update_flow(c, 'Aucun groupe détecté. Ajoutez le bot dans un groupe puis envoyez un message dans ce groupe pour qu’il apparaisse ici.', reply_markup=groups_menu_kb())
        return
    text = '📋 Groupes détectés\n\nCliquez sur un groupe pour choisir son rôle : principal, publicité, ciblé ou non.'
    keyboard = []
    for r in rows:
        icon = '⭐' if r['type'] == 'main' else ('📢' if r['type'] == 'pub' else '⚪')
        target = ' ☑' if r['type'] == 'pub' and r['targeted'] else ''
        keyboard.append([(f"{icon} {r['title'] or r['chat_id']}{target}", f"group:open:{r['chat_id']}")])
    keyboard.append([('⬅️ Retour panel', 'admin:home')])
    await update_flow(c, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t,d in row] for row in keyboard]))

@router.callback_query(F.data.startswith('group:'))
async def group_actions(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    parts = c.data.split(':')
    action = parts[1]
    if action == 'list':
        await render_group_list(c)
    elif action == 'open' and len(parts) == 3:
        chat_id = int(parts[2])
        r = await db.fetchrow('SELECT chat_id,title,type,targeted FROM groups WHERE chat_id=$1', chat_id)
        if not r:
            await c.answer('Groupe introuvable.', show_alert=True); return
        text = f"👥 {r['title'] or r['chat_id']}\n\nRôle actuel : {r['type']}\nCiblé pub : {'oui' if r['targeted'] else 'non'}"
        await update_flow(c, text, reply_markup=group_row_kb(chat_id, r['type']=='pub', r['type']=='main', bool(r['targeted'])))
    elif action in {'set_main','add_pub','remove_pub','toggle_target'} and len(parts) == 3:
        chat_id = int(parts[2])
        if action == 'set_main':
            # Un seul groupe principal à la fois. L’ancien principal redevient détecté.
            await db.execute("UPDATE groups SET type='detected', targeted=false, updated_at=now() WHERE type='main'")
            await db.execute("UPDATE groups SET type='main', active=true, targeted=false, updated_at=now() WHERE chat_id=$1", chat_id)
            await set_setting('main_group', str(chat_id))
            await c.answer('Groupe principal défini.', show_alert=True)
        elif action == 'add_pub':
            await db.execute("UPDATE groups SET type='pub', active=true, targeted=true, updated_at=now() WHERE chat_id=$1", chat_id)
            await c.answer('Groupe publicité ajouté.', show_alert=True)
        elif action == 'remove_pub':
            await db.execute("UPDATE groups SET type='detected', targeted=false, updated_at=now() WHERE chat_id=$1", chat_id)
            await c.answer('Groupe retiré des pubs.', show_alert=True)
        elif action == 'toggle_target':
            await db.execute("UPDATE groups SET targeted=NOT targeted, updated_at=now() WHERE chat_id=$1 AND type='pub'", chat_id)
            await c.answer('Ciblage modifié.', show_alert=True)
        await render_group_list(c)
    else:
        await c.answer('Action inconnue.', show_alert=True)
    await c.answer()

@router.callback_query(F.data.startswith('text:set:'))
async def set_text_cb(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id): return
    key = c.data.split(':', 2)[2]
    labels = {
        'ad_text': 'le texte de publicité',
        'premium_price': 'le prix premium',
        'paypal_link': 'le PayPal / lien PayPal',
        'usdt_address': 'l’adresse USDT',
        'auto_pub_interval_minutes': 'la fréquence de publicité en minutes',
    }
    await state.update_data(setting_key=key)
    if key == 'auto_pub_interval_minutes':
        current = await get_setting('auto_pub_interval_minutes', '10')
        await update_flow(c, f'⏱ Fréquence publicité\n\nFréquence actuelle : {current} minute(s).\n\nEnvoyez la nouvelle fréquence en minutes. Exemple : 30, 60, 180.')
    else:
        await update_flow(c, f'Envoyez maintenant {labels.get(key, key)}.')
    await state.set_state(AdminText.waiting_text)
    await c.answer()

@router.message(AdminText.waiting_text)
async def receive_admin_text(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    data = await state.get_data()
    key = data.get('setting_key')
    if not key:
        await state.clear(); return
    value = (m.text or '').strip()
    if key == 'auto_pub_interval_minutes':
        try:
            minutes = int(value)
            if minutes < 1 or minutes > 10080:
                raise ValueError
        except ValueError:
            await m.answer('Envoyez un nombre entier de minutes entre 1 et 10080.')
            return
        await set_setting(key, str(minutes))
        await send_flow(m.from_user.id, m.chat.id, f'✅ Fréquence publicité enregistrée : {minutes} minute(s).', reply_markup=pub_menu_kb(await get_setting('auto_pub_enabled','0')=='1'))
        await state.clear()
        return
    await set_setting(key, value)
    if key in {'premium_price', 'paypal_link', 'usdt_address'}:
        await send_flow(m.from_user.id, m.chat.id, f'✅ Réglage paiement enregistré : {key}.', reply_markup=payments_menu_kb())
    elif key == 'ad_text':
        await send_flow(m.from_user.id, m.chat.id, '✅ Texte de publicité enregistré.', reply_markup=pub_menu_kb(await get_setting('auto_pub_enabled','0')=='1'))
    else:
        await send_flow(m.from_user.id, m.chat.id, f'✅ Réglage enregistré : {key}.', reply_markup=admin_panel_kb())
    await state.clear()

# ---------- PUBLICITY ----------

async def publish_ad(chat_id: int):
    # Mode propre : une seule publicité visible par groupe.
    # Avant d'envoyer la nouvelle pub, on supprime l'ancienne si elle existe.
    row = await db.fetchrow('SELECT last_ad_message_id FROM groups WHERE chat_id=$1', chat_id)
    if row and row['last_ad_message_id']:
        try:
            await bot.delete_message(chat_id, int(row['last_ad_message_id']))
        except Exception as e:
            # Message déjà supprimé / trop ancien / permissions manquantes : on continue.
            await db.log('delete_previous_ad_failed', chat_id=chat_id, data={'message_id': int(row['last_ad_message_id']), 'error': str(e)}, level='warning')

    text = await get_setting('ad_text')
    image = await get_setting('ad_image_file_id', '')
    me = await bot.get_me()
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔗 Accéder au groupe privé', url=f'https://t.me/{me.username}?start=ad')]])
    if image:
        msg = await bot.send_photo(chat_id, image, caption=text, reply_markup=markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=markup)
    await db.execute('UPDATE groups SET last_ad_message_id=$2, updated_at=now() WHERE chat_id=$1', chat_id, msg.message_id)

async def publish_to_targets() -> int:
    rows = await db.fetch("SELECT chat_id FROM groups WHERE type='pub' AND active=true AND targeted=true")
    sent = 0
    for r in rows:
        try:
            await publish_ad(int(r['chat_id']))
            sent += 1
        except Exception as e:
            await db.log('publish_ad_failed', chat_id=int(r['chat_id']), data={'error': str(e)}, level='error')
    return sent

@router.callback_query(F.data == 'pub:now')
async def pub_now_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    sent = await publish_to_targets()
    await c.answer(f'Publicité envoyée dans {sent} groupe(s).', show_alert=True)

@router.callback_query(F.data == 'pub:auto_toggle')
async def auto_toggle(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    enabled = await get_setting('auto_pub_enabled', '0') == '1'
    await set_setting('auto_pub_enabled', '0' if enabled else '1')
    await update_flow(c, f"Auto pub {'désactivée' if enabled else 'activée'}.", reply_markup=pub_menu_kb(not enabled))
    await c.answer()

@router.callback_query(F.data == 'pub:targets')
async def pub_targets(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    rows = await db.fetch("SELECT chat_id,title,targeted FROM groups WHERE type='pub' ORDER BY title")
    if not rows:
        await update_flow(c, 'Aucun groupe publicité configuré. Allez dans 👥 Groupes puis définissez au moins un groupe comme publicité.', reply_markup=pub_menu_kb(await get_setting('auto_pub_enabled','0')=='1'))
        await c.answer(); return
    keyboard = []
    for r in rows:
        mark = '☑' if r['targeted'] else '☐'
        keyboard.append([(f"{mark} {r['title'] or r['chat_id']}", f"pub:toggle_target:{r['chat_id']}")])
    keyboard.append([('⬅️ Retour publicité', 'admin:pub')])
    await update_flow(c, '🎯 Groupes ciblés pour la publicité', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t,d in row] for row in keyboard]))
    await c.answer()

@router.callback_query(F.data.startswith('pub:toggle_target:'))
async def pub_toggle_target(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    chat_id = int(c.data.split(':')[-1])
    await db.execute('UPDATE groups SET targeted=NOT targeted, updated_at=now() WHERE chat_id=$1', chat_id)
    await pub_targets(c)

# ---------- APPLICATION DECISION / RULES ----------

@router.callback_query(F.data.startswith('app:'))
async def app_decision(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True); return
    _, action, app_id, user_id = c.data.split(':')
    app_id, user_id = int(app_id), int(user_id)
    app_status = await db.fetchval('SELECT status FROM applications WHERE id=$1', app_id)
    if app_status != 'pending_admin':
        await c.answer('Candidature déjà traitée.', show_alert=True)
        await safe_mark_admin_message(c, f'ℹ️ Déjà traité : {app_status}')
        return
    if action == 'approve':
        await db.execute("UPDATE applications SET status='approved',admin_decision_by=$2,decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        declared = await db.fetchval('SELECT declared_total FROM users WHERE telegram_id=$1', user_id) or 0
        half_required = max(1, (int(declared) + 1) // 2) if declared else 1
        await db.execute("""
            UPDATE users SET status='half_required', joined_main_at=NULL,
            first_media_at=NULL, valid_media_count=0, half_media_count=0, half_required=$2, updated_at=now()
            WHERE telegram_id=$1
        """, user_id, half_required)
        try:
            await bot.send_message(
                user_id,
                f'Votre candidature a été pré-validée.\n\nPour éviter les profils qui récupèrent les médias sans contribuer, vous devez maintenant envoyer ici au bot au moins la moitié de votre volume déclaré.\n\n📦 Déclaré : {declared}\n🎯 Minimum immédiat : {half_required} médias\n\nLes médias seront transmis aux admins pour validation de cohérence. Après validation, vous recevrez les règles puis le lien du groupe principal.'
            )
        except Exception:
            pass
        await safe_mark_admin_message(c, '✅ Pré-validé — attente 50%')
    elif action == 'reject':
        await db.execute("UPDATE applications SET status='rejected',admin_decision_by=$2,decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        await db.execute("UPDATE users SET status='rejected' WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, 'Votre profil ne correspond pas actuellement aux critères d’accès gratuit.\n\nVous pouvez demander un accès premium si cette option est disponible.', reply_markup=no_content_kb())
        except Exception:
            pass
        await safe_mark_admin_message(c, '❌ Refusé')
    elif action == 'ban':
        await ban_user(user_id, reason='admin_application_ban')
        await safe_mark_admin_message(c, '🚫 Banni')
    await c.answer()

async def safe_mark_admin_message(c: CallbackQuery, suffix: str):
    # Après décision admin, on nettoie la candidature pour ne pas polluer le chat admin.
    try:
        await c.message.delete()
    except Exception:
        try:
            if c.message.caption:
                await c.message.edit_caption(c.message.caption + f'\n\n{suffix}')
            else:
                await c.message.edit_text((c.message.text or '') + f'\n\n{suffix}')
        except Exception:
            pass


# ---------- VIP BROADCAST ----------

# IMPORTANT: this block must stay BEFORE the generic private message handler.
# Otherwise the admin text typed for the broadcast is swallowed by the private media handler.

VIP_BROADCAST_STATUSES = (
    'vip_provider_waiting',
    'vip_media_count_waiting',
    'vip_waiting',
    'vip_rejected',
)

async def get_vip_broadcast_targets():
    return await db.fetch(
        """
        SELECT telegram_id, username, status
        FROM users
        WHERE banned=false
          AND status = ANY($1::text[])
        ORDER BY updated_at DESC
        """,
        list(VIP_BROADCAST_STATUSES),
    )

@router.callback_query(F.data == 'broadcast:vip_start')
async def vip_broadcast_start(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return
    targets = await get_vip_broadcast_targets()
    if not targets:
        await update_flow(c, '🎟 Broadcast VIP coupe-file\n\nAucun utilisateur éligible trouvé pour le moment.', reply_markup=moderation_menu_kb())
        await c.answer()
        return
    await state.clear()
    await state.update_data(vip_broadcast_count=len(targets))
    await update_flow(
        c,
        f'🎟 Broadcast VIP coupe-file\n\nUtilisateurs ciblés : {len(targets)}\n\nEnvoyez maintenant le message à diffuser en privé aux personnes ayant demandé un accès coupe-file VIP.',
        reply_markup=back_admin_kb(),
    )
    await state.set_state(AdminBroadcast.waiting_vip_broadcast_text)
    await c.answer()

@router.message(AdminBroadcast.waiting_vip_broadcast_text)
async def vip_broadcast_text_received(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    text = (m.text or m.caption or '').strip()
    if len(text) < 2:
        await m.answer('Envoyez un message texte valide pour le broadcast VIP.')
        return
    text = text[:3500]
    targets = await get_vip_broadcast_targets()
    await state.update_data(vip_broadcast_text=text, vip_broadcast_count=len(targets))
    preview = text if len(text) <= 1000 else text[:1000] + '\n…'
    await send_flow(
        m.from_user.id,
        m.chat.id,
        f'🎟 Broadcast VIP coupe-file\n\nCibles actuelles : {len(targets)} utilisateur(s)\n\nAperçu du message :\n\n{preview}\n\nConfirmer l’envoi ?',
        reply_markup=broadcast_confirm_kb(),
    )

@router.callback_query(F.data == 'broadcast:vip_cancel')
async def vip_broadcast_cancel(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return
    await state.clear()
    await update_flow(c, 'Broadcast VIP annulé.', reply_markup=moderation_menu_kb())
    await c.answer()

@router.callback_query(F.data == 'broadcast:vip_confirm')
async def vip_broadcast_confirm(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return
    data = await state.get_data()
    text = data.get('vip_broadcast_text')
    if not text:
        await c.answer('Aucun message à envoyer.', show_alert=True)
        await state.clear()
        return
    targets = await get_vip_broadcast_targets()
    sent = 0
    failed = 0
    failed_ids = []
    await update_flow(c, f'🎟 Broadcast VIP en cours…\n\nCibles : {len(targets)}')
    for r in targets:
        uid = int(r['telegram_id'])
        try:
            await bot.send_message(uid, text)
            sent += 1
            await db.execute('UPDATE users SET updated_at=now() WHERE telegram_id=$1', uid)
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            failed_ids.append(uid)
            await db.log('vip_broadcast_send_failed', telegram_id=uid, data={'error': str(e)}, level='warning')
    await db.log('vip_broadcast_sent', telegram_id=c.from_user.id, data={'sent': sent, 'failed': failed, 'failed_ids': failed_ids[:20]})
    await state.clear()
    await update_flow(
        c,
        f'✅ Broadcast VIP terminé.\n\nEnvoyés : {sent}\nÉchecs : {failed}',
        reply_markup=moderation_menu_kb(),
    )
    await c.answer()


# ---------- RELANCES ADMIN ----------

@router.callback_query(F.data == 'relaunch:half_pending')
async def relaunch_half_pending(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True)
        return
    targets = await db.fetch("""
        SELECT telegram_id, username, half_required, half_media_count
        FROM users
        WHERE status='half_required'
          AND COALESCE(free_relaunch_sent,false)=false
          AND COALESCE(half_media_count,0) < COALESCE(half_required,1)
          AND COALESCE(banned,false)=false
        ORDER BY updated_at ASC
        LIMIT 500
    """)
    if not targets:
        await update_flow(c, '📣 Relance pré-validés\n\nAucun utilisateur à relancer.\n\nSoit tout le monde a déjà reçu la relance, soit personne n’est en attente de médias 50%.', reply_markup=moderation_menu_kb())
        await c.answer()
        return
    sent, failed = 0, 0
    failed_ids = []
    for u in targets:
        uid = int(u['telegram_id'])
        required = u['half_required'] or 1
        count = u['half_media_count'] or 0
        try:
            await bot.send_message(
                uid,
                f'📣 Rappel candidature\n\nVotre accès gratuit a été pré-validé, mais vous n’avez pas encore envoyé le minimum demandé.\n\nProgression actuelle : {count}/{required}\n\nEnvoyez vos médias directement ici au bot pour continuer la vérification.',
            )
            await db.execute('UPDATE users SET free_relaunch_sent=true, updated_at=now() WHERE telegram_id=$1', uid)
            sent += 1
        except Exception as e:
            failed += 1
            failed_ids.append(uid)
            await db.log('half_pending_relaunch_failed', telegram_id=uid, data={'error': str(e)}, level='warning')
        await asyncio.sleep(0.04)
    await db.log('half_pending_relaunch_sent', telegram_id=c.from_user.id, data={'sent': sent, 'failed': failed, 'failed_ids': failed_ids[:30]})
    await update_flow(c, f'📣 Relance pré-validés terminée.\n\nUtilisateurs concernés : {len(targets)}\n✅ Envoyés : {sent}\n❌ Échecs : {failed}', reply_markup=moderation_menu_kb())
    await c.answer()


@router.callback_query(F.data == 'relaunch:appeal_banned')
async def relaunch_appeal_banned(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True)
        return
    targets = await db.fetch("""
        SELECT telegram_id, username, declared_total, status
        FROM users
        WHERE COALESCE(appeal_relaunch_sent,false)=false
          AND COALESCE(declared_total,0) > 0
          AND status IN ('failed_no_activity','failed_quota')
        ORDER BY updated_at DESC
        LIMIT 500
    """)
    if not targets:
        await update_flow(c, '🧾 Appel bannis quota\n\nAucun utilisateur à contacter.\n\nSoit la relance a déjà été envoyée, soit il n’y a aucun échec quota/activité éligible.', reply_markup=moderation_menu_kb())
        await c.answer()
        return
    sent, failed = 0, 0
    failed_ids = []
    for u in targets:
        uid = int(u['telegram_id'])
        declared = u['declared_total'] or 0
        try:
            await bot.send_message(
                uid,
                'Si vous pensez qu’il s’agit d’une erreur, vous pouvez demander un réexamen.\n\nPour être débanni de tous les groupes, vous devrez envoyer ici la totalité des médias déclarés.\n\nCette relance est unique.',
                reply_markup=appeal_start_kb(),
            )
            await db.execute('UPDATE users SET appeal_relaunch_sent=true, appeal_required=$2, updated_at=now() WHERE telegram_id=$1', uid, declared)
            sent += 1
        except Exception as e:
            failed += 1
            failed_ids.append(uid)
            await db.log('appeal_relaunch_failed', telegram_id=uid, data={'error': str(e)}, level='warning')
        await asyncio.sleep(0.04)
    await db.log('appeal_relaunch_sent', telegram_id=c.from_user.id, data={'sent': sent, 'failed': failed, 'failed_ids': failed_ids[:30]})
    await update_flow(c, f'🧾 Relance appel terminée.\n\nUtilisateurs concernés : {len(targets)}\n✅ Envoyés : {sent}\n❌ Échecs : {failed}', reply_markup=moderation_menu_kb())
    await c.answer()


@router.callback_query(F.data == 'appeal:start')
async def appeal_start(c: CallbackQuery, state: FSMContext):
    row = await db.fetchrow('SELECT declared_total,appeal_relaunch_sent,appeal_media_count,appeal_required FROM users WHERE telegram_id=$1', c.from_user.id)
    if not row or not row['appeal_relaunch_sent']:
        await c.answer('Aucun réexamen disponible.', show_alert=True)
        return
    required = row['appeal_required'] or row['declared_total'] or 1
    count = row['appeal_media_count'] or 0
    await db.execute("UPDATE users SET status='appeal_required', banned=false, appeal_required=$2, updated_at=now() WHERE telegram_id=$1", c.from_user.id, required)
    await update_flow(c, f'🧾 Réexamen ouvert\n\nEnvoyez ici la totalité de vos médias pour vérification.\n\nProgression : {count}/{required}\n\nLes doublons ne seront pas comptés.')
    await state.clear()
    await c.answer()

# ---------- HALF UPLOAD / MAIN GROUP CONTRIBUTION ----------

async def private_media_from_message(m: Message):
    if m.photo:
        p = m.photo[-1]
        return 'photo', p.file_id, p.file_unique_id
    if m.video:
        return 'video', m.video.file_id, m.video.file_unique_id
    if m.document and (m.document.mime_type or '').startswith(('image/', 'video/')):
        return 'document', m.document.file_id, m.document.file_unique_id
    return None, None, None


@router.message(F.chat.type == 'private')
async def appeal_upload_private(m: Message):
    if m.from_user and is_admin(m.from_user.id):
        return
    row = await db.fetchrow('SELECT status,appeal_required,appeal_media_count,username FROM users WHERE telegram_id=$1', m.from_user.id)
    if not row or row['status'] != 'appeal_required':
        return
    media_type, file_id, unique_id = await private_media_from_message(m)
    if not media_type:
        await m.answer('Merci d’envoyer uniquement des médias pour le réexamen.')
        return
    exists = await db.fetchval('SELECT id FROM appeal_media WHERE telegram_id=$1 AND file_unique_id=$2', m.from_user.id, unique_id)
    if exists:
        await m.answer('Ce média a déjà été reçu et ne sera pas recompté.')
        return
    await db.execute('INSERT INTO appeal_media(telegram_id,file_id,file_unique_id,media_type,source_message_id) VALUES($1,$2,$3,$4,$5)', m.from_user.id, file_id, unique_id, media_type, m.message_id)
    await db.execute('UPDATE users SET appeal_media_count=appeal_media_count+1, updated_at=now() WHERE telegram_id=$1', m.from_user.id)
    count = await db.fetchval('SELECT appeal_media_count FROM users WHERE telegram_id=$1', m.from_user.id) or 0
    required = row['appeal_required'] or 1
    caption = f"🧾 Média réexamen déban\n\n👤 @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\nProgression : {count}/{required}"
    for aid in config.admin_ids:
        try:
            await bot.copy_message(chat_id=aid, from_chat_id=m.chat.id, message_id=m.message_id, caption=caption)
        except Exception as e:
            await db.log('appeal_media_send_admin_failed', telegram_id=m.from_user.id, data={'admin_id': aid, 'error': str(e)}, level='warning')
    if count >= required:
        await db.execute("UPDATE users SET status='appeal_review_pending', updated_at=now() WHERE telegram_id=$1", m.from_user.id)
        await m.answer('✅ Tous les médias demandés ont été reçus.\n\nLes admins vont vérifier votre demande de réexamen.')
        for aid in config.admin_ids:
            try:
                await bot.send_message(aid, f"🧾 Réexamen prêt\n\n👤 @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\nDéclaré : {required}\nReçu : {count}\n\nDécision admin requise.", reply_markup=admin_appeal_kb(m.from_user.id))
            except Exception:
                pass
    else:
        await m.answer(f'✅ Média reçu. Progression : {count}/{required}')


@router.callback_query(F.data.startswith('appeal:'))
async def appeal_decision(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True)
        return
    _, action, user_id = c.data.split(':')
    user_id = int(user_id)
    current_status = await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', user_id)
    if current_status != 'appeal_review_pending':
        await c.answer('Réexamen déjà traité ou inactif.', show_alert=True)
        await safe_mark_admin_message(c, f'ℹ️ Déjà traité : {current_status}')
        return
    if action == 'approve':
        ok, failed, errors = await unban_user_from_configured_groups(user_id)
        await db.execute("UPDATE users SET status='member_validated', banned=false, updated_at=now() WHERE telegram_id=$1", user_id)
        link = None
        try:
            link = await create_main_invite_for_user(user_id, hours=24)
        except Exception as e:
            await db.log('appeal_invite_failed', telegram_id=user_id, data={'error': str(e)}, level='error')
        try:
            if link:
                await bot.send_message(user_id, f'✅ Votre demande de réexamen a été acceptée.\n\nVous avez été débanni des groupes configurés. Voici un nouveau lien personnel valable 24h.', reply_markup=url_kb('🔗 Rejoindre le groupe principal', link))
            else:
                await bot.send_message(user_id, '✅ Votre demande de réexamen a été acceptée.\n\nVous avez été débanni des groupes configurés. Un admin vous renverra le lien du groupe principal.')
        except Exception:
            pass
        await safe_mark_admin_message(c, f'✅ Appel accepté\n\nDébans OK : {ok}\nÉchecs : {failed}')
        await c.answer('Appel accepté')
    elif action == 'reject':
        await db.execute("UPDATE users SET status='appeal_rejected', banned=true, updated_at=now() WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, '❌ Votre demande de réexamen a été refusée.')
        except Exception:
            pass
        await safe_mark_admin_message(c, '❌ Appel refusé')
        await c.answer('Refusé')
    elif action == 'ban':
        await ban_user(user_id, reason='appeal_ban')
        await safe_mark_admin_message(c, '🚫 Banni définitivement après appel')
        await c.answer('Banni')

@router.message(F.chat.type == 'private')
async def half_upload_private(m: Message):
    if m.from_user and is_admin(m.from_user.id):
        return
    row = await db.fetchrow('SELECT status,half_required,half_media_count,username FROM users WHERE telegram_id=$1', m.from_user.id)
    if not row or row['status'] != 'half_required':
        return
    media_type, file_id, unique_id = await private_media_from_message(m)
    if not media_type:
        await m.answer('Merci d’envoyer uniquement des médias pour la vérification de cohérence.')
        return
    exists = await db.fetchval('SELECT id FROM half_media WHERE telegram_id=$1 AND file_unique_id=$2', m.from_user.id, unique_id)
    if exists:
        await m.answer('Ce média a déjà été reçu et ne sera pas recompté.')
        return
    await db.execute('INSERT INTO half_media(telegram_id,file_id,file_unique_id,media_type,source_message_id) VALUES($1,$2,$3,$4,$5)', m.from_user.id, file_id, unique_id, media_type, m.message_id)
    await db.execute('UPDATE users SET half_media_count=half_media_count+1, updated_at=now() WHERE telegram_id=$1', m.from_user.id)
    count = await db.fetchval('SELECT half_media_count FROM users WHERE telegram_id=$1', m.from_user.id) or 0
    required = row['half_required'] or 1
    caption = f"📦 Média vérification 50%\n\n👤 @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\nProgression : {count}/{required}"
    # Envoi réel du média aux admins.
    # On utilise copy_message depuis le message original reçu en privé :
    # c'est plus fiable que ré-envoyer uniquement le file_id, et ça évite les pertes silencieuses.
    for aid in config.admin_ids:
        try:
            await bot.copy_message(
                chat_id=aid,
                from_chat_id=m.chat.id,
                message_id=m.message_id,
                caption=caption,
            )
            await db.log('half_media_sent_to_admin', telegram_id=m.from_user.id, data={'admin_id': aid, 'count': count, 'required': required})
        except Exception as e:
            await db.log('half_media_send_admin_failed', telegram_id=m.from_user.id, data={'admin_id': aid, 'error': str(e), 'count': count, 'required': required}, level='error')
            try:
                await bot.send_message(aid, f"⚠️ Impossible de copier un média 50% pour @{m.from_user.username or '-'} ({m.from_user.id}).\nErreur : {e}")
            except Exception:
                pass
    if count >= required:
        await db.execute("UPDATE users SET status='half_review_pending', updated_at=now() WHERE telegram_id=$1", m.from_user.id)
        await m.answer('✅ Minimum immédiat reçu.\n\nLes admins vont maintenant vérifier la cohérence de vos médias. Vous recevrez le lien du groupe après validation.')
        for aid in config.admin_ids:
            try:
                await bot.send_message(aid, f"✅ Vérification 50% prête\n\n👤 @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\nMédias reçus : {count}/{required}\n\nDécision admin requise.", reply_markup=half_review_kb(m.from_user.id))
            except Exception:
                pass
    else:
        await m.answer(f'✅ Média reçu. Progression : {count}/{required}')

@router.callback_query(F.data.startswith('half:'))
async def half_decision(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True)
        return
    _, action, user_id = c.data.split(':')
    user_id = int(user_id)
    current_status = await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', user_id)
    if current_status != 'half_review_pending':
        await c.answer('Validation 50% déjà traitée ou inactive.', show_alert=True)
        await safe_mark_admin_message(c, f'ℹ️ Déjà traité : {current_status}')
        return
    if action == 'approve':
        await db.execute("UPDATE users SET status='validated', updated_at=now() WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, '✅ Vos médias ont été jugés cohérents.\n\nAvant d’accéder au groupe principal, veuillez accepter les règles suivantes.', reply_markup=rules_kb(1))
        except Exception:
            pass
        await safe_mark_admin_message(c, '✅ 50% validé')
        await c.answer('Validé')
    elif action == 'reject':
        await db.execute("UPDATE users SET status='rejected_half', updated_at=now() WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, 'Votre vérification n’a pas été jugée cohérente.\n\nVous pouvez demander un accès premium si cette option est disponible.', reply_markup=no_content_kb())
        except Exception:
            pass
        await safe_mark_admin_message(c, '❌ 50% refusé')
        await c.answer('Refusé')
    elif action == 'ban':
        await ban_user(user_id, reason='half_review_ban')
        await safe_mark_admin_message(c, '🚫 Banni après 50%')
        await c.answer('Banni')

@router.callback_query(F.data.startswith('rule:'))
async def rules(c: CallbackQuery):
    n = int(c.data.split(':')[1])
    texts = {
        1: 'Le contact privé entre membres est interdit.',
        2: 'Le partage du lien entraîne une exclusion définitive.',
        3: 'Aucun lien externe n’est autorisé dans le groupe.',
        4: 'Vous devrez publier le volume déclaré immédiatement dans le groupe principal. Si aucune contribution valide n’est détectée rapidement, l’accès sera retiré.',
        
    }
    await update_flow(c, texts.get(n, 'Règle'), reply_markup=rules_kb(n+1))
    await c.answer()

@router.callback_query(F.data == 'rules:done')
async def rules_done(c: CallbackQuery):
    main = await get_setting('main_group', '')
    if not main:
        await update_flow(c, 'Le groupe principal n’est pas encore configuré. Contactez un admin.')
        await c.answer(); return
    try:
        invite = await bot.create_chat_invite_link(
            int(main),
            member_limit=1,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=24),
            creates_join_request=False,
        )
        await db.execute('INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)', c.from_user.id, int(main), invite.invite_link, c.from_user.id, datetime.now(timezone.utc)+timedelta(hours=24))
        await update_flow(c, 'Félicitations.\n\nVotre accès a été validé.\n\n⚠ Ce lien est personnel, limité à un seul usage, valable 24h et surveillé automatiquement.', reply_markup=url_kb('🔗 Rejoindre le groupe principal', invite.invite_link))
    except Exception as e:
        await update_flow(c, f'Erreur création lien. Vérifiez que le bot est admin du groupe principal.\n\n{e}')
    await c.answer()


async def get_main_group_id() -> int | None:
    main = await get_setting('main_group', '')
    return int(main) if main else None

async def unban_user_from_configured_groups(user_id: int):
    rows = await db.fetch("SELECT chat_id,title,type FROM groups WHERE active=true AND type IN ('pub','main')")
    ok, failed, errors = 0, 0, []
    for r in rows:
        try:
            await bot.unban_chat_member(int(r['chat_id']), user_id, only_if_banned=True)
            ok += 1
        except Exception as e:
            failed += 1
            errors.append({'chat_id': int(r['chat_id']), 'title': r['title'], 'error': str(e)})
            await db.log('appeal_unban_failed', telegram_id=user_id, chat_id=int(r['chat_id']), data={'error': str(e)}, level='warning')
    return ok, failed, errors

async def create_main_invite_for_user(user_id: int, hours: int = 24):
    main = await get_main_group_id()
    if not main:
        return None
    invite = await bot.create_chat_invite_link(
        main,
        member_limit=1,
        expire_date=datetime.now(timezone.utc) + timedelta(hours=hours),
        creates_join_request=False,
    )
    await db.execute(
        'INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)',
        user_id, main, invite.invite_link, user_id, datetime.now(timezone.utc)+timedelta(hours=hours),
    )
    return invite.invite_link

# ---------- GROUP MODERATION / MEDIA COUNT ----------

@router.my_chat_member()
async def on_bot_chat_member(update: ChatMemberUpdated):
    # Détection automatique quand le bot est ajouté à un groupe.
    try:
        await register_detected_group(update.chat)
    except Exception:
        pass


async def ban_user(user_id: int, reason: str = 'ban'):
    # Blacklist en base + bannissement uniquement dans les groupes publicité actifs.
    # Correction importante : Telegram refuse de retirer le créateur/propriétaire d'un groupe.
    # On vérifie donc le statut de la cible AVANT de bannir, et on log précisément la cause.
    await db.execute("UPDATE users SET banned=true,status='banned',updated_at=now() WHERE telegram_id=$1", user_id)
    rows = await db.fetch("SELECT chat_id,title,type FROM groups WHERE active=true AND type='pub'")
    if not rows:
        await db.log(reason + '_no_publicity_groups_registered', telegram_id=user_id, level='warning')
        await notify_admins(f"⚠️ Ban pub utilisateur {user_id} : aucun groupe pub actif détecté. Va dans 👥 Groupes et marque au moins un groupe comme publicité.")
        return

    ok = 0
    skipped = 0
    failed = 0
    errors = []

    for r in rows:
        chat_id = int(r['chat_id'])
        title = r['title'] or str(chat_id)
        group_type = r['type']
        status = 'unknown'
        try:
            # 1) Vérifier que le bot a le droit de bannir dans CE groupe.
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if not bool(getattr(bot_member, 'can_restrict_members', False)):
                skipped += 1
                msg = f"{title}: bot sans permission de bannir"
                errors.append(msg)
                await db.log('group_ban_skipped_no_permission', telegram_id=user_id, chat_id=chat_id, data={'reason': reason, 'group_type': group_type, 'title': title}, level='warning')
                continue

            # 2) Vérifier le statut de la personne visée.
            # Si Telegram dit creator/owner, on ne tente pas le ban : c'est impossible.
            try:
                target_member = await bot.get_chat_member(chat_id, user_id)
                status = getattr(target_member, 'status', 'unknown')
                if status == ChatMemberStatus.CREATOR:
                    skipped += 1
                    msg = f"{title}: impossible, l'utilisateur est propriétaire/créateur de ce groupe"
                    errors.append(msg)
                    await db.log('group_ban_skipped_owner', telegram_id=user_id, chat_id=chat_id, data={'reason': reason, 'status': status, 'group_type': group_type, 'title': title}, level='warning')
                    continue
                if status == ChatMemberStatus.ADMINISTRATOR:
                    skipped += 1
                    msg = f"{title}: impossible, l'utilisateur est admin du groupe"
                    errors.append(msg)
                    await db.log('group_ban_skipped_admin', telegram_id=user_id, chat_id=chat_id, data={'reason': reason, 'status': status, 'group_type': group_type, 'title': title}, level='warning')
                    continue
            except Exception as member_error:
                # Si get_chat_member échoue, on tente quand même le ban : Telegram peut bannir un utilisateur non-présent.
                status = f"member_check_failed: {member_error}"

            # 3) Bannir.
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id, revoke_messages=False)
            ok += 1
            await db.log('group_ban_success', telegram_id=user_id, chat_id=chat_id, data={'reason': reason, 'status_before': status, 'group_type': group_type, 'title': title})
        except Exception as e:
            failed += 1
            err = str(e)
            # Message plus clair pour le cas fréquent Telegram : can't remove chat owner.
            if "can't remove chat owner" in err.lower():
                err = "Telegram refuse : l'utilisateur est propriétaire/créateur de ce groupe, ou Telegram le voit comme tel. Impossible de le retirer par bot."
            errors.append(f"{title}: {err}")
            await db.log('group_ban_failed', telegram_id=user_id, chat_id=chat_id, data={'reason': reason, 'error': err, 'status_before': status, 'group_type': group_type, 'title': title}, level='error')

    await db.log(reason, telegram_id=user_id, data={'groups_ok': ok, 'groups_skipped': skipped, 'groups_failed': failed})
    if failed or skipped:
        details = '\n'.join(errors[:8])
        await notify_admins(
            f"⚠️ Ban partiel pour {user_id}\n\n"
            f"✅ Groupes publicité bannis : {ok}\n"
            f"⏭️ Groupes ignorés : {skipped}\n"
            f"❌ Échecs : {failed}\n\n"
            f"Détails :\n{details}"
        )

async def ban_from_chat(chat_id: int, user_id: int, reason: str):
    # Ban définitif dans un chat précis : pas de unban derrière.
    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id, revoke_messages=False)
        await db.log(reason, telegram_id=user_id, chat_id=chat_id, data={'ban_type': 'permanent_chat_ban'})
    except Exception as e:
        await db.log(reason + '_failed', telegram_id=user_id, chat_id=chat_id, data={'error': str(e)}, level='error')


async def handle_main_group_join(chat_id: int, member):
    """Traite l’arrivée d’un utilisateur dans le groupe principal.

    On l’appelle depuis deux sources :
    - message service new_chat_members ;
    - update chat_member.

    Cela évite le bug où Telegram ne déclenche pas toujours le message service
    selon le type de groupe / client / paramètres du groupe.
    """
    main = await get_setting('main_group', '')
    if not main or str(chat_id) != str(main):
        return
    if getattr(member, 'is_bot', False):
        return

    u = await db.fetchrow('SELECT status,declared_total,attempts,banned FROM users WHERE telegram_id=$1', member.id)
    await db.log('main_group_join_detected', telegram_id=member.id, chat_id=chat_id, data={'status': u['status'] if u else None, 'banned': bool(u['banned']) if u else None})

    allowed_statuses = {'validated', 'temporary_member', 'premium_validated', 'vip_validated', 'member_validated'}
    if not u or u['banned'] or u['status'] not in allowed_statuses:
        await ban_from_chat(chat_id, member.id, 'ban_join_without_validation')
        return

    # Idempotence importante : Telegram peut déclencher à la fois new_chat_members
    # et chat_member pour la même entrée. Si le premier handler a déjà transformé
    # premium_validated/vip_validated en member_validated, le second ne doit jamais
    # bannir la personne. Il ne fait rien.
    if u['status'] == 'member_validated':
        await db.log('main_group_join_already_validated_ignored', telegram_id=member.id, chat_id=chat_id)
        return

    if u['status'] in {'premium_validated', 'vip_validated'}:
        await db.execute("UPDATE users SET status='member_validated', joined_main_at=now(), updated_at=now() WHERE telegram_id=$1", member.id)
        try:
            await bot.send_message(member.id, '✅ Vous êtes entré dans le groupe principal.\n\nVotre accès premium/VIP est validé. Bienvenue.')
        except Exception as e:
            await db.log('premium_private_welcome_failed', telegram_id=member.id, chat_id=chat_id, data={'error': str(e)}, level='warning')
        try:
            msg = await bot.send_message(chat_id, f"Bienvenue @{member.username or member.first_name}.\n\n✅ Accès premium/VIP validé.")
            await asyncio.sleep(180)
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except Exception:
                pass
        except Exception as e:
            await db.log('premium_welcome_message_failed', telegram_id=member.id, chat_id=chat_id, data={'error': str(e)}, level='error')
        return

    await db.execute("UPDATE users SET status='temporary_member', joined_main_at=COALESCE(joined_main_at, now()), first_media_at=NULL, valid_media_count=0, updated_at=now() WHERE telegram_id=$1", member.id)
    private_text = (
        f"✅ Vous êtes entré dans le groupe principal.\n\n"
        f"📦 Déclaration : {u['declared_total']} médias.\n\n"
        "Vous devez maintenant publier tous les médias déclarés lors de votre candidature.\n\nVous disposez d’un délai court pour commencer : si aucune contribution valide n’est détectée sous 10 minutes, l’accès sera retiré définitivement.\n\n"
        "Les doublons, reposts ou contenus déjà présents ne seront pas comptabilisés."
    )
    try:
        await bot.send_message(member.id, private_text)
    except Exception as e:
        await db.log('main_group_private_welcome_failed', telegram_id=member.id, chat_id=chat_id, data={'error': str(e)}, level='warning')

    try:
        msg = await bot.send_message(
            chat_id,
            f"Bienvenue @{member.username or member.first_name}\n\n"
            f"📦 Déclaration : {u['declared_total']} médias.\n\n"
            "Vous devez maintenant publier tous les médias déclarés lors de votre candidature.\n\n⚠ Si aucune contribution valide n’est détectée sous 10 minutes, l’accès sera retiré définitivement.\n\n"
            "⚠ Les doublons, reposts ou contenus déjà présents ne seront pas comptabilisés."
        )
        await db.log('main_group_welcome_sent', telegram_id=member.id, chat_id=chat_id, data={'declared_total': u['declared_total']})
        await asyncio.sleep(180)
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except Exception:
            pass
    except Exception as e:
        await db.log('main_group_welcome_failed', telegram_id=member.id, chat_id=chat_id, data={'error': str(e)}, level='error')


@router.message(F.new_chat_members)
async def on_new_members(m: Message):
    main = await get_setting('main_group', '')
    if not main or str(m.chat.id) != str(main):
        return
    try:
        await m.delete()
    except Exception:
        pass
    for member in m.new_chat_members:
        await handle_main_group_join(m.chat.id, member)


@router.chat_member()
async def on_chat_member_update(update: ChatMemberUpdated):
    """Fallback robuste pour détecter l’arrivée dans le groupe principal.

    Certains groupes/clients ne montrent pas toujours le message service
    new_chat_members comme prévu. Cette update permet de traiter aussi le
    changement de statut vers member.
    """
    main = await get_setting('main_group', '')
    if not main or str(update.chat.id) != str(main):
        return
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status
    user = update.new_chat_member.user
    if new_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        await handle_main_group_join(update.chat.id, user)
        return
    # Option B : départ volontaire du groupe principal = accès perdu.
    if new_status == ChatMemberStatus.LEFT and old_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED} and not getattr(user, 'is_bot', False):
        row = await db.fetchrow('SELECT status,banned FROM users WHERE telegram_id=$1', user.id)
        if row and not row['banned'] and row['status'] in {'temporary_member','member_validated','premium_validated','vip_validated'}:
            await db.execute("UPDATE users SET status='left_access_lost', banned=true, left_access_lost_at=now(), updated_at=now() WHERE telegram_id=$1", user.id)
            await db.log('main_group_left_access_lost', telegram_id=user.id, chat_id=update.chat.id)
            try:
                await bot.send_message(user.id, 'Vous avez quitté le groupe principal. Votre accès est maintenant perdu.')
            except Exception:
                pass


async def extract_media_ids(m: Message):
    if m.photo:
        p = m.photo[-1]
        return 'photo', p.file_id, p.file_unique_id
    if m.video:
        return 'video', m.video.file_id, m.video.file_unique_id
    if m.document and (m.document.mime_type or '').startswith(('image/', 'video/')):
        return 'document', m.document.file_id, m.document.file_unique_id
    return None, None, None

async def perceptual_hash(file_id: str) -> str | None:
    try:
        f = await bot.get_file(file_id)
        bio = BytesIO()
        await bot.download_file(f.file_path, bio)
        bio.seek(0)
        img = Image.open(bio).convert('RGB')
        return str(imagehash.phash(img))
    except Exception:
        return None

@router.message(F.chat.type.in_({'group','supergroup'}))
async def group_messages(m: Message):
    await register_detected_group(m.chat)
    if m.from_user and not m.from_user.is_bot:
        banned_row = await db.fetchrow('SELECT banned FROM users WHERE telegram_id=$1', m.from_user.id)
        if banned_row and banned_row['banned']:
            try:
                await m.delete()
            except Exception:
                pass
            gtype = await db.fetchval('SELECT type FROM groups WHERE chat_id=$1', m.chat.id)
            # Les utilisateurs blacklistés sont expulsés automatiquement uniquement des groupes pub.
            # Le groupe principal est géré par les règles d'entrée/quota dédiées.
            if gtype == 'pub':
                try:
                    await bot.ban_chat_member(chat_id=m.chat.id, user_id=m.from_user.id, revoke_messages=False)
                    await db.log('banned_user_pub_group_ban_success', telegram_id=m.from_user.id, chat_id=m.chat.id)
                except Exception as e:
                    await db.log('banned_user_pub_group_ban_failed', telegram_id=m.from_user.id, chat_id=m.chat.id, data={'error': str(e)}, level='error')
            return
    main = await get_setting('main_group', '')
    if not main or str(m.chat.id) != str(main):
        return
    if m.from_user and m.from_user.is_bot:
        return
    if (m.text and URL_RE.search(m.text)) or (m.caption and URL_RE.search(m.caption)):
        try: await m.delete()
        except Exception: pass
        return
    media_type, file_id, unique_id = await extract_media_ids(m)
    if not media_type or not m.from_user:
        return
    uid = m.from_user.id
    user = await db.fetchrow('SELECT status,declared_total,attempts,joined_main_at,valid_media_count,banned FROM users WHERE telegram_id=$1', uid)
    if not user or user['banned']:
        return
    if user['status'] not in {'temporary_member','validated','member_validated'}:
        return
    if not user['joined_main_at']:
        await db.execute("UPDATE users SET joined_main_at=now(), status='temporary_member' WHERE telegram_id=$1", uid)
    exists = await db.fetchval('SELECT id FROM media_hashes WHERE file_unique_id=$1', unique_id)
    counted = not bool(exists)
    ph = None
    if counted and media_type == 'photo':
        ph = await perceptual_hash(file_id)
        if ph:
            similar = await db.fetchval('SELECT id FROM media_hashes WHERE perceptual_hash=$1 LIMIT 1', ph)
            if similar:
                counted = False
    try:
        await db.execute('INSERT INTO media_hashes(telegram_id,chat_id,message_id,file_unique_id,perceptual_hash,media_type,counted) VALUES($1,$2,$3,$4,$5,$6,$7)', uid, m.chat.id, m.message_id, unique_id, ph, media_type, counted)
    except Exception:
        counted = False
    if counted:
        await db.execute('UPDATE users SET valid_media_count=valid_media_count+1, first_media_at=COALESCE(first_media_at,now()), updated_at=now() WHERE telegram_id=$1', uid)
        total = await db.fetchval('SELECT declared_total FROM users WHERE telegram_id=$1', uid) or 0
        valid = await db.fetchval('SELECT valid_media_count FROM users WHERE telegram_id=$1', uid) or 0
        if total and valid >= total:
            await db.execute("UPDATE users SET status='member_validated',updated_at=now() WHERE telegram_id=$1", uid)
            try:
                await bot.send_message(uid, '✅ Contribution complétée.\n\nVotre accès est maintenant définitivement validé.')
            except Exception:
                pass
            await db.log('quota_completed', telegram_id=uid, chat_id=m.chat.id, data={'total': total, 'valid': valid})

# ---------- PAYMENTS / MODERATION ----------


@router.callback_query(F.data == 'premium:repair_victims')
async def repair_premium_victims(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        return
    main = await get_setting('main_group', '')
    if not main:
        await c.message.answer('❌ Groupe principal non configuré.', reply_markup=back_admin_kb())
        await c.answer()
        return
    # Corrige les utilisateurs premium lésés par l’ancien bug : paiement validé
    # mais utilisateur banni/blacklisté ou passé dans un statut d’échec quota.
    rows = await db.fetch("""
        SELECT DISTINCT u.telegram_id
        FROM users u
        JOIN payments p ON p.telegram_id = u.telegram_id
        WHERE p.status='validated'
          AND (
            COALESCE(u.banned,false)=true
            OR u.status IN ('failed_no_activity','failed_quota','left_access_lost','premium_payment_pending','premium_payment_rejected')
            OR u.status NOT IN ('premium_validated','vip_validated','member_validated')
          )
        UNION
        SELECT telegram_id
        FROM users
        WHERE COALESCE(banned,false)=true AND status IN ('premium_validated','vip_validated')
    """)
    if not rows:
        await c.message.answer('✅ Aucun premium/VIP lésé à réparer.', reply_markup=back_admin_kb())
        await c.answer()
        return
    concerned = len(rows)
    unban_ok = 0
    unban_failed = 0
    links_sent = 0
    send_failed = 0
    failed_ids = []

    await c.message.answer(
        f'♻️ Réparation premium lancée.\n\n'
        f'Utilisateurs concernés : {concerned}\n\n'
        "Je débannis les comptes concernés du groupe principal et je renvoie un nouveau lien valable 48h."
    )

    for r in rows:
        uid = int(r['telegram_id'])
        try:
            # Ici le unban est volontaire : il répare uniquement un ban erroné passé.
            try:
                await bot.unban_chat_member(chat_id=int(main), user_id=uid, only_if_banned=True)
                unban_ok += 1
            except Exception as e:
                unban_failed += 1
                await db.log('premium_repair_unban_failed', telegram_id=uid, chat_id=int(main), data={'error': str(e)}, level='warning')

            await db.execute("""
                UPDATE users
                SET banned=false,
                    status='premium_validated',
                    joined_main_at=NULL,
                    first_media_at=NULL,
                    valid_media_count=0,
                    updated_at=now()
                WHERE telegram_id=$1
            """, uid)
            invite = await bot.create_chat_invite_link(
                int(main),
                member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
                creates_join_request=False,
            )
            await db.execute(
                'INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)',
                uid, int(main), invite.invite_link, uid, datetime.now(timezone.utc)+timedelta(hours=48)
            )
            try:
                await bot.send_message(
                    uid,
                    '✅ Correction effectuée.\n\nVotre accès premium a été réactivé. Voici un nouveau lien personnel valable 48h.',
                    reply_markup=url_kb('🔗 Rejoindre le groupe principal', invite.invite_link)
                )
                links_sent += 1
                await db.log('premium_repaired_and_resent', telegram_id=uid, chat_id=int(main))
            except Exception as e:
                send_failed += 1
                failed_ids.append(uid)
                await db.log('premium_repair_link_send_failed', telegram_id=uid, chat_id=int(main), data={'error': str(e)}, level='error')
        except Exception as e:
            send_failed += 1
            failed_ids.append(uid)
            await db.log('premium_repair_failed', telegram_id=uid, chat_id=int(main), data={'error': str(e)}, level='error')

    details = ''
    if failed_ids:
        details = '\n\nIDs en échec : ' + ', '.join(str(x) for x in failed_ids[:20])
        if len(failed_ids) > 20:
            details += f'… (+{len(failed_ids)-20})'

    await c.message.answer(
        '♻️ Réparation premium terminée.\n\n'
        f'👥 Utilisateurs concernés : {concerned}\n'
        f'✅ Débans réussis : {unban_ok}\n'
        f'⚠️ Débans échoués : {unban_failed}\n'
        f'🔗 Nouveaux liens envoyés : {links_sent}\n'
        f'❌ Envois échoués : {send_failed}'
        f'{details}',
        reply_markup=back_admin_kb()
    )
    await c.answer()

@router.callback_query(F.data == 'admin:payments')
async def admin_payments(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    price = await get_setting('premium_price', 'non configuré')
    paypal = await get_setting('paypal_link', 'non configuré')
    usdt = await get_setting('usdt_address', 'non configuré')
    pot = await get_setting('pot_balance', '0')
    await update_flow(
        c,
        f"💳 Paiements\n\nPrix premium : {price}\nPayPal : {paypal}\nUSDT : {usdt}\n\nStatistique cagnotte actuelle : {pot}€",
        reply_markup=payments_menu_kb(),
    )
    await c.answer()

@router.callback_query(F.data == 'payments:status')
async def payments_status(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    price = await get_setting('premium_price', 'non configuré')
    paypal = await get_setting('paypal_link', '')
    usdt = await get_setting('usdt_address', '')
    pot = await get_setting('pot_balance', '0')
    pending = await db.fetchval("SELECT count(*) FROM payments WHERE status='pending'") or 0
    validated = await db.fetchval("SELECT count(*) FROM payments WHERE status='validated'") or 0
    await update_flow(
        c,
        "📊 Statut paiements\n\n"
        f"Prix premium : {price}\n"
        f"PayPal configuré : {'✅' if paypal else '❌'}\n"
        f"USDT configuré : {'✅' if usdt else '❌'}\n"
        f"Paiements en attente : {pending}\n"
        f"Paiements validés : {validated}\n"
        f"Cagnotte actuelle : {pot}€",
        reply_markup=payments_menu_kb(),
    )
    await c.answer()

@router.callback_query(F.data == 'admin:moderation')
async def admin_moderation(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    pending = await db.fetchval("SELECT count(*) FROM applications WHERE status='pending_admin'") or 0
    banned = await db.fetchval("SELECT count(*) FROM users WHERE banned=true") or 0
    await update_flow(c, f'📥 Modération\n\nCandidatures en attente : {pending}\nUtilisateurs blacklistés : {banned}', reply_markup=moderation_menu_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:info')
async def admin_info(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    checks = []
    try:
        await db.fetchval('SELECT 1')
        checks.append('✅ Base de données : OK')
    except Exception as e:
        checks.append(f'❌ Base de données : erreur {e}')
    me = await bot.get_me()
    checks.append(f'✅ Bot : @{me.username}')
    main = await get_setting('main_group', '')
    pub_count = await db.fetchval("SELECT count(*) FROM groups WHERE type='pub'") or 0
    target_count = await db.fetchval("SELECT count(*) FROM groups WHERE type='pub' AND targeted=true") or 0
    checks.append(f"{'✅' if main else '❌'} Groupe principal : {main or 'non configuré'}")
    checks.append(f"{'✅' if pub_count else '❌'} Groupes publicité : {pub_count} configuré(s), {target_count} ciblé(s)")
    # Vérification permissions de ban dans les groupes configurés/détectés
    try:
        groups = await db.fetch("SELECT chat_id,title,type FROM groups WHERE active=true ORDER BY type,title LIMIT 20")
        bot_id = me.id
        for g in groups:
            try:
                member = await bot.get_chat_member(int(g['chat_id']), bot_id)
                can_ban = bool(getattr(member, 'can_restrict_members', False))
                checks.append(f"{'✅' if can_ban else '❌'} Ban permission : {g['title'] or g['chat_id']} ({g['type']})")
            except Exception as e:
                checks.append(f"❌ Groupe inaccessible : {g['title'] or g['chat_id']} — {e}")
    except Exception as e:
        checks.append(f"❌ Vérification groupes impossible : {e}")
    for label, key in [('Image pub','ad_image_file_id'), ('Image accueil','welcome_image_file_id'), ('Image preuve','proof_example_image_file_id')]:
        checks.append(f"{'✅' if await get_setting(key, '') else '❌'} {label}")
    checks.append(f"{'✅' if await get_setting('ad_text','') else '❌'} Texte publicité")
    checks.append(f"{'✅' if await get_setting('premium_price','') else '❌'} Prix premium")
    checks.append(f"{'✅' if await get_setting('paypal_link','') else '❌'} PayPal")
    checks.append(f"{'✅' if await get_setting('usdt_address','') else '❌'} USDT")
    enabled = await get_setting('auto_pub_enabled', '0') == '1'
    interval = await get_setting('auto_pub_interval_minutes', '10')
    checks.append(f"{'🟢' if enabled else '🔴'} Auto pub : {'ON' if enabled else 'OFF'}")
    checks.append(f"⏱ Fréquence publicité : {interval} minute(s)")
    await update_flow(c, 'ℹ️ Info / Vérification\n\n' + '\n'.join(checks), reply_markup=back_admin_kb())
    await c.answer()



# ---------- OTHER ADMIN ----------

@router.callback_query(F.data == 'admin:stats')
async def admin_stats(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    total = await db.fetchval('SELECT count(*) FROM users') or 0
    pending = await db.fetchval("SELECT count(*) FROM applications WHERE status='pending_admin'") or 0
    valid = await db.fetchval("SELECT count(*) FROM users WHERE status='member_validated'") or 0
    banned = await db.fetchval("SELECT count(*) FROM users WHERE banned=true") or 0
    pot = await get_setting('pot_balance', '0')
    await update_flow(c, f'📊 Stats\n\nUtilisateurs : {total}\nCandidatures en attente : {pending}\nMembres validés : {valid}\nBannis : {banned}\nCagnotte : {pot}€', reply_markup=back_admin_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:apps')
async def admin_apps(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    rows = await db.fetch("SELECT a.id,u.telegram_id,u.username,u.declared_total,a.created_at FROM applications a JOIN users u ON u.telegram_id=a.telegram_id WHERE a.status='pending_admin' ORDER BY a.created_at DESC LIMIT 10")
    if not rows:
        text = 'Aucune candidature en attente.'
    else:
        text = '📥 Candidatures en attente\n\n' + '\n'.join([f"#{r['id']} @{r['username'] or '-'} | {r['declared_total']} médias | ID {r['telegram_id']}" for r in rows])
    await update_flow(c, text, reply_markup=back_admin_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:blacklist')
async def admin_blacklist(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    rows = await db.fetch("SELECT telegram_id,username,status FROM users WHERE banned=true OR status IN ('failed_no_activity','banned') ORDER BY updated_at DESC LIMIT 20")
    if not rows:
        text = 'Blacklist vide.'
    else:
        text = '🚫 Blacklist / échecs\n\n' + '\n'.join([f"@{r['username'] or '-'} | {r['telegram_id']} | {r['status']}" for r in rows])
    await update_flow(c, text, reply_markup=back_admin_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:logs')
async def admin_logs(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    rows = await db.fetch("SELECT level,event,telegram_id,chat_id,data,created_at FROM logs ORDER BY created_at DESC LIMIT 15")
    if not rows:
        text = '🧾 Aucun log pour le moment.'
    else:
        lines = []
        for r in rows:
            icon = '❌' if r['level'] == 'error' else ('⚠️' if r['level'] == 'warning' else 'ℹ️')
            lines.append(f"{icon} {r['event']} | user:{r['telegram_id'] or '-'} | chat:{r['chat_id'] or '-'}")
        text = '🧾 Logs récents\n\n' + '\n'.join(lines)
    await update_flow(c, text, reply_markup=moderation_menu_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:settings')
async def admin_settings(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    interval = await get_setting('auto_pub_interval_minutes', '10')
    await update_flow(c, f'⚙️ Réglages\n\nVersion simple active :\n• français uniquement ;\n• pas de deuxième tentative ;\n• contrôle silencieux des contributions ;\n• anti-liens et anti-doublons actifs ;\n• une seule publicité visible par groupe.\n\n⏱ Fréquence publicité actuelle : {interval} minute(s).', reply_markup=settings_menu_kb())
    await c.answer()


@router.callback_query()
async def ignored_banned_callbacks(c: CallbackQuery):
    # Fallback sécurité : si un utilisateur banni clique sur un ancien bouton, aucun parcours ne redémarre.
    u = await db.fetchrow('SELECT banned FROM users WHERE telegram_id=$1', c.from_user.id)
    if u and u['banned']:
        await c.answer('Accès bloqué.', show_alert=True)
        return
    await c.answer()

# ---------- MONITORS ----------

async def monitor_members():
    while True:
        try:
            main = await get_setting('main_group', '')
            if main:
                rows = await db.fetch("""
                    SELECT telegram_id,attempts,joined_main_at,first_media_at,declared_total,valid_media_count,status
                    FROM users
                    WHERE status='temporary_member' AND joined_main_at IS NOT NULL
                """)
                now = datetime.now(timezone.utc)
                for u in rows:
                    joined = u['joined_main_at']
                    if not joined:
                        continue
                    # Version actuelle : une seule chance.
                    # Si aucun média valide après 10 minutes : ban définitif + blacklist.
                    if not u['first_media_at'] and now - joined > timedelta(minutes=10):
                        try:
                            await bot.send_message(int(u['telegram_id']), '❌ Aucune contribution détectée dans le délai prévu.\n\nVotre accès a été retiré automatiquement.')
                        except Exception:
                            pass
                        await ban_from_chat(int(main), int(u['telegram_id']), reason='ban_main_no_activity_10min')
                        await ban_user(int(u['telegram_id']), reason='ban_pub_no_activity_10min')
                        await db.execute("UPDATE users SET status='failed_no_activity', banned=true, updated_at=now() WHERE telegram_id=$1", u['telegram_id'])
                    # Si le quota complet n'est pas publié après 24h : ban définitif.
                    elif now - joined > timedelta(hours=24) and (u['valid_media_count'] or 0) < (u['declared_total'] or 0):
                        try:
                            await bot.send_message(int(u['telegram_id']), '❌ Quota non respecté.\n\nVotre accès a été retiré définitivement.')
                        except Exception:
                            pass
                        await ban_from_chat(int(main), int(u['telegram_id']), reason='ban_main_quota_24h_failed')
                        await ban_user(int(u['telegram_id']), reason='ban_pub_quota_24h_failed')
                        await db.execute("UPDATE users SET status='failed_quota', banned=true, updated_at=now() WHERE telegram_id=$1", u['telegram_id'])
            # Relance premium unique après 5h d’abandon du formulaire.
            abandoned = await db.fetch("""
                SELECT telegram_id,status,updated_at
                FROM users
                WHERE COALESCE(premium_nudge_sent,false)=false
                  AND COALESCE(banned,false)=false
                  AND status IN ('interested','language_chosen','profile_selecting','buyer_regular_question','origin_waiting','total_waiting','profile_filled')
                  AND updated_at < now() - interval '5 hours'
                LIMIT 50
            """)
            for a in abandoned:
                try:
                    await bot.send_message(int(a['telegram_id']), 'Vous n’avez pas terminé votre candidature.\n\nSi vous ne disposez pas du volume requis, un accès premium peut être disponible.', reply_markup=no_content_kb())
                    await db.execute('UPDATE users SET premium_nudge_sent=true, updated_at=now() WHERE telegram_id=$1', a['telegram_id'])
                    await db.log('premium_nudge_sent', telegram_id=int(a['telegram_id']), data={'status': a['status']})
                except Exception as e:
                    await db.log('premium_nudge_failed', telegram_id=int(a['telegram_id']), data={'error': str(e)}, level='warning')

            # Rappel admin si une candidature reste sans décision trop longtemps.
            pending_apps = await db.fetch("""
                SELECT a.id,a.telegram_id,u.username,a.created_at
                FROM applications a
                JOIN users u ON u.telegram_id=a.telegram_id
                WHERE a.status='pending_admin'
                  AND a.created_at < now() - interval '24 hours'
                LIMIT 20
            """)
            for app in pending_apps:
                await db.log('pending_application_over_24h', telegram_id=int(app['telegram_id']), data={'app_id': app['id'], 'username': app['username']}, level='warning')
        except Exception as e:
            await db.log('monitor_members_error', data={'error': str(e)}, level='error')
        await asyncio.sleep(60)

async def auto_pub_loop():
    while True:
        try:
            enabled = await get_setting('auto_pub_enabled', '0') == '1'
            if enabled:
                await publish_to_targets()
                minutes_raw = await get_setting('auto_pub_interval_minutes', '10')
                try:
                    minutes = max(1, int(minutes_raw))
                except ValueError:
                    minutes = 10
                await asyncio.sleep(minutes * 60)
            else:
                await asyncio.sleep(30)
        except Exception as e:
            await db.log('auto_pub_error', data={'error': str(e)}, level='error')
            await asyncio.sleep(60)

async def main():
    await db.connect()
    if config.auto_migrate:
        await db.migrate()
    asyncio.create_task(monitor_members())
    asyncio.create_task(auto_pub_loop())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == '__main__':
    asyncio.run(main())
