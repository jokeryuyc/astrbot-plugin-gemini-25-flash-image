import asyncio
import base64
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import aiohttp
import aiofiles

from astrbot.api import logger


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = PLUGIN_ROOT / "images"


def _now() -> datetime:
    return datetime.now()


async def cleanup_old_images(minutes: int = 15, images_dir: Path = IMAGES_DIR) -> None:
    try:
        if not images_dir.exists():
            return
        cutoff = _now() - timedelta(minutes=minutes)
        for p in images_dir.glob("gemini_image_*." + "*"):
            try:
                if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                    p.unlink(missing_ok=True)
                    logger.info(f"cleanup: removed old image {p}")
            except Exception as e:
                logger.debug(f"cleanup ignore {p}: {e}")
    except Exception as e:
        logger.warning(f"cleanup_old_images failed: {e}")


async def save_base64_image(b64_data: str, mime: str = "image/png", images_dir: Path = IMAGES_DIR) -> Optional[str]:
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
        await cleanup_old_images(images_dir=images_dir)

        # Handle possible data URI prefix
        if b64_data.startswith("data:image/"):
            header, b64_data = b64_data.split(",", 1)
            try:
                mime = header.split(":", 1)[1].split(";", 1)[0]
            except Exception:
                mime = "image/png"

        ext = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/webp": "webp",
        }.get(mime.lower(), "png")

        ts = _now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]
        path = images_dir / f"gemini_image_{ts}_{uid}.{ext}"

        data = base64.b64decode(b64_data)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        logger.info(f"saved image -> {path}")
        return str(path)
    except Exception as e:
        logger.error(f"save_base64_image failed: {e}")
        return None


def schedule_delete_file(path: str, delay_seconds: int = 15) -> None:
    async def _delete():
        try:
            await asyncio.sleep(max(0, delay_seconds))
            os.remove(path)
            logger.info(f"deleted image after send -> {path}")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug(f"delete file ignore: {e}")

    try:
        asyncio.create_task(_delete())
    except RuntimeError:
        # In case loop is not running
        logger.debug("event loop not running, skip async delete")


def _build_endpoint(api_base: str, api_version: str, model: str, api_key: str) -> str:
    # e.g. https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key=API_KEY
    return f"{api_base}/{api_version}/models/{model}:generateContent?key={api_key}"


def _parts_from_inputs(prompt: str, input_images: Optional[List[str]]) -> list:
    parts = []
    if prompt:
        parts.append({"text": prompt})
    for b64 in (input_images or []):
        # Best effort mime; most chat images are jpeg/png
        mime = "image/png"
        try:
            if b64.startswith("data:image/"):
                mime = b64.split(":", 1)[1].split(";", 1)[0]
        except Exception:
            pass
        parts.append({
            "inlineData": {
                "mimeType": mime,
                "data": b64.split(",", 1)[1] if b64.startswith("data:") else b64,
            }
        })
    return parts


def _find_image_base64_from_response(data: dict) -> Optional[tuple[str, str]]:
    # Return (base64_data, mime)
    try:
        candidates = data.get("candidates") or []
        for cand in candidates:
            content = (cand or {}).get("content") or {}
            for part in (content.get("parts") or []):
                inline = part.get("inlineData")
                if inline and isinstance(inline, dict):
                    mime = inline.get("mimeType") or "image/png"
                    b64 = inline.get("data")
                    if b64:
                        return b64, mime
                # Some variants embed data URI in text
                text = part.get("text")
                if isinstance(text, str) and text.startswith("data:image/"):
                    header, b64 = text.split(",", 1)
                    mime = header.split(":", 1)[1].split(";", 1)[0]
                    return b64, mime
    except Exception as e:
        logger.debug(f"parse response failed: {e}")
    return None


async def generate_image_google(
    prompt: str,
    api_keys: List[str],
    model: str = "gemini-2.5-flash-image-preview",
    api_base: str = "https://generativelanguage.googleapis.com",
    api_version: str = "v1beta",
    input_images: Optional[List[str]] = None,
    max_retries: int = 3,
    cleanup_minutes: int = 15,
) -> Optional[str]:
    """Call Gemini official API to generate or edit image.

    Returns local file path if success, else None.
    """

    if not api_keys:
        raise ValueError("api_keys is empty")

    timeout = aiohttp.ClientTimeout(total=120)

    for idx, key in enumerate(api_keys):
        endpoint = _build_endpoint(api_base, api_version, model, key)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": _parts_from_inputs(prompt, input_images),
                }
            ]
            # Note: omit generationConfig.responseMimeType; some endpoints disallow image mime here
        }

        for attempt in range(max(1, int(max_retries))):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(endpoint, json=payload) as resp:
                        text = await resp.text()
                        # Try to parse json if possible
                        data = None
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            data = None

                        if resp.status == 200 and isinstance(data, dict):
                            found = _find_image_base64_from_response(data)
                            if found:
                                b64, mime = found
                                path = await save_base64_image(b64, mime)
                                return path
                            else:
                                logger.info("Gemini API success but no image in response")
                                return None

                        # Quota / rate-limit -> rotate to next key
                        if resp.status in (429, 403):
                            msg = None
                            if isinstance(data, dict):
                                msg = (data.get("error") or {}).get("message")
                            logger.warning(f"key#{idx} quota/denied ({resp.status}): {msg or text}")
                            break

                        # Other errors -> retry
                        logger.warning(f"Gemini API error ({resp.status}): {text[:500]}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"network error key#{idx} try {attempt+1}/{max_retries}: {e}")
            except Exception as e:
                logger.warning(f"unexpected error key#{idx} try {attempt+1}/{max_retries}: {e}")

            # backoff: 2^attempt seconds up to 8s
            await asyncio.sleep(min(8, 2 ** attempt))

        # next key
        logger.info("rotating to next API key")

    logger.error("all api keys exhausted")
    # Cleanup older files opportunistically
    await cleanup_old_images(minutes=cleanup_minutes)
    return None
