import hashlib
import hmac
import json
import os
import re
import time
from typing import List
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "MyMotionLab_bot").strip().lstrip("@")
MAX_INIT_AGE = int(os.getenv("MAX_INIT_AGE", "86400"))

if not BOT_TOKEN:
    print("WARNING: BOT_TOKEN is not configured.")

app = FastAPI(
    title="MotionLab Telegram Sticker Backend",
    version="2.0.0",
)

# GitHub Pages origin. If your Pages URL uses another GitHub account,
# set ALLOWED_ORIGINS in Render.
ALLOWED_ORIGINS = [
    x.strip()
    for x in os.getenv(
        "ALLOWED_ORIGINS",
        "https://kumushxonshakarboyeva-droid.github.io",
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================
# TELEGRAM WEB APP AUTH
# ============================================================

def telegram_secret_key() -> bytes:
    return hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def validate_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="BOT_TOKEN is not configured on the server.",
        )

    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="Telegram initData is missing. Open MotionLab from Telegram.",
        )

    pairs = {}
    received_hash = None

    for key, value in parse_qsl(init_data, keep_blank_values=True):
        if key == "hash":
            received_hash = value
        else:
            pairs[key] = value

    if not received_hash:
        raise HTTPException(
            status_code=401,
            detail="Telegram initData hash is missing.",
        )

    data_check_string = "\n".join(
        f"{key}={pairs[key]}"
        for key in sorted(pairs)
    )

    calculated_hash = hmac.new(
        telegram_secret_key(),
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram initData.",
        )

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram auth_date.",
        )

    if auth_date <= 0:
        raise HTTPException(
            status_code=401,
            detail="Telegram auth_date is missing.",
        )

    if time.time() - auth_date > MAX_INIT_AGE:
        raise HTTPException(
            status_code=401,
            detail="Telegram initData has expired. Reopen the Mini App.",
        )

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(
            status_code=401,
            detail="Telegram user data is missing.",
        )

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram user data.",
        )

    if not user.get("id"):
        raise HTTPException(
            status_code=401,
            detail="Telegram user ID is missing.",
        )

    return user


# ============================================================
# STICKER PACK NAME
# ============================================================

def normalize_pack_name(raw_name: str) -> str:
    """
    Telegram bot-created sticker set names must:
      - be 1..64 characters
      - contain English letters, digits and underscores
      - start with a letter
      - not contain consecutive underscores
      - end with _by_<bot_username>
    """

    raw = (raw_name or "").strip()

    # Keep only Telegram-safe characters.
    raw = re.sub(r"[^A-Za-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")

    if not raw:
        raw = "motionlab"

    # Must start with a letter.
    if not raw[0].isalpha():
        raw = "motionlab_" + raw

    suffix = f"_by_{BOT_USERNAME}"

    # Remove an already supplied suffix first.
    if raw.lower().endswith(suffix.lower()):
        raw = raw[: -len(suffix)].rstrip("_")

    if not raw:
        raw = "motionlab"

    # Leave room for the required suffix.
    max_base_length = 64 - len(suffix)
    raw = raw[:max_base_length].rstrip("_")

    if not raw:
        raw = "motionlab"

    # Final name. Telegram accepts bot username case-insensitively.
    final_name = f"{raw}{suffix}"

    if len(final_name) > 64:
        raise HTTPException(
            status_code=400,
            detail="Sticker pack name is too long.",
        )

    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", final_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid sticker pack name.",
        )

    if "__" in final_name:
        raise HTTPException(
            status_code=400,
            detail="Sticker pack name cannot contain consecutive underscores.",
        )

    return final_name


# ============================================================
# TELEGRAM API
# ============================================================

async def telegram_api(method: str, data=None, files=None):
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="BOT_TOKEN is not configured on the server.",
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=20.0)
        ) as client:
            response = await client.post(
                url,
                data=data,
                files=files,
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Telegram request timed out. Please try again.",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to Telegram: {exc}",
        )

    try:
        payload = response.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Telegram returned an invalid response.",
        )

    if not payload.get("ok"):
        description = payload.get(
            "description",
            "Telegram API error",
        )

        # Make the most common pack errors understandable in the Mini App.
        if "SHORT_NAME_OCCUPIED" in description.upper():
            description = (
                "This sticker pack name is already taken. "
                "Change the Pack name and try again."
            )
        elif "STICKER_VIDEO_BIG" in description.upper():
            description = (
                "A sticker is larger than Telegram's 256 KB limit."
            )
        elif "STICKER_VIDEO_NOWEBM" in description.upper():
            description = (
                "Telegram did not receive a valid WEBM video sticker. "
                "Export again with Telegram Sticker selected."
            )
        elif "STICKER_VIDEO_NODOC" in description.upper():
            description = (
                "Telegram could not read the uploaded video sticker."
            )
        elif "STICKER_GIF_DIMENSIONS" in description.upper():
            description = (
                "Sticker dimensions are invalid. Use 512×512."
            )
        elif "STICKER_EMOJI_INVALID" in description.upper():
            description = (
                "The sticker emoji is invalid. Use a normal emoji such as ✨."
            )

        raise HTTPException(
            status_code=400,
            detail=description,
        )

    return payload["result"]


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "MotionLab Telegram Sticker Backend",
        "version": "2.0.0",
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "telegram_configured": bool(BOT_TOKEN),
        "bot_username": BOT_USERNAME,
    }


# ============================================================
# CREATE TELEGRAM STICKER PACK
# ============================================================

@app.post("/api/create-sticker-pack")
async def create_sticker_pack(
    init_data: str = Header(
        default="",
        alias="X-Telegram-Init-Data",
    ),
    title: str = Form(...),
    pack_name: str = Form(...),
    emoji: str = Form("✨"),
    stickers: List[UploadFile] = File(...),
):
    # 1. Verify the Mini App really came from Telegram.
    user = validate_init_data(init_data)

    # 2. Validate pack title.
    title = title.strip()

    if not 1 <= len(title) <= 64:
        raise HTTPException(
            status_code=400,
            detail="Pack title must be 1–64 characters.",
        )

    # 3. Validate emoji.
    emoji = (emoji or "").strip()

    if not emoji:
        emoji = "✨"

    if len(emoji) > 20:
        emoji = emoji[:20]

    # 4. Validate number of stickers.
    if not stickers:
        raise HTTPException(
            status_code=400,
            detail="Add at least one sticker first.",
        )

    # Telegram currently allows up to 120 stickers in a regular set.
    if len(stickers) > 120:
        raise HTTPException(
            status_code=400,
            detail="Maximum 120 stickers can be added to one pack.",
        )

    # 5. Normalize the short name.
    pack_short_name = normalize_pack_name(pack_name)

    # 6. Read and validate every WebM before calling Telegram.
    prepared = []

    for i, upload in enumerate(stickers):
        filename = upload.filename or f"sticker_{i + 1}.webm"

        if not filename.lower().endswith(".webm"):
            raise HTTPException(
                status_code=400,
                detail=f"{filename}: only WEBM stickers are supported.",
            )

        content = await upload.read()

        if not content:
            raise HTTPException(
                status_code=400,
                detail=f"{filename}: file is empty.",
            )

        # Telegram video sticker limit.
        if len(content) > 256 * 1024:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{filename}: {len(content) / 1024:.0f} KB. "
                    "Telegram allows a maximum of 256 KB."
                ),
            )

        prepared.append(
            (
                f"sticker{i}",
                filename,
                content,
            )
        )

    # 7. Build Telegram InputSticker objects.
    #
    # Important:
    # format="video" is required for WEBM video stickers.
    sticker_items = []

    for field_name, _, _ in prepared:
        sticker_items.append(
            {
                "sticker": f"attach://{field_name}",
                "format": "video",
                "emoji_list": [emoji],
            }
        )

    # 8. Attach the actual WebM files.
    multipart_files = []

    for field_name, filename, content in prepared:
        multipart_files.append(
            (
                field_name,
                (
                    filename,
                    content,
                    "video/webm",
                ),
            )
        )

    # 9. Create the complete pack in one Telegram API call.
    form_data = {
        "user_id": str(user["id"]),
        "name": pack_short_name,
        "title": title,
        "sticker_type": "regular",
        "stickers": json.dumps(
            sticker_items,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }

    result = await telegram_api(
        "createNewStickerSet",
        data=form_data,
        files=multipart_files,
    )

    pack_url = (
        f"https://t.me/addstickers/{pack_short_name}"
    )

    return {
        "ok": True,
        "message": "Sticker Pack created successfully.",
        "pack_name": pack_short_name,
        "pack_url": pack_url,
        "title": title,
        "sticker_count": len(prepared),
        "user_id": user["id"],
        "telegram_result": result,
    }
