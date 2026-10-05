import random
import asyncio
import logging
import html
import os
import psycopg2
from psycopg2 import pool
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.error import RetryAfter, BadRequest

# Logging Config
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT TOKEN & ADMIN CONFIG ---
TOKEN = os.getenv("BOT_TOKEN", "8847802267:AAFuOudnLo1CnSpu3YcLSZZ56gMM9aLVloA")
BOT_ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))

# --- DATABASE CONNECTION POOL ---
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = None

def init_db_pool():
    global db_pool
    try:
        if DATABASE_URL:
            db_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL, sslmode="require")
        else:
            db_pool = pool.SimpleConnectionPool(
                1, 20,
                dbname=os.getenv("DB_NAME", "football_bot"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", "postgres"),
                host=os.getenv("DB_HOST", "localhost"),
                port=os.getenv("DB_PORT", "5432")
            )
        logger.info("Database Connection Pool initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Connection Pool: {e}")

class get_db:
    """Context Manager for Database Connections using Connection Pool"""
    def __enter__(self):
        self.conn = db_pool.getconn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
            db_pool.putconn(self.conn)

# Initialize Database Tables
def init_db():
    init_db_pool()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT,
            coins INT DEFAULT 0
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY,
            title TEXT
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_users (
            chat_id BIGINT,
            user_id BIGINT,
            PRIMARY KEY (chat_id, user_id)
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT
        );
        """)
        cursor.close()

# Start Initial DB Setup
init_db()

# --- DATABASE HELPER FUNCTIONS ---

def db_add_or_update_user(user_id, first_name):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, first_name) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET first_name = EXCLUDED.first_name
        """, (user_id, first_name))
        cursor.close()

def db_add_group(chat_id, title):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO groups (chat_id, title) VALUES (%s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title
        """, (chat_id, title))
        cursor.close()

def db_add_group_user(chat_id, user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO group_users (chat_id, user_id) VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (chat_id, user_id))
        cursor.close()

def db_add_coins(user_id, reward):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET coins = coins + %s WHERE user_id = %s
        """, (reward, user_id))
        cursor.close()

def db_get_user_info(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, coins FROM users WHERE user_id = %s", (user_id,))
        res = cursor.fetchone()
        cursor.close()
        return res

def db_get_setting(key, default=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value, type FROM settings WHERE key = %s", (key,))
        res = cursor.fetchone()
        cursor.close()
        if res:
            return res[0], res[1]
        return default, None

def db_set_setting(key, value, media_type=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value, type) VALUES (%s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, type = EXCLUDED.type
        """, (key, str(value), media_type))
        cursor.close()

def db_delete_setting(key):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM settings WHERE key = %s", (key,))
        cursor.close()


# --- TEAMS DATA ---
TEAMS = {
    # Premier League
    "Arsenal": {"emoji": "🔴⚪", "stadium": "Emirates Stadium"},
    "Aston Villa": {"emoji": "🦁🟣", "stadium": "Villa Park"},
    "Bournemouth": {"emoji": "🍒🔴", "stadium": "Vitality Stadium"},
    "Brentford": {"emoji": "🐝🔴", "stadium": "Gtech Community Stadium"},
    "Brighton": {"emoji": "🔵⚪️", "stadium": "Amex Stadium"},
    "Chelsea": {"emoji": "🔵", "stadium": "Stamford Bridge"},
    "Crystal Palace": {"emoji": "🦅🔵", "stadium": "Selhurst Park"},
    "Everton": {"emoji": "🔵⚪️", "stadium": "Goodison Park"},
    "Fulham": {"emoji": "⚪⚫️", "stadium": "Craven Cottage"},
    "Ipswich Town": {"emoji": "🚜🔵", "stadium": "Portman Road"},
    "Leicester City": {"emoji": "🦊🔵", "stadium": "King Power Stadium"},
    "Liverpool": {"emoji": "🔴", "stadium": "Anfield"},
    "Manchester City": {"emoji": "🩵", "stadium": "Etihad Stadium"},
    "Manchester United": {"emoji": "🔴😈", "stadium": "Old Trafford"},
    "Newcastle United": {"emoji": "⚪️⚫️", "stadium": "St James' Park"},
    "Nottingham Forest": {"emoji": "🌳🔴", "stadium": "City Ground"},
    "Southampton": {"emoji": "🔴⚪️", "stadium": "St Mary's Stadium"},
    "Tottenham Hotspur": {"emoji": "⚪️", "stadium": "Tottenham Hotspur Stadium"},
    "West Ham United": {"emoji": "⚒️🟣", "stadium": "London Stadium"},
    "Wolverhampton Wanderers": {"emoji": "🐺🟠", "stadium": "Molineux Stadium"},

    # Top European Clubs
    "Real Madrid": {"emoji": "👑⚪", "stadium": "Santiago Bernabéu"},
    "Barcelona": {"emoji": "🔵🔴", "stadium": "Camp Nou"},
    "Atletico Madrid": {"emoji": "🔴⚪", "stadium": "Cívitas Metropolitano"},
    "Bayern Munich": {"emoji": "🔴🔴", "stadium": "Allianz Arena"},
    "Borussia Dortmund": {"emoji": "🟡⚫️", "stadium": "Signal Iduna Park"},
    "Bayer Leverkusen": {"emoji": "🔴⚫️", "stadium": "BayArena"},
    "Juventus": {"emoji": "⚪⚫", "stadium": "Allianz Stadium"},
    "Inter Milan": {"emoji": "🔵⚫", "stadium": "San Siro"},
    "AC Milan": {"emoji": "🔴⚫", "stadium": "San Siro"},
    "PSG": {"emoji": "🔵🔴", "stadium": "Parc des Princes"}
}

# --- GLOBAL RUNTIME MEMORY & CACHE ---
group_counters = {}   # {chat_id: int}
active_games = {}     # {chat_id: game_data}
last_result_data = {} # {chat_id: {"text": str, "markup": InlineKeyboardMarkup}}
CACHE_SETTINGS = {"threshold": 6}

def load_cached_threshold():
    val, _ = db_get_setting("global_threshold")
    if val:
        CACHE_SETTINGS["threshold"] = int(val)

load_cached_threshold()

def get_mention(user_id, name):
    safe_name = html.escape(str(name))
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

# Admin Command: /c <number>
async def set_counter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ ဒီ Command ကို Group ထဲတွင်သာ သုံးပါ။")
        return

    try:
        chat_member = await context.bot.get_chat_member(chat_id, user.id)
        is_group_admin = chat_member.status in ["creator", "administrator"]
    except Exception:
        is_group_admin = False

    is_bot_admin = (user.id == BOT_ADMIN_ID)

    if not (is_group_admin or is_bot_admin):
        await update.message.reply_text("❌ ဒီ Command ကို Admin များသာ သုံးနိုင်ပါသည်။")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ စာကြောင်း အရေအတွက် ကိန်းဂဏန်း ထည့်ပေးပါ။\nဥပမာ - `/c 6`", parse_mode="HTML")
        return

    new_threshold = int(context.args[0])
    await asyncio.to_thread(db_set_setting, "global_threshold", new_threshold)
    CACHE_SETTINGS["threshold"] = new_threshold

    await update.message.reply_text(f"🌐 <b>Global Setting Updated:</b>\nGroup အားလုံးအတွက် စာကြောင်း <b>{new_threshold}</b> ကြောင်း ပြည့်တိုင်း ဂိမ်းစတင်ပါမည်။", parse_mode="HTML")

# Start Command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await asyncio.to_thread(db_add_or_update_user, user.id, user.first_name)
    bot_info = await context.bot.get_me()
    
    first_name_safe = html.escape(user.first_name) if user.first_name else "User"
    bot_name_safe = html.escape(bot_info.first_name) if bot_info.first_name else "Bot"

    start_text = (
        f"👋 မင်္ဂလာပါ <b>{first_name_safe}</b>!\n\n"
        f"⚽ <b>{bot_name_safe}</b> မှ ကြိုဆိုပါတယ်။\n"
        f"ဒီ Bot ဟာ Group ထဲမှာ ဘောလုံးပွဲစဉ်များကို ခန့်မှန်းပြီး 🩸 <b>Kachin Coin</b> များ စုဆောင်းနိုင်မည့် Game Bot ဖြစ်ပါတယ်။\n\n"
        f"📌 <b>အဓိက Commands များ -</b>\n"
        f"• `/kc` - မိမိ၏ Coin ပမာဏနှင့် Rank ကို စစ်ဆေးရန်\n"
        f"• `/c &lt;ပမာဏ&gt;` - Group Admin များ စာကြောင်းအရေအတွက် သတ်မှတ်ရန်\n\n"
        f"👇 အောက်ပါ Button ကို နှိပ်ပြီး သင့် Group သို့ Bot ကို ထည့်သွင်းနိုင်ပါသည်-"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add To Group", url=f"https://t.me/{bot_info.username}?startgroup=true")]
    ])
    
    await update.message.reply_text(start_text, parse_mode="HTML", reply_markup=keyboard)

# Admin Panel Command
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != BOT_ADMIN_ID:
        return

    admin_text = (
        f"👑 <b>Bot Admin Commands Panel</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛠️ <b>Media Settings:</b>\n"
        f"• `/g set` (Reply to Photo/Video) - Game စချိန် Media သတ်မှတ်ရန်\n"
        f"• `/g del` - Game Media ပြန်ဖျက်ရန်\n"
        f"• `/r set` (Reply to Photo/Video) - Result ထွက်ချိန် Media သတ်မှတ်ရန်\n"
        f"• `/r del` - Result Media ပြန်ဖျက်ရန်\n\n"
        f"⚙️ <b>System Controls:</b>\n"
        f"• `/c &lt;အရေအတွက်&gt;` - စာကြောင်း အရေအတွက် သတ်မှတ်ရန်\n"
        f"• `/stats` - User နှင့် Group စာရင်း ကြည့်ရန်\n"
        f"• `/broadcast` (Reply to Message) - User/Group အားလုံးသို့ စာပို့ရန်\n"
    )
    await update.message.reply_text(admin_text, parse_mode="HTML")

# Custom Game & Result Media Setters (Admin Only)
async def media_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != BOT_ADMIN_ID:
        return

    cmd = update.message.text.strip().split()
    if not cmd:
        return

    main_cmd = cmd[0].lower()
    sub_cmd = cmd[1].lower() if len(cmd) > 1 else ""

    setting_key = "game_media" if main_cmd == "/g" else ("result_media" if main_cmd == "/r" else None)
    if setting_key is None:
        return

    if sub_cmd == "set":
        reply = update.message.reply_to_message
        if not reply:
            await update.message.reply_text("⚠️ ပုံ သို့မဟုတ် ဗီဒီယိုကို Reply ထောက်ပြီး မိန့်ခွန်းပေးပါ။")
            return

        if reply.photo:
            await asyncio.to_thread(db_set_setting, setting_key, reply.photo[-1].file_id, "photo")
            await update.message.reply_text("✅ Photo ကို အောင်မြင်စွာ သတ်မှတ်လိုက်ပါပြီ။")
        elif reply.video:
            await asyncio.to_thread(db_set_setting, setting_key, reply.video.file_id, "video")
            await update.message.reply_text("✅ Video ကို အောင်မြင်စွာ သတ်မှတ်လိုက်ပါပြီ။")
        else:
            await update.message.reply_text("❌ Photo သို့မဟုတ် Video မဟုတ်ပါ။")

    elif sub_cmd == "del":
        await asyncio.to_thread(db_delete_setting, setting_key)
        await update.message.reply_text("🗑️ Media ကို ဖျက်လိုက်ပါပြီ။")

# Stats Command
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_ADMIN_ID:
        return

    def get_stats():
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            u_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM groups")
            g_count = cursor.fetchone()[0]
            cursor.close()
            return u_count, g_count

    total_users, total_groups = await asyncio.to_thread(get_stats)

    msg = (
        f"📊 <b>BOT STATISTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Total Users:</b> <code>{total_users}</code>\n"
        f"🏰 <b>Total Groups:</b> <code>{total_groups}</code>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# Broadcast Command
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_ADMIN_ID:
        return

    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("⚠️ Broadcast လုပ်လိုသည့် Message ကို Reply ထောက်၍ `/broadcast` ဟု ရိုက်ပါ။")
        return

    status_msg = await update.message.reply_text("🚀 Broadcast စတင်ပို့ဆောင်နေပါသည်...")

    def get_broadcast_targets():
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT chat_id FROM groups")
            groups = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return list(set(users) | set(groups))

    targets = await asyncio.to_thread(get_broadcast_targets)
    success = 0
    failed = 0

    for chat_id in targets:
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=reply.chat_id, message_id=reply.message_id)
            success += 1
            await asyncio.sleep(0.04) # Telegram Rate Limit Protection
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=reply.chat_id, message_id=reply.message_id)
                success += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ <b>Broadcast ပြီးစီးပါပြီ!</b>\n\n🎯 Success: {success}\n❌ Failed: {failed}", parse_mode="HTML")

# Message Handler & Trigger
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if update.effective_chat.type == "private":
        if user:
            await asyncio.to_thread(db_add_or_update_user, user.id, user.first_name)
        return

    # Track Group and Users
    if update.effective_chat.title:
        await asyncio.to_thread(db_add_group, chat_id, update.effective_chat.title)

    if user:
        await asyncio.to_thread(db_add_or_update_user, user.id, user.first_name)
        await asyncio.to_thread(db_add_group_user, chat_id, user.id)

    if update.message and update.message.text and update.message.text.startswith('/'):
        return

    if chat_id in active_games:
        return

    group_counters[chat_id] = group_counters.get(chat_id, 0) + 1
    current_count = group_counters[chat_id]

    threshold = CACHE_SETTINGS.get("threshold", 6)
    if current_count >= threshold:
        group_counters[chat_id] = 0
        asyncio.create_task(start_game(chat_id, context))

# UI Text Generator
def generate_game_text(game):
    t1 = TEAMS[game['team1']]
    t2 = TEAMS[game['team2']]

    list_t1 = [get_mention(uid, b['name']) for uid, b in game['bets'].items() if b['choice'] == '1']
    list_draw = [get_mention(uid, b['name']) for uid, b in game['bets'].items() if b['choice'] == 'draw']
    list_t2 = [get_mention(uid, b['name']) for uid, b in game['bets'].items() if b['choice'] == '2']

    text = (
        f"⚽  <b>𝗖𝗵𝗼𝗼𝘀𝗲 𝗙𝗼𝗿 𝗪𝗶𝗻 🍀</b>\n\n"
        f"🏖️ {t1['emoji']} <b>{game['team1']}</b> 𝚟𝚜 <b>{game['team2']}</b> {t2['emoji']} ⛵\n\n"
        f"⛲ 𝘚𝘵𝘢𝘥𝘪𝘶𝘮 - {t1['stadium']}\n"
        f"⏲ 𝘛𝘪𝘮𝘦 𝘓𝘦𝘧𝘵 - <code>{game['time_left']}</code>s\n\n"
        f"🧩 𝙇𝙞𝙫𝙚 𝘽𝙚𝙩𝙩𝙞𝙣𝙜 𝙇𝙞𝙨𝙩\n\n"
        f"♠️ <b>{game['team1']}:</b> {', '.join(list_t1) if list_t1 else '-'}\n"
        f"♦️ <b>Draw:</b> {', '.join(list_draw) if list_draw else '-'}\n"
        f"♥ <b>{game['team2']}:</b> {', '.join(list_t2) if list_t2 else '-'}\n\n"
        f"GᴏᴏᴅLᴜᴄᴋ G_ʏ ☘️"
    )
    return text

# Start Game
async def start_game(chat_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        team1_name, team2_name = random.sample(list(TEAMS.keys()), 2)
        team1 = TEAMS[team1_name]
        team2 = TEAMS[team2_name]

        game_data = {
            "team1": team1_name,
            "team2": team2_name,
            "bets": {},
            "time_left": 60
        }
        active_games[chat_id] = game_data

        keyboard = [
            [
                InlineKeyboardButton(f"{team1['emoji']} {team1_name}", callback_data="bet_1"),
                InlineKeyboardButton(f"{team2['emoji']} {team2_name}", callback_data="bet_2")
            ],
            [
                InlineKeyboardButton("🤝 Draw", callback_data="bet_draw")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = generate_game_text(game_data)

        val, media_type = await asyncio.to_thread(db_get_setting, "game_media")
        game_media = {"type": media_type, "file_id": val} if val else {"type": None, "file_id": None}

        if game_media["type"] == "photo":
            sent_msg = await context.bot.send_photo(chat_id=chat_id, photo=game_media["file_id"], caption=text, parse_mode="HTML", reply_markup=reply_markup)
        elif game_media["type"] == "video":
            sent_msg = await context.bot.send_video(chat_id=chat_id, video=game_media["file_id"], caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)

        game_data["message_id"] = sent_msg.message_id

        # Countdown Loop
        for _ in range(12):
            await asyncio.sleep(5)
            if chat_id not in active_games:
                return
            game_data["time_left"] -= 5
            try:
                if game_media["type"]:
                    await context.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=game_data["message_id"],
                        caption=generate_game_text(game_data),
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=game_data["message_id"],
                        text=generate_game_text(game_data),
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            except BadRequest:
                pass
            except Exception as e:
                logger.error(f"Error updating game countdown: {e}")

        await resolve_game(chat_id, context)

    except Exception as e:
        logger.error(f"Error in start_game: {e}")
        active_games.pop(chat_id, None)

# Button Handler
async def handle_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user = query.from_user

    if chat_id not in active_games:
        await query.answer("❌ ဒီပွဲစဉ်အတွက် အချိန်ကုန်သွားပါပြီ။", show_alert=True)
        return

    choice = query.data.replace("bet_", "")
    game = active_games[chat_id]

    await asyncio.to_thread(db_add_or_update_user, user.id, user.first_name)
    game["bets"][user.id] = {
        "name": user.first_name,
        "choice": choice
    }

    choice_name = game['team1'] if choice == '1' else (game['team2'] if choice == '2' else "Draw")
    await query.answer(f"✅ သင်သည် {choice_name} ကို ရွေးချယ်လိုက်ပါပြီ။")

# Game Result
async def resolve_game(chat_id, context: ContextTypes.DEFAULT_TYPE):
    game = active_games.pop(chat_id, None)
    if not game:
        return

    msg_id = game.get("message_id")

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass

    try:
        anim_msg = await context.bot.send_dice(chat_id=chat_id, emoji="⚡")
        await asyncio.sleep(3)
        await context.bot.delete_message(chat_id=chat_id, message_id=anim_msg.message_id)
    except Exception:
        pass

    score1 = random.randint(0, 4)
    score2 = random.randint(0, 4)

    if score1 > score2:
        winning_choice = "1"
        winner_name = game["team1"]
    elif score2 > score1:
        winning_choice = "2"
        winner_name = game["team2"]
    else:
        winning_choice = "draw"
        winner_name = "Draw"

    winners = []
    losers = []

    for user_id, bet in game["bets"].items():
        user_mt = get_mention(user_id, bet['name'])
        if bet["choice"] == winning_choice:
            reward = 30 if winning_choice == "draw" else 10
            await asyncio.to_thread(db_add_coins, user_id, reward)
            winners.append(f"{user_mt} (+{reward} 🩸Kachin Coin)")
        else:
            losers.append(f"{user_mt}")

    t1 = TEAMS[game['team1']]
    t2 = TEAMS[game['team2']]

    result_text = (
        f"🎗️  <b>𝗠𝗮𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁   🧶</b>\n\n"
        f"🏖️ {t1['emoji']} <b>{game['team1']}</b> {score1} - {score2} <b>{game['team2']}</b> {t2['emoji']} 🪂\n\n"
        f"⚡ 𝗪𝗶𝗻 - <b>{winner_name}</b>\n\n"
        f"✨ <b>𝐖𝐢𝐧𝐧𝐞𝐫𝐬 -</b>\n" + ("\n".join([f"• {w}" for w in winners]) if winners else "• မရှိပါ") + "\n\n"
        f"🐸 <b>𝐋𝐨𝐬𝐬𝐞𝐫𝐬 -</b>\n" + ("\n".join([f"• {l}" for l in losers]) if losers else "• မရှိပါ")
    )

    keyboard = [
        [
            InlineKeyboardButton("🏆 Top In Gp", callback_data="top_gp"),
            InlineKeyboardButton("🌐 Global Top", callback_data="top_global")
        ],
        [
            InlineKeyboardButton("🏰 Top Groups", callback_data="top_groups")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    last_result_data[chat_id] = {
        "text": result_text,
        "markup": reply_markup
    }

    val, media_type = await asyncio.to_thread(db_get_setting, "result_media")
    result_media = {"type": media_type, "file_id": val} if val else {"type": None, "file_id": None}

    if result_media["type"] == "photo":
        await context.bot.send_photo(chat_id=chat_id, photo=result_media["file_id"], caption=result_text, parse_mode="HTML", reply_markup=reply_markup)
    elif result_media["type"] == "video":
        await context.bot.send_video(chat_id=chat_id, video=result_media["file_id"], caption=result_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="HTML", reply_markup=reply_markup)

# /kc Command Check User Info
async def check_kc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await asyncio.to_thread(db_add_or_update_user, user_id, user.first_name)

    info = await asyncio.to_thread(db_get_user_info, user_id)
    coins = info[1] if info else 0
    user_mt = get_mention(user_id, user.first_name)

    def get_rank():
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE coins > %s", (coins,))
            higher_rank_users = cursor.fetchone()[0]
            cursor.close()
            return higher_rank_users + 1

    rank_num = await asyncio.to_thread(get_rank)
    rank = f"#{rank_num}" if coins > 0 else "Unranked"

    msg = (
        f"💳 <b>KACHIN COIN INFO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Name:</b> {user_mt}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🩸 <b>Kachin Coin:</b> <b>{coins}</b>\n"
        f"🏆 <b>Global Rank:</b> <b>{rank}</b>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# Leaderboard Callback Query Handler
async def handle_leaderboards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    back_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_result")]])

    async def update_msg(text, markup):
        try:
            if query.message.photo or query.message.video:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

    if data == "top_gp":
        def get_top_gp():
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT u.user_id, u.first_name, u.coins 
                    FROM group_users gu 
                    JOIN users u ON gu.user_id = u.user_id 
                    WHERE gu.chat_id = %s AND u.coins > 0 
                    ORDER BY u.coins DESC LIMIT 10
                """, (chat_id,))
                res = cursor.fetchall()
                cursor.close()
                return res

        top10 = await asyncio.to_thread(get_top_gp)

        text = "🏆 <b>TOP 10 IN GROUP</b>\n━━━━━━━━━━━━━━━━━━━\n"
        if not top10:
            text += "မရှိသေးပါ"
        else:
            for idx, (uid, name, c) in enumerate(top10, start=1):
                text += f"{idx}. {get_mention(uid, name)} — <b>{c}</b> 🩸\n"

        await update_msg(text, back_button)

    elif data == "top_global":
        def get_top_global():
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, first_name, coins FROM users WHERE coins > 0 ORDER BY coins DESC LIMIT 10")
                res = cursor.fetchall()
                cursor.close()
                return res

        global_scores = await asyncio.to_thread(get_top_global)

        text = "🌐 <b>GLOBAL TOP 10 PLAYERS</b>\n━━━━━━━━━━━━━━━━━━━\n"
        if not global_scores:
            text += "မရှိသေးပါ"
        else:
            for idx, (uid, name, c) in enumerate(global_scores, start=1):
                text += f"{idx}. {get_mention(uid, name)} — <b>{c}</b> 🩸\n"

        await update_msg(text, back_button)

    elif data == "top_groups":
        def get_top_groups():
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT g.chat_id, g.title, SUM(u.coins) as total_coins 
                    FROM group_users gu 
                    JOIN groups g ON gu.chat_id = g.chat_id 
                    JOIN users u ON gu.user_id = u.user_id 
                    GROUP BY g.chat_id, g.title 
                    HAVING SUM(u.coins) > 0 
                    ORDER BY total_coins DESC LIMIT 10
                """)
                res = cursor.fetchall()
                cursor.close()
                return res

        sorted_gps = await asyncio.to_thread(get_top_groups)

        text = "🏰 <b>The Group with the Highest Total Kachi Coin</b>\n━━━━━━━━━━━━━━━━━━━\n"
        if not sorted_gps:
            text += "မရှိသေးပါ"
        else:
            for idx, (g_id, g_title, tot) in enumerate(sorted_gps, start=1):
                text += f"{idx}. <b>{html.escape(g_title if g_title else f'Group {g_id}')}</b> — <b>{tot}</b> 🩸\n"

        await update_msg(text, back_button)

    elif data == "back_to_result":
        orig_data = last_result_data.get(chat_id)
        if orig_data:
            await update_msg(orig_data["text"], orig_data["markup"])
        else:
            await query.answer("မရရှိနိုင်တော့ပါ။", show_alert=True)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("c", set_counter))
    app.add_handler(CommandHandler("kc", check_kc))
    app.add_handler(CommandHandler("bal", check_kc))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # Photo / Video Commands for Admin
    app.add_handler(CommandHandler("g", media_control))
    app.add_handler(CommandHandler("r", media_control))

    app.add_handler(CallbackQueryHandler(handle_bet, pattern="^bet_"))
    app.add_handler(CallbackQueryHandler(handle_leaderboards, pattern="^(top_gp|top_global|top_groups|back_to_result)$"))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

    print("=== Bot is running cleanly with PostgreSQL Connection Pool ===")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
