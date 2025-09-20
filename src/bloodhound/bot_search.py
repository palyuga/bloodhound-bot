# bot_search.py
import os
import asyncio
import logging
from typing import List, Optional, Dict, Any, Any as AnyType

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters, Application, JobQueue, CallbackContext,
)

from sqlalchemy import create_engine, and_, func, select
from sqlalchemy.orm import sessionmaker
import sqlalchemy

from src.bloodhound.models import Post, PostType

DISTRICTS_CACHE = {"rent": [], "sell": []}

BUDGET_QUESTION = "Max budget in USD (send a number or type 'Skip')"

# --- Config & logging ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bloodhound.db")
CHANNEL_USERNAME = "rent_tbilisi_ge"  # used to build links

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rentbot")

# --- DB ---
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine, future=True)

# --- Conversation states ---
(
    STATE_TYPE,
    STATE_DISTRICTS,
    STATE_BUDGET,
    STATE_ROOMS,
    STATE_PETS,
    STATE_FEATURES,
    STATE_CONFIRM,
) = range(7)

PAGE_SIZE = 10

# --- Predefined features scaffold ---
PREDEFINED_FEATURES = ["Balcony", "Conditioner", "Oven", "Dishwasher"]

# --- Priority districts ordering ---
PRIORITY_DISTRICTS = ["Vake", "Saburtalo", "Vera", "Mtatsminda", "Sololaki"]


# --- DB helpers ---

def sort_districts(districts: list) -> list:
    """Put priority districts first, then the rest alphabetically."""
    priority = [d for d in PRIORITY_DISTRICTS if d in districts]
    others = sorted([d for d in districts if d not in PRIORITY_DISTRICTS])
    return priority + others


def _distinct_districts_for_type_db(post_type: str):
    """Return distinct districts for given post_type (synchronous DB call)."""
    with Session() as session:
        # Post.type is Enum(PostType) so compare with PostType[post_type]
        q = session.query(func.distinct(Post.district)).filter(
            Post.deleted.is_(False),
            Post.type == PostType[post_type]
        )
        return [r[0] for r in q.all() if r[0] is not None]


async def get_distinct_districts(post_type: str) -> List[str]:
    """Async wrapper to get distinct districts only for the given type (rent/sell)."""
    return await asyncio.to_thread(_distinct_districts_for_type_db, post_type)


async def search_posts(filters: Dict[str, Any]) -> List[Post]:
    """
    filters: {
        "type": "rent"|"sell",
        "districts": [..] or None,
        "max_price": int or None,
        "rooms": [..] or None,  # values: 0 (studio), 1,2,3,4 (4 means 4+); None means Any
        "pets_allowed": True/False/None,
        "features": [..] or None
    }
    """
    def _query():
        with Session() as session:
            q = session.query(Post).filter(Post.deleted.is_(False))
            # type
            if filters.get("type"):
                t = PostType[filters["type"]]
                q = q.filter(Post.type == t)
            # districts
            if filters.get("districts"):
                q = q.filter(Post.district.in_(filters["districts"]))
            # price (max)
            if filters.get("max_price") is not None:
                q = q.filter(Post.price <= filters["max_price"])
            # rooms: support studio (0), 1,2,3,4+
            rooms_sel = filters.get("rooms")
            if rooms_sel:
                conds = []
                # studio
                if 0 in rooms_sel:
                    conds.append(Post.rooms == 0)
                # 4+ (rooms >=4)
                if 4 in rooms_sel:
                    conds.append(Post.rooms >= 4)
                # other explicit numbers (1,2,3)
                non_special = [r for r in rooms_sel if r not in (0, 4)]
                if non_special:
                    conds.append(Post.rooms.in_(non_special))
                if conds:
                    q = q.filter(sqlalchemy.or_(*conds))
            # pets
            dogs = filters.get("pets_allowed")
            if dogs is True:
                q = q.filter(Post.pets.in_(["allowed", "by_agreement"]))
            # features: for sqlite JSON list we filter in Python after fetching candidates
            feats = filters.get("features")
            if feats:
                candidates = q.all()
                def _has_all_features(post):
                    pf = set([s.lower() for s in (post.features or [])])
                    return all(f.lower() in pf for f in feats)
                return [p for p in candidates if _has_all_features(p)]
            # finally
            return q.order_by(Post.created_at.desc()).all()
    return await asyncio.to_thread(_query)


# --- Keyboard helpers ---


def chunk_buttons(items: List[str], per_row=2):
    kb = []
    if not items:
        return kb
    max_len = max(len(i) for i in items)
    row = []
    for i, it in enumerate(items, 1):
        row.append(InlineKeyboardButton(it.ljust(max_len), callback_data=f"toggle::{it}"))
        if i % per_row == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return kb


def make_page_keyboard(page: int, total: int, prefix: str):
    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}::prev::{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        kb.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}::next::{page+1}"))
    kb.append(InlineKeyboardButton("🔄 New search", callback_data="newsearch"))
    return InlineKeyboardMarkup([kb])


def build_multichoice_keyboard(items: List[str], selected: Optional[List[str]] = None,
                               done_data="done", skip_data=None, per_row=2):
    """
    Build multi-choice inline keyboard with checkmarks for selected items.
    - Keeps a 2-column layout by default.
    - Anchors 'Next' button at the bottom in its own row.
    """
    selected = selected or []
    kb = []
    row = []

    for i, item in enumerate(items, 1):
        label = f"✅ {item}" if item in selected else item
        row.append(InlineKeyboardButton(label, callback_data=f"toggle::{item}"))
        if i % per_row == 0:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    if skip_data:
        kb.append([InlineKeyboardButton("Any", callback_data=skip_data)])
    kb.append([InlineKeyboardButton("➡️ Next", callback_data=done_data)])
    return InlineKeyboardMarkup(kb)


# --- Bot handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! I'll help you to find apartments\nFirst: Rent or Buy?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Rent", callback_data="type::rent"),
             InlineKeyboardButton("Buy", callback_data="type::sell")]
        ])
    )
    return STATE_TYPE


async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, chosen = q.data.split("::", 1)
    context.user_data["type"] = chosen  # 'rent' or 'sell'

    districts = sort_districts(DISTRICTS_CACHE[chosen])
    if not districts:
        await q.edit_message_text("No flats available for the given type of deal")
        return ConversationHandler.END

    context.user_data["districts_selected"] = []

    await q.edit_message_text(
        "Select districts (multiple choice). Press Next when finished or Any to select all",
        reply_markup=build_multichoice_keyboard(
            districts, selected=[], done_data="districts::done", skip_data="districts::any", per_row=2
        )
    )
    return STATE_DISTRICTS


async def districts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "districts::done":
        await q.edit_message_text(BUDGET_QUESTION)
        return STATE_BUDGET

    if data == "districts::any":
        context.user_data["districts_selected"] = None
        await q.edit_message_text(BUDGET_QUESTION)
        return STATE_BUDGET

    # toggle selection
    prefix, val = data.split("::", 1)
    if prefix != "toggle":
        return STATE_DISTRICTS

    # Initialize selection if None
    sel = context.user_data.get("districts_selected")
    if sel is None:
        sel = []
        context.user_data["districts_selected"] = sel

    # Toggle district
    if val in sel:
        sel.remove(val)
    else:
        sel.append(val)

    # Re-fetch districts for the same chosen type to preserve consistent list
    districts = sort_districts(DISTRICTS_CACHE[context.user_data["type"]])

    # Only add "Next" button if at least one selected
    done_data = "districts::done" if sel else None
    skip_data = "districts::any"

    # Rebuild keyboard with selections (2 columns)
    kb = []
    per_row = 2
    row = []
    for i, d in enumerate(districts, 1):
        label = f"✅ {d}" if d in sel else d
        row.append(InlineKeyboardButton(label, callback_data=f"toggle::{d}"))
        if i % per_row == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    # Add Next only when selection exists, otherwise still show Any
    if sel:
        kb.append([InlineKeyboardButton("➡️ Next", callback_data="districts::done")])
    kb.append([InlineKeyboardButton("Any", callback_data="districts::any")])

    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return STATE_DISTRICTS


async def budget_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ("skip", "no"):
        context.user_data["max_price"] = None
    else:
        try:
            context.user_data["max_price"] = int(''.join(ch for ch in text if ch.isdigit()))
        except Exception:
            await update.message.reply_text("I didn't understand. Please send a number or 'skip'.")
            return STATE_BUDGET

    # initialize rooms_selected
    context.user_data["rooms_selected"] = []

    # Show Studio, 1,2,3,4+, Any in a horizontal row
    kb = [
        [
            InlineKeyboardButton("Studio", callback_data="room::0"),
            InlineKeyboardButton("1", callback_data="room::1"),
            InlineKeyboardButton("2", callback_data="room::2"),
            InlineKeyboardButton("3", callback_data="room::3"),
            InlineKeyboardButton("4+", callback_data="room::4"),
            InlineKeyboardButton("Any", callback_data="room::any"),
        ]
    ]
    await update.message.reply_text("Number of bedrooms (multiple allowed):", reply_markup=InlineKeyboardMarkup(kb))
    return STATE_ROOMS


async def rooms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, val = q.data.split("::", 1)

    sel = context.user_data.setdefault("rooms_selected", [])

    if val == "any":
        # User selected "Any" → clear selections and proceed
        context.user_data["rooms_selected"] = None
        # Proceed to next question (pets or features)
        if context.user_data.get("type") == "sell":
            return await features_callback(update, context)
        else:
            kb = [
                [InlineKeyboardButton("Yes", callback_data="pets::yes"),
                 InlineKeyboardButton("No", callback_data="pets::no")]
            ]
            await q.edit_message_text("Do you have pets?", reply_markup=InlineKeyboardMarkup(kb))
            return STATE_PETS

    # Regular selection: val is "0","1","2","3","4"
    r = 4 if val == "4" else int(val)
    # If previously Any was selected (None), convert to list
    if sel is None:
        sel = []
        context.user_data["rooms_selected"] = sel

    if r in sel:
        sel.remove(r)
    else:
        sel.append(r)

    labels = [("Studio", 0), ("1", 1), ("2", 2), ("3", 3), ("4+", 4), ("Any", "any")]
    kb_row = []
    for label_text, label_val in labels:
        if label_val == "any":
            checked = sel is None
            data = "room::any"
        else:
            checked = (label_val in sel) if sel is not None else False
            data = f"room::{label_val}"
        btn_label = f"✅ {label_text}" if checked else label_text
        kb_row.append(InlineKeyboardButton(btn_label, callback_data=data))

    # Add Next button if any selection present (or Any)
    if sel or sel is None:
        kb = [kb_row, [InlineKeyboardButton("➡️ Next", callback_data="rooms::done")]]
    else:
        kb = [kb_row]

    await q.edit_message_text("Select rooms (multiple allowed):", reply_markup=InlineKeyboardMarkup(kb))
    return STATE_ROOMS

async def rooms_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # If no selection at all (empty list), ask to choose
    if context.user_data.get("rooms_selected") == []:
        await q.edit_message_text("You must select at least one rooms option.")
        return STATE_ROOMS
    if context.user_data.get("type") == "sell":
        return await features_callback(update, context)
    kb = [
        [InlineKeyboardButton("Yes", callback_data="pets::yes"), InlineKeyboardButton("No", callback_data="pets::no")]
    ]
    await q.edit_message_text("Do you have pets?", reply_markup=InlineKeyboardMarkup(kb))
    return STATE_PETS


async def pets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, val = q.data.split("::", 1)
    context.user_data["pets_allowed"] = True if val == "yes" else False

    if context.user_data.get("features_selected") is None:
        context.user_data["features_selected"] = []

    return await features_callback(update, context)


async def features_callback(update: AnyType, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query if hasattr(update, "callback_query") else update
    feats = PREDEFINED_FEATURES
    context.user_data.setdefault("features_selected", [])

    sel = context.user_data.get("features_selected") or []

    done_data = "features::done" if sel else None
    skip_data = "features::skip"

    kb = []
    per_row = 2
    row = []
    for i, f in enumerate(feats, 1):
        label = f"✅ {f}" if f in sel else f
        row.append(InlineKeyboardButton(label, callback_data=f"toggle::{f}"))
        if i % per_row == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    if done_data:
        kb.append([InlineKeyboardButton("➡️ Next", callback_data=done_data)])
    kb.append([InlineKeyboardButton("Skip", callback_data=skip_data)])

    await q.edit_message_text(
        "Select mandatory features (toggle), or Skip:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return STATE_FEATURES


async def features_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "features::done":
        return await finalize_and_search(q, context)
    if q.data == "features::skip":
        context.user_data["features_selected"] = None
        return await finalize_and_search(q, context)

    prefix, val = q.data.split("::", 1)
    sel = context.user_data.setdefault("features_selected", [])

    if val in sel:
        sel.remove(val)
    else:
        sel.append(val)

    # Rebuild keyboard dynamically
    feats = PREDEFINED_FEATURES
    done_data = "features::done" if sel else None
    skip_data = "features::skip"

    kb = []
    per_row = 2
    row = []
    for i, f in enumerate(feats, 1):
        label = f"✅ {f}" if f in sel else f
        row.append(InlineKeyboardButton(label, callback_data=f"toggle::{f}"))
        if i % per_row == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    if done_data:
        kb.append([InlineKeyboardButton("➡️ Next", callback_data=done_data)])
    kb.append([InlineKeyboardButton("Skip", callback_data=skip_data)])

    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return STATE_FEATURES


async def finalize_and_search(q: AnyType, context: ContextTypes.DEFAULT_TYPE):
    filters = {
        "type": context.user_data.get("type"),
        "districts": context.user_data.get("districts_selected"),
        "max_price": context.user_data.get("max_price"),
        "rooms": context.user_data.get("rooms_selected"),
        "pets_allowed": context.user_data.get("pets_allowed"),
        "features": context.user_data.get("features_selected"),
    }
    await q.edit_message_text("Searching…")
    results = await search_posts(filters)
    context.user_data["last_results"] = results
    context.user_data["last_filters"] = filters
    return await send_results_page(q, context, page=0)


async def send_results_page(q_or_msg: AnyType, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    results: List[Post] = context.user_data.get("last_results", [])
    filters = context.user_data.get("last_filters", {})
    total = len(results)

    def format_filters(filters: dict) -> str:
        parts = []
        if filters.get("type"):
            parts.append(f"Type: {'Rent' if filters['type'] == 'rent' else 'Buy'}")
        districts = filters.get("districts")
        parts.append(f"Districts: {', '.join(districts) if districts else 'Any'}")
        max_price = filters.get("max_price")
        if max_price:
            parts.append(f"Max: ${max_price}")
        rooms = filters.get("rooms")
        if rooms:
            room_strs = [("Studio" if r == 0 else ("4+" if r == 4 else str(r))) for r in rooms]
            parts.append(f"Bedrooms: {', '.join(room_strs)}")
        pets = filters.get("pets_allowed")
        if pets is True:
            parts.append("Pet-friendly")
        features = filters.get("features")
        if features:
            parts.append(f"Features: {', '.join(features)}")
        return " | ".join(parts)

    filters_summary = format_filters(filters)

    if total == 0:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Start a new search", callback_data="newsearch")]
        ])
        await q_or_msg.edit_message_text(
            f"Your search:\n{filters_summary}\n\nNo posts match your criteria. Try a different search.",
            reply_markup=keyboard
        )
        return STATE_CONFIRM

    # Paginate results
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_posts = results[start:end]

    lines = [f"Found {total} posts — showing {start+1}-{min(end, total)}"]
    for p in page_posts:
        link = f"https://t.me/{CHANNEL_USERNAME}/{p.source_id}"
        rooms_label = "Studio" if (p.rooms == 0) else (f"{p.rooms} Bedrooms" if p.rooms else "? Bedrooms")
        lines.append(f"{p.district or ''} • {p.address or ''} • {rooms_label} • ${p.price or '?'}\n{link}")

    text = f"Your search:\n{filters_summary}\n\nResults:\n" + "\n\n".join(lines)
    keyboard = make_page_keyboard(page, total, prefix="page")

    if hasattr(q_or_msg, "edit_message_text"):
        await q_or_msg.edit_message_text(text, reply_markup=keyboard)
    else:
        await q_or_msg.reply_text(text, reply_markup=keyboard)

    context.user_data["page"] = page
    return STATE_CONFIRM


async def pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "newsearch":
        # Preserve last search results for reference
        previous_results = context.user_data.get("last_results")
        previous_filters = context.user_data.get("last_filters")
        context.user_data.clear()
        if previous_results:
            context.user_data["previous_results"] = previous_results
            context.user_data["previous_filters"] = previous_filters

        await q.edit_message_text("Starting new search. Rent or Buy?",
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("Rent", callback_data="type::rent"),
                                       InlineKeyboardButton("Buy", callback_data="type::sell")]
                                  ]))
        return STATE_TYPE
    prefix, action, page_str = data.split("::", 2)
    page = int(page_str)
    return await send_results_page(q, context, page=page)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# --- Build application ---
def build_app():
    job_queue = JobQueue()
    app = Application.builder().token(BOT_TOKEN).job_queue(job_queue).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_TYPE: [CallbackQueryHandler(type_handler, pattern=r"^type::")],
            STATE_DISTRICTS: [CallbackQueryHandler(districts_callback, pattern=r"^(toggle::|districts::)")],
            STATE_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_message)],
            STATE_ROOMS: [
                CallbackQueryHandler(rooms_callback, pattern=r"^room::"),
                CallbackQueryHandler(rooms_done_callback, pattern=r"^rooms::done"),
            ],
            STATE_PETS: [CallbackQueryHandler(pets_callback, pattern=r"^pets::")],
            STATE_FEATURES: [CallbackQueryHandler(features_handler, pattern=r"^(toggle::|features::)")],
            STATE_CONFIRM: [
                CallbackQueryHandler(pagination_callback, pattern=r"^(page::|newsearch)"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app

async def refresh_districts(_: CallbackContext) -> None:
    with Session() as session:
        logger.info("refresh_districts() is called")
        rent_q = session.query(Post.district).filter(
            Post.deleted.is_(False),  Post.type == PostType.rent
        )
        sell_q = session.query(Post.district).filter(
            Post.deleted.is_(False),  Post.type == PostType.sell
        )
        DISTRICTS_CACHE["rent"] = sorted({d[0] for d in rent_q.distinct() if d[0]})
        DISTRICTS_CACHE["sell"] = sorted({d[0] for d in sell_q.distinct() if d[0]})

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Set BOT_TOKEN in env or .env file")
        raise SystemExit(1)
    app = build_app()
    app.job_queue.run_repeating(refresh_districts, interval=300, first=5)
    app.run_polling()

