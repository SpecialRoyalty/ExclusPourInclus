import asyncio
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

class AdminMedia(StatesGroup):
    waiting_photo = State()

class AdminText(StatesGroup):
    waiting_text = State()

class Proposal(StatesGroup):
    name = State()
    link = State()

class PotState(StatesGroup):
    set_balance = State()


def is_admin(uid: int) -> bool:
    return uid in config.admin_ids

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

async def send_flow(user_id: int, chat_id: int, text: str, reply_markup=None, image_setting: str | None = None):
    await delete_previous_flow_message(user_id)
    image_file_id = await get_setting(image_setting, '') if image_setting else ''
    if image_file_id:
        msg = await bot.send_photo(chat_id, image_file_id, caption=text, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', user_id, chat_id, msg.message_id)
    return msg

async def update_flow(c: CallbackQuery, text: str, reply_markup=None, image_setting: str | None = None):
    image_file_id = await get_setting(image_setting, '') if image_setting else ''
    if image_file_id:
        await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup, image_setting)
        return
    try:
        if c.message.photo:
            await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup)
        else:
            await c.message.edit_text(text, reply_markup=reply_markup)
            await db.execute('UPDATE users SET flow_chat_id=$2, flow_message_id=$3 WHERE telegram_id=$1', c.from_user.id, c.message.chat.id, c.message.message_id)
    except TelegramBadRequest:
        await send_flow(c.from_user.id, c.message.chat.id, text, reply_markup)

async def user_status(uid: int) -> str:
    return await db.fetchval('SELECT status FROM users WHERE telegram_id=$1', uid) or 'new'

async def clean_user_message(m: Message):
    try:
        await m.delete()
    except Exception:
        pass

async def show_admin_panel(chat_id: int, user_id: int):
    await send_flow(user_id, chat_id, 'Panneau admin', reply_markup=admin_panel_kb())

# ---------- START / ONBOARDING ----------

@router.message(Command('start'))
async def start(m: Message, state: FSMContext):
    await ensure_user(m)
    await clean_user_message(m)
    await state.clear()
    u = await db.fetchrow('SELECT banned,status FROM users WHERE telegram_id=$1', m.from_user.id)
    if u and u['banned']:
        await send_flow(m.from_user.id, m.chat.id, 'Votre accès est bloqué.')
        return
    if is_admin(m.from_user.id):
        await show_admin_panel(m.chat.id, m.from_user.id)
        return
    await send_flow(
        m.from_user.id,
        m.chat.id,
        'Bienvenue.\n\nVous êtes sur le point de rejoindre une communauté privée réservée aux profils capables d’apporter du contenu inédit.\n\nLe processus d’accès est sélectif afin de préserver la qualité du groupe.',
        reply_markup=start_kb(),
        image_setting='welcome_image_file_id',
    )

@router.message(Command('admin'))
async def admin_shortcut(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await clean_user_message(m)
    await state.clear()
    await show_admin_panel(m.chat.id, m.from_user.id)

@router.callback_query(F.data == 'start:not_interested')
async def not_interested(c: CallbackQuery):
    await ensure_user(c)
    await db.execute("UPDATE users SET status='not_interested' WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Aucun problème.\n\nCertaines campagnes premium peuvent être ouvertes ultérieurement.')
    await c.answer()

@router.callback_query(F.data == 'start:interested')
async def interested(c: CallbackQuery, state: FSMContext):
    await ensure_user(c)
    await db.execute("UPDATE users SET status='interested' WHERE telegram_id=$1", c.from_user.id)
    await update_flow(c, 'Veuillez choisir votre langue.', reply_markup=languages_kb())
    await state.set_state(Apply.language)
    await c.answer()

@router.callback_query(F.data.startswith('lang:'))
async def language(c: CallbackQuery, state: FSMContext):
    lang = c.data.split(':', 1)[1]
    await db.execute("UPDATE users SET language=$2,status='language_chosen' WHERE telegram_id=$1", c.from_user.id, lang)
    await update_flow(c, 'Cette communauté est principalement francophone.\n\nMerci de répondre sérieusement aux prochaines étapes afin de préserver la qualité des accès.', reply_markup=continue_kb())
    await c.answer()

@router.callback_query(F.data == 'go:profile')
async def go_profile(c: CallbackQuery, state: FSMContext):
    await update_flow(c, 'Quel profil correspond le mieux au vôtre ?', reply_markup=profile_kb())
    await state.set_state(Apply.profile)
    await c.answer()

@router.callback_query(F.data.startswith('profile:'))
async def choose_profile(c: CallbackQuery, state: FSMContext):
    p = c.data.split(':', 1)[1]
    await db.execute('UPDATE users SET profile_type=$2 WHERE telegram_id=$1', c.from_user.id, p)
    if p == 'none':
        await db.execute("UPDATE users SET status='premium_proposed' WHERE telegram_id=$1", c.from_user.id)
        await update_flow(c, 'Les accès gratuits sont réservés aux membres capables de contribuer à la communauté.\n\nCertaines places premium payantes peuvent être ouvertes ultérieurement.')
        await c.answer()
        return
    await state.update_data(profile_type=p)
    if p == 'supplier':
        await update_flow(c, 'Combien de créatrices/personnes différentes possédez-vous approximativement ?')
        await state.set_state(Apply.creators)
    else:
        await update_flow(c, 'Combien de médias exclusifs possédez-vous approximativement ?')
        await state.set_state(Apply.total)
    await c.answer()

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
    await send_flow(m.from_user.id, m.chat.id, 'Combien environ de photos ?')
    await state.set_state(Apply.photos)

@router.message(Apply.photos)
async def apply_photos(m: Message, state: FSMContext):
    n = await parse_positive_int(m)
    if n is None:
        return
    await state.update_data(photos=n)
    await send_flow(m.from_user.id, m.chat.id, 'Combien environ de vidéos ?')
    await state.set_state(Apply.videos)

@router.message(Apply.videos)
async def apply_videos(m: Message, state: FSMContext):
    n = await parse_positive_int(m)
    if n is None:
        return
    data = await state.get_data()
    await state.update_data(videos=n)
    await db.execute(
        "UPDATE users SET declared_total=$2, declared_photos=$3, declared_videos=$4, status='profile_filled' WHERE telegram_id=$1",
        m.from_user.id, int(data['total']), int(data['photos']), n,
    )
    await send_flow(
        m.from_user.id,
        m.chat.id,
        '⚠ Important\n\nLa communauté est principalement destinée aux contenus considérés comme exclusifs ou peu diffusés.\n\nLes médias déjà largement partagés, repostés ou facilement trouvables risquent d’être refusés.\n\nLes médias déjà présents dans la base du groupe peuvent être automatiquement détectés et non comptabilisés.',
        reply_markup=ok_kb('quota:recap'),
    )

@router.callback_query(F.data == 'quota:recap')
async def quota_recap(c: CallbackQuery):
    u = await db.fetchrow('SELECT declared_total,declared_photos,declared_videos FROM users WHERE telegram_id=$1', c.from_user.id)
    await update_flow(c, f"Récapitulatif :\n\n📦 Médias déclarés : {u['declared_total']}\n🖼 Photos : {u['declared_photos']}\n🎥 Vidéos : {u['declared_videos']}\n\nConfirmez-vous ces informations ?", reply_markup=confirm_kb())
    await c.answer()

@router.callback_query(F.data == 'quota:edit')
async def quota_edit(c: CallbackQuery, state: FSMContext):
    await update_flow(c, 'Combien de médias exclusifs possédez-vous approximativement ?')
    await state.set_state(Apply.total)
    await c.answer()

@router.callback_query(F.data == 'quota:confirm')
async def quota_confirm(c: CallbackQuery, state: FSMContext):
    proof_img = await get_setting('proof_example_image_file_id')
    text = 'Pour protéger les membres de la communauté, une vérification est nécessaire.\n\nVeuillez envoyer une preuve correspondant à l’exemple fourni par les admins.\n\nLes preuves incohérentes ou invalides peuvent entraîner un refus.'
    await update_flow(c, text, image_setting='proof_example_image_file_id' if proof_img else None)
    await state.set_state(Apply.proof)
    await c.answer()

@router.message(Apply.proof)
async def apply_proof(m: Message, state: FSMContext):
    file_id = None
    proof_type = 'photo'
    if m.photo:
        file_id = m.photo[-1].file_id
        proof_type = 'photo'
    elif m.document:
        file_id = m.document.file_id
        proof_type = 'document'
    if not file_id:
        await m.answer('Merci d’envoyer une image ou un document comme preuve.')
        return
    app_id = await db.fetchval(
        "INSERT INTO applications(telegram_id,status,proof_file_id,proof_type) VALUES($1,'pending_admin',$2,$3) RETURNING id",
        m.from_user.id, file_id, proof_type,
    )
    await db.execute("UPDATE users SET status='proof_sent' WHERE telegram_id=$1", m.from_user.id)
    u = await db.fetchrow('SELECT declared_total,declared_photos,declared_videos FROM users WHERE telegram_id=$1', m.from_user.id)
    caption = f"📥 Nouvelle candidature\n\n👤 Utilisateur : @{m.from_user.username or '-'}\n🆔 ID : {m.from_user.id}\n\n📦 Déclaré : {u['declared_total']} médias\n🖼 Photos : {u['declared_photos']}\n🎥 Vidéos : {u['declared_videos']}"
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
    await update_flow(c, '📢 Publicité\n\nGérez la publicité, le texte, les groupes ciblés et l’auto-publication.', reply_markup=pub_menu_kb(enabled))
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
        'premium_image_file_id': 'campagne premium',
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
        ('Image premium', 'premium_image_file_id'),
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
    await update_flow(c, '👥 Groupes\n\nUtilisez ces boutons depuis le groupe concerné, ou utilisez les commandes dans le groupe : /set_main_group et /add_pub_group.', reply_markup=groups_menu_kb())
    await c.answer()

@router.callback_query(F.data.startswith('group:'))
async def group_actions(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    action = c.data.split(':', 1)[1]
    if action == 'list':
        rows = await db.fetch('SELECT chat_id,title,type,active,targeted FROM groups ORDER BY type,title')
        if not rows:
            text = 'Aucun groupe configuré.'
        else:
            lines = ['📋 Groupes configurés']
            for r in rows:
                lines.append(f"• {r['type']} | {r['title'] or '-'} | {r['chat_id']} | actif={r['active']} | ciblé={r['targeted']}")
            text = '\n'.join(lines)
        await update_flow(c, text, reply_markup=groups_menu_kb())
    else:
        await c.answer('Ces actions doivent être faites directement dans le groupe concerné via /set_main_group ou /add_pub_group.', show_alert=True)
    await c.answer()

@router.message(Command('set_main_group'))
async def cmd_set_main_group(m: Message):
    if not is_admin(m.from_user.id): return
    if m.chat.type not in {'group', 'supergroup'}:
        await m.answer('À utiliser dans le groupe principal.')
        return
    await set_setting('main_group', str(m.chat.id))
    await db.execute("INSERT INTO groups(chat_id,title,type,active,targeted) VALUES($1,$2,'main',true,false) ON CONFLICT(chat_id) DO UPDATE SET title=$2,type='main',active=true,targeted=false,updated_at=now()", m.chat.id, m.chat.title or '')
    await m.answer('✅ Groupe principal défini.')

@router.message(Command('add_pub_group'))
async def cmd_add_pub_group(m: Message):
    if not is_admin(m.from_user.id): return
    if m.chat.type not in {'group', 'supergroup'}:
        await m.answer('À utiliser dans un groupe publicité.')
        return
    await db.execute("INSERT INTO groups(chat_id,title,type,active,targeted) VALUES($1,$2,'publicity',true,true) ON CONFLICT(chat_id) DO UPDATE SET title=$2,type='publicity',active=true,targeted=true,updated_at=now()", m.chat.id, m.chat.title or '')
    await m.answer('✅ Groupe publicité ajouté et ciblé.')

@router.callback_query(F.data == 'text:set:ad_text')
async def set_ad_text_cb(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id): return
    await state.update_data(setting_key='ad_text')
    await update_flow(c, 'Envoyez le nouveau texte de publicité.')
    await state.set_state(AdminText.waiting_text)
    await c.answer()

@router.message(AdminText.waiting_text)
async def receive_admin_text(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    data = await state.get_data()
    key = data.get('setting_key')
    if not key:
        await state.clear(); return
    await set_setting(key, m.text or '')
    await send_flow(m.from_user.id, m.chat.id, f'✅ Texte enregistré pour {key}.', reply_markup=admin_panel_kb())
    await state.clear()

# ---------- PUBLICITY ----------

async def publish_ad(chat_id: int):
    text = await get_setting('ad_text')
    image = await get_setting('ad_image_file_id', '')
    me = await bot.get_me()
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔗 Accéder au groupe privé', url=f'https://t.me/{me.username}?start=ad')]])
    if image:
        await bot.send_photo(chat_id, image, caption=text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)

async def publish_to_targets() -> int:
    rows = await db.fetch("SELECT chat_id FROM groups WHERE type='publicity' AND active=true AND targeted=true")
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

@router.message(Command('pub_now'))
async def pub_now_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    sent = await publish_to_targets()
    await m.answer(f'Publicité envoyée dans {sent} groupe(s).')

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
    rows = await db.fetch("SELECT chat_id,title,targeted FROM groups WHERE type='publicity' ORDER BY title")
    if not rows:
        await update_flow(c, 'Aucun groupe publicité configuré. Ajoutez le bot dans un groupe puis utilisez /add_pub_group.', reply_markup=pub_menu_kb(await get_setting('auto_pub_enabled','0')=='1'))
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
    if action == 'approve':
        await db.execute("UPDATE applications SET status='approved',admin_decision_by=$2,decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        await db.execute("""
            UPDATE users SET status='validated', attempts=attempts+1, joined_main_at=NULL,
            first_media_at=NULL, valid_media_count=0, updated_at=now()
            WHERE telegram_id=$1
        """, user_id)
        try:
            await bot.send_message(user_id, 'Votre candidature a été validée.\n\nAvant d’accéder au groupe principal, veuillez accepter les règles suivantes.', reply_markup=rules_kb(1))
        except Exception:
            pass
        await safe_mark_admin_message(c, '✅ Validé')
    elif action == 'reject':
        await db.execute("UPDATE applications SET status='rejected',admin_decision_by=$2,decision_at=now() WHERE id=$1", app_id, c.from_user.id)
        await db.execute("UPDATE users SET status='rejected' WHERE telegram_id=$1", user_id)
        try:
            await bot.send_message(user_id, 'Votre profil ne correspond pas actuellement aux critères d’accès gratuit.\n\nUne proposition d’accès premium pourra éventuellement vous être envoyée ultérieurement.')
        except Exception:
            pass
        await safe_mark_admin_message(c, '❌ Refusé')
    elif action == 'ban':
        await ban_user(user_id, reason='admin_application_ban')
        await safe_mark_admin_message(c, '🚫 Banni')
    await c.answer()

async def safe_mark_admin_message(c: CallbackQuery, suffix: str):
    try:
        if c.message.caption:
            await c.message.edit_caption(c.message.caption + f'\n\n{suffix}')
        else:
            await c.message.edit_text(c.message.text + f'\n\n{suffix}')
    except Exception:
        pass

@router.callback_query(F.data.startswith('rule:'))
async def rules(c: CallbackQuery):
    n = int(c.data.split(':')[1])
    texts = {
        1: 'Le contact privé entre membres est interdit.',
        2: 'Le partage du lien entraîne une exclusion définitive.',
        3: 'Aucun lien externe n’est autorisé dans le groupe.',
        4: 'Vous devrez publier le volume déclaré afin de conserver votre accès.',
        5: 'Les campagnes premium servent à financer la communauté et les futurs sondages.',
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
            expire_date=datetime.now(timezone.utc) + timedelta(hours=6),
            creates_join_request=False,
        )
        await db.execute('INSERT INTO invite_links(telegram_id,chat_id,invite_link,expected_user_id,expires_at) VALUES($1,$2,$3,$4,$5)', c.from_user.id, int(main), invite.invite_link, c.from_user.id, datetime.now(timezone.utc)+timedelta(hours=6))
        await update_flow(c, 'Félicitations.\n\nVotre accès a été pré-validé.\n\n⚠ Ce lien est personnel, limité à un seul usage et surveillé automatiquement.', reply_markup=url_kb('🔗 Rejoindre le groupe principal', invite.invite_link))
    except Exception as e:
        await update_flow(c, f'Erreur création lien. Vérifiez que le bot est admin du groupe principal.\n\n{e}')
    await c.answer()

# ---------- GROUP MODERATION / MEDIA COUNT ----------

async def ban_user(user_id: int, reason: str = 'ban'):
    await db.execute("UPDATE users SET banned=true,status='banned',updated_at=now() WHERE telegram_id=$1", user_id)
    main = await get_setting('main_group', '')
    if main:
        try:
            await bot.ban_chat_member(int(main), user_id)
        except Exception:
            pass
    await db.log(reason, telegram_id=user_id)

async def kick_user(chat_id: int, user_id: int, reason: str):
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
    except Exception:
        pass
    await db.log(reason, telegram_id=user_id, chat_id=chat_id)

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
        if member.is_bot:
            continue
        u = await db.fetchrow('SELECT status,declared_total,attempts,banned FROM users WHERE telegram_id=$1', member.id)
        if not u or u['banned'] or u['status'] not in {'validated', 'temporary_member', 'failed_publication_1'}:
            await kick_user(m.chat.id, member.id, 'join_without_validation')
            continue
        await db.execute("UPDATE users SET status='temporary_member', joined_main_at=now(), first_media_at=NULL, valid_media_count=0, updated_at=now() WHERE telegram_id=$1", member.id)
        try:
            msg = await bot.send_message(m.chat.id, f"Bienvenue @{member.username or member.first_name}.\n\n📦 Déclaration : {u['declared_total']} médias.\n\nVous devez maintenant publier les médias déclarés lors de votre candidature.\n\n⚠ Les doublons, reposts ou contenus déjà présents ne seront pas comptabilisés.")
            await asyncio.sleep(180)
            try: await bot.delete_message(m.chat.id, msg.message_id)
            except Exception: pass
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

# ---------- PROPOSALS / CAGNOTTE ----------

@router.message(Command('proposer'))
async def propose(m: Message, state: FSMContext):
    st = await user_status(m.from_user.id)
    if st != 'member_validated':
        await m.answer('Seuls les membres validés peuvent proposer.')
        return
    await m.answer('Nom de la créatrice/proposition ?')
    await state.set_state(Proposal.name)

@router.message(Proposal.name)
async def prop_name(m: Message, state: FSMContext):
    await state.update_data(name=(m.text or '').strip())
    await m.answer('Lien de la plateforme ?')
    await state.set_state(Proposal.link)

@router.message(Proposal.link)
async def prop_link(m: Message, state: FSMContext):
    link = (m.text or '').strip()
    if not URL_RE.search(link):
        await m.answer('Merci d’envoyer un lien valide.')
        return
    data = await state.get_data()
    pid = await db.fetchval('INSERT INTO proposals(proposer_id,name,platform_link) VALUES($1,$2,$3) RETURNING id', m.from_user.id, data['name'], link)
    await notify_admins(f"📥 Nouvelle proposition\n\n👤 @{m.from_user.username or '-'}\n📦 Nom : {data['name']}\n🔗 Lien : {link}", reply_markup=proposal_admin_kb(pid))
    await m.answer('Proposition envoyée aux admins.')
    await state.clear()

@router.callback_query(F.data.startswith('prop:'))
async def prop_admin(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    _, action, pid = c.data.split(':')
    pid = int(pid)
    p = await db.fetchrow('SELECT * FROM proposals WHERE id=$1', pid)
    if not p:
        await c.answer('Proposition introuvable', show_alert=True); return
    if action == 'reject':
        await db.execute("UPDATE proposals SET status='rejected',closed_at=now() WHERE id=$1", pid)
        await c.message.edit_text('Proposition refusée.')
    elif action == 'publish':
        main = await get_setting('main_group', '')
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
    if st != 'member_validated':
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

@router.callback_query(F.data == 'admin:pot')
async def admin_pot(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    balance = await get_setting('pot_balance', '0')
    await update_flow(c, f'💰 Cagnotte actuelle : {balance}€\n\nUtilisez /set_pot 123 pour déclarer le nouveau montant disponible.', reply_markup=back_admin_kb())
    await c.answer()

@router.message(Command('set_pot'))
async def set_pot_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    parts = (m.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await m.answer('Usage : /set_pot 123')
        return
    try:
        amount = float(parts[1].replace(',', '.'))
    except ValueError:
        await m.answer('Montant invalide.')
        return
    await set_setting('pot_balance', str(amount))
    await db.execute('INSERT INTO pot_transactions(amount,reason,created_by) VALUES($1,$2,$3)', amount, 'admin_set_balance', m.from_user.id)
    await m.answer(f'✅ Cagnotte déclarée : {amount}€')

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
    rows = await db.fetch("SELECT telegram_id,username,status FROM users WHERE banned=true OR status IN ('failed_publication_1','failed_quota_24h') ORDER BY updated_at DESC LIMIT 20")
    if not rows:
        text = 'Blacklist vide.'
    else:
        text = '🚫 Blacklist / échecs\n\n' + '\n'.join([f"@{r['username'] or '-'} | {r['telegram_id']} | {r['status']}" for r in rows])
    await update_flow(c, text, reply_markup=back_admin_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:proposals')
async def admin_proposals(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    rows = await db.fetch("SELECT id,name,status,yes_count,no_count FROM proposals ORDER BY created_at DESC LIMIT 10")
    if not rows:
        text = 'Aucune proposition.'
    else:
        text = '🗳 Propositions\n\n' + '\n'.join([f"#{r['id']} {r['name']} | {r['status']} | ✅{r['yes_count']} ❌{r['no_count']}" for r in rows])
    await update_flow(c, text, reply_markup=back_admin_kb())
    await c.answer()

@router.callback_query(F.data == 'admin:settings')
async def admin_settings(c: CallbackQuery):
    if not is_admin(c.from_user.id): return
    await update_flow(c, '⚙️ Réglages\n\nCommandes utiles :\n/set_main_group dans le groupe principal\n/add_pub_group dans un groupe publicité\n/pub_now pour publier\n/set_pot 0 pour déclarer la cagnotte', reply_markup=back_admin_kb())
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
                    # 1ère tentative : si aucun média valide après 4h = kick, l'utilisateur peut recommencer 1 fois.
                    if u['attempts'] <= 1:
                        if not u['first_media_at'] and now - joined > timedelta(hours=4):
                            await kick_user(int(main), int(u['telegram_id']), 'kick_no_activity_4h')
                            await db.execute("UPDATE users SET status='failed_publication_1', updated_at=now() WHERE telegram_id=$1", u['telegram_id'])
                        elif now - joined > timedelta(hours=24) and (u['valid_media_count'] or 0) < (u['declared_total'] or 0):
                            await kick_user(int(main), int(u['telegram_id']), 'kick_quota_24h')
                            await db.execute("UPDATE users SET status='failed_quota_24h', updated_at=now() WHERE telegram_id=$1", u['telegram_id'])
                    # 2ème tentative : quota complet sous 1h sinon ban définitif.
                    else:
                        if now - joined > timedelta(hours=1) and (u['valid_media_count'] or 0) < (u['declared_total'] or 0):
                            await ban_user(int(u['telegram_id']), reason='ban_second_attempt_quota_failed')
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
