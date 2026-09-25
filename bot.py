import json
import logging
import os
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "quiz_data.json")

with open(DATA_FILE, "r", encoding="utf-8") as f:
    RAW_QUESTIONS = json.load(f)

OPTION_LABELS = ["🅰️", "🅱️", "🅲️"]


def build_shuffled_quiz():
    """Return a fresh, shuffled copy of the quiz: question order AND option
    order are both randomized, so every attempt looks a little different."""
    quiz = []
    for q in RAW_QUESTIONS:
        indexed_options = list(enumerate(q["options"]))
        random.shuffle(indexed_options)
        new_correct_idx = next(
            i for i, (orig_i, _) in enumerate(indexed_options)
            if orig_i == q["correct_idx"]
        )
        quiz.append(
            {
                "question": q["question"],
                "options": [text for _, text in indexed_options],
                "correct_idx": new_correct_idx,
            }
        )
    random.shuffle(quiz)
    return quiz


def question_keyboard(question, question_idx, disabled=False):
    buttons = []
    for i, option_text in enumerate(question["options"]):
        label = f"{OPTION_LABELS[i]} {option_text}"
        callback_data = f"noop" if disabled else f"ans:{question_idx}:{i}"
        buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
    return InlineKeyboardMarkup(buttons)


def question_text(question, number, total):
    return f"❓ Savol {number}/{total}\n\n{question['question']}"


async def send_question(chat_id, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data["quiz"]
    idx = state["index"]
    quiz = state["questions"]
    q = quiz[idx]
    text = question_text(q, idx + 1, len(quiz))
    keyboard = question_keyboard(q, idx)
    msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    state["last_message_id"] = msg.message_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎯 Testni boshlash", callback_data="start_quiz")]]
    )
    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "Bu — \"Jahon iqtisodiyoti\" fanidan test botim.\n"
        f"Jami savollar soni: {len(RAW_QUESTIONS)} ta.\n\n"
        "Har safar savollar va javob variantlari aralashtiriladi, "
        "shuning uchun har bir urinish boshqacha bo'ladi.\n\n"
        "Boshlashga tayyor bo'lsangiz, tugmani bosing 👇",
        reply_markup=keyboard,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — botni ishga tushirish va testni boshlash\n"
        "/quiz — testni qaytadan boshlash\n"
        "/help — yordam"
    )


async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["quiz"] = {
        "questions": build_shuffled_quiz(),
        "index": 0,
        "score": 0,
        "last_message_id": None,
    }
    await query.edit_message_reply_markup(reply_markup=None)
    await send_question(query.message.chat_id, context)


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quiz"] = {
        "questions": build_shuffled_quiz(),
        "index": 0,
        "score": 0,
        "last_message_id": None,
    }
    await send_question(update.effective_chat.id, context)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    state = context.user_data.get("quiz")

    if not state:
        await query.answer("Iltimos, /start orqali testni qaytadan boshlang.", show_alert=True)
        return

    _, q_idx_str, chosen_idx_str = query.data.split(":")
    q_idx = int(q_idx_str)
    chosen_idx = int(chosen_idx_str)

    # Ignore taps on a question that's not the current one (stale buttons)
    if q_idx != state["index"]:
        await query.answer()
        return

    quiz = state["questions"]
    q = quiz[q_idx]
    correct_idx = q["correct_idx"]
    is_correct = chosen_idx == correct_idx

    if is_correct:
        state["score"] += 1
        await query.answer("✅ To'g'ri!")
    else:
        await query.answer("❌ Noto'g'ri")

    # Rebuild the text, marking the chosen and correct options
    lines = [question_text(q, q_idx + 1, len(quiz)), ""]
    for i, option_text in enumerate(q["options"]):
        prefix = OPTION_LABELS[i]
        suffix = ""
        if i == correct_idx:
            suffix = "  ✅"
        elif i == chosen_idx:
            suffix = "  ❌"
        lines.append(f"{prefix} {option_text}{suffix}")
    result_text = "\n".join(lines)

    is_last = state["index"] == len(quiz) - 1
    next_label = "🏁 Natijani ko'rish" if is_last else "➡️ Keyingi savol"
    next_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(next_label, callback_data="next")]]
    )

    await query.edit_message_text(result_text, reply_markup=next_keyboard)


async def next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    state = context.user_data.get("quiz")
    if not state:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    state["index"] += 1
    quiz = state["questions"]

    if state["index"] >= len(quiz):
        score = state["score"]
        total = len(quiz)
        percent = round(100 * score / total) if total else 0

        if percent >= 90:
            comment = "A'lo natija! 🏆"
        elif percent >= 70:
            comment = "Yaxshi natija! 👍"
        elif percent >= 50:
            comment = "Qoniqarli, lekin yana mashq qiling 💪"
        else:
            comment = "Ko'proq tayyorlanish kerak 📚"

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔄 Qayta boshlash", callback_data="start_quiz")]]
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"🏁 Test tugadi!\n\n"
                f"To'g'ri javoblar: {score}/{total}\n"
                f"Natija: {percent}%\n\n"
                f"{comment}"
            ),
            reply_markup=keyboard,
        )
        context.user_data.pop("quiz", None)
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await send_question(query.message.chat_id, context)


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Railway loyihasida BOT_TOKEN environment "
            "variable'ini o'rnating (@BotFather'dan olingan token)."
        )

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CallbackQueryHandler(start_quiz, pattern="^start_quiz$"))
    app.add_handler(CallbackQueryHandler(next_question, pattern="^next$"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^ans:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

    logger.info("Bot ishga tushdi, %d ta savol yuklandi.", len(RAW_QUESTIONS))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
