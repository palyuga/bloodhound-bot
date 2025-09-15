# bot_search.py
import os
import asyncio
import logging
from typing import List, Optional, Dict, Any

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
    filters,
)

from sqlalchemy import create_engine, and_, func
from sqlalchemy.orm import sessionmaker
import sqlalchemy

# Import your models
from src.bloodhound.models import Post, PostType

BUDGET_QUESTION = "Max budget in USD (send a number or type 'Skip')"

# --- Config & logging ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bloodhound.db")
CHANNEL_USERNAME = "rent_tbilisi_ge" # used to build links

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
PREDEFINED_FEATURES = ["Balcony", "Conditioner", "Oven", "Dishwasher", "TV"]

# --- DB helpers ---

def _distinct_values_from_db(column):
    with Session() as session:
        q = session.query(func.distinct(column)).filter(Post.deleted.is_(False))
        return [r[0] for r in q.all() if r[0] is not None]


async def get_distinct_districts():
    return await asyncio.to_thread(_distinct_values_from_db, Post.district)


async def search_posts(filters: Dict[str, Any]) -> List[Post]:
    def _query():
        with Session() as session:
            q = session.query(Post).filter(Post.deleted.is_(False))
            if filters.get("type"):
                t = PostType[filters["type"]]
                q = q.filter(Post.type == t)
            if filters.get("districts"):
                q = q.filter(Post.district.in_(filters["districts"]))
            if filters.get("max_price") is not None:
                q = q.filter(Post.price <= filters["max_price"])
            rooms_sel = filters.get("rooms")
            if rooms_sel:
                conds = []
                if 4 in rooms_sel:
                    conds.append(Post.rooms >= 4)
                non_four = [r for r in rooms_sel if r != 4]
                if non_four:
                    conds.append(Post.rooms.in_(non_four))
                if conds:
                    q = q.filter(sqlalchemy.or_(*conds))
            dogs = filters.get("pets_allowed")
            if dogs is True:
                q = q.filter(Post.pets.in_(["allowed", "by_agreement"]))
            feats = filters.get("features")
            if feats:
                candidates = q.all()
                def _has_all_features(post):
                    pf = set([s.lower() for s in (post.features or [])])
                    return all(f.lower() in pf for f in feats)
                return [p for p in candidates if _has_all_features(p)]
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
    - Keeps original 2-column layout.
    - Always anchors 'Next' button at the bottom.
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

    kb.append([InlineKeyboardButton("➡️ Next", callback_data=done_data)])

    if skip_data:
        kb.append([InlineKeyboardButton("Skip", callback_data=skip_data)])

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
    context.user_data["type"] = chosen

    districts = sort_districts(await get_distinct_districts())
    if not districts:
        await q.edit_message_text("No districts available in DB.")
        return ConversationHandler.END

    context.user_data["districts_selected"] = []

    # Build keyboard with NO Next button initially
    kb = []
    per_row = 2
    row = []
    for i, d in enumerate(districts, 1):
        row.append(InlineKeyboardButton(d, callback_data=f"toggle::{d}"))
        if i % per_row == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    # Always include "Any" button
    kb.append([InlineKeyboardButton("Any", callback_data="districts::any")])

    await q.edit_message_text(
        "Select districts (toggle). Press Next when finished or Any to select all",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return STATE_DISTRICTS


PRIORITY_DISTRICTS = ["Vake", "Saburtalo", "Vera", "Mtatsminda", "Sololaki"]

def sort_districts(districts: list) -> list:
    """Put priority districts first, then the rest alphabetically."""
    priority = [d for d in PRIORITY_DISTRICTS if d in districts]
    others = sorted([d for d in districts if d not in PRIORITY_DISTRICTS])
    return priority + others

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

    # Fetch and sort districts
    districts = sort_districts(await get_distinct_districts())

    # Only add "Next" button if at least one selected
    done_data = "districts::done" if sel else None
    skip_data = "districts::any"

    # Build keyboard safely
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
    if done_data:
        kb.append([InlineKeyboardButton("➡️ Next", callback_data=done_data)])
    if skip_data:
        kb.append([InlineKeyboardButton("Any", callback_data=skip_data)])

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
    context.user_data["rooms_selected"] = []
    kb = [
        [InlineKeyboardButton("1", callback_data="room::1"),
         InlineKeyboardButton("2", callback_data="room::2"),
         InlineKeyboardButton("3", callback_data="room::3"),
         InlineKeyboardButton("4+", callback_data="room::4"),
         InlineKeyboardButton("Any", callback_data="room::any")]
    ]
    await update.message.reply_text("Select rooms (multiple allowed):", reply_markup=InlineKeyboardMarkup(kb))
    return STATE_ROOMS

async def rooms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, val = q.data.split("::", 1)

    sel = context.user_data.setdefault("rooms_selected", [])

    if val == "any":
        # User selected "Any" → clear selections
        context.user_data["rooms_selected"] = None
        # Proceed to next question
        if context.user_data.get("type") == "sell":
            return await features_callback(update, context)
        else:
            kb = [
                [InlineKeyboardButton("Yes", callback_data="pets::yes"),
                 InlineKeyboardButton("No", callback_data="pets::no")]
            ]
            await q.edit_message_text("Do you have pets?", reply_markup=InlineKeyboardMarkup(kb))
            return STATE_PETS

    # Regular number selection
    r = 4 if val == "4" else int(val)
    if sel is None:
        sel = []
        context.user_data["rooms_selected"] = sel

    if r in sel:
        sel.remove(r)
    else:
        sel.append(r)

    # Build horizontal compact keyboard with Any
    labels = ["1", "2", "3", "4+", "Any"]
    kb_row = []
    for l in labels:
        if l == "Any":
            checked = sel is None
            data = "room::any"
        else:
            r_val = 4 if l == "4+" else int(l)
            checked = r_val in sel if sel is not None else False
            data = f"room::{l.strip('+')}"
        label = f"✅ {l}" if checked else l
        kb_row.append(InlineKeyboardButton(label, callback_data=data))

    # Only add "Next" button if at least one option selected or "Any"
    if sel or sel is None:
        kb = [kb_row, [InlineKeyboardButton("➡️ Next", callback_data="rooms::done")]]
    else:
        kb = [kb_row]  # No Next button

    await q.edit_message_text("Select rooms (multiple allowed):", reply_markup=InlineKeyboardMarkup(kb))
    return STATE_ROOMS

async def rooms_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not context.user_data.get("rooms_selected"):
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
    return await features_callback(update, context)


async def features_callback(update: Any, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query if hasattr(update, "callback_query") else update
    feats = PREDEFINED_FEATURES
    context.user_data.setdefault("features_selected", [])

    sel = context.user_data.get("features_selected", [])

    # Only show "Next" button if at least one feature is selected
    done_data = "features::done" if sel else None
    skip_data = "features::skip"

    # Build keyboard manually to control Next button dynamically
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
    if skip_data:
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
    if skip_data:
        kb.append([InlineKeyboardButton("Skip", callback_data=skip_data)])

    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return STATE_FEATURES



async def finalize_and_search(q: Any, context: ContextTypes.DEFAULT_TYPE):
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

async def send_results_page(q_or_msg: Any, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    results: List[Post] = context.user_data.get("last_results", [])
    filters = context.user_data.get("last_filters", {})
    total = len(results)

    def format_filters(filters: dict) -> str:
        """
        Return a concise, human-readable summary of the user's search.
        Only include relevant filters (omit pets if not filtering by it).
        """
        parts = []

        # Type
        if filters.get("type"):
            parts.append(f"Type: {'Rent' if filters['type'] == 'rent' else 'Buy'}")

        # Districts
        districts = filters.get("districts")
        parts.append(f"Districts: {', '.join(districts) if districts else 'Any'}")

        # Max price
        max_price = filters.get("max_price")
        if max_price:
            parts.append(f"Max: ${max_price}")

        # Rooms
        rooms = filters.get("rooms")
        if rooms:
            parts.append(f"Rooms: {', '.join(['4+' if r == 4 else str(r) for r in rooms])}")

        # Pets (only include if True, i.e., user requested pet-friendly)
        pets = filters.get("pets_allowed")
        if pets is True:
            parts.append("Pets allowed ✅")

        # Features
        features = filters.get("features")
        if features:
            parts.append(f"Features: {', '.join(features)}")

        return " | ".join(parts)  # compact one-line summary

    filters_summary = format_filters(filters)

    if total == 0:
        # Provide a button to start a new search
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Start a new search", callback_data="newsearch")]
        ])
        await q_or_msg.edit_message_text(
            f"Your search:\n{filters_summary}\n\nNo posts match your criteria. Try a different search.",
            reply_markup=keyboard
        )
        return STATE_CONFIRM  # keep conversation active so button works

    # Paginate results
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_posts = results[start:end]

    lines = [f"Found {total} posts — showing {start+1}-{min(end, total)}"]
    for p in page_posts:
        link = f"https://t.me/{CHANNEL_USERNAME}/{p.source_id}"
        lines.append(f"{p.district or ''} • {p.rooms or '?'} Rooms • ${p.price or '?'} • {p.address or ''}\n{link}")

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
    app = ApplicationBuilder().token(BOT_TOKEN).build()
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

def format_filters_for_user(filters: dict) -> str:
    """
    Convert filters dict into a human-readable summary string.
    """
    lines = []

    # Type
    if filters.get("type"):
        lines.append(f"Type: {'Rent' if filters['type'] == 'rent' else 'Buy'}")

    # Districts
    districts = filters.get("districts")
    if districts is None:
        lines.append("Districts: Any")
    else:
        lines.append(f"Districts: {', '.join(districts)}")

    # Max price
    if filters.get("max_price"):
        lines.append(f"Max price: ${filters['max_price']}")
    else:
        lines.append("Max price: Any")

    # Rooms
    rooms = filters.get("rooms")
    if rooms:
        room_strs = ["4+" if r == 4 else str(r) for r in rooms]
        lines.append(f"Rooms: {', '.join(room_strs)}")
    else:
        lines.append("Rooms: Any")

    # Pets (only for rent)
    pets = filters.get("pets_allowed")
    if pets is not None:
        lines.append(f"Pets allowed: {'Yes' if pets else 'No'}")

    # Features
    feats = filters.get("features")
    if feats:
        lines.append(f"Features: {', '.join(feats)}")
    else:
        lines.append("Features: Any")

    return "\n".join(lines)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Set BOT_TOKEN in env or .env file")
        raise SystemExit(1)
    app = build_app()
    app.run_polling()
