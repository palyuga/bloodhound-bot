import logging
import re
from datetime import timezone
from typing import Optional

from telethon.tl.types import Message
from .models import Post, PostType

logger = logging.getLogger("bloodhound.parser")

# ---------------------
# Regexes
# ---------------------
# Matches text until the first space, hash, or emoji
TEXT_BEFORE_EMOJI = r"[^\s#\U0001F300-\U0001FAFF\U00002600-\U000027BF]+"

# These can be only on the first non-empty line
RE_HEADER_DISTRICT = re.compile(rf"^\s*#({TEXT_BEFORE_EMOJI})")
RE_HEADER_METRO = re.compile(rf"🚇\s*#({TEXT_BEFORE_EMOJI})")

RE_ADDRESS = re.compile(rf"📍\s*({TEXT_BEFORE_EMOJI}[^#\n]{{0,120}})")
RE_PRICE = re.compile(r"💰.*?\$?\s*([0-9][0-9\.,]*)\$?", re.IGNORECASE)
RE_SIZE = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*(?:Sq\.m|sqm|m2)", re.IGNORECASE)
RE_ROOMS = re.compile(r"#(\d+)Bed", re.IGNORECASE)
RE_RENT = re.compile(r"#Rent", re.IGNORECASE)
RE_SELL = re.compile(r"#(Sell|Sale)", re.IGNORECASE)
RE_RENTED = re.compile(r"#Rented", re.IGNORECASE)
RE_FLOOR = re.compile(r"(\d{1,2})(?:/(\d{1,2}))?\s*Floor", re.IGNORECASE)
RE_PETS = re.compile(r"#(Allowed|NotAllowed|ByAgreement)", re.IGNORECASE)
RE_FEATURES = re.compile(r"✅\s*#([A-Za-z0-9]+)", re.IGNORECASE) # Features like #Oven, #Balcony

MIN_REQUIRED_STRUCTURED_FIELDS = 3  # guard: require at least N of tags to be present

# Normalization maps
DISTRICT_MAP = {
    "dighomi": "Digomi",
    "dididighomi": "DidiDigomi",
}

METRO_MAP = {
    "libertysquare": "LibertySquare",
    "ahmetelitheatre": "AkhmeteliTheatre",
    "technicaluniversity": "TCUniversity"
}

PETS_MAPPING = {
    "allowed": "allowed",
    "notallowed": "not_allowed",
    "byagreement": "by_agreement"
}

# ---------------------
# parse header
# ---------------------
def parse_header_first_line(text: str):
    """Extract district, metro, address from the FIRST non-empty line only."""
    first_line = _first_non_empty_line(text)
    if not first_line:
        return None, None, None

    # district only if it appears at start of the line as a tag
    d_m = RE_HEADER_DISTRICT.match(first_line)
    district = d_m.group(1) if d_m else None

    # metro anywhere in the header line (emoji + tag)
    m_m = RE_HEADER_METRO.search(first_line)
    metro = m_m.group(1) if m_m else None

    logger.debug("Header parsed: district=%s metro=%s", district, metro)
    return district, metro


# ---------------------
# Main parser
# ---------------------
def parse_post(message: Message | object, channel_id: str) -> Optional[Post]:
    """
    Parse a Telegram Message (or object with `.message` and `.id`)
    and return a Post() instance (SQLAlchemy model) or None if irrelevant.
    - extracts district/metro/address only from first non-empty line
    - ignores posts containing #Rented
    - requires at least MIN_REQUIRED_STRUCTURED_FIELDS present among key attributes
    """
    # get raw text
    text = None
    msg_id = None
    # support both telethon Message and a SimpleNamespace used in tests
    if hasattr(message, "message"):
        text = message.message or ""
    else:
        # fallback if message is a raw string
        text = str(message)

    if hasattr(message, "id"):
        msg_id = getattr(message, "id")

    if not text:
        logger.debug("Empty message text, skip")
        return None

    # ignore rented notifications
    if RE_RENTED.search(text):
        logger.debug("Skipping #Rented post (channel=%s id=%s)", channel_id, msg_id)
        return None

    # type detection
    post_type = None
    if RE_RENT.search(text):
        post_type = PostType.rent
    elif RE_SELL.search(text):
        post_type = PostType.sell
    else:
        # If there's no explicit #Rent/#Sell tag, skip it (safer)
        logger.debug("No #Rent/#Sell tag found — skip post (channel=%s id=%s)", channel_id, msg_id)
        return None

    # header parsing (first line only)
    district, metro = parse_header_first_line(text)
    district = normalize_district(district)
    metro = normalize_metro(metro)

    # parse body
    address = None
    if m := RE_ADDRESS.search(text):
        address = m.group(1).strip()

    floor = None
    total_floors = None
    if m := RE_FLOOR.search(text):
        floor = _clean_int(m.group(1))
        total_floors = _clean_int(m.group(2))


    pets = None
    if m := RE_PETS.search(text):
        pets = PETS_MAPPING.get(m.group(1).lower())

    price = None
    if m := RE_PRICE.findall(text):
        # take the last one (actual for discounts)
        price = _clean_int(m[-1])

    size_sqm = None
    if m := RE_SIZE.search(text):
        size_sqm = _clean_float(m.group(1))

    rooms = None
    if m := RE_ROOMS.search(text):
        rooms = _clean_int(m.group(1))

    features = []
    for m in RE_FEATURES.findall(text):
        features.append(m.strip())

    # guard: require at least some structured info
    key_attrs = [district, price, rooms, size_sqm, address]
    present = sum(1 for v in key_attrs if v is not None)
    if present < MIN_REQUIRED_STRUCTURED_FIELDS:
        logger.warning("Skipping incomplete post (channel=%s id=%s) — found %d of required fields",
                       channel_id, msg_id, present)
        return None

    # Build Post instance (not yet persisted)
    try:
        post = Post(
            channel_id=str(channel_id),
            source_id=int(msg_id) if msg_id is not None else None,
            type=post_type,
            district=district,
            metro=metro,
            address=address,
            rooms=rooms,
            size_sqm=size_sqm,
            floor=floor,
            price=price,
            pets=pets,
            features=features,
            tenants=None,
            deleted=False,
        )
    except Exception as e:
        logger.exception("Failed to construct Post object: %s", e)
        return None

    logger.info("Parsed post channel=%s id=%s district=%s price=%s rooms=%s size=%s",
                channel_id, msg_id, district, price, rooms, size_sqm)
    return post

async def sync_channel(client, session, channel, cutoff_date, reset: bool = False):
    """
    Keep sync_channel behaviour same as before — iterate messages,
    parse via parse_post(), upsert into DB and mark missing as deleted.
    """
    # ensure cutoff_date is UTC aware, so it is compatible with message.date
    cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)

    entity = await client.get_entity(channel)
    channel_id = str(entity.id)
    logger.info("Syncing channel %s (entity id=%s) since %s", channel, channel_id, cutoff_date)

    if reset:
        deleted_count = session.query(Post).filter_by(channel_id=channel_id).delete()
        session.commit()
        logger.info("Reset enabled: deleted %d existing posts for channel %s", deleted_count, channel_id)

    seen_ids = set()
    async for message in client.iter_messages(entity):

        if not getattr(message, "message", None) or not message.text:
            continue

        # stop once we've reached older messages
        if message.date < cutoff_date:
            break

        parsed = parse_post(message, channel_id)
        seen_ids.add(message.id)
        if parsed is None:
            continue

        # Upsert: try getting by PK (channel_id, source_id)
        existing = session.get(Post, (parsed.channel_id, parsed.source_id))
        if existing:
            # update fields
            existing.type = parsed.type
            existing.district = parsed.district
            existing.metro = parsed.metro
            existing.address = parsed.address
            existing.rooms = parsed.rooms
            existing.size_sqm = parsed.size_sqm
            existing.price = parsed.price
            existing.deleted = False
            logger.debug("Updated post %s:%s", parsed.channel_id, parsed.source_id)
        else:
            session.add(parsed)
            logger.debug("Inserted post %s:%s", parsed.channel_id, parsed.source_id)

    # mark deleted
    db_rows = session.query(Post).filter_by(channel_id=channel_id, deleted=False).all()
    db_ids = {r.source_id for r in db_rows if r.source_id is not None}
    to_mark = db_ids - seen_ids
    if to_mark:
        session.query(Post).filter(Post.channel_id == channel_id, Post.source_id.in_(to_mark))\
            .update({"deleted": True}, synchronize_session=False)
        logger.info("Marked %d posts as deleted for channel %s", len(to_mark), channel_id)
    session.commit()

def _clean_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None

def _first_non_empty_line(text: str) -> Optional[str]:
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return None

def _clean_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    # Keep digits and optional dot
    match = re.search(r"\d+(?:\.\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None

def normalize_district(d: str) -> str | None:
    if not d:
        return None
    d = d.strip().replace(" ", "")
    return DISTRICT_MAP.get(d.lower(), d)

def normalize_metro(m: str) -> str | None:
    if not m:
        return None
    m = m.strip().replace(" ", "")
    return METRO_MAP.get(m.lower(), m)

def _clean_price(s: str) -> int:
    """Remove commas, dots, spaces and convert to int"""
    return int(s.replace(",", "").replace(".", "").replace(" ", ""))