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

TIKTOK_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)/\S+",
    re.IGNORECASE,
)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


async def download_video(url, folder):
    output = str(folder / "%(title)s.%(ext)s")

    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-o",
        output,
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    await process.communicate()

    files = list(folder.glob("*"))
    return files[0]


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Отправь ссылку на TikTok")


@dp.message()
async def handle(message: Message):

    match = TIKTOK_RE.search(message.text)

    if not match:
        return

    url = match.group(0)

    status = await message.answer("Скачиваю...")

    temp = Path(tempfile.mkdtemp())

    try:

        file = await download_video(url, temp)

        await message.answer_video(FSInputFile(file))

        await status.delete()

    except Exception as e:

        await status.edit_text(str(e))

    finally:

        shutil.rmtree(temp, ignore_errors=True)


async def webhook(request):

    data = await request.json()

    update = Update.model_validate(data)

    await dp.feed_update(bot, update)

    return web.Response(text="ok")


async def startup(app):

    url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"

    await bot.set_webhook(url)

    print("Webhook:", url)


app = web.Application()

app.router.add_post(f"/webhook/{WEBHOOK_SECRET}", webhook)

app.router.add_get("/", lambda r: web.Response(text="Bot running"))

app.on_startup.append(startup)

if __name__ == "__main__":

    web.run_app(app, host="0.0.0.0", port=PORT)
