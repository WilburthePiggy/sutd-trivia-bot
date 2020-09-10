from telegram.ext import Updater
from telegram.update import Update

updater = Updater(
    token="944974168:AAGGHap1ul5dQqnmxcdeINhzusCuJ2IFGvA", use_context=True
)

dispatcher = updater.dispatcher


def start(update: Update, context):
    print(update.effective_chat.id)
    context.bot.send_message(
        chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!"
    )


from telegram.ext import CommandHandler

start_handler = CommandHandler("start", start)
dispatcher.add_handler(start_handler)

updater.start_polling()
