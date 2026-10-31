import logging
import os
from typing import Optional, Dict, Any, List
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, default_chat_id: Optional[str] = None):
        self.token = bot_token or TELEGRAM_BOT_TOKEN
        self.default_chat_id = default_chat_id or TELEGRAM_CHAT_ID
        self.bot = Bot(token=self.token)

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
        """Sends a markdown formatted message to the specified or default chat."""
        target_id = chat_id or self.default_chat_id
        if not target_id:
            logger.error("No Telegram chat ID provided!")
            return False

        try:
            await self.bot.send_message(
                chat_id=target_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
                reply_markup=reply_markup
            )
            logger.info(f"Message sent to Telegram chat {target_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {target_id}: {e}")
            try:
                await self.bot.send_message(
                    chat_id=target_id,
                    text=text,
                    disable_web_page_preview=False,
                    reply_markup=reply_markup
                )
                return True
            except Exception as e2:
                logger.error(f"Fallback plain text message also failed: {e2}")
                return False

    async def send_photo(self, photo_path: str, caption: str = "", chat_id: Optional[str] = None) -> bool:
        """Sends a screenshot/photo to the specified chat."""
        target_id = chat_id or self.default_chat_id
        if not os.path.exists(photo_path):
            logger.warning(f"Photo path does not exist: {photo_path}")
            return False

        try:
            with open(photo_path, "rb") as photo:
                await self.bot.send_photo(
                    chat_id=target_id,
                    photo=photo,
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send photo to Telegram: {e}")
            return False

    def format_menu_text(self, week_data: Dict[str, Any]) -> str:
        label = week_data.get("label", "Menu")
        dishes = week_data.get("dishes", [])

        num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟", "1️⃣1️⃣", "1️⃣2️⃣", "1️⃣3️⃣", "1️⃣4️⃣", "1️⃣5️⃣"]

        text = f"🍽️ *MarleenKookt Menu — {label}*\n\n"

        # Check if there are already selected dishes on MarleenKookt
        selected_dishes = [d for d in dishes if d.get("is_selected")]
        if selected_dishes:
            total_qty = sum(d.get("quantity", 1) for d in selected_dishes)
            text += f"🥘 *Jullie huidige selectie ({total_qty} maaltijden):*\n"
            for d in selected_dishes:
                qty = d.get("quantity", 1)
                qty_str = f"{qty}× " if qty > 1 else ""
                text += f"• {qty_str}*{d.get('title')}*\n"
            text += "\n━━━━━━━━━━━━━━━━━━━━\n*Alle beschikbare gerechten:*\n"
            text += "_(Dikgedrukt met ✅ = geselecteerd)_\n\n"

        for d in dishes:
            idx = d.get("index", 1)
            emoji = num_emojis[idx - 1] if idx <= len(num_emojis) else f"{idx}."
            title = d.get("title", f"Gerecht {idx}")
            is_sel = d.get("is_selected", False)
            qty = d.get("quantity", 1)

            # Selected dishes are BOLD with checkmark, unselected are plain text
            if is_sel:
                qty_badge = f" `({qty}× gekozen)`" if qty > 1 else " `(gekozen)`"
                title_line = f"✅ {emoji} *{title}*{qty_badge}"
            else:
                title_line = f"{emoji} {title}"

            tags = " · ".join(d.get("tags", []))
            tags_str = f"   _{tags}_\n" if tags else ""
            text += f"{title_line}\n{tags_str}"

        text += (
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "✍️ *Hoe te kiezen:*\n"
            "Typ bijvoorbeeld: `/kies 1, 2, 4`\n"
            "Of gebruik de cijferknoppen hieronder om direct gerechten te selecteren!"
        )
        return text

    async def send_morning_reminder(self, chat_id: Optional[str] = None, info: Optional[Dict[str, Any]] = None):
        date_line = f"📅 *Volgende bezorging:* {info['date']} ({info.get('details', '')})\n" if info and info.get('date') else ""
        link_url = info.get("order_url", "https://app.marleenkookt.nl/bestellen") if info else "https://app.marleenkookt.nl/bestellen"

        msg = (
            "🍽️ *MarleenKookt herinnering!*\n\n"
            "Goedemorgen! De maaltijden voor aankomende week zijn nog *niet* gekozen.\n\n"
            f"{date_line}\n"
            "Bekijk de gerechten direct in Telegram met `/menu` of kies via de knop hieronder!\n\n"
            "⏰ _Deadline: vanavond voor 23:59_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Bekijk menu in Telegram", callback_data="show_menu_0")],
            [InlineKeyboardButton("🌐 Open MarleenKookt site", url=link_url)]
        ])
        return await self.send_message(msg, chat_id, reply_markup=keyboard)

    async def send_already_selected_confirmation(self, chat_id: Optional[str] = None, info: Optional[Dict[str, Any]] = None):
        date_line = f"📅 *Bezorging:* {info['date']} ({info.get('details', '')})\n\n" if info and info.get('date') else ""

        msg = (
            "✅ *MarleenKookt — Alles geregeld!*\n\n"
            f"{date_line}"
            "Jullie maaltijden voor volgende week zijn al geselecteerd.\n"
            "Lekker bezig! Eet smakelijk alvast. 🥘\n\n"
            "_Wil je toch iets anders? Bekijk het menu met /menu._"
        )
        return await self.send_message(msg, chat_id)

    async def send_evening_escalation(self, chat_id: Optional[str] = None, info: Optional[Dict[str, Any]] = None):
        date_line = f"📅 *Bezorging:* {info['date']} ({info.get('details', '')})\n" if info and info.get('date') else ""
        link_url = info.get("order_url", "https://app.marleenkookt.nl/bestellen") if info else "https://app.marleenkookt.nl/bestellen"

        msg = (
            "⚠️ *Laatste kans voor MarleenKookt!*\n\n"
            f"{date_line}\n"
            "🚨 Jullie hebben nog *geen* maaltijden gekozen!\n"
            "Over circa 3 uur (om 23:59) sluit de keuze.\n"
            "Als je nu niets kiest, selecteert Marleen automatisch gerechten voor jullie.\n\n"
            "👉 Typ nu direct `/kies [nummers]` of bekijk het menu met `/menu`!"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Bekijk menu & kies nu", callback_data="show_menu_0")],
            [InlineKeyboardButton("🌐 Naar MarleenKookt site", url=link_url)]
        ])
        return await self.send_message(msg, chat_id, reply_markup=keyboard)
