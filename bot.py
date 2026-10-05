import logging
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
CHANNEL_USERNAME = "@TeleFeedBookChannel"  # Channel Username
CHANNEL_LINK = "https://t.me/TeleFeedBookChannel"

# DATABASE CONNECTION (PostgreSQL Support for Railway)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS post_views (
        user_id BIGINT,
        post_id INT,
        PRIMARY KEY (user_id, post_id)
    );
    """)

    # Group Settings Table (Added group_title, added_by, group_username for list tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_settings (
        chat_id BIGINT PRIMARY KEY,
        group_title TEXT,
        group_username TEXT,
        added_by BIGINT,
        msg_limit INT DEFAULT 20,
        current_count INT DEFAULT 0
    );
    """)

    # Global Config Table (For global default message limit)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS global_config (
        key TEXT PRIMARY KEY,
        value_int INT
    );
    """)
    cursor.execute("INSERT INTO global_config (key, value_int) VALUES ('default_msg_limit', 20) ON CONFLICT (key) DO NOTHING;")

    # Group Post History Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_post_history (
        chat_id BIGINT,
        post_id INT,
        PRIMARY KEY (chat_id, post_id)
    );
    """)

    conn.commit()
    cursor.close()
    conn.close()

# Initialize Database
init_db()


# Helper: Get Global Default Message Limit
def get_global_limit() -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value_int FROM global_config WHERE key = 'default_msg_limit'")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else 20


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


# Helper: Random Unseen Post ID (User DM အတွက်)
def get_random_post_id(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT post_id FROM posts 
        WHERE post_id NOT IN (SELECT post_id FROM post_views WHERE user_id = %s)
        ORDER BY RANDOM() LIMIT 1
    """, (user_id,))
    unseen_post = cursor.fetchone()

    if unseen_post:
        cursor.close()
        conn.close()
        return unseen_post[0]

    cursor.execute("SELECT post_id FROM posts ORDER BY RANDOM() LIMIT 1")
    any_post = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return any_post[0] if any_post else None


# Helper: Random Post ID (Group များအတွက်)
def get_random_group_post_id(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT post_id FROM posts 
        WHERE post_id NOT IN (SELECT post_id FROM group_post_history WHERE chat_id = %s)
        ORDER BY RANDOM() LIMIT 1
    """, (chat_id,))
    unseen_post = cursor.fetchone()

    if unseen_post:
        post_id = unseen_post[0]
        cursor.execute("INSERT INTO group_post_history (chat_id, post_id) VALUES (%s, %s)", (chat_id, post_id))
        conn.commit()
        cursor.close()
        conn.close()
        return post_id

    # အကုန်ကျဖူးသွားရင် History ရှင်းပြီး Random ပြန်စမည်
    cursor.execute("DELETE FROM group_post_history WHERE chat_id = %s", (chat_id,))
    conn.commit()

    cursor.execute("SELECT post_id FROM posts ORDER BY RANDOM() LIMIT 1")
    any_post = cursor.fetchone()
    if any_post:
        cursor.execute("INSERT INTO group_post_history (chat_id, post_id) VALUES (%s, %s)", (chat_id, any_post[0]))
        conn.commit()

    cursor.close()
    conn.close()
    return any_post[0] if any_post else None


# Helper: Post UI Render (DM နှင့် Group ခွဲခြားထားပါသည်)
def render_post_ui(post_id: int, user_id: int, is_profile: bool = False, current_index: int = 0, total_posts: int = 0, is_group: bool = False, bot_username: str = ""):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, post_type, file_id, caption FROM posts WHERE post_id = %s", (post_id,))
    post = cursor.fetchone()
    if not post:
        cursor.close()
        conn.close()
        return None, None, None

    author_id, post_type, file_id, caption = post

    if not is_group:
        cursor.execute("""
            INSERT INTO post_views (user_id, post_id) VALUES (%s, %s)
            ON CONFLICT (user_id, post_id) DO NOTHING
        """, (user_id, post_id))
        conn.commit()

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
        InlineKeyboardButton(f"{r} {counts[r]}", callback_data=f"rec_{post_id}_{r}_{'grp' if is_group else 'dm'}")
        for r in reactions_list
    ]

    keyboard = [rec_buttons]

    # Group ထဲတွင် ကျလာပါက Reaction Button အောက်၌ "✍️ Post တင်ရန်" Button ထည့်မည်
    if is_group:
        post_url = f"https://t.me/{bot_username}?start=post" if bot_username else CHANNEL_LINK
        keyboard.append([InlineKeyboardButton("✍️ Post တင်ရန်", url=post_url)])

    # DM မဟုတ်မှသာ Next, Profile, Popular ခလုတ်များ ထည့်မည်
    if not is_group:
        nav_buttons = []
        if is_profile:
            if current_index > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"profnav_{current_index - 1}"))
            if current_index < total_posts - 1:
                nav_buttons.append(InlineKeyboardButton("▶ Next", callback_data=f"profnav_{current_index + 1}"))
        else:
            nav_buttons.append(InlineKeyboardButton("▶ Next Post", callback_data=f"feednav_{post_id}_next"))

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
            
            if user_id == ADMIN_ID:
                keyboard.append([InlineKeyboardButton("🗑 Dele (Admin Only)", callback_data=f"admin_dele_{post_id}")])

    cursor.close()
    conn.close()
    return text, InlineKeyboardMarkup(keyboard), (post_type, file_id)


# Helper: Group List Page Generator
async def build_grouplist_page(bot, page: int = 0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, group_title, group_username, added_by, msg_limit FROM group_settings ORDER BY chat_id DESC")
    groups = cursor.fetchall()
    cursor.close()
    conn.close()

    if not groups:
        return "❌ မည်သည့် Group မှ မရှိသေးပါ bro!", InlineKeyboardMarkup([])

    per_page = 5
    total_groups = len(groups)
    max_page = (total_groups - 1) // per_page

    if page < 0:
        page = 0
    if page > max_page:
        page = max_page

    start_idx = page * per_page
    page_groups = groups[start_idx : start_idx + per_page]

    text = f"📋 **Bot Joined Groups List** (Total: {total_groups})\n"
    text += f"📄 Page: {page + 1} / {max_page + 1}\n\n"

    for idx, (chat_id, title, username, added_by, msg_limit) in enumerate(page_groups, start=start_idx + 1):
        g_title = escape_markdown(title or "Unknown Group")
        
        # Link ရယူခြင်း
        if username:
            link_str = f"[https://t.me/{username}](https://t.me/{username})"
        else:
            try:
                invite_link = await bot.export_chat_invite_link(chat_id)
                link_str = f"[Group Link]({invite_link})"
            except Exception:
                link_str = "`Private/No Link`"

        # Member Count ရယူခြင်း
        try:
            member_count = await bot.get_chat_member_count(chat_id)
        except Exception:
            member_count = "Unknown"

        # Adder User Info ရယူခြင်း
        added_by_str = f"`{added_by}`" if added_by else "Unknown"
        if added_by:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT username FROM users WHERE user_id = %s", (added_by,))
            u_row = c.fetchone()
            if u_row and u_row[0]:
                added_by_str = f"[{escape_markdown(u_row[0])}](tg://user?id={added_by})"
            c.close()
            conn.close()

        text += (
            f"**{idx}. {g_title}**\n"
            f"• **Group ID:** `{chat_id}`\n"
            f"• **Link:** {link_str}\n"
            f"• **Added By:** {added_by_str}\n"
            f"• **Members:** `{member_count}`\n"
            f"• **Msg Limit:** `{msg_limit}`\n"
            f"-----------------------------------\n"
        )

    # Navigation Buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"gplist_{page - 1}"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"gplist_{page + 1}"))

    keyboard = [nav_buttons] if nav_buttons else []
    return text, InlineKeyboardMarkup(keyboard)


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
    # Group ထဲတွင် /start ခေါ်ပါက မည်သည့်အရာမှ ပြန်မလုပ်ပါ
    if update.effective_chat.type in ["group", "supergroup"]:
        return

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
    
    # Add to Group Button ထည့်သွင်းခြင်း
    bot_username = context.bot.username
    add_group_url = f"https://t.me/{bot_username}?startgroup=true"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add to Group", url=add_group_url)]
    ])

    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def create_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        return

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
    if update.effective_chat.type in ["group", "supergroup"]:
        return

    user_id = update.effective_user.id

    if not await check_channel_member(context.bot, user_id):
        await update.message.reply_text("⚠️ Feed ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    post_id = get_random_post_id(user_id)

    if not post_id:
        await update.message.reply_text("လောလောဆယ် Post မရှိသေးပါဘူး bro!", reply_to_message_id=update.message.message_id)
        return

    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)

    if post_type == "photo":
        await update.message.reply_photo(photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
    elif post_type == "video":
        await update.message.reply_video(video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        return

    user = update.effective_user

    if not await check_channel_member(context.bot, user.id):
        await update.message.reply_text("⚠ Profile ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    profile_text, reply_markup = get_profile_dashboard(user)
    await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        return

    if not await check_channel_member(context.bot, update.effective_user.id):
        await update.message.reply_text("⚠️ Popular Posts ကြည့်ရန် အောက်ပါ Channel ကို အရင် Join ပေးပါ bro!", reply_markup=get_force_join_keyboard(), reply_to_message_id=update.message.message_id)
        return

    msg, keyboard = get_popular_data(context.bot.username)
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


# --- Stats Command (Group Count ပါဝင်သည်) ---
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM posts")
    total_posts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reactions")
    total_reactions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM group_settings")
    total_groups = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    stats_msg = (
        "📊 **Bot Overall Statistics**\n\n"
        f"• **Total Users:** `{total_users}`\n"
        f"• **Total Posts:** `{total_posts}`\n"
        f"• **Total Reactions:** `{total_reactions}`\n"
        f"• **Total Active Groups:** `{total_groups}`"
    )

    await update.message.reply_text(stats_msg, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


# --- Admin Command: /add (Global & Group Specific Limit) ---
async def set_group_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ ကျေးဇူးပြုပြီး ဂဏန်းထည့်ပေးပါ။ ဥပမာ - `/add 20`", parse_mode="Markdown")
        return

    limit = int(context.args[0])
    chat_type = update.effective_chat.type

    conn = get_db_connection()
    cursor = conn.cursor()

    # DM တွင် ခေါ်ဆိုပါက Global Default Limit ကို ပြောင်းလဲမည်
    if chat_type in ["private"]:
        cursor.execute("UPDATE global_config SET value_int = %s WHERE key = 'default_msg_limit'", (limit,))
        cursor.execute("UPDATE group_settings SET msg_limit = %s", (limit,))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text(f"🌐 **Global Limit Updated!**\n\nGroup အားလုံးအတွက် Default Message Limit ကို `{limit}` ဟု သတ်မှတ်လိုက်ပါပြီ bro!", parse_mode="Markdown")
        return

    # Group ထဲတွင် ခေါ်ဆိုပါက အဆိုပါ Group တစ်ခုတည်းအတွက် Limit သတ်မှတ်မည်
    chat = update.effective_chat
    chat_id = chat.id

    cursor.execute("""
        INSERT INTO group_settings (chat_id, group_title, group_username, msg_limit, current_count) 
        VALUES (%s, %s, %s, %s, 0)
        ON CONFLICT (chat_id) DO UPDATE SET 
            msg_limit = EXCLUDED.msg_limit,
            group_title = EXCLUDED.group_title,
            group_username = EXCLUDED.group_username
    """, (chat_id, chat.title, chat.username, limit))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"✅ ဒီ Group အတွက် Message `{limit}` ကြောင်း ပြည့်တိုင်း Post တစ်ခု အလိုအလျောက် ကျလာပါမည် bro!", parse_mode="Markdown")


# --- Admin Command: /grouplist ---
async def show_group_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    if update.effective_chat.type in ["group", "supergroup"]:
        return

    text, reply_markup = await build_grouplist_page(context.bot, page=0)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown", reply_to_message_id=update.message.message_id)


# --- Group Message Listener & Random Post Sender ---
async def track_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return

    chat_id = chat.id
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT msg_limit, current_count FROM group_settings WHERE chat_id = %s", (chat_id,))
    res = cursor.fetchone()

    default_limit = get_global_limit()

    if not res:
        inviter_id = update.effective_user.id if update.effective_user else None
        cursor.execute("""
            INSERT INTO group_settings (chat_id, group_title, group_username, added_by, msg_limit, current_count) 
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (chat_id, chat.title, chat.username, inviter_id, default_limit))
        conn.commit()
        cursor.close()
        conn.close()
        return

    msg_limit, current_count = res
    new_count = current_count + 1

    if new_count >= msg_limit:
        # Counter ကို Reset ပြန်လုပ်မည်
        cursor.execute("UPDATE group_settings SET current_count = 0, group_title = %s, group_username = %s WHERE chat_id = %s", (chat.title, chat.username, chat_id))
        conn.commit()
        cursor.close()
        conn.close()

        # Group အတွက် Random Post ဆွဲယူမည်
        post_id = get_random_group_post_id(chat_id)
        if post_id:
            text, reply_markup, (post_type, file_id) = render_post_ui(
                post_id, user_id=0, is_group=True, bot_username=context.bot.username
            )
            if post_type == "photo":
                await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            elif post_type == "video":
                await context.bot.send_video(chat_id=chat_id, video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        cursor.execute("UPDATE group_settings SET current_count = %s, group_title = %s, group_username = %s WHERE chat_id = %s", (new_count, chat.title, chat.username, chat_id))
        conn.commit()
        cursor.close()
        conn.close()


# --- Callbacks ---

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Reaction ပေးရန် Channel ကို အရင် Join ထားရပါမည်!", show_alert=True)
        return

    await query.answer()

    data = query.data.split("_")
    post_id = int(data[1])
    selected_rec = data[2]
    is_group = (data[3] == "grp")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reactions (post_id, user_id, reaction) VALUES (%s, %s, %s)
        ON CONFLICT (post_id, user_id) DO UPDATE SET reaction = EXCLUDED.reaction
    """, (post_id, user_id, selected_rec))
    conn.commit()
    cursor.close()
    conn.close()

    text, reply_markup, _ = render_post_ui(
        post_id, user_id, is_profile=False, is_group=is_group, bot_username=context.bot.username
    )
    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except Exception:
        pass


async def handle_grouplist_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.answer("❌ Admin Only!", show_alert=True)
        return

    await query.answer()
    page = int(query.data.split("_")[1])

    text, reply_markup = await build_grouplist_page(context.bot, page=page)
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        pass


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

async def handle_feed_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass

    post_id = get_random_post_id(user_id)
    if not post_id:
        await context.bot.send_message(chat_id=user_id, text="လောလောဆယ် Post များ မရှိသေးပါဘူး bro!")
        return

    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)
    if post_type == "photo":
        await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    elif post_type == "video":
        await context.bot.send_video(chat_id=user_id, video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_admin_delete_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.answer("❌ ဒီ ခလုတ်ကို Admin သီးသန့်သာ အသုံးပြုခွင့်ရှိပါတယ် bro!", show_alert=True)
        return
    post_id = int(query.data.split("_")[2])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM posts WHERE post_id = %s", (post_id,))
    cursor.execute("DELETE FROM reactions WHERE post_id = %s", (post_id,))
    cursor.execute("DELETE FROM post_views WHERE post_id = %s", (post_id,))
    conn.commit()
    cursor.close()
    conn.close()
    await query.answer("🗑 Post ကို အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ Admin!", show_alert=True)
    try:
        await query.message.delete()
    except Exception:
        pass

async def handle_view_my_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
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
    try:
        await query.message.delete()
    except Exception:
        pass
    post_id = user_posts[0][0]
    text, reply_markup, (post_type, file_id) = render_post_ui(
        post_id, user_id, is_profile=True, current_index=0, total_posts=len(user_posts)
    )
    if post_type == "photo":
        await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    elif post_type == "video":
        await context.bot.send_video(chat_id=user_id, video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

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
    try:
        await query.message.delete()
    except Exception:
        pass
    post_id = user_posts[target_index][0]
    text, reply_markup, (post_type, file_id) = render_post_ui(
        post_id, user_id, is_profile=True, current_index=target_index, total_posts=len(user_posts)
    )
    if post_type == "photo":
        await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    elif post_type == "video":
        await context.bot.send_video(chat_id=user_id, video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_delete_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("_")
    post_id = int(data[2])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM posts WHERE post_id = %s AND user_id = %s", (post_id, user_id))
    cursor.execute("DELETE FROM reactions WHERE post_id = %s", (post_id,))
    cursor.execute("DELETE FROM post_views WHERE post_id = %s", (post_id,))
    conn.commit()
    await query.answer("🗑 Post ကို အောင်မြင်စွာ ဖျက်လိုက်ပါပြီ!", show_alert=True)
    try:
        await query.message.delete()
    except Exception:
        pass
    profile_text, reply_markup = get_profile_dashboard(query.from_user)
    await context.bot.send_message(chat_id=user_id, text=profile_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_back_to_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    profile_text, reply_markup = get_profile_dashboard(user)
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(chat_id=user.id, text=profile_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_open_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    post_id = get_random_post_id(user_id)
    if not post_id:
        await context.bot.send_message(chat_id=user_id, text="လောလောဆယ် Post မရှိသေးပါဘူး bro!")
        return
    text, reply_markup, (post_type, file_id) = render_post_ui(post_id, user_id, is_profile=False)
    if post_type == "photo":
        await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    elif post_type == "video":
        await context.bot.send_video(chat_id=user_id, video=file_id, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_open_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await check_channel_member(context.bot, user_id):
        await query.answer("⚠️ Channel ကို အရင် Join ပေးပါ bro!", show_alert=True)
        return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    msg, keyboard = get_popular_data(context.bot.username)
    await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=keyboard, parse_mode="Markdown")


# --- Main ---
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", create_post))
    app.add_handler(CommandHandler("feed", show_feed))
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("popular", show_popular))
    app.add_handler(CommandHandler("stats", show_stats))

    # Admin Commands
    app.add_handler(CommandHandler("add", set_group_limit))
    app.add_handler(CommandHandler("grouplist", show_group_list))

    # Group Text Message Listener
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), track_group_messages))

    # Inline Callbacks
    app.add_handler(CallbackQueryHandler(handle_check_join, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(handle_reaction, pattern="^rec_"))
    app.add_handler(CallbackQueryHandler(handle_grouplist_nav, pattern="^gplist_"))
    app.add_handler(CallbackQueryHandler(handle_feed_nav, pattern="^feednav_"))
    app.add_handler(CallbackQueryHandler(handle_admin_delete_post, pattern="^admin_dele_"))
    app.add_handler(CallbackQueryHandler(handle_view_my_posts, pattern="^view_my_posts$"))
    app.add_handler(CallbackQueryHandler(handle_profile_nav, pattern="^profnav_"))
    app.add_handler(CallbackQueryHandler(handle_delete_post, pattern="^delete_post_"))
    app.add_handler(CallbackQueryHandler(handle_back_to_profile, pattern="^back_to_profile$"))
    app.add_handler(CallbackQueryHandler(handle_back_to_profile, pattern="^open_my_profile$"))
    app.add_handler(CallbackQueryHandler(handle_open_feed, pattern="^open_feed$"))
    app.add_handler(CallbackQueryHandler(handle_open_popular, pattern="^open_popular$"))

    print("FB Advanced Group-Supported Bot စတင်ပွင့်လှစ်နေပါပြီ...")
    app.run_polling()
