import asyncio
import json
import logging
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. Railway'da Variables bo'limiga BOT_TOKEN qo'shing "
        "(yoki lokal ishga tushirishda muhit o'zgaruvchisi sifatida bering)."
    )

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
    ALL_QUESTIONS = json.load(f)

TOTAL_QUESTIONS = len(ALL_QUESTIONS)
LETTERS = ["A", "B", "C", "D", "E"]  # savolda nechta variant bo'lsa, shunchasi ishlatiladi

# Bloklar: (nomi, boshlanish_index, tugash_index) - 0-based, tugash exclusive
BLOCK_SIZE = 20
BLOCKS = {}
_start = 0
_num = 1
while _start < TOTAL_QUESTIONS:
    _end = min(_start + BLOCK_SIZE, TOTAL_QUESTIONS)
    BLOCKS[f"block{_num}"] = (_start, _end)
    _start = _end
    _num += 1

# Har bir user uchun joriy test holati (RAM'da saqlanadi, bot qayta ishga
# tushganda tozalanadi - agar natijalarni doimiy saqlash kerak bo'lsa,
# bu yerga SQLite/Postgres qo'shish mumkin)
sessions: dict[int, dict] = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def build_keyboard(pos: int, num_options: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=LETTERS[i], callback_data=f"ans:{pos}:{i}")
        for i in range(num_options)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def format_question_text(session: dict) -> str:
    pos = session["pos"]
    q = ALL_QUESTIONS[session["indices"][pos]]
    lines = [f"❓ {pos + 1}/{session['total']}", "", q["question"], ""]
    for i, opt in enumerate(q["options"]):
        lines.append(f"{LETTERS[i]}) {opt}")
    return "\n".join(lines)


async def send_current_question(message: Message, session: dict):
    text = format_question_text(session)
    q = ALL_QUESTIONS[session["indices"][session["pos"]]]
    kb = build_keyboard(session["pos"], len(q["options"]))
    await message.answer(text, reply_markup=kb)


def start_session(user_id: int, indices: list[int], label: str):
    sessions[user_id] = {
        "indices": indices,
        "pos": 0,
        "correct": 0,
        "total": len(indices),
        "label": label,
    }


HELP_TEXT = (
    "🎓 \"Jahon iqtisodiyoti\" fanidan test!\n\n"
    f"Jami savollar bazasi: {TOTAL_QUESTIONS} ta\n\n"
    "📦 Bloklar bo'yicha:\n"
)
for name, (s, e) in BLOCKS.items():
    HELP_TEXT += f"/{name} — {s + 1}-{e} savollar\n"
HELP_TEXT += (
    "\n🎲 /random20 — 20 ta savol tasodifiy tanlanadi\n"
    "📋 /all — barcha savollar ketma-ket\n\n"
    "/stop — testni to'xtatish"
)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(message: Message):
    sessions.pop(message.from_user.id, None)
    await message.answer(HELP_TEXT)


async def cmd_block(message: Message, block_name: str):
    start, end = BLOCKS[block_name]
    indices = list(range(start, end))
    start_session(message.from_user.id, indices, block_name)
    count = len(indices)
    await message.answer(
        f"✅ Blok {start + 1}-{end} ({count} ta savol). Boshlandi! 👍"
    )
    await send_current_question(message, sessions[message.from_user.id])


def make_block_handler(block_name: str):
    async def handler(message: Message):
        await cmd_block(message, block_name)

    return handler


for name in BLOCKS:
    dp.message(Command(name))(make_block_handler(name))


@dp.message(Command("random20"))
async def cmd_random20(message: Message):
    n = min(20, TOTAL_QUESTIONS)
    indices = random.sample(range(TOTAL_QUESTIONS), n)
    start_session(message.from_user.id, indices, "random20")
    await message.answer(f"✅ {n} ta savol tasodifiy tanlandi. Boshlandi! 👍")
    await send_current_question(message, sessions[message.from_user.id])


@dp.message(Command("all"))
async def cmd_all(message: Message):
    indices = list(range(TOTAL_QUESTIONS))
    start_session(message.from_user.id, indices, "all")
    await message.answer(
        f"✅ Barcha savollar ({TOTAL_QUESTIONS} ta). Boshlandi! 👍"
    )
    await send_current_question(message, sessions[message.from_user.id])


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    if sessions.pop(message.from_user.id, None) is not None:
        await message.answer("⏹ Test to'xtatildi. Qayta boshlash uchun /start yuboring.")
    else:
        await message.answer("Hozircha faol test yo'q. Boshlash uchun /start yuboring.")


@dp.callback_query(F.data.startswith("ans:"))
async def on_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = sessions.get(user_id)

    _, pos_str, choice_str = callback.data.split(":")
    pos = int(pos_str)
    choice = int(choice_str)

    if session is None or session["pos"] != pos:
        # Eski yoki tugagan test tugmasi bosilgan
        await callback.answer("Bu savol eskirgan.", show_alert=False)
        return

    q = ALL_QUESTIONS[session["indices"][pos]]
    is_correct = choice == q["correct"]

    if is_correct:
        session["correct"] += 1
        result_line = "✅ To'g'ri!"
    else:
        correct_text = q["options"][q["correct"]]
        correct_letter = LETTERS[q["correct"]]
        result_line = f"❌ Noto'g'ri.\nTo'g'ri javob: {correct_letter}) {correct_text}"

    base_text = format_question_text(session)
    try:
        await callback.message.edit_text(f"{base_text}\n\n{result_line}")
    except Exception:
        pass
    await callback.answer()

    session["pos"] += 1
    if session["pos"] >= session["total"]:
        correct = session["correct"]
        total = session["total"]
        percent = round(correct / total * 100) if total else 0
        await callback.message.answer(
            "🎉 Test yakunlandi!\n\n"
            f"✅ To'g'ri javoblar: {correct}/{total}\n"
            f"📊 Natija: {percent}%\n\n"
            "Qayta boshlash uchun /start buyrug'ini yuboring."
        )
        sessions.pop(user_id, None)
    else:
        await send_current_question(callback.message, session)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
