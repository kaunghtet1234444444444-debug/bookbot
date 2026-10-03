import logging
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import BadRequest

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8600048570:AAEESJG1PDTCVDgaao_1TpgPNE2TDBHt1Vw")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
CHANNEL_USERNAME = "@TeleFeedBookChannel"  # Channel Username
CHANNEL_LINK = "https://t.me/TeleFeedBookChannel"

# DATABASE CONNECTION (PostgreSQL Support for Railways)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        # Railways Cloud Environment
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        # Local Environment (Fallback to local Postgres if needed, or update connection details)
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "fakebook"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
    return conn

# Database Tables Initialization
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        post_id SERIAL PRIMARY KEY,
        user_id BIGINT,
        post_type TEXT,
        file_id TEXT,
        caption TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reactions (
        post_id INT,
        user_id BIGINT,
        reaction TEXT,
        PRIMARY KEY (post_id, user_id)
    );
    """)
    conn.commit()
    cursor.close()
    conn.close()

# Initialize Database
init_db()


# Helper: Markdown Text Escape
def escape_markdown(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_*`\[\]])', r'\\\1', str(text))


# Helper: Check Force Join
async def check_channel_member(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking channel membership: {e}")
        return False


def get_force_join_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("🔄 Try Again / ပြီးပါပြီ", callback_data="check_join")]
    ]
    return InlineKeyboardMarkup(keyboard)


# Helper: Post UI Render လုပ်ပေးသည့် Function
def render_post_ui(post_id: int, user_id: int, is_profile: bool = False, current_index: int = 0, total_posts: int = 0):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, post_type, file_id, caption FROM posts WHERE post_id = %s", (post_id,))
    post = cursor.fetchone()
    if not post:
        cursor.close()
        conn.close()
        return None, None, None

    author_id, post_type, file_id, caption = post

    # Author Name with Mention Link
    cursor.execute("SELECT username FROM users WHERE user_id = %s", (author_id,))
    author = cursor.fetchone()
    raw_author_name = author[0] if author else "Unknown"
    safe_author_name = escape_markdown(raw_author_name)
    
    header = f"👤 [{safe_author_name}](tg://user?id={author_id})\n"
    if is_profile:
        header += f"📌 Post ({current_index + 1}/{total_posts})\n"
    
    body = f"\n{escape_markdown(caption)}" if caption else ""
    text = f"{header}{body}"

    # Reaction Counts
    reactions_list = ["😂", "❤️", "💩", "👍"]
    counts = {}
    for r in reactions_list:
        cursor.execute("SELECT COUNT(*) FROM reactions WHERE post_id = %s AND reaction = %s", (post_id, r))
        counts[r] = cursor.fetchone()[0]

    rec_buttons = [
        InlineKeyboardButton(f"{r} {counts[r]}", callback_data=f"rec_{post_id}_{r}_{'prof' if is_profile else 'feed'}_{current_index}")
        for r in reactions_list
    ]

    nav_buttons = []
    if is_profile:
        if current_index > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"profnav_{current_index - 1}"))
        if current_index < total_posts - 1:
            nav_buttons.append(InlineKeyboardButton("▶ Next", callback_data=f"profnav_{current_index + 1}"))
    else:
        cursor.execute("SELECT post_id FROM posts WHERE post_id > %s ORDER BY post_id ASC LIMIT 1", (post_id,))
        has_newer = cursor.fetchone()
        
        cursor.execute("SELECT post_id FROM posts WHERE post_id < %s ORDER BY post_id DESC LIMIT 1", (post_id,))
        has_older = cursor.fetchone()

        if has_newer:
            nav_buttons.append(InlineKeyboardButton("◀️ Back Post", callback_data=f"feednav_{post_id}_prev"))
        if has_older:
            nav_buttons.append(InlineKeyboardButton("▶ Next Post", callback_data=f"feednav_{post_id}_next"))

    keyboard = [rec_buttons]
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    if is_profile:
        keyboard.append([InlineKeyboardButton("🗑 Delete This Post", callback_data=f"delete_post_{post_id}_{current_index}")])
        keyboard.append([InlineKeyboardButton("⬅ Back to Profile", callback_data="back_to_profile")])
    else:
        keyboard.append([
            InlineKeyboardButton("🔥 Popular Posts", callback_data="open_popular"),
            InlineKeyboardButton("👤 မိမိ Profile", callback_data="open_my_profile")
        ])

    cursor.close()
    conn.close()
    return text, InlineKeyboardMarkup(keyboard), (post_type, file_id)


# Helper: Profile Dashboard Text & Keyboard
def get_profile_dashboard(user):
    user_id = user.id
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM posts WHERE user_id = %s", (user_id,))
    total_posts = cursor.fetchone()[0]

    cursor.execute("""
        SELECT reaction, COUNT(*) 
        FROM reactions 
        WHERE post_id IN (SELECT post_id FROM posts WHERE user_id = %s) 
        GROUP BY reaction
    """, (user_id,))
    
    rec_results = dict(cursor.fetchall())
    reactions_list = ["😂", "❤️", "💩", "👍"]
    rec_summary = " | ".join([f"{r} {rec_results.get(r, 0)}" for r in reactions_list])

    profile_text = (
        f"👤 **User Profile**\n\n"
        f"• **Name:** [{escape_markdown(user.first_name)}](tg://user?id={user_id})\n"
        f"• **ID:** `{user_id}`\n"
        f"• **Total Posts:** {total_posts}\n\n"
        f"📊 **Total Reactions Received:**\n"
        f"{rec_summary}"
    )

    keyboard = []
    if total_posts > 0:
        keyboard.append([InlineKeyboardButton("🖼 မိမိ Post များကို ကြည့်ရန်", callback_data="view_my_posts")])
    keyboard.append([InlineKeyboardButton("📰 Feed ကြည့်ရန်", callback_data="open_feed")])

    cursor.close()
    conn.close()
    return profile_text, InlineKeyboardMarkup(keyboard)


# Helper: Edit Message with Safety Catch
async def edit_post_message(query, text, reply_markup, post_type, file_id):
    try:
        msg = query.message
        is_media_msg = bool(msg.photo or msg.video)

        if post_type == "photo":
            if is_media_msg:
                await query.edit_message_media(
                    media=InputMediaPhoto(media=file_id, caption=text, parse_mode="Markdown"),
                    reply_markup=reply_markup
                )
            else:
                await msg.delete()
                await msg.reply_photo(photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        elif post_type == "video":
            if is_media_msg:
                await query.edit_message_media(
                    media=InputMediaVideo(media=file_id, caption=text, parse_mode="Markdown"),
                    reply_markup=reply_markup
                )
            else:
                await msg.delete()
                await msg.reply_video(video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            if is_media_msg:
                await msg.delete()
                await msg.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logging.error(f"Error editing message: {e}")
    except Exception as e:
        logging.error(f"Error editing message: {e}")


# Helper: Popular Posts
def get_popular_data(bot_username: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.post_id, p.user_id, u.username, COUNT(r.reaction) as total_recs
        FROM posts p
        LEFT JOIN reactions r ON p.post_id = r.post_id
        LEFT JOIN users u ON p.user_id = u.user_id
        GROUP BY p.post_id, p.user_id, u.username
        ORDER BY total_recs DESC
        LIMIT 10
    """)
    top_posts = cursor.fetchall()
    cursor.close()
    conn.close()

    if not top_posts:
        return "လောလောဆယ် Post များ မရှိသေးပါဘူး bro!", InlineKeyboardMarkup([[InlineKeyboardButton("📰 Feed သို့ ပြန်သွားရန်", callback_data="open_feed")]])

    msg = "🔥 **Top 10 Popular Posts Leaderboard** 🔥\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for idx, (post_id, user_id, username, total_recs) in enumerate(top_posts):
        name = escape_markdown(username) if username else "Unknown"
        medal = medals[idx] if idx < len(medals) else f"{idx+1}."
        
        post_link = f"https://t.me/{bot_username}?start=view_{post_id}"
        msg += f"{medal} [{name}](tg://user?id={user_id}) - **{total_recs} Recs** | [👁 ကြည့်ရန်]({post_link})\n"

    keyboard = [[InlineKeyboardButton("📰 Feed သို့ ပြန်သွားရန်", callback_data="open_feed")]]
    return msg, InlineKeyboardMarkup(keyboard)


# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
    """, (user.id, user.first_name))
    conn.commit()
    cursor.close()
    conn.close()

    if not await check_channel_member(context.bot, user.id):
        await update.message.reply_text(
            "⚠️ Bot ကို အသုံးပြုရန်အတွက် အောက်ပါ Channel ကို မဖြစ်မနေ Join ပေးရန် လိုအပ်ပါတယ် bro!",
            reply_markup=get_force_join_keyboard(),
            reply_to_message_id=update.message.message_id
        )
        return

    if context.args and context.args[0].startswith("view_"):
        try:
            post_id = int(context.args[0].split("_")[1])
            text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user.id, is_profile=False)
            
            if text:
                if post_type == "photo":
                    await update.message.reply_photo(photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
                elif post_type == "video":
                    await update.message.reply_video(video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
                else:
                    await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
                return
            else:
                await update.message.reply_text("❌ ဒီ Post မရှိတော့ပါဘူး bro!", reply_to_message_id=update.message.message_id)
                return
        except Exception:
            pass

    msg = (
        f"မင်္ဂလာပါ {escape_markdown(user.first_name)} bro! 🚀\n\n"
        "📌 **အသုံးပြုနည်းများ:**\n"
        "• **Post တင်ရန်:** စာ/ပုံ/Video ကို Reply (rp) ထောက်ပြီး `/post` ဟု ရိုက်ပါ။\n"
        "• `/feed` - Post များကို တလှည့်စီ ကြည့်ရန်/Reaction ပေးရန်\n"
        "• `/profile` - မိမိ Profile Dashboard ကြည့်ရန်\n"
        "• `/popular` - Popular Post များဆီ သွားရောက်ကြည့်ရှုရန်"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def create_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_channel_member(context.bot, user_id):
        await update.message.reply_text(
            "⚠️ Post မတင်မီ အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!",
            reply_markup=get_force_join_keyboard(),
            reply_to_message_id=update.message.message_id
        )
        return

    reply_msg = update.message.reply_to_message

    if not reply_msg:
        await update.message.reply_text("❌ ကျေးဇူးပြုပြီး Post တင်ချင်တဲ့ စာ/ပုံ/Video Message ကို Reply (rp) ထောက်ပြီး `/post` လို့ ရိုက်ပေးပါ bro!", reply_to_message_id=update.message.message_id)
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (user_id, username) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
    """, (user_id, update.effective_user.first_name))

    post_type = "text"
    file_id = None
    caption = reply_msg.text or reply_msg.caption or ""

    if reply_msg.photo:
        post_type = "photo"
        file_id = reply_msg.photo[-1].file_id
    elif reply_msg.video:
        post_type = "video"
        file_id = reply_msg.video.file_id

    cursor.execute(
        "INSERT INTO posts (user_id, post_type, file_id, caption) VALUES (%s, %s, %s, %s)",
        (user_id, post_type, file_id, caption)
    )
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text("✅ Post ကို အောင်မြင်စွာ တင်ပြီးပါပြီ bro!", reply_to_message_id=update.message.message_id)


async def show_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_channel_member(context.bot, user_id):
        await update.message.reply_text("⚠️ Feed ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id FROM posts ORDER BY post_id DESC LIMIT 1")
    latest_post = cursor.fetchone()
    cursor.close()
    conn.close()

    if not latest_post:
        await update.message.reply_text("လောလောဆယ် Post မရှိသေးပါဘူး bro!", reply_to_message_id=update.message.message_id)
        return

    post_id = latest_post[0]
    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)

    if post_type == "photo":
        await update.message.reply_photo(photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
    elif post_type == "video":
        await update.message.reply_video(video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await check_channel_member(context.bot, user.id):
        await update.message.reply_text("⚠️ Profile ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    profile_text, reply_markup = get_profile_dashboard(user)
    await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_member(context.bot, update.effective_user.id):
        await update.message.reply_text("⚠️ Popular Posts ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    msg, keyboard = get_popular_data(context.bot.username)
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


# --- Admin Commands ---

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM posts")
    total_posts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reactions")
    total_reactions = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    stats_msg = (
        "📊 **Bot Statistics (Admin Only)**\n\n"
        f"👥 စုစုပေါင်း Users: `{total_users}`\n"
        f"📝 စုစုပေါင်း Posts: `{total_posts}`\n"
        f"❤️ စုစုပေါင်း Reactions: `{total_reactions}`"
    )
    await update.message.reply_text(stats_msg, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    reply_msg = update.message.reply_to_message
    if not reply_msg:
        await update.message.reply_text("❌ ကျေးဇူးပြုပြီး Broadcast ပို့ချင်သည့် စာ/ပုံ/Video ကို Reply (rp) ထောက်ပြီး `/broadcast` လို့ ရိုက်ပါ bro!", reply_to_message_id=update.message.message_id)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    success = 0
    failed = 0

    status_msg = await update.message.reply_text("📢 Broadcast စတင် ပို့ဆောင်နေပါပြီ...", reply_to_message_id=update.message.message_id)

    for u in users:
        target_id = u[0]
        try:
            await context.bot.copy_message(
                chat_id=target_id,
                from_chat_id=update.effective_chat.id,
                message_id=reply_msg.message_id
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ **Broadcast ပို့ဆောင်မှု ပြီးစီးပါပြီ!**\n\n"
        f"🎯 အောင်မြင်စွာ ပို့ပြီး: `{success}`\n"
        f"❌ မပို့နိုင်ခဲ့ပါ (Block/Blocked): `{failed}`",
        parse_mode="Markdown"
    )


# --- Callbacks ---

async def handle_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if await check_channel_member(context.bot, user_id):
        await query.answer("✅ Channel Join ထားခြင်း အတည်ပြုပြီးပါပြီ!", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass

        msg = (
            f"မင်္ဂလာပါ {escape_markdown(query.from_user.first_name)} bro! 🚀\n\n"
            "📌 **အသုံးပြုနည်းများ:**\n"
            "• **Post တင်ရန်:** စာ/ပုံ/Video ကို Reply (rp) ထောက်ပြီး `/post` ဟု ရိုက်ပါ။\n"
            "• `/feed` - Post များကို တလှည့်စီ ကြည့်ရန်/Reaction ပေးရန်\n"
            "• `/profile` - မိမိ Profile Dashboard ကြည့်ရန်\n"
            "• `/popular` - Popular Post များဆီ သွားရောက်ကြည့်ရှုရန်"
        )
        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
    else:
        await query.answer("❌ Channel ကို Join မထားရသေးပါဘူး bro! ကျေးဇူးပြုပြီး မဖြစ်မနေ Join ပေးပါ။", show_alert=True)


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠ Reaction ပေးရန် Channel ကို အရင် Join ထားရပါမည်!", show_alert=True)
        return

    await query.answer()

    data = query.data.split("_")
    post_id = int(data[1])
    selected_rec = data[2]
    mode = data[3]
    index = int(data[4]) if len(data) > 4 else 0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reactions (post_id, user_id, reaction) VALUES (%s, %s, %s)
        ON CONFLICT (post_id, user_id) DO UPDATE SET reaction = EXCLUDED.reaction
    """, (post_id, user_id, selected_rec))
    conn.commit()

    is_profile = (mode == "prof")
    total_posts = 0
    if is_profile:
        cursor.execute("SELECT COUNT(*) FROM posts WHERE user_id = %s", (user_id,))
        total_posts = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=is_profile, current_index=index, total_posts=total_posts)
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_feed_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return

    await query.answer()

    data = query.data.split("_")
    current_post_id = int(data[1])
    direction = data[2]

    conn = get_db_connection()
    cursor = conn.cursor()

    if direction == "next":
        cursor.execute("SELECT post_id FROM posts WHERE post_id < %s ORDER BY post_id DESC LIMIT 1", (current_post_id,))
    else:
        cursor.execute("SELECT post_id FROM posts WHERE post_id > %s ORDER BY post_id ASC LIMIT 1", (current_post_id,))

    target_post = cursor.fetchone()
    cursor.close()
    conn.close()

    if not target_post:
        await query.answer("နောက်ထပ် Post မရှိတော့ပါဘူး bro!", show_alert=True)
        return

    post_id = target_post[0]
    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_view_my_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return

    await query.answer()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id FROM posts WHERE user_id = %s ORDER BY post_id DESC", (user_id,))
    user_posts = cursor.fetchall()
    cursor.close()
    conn.close()

    if not user_posts:
        await query.answer("Bro တင်ထားတဲ့ Post မရှိပါဘူး!", show_alert=True)
        return

    post_id = user_posts[0][0]
    text, reply_markup, (post_type, file_id) = render_post_ui(
        post_id, user_id, is_profile=True, current_index=0, total_posts=len(user_posts)
    )
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_profile_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return

    await query.answer()

    target_index = int(query.data.split("_")[1])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id FROM posts WHERE user_id = %s ORDER BY post_id DESC", (user_id,))
    user_posts = cursor.fetchall()
    cursor.close()
    conn.close()

    if not user_posts or target_index < 0 or target_index >= len(user_posts):
        return

    post_id = user_posts[target_index][0]
    text, reply_markup, (post_type, file_id) = render_post_ui(
        post_id, user_id, is_profile=True, current_index=target_index, total_posts=len(user_posts)
    )
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_delete_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    data = query.data.split("_")
    post_id = int(data[2])
    current_index = int(data[3])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM posts WHERE post_id = %s AND user_id = %s", (post_id, user_id))
    cursor.execute("DELETE FROM reactions WHERE post_id = %s", (post_id,))
    conn.commit()

    await query.answer("🗑 Post ကို အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ!", show_alert=True)

    cursor.execute("SELECT post_id FROM posts WHERE user_id = %s ORDER BY post_id DESC", (user_id,))
    remaining_posts = cursor.fetchall()
    cursor.close()
    conn.close()

    if not remaining_posts:
        profile_text, reply_markup = get_profile_dashboard(query.from_user)
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=user_id, text=profile_text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    new_index = current_index if current_index < len(remaining_posts) else len(remaining_posts) - 1
    next_post_id = remaining_posts[new_index][0]

    text, reply_markup, (post_type, file_id) = render_post_ui(
        next_post_id, user_id, is_profile=True, current_index=new_index, total_posts=len(remaining_posts)
    )
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_back_to_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    profile_text, reply_markup = get_profile_dashboard(user)

    try:
        if query.message.photo or query.message.video:
            await query.message.delete()
            await context.bot.send_message(chat_id=user.id, text=profile_text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error returning to profile: {e}")


async def handle_open_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return

    await query.answer()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id FROM posts ORDER BY post_id DESC LIMIT 1")
    latest_post = cursor.fetchone()
    cursor.close()
    conn.close()

    if not latest_post:
        await query.answer("လောလောဆယ် Post မရှိသေးပါဘူး bro!", show_alert=True)
        return

    post_id = latest_post[0]
    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)
    await edit_post_message(query, text, reply_markup, post_type, file_id)


async def handle_open_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return

    await query.answer()

    msg, keyboard = get_popular_data(context.bot.username)

    if query.message.photo or query.message.video:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await query.edit_message_text(msg, reply_markup=keyboard, parse_mode="Markdown")


# --- Main ---
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", create_post))
    app.add_handler(CommandHandler("feed", show_feed))
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("popular", show_popular))

    # Admin Commands
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))

    # Inline Callbacks
    app.add_handler(CallbackQueryHandler(handle_check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(handle_reaction, pattern="^rec_"))
    app.add_handler(CallbackQueryHandler(handle_feed_nav, pattern="^feednav_"))
    app.add_handler(CallbackQueryHandler(handle_view_my_posts, pattern="^view_my_posts$"))
    app.add_handler(CallbackQueryHandler(handle_profile_nav, pattern="^profnav_"))
    app.add_handler(CallbackQueryHandler(handle_delete_post, pattern="^delete_post_"))
    app.add_handler(CallbackQueryHandler(handle_back_to_profile, pattern="^back_to_profile$"))
    app.add_handler(CallbackQueryHandler(handle_back_to_profile, pattern="^open_my_profile$"))
    app.add_handler(CallbackQueryHandler(handle_open_feed, pattern="^open_feed$"))
    app.add_handler(CallbackQueryHandler(handle_open_popular, pattern="^open_popular$"))

    print("FB Advanced Telegram Bot (PostgreSQL Connected) စတင်ပွင့်လှစ်နေပါပြီ...")
    app.run_polling()
