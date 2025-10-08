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

# === CACHE & STATE ===
cache = {}
user_state = {}

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

# === START / SEARCH ===
@bot.message_handler(commands=["start", "search"])
def cmd_start(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(text=d, callback_data=d) for d in DISTRICTS]
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "Выберите район для поиска жилых комплексов:",
        reply_markup=markup
    )
    print("Search command triggered")

# === TALK TO MANAGER ===
@bot.message_handler(commands=["talk_to_manager"])
def cmd_talk_manager(message):
    bot.send_message(
        message.chat.id,
        "Чтобы связаться с менеджером, напишите на телеграм: @sardorbatyrov"
    )

# === CALLBACK HANDLER ===
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data

    if data in DISTRICTS:
        handle_district(call, data)
    else:
        handle_layout_selection(call, data)

# === HANDLE DISTRICT ===
def handle_district(call, district):
    bot.answer_callback_query(call.id, f"Вы выбрали: {district}")
    chat_id = call.message.chat.id

    # Check cache
    if district in cache and time.time() - cache[district]["time"] < 300:
        complexes = cache[district]["data"]
        print(f"⚡ Using cached data for {district}")
    else:
        response = supabase.table("complexes").select("*").eq("district", district).execute()
        complexes = response.data
        cache[district] = {"data": complexes, "time": time.time()}
        print(f"🌐 Loaded {len(complexes)} complexes for {district}")

    if not complexes:
        bot.send_message(chat_id, "В этом районе пока нет комплексов.")
        return

    # Use the first complex as the active one
    first_complex = complexes[0]
    id_complex = first_complex["id_complex"]

    # Save state
    user_state[call.from_user.id] = {"id_complex": id_complex, "district": district}

    # 1️⃣ Send renders
    send_renders(chat_id, id_complex)

    # 2️⃣ Wait 3 sec → Send caption
    time.sleep(3)
    caption = first_complex.get("caption", "Описание отсутствует.")
    bot.send_message(chat_id, caption)

    # 3️⃣ Wait 3 sec → Show layouts
    time.sleep(3)
    show_layout_buttons(chat_id, id_complex)

# === SEND RENDERS ===
def send_renders(chat_id, id_complex):
    response = supabase.table("renders").select("file_url").eq("id_complex", id_complex).execute()
    renders = response.data

    if not renders:
        bot.send_message(chat_id, "Нет изображений рендера для этого комплекса.")
        return

    media = [types.InputMediaPhoto(r["file_url"]) for r in renders]
    bot.send_media_group(chat_id, media)
    print(f"📸 Sent {len(renders)} renders for {id_complex}")

# === SHOW LAYOUT BUTTONS ===
def show_layout_buttons(chat_id, id_complex):
    response = supabase.table("layouts").select("area").eq("id_complex", id_complex).execute()
    layouts = response.data

    if not layouts:
        bot.send_message(chat_id, "Планировок для этого комплекса пока нет.")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(text=l["area"], callback_data=f"layout_{l['area']}") for l in layouts]
    markup.add(*buttons)
    bot.send_message(chat_id, "У нас есть такие планировки в этом комплексе:", reply_markup=markup)
    print(f"🏗️ Showing {len(layouts)} layouts for {id_complex}")

# === HANDLE LAYOUT SELECTION ===
def handle_layout_selection(call, data):
    user_id = call.from_user.id
    state = user_state.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "Пожалуйста, начните заново с /search")
        return

    if not data.startswith("layout_"):
        bot.answer_callback_query(call.id)
        return

    area = data.replace("layout_", "")
    id_complex = state["id_complex"]

    response = (
        supabase.table("layouts")
        .select("file_url")
        .eq("id_complex", id_complex)
        .eq("area", area)
        .execute()
    )

    layouts = response.data
    if not layouts:
        bot.answer_callback_query(call.id, "Нет изображения для этой планировки.")
        return

    bot.answer_callback_query(call.id)

    # Send layout image with registration button
    layout = layouts[0]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📞 Регистрация", url="https://t.me/sardorbatyrov"))
    bot.send_photo(
        call.message.chat.id,
        layout["file_url"],
        caption=f"Планировка {area}",
        reply_markup=markup
    )
    print(f"🏘️ Sent layout {area} for complex {id_complex}")

# === FALLBACK ===
@bot.message_handler(func=lambda msg: True)
def fallback(message):
    bot.send_message(
        message.chat.id,
        "Неизвестная команда. Используйте /search или /talk_to_manager"
    )

# === RUN ===
print("Bot started ✅")
bot.polling(none_stop=True)
