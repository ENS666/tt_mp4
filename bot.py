import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message, Update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")
PORT = int(os.getenv("PORT", "10000"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "49"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "")

SUPPORTED_URL_RE = re.compile(
    r"https?://\S+",
    re.IGNORECASE,
)

SUPPORTED_DOMAINS = (
    "tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "www.instagram.com",
    "pinterest.com",
    "pin.it",
)

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
}


bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def extract_supported_url(text: str) -> str | None:
    if not text:
        return None

    matches = SUPPORTED_URL_RE.findall(text)
    for url in matches:
        lower = url.lower()
        if any(domain in lower for domain in SUPPORTED_DOMAINS):
            return url
    return None


async def run_cmd(*args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="ignore"),
        stderr.decode("utf-8", errors="ignore"),
    )


def find_downloaded_file(folder: Path) -> Path:
    files = sorted(
        [p for p in folder.rglob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    media_files = [p for p in files if p.suffix.lower() in VIDEO_EXTENSIONS]

    if not media_files:
        raise RuntimeError("Не удалось найти скачанный видеофайл")

    return media_files[0]


async def download_video(url: str, folder: Path) -> Path:
    output_template = str(folder / "%(title).80s [%(id)s].%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-o",
        output_template,
        "--merge-output-format",
        "mp4",
        url,
    ]

    if COOKIES_FILE:
        cmd.extend(["--cookies", COOKIES_FILE])

    code, stdout, stderr = await run_cmd(*cmd)

    logger.info("yt-dlp stdout: %s", stdout)
    logger.info("yt-dlp stderr: %s", stderr)

    if code != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or "yt-dlp завершился с ошибкой")

    return find_downloaded_file(folder)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Отправь ссылку на видео.\n\n"
        "Поддерживаются:\n"
        "• TikTok\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Pinterest"
    )


@dp.message()
async def handle(message: Message):
    text = message.text or message.caption or ""
    url = extract_supported_url(text)

    if not url:
        await message.answer(
            "Пришли ссылку на видео с TikTok, YouTube, Instagram или Pinterest."
        )
        return

    status = await message.answer("Скачиваю видео...")

    temp = Path(tempfile.mkdtemp(prefix="media_bot_"))

    try:
        file_path = await download_video(url, temp)

        size_mb = file_path.stat().st_size / (1024 * 1024)

        if size_mb > MAX_FILE_SIZE_MB:
            await status.edit_text(
                f"Видео скачалось, но весит {size_mb:.1f} МБ, это больше лимита {MAX_FILE_SIZE_MB} МБ."
            )
            return

        await message.answer_video(
            video=FSInputFile(file_path),
            caption=f"Готово: {file_path.name}",
        )

        await status.delete()

    except Exception as e:
        logger.exception("Download error")
        await status.edit_text(f"Не удалось скачать видео: {e}")

    finally:
        shutil.rmtree(temp, ignore_errors=True)


async def webhook(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")


async def startup(app):
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")

    if not BASE_URL:
        raise RuntimeError("Не задан BASE_URL")

    url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(url)
    logger.info("Webhook: %s", url)


async def shutdown(app):
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()


app = web.Application()
app.router.add_post(f"/webhook/{WEBHOOK_SECRET}", webhook)
app.router.add_get("/", lambda r: web.Response(text="Bot running"))
app.on_startup.append(startup)
app.on_shutdown.append(shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
