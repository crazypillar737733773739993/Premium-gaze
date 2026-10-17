import logging, sqlite3, secrets, string, io, os
from datetime import datetime, timedelta
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
#  CONFIG  (sirf yahan se sab change karo)
# ════════════════════════════════════════════════════════════
BOT_TOKEN  = "8826518970:AAFbI6GMgf_mnAsZ30W28xCKo17xndP63jQ"
ADMIN_IDS  = [1944038297]
UPI_ID     = "kunwarpayment@fam"
UPI_NAME   = "Premium Gaze"
SUPPORT_TIMEOUT_MIN = 15   # support reply timeout minutes

CHANNELS = {
    "ch1": {"name": "Subhashree Sahu 🔥",          "emoji": "👸", "link": "https://t.me/+o1tKXOkzyZ03YTdl"},
    "ch2": {"name": "Muskan Karia 💎",              "emoji": "💋", "link": "https://t.me/+HJCs2xRZ3mY4MTI1"},
    "ch3": {"name": "Chandni Bhati Exclusive ✨",   "emoji": "🌙", "link": "https://t.me/+qjIh5VdK0tYxNzBl"},
    "ch4": {"name": "Instagram Leaks 📱",           "emoji": "📸", "link": "https://t.me/+728a7ZfnYis1Nzc1"},
    "ch5": {"name": "Sofia Khan Paid Content 👑",   "emoji": "💫", "link": "https://t.me/+YhVH-ypXRg5mOTg1"},
    "ch6": {"name": "Kajal Pandey Exclusive 🍓",    "emoji": "🎀", "link": "https://t.me/+oPhoQR1eI90zZDc1"},
    "ch7": {"name": "Aditi Mistry Paid Content 🔥", "emoji": "💥", "link": "https://t.me/+kq4cdnZWH6MxNGM9"},
    "ch8": {"name": "Lucky Razor Exclusive 💎",     "emoji": "⚡", "link": "https://t.me/+4P2rH94TcGRhZTg1"},
    "ch9": {"name": "1500+ Faphouse Premium 🏆",    "emoji": "🎭", "link": "https://t.me/+OSg7w3VtRjYzODA9"},
}

PLANS = {
    "daily":   {"label": "Daily",   "hours": 24,  "inr": 10,  "stars": 10,  "gc": 10,  "emoji": "⚡"},
    "weekly":  {"label": "Weekly",  "hours": 168, "inr": 60,  "stars": 50,  "gc": 50,  "emoji": "📅"},
    "monthly": {"label": "Monthly", "hours": 720, "inr": 249, "stars": 200, "gc": 200, "emoji": "👑"},
}

TNC = """📜 *TERMS & CONDITIONS — Premium Gaze*

━━━━━━━━━━━━━━━━━━━━━
✅ *1. Age* — Sirf 18+ users. Minor hain to ban.
✅ *2. No Refund* — Payment ke baad koi refund nahi.
✅ *3. Validity* — Daily 24h · Weekly 7d · Monthly 30d.
✅ *4. Single User* — Sharing/reselling = permanent ban.
✅ *5. Content* — Personal use only. Redistribute = legal action.
✅ *6. Verification* — GC/UPI verify hone ke baad access. Stars instant.
✅ *7. Support* — Bot mein message karo. Bahar nahi.
✅ *8. Fraud* — Fake payment = ban + legal notice.
━━━━━━━━━━━━━━━━━━━━━
_"I Agree" press = 18+ confirm + sab accept._"""

GC_PROCESS = """🎁 *Amazon Gift Card Kaise Khareedein?*

━━━━━━━━━━━━━━━━━━━━━
📱 *Google Pay se:*

1️⃣ Google Pay app kholo
2️⃣ Search bar mein *"Gift Card"* type karo
3️⃣ *"Amazon Pay Gift Card"* select karo
4️⃣ Amount select karo (₹10 / ₹50 / ₹60 / ₹249)
5️⃣ Pay karo — code milega screen pe
6️⃣ Woh code *yahan bot mein bhejo*

━━━━━━━━━━━━━━━━━━━━━
📌 *Format:* `XXXX-XXXXXX-XXXX` ya `GC-XXXX-XXXX-XXXX`

⚡ Code receive hote hi access milega!"""

# ════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════
DB = "premium_gaze.db"

@contextmanager
def conn():
    c = sqlite3.connect(DB, detect_types=sqlite3.PARSE_DECLTYPES)
    c.row_factory = sqlite3.Row
    try:
        yield c; c.commit()
    except:
        c.rollback(); raise
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS subs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT,
            plan TEXT, method TEXT, amount TEXT, expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS gc_codes(
            code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER DEFAULT 0,
            used_by INTEGER, used_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS upi_pending(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT,
            plan TEXT, amount INTEGER, file_id TEXT, status TEXT DEFAULT 'pending',
            full_name TEXT, username TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS gc_pending(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT,
            plan TEXT, code TEXT, status TEXT DEFAULT 'pending',
            full_name TEXT, username TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
            full_name TEXT, username TEXT, is_resolved INTEGER DEFAULT 0,
            admin_reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS broadcast_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT,
            sent_count INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """)
        # Migration — purani DB pe naye columns add karo
        try:
            c.execute("ALTER TABLE tickets ADD COLUMN admin_reply TEXT")
        except: pass

# DB helpers
def upsert_user(uid, uname, fname):
    with conn() as c:
        c.execute("INSERT INTO users(user_id,username,full_name) VALUES(?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name",
                  (uid, uname, fname))

def is_banned(uid):
    with conn() as c:
        r = c.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
        return r and r["is_banned"] == 1

def ban_user(uid):
    with conn() as c:
        c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))

def unban_user(uid):
    with conn() as c:
        c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))

def get_all_users():
    with conn() as c:
        return c.execute("SELECT * FROM users ORDER BY joined_at DESC").fetchall()

def add_sub(uid, ch_id, plan, method, amount, hours):
    exp = datetime.now() + timedelta(hours=hours)
    with conn() as c:
        c.execute("INSERT INTO subs(user_id,channel_id,plan,method,amount,expires_at) VALUES(?,?,?,?,?,?)",
                  (uid, ch_id, plan, method, str(amount), exp))
    return exp

def revoke_sub(uid, ch_id):
    with conn() as c:
        c.execute("UPDATE subs SET expires_at=CURRENT_TIMESTAMP WHERE user_id=? AND channel_id=? AND expires_at>CURRENT_TIMESTAMP",
                  (uid, ch_id))

def has_sub(uid, ch_id):
    with conn() as c:
        return c.execute("SELECT id FROM subs WHERE user_id=? AND channel_id=? AND expires_at>CURRENT_TIMESTAMP",
                         (uid, ch_id)).fetchone() is not None

def my_subs(uid):
    with conn() as c:
        return c.execute("SELECT * FROM subs WHERE user_id=? AND expires_at>CURRENT_TIMESTAMP ORDER BY expires_at DESC", (uid,)).fetchall()

def use_gc(code, uid):
    with conn() as c:
        r = c.execute("SELECT * FROM gc_codes WHERE code=? AND is_used=0", (code,)).fetchone()
        if not r: return None
        c.execute("UPDATE gc_codes SET is_used=1,used_by=?,used_at=CURRENT_TIMESTAMP WHERE code=?", (uid, code))
        return r["amount"]

def gen_gc(amount):
    code = "GC-" + "-".join("".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4)) for _ in range(3))
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO gc_codes(code,amount) VALUES(?,?)", (code, amount))
    return code

def list_gc():
    with conn() as c:
        return c.execute("SELECT * FROM gc_codes ORDER BY created_at DESC LIMIT 30").fetchall()

def add_upi_pending(uid, ch_id, plan, amount, file_id, fname, uname):
    with conn() as c:
        c.execute("INSERT INTO upi_pending(user_id,channel_id,plan,amount,file_id,full_name,username) VALUES(?,?,?,?,?,?,?)",
                  (uid, ch_id, plan, amount, file_id, fname, uname))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]

def add_gc_pending(uid, ch_id, plan, code, fname, uname):
    with conn() as c:
        c.execute("INSERT INTO gc_pending(user_id,channel_id,plan,code,full_name,username) VALUES(?,?,?,?,?,?)",
                  (uid, ch_id, plan, code, fname, uname))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]

def close_pending(table, pid, status):
    with conn() as c:
        c.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, pid))

def get_pending_upi():
    with conn() as c:
        return c.execute("SELECT * FROM upi_pending WHERE status='pending' ORDER BY created_at DESC").fetchall()

def get_pending_gc():
    with conn() as c:
        return c.execute("SELECT * FROM gc_pending WHERE status='pending' ORDER BY created_at DESC").fetchall()

def add_ticket(uid, msg, fname, uname):
    with conn() as c:
        c.execute("INSERT INTO tickets(user_id,message,full_name,username) VALUES(?,?,?,?)", (uid, msg, fname, uname))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_tickets():
    with conn() as c:
        return c.execute("SELECT * FROM tickets WHERE is_resolved=0 ORDER BY created_at DESC LIMIT 20").fetchall()

def resolve_ticket(tid, reply=None):
    with conn() as c:
        c.execute("UPDATE tickets SET is_resolved=1, admin_reply=? WHERE id=?", (reply, tid))

def db_stats():
    with conn() as c:
        tu = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        tb = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
        ts = c.execute("SELECT COUNT(*) FROM subs").fetchone()[0]
        td = c.execute("SELECT COUNT(*) FROM subs WHERE date(created_at)=date('now')").fetchone()[0]
        bm = c.execute("SELECT method, COUNT(*) cnt FROM subs GROUP BY method").fetchall()
        bp = c.execute("SELECT plan, COUNT(*) cnt FROM subs GROUP BY plan").fetchall()
        return tu, tb, ts, td, bm, bp

# ════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════
def kb(*rows): return InlineKeyboardMarkup(list(rows))
def btn(text, data=None, url=None):
    return InlineKeyboardButton(text, callback_data=data) if not url else InlineKeyboardButton(text, url=url)

def ch_name(ch_id): return CHANNELS.get(ch_id, {}).get("name", ch_id)
def ch_link(ch_id): return CHANNELS.get(ch_id, {}).get("link", "#")

def make_upi_qr(amount):
    """Generate UPI QR as PNG bytes. Returns None if qrcode not available."""
    if not QR_AVAILABLE:
        return None
    try:
        upi_url = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME.replace(' ','%20')}&am={amount}&cu=INR"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(upi_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"QR gen error: {e}")
        return None

def upi_caption(ch_name, plan_label, plan_emoji, amount):
    return (
        f"Channel: *{ch_name}*\nPlan: *{plan_emoji} {plan_label}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 *QR scan karo ya UPI ID se pay karo:*\n\n"
        f"🏦 UPI ID: `{UPI_ID}`\n"
        f"👤 Name: *{UPI_NAME}*\n"
        f"💰 Amount: *₹{amount}*\n\n"
        f"✅ GPay / PhonePe / Paytm / BHIM — sab chalega\n\n"
        f"📸 Pay ke baad *screenshot yahan bhejo*\n"
        f"⏰ Max *{SUPPORT_TIMEOUT_MIN} min* mein access\n\n"
        f"⚠️ _Galat amount ya fake ss = instant ban_"
    )

async def notify_admins(bot, text, keyboard=None, photo=None):
    for aid in ADMIN_IDS:
        try:
            if photo:
                await bot.send_photo(aid, photo=photo, caption=text, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await bot.send_message(aid, text, parse_mode="Markdown", reply_markup=keyboard)
        except: pass

# ════════════════════════════════════════════════════════════
#  USER HANDLERS
# ════════════════════════════════════════════════════════════

async def start(u: Update, ctx):
    upsert_user(u.effective_user.id, u.effective_user.username, u.effective_user.full_name)
    if is_banned(u.effective_user.id):
        await u.message.reply_text("❌ Aapka account banned hai. Support se contact karein."); return
    await u.message.reply_text(
        "🔥 *Welcome to Premium Gaze* 🔥\n\n"
        "India ka best premium content — verified, exclusive, daily updated.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 *9 Premium Channels*\n"
        "💳 *Plans from just ₹10/day*\n"
        "⭐ Telegram Stars  •  🎁 Gift Card  •  💸 UPI\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Neeche se choose karo 👇",
        parse_mode="Markdown",
        reply_markup=kb(
            [btn("🔥 Browse Channels", "channels")],
            [btn("📋 My Access", "myaccess"), btn("🆘 Support", "support")],
            [btn("ℹ️ How to Buy Gift Card", "gc_howto")]
        )
    )

async def main_menu(u: Update, ctx):
    q = u.callback_query; await q.answer()
    await q.edit_message_text(
        "🔥 *Premium Gaze* 🔥\n\nApna channel choose karo 👇",
        parse_mode="Markdown",
        reply_markup=kb(
            [btn("🔥 Browse Channels", "channels")],
            [btn("📋 My Access", "myaccess"), btn("🆘 Support", "support")],
            [btn("ℹ️ How to Buy Gift Card", "gc_howto")]
        )
    )

# ── Channels ─────────────────────────────────────────────────
async def show_channels(u: Update, ctx):
    q = u.callback_query; await q.answer(); uid = q.from_user.id
    rows = []
    for ch_id, ch in CHANNELS.items():
        tick = "✅ " if has_sub(uid, ch_id) else ""
        rows.append([btn(f"{tick}{ch['emoji']} {ch['name']}", f"ch_{ch_id}")])
    rows.append([btn("🏠 Main Menu", "main_menu")])
    await q.edit_message_text("🎭 *Choose Your Channel*\n\n✅ = Active access hai tumhara",
                               parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))

async def channel_detail(u: Update, ctx):
    q = u.callback_query; await q.answer()
    ch_id = q.data[3:]; ch = CHANNELS.get(ch_id, {}); uid = q.from_user.id
    active = has_sub(uid, ch_id)
    text = f"{ch.get('emoji','')} *{ch.get('name','')}*\n\n"
    if active:
        text += "✅ *Tumhara active access hai is channel pe!*"
        rows = [[btn("🔗 Channel Join Karo", url=ch.get("link","#"))],
                [btn("⬅️ All Channels", "channels")]]
    else:
        text += ("💰 *Plans:*\n"
                 "⚡ Daily — ₹10 / 10⭐ / 10 GC\n"
                 "📅 Weekly — ₹60 / 50⭐ / 50 GC\n"
                 "👑 Monthly — ₹249 / 200⭐ / 200 GC")
        rows = [
            [btn("⚡ Daily ₹10",    f"tnc_{ch_id}_daily"),
             btn("📅 Weekly ₹60",   f"tnc_{ch_id}_weekly")],
            [btn("👑 Monthly ₹249", f"tnc_{ch_id}_monthly")],
            [btn("⬅️ All Channels", "channels")]
        ]
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))

# ── T&C → Agree → Pay ────────────────────────────────────────
async def show_tnc(u: Update, ctx):
    q = u.callback_query; await q.answer()
    _, ch_id, plan = q.data.split("_", 2)
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    text = TNC + f"\n\n*Plan:* {p['emoji']} {p['label']} | *Channel:* {ch.get('name','')}\n₹{p['inr']} / {p['stars']}⭐ / {p['gc']} GC"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=kb([btn("✅ I Agree — Pay Now", f"agree_{ch_id}_{plan}")],
                        [btn("❌ Cancel", f"ch_{ch_id}")]))

async def agree_tnc(u: Update, ctx):
    q = u.callback_query; await q.answer()
    _, ch_id, plan = q.data.split("_", 2)
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    await q.edit_message_text(
        f"💳 *Payment — {ch.get('name','')}*\n\nPlan: *{p['emoji']} {p['label']}*\n\nChoose payment method:",
        parse_mode="Markdown",
        reply_markup=kb(
            [btn(f"⭐ Stars ({p['stars']}⭐)", f"stars_{ch_id}_{plan}")],
            [btn(f"🎁 Gift Card (₹{p['gc']})",  f"gc_{ch_id}_{plan}")],
            [btn(f"💸 UPI (₹{p['inr']})",        f"upi_{ch_id}_{plan}")],
            [btn("⬅️ Back", f"ch_{ch_id}")]
        ))

# ── Stars ─────────────────────────────────────────────────────
async def stars_pay(u: Update, ctx):
    q = u.callback_query; await q.answer()
    _, ch_id, plan = q.data.split("_", 2)
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    ctx.user_data["stars_ch"] = ch_id; ctx.user_data["stars_plan"] = plan
    await ctx.bot.send_invoice(
        chat_id=q.from_user.id,
        title=f"Premium Gaze — {ch.get('name','')}",
        description=f"{p['label']} Plan Access • {ch.get('name','')}",
        payload=f"{ch_id}|{plan}|stars",
        currency="XTR",
        prices=[LabeledPrice(f"{p['label']} Access", p["stars"])],
        provider_token=""
    )
    await q.edit_message_text(f"⭐ Invoice bheja! *{p['stars']} Stars* pay karo — instant access milega 🚀",
                               parse_mode="Markdown")

async def stars_done(u: Update, ctx):
    pay = u.message.successful_payment; uid = u.effective_user.id
    ch_id, plan, _ = pay.invoice_payload.split("|")
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    exp = add_sub(uid, ch_id, plan, "stars", pay.total_amount, p["hours"])
    await u.message.reply_text(
        f"✅ *Stars Payment Done!*\n\n🎉 *{ch.get('name','')}* access mil gaya!\n"
        f"Plan: *{p['label']}* | Expires: `{exp.strftime('%d %b %Y %H:%M')}`\n\n"
        f"🔗 {ch.get('link','#')}",
        parse_mode="Markdown", disable_web_page_preview=True)
    await notify_admins(ctx.bot,
        f"💰 *Stars Payment*\nUser: {u.effective_user.full_name} (`{uid}`)\n"
        f"Channel: {ch.get('name','')} | Plan: {p['label']} | ⭐{pay.total_amount}")

# ── Gift Card ─────────────────────────────────────────────────
async def gc_howto(u: Update, ctx):
    q = u.callback_query; await q.answer()
    await q.edit_message_text(GC_PROCESS, parse_mode="Markdown",
        reply_markup=kb([btn("🏠 Main Menu", "main_menu")]))

async def gc_start(u: Update, ctx):
    q = u.callback_query; await q.answer()
    _, ch_id, plan = q.data.split("_", 2)
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    ctx.user_data["gc_ch"] = ch_id; ctx.user_data["gc_plan"] = plan
    await q.edit_message_text(
        f"🎁 *Amazon Gift Card*\n\nChannel: *{ch.get('name','')}*\nPlan: *{p['label']}*\n\n"
        f"{GC_PROCESS}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⬆️ Process follow karo aur code yahan bhejo!",
        parse_mode="Markdown",
        reply_markup=kb([btn("⬅️ Back", f"agree_{ch_id}_{plan}")]))

async def gc_verify(u: Update, ctx):
    uid = u.effective_user.id
    code = u.message.text.strip().upper().replace(" ", "")
    ch_id = ctx.user_data.get("gc_ch"); plan = ctx.user_data.get("gc_plan")
    if not ch_id or not plan:
        await u.message.reply_text("⚠️ Session expire. Dobara channel select karo.",
            reply_markup=kb([btn("🔥 Browse", "channels")])); return
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    amount = use_gc(code, uid)
    if amount is not None:
        if amount < p["gc"]:
            await u.message.reply_text(f"❌ GC amount kam hai!\nNeeded: ₹{p['gc']} | Code: ₹{amount}"); return
        exp = add_sub(uid, ch_id, plan, "giftcard", f"GC:{code}", p["hours"])
        await u.message.reply_text(
            f"✅ *Gift Card Verified!*\n\n🎉 *{ch.get('name','')}* access mil gaya!\n"
            f"Expires: `{exp.strftime('%d %b %Y %H:%M')}`\n\n🔗 {ch.get('link','#')}",
            parse_mode="Markdown", disable_web_page_preview=True)
        ctx.user_data.clear()
        await notify_admins(ctx.bot,
            f"🎁 *GC Auto Verified*\nUser: {u.effective_user.full_name} (`{uid}`)\n"
            f"Code: `{code}` | {ch.get('name','')} | {p['label']}")
    else:
        pid = add_gc_pending(uid, ch_id, plan, code, u.effective_user.full_name, u.effective_user.username or "N/A")
        await u.message.reply_text(
            f"📨 *Code receive hua!*\n\nAdmin manually verify karega.\n"
            f"*Max {SUPPORT_TIMEOUT_MIN} min* mein access milega. ⏰",
            parse_mode="Markdown")
        await notify_admins(ctx.bot,
            f"🎁 *GC Verify Request*\n\nUser: {u.effective_user.full_name} (`{uid}`)\n"
            f"@{u.effective_user.username or 'N/A'}\n\nCode: `{code}`\n"
            f"Channel: {ch.get('name','')} | Plan: {p['label']} (₹{p['gc']})\n"
            f"Pending ID: `{pid}`",
            keyboard=kb(
                [btn("✅ Approve", f"adm_gc_ok_{pid}_{uid}_{ch_id}_{plan}"),
                 btn("❌ Reject",  f"adm_gc_no_{pid}_{uid}")]
            ))

# ── UPI ───────────────────────────────────────────────────────
async def upi_start(u: Update, ctx):
    q = u.callback_query; await q.answer()
    _, ch_id, plan = q.data.split("_", 2)
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    ctx.user_data["upi_ch"] = ch_id
    ctx.user_data["upi_plan"] = plan
    ctx.user_data["upi_wait"] = True

    caption = upi_caption(ch.get("name",""), p["label"], p["emoji"], p["inr"])
    back_btn = kb([btn("⬅️ Back", f"agree_{ch_id}_{plan}")])
    qr_buf = make_upi_qr(p["inr"])
    if qr_buf:
        try:
            await q.message.reply_photo(photo=qr_buf, caption=caption,
                                        parse_mode="Markdown", reply_markup=back_btn)
            try: await q.delete_message()
            except: pass
            return
        except Exception as e:
            logger.error(f"QR send error: {e}")
    # fallback — text only
    await q.edit_message_text(caption, parse_mode="Markdown", reply_markup=back_btn)

async def upi_screenshot(u: Update, ctx):
    if not ctx.user_data.get("upi_wait"): return
    uid = u.effective_user.id
    ch_id = ctx.user_data.get("upi_ch"); plan = ctx.user_data.get("upi_plan")
    if not ch_id or not plan:
        await u.message.reply_text("⚠️ Session expire. Retry karo."); return
    p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
    file_id = u.message.photo[-1].file_id
    pid = add_upi_pending(uid, ch_id, plan, p["inr"], file_id,
                          u.effective_user.full_name, u.effective_user.username or "N/A")
    ctx.user_data["upi_wait"] = False
    await u.message.reply_text(
        f"📸 *Screenshot receive hua!*\n\nAdmin verify karega.\n*Max {SUPPORT_TIMEOUT_MIN} min* mein access milega. ⏰",
        parse_mode="Markdown")
    await notify_admins(ctx.bot,
        f"💸 *UPI Verify Request*\n\nUser: {u.effective_user.full_name} (`{uid}`)\n"
        f"@{u.effective_user.username or 'N/A'}\n"
        f"Channel: {ch.get('name','')} | Plan: {p['label']} (₹{p['inr']})\nID: `{pid}`",
        keyboard=kb(
            [btn("✅ Approve", f"adm_upi_ok_{pid}_{uid}_{ch_id}_{plan}"),
             btn("❌ Reject",  f"adm_upi_no_{pid}_{uid}")]
        ), photo=file_id)

# ── My Access ─────────────────────────────────────────────────
async def my_access(u: Update, ctx):
    q = u.callback_query; uid = q.from_user.id; await q.answer()
    subs = my_subs(uid)
    if not subs:
        await q.edit_message_text(
            "📋 *My Access*\n\n❌ Koi active subscription nahi hai.\nChannels browse karo aur subscribe karo!",
            parse_mode="Markdown",
            reply_markup=kb([btn("🔥 Browse Channels", "channels")], [btn("🏠 Home", "main_menu")])); return
    text = "📋 *My Active Access*\n\n"
    for s in subs:
        ch = CHANNELS.get(s["channel_id"], {})
        exp = datetime.fromisoformat(s["expires_at"])
        hrs = int((exp - datetime.now()).total_seconds() // 3600)
        text += f"✅ *{ch.get('name', s['channel_id'])}*\n   {s['plan'].capitalize()} • {hrs}h remaining\n   🔗 {ch.get('link','#')}\n\n"
    await q.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=kb([btn("🔥 More Channels", "channels")], [btn("🏠 Home", "main_menu")]))

# ── Support ───────────────────────────────────────────────────
async def support_menu(u: Update, ctx):
    q = u.callback_query; await q.answer()
    ctx.user_data["support"] = True; ctx.user_data["gc_ch"] = None; ctx.user_data["upi_wait"] = False
    await q.edit_message_text(
        f"🆘 *Support*\n\nApni problem yahan type karo.\n"
        f"Admin *{SUPPORT_TIMEOUT_MIN}-20 min* mein reply karega.\n\n"
        "_Payment issue, access problem ya koi sawaal — sab yahan._",
        parse_mode="Markdown",
        reply_markup=kb([btn("⬅️ Menu", "main_menu")]))

async def support_msg(u: Update, ctx):
    if not ctx.user_data.get("support"): return
    uid = u.effective_user.id; msg = u.message.text
    tid = add_ticket(uid, msg, u.effective_user.full_name, u.effective_user.username or "N/A")
    ctx.user_data["support"] = False
    await u.message.reply_text(
        f"✅ *Support request bheja gaya!*\n\nTicket ID: `{tid}`\n"
        f"*{SUPPORT_TIMEOUT_MIN}-20 min* mein admin reply karega.",
        parse_mode="Markdown",
        reply_markup=kb([btn("🏠 Home", "main_menu")]))
    await notify_admins(ctx.bot,
        f"🎫 *Support Ticket #{tid}*\n\nUser: {u.effective_user.full_name} (`{uid}`)\n"
        f"@{u.effective_user.username or 'N/A'}\n\n_{msg}_",
        keyboard=kb([btn(f"💬 Reply Ticket #{tid}", f"adm_reply_{tid}_{uid}")]))

# ════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ════════════════════════════════════════════════════════════

async def admin_cmd(u: Update, ctx):
    if u.effective_user.id not in ADMIN_IDS:
        await u.message.reply_text("❌ Unauthorized."); return
    await _admin_home(u.message, ctx, edit=False)

async def _admin_home(msg_or_q, ctx, edit=True):
    tu, tb, ts, td, bm, bp = db_stats()
    pu = len(get_pending_upi()); pg = len(get_pending_gc()); tk = len(get_tickets())
    text = (
        f"🛡️ *ADMIN PANEL — Premium Gaze*\n\n"
        f"👥 Users: `{tu}` | 🚫 Banned: `{tb}`\n"
        f"📦 Total Sales: `{ts}` | 📅 Today: `{td}`\n\n"
        f"By Plan: " + " · ".join(f"{r['plan']}:{r['cnt']}" for r in bp) + "\n"
        f"By Method: " + " · ".join(f"{r['method']}:{r['cnt']}" for r in bm) + "\n\n"
        f"⏳ UPI Pending: `{pu}` | GC Pending: `{pg}` | 🎫 Tickets: `{tk}`"
    )
    markup = kb(
        [btn("💸 UPI Pending",    "adm_upi_list"),   btn("🎁 GC Pending",   "adm_gc_plist")],
        [btn("🎫 Tickets",        "adm_tickets"),     btn("📊 Sales",        "adm_sales")],
        [btn("👥 User List",      "adm_users"),       btn("🔍 Find User",    "adm_finduser")],
        [btn("🎁 Gen GC Code",    "adm_gengc"),       btn("🗂️ GC Codes",    "adm_gclist")],
        [btn("📢 Broadcast",      "adm_broadcast"),   btn("💰 Change UPI",   "adm_changeupi")],
        [btn("🎁 Grant Access",   "adm_grant"),       btn("🗑️ Revoke Access","adm_revoke")]
    )
    if edit:
        await msg_or_q.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await msg_or_q.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def admin_cb(u: Update, ctx):
    q = u.callback_query; uid = q.from_user.id; await q.answer()
    if uid not in ADMIN_IDS:
        await q.answer("❌ Unauthorized!", show_alert=True); return
    d = q.data

    # ── UPI Approve ──────────────────────────────────────────
    if d.startswith("adm_upi_ok_"):
        pts = d.split("_"); pid=int(pts[3]); tuid=int(pts[4]); ch_id=pts[5]; plan=pts[6]
        p=PLANS[plan]; ch=CHANNELS.get(ch_id,{})
        exp = add_sub(tuid, ch_id, plan, "upi", p["inr"], p["hours"])
        close_pending("upi_pending", pid, "approved")
        try:
            await ctx.bot.send_message(tuid,
                f"✅ *UPI Approved!*\n\n🎉 *{ch.get('name','')}* access mil gaya!\n"
                f"Plan: *{p['label']}* | Expires: `{exp.strftime('%d %b %Y %H:%M')}`\n\n"
                f"🔗 {ch.get('link','#')}",
                parse_mode="Markdown", disable_web_page_preview=True)
        except: pass
        try: await q.edit_message_caption(caption=(q.message.caption or "")+"  ✅ APPROVED", parse_mode="Markdown")
        except:
            try: await q.edit_message_text((q.message.text or "")+"  ✅ APPROVED", parse_mode="Markdown")
            except: pass

    elif d.startswith("adm_upi_no_"):
        pts = d.split("_"); pid=int(pts[3]); tuid=int(pts[4])
        close_pending("upi_pending", pid, "rejected")
        try: await ctx.bot.send_message(tuid, "❌ UPI payment reject hua. Sahi screenshot bhejo ya support contact karo.")
        except: pass
        try: await q.edit_message_caption(caption=(q.message.caption or "")+"  ❌ REJECTED", parse_mode="Markdown")
        except:
            try: await q.edit_message_text((q.message.text or "")+"  ❌ REJECTED", parse_mode="Markdown")
            except: pass

    # ── GC Approve ───────────────────────────────────────────
    elif d.startswith("adm_gc_ok_"):
        pts = d.split("_"); pid=int(pts[3]); tuid=int(pts[4]); ch_id=pts[5]; plan=pts[6]
        p=PLANS[plan]; ch=CHANNELS.get(ch_id,{})
        exp = add_sub(tuid, ch_id, plan, "giftcard", "GC-manual", p["hours"])
        close_pending("gc_pending", pid, "approved")
        try:
            await ctx.bot.send_message(tuid,
                f"✅ *Gift Card Approved!*\n\n🎉 *{ch.get('name','')}* access!\n"
                f"Plan: *{p['label']}* | Expires: `{exp.strftime('%d %b %Y %H:%M')}`\n\n"
                f"🔗 {ch.get('link','#')}",
                parse_mode="Markdown", disable_web_page_preview=True)
        except: pass
        await q.edit_message_text((q.message.text or "")+"  ✅ APPROVED", parse_mode="Markdown")

    elif d.startswith("adm_gc_no_"):
        pts = d.split("_"); pid=int(pts[3]); tuid=int(pts[4])
        close_pending("gc_pending", pid, "rejected")
        try: await ctx.bot.send_message(tuid, "❌ Gift Card reject hua. Sahi code bhejo ya support contact karo.")
        except: pass
        await q.edit_message_text((q.message.text or "")+"  ❌ REJECTED", parse_mode="Markdown")

    # ── Pending Lists ─────────────────────────────────────────
    elif d == "adm_upi_list":
        rows = get_pending_upi()
        text = f"💸 *Pending UPI ({len(rows)})*\n\n" if rows else "💸 *No pending UPI* ✅\n\n"
        for r in rows:
            text += f"🔹 ID:`{r['id']}` | User:`{r['user_id']}` @{r['username']}\n   {ch_name(r['channel_id'])} | {r['plan']} | ₹{r['amount']}\n"
            text += f"   Approve: `/aprupi_{r['id']}_{r['user_id']}_{r['channel_id']}_{r['plan']}`\n\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    elif d == "adm_gc_plist":
        rows = get_pending_gc()
        text = f"🎁 *Pending GC ({len(rows)})*\n\n" if rows else "🎁 *No pending GC* ✅\n\n"
        for r in rows:
            text += f"🔹 ID:`{r['id']}` | User:`{r['user_id']}` @{r['username']}\n   Code:`{r['code']}` | {ch_name(r['channel_id'])} | {r['plan']}\n\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Tickets ───────────────────────────────────────────────
    elif d == "adm_tickets":
        rows = get_tickets()
        text = f"🎫 *Open Tickets ({len(rows)})*\n\n" if rows else "🎫 *No open tickets* ✅\n\n"
        btns = []
        for r in rows:
            text += f"#{r['id']} | {r['full_name']} @{r['username']} (`{r['user_id']}`)\n_{r['message'][:80]}_\n\n"
            btns.append([btn(f"💬 Reply #{r['id']}", f"adm_reply_{r['id']}_{r['user_id']}")])
        btns.append([btn("⬅️ Admin", "adm_home")])
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

    elif d.startswith("adm_reply_"):
        pts = d.split("_"); tid=pts[2]; tuid=pts[3]
        ctx.user_data["adm_reply_ticket"] = tid
        ctx.user_data["adm_reply_user"] = int(tuid)
        await q.edit_message_text(
            f"💬 *Ticket #{tid} Reply*\n\nUser `{tuid}` ko reply type karo aur bhejo:",
            parse_mode="Markdown",
            reply_markup=kb([btn("⬅️ Tickets", "adm_tickets")]))

    # ── Sales ─────────────────────────────────────────────────
    elif d == "adm_sales":
        with conn() as c:
            rows = c.execute("SELECT s.*,u.full_name,u.username FROM subs s JOIN users u ON s.user_id=u.user_id ORDER BY s.created_at DESC LIMIT 20").fetchall()
        text = "📊 *Recent Sales (20)*\n\n"
        for r in rows:
            text += f"• {r['full_name']} | {ch_name(r['channel_id'])} | {r['plan']} | {r['method']}\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── User List ─────────────────────────────────────────────
    elif d == "adm_users":
        users = get_all_users()
        text = f"👥 *All Users ({len(users)})*\n\n"
        for uu in users[:20]:
            banned = "🚫" if uu["is_banned"] else "✅"
            text += f"{banned} `{uu['user_id']}` | {uu['full_name']} @{uu['username'] or 'N/A'}\n"
        if len(users) > 20: text += f"\n_...aur {len(users)-20} users_"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Find / Ban / Unban ────────────────────────────────────
    elif d == "adm_finduser":
        ctx.user_data["adm_action"] = "finduser"
        await q.edit_message_text("🔍 *Find User*\n\nUser ka Telegram ID type karo:",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── GC Codes ──────────────────────────────────────────────
    elif d == "adm_gengc":
        await q.edit_message_text("🎁 *Generate GC Code*\n\nAmount choose karo:", parse_mode="Markdown",
            reply_markup=kb(
                [btn("₹10",  "adm_mkgc_10"),  btn("₹50",  "adm_mkgc_50")],
                [btn("₹60",  "adm_mkgc_60"),  btn("₹249", "adm_mkgc_249")],
                [btn("⬅️ Admin", "adm_home")]))

    elif d.startswith("adm_mkgc_"):
        amount = int(d.split("_")[2])
        code = gen_gc(amount)
        await q.edit_message_text(
            f"🎁 *Code Generated!*\n\nCode: `{code}`\nAmount: ₹{amount}\n\nUser ko do.",
            parse_mode="Markdown",
            reply_markup=kb([btn("🎁 Aur Generate", "adm_gengc"), btn("⬅️ Admin", "adm_home")]))

    elif d == "adm_gclist":
        codes = list_gc()
        text = "🗂️ *GC Codes (Last 30)*\n\n"
        for c2 in codes:
            st = "✅ Used" if c2["is_used"] else "🟢 Active"
            text += f"`{c2['code']}` | ₹{c2['amount']} | {st}\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Broadcast ─────────────────────────────────────────────
    elif d == "adm_broadcast":
        ctx.user_data["adm_action"] = "broadcast"
        await q.edit_message_text(
            "📢 *Broadcast*\n\nWoh message type karo jo *sabhi users* ko bhejana hai:",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Change UPI ────────────────────────────────────────────
    elif d == "adm_changeupi":
        ctx.user_data["adm_action"] = "changeupi"
        await q.edit_message_text(
            f"💰 *Change UPI ID*\n\nCurrent: `{UPI_ID}`\n\nNaya UPI ID type karo:",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Grant Access ──────────────────────────────────────────
    elif d == "adm_grant":
        ctx.user_data["adm_action"] = "grant"
        await q.edit_message_text(
            "🎁 *Grant Access*\n\nFormat: `USER_ID CH_ID PLAN`\n"
            "Example: `123456789 ch1 monthly`\n\nType karo:",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    # ── Revoke Access ─────────────────────────────────────────
    elif d == "adm_revoke":
        ctx.user_data["adm_action"] = "revoke"
        await q.edit_message_text(
            "🗑️ *Revoke Access*\n\nFormat: `USER_ID CH_ID`\nExample: `123456789 ch1`\n\nType karo:",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    elif d == "adm_home":
        await _admin_home(q, ctx, edit=True)

# ── Admin text input handler ──────────────────────────────────
async def admin_text_input(u: Update, ctx):
    uid = u.effective_user.id
    if uid not in ADMIN_IDS: return

    action = ctx.user_data.get("adm_action")
    reply_ticket = ctx.user_data.get("adm_reply_ticket")
    reply_user   = ctx.user_data.get("adm_reply_user")
    text = u.message.text.strip()

    # ── Ticket Reply ──
    if reply_ticket and reply_user:
        try:
            await ctx.bot.send_message(reply_user,
                f"💬 *Admin Reply (Ticket #{reply_ticket}):*\n\n{text}",
                parse_mode="Markdown")
            resolve_ticket(reply_ticket, text)
        except Exception as e:
            await u.message.reply_text(f"❌ Send failed: {e}"); return
        ctx.user_data.pop("adm_reply_ticket", None)
        ctx.user_data.pop("adm_reply_user", None)
        await u.message.reply_text(f"✅ Ticket #{reply_ticket} replied aur resolved!",
            reply_markup=kb([btn("⬅️ Admin", "adm_home")]))
        return

    if not action: return

    if action == "broadcast":
        users = get_all_users(); sent = 0
        await u.message.reply_text(f"📢 Broadcast shuru... {len(users)} users ko bhej raha hoon.")
        for uu in users:
            try:
                await ctx.bot.send_message(uu["user_id"], f"📢 *Premium Gaze Update*\n\n{text}", parse_mode="Markdown")
                sent += 1
            except: pass
        ctx.user_data.pop("adm_action", None)
        await u.message.reply_text(f"✅ Broadcast done! {sent}/{len(users)} users ko mila.",
            reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    elif action == "changeupi":
        global UPI_ID
        UPI_ID = text.strip()
        ctx.user_data.pop("adm_action", None)
        await u.message.reply_text(f"✅ UPI ID update ho gaya!\nNaya: `{UPI_ID}`",
            parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

    elif action == "finduser":
        try:
            target = int(text)
            with conn() as c:
                uu = c.execute("SELECT * FROM users WHERE user_id=?", (target,)).fetchone()
            if not uu:
                await u.message.reply_text("❌ User nahi mila."); return
            user_subs = my_subs(target)
            info = (f"👤 *User Info*\n\n"
                    f"ID: `{uu['user_id']}`\nName: {uu['full_name']}\n@{uu['username'] or 'N/A'}\n"
                    f"Banned: {'🚫 Yes' if uu['is_banned'] else '✅ No'}\n"
                    f"Joined: {uu['joined_at']}\n\nActive Subs: {len(user_subs)}")
            ctx.user_data.pop("adm_action", None)
            await u.message.reply_text(info, parse_mode="Markdown",
                reply_markup=kb(
                    [btn("🚫 Ban",   f"adm_ban_{target}"),
                     btn("✅ Unban", f"adm_unban_{target}")],
                    [btn("⬅️ Admin", "adm_home")]
                ))
        except ValueError:
            await u.message.reply_text("❌ Valid Telegram ID do (number).")

    elif action == "grant":
        try:
            parts = text.split()
            tuid = int(parts[0]); ch_id = parts[1]; plan = parts[2]
            p = PLANS[plan]; ch = CHANNELS.get(ch_id, {})
            exp = add_sub(tuid, ch_id, plan, "admin_grant", 0, p["hours"])
            try:
                await ctx.bot.send_message(tuid,
                    f"🎁 *Access Granted!*\n\n*{ch.get('name','')}*\nPlan: *{p['label']}*\n"
                    f"Expires: `{exp.strftime('%d %b %Y %H:%M')}`\n\n🔗 {ch.get('link','')}",
                    parse_mode="Markdown", disable_web_page_preview=True)
            except: pass
            ctx.user_data.pop("adm_action", None)
            await u.message.reply_text(f"✅ Access granted!\nUser: `{tuid}` | {ch.get('name','')} | {plan}",
                parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))
        except Exception as e:
            await u.message.reply_text(f"❌ Error: {e}\nFormat: `USER_ID ch1 daily`", parse_mode="Markdown")

    elif action == "revoke":
        try:
            parts = text.split(); tuid = int(parts[0]); ch_id = parts[1]
            revoke_sub(tuid, ch_id)
            ctx.user_data.pop("adm_action", None)
            await u.message.reply_text(f"✅ Access revoked!\nUser: `{tuid}` | {ch_name(ch_id)}",
                parse_mode="Markdown", reply_markup=kb([btn("⬅️ Admin", "adm_home")]))
        except Exception as e:
            await u.message.reply_text(f"❌ Error: {e}\nFormat: `USER_ID ch1`", parse_mode="Markdown")

async def ban_unban_cb(u: Update, ctx):
    q = u.callback_query; await q.answer()
    if q.from_user.id not in ADMIN_IDS: return
    d = q.data
    if d.startswith("adm_ban_"):
        target = int(d.split("_")[2]); ban_user(target)
        try: await ctx.bot.send_message(target, "🚫 Aapka account ban ho gaya hai.")
        except: pass
        await q.edit_message_text(f"🚫 User `{target}` banned!", parse_mode="Markdown",
            reply_markup=kb([btn("⬅️ Admin", "adm_home")]))
    elif d.startswith("adm_unban_"):
        target = int(d.split("_")[2]); unban_user(target)
        try: await ctx.bot.send_message(target, "✅ Aapka account unban ho gaya hai!")
        except: pass
        await q.edit_message_text(f"✅ User `{target}` unbanned!", parse_mode="Markdown",
            reply_markup=kb([btn("⬅️ Admin", "adm_home")]))

# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("admin",  admin_cmd))

    app.add_handler(CallbackQueryHandler(main_menu,      pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_channels,  pattern="^channels$"))
    app.add_handler(CallbackQueryHandler(channel_detail, pattern="^ch_"))
    app.add_handler(CallbackQueryHandler(show_tnc,       pattern="^tnc_"))
    app.add_handler(CallbackQueryHandler(agree_tnc,      pattern="^agree_"))
    app.add_handler(CallbackQueryHandler(stars_pay,      pattern="^stars_"))
    app.add_handler(CallbackQueryHandler(gc_howto,       pattern="^gc_howto$"))
    app.add_handler(CallbackQueryHandler(gc_start,       pattern="^gc_ch"))
    app.add_handler(CallbackQueryHandler(upi_start,      pattern="^upi_ch"))
    app.add_handler(CallbackQueryHandler(my_access,      pattern="^myaccess$"))
    app.add_handler(CallbackQueryHandler(support_menu,   pattern="^support$"))
    app.add_handler(CallbackQueryHandler(ban_unban_cb,   pattern="^adm_ban_|^adm_unban_"))
    app.add_handler(CallbackQueryHandler(admin_cb,       pattern="^adm_"))

    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, stars_done))
    app.add_handler(MessageHandler(filters.PHOTO, upi_screenshot))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^(GC-|[A-Z0-9]{4}-[A-Z0-9]{6}-[A-Z0-9]{4})'),
        gc_verify))

    # Admin text inputs (higher priority for admins)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text))

    logger.info("Premium Gaze Bot started! 🔥")
    app.run_polling(drop_pending_updates=True)

async def _route_text(u: Update, ctx):
    """Route text to admin handler or support"""
    if u.effective_user.id in ADMIN_IDS and (
        ctx.user_data.get("adm_action") or
        ctx.user_data.get("adm_reply_ticket")
    ):
        await admin_text_input(u, ctx)
    elif ctx.user_data.get("support"):
        await support_msg(u, ctx)

if __name__ == "__main__":
    main()
