import telebot
import psycopg2
import asyncio
from telebot import types
from aiohttp import web

# ==================== НАСТРОЙКИ СЕРВЕРА ====================
BOT_TOKEN = "8963416771:AAHIlA7tiWh6e6fjNLqqkwBj_o2x8n8oBK0"
DATABASE_URL = "postgresql://diams30690:6lw6qhN4oAiSgWyvVlA7DSDUi4ccvw56@://render.com"
CURRENT_VERSION = "1.0"

# ВСТАВЬТЕ СЮДА ВАШ ЦИФРОВОЙ TELEGRAM ID (Узнать можно в @userinfobot)
ADMIN_TG_ID = 5541669577  
# ==========================================================

bot = telebot.TeleBot(BOT_TOKEN)

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
        print("✅ Успешное подключение к PostgreSQL! Таблицы проверены.")
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

# --- ТГ БОТ И АДМИН ПАНЕЛЬ ---

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_sub = types.KeyboardButton("⏳ Выдать подписку")
    btn_hwid = types.KeyboardButton("🔓 Сбросить HWID")
    btn_role = types.KeyboardButton("👑 Изменить роль")
    btn_stats = types.KeyboardButton("📊 Статистика базы")
    markup.add(btn_sub, btn_hwid, btn_role, btn_stats)
    return markup

@bot.message_handler(commands=['start', 'back'])
def send_welcome(message):
    if message.from_user.id == ADMIN_TG_ID:
        bot.reply_to(
            message, 
            "👑 Добро пожаловать, Главный Администратор dimas30690!\nОкно управления пользователями активировано.", 
            reply_markup=get_admin_keyboard()
        )
    else:
        welcome_text = (
            "👋 Приветствуем в PulseVisuals!\n\n"
            "Для регистрации в лаунчере отправьте команду:\n"
            "📝 `/reg логин пароль`"
        )
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_TG_ID)
def admin_buttons_handler(message):
    if message.text == "⏳ Выдать подписку":
        bot.reply_to(
            message, 
            "📝 *Шаблон выдачи подписки:*\n`/subscribe количество_дней логин` (например: `/subscribe 30 testuser`)\n\n↩ Для отмены отправьте /back", 
            parse_mode="Markdown"
        )
    elif message.text == "🔓 Сбросить HWID":
        bot.reply_to(
            message, 
            "📝 *Шаблон сброса привязки железа:*\n`/unban_hwid логин` (например: `/unban_hwid testuser`)\n\n↩ Для отмены отправьте /back", 
            parse_mode="Markdown"
        )
    elif message.text == "👑 Изменить роль":
        bot.reply_to(
            message, 
            "📝 *Шаблон изменения роли:*\n`/setrole название_роли логин` (например: `/setrole VIP testuser`)\n\n↩ Для отмены отправьте /back", 
            parse_mode="Markdown"
        )
    elif message.text == "📊 Статистика базы":
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            bot.reply_to(message, f"📊 *Текущая статистика:*\nВсего пользователей в базе: `{total_users}`", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка получения статистики: {e}")

# --- ОБРАБОТКА АДМИНСКИХ КОМАНД ТЕКСТОМ ---

@bot.message_handler(commands=['subscribe'])
def cmd_subscribe(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Неверный формат! Используйте: `/subscribe дни логин`")
        return
    days, login = args[1], args[2]
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET subscription = subscription + %s WHERE login = %s", (int(days), login))
        conn.commit()
        cursor.close()
        conn.close()
        bot.reply_to(message, f"✅ Пользователю `{login}` успешно начислено `{days}` дней подписки!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка изменения подписки: {e}")

@bot.message_handler(commands=['unban_hwid'])
def cmd_unban_hwid(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ Неверный формат! Используйте: `/unban_hwid логин`")
        return
    login = args[1]
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET hwid = NULL WHERE login = %s", (login,))
        conn.commit()
        cursor.close()
        conn.close()
        bot.reply_to(message, f"✅ Привязка HWID для пользователя `{login}` успешно сброшена! Теперь он может войти с любого ПК.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка сброса HWID: {e}")

@bot.message_handler(commands=['setrole'])
def cmd_setrole(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Неверный формат! Используйте: `/setrole роль логин`")
        return
    role, login = args[1], args[2]
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = %s WHERE login = %s", (role, login))
        conn.commit()
        cursor.close()
        conn.close()
        bot.reply_to(message, f"✅ Роль пользователя `{login}` успешно изменена на `{role}`!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка изменения роли: {e}")

# Стандартная пользовательская регистрация
@bot.message_handler(commands=['reg'])
def register_user(message):
    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Формат: `/reg логин пароль`")
        return
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
