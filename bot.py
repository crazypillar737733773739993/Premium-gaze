import io
import random
import string
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

from config import BOT_TOKEN, ADMIN_IDS, UPI_ID, PRODUCTS
import database as db
from qr_utils import generate_upi_qr
from collections import defaultdict
import time

db.init_db()

# ── RATE LIMITER ──────────────────────────────────────────────────────────────
user_last_action = defaultdict(float)
user_action_count = defaultdict(int)
user_action_window = defaultdict(float)

COOLDOWN_SECONDS = 1.5      # min gap between any two actions
SPAM_LIMIT = 10             # max actions per window
SPAM_WINDOW = 30            # window in seconds
SPAM_BAN_DURATION = 300     # 5 min temp ban

temp_banned = {}  # uid -> unban_timestamp

def check_rate_limit(uid):
    """Returns (allowed, reason). Admins are never rate limited."""
    if uid in ADMIN_IDS:
        return True, None

    now = time.time()

    # Check temp ban
    if uid in temp_banned:
        if now < temp_banned[uid]:
            remaining = int(temp_banned[uid] - now)
            return False, f"⏳ You are temporarily restricted for {remaining}s due to spam."
        else:
            del temp_banned[uid]
            user_action_count[uid] = 0

    # Cooldown check
    last = user_last_action[uid]
    if now - last < COOLDOWN_SECONDS:
        return False, "⚡ Slow down! Please wait a moment."

    # Spam window check
    if now - user_action_window[uid] > SPAM_WINDOW:
        user_action_window[uid] = now
        user_action_count[uid] = 0

    user_action_count[uid] += 1
    user_last_action[uid] = now

    if user_action_count[uid] > SPAM_LIMIT:
        temp_banned[uid] = now + SPAM_BAN_DURATION
        user_action_count[uid] = 0
        return False, f"🚫 Too many requests! You are restricted for {SPAM_BAN_DURATION//60} minutes."

    return True, None

def gen_order_id():
    return "ORD-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def is_admin(uid):
    return uid in ADMIN_IDS

# ── MAIN MENU KEYBOARD ────────────────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🛒 Buy Products"), KeyboardButton("📦 My Orders")],
            [KeyboardButton("💬 Support"), KeyboardButton("ℹ️ About")]
        ],
        resize_keyboard=True
    )

# ── ADMIN INLINE KEYBOARD ─────────────────────────────────────────────────────
def admin_menu_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Stock Manager", callback_data="adm_stock"),
         InlineKeyboardButton("💰 Pending Orders", callback_data="adm_pending")],
        [InlineKeyboardButton("👥 User List", callback_data="adm_users"),
         InlineKeyboardButton("📊 Stats", callback_data="adm_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("💬 Reply User", callback_data="adm_reply")],
        [InlineKeyboardButton("💲 Set Price", callback_data="adm_price")]
    ])

# ─────────────────────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    db.upsert_user(uid, user.username, user.first_name)

    if db.is_banned(uid):
        await update.message.reply_text("🚫 You are banned from this bot.")
        return

    await update.message.reply_text(
        f"╔═══════════════════════╗\n"
        f"║   🏪 *LOOTER PROS SHOP*   ║\n"
        f"╚═══════════════════════╝\n\n"
        f"👋 Welcome, *{user.first_name}*!\n\n"
        f"🛍️ Premium JSON files & Swiggy offers\n"
        f"⚡ Instant delivery after approval\n"
        f"🔒 100% Safe & Trusted\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Use the menu below to get started 👇",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

# ─────────────────────────────────────────────────────────────────────────────
# TEXT HANDLER
# ─────────────────────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if db.is_banned(uid):
        await update.message.reply_text("🚫 You are banned.")
        return

    allowed, reason = check_rate_limit(uid)
    if not allowed:
        await update.message.reply_text(reason)
        return

    state = context.user_data.get("state")

    # ── Admin states ──
    if state == "await_new_product" and is_admin(uid):
        await handle_new_product_step(update, context)
        return
    if state == "await_stock_content" and is_admin(uid):
        await handle_stock_batch(update, context)
        return
    if state == "await_broadcast" and is_admin(uid):
        await handle_broadcast_send(update, context)
        return
    if state == "await_reply_uid" and is_admin(uid):
        try:
            context.user_data["reply_target"] = int(text)
            context.user_data["state"] = "await_reply_msg"
            await update.message.reply_text("✏️ Now send the message:")
        except:
            await update.message.reply_text("❌ Send a valid numeric user ID.")
        return
    if state == "await_reply_msg" and is_admin(uid):
        target = context.user_data.get("reply_target")
        try:
            await context.bot.send_message(
                target,
                f"📩 *Message from Admin:*\n\n{text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ Message sent!")
        except:
            await update.message.reply_text("❌ Failed — user may have blocked the bot.")
        context.user_data.clear()
        return
    if state == "await_price_val" and is_admin(uid):
        await handle_price_set(update, context)
        return
    if state == "await_ban_uid" and is_admin(uid):
        try:
            target = int(text)
            db.ban_user(target)
            context.user_data['state'] = None
            await update.message.reply_text(f"🚫 User `{target}` banned.", parse_mode="Markdown")
            try:
                await context.bot.send_message(target, "🚫 You have been banned from this bot.")
            except:
                pass
        except:
            await update.message.reply_text("❌ Invalid user ID.")
        return
    if state == "await_unban_uid" and is_admin(uid):
        try:
            target = int(text)
            db.unban_user(target)
            context.user_data['state'] = None
            await update.message.reply_text(f"✅ User `{target}` unbanned.", parse_mode="Markdown")
            try:
                await context.bot.send_message(target, "✅ You have been unbanned! Welcome back.")
            except:
                pass
        except:
            await update.message.reply_text("❌ Invalid user ID.")
        return

    # ── User states ──
    if state == "await_qty":
        await handle_qty_input(update, context)
        return
    if state == "await_screenshot":
        await update.message.reply_text("📸 Please send an IMAGE screenshot, not text.")
        return

    # ── Menu buttons ──
    if text == "🛒 Buy Products":
        await show_products(update, context)
    elif text == "📦 My Orders":
        await show_my_orders(update, context)
    elif text == "💬 Support":
        await update.message.reply_text(
            "💬 *Support*\n\n"
            "For any issues contact us.\n\n"
            "⚠️ *Note:* Screen recording is mandatory for any claim or refund.",
            parse_mode="Markdown"
        )
    elif text == "ℹ️ About":
        await update.message.reply_text(
            "╔═══════════════════════╗\n"
            "║   🏪 *LOOTER PROS SHOP*   ║\n"
            "╚═══════════════════════╝\n\n"
            "✅ Trusted seller\n"
            "⚡ Instant delivery after approval\n"
            "🔒 Safe & secure payments\n"
            "📦 Premium JSON files & Swiggy offers\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 Payment via UPI only\n"
            "📸 Screenshot required for verification",
            parse_mode="Markdown"
        )
    elif text in ["/admin", "🔧 Admin"]:
        if is_admin(uid):
            await update.message.reply_text(
                "🔧 *Admin Panel*",
                parse_mode="Markdown",
                reply_markup=admin_menu_inline()
            )

# ─────────────────────────────────────────────────────────────────────────────
# SHOW PRODUCTS
# ─────────────────────────────────────────────────────────────────────────────
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = db.get_all_stock_counts()
    buttons = []
    for key, prod in PRODUCTS.items():
        cnt = stocks.get(key, 0)
        if cnt > 10:
            stock_label = f"✅ {cnt}"
        elif cnt > 0:
            stock_label = f"🟡 Low: {cnt}"
        else:
            stock_label = "❌ Out"
        buttons.append([InlineKeyboardButton(
            f"{prod['emoji']} {prod['name']} — ₹{prod['price']} ({stock_label})",
            callback_data=f"buy_{key}"
        )])

    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        "🛒 *Available Products*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a product below 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT DETAIL
# ─────────────────────────────────────────────────────────────────────────────
async def show_product_detail(q, context, key):
    prod = PRODUCTS.get(key)
    if not prod:
        await q.edit_message_text("❌ Product not found.")
        return

    stock = db.get_stock_count(key)
    if stock > 10:
        stock_str = f"✅ {stock} in stock"
    elif stock > 0:
        stock_str = f"🟡 Low stock ({stock} left)"
    else:
        stock_str = "❌ Out of stock"

    text = (
        f"{prod['emoji']} *{prod['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📄 {prod['description']}\n\n"
        f"📦 Stock: {stock_str}\n"
        f"💰 Price: ₹{prod['price']} per unit\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Select quantity 👇"
    )

    buttons = [
        [InlineKeyboardButton("🛒 1", callback_data=f"qty_{key}_1"),
         InlineKeyboardButton("🛒 2", callback_data=f"qty_{key}_2"),
         InlineKeyboardButton("🛒 5", callback_data=f"qty_{key}_5")],
        [InlineKeyboardButton("✏️ Other Amount", callback_data=f"qty_{key}_custom")],
        [InlineKeyboardButton("🔙 Back to Products", callback_data="back_products")]
    ]

    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(buttons))

# ─────────────────────────────────────────────────────────────────────────────
# TERMS & CONDITIONS
# ─────────────────────────────────────────────────────────────────────────────
async def show_terms(q, context, key, qty):
    prod = PRODUCTS[key]
    total = prod['price'] * qty
    context.user_data['buy_key'] = key
    context.user_data['buy_qty'] = qty

    text = (
        "📋 *Terms & Conditions*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚨 *Important Note:*\n"
        "_• File/offer must be used immediately after delivery\n"
        "• Report any issue within 24 hours\n"
        "• No replacement after 24 hours\n"
        "• Screen recording mandatory for claims_\n\n"
        "✅ One purchase = One use only\n"
        "⚠️ No refund after delivery\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛍️ *{prod['name']}*\n"
        f"🔢 Qty: {qty}  |  💰 Total: ₹{total:.2f}\n\n"
        "Tap *I Agree* to proceed 👇"
    )

    buttons = [
        [InlineKeyboardButton("✅ I Agree — Proceed to Payment", callback_data=f"agree_{key}_{qty}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_products")]
    ]

    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(buttons))

# ─────────────────────────────────────────────────────────────────────────────
# QR + ORDER
# ─────────────────────────────────────────────────────────────────────────────
async def handle_confirm_order(q, context):
    uid = q.from_user.id
    key = context.user_data.get("buy_key")
    qty = context.user_data.get("buy_qty", 1)
    prod = PRODUCTS.get(key)

    if not prod:
        await q.edit_message_text("❌ Product not found.")
        return

    stock = db.get_stock_count(key)
    if stock < qty:
        await q.edit_message_text(
            f"😔 *Not enough stock!*\n\n"
            f"Available: {stock} | Requested: {qty}\n\n"
            f"Please select a lower quantity.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="back_products")]
            ])
        )
        return

    total = prod['price'] * qty
    order_ref = gen_order_id()
    order_id = db.create_order(uid, key, qty, total, order_ref)
    context.user_data['pending_order_id'] = order_id
    context.user_data['pending_amount'] = total
    context.user_data['pending_ref'] = order_ref

    try:
        qr_bytes = generate_upi_qr(UPI_ID, total, "LooterPros", order_ref)
        await q.edit_message_text(
            f"💳 *Payment Required*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🧾 Order ID: `{order_ref}`\n"
            f"🛍️ *{prod['name']}* × {qty}\n"
            f"💰 Amount: ₹{total:.2f}\n\n"
            f"📱 Scan QR below & pay via:\n"
            f"_GPay / PhonePe / Paytm / Any UPI_\n\n"
            f"After payment tap ✅ *I've Paid*",
            parse_mode="Markdown"
        )
        await context.bot.send_photo(
            chat_id=q.message.chat_id,
            photo=InputFile(io.BytesIO(qr_bytes), filename="qr.png"),
            caption=f"💰 Pay ₹{total:.2f} | Ref: {order_ref}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I've Paid", callback_data=f"paid_{order_id}")],
                [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order_id}")]
            ])
        )
    except Exception as e:
        await q.edit_message_text(
            f"💳 *Payment Required*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🧾 Order ID: `{order_ref}`\n"
            f"🛍️ *{prod['name']}* × {qty}\n"
            f"💰 Amount: ₹{total:.2f}\n\n"
            f"📲 Pay to UPI:\n`{UPI_ID}`\n\n"
            f"After payment tap ✅ *I've Paid*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I've Paid", callback_data=f"paid_{order_id}")],
                [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order_id}")]
            ])
        )

    # Notify admin
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🛒 *New Order Created!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🧾 Order: `{order_ref}`\n"
                f"👤 User: {q.from_user.first_name} (@{q.from_user.username or 'N/A'}) | `{uid}`\n"
                f"🛍️ {prod['name']} × {qty}\n"
                f"💰 ₹{total:.2f}\n\n"
                f"⏳ Waiting for payment screenshot...",
                parse_mode="Markdown"
            )
        except:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# PAID — screenshot
# ─────────────────────────────────────────────────────────────────────────────
async def handle_paid_button(q, context):
    order_id = int(q.data.split("_")[1])
    context.user_data["state"] = "await_screenshot"
    context.user_data["screenshot_order_id"] = order_id
    await q.edit_message_caption(
        caption="📸 *Send Payment Screenshot*\n\nSend the screenshot as an image.",
        parse_mode="Markdown"
    )

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = context.user_data.get("state")
    if state != "await_screenshot":
        return

    photo = update.message.photo
    if not photo:
        await update.message.reply_text("❌ Please send an image screenshot.")
        return

    file_id = photo[-1].file_id
    order_id = context.user_data.get("screenshot_order_id")
    order = db.get_order(order_id)
    if not order:
        await update.message.reply_text("❌ Order not found.")
        return

    payment_id = db.create_payment(order_id, uid, order['amount'], file_id)
    context.user_data['state'] = None

    await update.message.reply_text(
        "✅ *Screenshot received!*\n\n"
        "⏳ Admin will verify & deliver shortly.\n"
        "_Usually within 5-15 minutes._",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    prod = PRODUCTS.get(order['product_key'], {})
    user = update.effective_user

    # Forward screenshot to admin with reply capability
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id,
                photo=file_id,
                caption=(
                    f"💸 *Payment Screenshot Received*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🧾 Order: `{order['order_ref']}`\n"
                    f"🆔 Order ID: #{order_id} | Payment: #{payment_id}\n"
                    f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🔢 User ID: `{uid}`\n"
                    f"🛍️ {prod.get('name','?')} × {order['qty']}\n"
                    f"💰 Amount: ₹{order['amount']:.2f}\n\n"
                    f"📲 *Reply to this message* to message the user directly.\n\n"
                    f"Approve or Reject below 👇"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve & Deliver", callback_data=f"approve_{payment_id}_{order_id}_{uid}")],
                    [InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_{payment_id}_{order_id}_{uid}")]
                ])
            )
            # Store mapping: admin message → user id for reply
            db.store_admin_msg_map(admin_id, payment_id, uid)
        except:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN REPLY TO USER via forwarded message reply
# ─────────────────────────────────────────────────────────────────────────────
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return

    state = context.user_data.get("state")

    # Check if admin is replying to a forwarded payment screenshot
    if update.message.reply_to_message:
        # Try to extract user_id from caption
        caption = update.message.reply_to_message.caption or ""
        import re
        match = re.search(r'User ID: `(\d+)`', caption)
        if match:
            target_uid = int(match.group(1))
            try:
                await context.bot.send_message(
                    target_uid,
                    f"📩 *Message from Admin:*\n\n{update.message.text}",
                    parse_mode="Markdown"
                )
                await update.message.reply_text("✅ Message delivered to user!")
            except:
                await update.message.reply_text("❌ Could not deliver — user may have blocked bot.")
            return

    # Normal text handling
    await handle_text(update, context)

# ─────────────────────────────────────────────────────────────────────────────
# APPROVE / REJECT
# ─────────────────────────────────────────────────────────────────────────────
async def handle_approve(q, context, parts):
    payment_id = int(parts[1])
    order_id = int(parts[2])
    user_id = int(parts[3])

    order = db.get_order(order_id)
    prod = PRODUCTS.get(order['product_key'], {})

    items = db.pop_stock(order['product_key'], order['qty'])
    if not items:
        await q.edit_message_caption(
            caption="❌ *Out of stock!* Cannot deliver.\nAdd stock first.",
            parse_mode="Markdown"
        )
        return

    db.save_order_items(order_id, items)
    db.complete_order(order_id)
    db.approve_payment(payment_id)
    db.update_user_stats(user_id, order['amount'])

    delivery_text = (
        f"🎉 *Order Approved & Delivered!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🧾 Order: `{order['order_ref']}`\n"
        f"🛍️ *{prod.get('name','?')}* × {order['qty']}\n\n"
        f"📦 *Your Item(s):*\n"
        + "\n".join([f"`{item}`" for item in items]) +
        f"\n\n⚠️ Use immediately!\n"
        f"Screen recording required for any claims.\n\n"
        f"Thank you for shopping at Looter Pros! 🙏"
    )

    try:
        await context.bot.send_message(user_id, delivery_text, parse_mode="Markdown")
    except:
        pass

    await q.edit_message_caption(
        caption=f"✅ *Approved & Delivered!*\n\nUser: `{user_id}`\nOrder: `{order['order_ref']}`",
        parse_mode="Markdown"
    )

async def handle_reject(q, context, parts):
    payment_id = int(parts[1])
    order_id = int(parts[2])
    user_id = int(parts[3])

    order = db.get_order(order_id)
    db.reject_payment(payment_id)

    try:
        await context.bot.send_message(
            user_id,
            f"❌ *Payment Rejected*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Order `{order['order_ref']}` was rejected.\n"
            f"Reason: Payment not verified.\n\n"
            f"Contact support if you believe this is an error.",
            parse_mode="Markdown"
        )
    except:
        pass

    await q.edit_message_caption(
        caption=f"❌ *Rejected*\nOrder #{order_id} | User `{user_id}`",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────────────────────────────────────
# MY ORDERS
# ─────────────────────────────────────────────────────────────────────────────
async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    orders = db.get_user_orders(uid)
    msg = update.message if update.message else update.callback_query.message

    if not orders:
        await msg.reply_text(
            "📦 *My Orders*\n\n"
            "You have no orders yet.\n"
            "Tap 🛒 Buy Products to get started!",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    text = "📦 *Your Recent Orders:*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for o in orders[:8]:
        prod = PRODUCTS.get(o['product_key'], {})
        if o['status'] == 'completed':
            status = "✅ Delivered"
        elif o['status'] == 'pending':
            status = "⏳ Pending"
        else:
            status = "❌ Cancelled"
        text += (
            f"🧾 `{o['order_ref']}`\n"
            f"   {prod.get('name','?')} × {o['qty']}\n"
            f"   💰 ₹{o['amount']:.2f} | {status}\n"
            f"   📅 {o['created_at'][:16]}\n\n"
        )

    await msg.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: STOCK (batch mode)
# ─────────────────────────────────────────────────────────────────────────────
async def adm_stock_menu(q, context):
    buttons = []
    stocks = db.get_all_stock_counts()
    for key, prod in PRODUCTS.items():
        cnt = stocks.get(key, 0)
        buttons.append([InlineKeyboardButton(
            f"{prod['emoji']} {prod['name']} — {cnt} in stock",
            callback_data=f"adm_addstock_{key}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_panel")])
    await q.edit_message_text(
        "📦 *Stock Manager*\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSelect product to add stock:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def adm_add_stock_prompt(q, context, key):
    context.user_data['state'] = 'await_stock_content'
    context.user_data['stock_key'] = key
    context.user_data['stock_batch'] = []
    prod = PRODUCTS[key]
    await q.edit_message_text(
        f"📥 *Add Stock: {prod['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Send items one by one or multiple per message.\n"
        f"Each line = one item.\n\n"
        f"📄 You can also upload a *.txt* or *.json* file\n\n"
        f"When done, send */done*\n\n"
        f"_Current batch: 0 items_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_stock")]])
    )

async def handle_stock_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "/done":
        batch = context.user_data.get('stock_batch', [])
        if not batch:
            await update.message.reply_text("❌ No items added yet. Send some items first.")
            return
        key = context.user_data.get('stock_key')
        count = db.add_stock(key, batch)
        prod = PRODUCTS.get(key, {})
        total_stock = db.get_stock_count(key)
        context.user_data['state'] = None
        context.user_data['stock_batch'] = []
        await update.message.reply_text(
            f"✅ *Stock Added Successfully!*\n\n"
            f"📦 Product: *{prod.get('name','?')}*\n"
            f"➕ Added: {count} items\n"
            f"📊 Total stock now: {total_stock}",
            parse_mode="Markdown"
        )
        return

    items = [l for l in text.splitlines() if l.strip()]
    if not items:
        return

    batch = context.user_data.get('stock_batch', [])
    batch.extend(items)
    context.user_data['stock_batch'] = batch

    await update.message.reply_text(
        f"➕ *{len(items)} item(s) added to batch*\n"
        f"📊 Total in batch: *{len(batch)}*\n\n"
        f"Keep sending more or send */done* to save.",
        parse_mode="Markdown"
    )

async def handle_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = context.user_data.get("state")

    if state == "await_stock_content" and is_admin(uid):
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        content_text = file_bytes.decode('utf-8', errors='ignore')
        items = [l for l in content_text.strip().splitlines() if l.strip()]

        batch = context.user_data.get('stock_batch', [])
        batch.extend(items)
        context.user_data['stock_batch'] = batch

        await update.message.reply_text(
            f"📄 *File uploaded!*\n"
            f"➕ {len(items)} item(s) added to batch\n"
            f"📊 Total in batch: *{len(batch)}*\n\n"
            f"Send more or send */done* to save.",
            parse_mode="Markdown"
        )
    elif state == "await_screenshot":
        await update.message.reply_text("❌ Please send an IMAGE screenshot, not a file.")

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: USERS LIST (paginated)
# ─────────────────────────────────────────────────────────────────────────────
async def adm_users_list(q, context, page=0):
    users = db.get_all_users()
    per_page = 10
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * per_page:(page + 1) * per_page]

    text = f"👥 *Users ({len(users)} total) — Page {page+1}/{total_pages}:*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for u in chunk:
        ban = "🚫" if u['banned'] else "✅"
        uname = f"@{u['username']}" if u['username'] else u['first_name']
        text += f"{ban} `{u['user_id']}` {uname}\n   Orders: {u['total_orders']} | Spent: ₹{u['total_spent']:.0f}\n\n"

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"adm_users_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"adm_users_page_{page+1}"))

    buttons = []
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([
        InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
        InlineKeyboardButton("✅ Unban User", callback_data="adm_unban")
    ])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_panel")])

    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(buttons))

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: OTHER PANELS
# ─────────────────────────────────────────────────────────────────────────────
async def adm_pending_orders(q, context):
    orders = db.get_pending_orders()
    if not orders:
        await q.edit_message_text(
            "✅ *No pending orders!*\n\nAll clear.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_panel")]]))
        return

    text = f"⏳ *Pending Orders ({len(orders)}):*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for o in orders[:10]:
        prod = PRODUCTS.get(o['product_key'], {})
        text += (
            f"🧾 #{o['id']} | {prod.get('name','?')} × {o['qty']}\n"
            f"   💰 ₹{o['amount']:.2f} | 👤 `{o['user_id']}`\n"
            f"   📅 {o['created_at'][:16]}\n\n"
        )

    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_panel")]]))

async def adm_stats(q, context):
    stats = db.get_stats()
    stocks = db.get_all_stock_counts()
    stock_text = ""
    for key, prod in PRODUCTS.items():
        cnt = stocks.get(key, 0)
        stock_text += f"  {prod['emoji']} {prod['name']}: {cnt}\n"

    text = (
        "📊 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: *{stats['total_users']}*\n"
        f"✅ Completed Orders: *{stats['total_orders']}*\n"
        f"⏳ Pending Orders: *{stats['pending_orders']}*\n"
        f"💰 Total Revenue: *₹{stats['total_revenue']:.2f}*\n\n"
        f"📦 *Current Stock:*\n{stock_text}"
    )
    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_panel")]]))

async def adm_broadcast_prompt(q, context):
    context.user_data['state'] = 'await_broadcast'
    await q.edit_message_text(
        "📢 *Broadcast Message*\n\nSend the message to broadcast to ALL users:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]])
    )

async def handle_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    users = db.get_all_users()
    sent, failed = 0, 0
    for u in users:
        try:
            await context.bot.send_message(
                u['user_id'],
                f"📢 *Announcement:*\n\n{msg}",
                parse_mode="Markdown"
            )
            sent += 1
        except:
            failed += 1
    context.user_data['state'] = None
    await update.message.reply_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"📤 Sent: {sent}\n❌ Failed: {failed}",
        parse_mode="Markdown"
    )

async def adm_reply_prompt(q, context):
    context.user_data['state'] = 'await_reply_uid'
    await q.edit_message_text(
        "💬 *Reply to User*\n\nSend the user's Telegram ID:\n\n"
        "_Tip: You can also reply directly to any payment screenshot message to message that user._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]])
    )

async def adm_price_menu(q, context):
    buttons = []
    for key, prod in PRODUCTS.items():
        buttons.append([InlineKeyboardButton(
            f"{prod['emoji']} {prod['name']} — ₹{prod['price']}",
            callback_data=f"adm_setprice_{key}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_panel")])
    await q.edit_message_text(
        "💲 *Set Price*\n\nSelect product to update price:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def adm_set_price_prompt(q, context, key):
    context.user_data['state'] = 'await_price_val'
    context.user_data['price_key'] = key
    prod = PRODUCTS[key]
    await q.edit_message_text(
        f"💲 *{prod['name']}*\nCurrent price: ₹{prod['price']}\n\nSend new price (number only):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_price")]])
    )

async def handle_price_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get('price_key')
    try:
        new_price = float(update.message.text.strip())
        PRODUCTS[key]['price'] = new_price
        context.user_data['state'] = None
        await update.message.reply_text(
            f"✅ *Price Updated!*\n\n{PRODUCTS[key]['name']} → ₹{new_price:.2f}",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("❌ Invalid. Send a number like `21` or `30.5`", parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# CANCEL ORDER
# ─────────────────────────────────────────────────────────────────────────────
async def handle_cancel_order(q, context, order_id):
    await q.edit_message_caption(caption="❌ Order cancelled.", reply_markup=None)

# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data

    if db.is_banned(uid) and not is_admin(uid):
        await q.answer("🚫 You are banned.", show_alert=True)
        return

    allowed, reason = check_rate_limit(uid)
    if not allowed:
        await q.answer(reason, show_alert=True)
        return

    await q.answer()

    if d.startswith("buy_"):
        key = d[4:]
        await show_product_detail(q, context, key)

    elif d.startswith("qty_"):
        rest = d[len("qty_"):]
        qty_val = rest.rsplit("_", 1)[1]
        key = rest.rsplit("_", 1)[0]
        if qty_val == "custom":
            context.user_data['buy_key'] = key
            context.user_data['state'] = 'await_qty'
            await q.edit_message_text(
                "✏️ Enter the quantity you want:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"buy_{key}")]])
            )
        else:
            qty = int(qty_val)
            await show_terms(q, context, key, qty)

    elif d.startswith("agree_"):
        rest = d[len("agree_"):]
        qty = int(rest.rsplit("_", 1)[1])
        key = rest.rsplit("_", 1)[0]
        context.user_data['buy_key'] = key
        context.user_data['buy_qty'] = qty
        await handle_confirm_order(q, context)

    elif d.startswith("paid_"):
        await handle_paid_button(q, context)

    elif d.startswith("cancel_order_"):
        order_id = int(d.split("_")[2])
        await handle_cancel_order(q, context, order_id)

    elif d.startswith("approve_"):
        if is_admin(uid):
            parts = d.split("_")
            await handle_approve(q, context, parts)

    elif d.startswith("reject_"):
        if is_admin(uid):
            parts = d.split("_")
            await handle_reject(q, context, parts)

    elif d == "back_products":
        await show_products_inline(q, context)

    elif d == "adm_panel":
        if is_admin(uid):
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode="Markdown",
                                       reply_markup=admin_menu_inline())
    elif d == "adm_stock":
        if is_admin(uid):
            await adm_stock_menu(q, context)
    elif d.startswith("adm_addstock_"):
        if is_admin(uid):
            key = d[len("adm_addstock_"):]
            await adm_add_stock_prompt(q, context, key)
    elif d == "adm_pending":
        if is_admin(uid):
            await adm_pending_orders(q, context)
    elif d == "adm_users":
        if is_admin(uid):
            await adm_users_list(q, context, page=0)
    elif d.startswith("adm_users_page_"):
        if is_admin(uid):
            page = int(d.split("_")[-1])
            await adm_users_list(q, context, page=page)
    elif d == "adm_stats":
        if is_admin(uid):
            await adm_stats(q, context)
    elif d == "adm_broadcast":
        if is_admin(uid):
            await adm_broadcast_prompt(q, context)
    elif d == "adm_reply":
        if is_admin(uid):
            await adm_reply_prompt(q, context)
    elif d == "adm_price":
        if is_admin(uid):
            await adm_price_menu(q, context)
    elif d.startswith("adm_setprice_"):
        if is_admin(uid):
            key = d[len("adm_setprice_"):]
            await adm_set_price_prompt(q, context, key)
    elif d == "adm_ban":
        if is_admin(uid):
            context.user_data['state'] = 'await_ban_uid'
            await q.edit_message_text(
                "🚫 Send the user ID to ban:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_users")]])
            )
    elif d == "adm_unban":
        if is_admin(uid):
            context.user_data['state'] = 'await_unban_uid'
            await q.edit_message_text(
                "✅ Send the user ID to unban:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_users")]])
            )

    elif d == "adm_viewstock":
        if is_admin(uid):
            await adm_view_stock_menu(q, context)
    elif d.startswith("adm_vstk_"):
        if is_admin(uid):
            parts = d.split("_")
            page = int(parts[-1])
            key = "_".join(parts[2:-1])
            await adm_view_stock_items(q, context, key, page)
    elif d.startswith("adm_delitem_"):
        if is_admin(uid):
            parts = d.split("_")
            item_id = int(parts[2])
            page = int(parts[-1])
            key = "_".join(parts[3:-1])
            success = db.delete_stock_item(item_id)
            status = "✅ Deleted!" if success else "❌ Item not found."
            await q.answer(status, show_alert=True)
            await adm_view_stock_items(q, context, key, page)
    elif d.startswith("adm_delall_"):
        if is_admin(uid):
            key = d[len("adm_delall_"):]
            count = db.delete_all_stock(key)
            prod = get_all_products().get(key, {})
            await q.answer(f"Deleted {count} items!", show_alert=True)
            await adm_view_stock_menu(q, context)
    elif d == "adm_addproduct":
        if is_admin(uid):
            await adm_add_product_prompt(q, context)
    elif d == "adm_removeproduct":
        if is_admin(uid):
            await adm_remove_product_menu(q, context)
    elif d.startswith("adm_delprod_"):
        if is_admin(uid):
            key = d[len("adm_delprod_"):]
            db.remove_product(key)
            if key in PRODUCTS:
                del PRODUCTS[key]
            await q.answer("Product removed!", show_alert=True)
            await adm_remove_product_menu(q, context)

async def show_products_inline(q, context):
    stocks = db.get_all_stock_counts()
    buttons = []
    for key, prod in PRODUCTS.items():
        cnt = stocks.get(key, 0)
        if cnt > 10:
            stock_label = f"✅ {cnt}"
        elif cnt > 0:
            stock_label = f"🟡 Low: {cnt}"
        else:
            stock_label = "❌ Out"
        buttons.append([InlineKeyboardButton(
            f"{prod['emoji']} {prod['name']} — ₹{prod['price']} ({stock_label})",
            callback_data=f"buy_{key}"
        )])
    await q.edit_message_text(
        "🛒 *Available Products*\n━━━━━━━━━━━━━━━━━━━━━━━\n\nSelect a product below 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_qty_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
        key = context.user_data.get('buy_key')
        context.user_data['state'] = None
        prod = PRODUCTS[key]
        total = prod['price'] * qty
        context.user_data['buy_qty'] = qty
        text = (
            "📋 *Terms & Conditions*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚨 *Important Note:*\n"
            "_• Use immediately after delivery\n"
            "• Report issues within 24 hours\n"
            "• Screen recording mandatory_\n\n"
            f"🛍️ *{prod['name']}*\n"
            f"🔢 Qty: {qty}  |  💰 Total: ₹{total:.2f}\n\n"
            "Tap *I Agree* to proceed 👇"
        )
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I Agree — Proceed to Payment", callback_data=f"agree_{key}_{qty}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"buy_{key}")]
            ])
        )
    except:
        await update.message.reply_text("❌ Enter a valid number like `1`, `2`, `5`", parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN COMMANDS
# ─────────────────────────────────────────────────────────────────────────────
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Not authorized.")
        return
    await update.message.reply_text(
        "🔧 *Admin Panel*", parse_mode="Markdown",
        reply_markup=admin_menu_inline()
    )

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    state = context.user_data.get("state")
    if state == "await_stock_content":
        await handle_stock_batch(update, context)

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target = int(context.args[0])
        db.ban_user(target)
        await update.message.reply_text(f"🚫 User `{target}` banned.", parse_mode="Markdown")
        try:
            await context.bot.send_message(target, "🚫 You have been banned from this bot.")
        except:
            pass
    except:
        await update.message.reply_text("Usage: /ban <user_id>")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target = int(context.args[0])
        db.unban_user(target)
        await update.message.reply_text(f"✅ User `{target}` unbanned.", parse_mode="Markdown")
        try:
            await context.bot.send_message(target, "✅ You have been unbanned! Welcome back.")
        except:
            pass
    except:
        await update.message.reply_text("Usage: /unban <user_id>")



# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_all_products():
    """Merge default PRODUCTS with any custom DB products."""
    all_p = dict(PRODUCTS)
    try:
        custom = db.get_custom_products()
        all_p.update(custom)
    except:
        pass
    return all_p

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: VIEW STOCK
# ─────────────────────────────────────────────────────────────────────────────
async def adm_view_stock_menu(q, context):
    stocks = db.get_all_stock_counts()
    buttons = []
    for key, prod in get_all_products().items():
        cnt = stocks.get(key, 0)
        buttons.append([InlineKeyboardButton(
            f"{prod['emoji']} {prod['name']} — {cnt} items",
            callback_data=f"adm_vstk_{key}_0"
        )])
    buttons.append([InlineKeyboardButton("\U0001f519 Back", callback_data="adm_panel")])
    await q.edit_message_text(
        "\U0001f440 *View Stock*\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\nSelect product:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def adm_view_stock_items(q, context, key, page):
    prod = get_all_products().get(key, {})
    per_page = 5
    offset = page * per_page
    items = db.get_stock_items(key, limit=per_page, offset=offset)
    total = db.get_stock_items_count(key)
    total_pages = max(1, (total + per_page - 1) // per_page)

    if not items:
        text = f"No stock for *{prod.get('name','?')}*"
    else:
        text = f"*{prod.get('name','?')}* — {total} items (Page {page+1}/{total_pages})\n\n"
        for i, item in enumerate(items, start=offset+1):
            short = item['content'][:35] + "..." if len(item['content']) > 35 else item['content']
            text += f"`#{item['id']}` {i}. {short}\n"

    buttons = []
    for item in items:
        short = item['content'][:18] + ".." if len(item['content']) > 18 else item['content']
        buttons.append([InlineKeyboardButton(
            f"Delete #{item['id']}: {short}",
            callback_data=f"adm_delitem_{item['id']}_{key}_{page}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"adm_vstk_{key}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"adm_vstk_{key}_{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(f"Delete ALL {total} items", callback_data=f"adm_delall_{key}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="adm_viewstock")])

    await q.edit_message_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(buttons))

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: ADD PRODUCT (step by step)
# ─────────────────────────────────────────────────────────────────────────────
async def adm_add_product_prompt(q, context):
    context.user_data['state'] = 'await_new_product'
    context.user_data['new_product_step'] = 'name'
    context.user_data['new_product'] = {}
    await q.edit_message_text(
        "Step 1/4: Send the *product name*\nExample: `Meesho 200 OFF JSON`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="adm_panel")]])
    )

async def handle_new_product_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('new_product_step')
    data = context.user_data.get('new_product', {})
    text = update.message.text.strip()

    if step == 'name':
        data['name'] = text
        context.user_data['new_product_step'] = 'emoji'
        await update.message.reply_text("Step 2/4: Send an *emoji* for this product\nExample: `\U0001f6cd`", parse_mode="Markdown")
    elif step == 'emoji':
        data['emoji'] = text
        context.user_data['new_product_step'] = 'price'
        await update.message.reply_text("Step 3/4: Send the *price* (number only)\nExample: `25`", parse_mode="Markdown")
    elif step == 'price':
        try:
            data['price'] = float(text)
            context.user_data['new_product_step'] = 'description'
            await update.message.reply_text("Step 4/4: Send a short *description*\nExample: `Meesho Rs200 OFF coupon JSON`", parse_mode="Markdown")
        except:
            await update.message.reply_text("Invalid price. Send a number like `25`", parse_mode="Markdown")
    elif step == 'description':
        data['description'] = text
        # Generate key from name
        key = data['name'].lower().replace(' ', '_')[:20]
        db.add_product(key, data['name'], data['emoji'], data['price'], data['description'])
        # Add to runtime PRODUCTS too
        PRODUCTS[key] = {'name': data['name'], 'emoji': data['emoji'],
                          'price': data['price'], 'description': data['description']}
        context.user_data['state'] = None
        context.user_data['new_product_step'] = None
        await update.message.reply_text(
            f"Product *{data['name']}* added successfully!\n"
            f"Key: `{key}`\nPrice: Rs{data['price']}",
            parse_mode="Markdown"
        )

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: REMOVE PRODUCT
# ─────────────────────────────────────────────────────────────────────────────
async def adm_remove_product_menu(q, context):
    custom = db.get_custom_products()
    if not custom:
        await q.edit_message_text(
            "No custom products to remove.\nDefault products cannot be deleted.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="adm_panel")]])
        )
        return
    buttons = []
    for key, prod in custom.items():
        buttons.append([InlineKeyboardButton(
            f"Delete {prod['emoji']} {prod['name']}",
            callback_data=f"adm_delprod_{key}"
        )])
    buttons.append([InlineKeyboardButton("Back", callback_data="adm_panel")])
    await q.edit_message_text(
        "Select product to remove:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_stock_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_reply))

    print("🤖 Looter Pros Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
