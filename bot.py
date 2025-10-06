import time
import threading
import telebot
from telebot import types
from supabase import create_client, Client

# === CONFIG ===
TELEGRAM_TOKEN = "7579770697:AAGaIH7Wl12gNzdGFav3hLR4_cVjhYA0qo4"
SUPABASE_URL = "https://qyvioztatmdxkyblwyve.supabase.co"
SUPABASE_KEY = "sb_secret_QIgYizyVPZjedk_2PMvRAA_jgL7wSR-"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# === DISTRICTS ===
DISTRICTS = [
    "Мирзо-Улугбек", "Яшнабад", "Чиланзар", "Яккасарай",
    "Юнусабад", "Сергели", "Алмазар", "Янгихаят",
    "Шайхантахур", "Мирабад"
]

# === MEMORY STORAGE ===
user_state = {}  # Tracks user pagination
cache = {}       # Caches Supabase data temporarily


# === AUTO-CACHE CLEANER ===
def clear_cache_loop():
    while True:
        now = time.time()
        expired = [k for k, v in cache.items() if now - v["time"] > 300]
        for key in expired:
            del cache[key]
        if expired:
            print(f"🧹 Cleared {len(expired)} expired cache entries.")
        time.sleep(3600)


threading.Thread(target=clear_cache_loop, daemon=True).start()


# === START COMMAND ===
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "Здравствуйте! Чем могу помочь вам сегодня?"
    )
    print("Start command triggered")


# === SEARCH COMMAND ===
@bot.message_handler(commands=["search"])
def cmd_search(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(text=d, callback_data=d) for d in DISTRICTS]
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "Выберите район для поиска жилых комплексов:",
        reply_markup=markup
    )
    print("Search command triggered")


# === TALK TO MANAGER COMMAND ===
@bot.message_handler(commands=["talk_to_manager"])
def cmd_talk_manager(message):
    bot.send_message(
        message.chat.id,
        "Чтобы связаться с менеджером, напишите на телеграм: @sardorbatyrov"
    )
    print("Talk to manager command triggered")


# === CALLBACK HANDLER ===
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data

    if data in DISTRICTS:
        handle_district(call, data)
    elif data in ["next", "prev"]:
        handle_navigation(call)


# === HANDLE DISTRICT SELECTION ===
def handle_district(call, district):
    bot.answer_callback_query(call.id, f"Вы выбрали: {district}")
    bot.send_message(call.message.chat.id, f"Ищу жилые комплексы в районе {district}...")

    # Check cache
    if district in cache and time.time() - cache[district]["time"] < 300:
        rows = cache[district]["data"]
        print(f"⚡ Using cached data for {district} ({len(rows)} rows)")
    else:
        rows = supabase.table("complexes").select("*").eq("district", district).execute().data
        cache[district] = {"data": rows, "time": time.time()}
        print(f"🌐 Fetched {len(rows)} rows from Supabase for {district}")

    if not rows:
        bot.send_message(call.message.chat.id, "В этом районе пока нет комплексов.")
        return

    # Group by id_complex
    complexes = {}
    for row in rows:
        complexes.setdefault(row["id_complex"], []).append(row)
    complexes_list = list(complexes.values())

    # Save user state
    user_state[call.from_user.id] = {
        "district": district,
        "complexes": complexes_list,
        "index": 0,
        "message_ids": []
    }

    send_complex(call.message.chat.id, call.from_user.id, new_message=True)


# === SEND COMPLEX FUNCTION ===
def send_complex(chat_id, user_id, new_message=False, edit=False):
    state = user_state.get(user_id)
    if not state:
        bot.send_message(chat_id, "Пожалуйста, выберите район заново с помощью /start.")
        return

    complexes = state["complexes"]
    index = state["index"]
    current = complexes[index]

    caption = current[0]["caption"]
    media = [types.InputMediaPhoto(item["file_url"], caption=caption if i == 0 else None)
             for i, item in enumerate(current)]

    markup = types.InlineKeyboardMarkup()
    buttons = []
    if index > 0:
        buttons.append(types.InlineKeyboardButton("⬅️ Назад", callback_data="prev"))
    if index < len(complexes) - 1:
        buttons.append(types.InlineKeyboardButton("➡️ Далее", callback_data="next"))
    markup.add(*buttons)

    if new_message:
        media_group = bot.send_media_group(chat_id, media)
        text_msg = bot.send_message(
            chat_id,
            f"Проект {index + 1} из {len(complexes)}",
            reply_markup=markup
        )
        state["message_ids"] = [m.message_id for m in media_group] + [text_msg.message_id]
        print(f"✅ Sent complex {index + 1}/{len(complexes)}")

    elif edit:
        try:
            for msg_id in state["message_ids"]:
                bot.delete_message(chat_id, msg_id)
            media_group = bot.send_media_group(chat_id, media)
            text_msg = bot.send_message(
                chat_id,
                f"Проект {index + 1} из {len(complexes)}",
                reply_markup=markup
            )
            state["message_ids"] = [m.message_id for m in media_group] + [text_msg.message_id]
            print(f"🔄 Replaced with complex {index + 1}/{len(complexes)}")
        except Exception as e:
            print(f"Edit error: {e}")


# === NAVIGATION HANDLER ===
def handle_navigation(call):
    user_id = call.from_user.id
    state = user_state.get(user_id)
    if not state:
        bot.answer_callback_query(call.id, "Сначала выберите район через /start")
        return

    if call.data == "next" and state["index"] < len(state["complexes"]) - 1:
        state["index"] += 1
    elif call.data == "prev" and state["index"] > 0:
        state["index"] -= 1
    else:
        bot.answer_callback_query(call.id, "Нет больше проектов.")
        return

    bot.answer_callback_query(call.id)
    send_complex(call.message.chat.id, user_id, edit=True)


# === FALLBACK HANDLER ===
@bot.message_handler(func=lambda msg: True)
def fallback(message):
    bot.send_message(
        message.chat.id,
        "Неизвестная команда. Используйте /start, /search или /talk_to_manager"
    )


# === RUN BOT ===
print("Bot started ✅")
bot.polling(none_stop=True)
