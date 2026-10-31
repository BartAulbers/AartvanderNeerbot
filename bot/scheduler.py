import json
import logging
import os
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.config import (
    REMINDER_DAY,
    MORNING_REMINDER_TIME,
    EVENING_REMINDER_TIME,
    TIMEZONE,
    DATA_DIR
)
from bot.marleenkookt import MarleenChecker
from bot.telegram_client import TelegramNotifier

logger = logging.getLogger(__name__)

DAY_NAMES = {
    "mon": "Maandag",
    "tue": "Dinsdag",
    "wed": "Woensdag",
    "thu": "Donderdag",
    "fri": "Vrijdag",
    "sat": "Zaterdag",
    "sun": "Zondag"
}

class MarleenScheduler:
    def __init__(self, notifier: TelegramNotifier, checker: MarleenChecker):
        self.notifier = notifier
        self.checker = checker
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))
        self.meals_confirmed_today = False
        self.settings_file = os.path.join(DATA_DIR, "settings.json")
        self.reminder_day = self._load_reminder_day()

    def _load_reminder_day(self) -> str:
        """Loads saved reminder day from settings.json or defaults to config."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    day = data.get("reminder_day")
                    if day and day.lower()[:3] in DAY_NAMES:
                        return day.lower()[:3]
            except Exception as e:
                logger.error(f"Error loading settings.json: {e}")
        return REMINDER_DAY.lower()[:3]

    def _save_reminder_day(self, day: str):
        """Saves reminder day to settings.json so it persists across container restarts."""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            data = {}
            if os.path.exists(self.settings_file):
                try:
                    with open(self.settings_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["reminder_day"] = day
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving settings.json: {e}")

    def get_reminder_day(self) -> str:
        return self.reminder_day

    def get_reminder_day_name(self) -> str:
        return DAY_NAMES.get(self.reminder_day, self.reminder_day.capitalize())

    def parse_time(self, time_str: str):
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    async def morning_job(self):
        logger.info("Executing scheduled Morning Job...")
        self.meals_confirmed_today = False

        is_selected, reason, info = await self.checker.check_meals_selected()
        logger.info(f"Morning check result: is_selected={is_selected}, reason={reason}")

        if is_selected is True:
            self.meals_confirmed_today = True
            await self.notifier.send_already_selected_confirmation(info=info)
        else:
            await self.notifier.send_morning_reminder(info=info)

    async def evening_job(self):
        logger.info("Executing scheduled Evening Job...")
        is_selected, reason, info = await self.checker.check_meals_selected()
        logger.info(f"Evening check result: is_selected={is_selected}, reason={reason}")

        if is_selected is True:
            logger.info("Meals are already chosen, skipping evening escalation.")
            return

        # Not chosen yet: send urgent escalation
        await self.notifier.send_evening_escalation(info=info)

    def _reschedule(self):
        """Updates the cron jobs with the current reminder_day."""
        morning_hour, morning_minute = self.parse_time(MORNING_REMINDER_TIME)
        evening_hour, evening_minute = self.parse_time(EVENING_REMINDER_TIME)

        day = self.reminder_day

        self.scheduler.add_job(
            self.morning_job,
            CronTrigger(day_of_week=day, hour=morning_hour, minute=morning_minute, timezone=TIMEZONE),
            id="morning_reminder",
            name="Morning Marleen Reminder",
            replace_existing=True
        )

        self.scheduler.add_job(
            self.evening_job,
            CronTrigger(day_of_week=day, hour=evening_hour, minute=evening_minute, timezone=TIMEZONE),
            id="evening_reminder",
            name="Evening Marleen Escalation Reminder",
            replace_existing=True
        )
        logger.info(f"Rescheduled Marleen reminders to {day.upper()} (morning: {MORNING_REMINDER_TIME}, evening: {EVENING_REMINDER_TIME}).")

    def set_reminder_day(self, new_day: str) -> str:
        """Sets a new reminder day, persists it, and updates scheduler."""
        day_code = new_day.lower()[:3]
        if day_code not in DAY_NAMES:
            raise ValueError(f"Invalid day: {new_day}")

        self.reminder_day = day_code
        self._save_reminder_day(day_code)
        self._reschedule()
        return DAY_NAMES[day_code]

    def start(self):
        self._reschedule()
        self.scheduler.start()
        logger.info(
            f"Scheduler started. Morning job set for {self.reminder_day.upper()} at {MORNING_REMINDER_TIME}, "
            f"Evening job set for {self.reminder_day.upper()} at {EVENING_REMINDER_TIME} ({TIMEZONE})."
        )
