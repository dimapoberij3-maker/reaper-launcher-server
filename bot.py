import telebot
import psycopg2
import asyncio
from aiohttp import web

# ==================== НАСТРОЙКИ СЕРВЕРА ====================
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # <--- Вставьте сюда ваш токен от @BotFather!
DATABASE_URL = "postgresql://diams30690:6lw6qhN4oAiSgWyvVlA7DSDUi4ccvw56@://render.com"
CURRENT_VERSION = "1.0"
# ==========================================================

bot = telebot.TeleBot(BOT_TOKEN)

# Инициализация таблиц в Postgres
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                tg_id BIGINT,
                login TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'Пользователь',
                subscription INTEGER DEFAULT 10,
                hwid TEXT DEFAULT NULL
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Успешное подключение к PostgreSQL на Render! Таблицы проверены.")
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")

# --- API ДЛЯ ЛАУНЧЕРА ---

async def check_update_handler(request):
    client_version = request.query.get('version')
    if client_version != CURRENT_VERSION:
        return web.json_response({"update_required": True, "url": "https://github.com"})
    return web.json_response({"update_required": False})

async def login_user_handler(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"status": "error", "message": "Неверный формат запроса!"})

    login = data.get('login')
    password = data.get('password')
    client_hwid = data.get('hwid')

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id, login, role, subscription, hwid, tg_id FROM users WHERE login=%s AND password=%s", (login, password))
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Неверный логин или пароль!"})

        user_id, user_login, role, sub, db_hwid, tg_id = row

        # Авто-привязка HWID при первом логине
        if db_hwid is None:
            cursor.execute("UPDATE users SET hwid=%s WHERE id=%s", (client_hwid, user_id))
            conn.commit()
            db_hwid = client_hwid
            try:
                bot.send_message(tg_id, f"🔒 К вашему аккаунту `{user_login}` привязан HWID текущего ПК.")
            except:
                pass
        
        cursor.close()
        conn.close()

        if db_hwid != client_hwid:
            return web.json_response({"status": "error", "message": "Ошибка HWID! Доступ заблокирован."})

        return web.json_response({
            "status": "success",
            "data": {"id": user_id, "login": user_login, "role": role, "subscription": sub}
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": f"Ошибка БД: {str(e)}"})

# --- ТГ БОТ ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "👋 Приветствуем в PulseVisuals!\n\n"
        "Для регистрации в лаунчере отправьте команду:\n"
        "📝 `/reg логин пароль`"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['reg'])
def register_user(message):
    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Формат: `/reg логин пароль`")
        return
        
    # Исправленное считывание аргументов
    login, password = args[1], args[2]
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (tg_id, login, password) VALUES (%s, %s, %s) RETURNING id", (message.from_user.id, login, password))
        user_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        bot.reply_to(message, f"✅ Успешно!\n🆔 Ваш ID аккаунта: `{user_id}`\n\nМожете открывать лаунчер.")
    except psycopg2.IntegrityError:
        bot.reply_to(message, "❌ Этот логин уже занят!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка регистрации: {e}")

def run_bot_polling():
    print("Telegram-бот запущен...")
    bot.infinity_polling()

if __name__ == "__main__":
    init_db()
    
    server_app = web.Application()
    server_app.router.add_get('/check_update', check_update_handler)
    server_app.router.add_post('/login', login_user_handler)
    
    import threading
    threading.Thread(target=run_bot_polling, daemon=True).start()
    
    print("Сервер API запускается на порту 10000...")
    web.run_app(server_app, host='0.0.0.0', port=10000, handle_signals=False)
