from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = "7287037742:AAHCaVJF6OUz2G8yL4ztenlOXl4Tji5WKwc"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Русский", callback_data="language:ru")],
        [InlineKeyboardButton("English", callback_data="language:en")],
    ]
    await update.message.reply_text(
        "Выберите язык:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(f"Вы выбрали {query.data}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CallbackQueryHandler(handle_language_selection, pattern="^language:(ru|en)$")
    )
    app.run_polling()


if __name__ == "__main__":
    main()
