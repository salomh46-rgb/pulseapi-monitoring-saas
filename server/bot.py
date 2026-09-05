import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_URL = os.getenv("PULSEAPI_SERVER_URL", "http://127.0.0.1:8000")

dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    text = (
        f"⚡ <b>PulseAPI Monitoring SaaS Botiga Xush Kelibsiz!</b>\n\n"
        f"Sizning Chat ID raqamingiz: <code>{chat_id}</code>\n\n"
        f"Ushbu ID raqamni PulseAPI Dashboardidagi monitorlaringizga kiritsangiz, "
        f"serveringiz yiqilganda yoki xatolik berganda darhol shu yerga tezkor ogohlantirish (Alert) yuboriladi.\n\n"
        f"<b>Buyruqlar:</b>\n"
        f"• /status — Barcha serverlaringiz holati\n"
        f"• /ping — Hozir barcha serverlarni tekshirish"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 PulseAPI Dashboard", url="https://javohirbek-portfolio.vercel.app/")],
        [InlineKeyboardButton(text="🔄 Tizim Holatini Tekshirish", callback_data="check_status")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{API_URL}/api/status-page", timeout=5.0)
            data = res.json()
            monitors = data.get("monitors", [])
            if not monitors:
                await message.answer("⚠️ Hozircha faol monitorlar mavjud emas.")
                return

            lines = ["📊 <b>PulseAPI Tizim Holati:</b>\n"]
            for m in monitors:
                icon = "🟢" if m["status"] == "UP" else "🔴"
                lines.append(f"{icon} <b>{m['name']}</b>: {m['status']} ({m['last_latency_ms']}ms) — {m['uptime_pct']}% Uptime")

            await message.answer("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Server bilan ulanishda xatolik: {e}")

@dp.callback_query(lambda c: c.data == "check_status")
async def process_callback_status(callback_query: types.CallbackQuery):
    await callback_query.answer("Holat yangilanmoqda...")
    await cmd_status(callback_query.message)

async def main():
    if not BOT_TOKEN:
        print("Iltimos, TELEGRAM_BOT_TOKEN muhit o'zgaruvchisini kiriting!")
        return
    bot = Bot(token=BOT_TOKEN)
    print("PulseAPI Telegram Alert Boti ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
