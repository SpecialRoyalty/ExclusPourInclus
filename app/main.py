import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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

class Apply(StatesGroup):
    language = State()
    profile = State()
    creators = State()
    total = State()
    photos = State()
    videos = State()
    proof = State()

class Proposal(StatesGroup):
    name = State()
    link = State()

class PaymentState(StatesGroup):
    amount = State()
    proof = State()


def is_admin(uid: int) -> bool:
    return uid in config.admin_ids

async def ensure_user(m: Message | CallbackQuery):
    u = m.from_user
    await db.execute('''
        INSERT INTO users(telegram_id, username, first_name) VALUES($1,$2,$3)
        ON CONFLICT (telegram_id) DO UPDATE SET username=$2, first_name=$3, updated_at=now()
    ''', u.id, u.username, u.first_name)

async def get_setting(key: str, default: str = '') -> str:
    val = await db.fetchval('SELECT value FROM settings WHERE key=$1', key)
    return val if val is not None else default

async def set_setting(key: str, value: str):
    await db.execute('INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=$2', key, value)

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

async def send_single_flow_message(user_id: int, chat_id: int, text: str, reply_markup=None):
    await delete_previous_flow_message(user_id)
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', user_id, chat_id, msg.message_id)
    return msg

async def update_flow_message(c: CallbackQuery, text: str, reply_markup=None):
    try:
        await c.message.edit_text(text, reply_markup=reply_markup)
        await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', c.from_user.id, c.message.chat.id, c.message.message_id)
    except TelegramBadRequest:
        await send_single_flow_message(c.from_user.id, c.message.chat.id, text, reply_markup=reply_markup)

async def user_status(uid: int) -> str:
    return await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', uid) or 'new'

@router.message(Command('start'))
async def start(m: Message, state: FSMContext):
    await ensure_user(m)
    # Nettoie le /start utilisateur pour éviter plusieurs instances visibles.
    try:
        await m.delete()
    except Exception:
        pass

    u = await db.fetchrow('SELECT banned,status,attempts FROM users WHERE telegram_id=$1', m.from_user.id)
    if u and u['banned']:
        await send_single_flow_message(m.from_user.id, m.chat.id, 'Votre accès est bloqué.')
        return

    await state.clear()

    # Si l'utilisateur est admin, on affiche directement le panneau admin.
    # Il n'a pas besoin de taper /admin.
    if is_admin(m.from_user.id):
        await send_single_flow_message(m.from_user.id, m.chat.id, 'Panneau admin', reply_markup=admin_panel_kb())
        return

    await send_single_flow_message(
        m.from_user.id,
        m.chat.id,
        'Bienvenue.\n\nVous êtes sur le point de rejoindre une communauté privée réservée aux profils capables d’apporter du contenu inédit.\n\nLe processus d’accès est sélectif afin de préserver la qualité du groupe.',
        reply_markup=start_kb()
    )

@router.callback_query(F.data == 'start:not_interested')
async def not_interested(c: CallbackQuery):
    await ensure_user(c)
    await update_flow_message(c, 'Aucun problème.\n\nCertaines campagnes premium peuvent être ouvertes ultérieurement.')
    await c.answer()

@router.callback_query(F.data == 'start:interested')
async def interested(c: CallbackQuery, state: FSMContext):
    await ensure_user(c)
    await db.execute("UPDATE users SET status='interested' WHERE telegram_id=$1", c.from_user.id)
    await update_flow_message(c, 'Veuillez choisir votre langue.', reply_markup=languages_kb())
    await state.set_state(Apply.language)
    await c.answer()

@router.callback_query(F.data.startswith('lang:'))
async def lang(c: CallbackQuery, state: FSMContext):
    language = c.data.split(':')[1]
    await db.execute("UPDATE users SET language=$2, status='language_chosen' WHERE telegram_id=$1", c.from_user.id, language)
    await update_flow_message(c, 'Cette communauté est principalement francophone.\n\nMerci de répondre sérieusement aux prochaines étapes afin de préserver la qualité des accès.', reply_markup=ok_kb('go:profile'))
    await c.answer()

@router.callback_query(F.data == 'go:profile')
async def ask_profile(c: CallbackQuery, state: FSMContext):
    await update_flow_message(c, 'Quel profil correspond le mieux au vôtre ?', reply_markup=profile_kb())
    await state.set_state(Apply.profile)
    await c.answer()

@router.callback_query(F.data.startswith('profile:'))
async def profile(c: CallbackQuery, state: FSMContext):
    p = c.data.split(':')[1]
    await db.execute('UPDATE users SET profile_type=$2 WHERE telegram_id=$1', c.from_user.id, p)
    if p == 'none':
        await db.execute("UPDATE users SET status='premium_proposed' WHERE telegram_id=$1", c.from_user.id)
        await update_flow_message(c, 'Les accès gratuits sont réservés aux membres capables de contribuer à la communauté.\n\nCertaines places premium payantes peuvent être ouvertes ultérieurement.')
        return
    await state.update_data(profile_type=p)
    if p == 'supplier':
        await update_flow_message(c, 'Combien de créatrices/personnes différentes possédez-vous approximativement ?')
        await state.set_state(Apply.creators)
    else:
        await update_flow_message(c, 'Combien de médias exclusifs possédez-vous approximativement ?')
        await state.set_state(Apply.total)
    await c.answer()

@router.message(Apply.creators)
async def creators(m: Message, state: FSMContext):
    await state.update_data(creators=m.text)
    await m.answer('Combien de médias exclusifs possédez-vous au total ?')
    await state.set_state(Apply.total)

@router.message(Apply.total)
async def total(m: Message, state: FSMContext):
    if not (m.text or '').isdigit():
        await m.answer('Merci d’envoyer uniquement un nombre.')
        return
    await state.update_data(total=int(m.text))
    await m.answer('Combien environ de photos ?')
    await state.set_state(Apply.photos)

@router.message(Apply.photos)
async def photos(m: Message, state: FSMContext):
    if not (m.text or '').isdigit():
        await m.answer('Merci d’envoyer uniquement un nombre.')
        return
    await state.update_data(photos=int(m.text))
    await m.answer('Combien environ de vidéos ?')
    await state.set_state(Apply.videos)

@router.message(Apply.videos)
async def videos(m: Message, state: FSMContext):
    if not (m.text or '').isdigit():
        await m.answer('Merci d’envoyer uniquement un nombre.')
        return
    await state.update_data(videos=int(m.text))
    data = await state.get_data()
    await db.execute('UPDATE users SET declared_total=$2, declared_photos=$3, declared_videos=$4, status=$5 WHERE telegram_id=$1', m.from_user.id, data['total'], data['photos'], int(m.text), 'profile_filled')
    await m.answer('⚠ Important\n\nLa communauté est principalement destinée aux contenus considérés comme exclusifs ou peu diffusés.\n\nLes médias déjà largement partagés, repostés ou facilement trouvables risquent d’être refusés.\n\nLes médias déjà présents dans la base du groupe peuvent être automatiquement détectés et non comptabilisés.', reply_markup=ok_kb('quota:recap'))

@router.callback_query(F.data == 'quota:recap')
async def quota_recap(c: CallbackQuery):
    u = await db.fetchrow('SELECT declared_total, declared_photos, declared_videos FROM users WHERE telegram_id=$1', c.from_user.id)
    await update_flow_message(c, f"Récapitulatif :\n\n📦 Médias déclarés : {u['declared_total']}\n🖼 Photos : {u['declared_photos']}\n🎥 Vidéos : {u['declared_videos']}\n\nConfirmez-vous ces informations ?", reply_markup=confirm_kb())
    await c.answer()

@router.callback_query(F.data == 'quota:edit')
async def quota_edit(c: CallbackQuery, state: FSMContext):
    await update_flow_message(c, 'Combien de médias exclusifs possédez-vous approximativement ?')
    await state.set_state(Apply.total)
    await c.answer()

@router.callback_query(F.data == 'quota:confirm')
async def quota_confirm(c: CallbackQuery, state: FSMContext):
    await update_flow_message(c, 'Pour protéger les membres de la communauté, une vérification est nécessaire.\n\nVeuillez envoyer une preuve correspondant à l’exemple fourni par les admins.\n\nLes preuves incohérentes ou invalides peuvent entraîner un refus.')
    await state.set_state(Apply.proof)
    await c.answer()

@router.message(Apply.proof)
async def proof(m: Message, state: FSMContext):
    file_id = None
    if m.photo:
        file_id = m.photo[-1].file_id
    elif m.document:
        file_id = m.document.file_id
    if not file_id:
        await m.answer('Merci d’envoyer une image ou un document comme preuve.')
        return
    app_id = await db.fetchval('INSERT INTO applications(telegram_id,status,proof_file_id) VALUES($1,$2,$3) RETURNING id', m.from_user.id, 'pending_admin', file_id)
    await db.execute("UPDATE users SET status='proof_sent' WHERE telegram_id=$1", m.from_user.id)
    u = await db.fetchrow('SELECT declared_total, declared_photos, declared_videos FROM users WHERE telegram_id=$1', m.from_user.id)
    caption = f"📥 Nouvelle candidature\n\n👤 Utilisateur : @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\n\n📦 Déclaré : {u['declared_total']} médias\n🖼 Photos : {u['declared_photos']}\n🎥 Vidéos : {u['declared_videos']}"
    for aid in config.admin_ids:
        try:
            await bot.send_photo(aid, file_id, caption=caption, reply_markup=admin_application_kb(app_id, m.from_user.id))
        except Exception:
            await bot.send_message(aid, caption, reply_markup=admin_application_kb(app_id, m.from_user.id))
    await m.answer('Votre candidature a été envoyée aux admins. Vous serez notifié après décision.')
    await state.clear()

@router.callback_query(F.data.startswith('app:'))
async def app_decision(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer('Admin uniquement', show_alert=True); return
    _, action, app_id, user_id = c.data.split(':')
    app_id, user_id = int(app_id), int(user_id)
    if action == 'approve':
        await db.execute("UPDATE applications SET status='approved', admin_decision_by=$2, decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        await db.execute("UPDATE users SET status='validated', attempts=attempts+1 WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, 'Votre candidature a été validée.\n\nAvant d’accéder au groupe principal, veuillez accepter les règles suivantes.', reply_markup=rules_kb(1))
        except Exception: pass
        await c.message.edit_caption((c.message.caption or '') + '\n\n✅ Validé')
    elif action == 'reject':
        await db.execute("UPDATE applications SET status='rejected', admin_decision_by=$2, decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        await db.execute("UPDATE users SET status='rejected' WHERE telegram_id=$1", user_id)
        await bot.send_message(user_id, 'Votre profil ne correspond pas actuellement aux critères d’accès gratuit.\n\nUne proposition d’accès premium pourra éventuellement vous être envoyée ultérieurement.')
        await c.message.edit_caption((c.message.caption or '') + '\n\n❌ Refusé')
    elif action == 'ban':
        await ban_user(user_id, reason='admin_application_ban')
        await c.message.edit_caption((c.message.caption or '') + '\n\n🚫 Banni')
    await c.answer()

@router.callback_query(F.data.startswith('rule:'))
async def rules(c: CallbackQuery):
    n = int(c.data.split(':')[1])
    texts = {
        1: 'Le contact privé entre membres est interdit.',
        2: 'Le partage du lien entraîne une exclusion définitive.',
        3: 'Aucun lien externe n’est autorisé dans le groupe.',
        4: 'Vous devrez publier le volume déclaré afin de conserver votre accès.',
        5: 'Les campagnes premium servent à financer la communauté et les futurs sondages.'
    }
    if n <= 5:
        await update_flow_message(c, texts[n], reply_markup=rules_kb(n+1) if n < 5 else ok_kb('rules:done'))
    await c.answer()

@router.callback_query(F.data == 'rules:done')
async def rules_done(c: CallbackQuery):
    chat_id = await get_setting('main_group')
    if not chat_id:
        await update_flow_message(c, 'Le groupe principal n’est pas encore configuré. Contactez un admin.')
        return
    try:
        invite = await bot.create_chat_invite_link(int(chat_id), member_limit=1, expire_date=datetime.now(timezone.utc)+timedelta(hours=6), creates_join_request=False)
        await db.execute('INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)', c.from_user.id, int(chat_id), invite.invite_link, c.from_user.id, datetime.now(timezone.utc)+timedelta(hours=6))
        await update_flow_message(c, 'Félicitations.\n\nVotre accès a été pré-validé.\n\n⚠ Ce lien est personnel, limité à un seul usage et surveillé automatiquement.\n\n' + invite.invite_link)
    except Exception as e:
        await update_flow_message(c, f'Erreur création lien. Vérifiez que le bot est admin du groupe principal. ({e})')
    await c.answer()

@router.message(Command('admin'))
async def admin(m: Message):
    # Conservé comme raccourci, mais /start affiche déjà ce panneau aux admins.
    if not is_admin(m.from_user.id):
        return
    try:
        await m.delete()
    except Exception:
        pass
    await send_single_flow_message(m.from_user.id, m.chat.id, 'Panneau admin', reply_markup=admin_panel_kb())

@router.message(Command('migrate'))
async def migrate(m: Message):
    if not is_admin(m.from_user.id): return
    await db.migrate()
    await m.answer('Base de données prête.')

@router.message(Command('set_main_group'))
async def set_main_group(m: Message):
    if not is_admin(m.from_user.id): return
    await set_setting('main_group', str(m.chat.id))
    await db.execute("INSERT INTO groups(chat_id,title,type) VALUES($1,$2,'main') ON CONFLICT(chat_id) DO UPDATE SET title=$2,type='main',active=true", m.chat.id, m.chat.title or '')
    await m.answer('Groupe principal défini.')

@router.message(Command('add_pub_group'))
async def add_pub_group(m: Message):
    if not is_admin(m.from_user.id): return
    await db.execute("INSERT INTO groups(chat_id,title,type) VALUES($1,$2,'publicity') ON CONFLICT(chat_id) DO UPDATE SET title=$2,type='publicity',active=true", m.chat.id, m.chat.title or '')
    await m.answer('Groupe publicité ajouté.')

async def publish_ad(chat_id: int):
    text = await get_setting('ad_text', '🔒 Communauté privée francophone\n\n• Contenus exclusifs\n• Accès sélectif\n• Contribution obligatoire\n• Vérification manuelle\n\nLes candidatures sont limitées.\n\nCliquez pour accéder au bot.')
    me = await bot.get_me()
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔗 Accéder au groupe privé', url=f'https://t.me/{me.username}?start=ad')]]))

@router.message(Command('pub_now'))
async def pub_now(m: Message):
    if not is_admin(m.from_user.id): return
    rows = await db.fetch("SELECT chat_id FROM groups WHERE type='publicity' AND active=true")
    sent = 0
    for r in rows:
        try:
            await publish_ad(r['chat_id']); sent += 1
        except Exception as e:
            await db.log('pub_failed', chat_id=r['chat_id'], data={'err': str(e)}, level='error')
    await m.answer(f'Publicité envoyée dans {sent} groupe(s).')

@router.callback_query(F.data == 'admin:pub_now')
async def cb_pub(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    fake = Message.model_construct(message_id=c.message.message_id, date=datetime.now(), chat=c.message.chat, from_user=c.from_user)
    await pub_now(fake)
    await c.answer()

@router.callback_query(F.data == 'admin:stats')
async def stats(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    total = await db.fetchval('SELECT count(*) FROM users')
    valid = await db.fetchval("SELECT count(*) FROM users WHERE status='membre_valide' OR status='member_validated'")
    pending = await db.fetchval("SELECT count(*) FROM applications WHERE status='pending_admin'")
    pot = await db.fetchval('SELECT COALESCE(sum(amount),0) FROM pot_transactions')
    await c.message.edit_text(f'📊 Stats\n\nUtilisateurs : {total}\nMembres validés : {valid}\nCandidatures attente : {pending}\nCagnotte : {pot}€', reply_markup=admin_panel_kb())
    await c.answer()

async def ban_user(user_id: int, reason: str = 'ban'):
    await db.execute("UPDATE users SET banned=true,status='banned' WHERE telegram_id=$1", user_id)
    main = await get_setting('main_group')
    if main:
        try: await bot.ban_chat_member(int(main), user_id)
        except Exception: pass
    await db.log(reason, telegram_id=user_id)

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
    main = await get_setting('main_group')
    if main and str(m.chat.id) == str(main):
        if m.text and URL_RE.search(m.text):
            try: await m.delete()
            except Exception: pass
            return
        media_type, file_id, unique_id = await extract_media_ids(m)
        if not media_type: return
        uid = m.from_user.id
        user = await db.fetchrow('SELECT status, declared_total, attempts, joined_main_at, valid_media_count FROM users WHERE telegram_id=$1', uid)
        if not user: return
        if not user['joined_main_at']:
            await db.execute("UPDATE users SET joined_main_at=now(), status='temporary_member' WHERE telegram_id=$1", uid)
            user = await db.fetchrow('SELECT status, declared_total, attempts, joined_main_at, valid_media_count FROM users WHERE telegram_id=$1', uid)
        exists = await db.fetchval('SELECT id FROM media_hashes WHERE file_unique_id=$1', unique_id)
        counted = not bool(exists)
        ph = await perceptual_hash(file_id) if media_type == 'photo' else None
        if counted and ph:
            similar = await db.fetchval('SELECT id FROM media_hashes WHERE perceptual_hash=$1 LIMIT 1', ph)
            if similar: counted = False
        try:
            await db.execute('INSERT INTO media_hashes(telegram_id,chat_id,message_id,file_unique_id,perceptual_hash,media_type,counted) VALUES($1,$2,$3,$4,$5,$6,$7)', uid, m.chat.id, m.message_id, unique_id, ph, media_type, counted)
        except Exception:
            counted = False
        if counted:
            await db.execute('UPDATE users SET valid_media_count=valid_media_count+1, first_media_at=COALESCE(first_media_at, now()), updated_at=now() WHERE telegram_id=$1', uid)
            total = await db.fetchval('SELECT declared_total FROM users WHERE telegram_id=$1', uid) or 0
            valid = await db.fetchval('SELECT valid_media_count FROM users WHERE telegram_id=$1', uid) or 0
            if total and valid >= total:
                await db.execute("UPDATE users SET status='member_validated' WHERE telegram_id=$1", uid)
                try: await bot.send_message(uid, '✅ Contribution complétée.\n\nVotre accès est maintenant définitivement validé.')
                except Exception: pass

@router.message(Command('proposer'))
async def propose(m: Message, state: FSMContext):
    st = await user_status(m.from_user.id)
    if st not in {'member_validated', 'membre_valide'}:
        await m.answer('Seuls les membres validés peuvent proposer.')
        return
    await m.answer('Nom de la créatrice/proposition ?')
    await state.set_state(Proposal.name)

@router.message(Proposal.name)
async def prop_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer('Lien de la plateforme ?')
    await state.set_state(Proposal.link)

@router.message(Proposal.link)
async def prop_link(m: Message, state: FSMContext):
    if not URL_RE.search(m.text or ''):
        await m.answer('Merci d’envoyer un lien valide.')
        return
    data = await state.get_data()
    pid = await db.fetchval('INSERT INTO proposals(proposer_id,name,platform_link) VALUES($1,$2,$3) RETURNING id', m.from_user.id, data['name'], m.text)
    await notify_admins(f"📥 Nouvelle proposition\n\n👤 @{m.from_user.username or '-'}\n📦 Nom : {data['name']}\n🔗 Lien : {m.text}", reply_markup=proposal_admin_kb(pid))
    await m.answer('Proposition envoyée aux admins.')
    await state.clear()

@router.callback_query(F.data.startswith('prop:'))
async def prop_admin(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    _, action, pid = c.data.split(':')
    pid = int(pid)
    p = await db.fetchrow('SELECT * FROM proposals WHERE id=$1', pid)
    if action == 'reject':
        await db.execute("UPDATE proposals SET status='rejected' WHERE id=$1", pid)
        await c.message.edit_text('Proposition refusée.')
    elif action == 'publish':
        main = await get_setting('main_group')
        if not main:
            await c.answer('Groupe principal non défini', show_alert=True); return
        msg = await bot.send_message(int(main), f"📊 Vote communautaire\n\nCréatrice proposée :\n{p['name']}\n\nSouhaitez-vous ouvrir une campagne communautaire pour cette proposition ?", reply_markup=proposal_vote_kb(pid))
        await db.execute("UPDATE proposals SET status='voting', message_id=$2 WHERE id=$1", pid, msg.message_id)
        await c.message.edit_text('Vote publié.')
    await c.answer()

@router.callback_query(F.data.startswith('voteprop:'))
async def vote_prop(c: CallbackQuery):
    _, pid, vote = c.data.split(':')
    pid = int(pid)
    st = await user_status(c.from_user.id)
    if st not in {'member_validated', 'membre_valide'}:
        await c.answer('Seuls les membres validés peuvent voter.', show_alert=True); return
    await db.execute('INSERT INTO proposal_votes(proposal_id,voter_id,vote) VALUES($1,$2,$3) ON CONFLICT(proposal_id,voter_id) DO UPDATE SET vote=$3, created_at=now()', pid, c.from_user.id, vote)
    counts = await db.fetchrow("SELECT count(*) FILTER (WHERE vote='yes') yes, count(*) FILTER (WHERE vote='no') no FROM proposal_votes WHERE proposal_id=$1", pid)
    await db.execute('UPDATE proposals SET yes_count=$2,no_count=$3 WHERE id=$1', pid, counts['yes'], counts['no'])
    p = await db.fetchrow('SELECT * FROM proposals WHERE id=$1', pid)
    try:
        await c.message.edit_text(f"📊 Vote communautaire\n\nCréatrice proposée :\n{p['name']}\n\n✅ Oui : {counts['yes']}\n❌ Non : {counts['no']}\n\nSouhaitez-vous ouvrir une campagne communautaire pour cette proposition ?", reply_markup=proposal_vote_kb(pid))
    except TelegramBadRequest:
        pass
    await c.answer('Vote enregistré.')

async def monitor_members():
    while True:
        try:
            main = await get_setting('main_group')
            if main:
                rows = await db.fetch("SELECT telegram_id, attempts, joined_main_at, first_media_at, declared_total, valid_media_count FROM users WHERE status IN ('temporary_member','validated') AND joined_main_at IS NOT NULL")
                now = datetime.now(timezone.utc)
                for u in rows:
                    joined = u['joined_main_at']
                    if u['attempts'] <= 1:
                        if not u['first_media_at'] and now - joined > timedelta(hours=4):
                            try: await bot.ban_chat_member(int(main), u['telegram_id']); await bot.unban_chat_member(int(main), u['telegram_id'])
                            except Exception: pass
                            await db.execute("UPDATE users SET status='failed_publication_1' WHERE telegram_id=$1", u['telegram_id'])
                            await db.log('kick_no_activity_4h', telegram_id=u['telegram_id'], chat_id=int(main))
                    else:
                        if now - joined > timedelta(hours=1) and u['valid_media_count'] < u['declared_total']:
                            await ban_user(u['telegram_id'], reason='ban_second_attempt_quota_failed')
                    if now - joined > timedelta(hours=24) and u['valid_media_count'] < u['declared_total']:
                        try: await bot.ban_chat_member(int(main), u['telegram_id']); await bot.unban_chat_member(int(main), u['telegram_id'])
                        except Exception: pass
                        await db.execute("UPDATE users SET status='failed_quota_24h' WHERE telegram_id=$1", u['telegram_id'])
                        await db.log('kick_quota_24h', telegram_id=u['telegram_id'], chat_id=int(main))
        except Exception as e:
            await db.log('monitor_error', data={'err': str(e)}, level='error')
        await asyncio.sleep(60)

async def main():
    await db.connect()
    await db.migrate()
    asyncio.create_task(monitor_members())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
