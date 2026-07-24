import os
import secrets
import string
import psycopg2
import asyncio
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from aiohttp import web

# ==================== НАСТРОЙКИ СЕРВЕРА ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CURRENT_VERSION = "1.0"

# Ссылка на вашу базу PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "YOUR_DATABASE_URL_HERE")

# ВАШ ЦИФРОВОЙ TELEGRAM ID
ADMIN_TG_ID = 5541669577  
# ==========================================================

bot = AsyncTeleBot(BOT_TOKEN)

# Генератор ключей формата REAPER-XXXX-XXXX-XXXX
def generate_reaper_key():
    chars = string.ascii_uppercase + string.digits
    p1 = ''.join(secrets.choice(chars) for _ in range(4))
    p2 = ''.join(secrets.choice(chars) for _ in range(4))
    p3 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"REAPER-{p1}-{p2}-{p3}"

# Безопасная инициализация базы данных
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                tg_id BIGINT,
                login TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'Пользователь',
                subscription_expires TIMESTAMP,
                hwid TEXT DEFAULT NULL
            )
        ''')

        # Таблица промокодов / ключей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_keys (
                id SERIAL PRIMARY KEY,
                key_code TEXT UNIQUE,
                days INT,
                is_used BOOLEAN DEFAULT FALSE,
                used_by TEXT DEFAULT NULL
            )
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ База данных PostgreSQL успешно инициализирована!")
    except Exception as e:
        print(f"❌ Ошибка базы: {e}")

# --- API МАРШРУТЫ ДЛЯ ЛАУНЧЕРА ---

async def check_update_handler(request):
    client_version = request.query.get('version')
    if client_version != CURRENT_VERSION:
        return web.json_response({"update_required": True, "url": "https://github.com"})
    return web.json_response({"update_required": False})

async def login_user_handler(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "message": "Неверный формат запроса!"})

    login = data.get('login')
    password = data.get('password')
    client_hwid = data.get('hwid')

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id, login, role, subscription_expires, hwid, tg_id FROM users WHERE login=%s AND password=%s", (login, password))
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Неверный логин или пароль!"})

        user_id, user_login, role, expires_at, db_hwid, tg_id = row

        now = datetime.now()
        if expires_at is None or expires_at < now:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Срок действия вашей подписки истек!"})

        remaining_time = expires_at - now
        days_left = max(0, remaining_time.days)

        # Привязка HWID при первом входе
        if db_hwid is None:
            cursor.execute("UPDATE users SET hwid=%s WHERE id=%s", (client_hwid, user_id))
            conn.commit()
            db_hwid = client_hwid
            try:
                await bot.send_message(tg_id, f"🔒 К вашему аккаунту `{user_login}` привязан HWID текущего ПК.", parse_mode="Markdown")
            except Exception:
                pass
        
        cursor.close()
        conn.close()

        if db_hwid != client_hwid:
            return web.json_response({"status": "error", "message": "Ошибка HWID! Доступ заблокирован."})

        return web.json_response({
            "status": "success",
            "data": {"id": user_id, "login": user_login, "role": role, "subscription": days_left}
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": f"Ошибка сервера: {str(e)}"})

# Маршрут для активации промокода из Лаунчера
async def activate_key_handler(request):
    try:
        data = await request.json()
        login = data.get('login')
        key_code = data.get('key', '').strip().upper()

        if not login or not key_code:
            return web.json_response({"status": "error", "message": "Заполните все поля!"})

        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Проверка ключа
        cursor.execute("SELECT days, is_used FROM promo_keys WHERE key_code = %s", (key_code,))
        key_row = cursor.fetchone()

        if not key_row:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Недействительный ключ!"})

        days, is_used = key_row
        if is_used:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Ключ уже был активирован!"})

        # Получаем пользователя
        cursor.execute("SELECT subscription_expires FROM users WHERE login = %s", (login,))
        user_row = cursor.fetchone()

        if not user_row:
            cursor.close()
            conn.close()
            return web.json_response({"status": "error", "message": "Пользователь не найден!"})

        current_expires = user_row[0]
        now = datetime.now()

        if current_expires is None or current_expires < now:
            new_expires = now + timedelta(days=days)
        else:
            new_expires = current_expires + timedelta(days=days)

        # Обновляем подписку и помечаем ключ использованным
        cursor.execute("UPDATE users SET subscription_expires = %s WHERE login = %s", (new_expires, login))
        cursor.execute("UPDATE promo_keys SET is_used = TRUE, used_by = %s WHERE key_code = %s", (login, key_code))
        conn.commit()

        cursor.close()
        conn.close()

        return web.json_response({"status": "success", "message": f"Ключ активирован! Добавлено {days} дней.", "days": days})
    except Exception as e:
        return web.json_response({"status": "error", "message": f"Ошибка активации: {str(e)}"})

# --- АДМИН ПАНЕЛЬ КНОПКИ ---

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_sub = types.KeyboardButton("⏳ Выдать подписку")
    btn_gen = types.KeyboardButton("🔑 Сгенерировать ключ")
    btn_hwid = types.KeyboardButton("🔓 Сбросить HWID")
    btn_role = types.KeyboardButton("👑 Изменить роль")
    btn_stats = types.KeyboardButton("📊 Статистика базы")
    markup.add(btn_sub, btn_gen, btn_hwid, btn_role, btn_stats)
    return markup

@bot.message_handler(commands=['start', 'back'])
async def send_welcome(message):
    if message.from_user.id == ADMIN_TG_ID:
        await bot.reply_to(
            message, 
            "👑 **Добро пожаловать в панель управления Reaper Client!**\nВыберите действие в меню ниже:", 
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    else:
        welcome_text = (
            "👋 **Приветствуем в Reaper Client!**\n\n"
            "Для регистрации в системе лаунчера отправьте команду:\n"
            "📝 `/reg логин пароль`"
        )
        await bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

# Генерация ключа админом через команду /genkey <дни>
@bot.message_handler(commands=['genkey'])
async def cmd_genkey(message):
    if message.from_user.id != ADMIN_TG_ID: 
        return

    args = message.text.split()
    days = 30
    if len(args) >= 2 and args[1].isdigit():
        days = int(args[1])

    new_key = generate_reaper_key()

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promo_keys (key_code, days) VALUES (%s, %s)", (new_key, days))
        conn.commit()
        cursor.close()
        conn.close()

        msg = (
            f"🔑 **Ключ успешно создан!**\n\n"
            f"`{new_key}`\n\n"
            f"⏳ Срок: **{days} дней**\n"
            f"Игрок может активировать его прямо в Настройках лаунчера."
        )
        await bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка создания ключа: {e}")

@bot.message_handler(commands=['subscribe'])
async def cmd_subscribe(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 3:
        await bot.reply_to(message, "❌ Формат: `/subscribe дни логин`", parse_mode="Markdown")
        return
    
    try:
        days = int(args[1])
        login = args[2]
        
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT subscription_expires FROM users WHERE login = %s", (login,))
        row = cursor.fetchone()
        
        if not row:
            await bot.reply_to(message, f"❌ Пользователь с логином `{login}` не найден!", parse_mode="Markdown")
            cursor.close()
            conn.close()
            return
            
        current_expires = row[0]
        now = datetime.now()
        
        if current_expires is None or current_expires < now:
            new_expires = now + timedelta(days=days)
        else:
            new_expires = current_expires + timedelta(days=days)
            
        cursor.execute("UPDATE users SET subscription_expires = %s WHERE login = %s", (new_expires, login))
        conn.commit()
        cursor.close()
        conn.close()
        await bot.reply_to(message, f"✅ Пользователю `{login}` успешно начислено `{days}` дней подписки!", parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['unban_hwid'])
async def cmd_unban_hwid(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 2:
        await bot.reply_to(message, "❌ Формат: `/unban_hwid логин`", parse_mode="Markdown")
        return
    
    login = args[1]
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET hwid = NULL WHERE login = %s", (login,))
        conn.commit()
        cursor.close()
        conn.close()
        await bot.reply_to(message, f"✅ Привязка HWID для `{login}` успешно сброшена!", parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['setrole'])
async def cmd_setrole(message):
    if message.from_user.id != ADMIN_TG_ID: return
    args = message.text.split()
    if len(args) != 3:
        await bot.reply_to(message, "❌ Формат: `/setrole роль логин`", parse_mode="Markdown")
        return
    
    role = args[1]
    login = args[2]
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = %s WHERE login = %s", (role, login))
        conn.commit()
        cursor.close()
        conn.close()
        await bot.reply_to(message, f"✅ Роль пользователя `{login}` успешно изменена на `{role}`!", parse_mode="Markdown")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['reg'])
async def register_user(message):
    args = message.text.split()
    if len(args) != 3:
        await bot.reply_to(message, "❌ Формат: `/reg логин пароль`", parse_mode="Markdown")
        return
        
    login = args[1]
    password = args[2]
    default_sub_expires = datetime.now() + timedelta(days=10)
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (tg_id, login, password, subscription_expires) VALUES (%s, %s, %s, %s) RETURNING id", 
            (message.from_user.id, login, password, default_sub_expires)
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        await bot.reply_to(message, f"✅ Аккаунт **Reaper** успешно создан!\n🎁 Выдана пробная подписка на 10 дней.\n🆔 Ваш ID: `{user_id}`", parse_mode="Markdown")
    except psycopg2.IntegrityError:
        await bot.reply_to(message, "❌ Этот логин уже занят!")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка базы данных: {e}")

# Обработка админ-кнопок
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_TG_ID and message.text in ["⏳ Выдать подписку", "🔑 Сгенерировать ключ", "🔓 Сбросить HWID", "👑 Изменить роль", "📊 Статистика базы"])
async def admin_buttons_handler(message):
    if message.text == "⏳ Выдать подписку":
        await bot.reply_to(message, "📝 *Выдача подписки напрямую:*\n`/subscribe количество_дней логин`\n(Пример: `/subscribe 30 testuser`)", parse_mode="Markdown")
    elif message.text == "🔑 Сгенерировать ключ":
        await bot.reply_to(message, "📝 *Генерация промокода:*\n`/genkey количество_дней`\n(Пример: `/genkey 30`)\n\nБудет создан уникальный ключ `REAPER-XXXX-XXXX-XXXX`", parse_mode="Markdown")
    elif message.text == "🔓 Сбросить HWID":
        await bot.reply_to(message, "📝 *Сброс привязки ПК:*\n`/unban_hwid логин`", parse_mode="Markdown")
    elif message.text == "👑 Изменить роль":
        await bot.reply_to(message, "📝 *Смена роли:*\n`/setrole название_роли логин`", parse_mode="Markdown")
    elif message.text == "📊 Статистика базы":
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM promo_keys WHERE is_used = FALSE")
            active_keys = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            await bot.reply_to(message, f"📊 *Статистика Reaper DB:*\n• Пользователей: `{total_users}`\n• Неактивированных ключей: `{active_keys}`", parse_mode="Markdown")
        except Exception as e:
            await bot.reply_to(message, f"❌ Ошибка статистики: {e}")

# --- ЗАПУСК СЕРВЕРА И БОТА ---
async def main():
    init_db()
    server_app = web.Application()
    server_app.router.add_get('/check_update', check_update_handler)
    server_app.router.add_post('/login', login_user_handler)
    server_app.router.add_post('/activate_key', activate_key_handler)
    
    runner = web.AppRunner(server_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    print("🚀 Асинхронный API-сервер Reaper запущен на порту 10000")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
