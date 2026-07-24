import os
import telebot
import psycopg2
import asyncio
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from aiohttp import web

# ==================== НАСТРОЙКИ СЕРВЕРА ====================
BOT_TOKEN = "8963416771:AAHIlA7tiWh6e6fjNLqqkwBj_o2x8n8oBK0"  # Смени токен в @BotFather!
CURRENT_VERSION = "1.0"

# Внутренняя (Internal) ссылка на вашу базу reaperdb
DATABASE_URL = "postgresql://diams30690:6lw6qhN4oAiSgWyvVlA7DSDUi4ccvw56@dpg-d9hth27lk1mc738g881g-a/reaperdb"

# ВАШ ЦИФРОВОЙ TELEGRAM ID
ADMIN_TG_ID = 5541669577  
# ==========================================================

bot = AsyncTeleBot(BOT_TOKEN)

# Безопасная инициализация базы данных (без DROP TABLE)
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Создаем таблицу, только если её еще не существует (не сносим старые данные!)
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
    except:
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
        days_left = remaining_time.days

        if days_left < 0:
            days_left = 0

        # Привязка HWID при первом входе
        if db_hwid is None:
            cursor.execute("UPDATE users SET hwid=%s WHERE id=%s", (client_hwid, user_id))
            conn.commit()
            db_hwid = client_hwid
            try:
                await bot.send_message(tg_id, f"🔒 К вашему аккаунту `{user_login}` привязан HWID текущего ПК.")
            except:
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

# --- АДМИН ПАНЕЛЬ КНОПКИ ---

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_sub = types.KeyboardButton("⏳ Выдать подписку")
    btn_hwid = types.KeyboardButton("🔓 Сбросить HWID")
    btn_role = types.KeyboardButton("👑 Изменить роль")
    btn_stats = types.KeyboardButton("📊 Статистика базы")
    markup.add(btn_sub, btn_hwid, btn_role, btn_stats)
    return markup

@bot.message_handler(commands=['start', 'back'])
async def send_welcome(message):
    if message.from_user.id == ADMIN_TG_ID:
        await bot.reply_to(
            message, 
            "👑 Добро пожаловать, Главный Administrator dimas30690!\nОкно управления пользователями активировано.", 
            reply_markup=get_admin_keyboard()
        )
    else:
        welcome_text = (
            "👋 Приветствуем в PulseVisuals!\n\n"
            "Для регистрации в лаунчере отправьте команду:\n"
            "📝 `/reg логин пароль`"
        )
        await bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

# --- КОМАНДЫ АДМИНИСТРАТОРА (ВЫНЕСЕНЫ В НАЧАЛО) ---

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
        await bot.reply_to(message, f"✅ Успешно! Создан аккаунт с подпиской на 10 дней.\n🆔 Ваш ID: `{user_id}`", parse_mode="Markdown")
    except psycopg2.IntegrityError:
        await bot.reply_to(message, "❌ Этот логин уже занят!")
    except Exception as e:
        await bot.reply_to(message, f"❌ Ошибка базы данных: {e}")

# --- ОБРАБОТЧИК КНОПЕК МЕНЮ (Теперь только точные совпадения с текстом) ---

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_TG_ID and message.text in ["⏳ Выдать подписку", "🔓 Сбросить HWID", "👑 Изменить роль", "📊 Статистика базы"])
async def admin_buttons_handler(message):
    if message.text == "⏳ Выдать подписку":
        await bot.reply_to(message, "📝 *Шаблон выдачи подписки:*\n`/subscribe количество_дней логин` (например: `/subscribe 30 testuser`)\n\n↩ Для отмены отправьте /back", parse_mode="Markdown")
    elif message.text == "🔓 Сбросить HWID":
        await bot.reply_to(message, "📝 *Шаблон сброса привязки железа:*\n`/unban_hwid логин` (например: `/unban_hwid testuser`)\n\n↩ Для отмены отправьте /back", parse_mode="Markdown")
    elif message.text == "👑 Изменить роль":
        await bot.reply_to(message, "📝 *Шаблон изменения роли:*\n`/setrole название_роли логин` (например: `/setrole VIP testuser`)\n\n↩ Для отмены отправьте /back", parse_mode="Markdown")
    elif message.text == "📊 Статистика базы":
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            await bot.reply_to(message, f"📊 *Текущая статистика:*\nВсего пользователей в базе: `{total_users}`", parse_mode="Markdown")
        except Exception as e:
            await bot.reply_to(message, f"❌ Ошибка получения статистики: {e}")

# --- ЗАПУСК ---
async def main():
    init_db()
    server_app = web.Application()
    server_app.router.add_get('/check_update', check_update_handler)
    server_app.router.add_post('/login', login_user_handler)
    
    runner = web.AppRunner(server_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    print("🚀 Асинхронный API-сервер запущен")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
