import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604709697:AAGForn7n3SXUhkrUGgS7c6p7SYMSpZKKa0")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-5180109170")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "12528644")

MARLEENKOOKT_EMAIL = os.getenv("MARLEENKOOKT_EMAIL", "")
MARLEENKOOKT_PASSWORD = os.getenv("MARLEENKOOKT_PASSWORD", "")

REMINDER_DAY = os.getenv("REMINDER_DAY", "sun").lower()
MORNING_REMINDER_TIME = os.getenv("MORNING_REMINDER_TIME", "09:00")
EVENING_REMINDER_TIME = os.getenv("EVENING_REMINDER_TIME", "21:00")
TIMEZONE = os.getenv("TZ", "Europe/Amsterdam")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")

# Home Assistant Integration
HASS_URL = os.getenv("HASS_URL", "")
HASS_TOKEN = os.getenv("HASS_TOKEN", "")
