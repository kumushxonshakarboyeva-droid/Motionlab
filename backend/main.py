import hashlib
import hmac
import json
import os
import re
import time
from typing import List

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "MyMotionLab_bot").strip().lstrip("@")
MAX_INIT_AGE = int(os.getenv("MAX_INIT_AGE", "86400"))

if not BOT_TOKEN:
    # The server can still boot for health checks, but Telegram actions will fail clearly.
    print("WARNING: BOT_TOKEN is not configured.")

app = FastAPI(title="MotionLab Telegram Sticker Backend", version="1.0.0")

# For production, replace "*" with your exact GitHub Pages origin.
ALLOWED_ORIGINS = [
    x.strip() for x in os.getenv(
        "ALLOWED_ORIGINS",
        "https://kumushxonshakarboyeva-droid.github.io"
    ).split(",") if x.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


def telegram_secret_key() -> bytes:
    return hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()


def validate_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured on the server.")
    if not init_data:
        raise HTTPException(401, "Telegram initData is missing.")

    pairs = {}
    received_hash = None

    from urllib.parse import parse_qsl
    for key, value in parse_qsl(init_data, keep_blank_values=True):
        if key == "hash":
            received_hash = value
        else:
            pairs[key] = value

    if not received_hash:
        raise HTTPException(401, "Telegram initData hash is missing.")

    data_check_string = "\n".join(
        f"{key}={pairs[key]}" for key in sorted(pairs)
    )
    calculated_hash = hmac.new(
        telegram_secret_key(),
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(401, "Invalid Telegram initData.")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid auth_date.")

    if auth_date <= 0 or time.time() - auth_date > MAX_INIT_AGE:
        raise HTTPException(401, "Telegram initData has expired.")

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(401, "Telegram user data is missing.")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(401, "Invalid Telegram user data.")

    if not user.get("id"):
        raise HTTPException(401, "Telegram user ID is missing.")

    return user


def normalize_pack_name(raw_name: str) -> str:
    # Telegram bot-created pack names must end with _by_<bot_username>.
    raw = (raw_name or "").strip()
    raw = re.sub(r"[^A-Za-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")

    if not raw:
        raw = "motionlab"

    suffix = f"_by_{BOT_USERNAME}"
    if not raw.lower().endswith(suffix.lower()):
        raw = raw[:64 - len(suffix)].rstrip("_") + suffix

    if not re.match(r"^[A-Za-z]", raw):
        raw = "motionlab" + raw

    if len(raw) > 64:
        raw = raw[:64]

    return raw


async def telegram_api(method: str, data=None, files=None):
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN is not configured on the server.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, data=data, files=files)

    try:
        payload = response.json()
    except Exception:
        raise HTTPException(502, "Telegram returned an invalid response.")

    if not payload.get("ok"):
        description = payload.get("description", "Telegram API error")
        raise HTTPException(400, description)

    return payload["result"]


@app.get("/")
async def root():
    return {"ok": True, "service": "MotionLab Telegram Sticker Backend"}


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/create-sticker-pack")
async def create_sticker_pack(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    title: str = Form(...),
    pack_name: str = Form(...),
    emoji: str = Form("✨"),
    stickers: List[UploadFile] = File(...),
):
    user = validate_init_data(init_data)

    title = title.strip()
    if not 1 <= len(title) <= 64:
        raise HTTPException(400, "Pack title must be 1–64 characters.")

    if not emoji.strip():
        emoji = "✨"

    if len(stickers) < 1:
        raise HTTPException(400, "Add at least one sticker.")

    if len(stickers) > 50:
        raise HTTPException(400, "Maximum 50 stickers can be added when creating a pack.")

    pack_short_name = normalize_pack_name(pack_name)

    # Read and validate the uploaded WEBM files before sending anything to Telegram.
    prepared = []
    for i, upload in enumerate(stickers):
        filename = upload.filename or f"sticker_{i}.webm"
        if not filename.lower().endswith(".webm"):
            raise HTTPException(400, f"{filename}: only WEBM video stickers are supported.")

        content = await upload.read()
        if not content:
            raise HTTPException(400, f"{filename}: file is empty.")

        # Telegram's documented video-sticker limit is 256 KB.
        if len(content) > 256 * 1024:
            raise HTTPException(400, f"{filename}: exceeds Telegram's 256 KB video-sticker limit.")

        prepared.append((f"sticker{i}", filename, content))

    sticker_items = []
    for field_name, _, _ in prepared:
        sticker_items.append({
            "sticker": f"attach://{field_name}",
            "format": "video",
            "emoji_list": [emoji[:20]],
        })

    # Multipart fields for createNewStickerSet.
    multipart_files = []
    for field_name, filename, content in prepared:
        multipart_files.append(
            (field_name, (filename, content, "video/webm"))
        )

    form_data = {
        "user_id": str(user["id"]),
        "name": pack_short_name,
        "title": title,
        "sticker_type": "regular",
        "stickers": json.dumps(sticker_items, ensure_ascii=False),
    }

    result = await telegram_api(
        "createNewStickerSet",
        data=form_data,
        files=multipart_files,
    )

    return {
        "ok": True,
        "pack_name": pack_short_name,
        "pack_url": f"https://t.me/addstickers/{pack_short_name}",
        "user_id": user["id"],
        "telegram_result": result,
    }
