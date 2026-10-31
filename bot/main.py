import asyncio
import logging
import re
import sys
from typing import Dict, List, Set
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from bot.config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_USER_ID,
    MORNING_REMINDER_TIME,
    EVENING_REMINDER_TIME
)
from bot.marleenkookt import MarleenChecker
from bot.telegram_client import TelegramNotifier
from bot.scheduler import MarleenScheduler
from bot.groceries import GroceryManager
from bot.homeassistant import HomeAssistantClient

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

checker = MarleenChecker()
notifier = TelegramNotifier()
scheduler = MarleenScheduler(notifier=notifier, checker=checker)
groceries = GroceryManager()
hass = HomeAssistantClient()

# Cache for scraped menus: {"data": {...}}
cached_menus = {}

# Active meal selections in chat: {chat_id: {"week_index": int, "selected": set(int)}}
active_selections: Dict[int, Dict] = {}


def get_persistent_reply_keyboard() -> ReplyKeyboardMarkup:
    """Bottom persistent menu buttons always visible to the user."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🛒 Boodschappen"), KeyboardButton("🍲 MarleenKookt")],
            [KeyboardButton("💡 Home Assistant"), KeyboardButton("🏠 Hoofdmenu")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the central household dashboard menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍲 MarleenKookt", callback_data="nav_marleen"),
            InlineKeyboardButton("🛒 Boodschappenlijst", callback_data="nav_groceries")
        ],
        [
            InlineKeyboardButton("💡 Home Assistant", callback_data="nav_hass"),
            InlineKeyboardButton("⚙️ Systeem Status", callback_data="nav_status")
        ]
    ])


def get_marleen_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the MarleenKookt sub-menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Bekijk Menu & Kies", callback_data="show_menu_0"),
            InlineKeyboardButton("🔍 Status Bestelling", callback_data="marleen_check_status")
        ],
        [
            InlineKeyboardButton("⏰ Herinnering Instellen", callback_data="marleen_settings_reminder"),
            InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")
        ]
    ])


def get_reminder_settings_keyboard(current_day: str) -> InlineKeyboardMarkup:
    """Builds inline keyboard for setting the weekly reminder day."""
    days = [
        ("mon", "Maandag"),
        ("tue", "Dinsdag"),
        ("wed", "Woensdag"),
        ("thu", "Donderdag"),
        ("fri", "Vrijdag"),
        ("sat", "Zaterdag"),
        ("sun", "Zondag")
    ]
    buttons = []
    row = []
    for code, name in days:
        is_active = code == current_day.lower()[:3]
        label = f"✅ {name}" if is_active else name
        row.append(InlineKeyboardButton(label, callback_data=f"set_rem_day_{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔙 Terug naar MarleenKookt", callback_data="nav_marleen"),
        InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")
    ])
    return InlineKeyboardMarkup(buttons)


def build_menu_keyboard(weeks: List[Dict], current_week_idx: int, selected_dishes: Set[int]) -> InlineKeyboardMarkup:
    """Builds inline keyboard for week switching and dish selection."""
    buttons = []

    # Week tabs row
    week_row = []
    for w in weeks:
        w_idx = w["week_index"]
        label = w["label"].split("\n")[0].strip()
        label_short = re.sub(r'\s+(Nog|Al|Bezorgd).*$', '', label).strip()
        prefix = "🔘 " if w_idx == current_week_idx else ""
        week_row.append(InlineKeyboardButton(f"{prefix}{label_short}", callback_data=f"menu_week_{w_idx}"))
    if week_row:
        buttons.append(week_row)

    # Dish selection buttons for the current week (grid of 5 columns)
    current_week = next((w for w in weeks if w["week_index"] == current_week_idx), weeks[0] if weeks else None)
    if current_week:
        dishes = current_week.get("dishes", [])
        dish_rows = []
        current_row = []
        for d in dishes:
            idx = d["index"]
            is_sel = idx in selected_dishes
            btn_text = f"✅ {idx}" if is_sel else f"[{idx}]"
            current_row.append(InlineKeyboardButton(btn_text, callback_data=f"toggle_{current_week_idx}_{idx}"))
            if len(current_row) == 5:
                dish_rows.append(current_row)
                current_row = []
        if current_row:
            dish_rows.append(current_row)
        buttons.extend(dish_rows)

    # Action row: Confirm button
    sel_count = len(selected_dishes)
    save_text = f"💾 Opslaan op MarleenKookt ({sel_count} gekozen)" if sel_count > 0 else "💾 Kies gerechten hierboven"
    buttons.append([
        InlineKeyboardButton(save_text, callback_data=f"save_{current_week_idx}"),
        InlineKeyboardButton("🔄 Herladen", callback_data=f"reload_menu_{current_week_idx}")
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Terug naar MarleenKookt", callback_data="nav_marleen"),
        InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")
    ])

    return InlineKeyboardMarkup(buttons)


# ==========================================
# COMMAND & BUTTON HANDLERS
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds with greeting, main menu, and activates the persistent bottom keyboard."""
    user = update.effective_user
    is_admin = str(user.id) == str(ADMIN_USER_ID)
    admin_tag = " 👑" if is_admin else ""

    text = (
        f"🏠 *Welkom bij AartvanderNeerbot*{admin_tag}!\n\n"
        f"Hoi {user.first_name}! Ik ben de centrale assistent voor jullie huishouden.\n\n"
        f"Gebruik de **menuknoppen onderaan je scherm** of kies een taak hieronder:"
    )
    # Send message with persistent reply keyboard and inline menu
    await update.message.reply_text(
        text,
        reply_markup=get_persistent_reply_keyboard(),
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "Kies een taak om direct te starten:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def text_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on the bottom persistent reply keyboard buttons."""
    text = (update.message.text or "").strip().lower()

    if "boodschappen" in text:
        await boodschappen_command(update, context)
    elif "marleen" in text:
        await marleen_command(update, context)
    elif "home assistant" in text or "homeassistant" in text or "hass" in text:
        await hass_command(update, context)
    elif "hoofdmenu" in text or text in ("menu", "start", "home"):
        await start_command(update, context)


# --- BOODSCHAPPEN COMMANDS ---

async def boodschappen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the shopping list."""
    text, keyboard = groceries.get_view()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def koop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds items to the grocery list: /koop melk, eieren, koffie."""
    raw_args = " ".join(context.args).strip()
    if not raw_args:
        await update.message.reply_text(
            "💡 *Gebruik van /koop:*\n"
            "Typ de artikelen gescheiden door komma's:\n"
            "👉 `/koop melk, eieren, koffiebonen, appels`",
            parse_mode="Markdown"
        )
        return

    user = update.effective_user
    added = groceries.add_items(raw_args, added_by=user.first_name)
    if added:
        items_str = "\n".join([f"• {it}" for it in added])
        text, keyboard = groceries.get_view()
        await update.message.reply_text(
            f"🛒 *Toegevoegd aan de boodschappenlijst:*\n{items_str}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Geen nieuwe items toegevoegd (stonden mogelijk al op de lijst).")


async def wis_boodschappen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears checked items from the grocery list."""
    removed = groceries.clear_checked()
    text, keyboard = groceries.get_view()
    await update.message.reply_text(f"🧹 {removed} afgevinkte artikelen verwijderd van de lijst.", reply_markup=keyboard)


# --- HOME ASSISTANT COMMANDS ---

async def hass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens Home Assistant dashboard."""
    text, keyboard = await hass.get_dashboard_view()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def lichten_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct shortcut to view and toggle lights."""
    text, keyboard = await hass.get_domain_view("light")
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def schakelaars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct shortcut to view and toggle switches."""
    text, keyboard = await hass.get_domain_view("switch")
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


# --- MARLEENKOOKT COMMANDS ---

async def marleen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens MarleenKookt sub-menu."""
    text = (
        "🍲 *MarleenKookt Menu*\n\n"
        "Wat wil je doen voor MarleenKookt?\n\n"
        "• Bekijk het menu van de komende weken\n"
        "• Selecteer direct jullie maaltijden\n"
        "• Controleer of er al gekozen is"
    )
    await update.message.reply_text(text, reply_markup=get_marleen_menu_keyboard(), parse_mode="Markdown")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the menu for available weeks with interactive selection."""
    chat_id = update.effective_chat.id
    wait_msg = await update.message.reply_text(
        "⏳ *We halen informatie op bij MarleenKookt, een ogenblik geduld alstublieft...*",
        parse_mode="Markdown"
    )

    menus = await checker.get_all_menus()
    if "error" in menus or not menus.get("weeks"):
        await wait_msg.edit_text(f"❌ Kon het menu niet ophalen: {menus.get('error', 'Onbekende fout')}")
        return

    cached_menus["data"] = menus["weeks"]

    current_week_idx = 0
    active_selections[chat_id] = {"week_index": current_week_idx, "selected": set()}

    current_week = menus["weeks"][0]
    initial_selected = {d["index"] for d in current_week.get("dishes", []) if d.get("is_selected")}
    active_selections[chat_id] = {"week_index": current_week_idx, "selected": set(initial_selected)}

    menu_text = notifier.format_menu_text(current_week)
    keyboard = build_menu_keyboard(menus["weeks"], current_week_idx, initial_selected)

    await wait_msg.edit_text(menu_text, reply_markup=keyboard, parse_mode="Markdown")


async def kies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct selection command: /kies 1, 2, 4"""
    chat_id = update.effective_chat.id
    raw_args = " ".join(context.args)

    if not raw_args:
        await update.message.reply_text(
            "💡 *Gebruik van /kies:*\n\n"
            "Typ de nummers van de gerechten die je wilt kiezen:\n"
            "👉 `/kies 1, 2, 4`\n\n"
            "Of voor week 2:\n"
            "👉 `/kies week 2: 1, 3, 5`\n\n"
            "_Tip: Typ /maaltijden om alle gerechtnummers te zien!_",
            parse_mode="Markdown"
        )
        return

    week_idx = 0
    week_match = re.search(r'week\s*(\d+)', raw_args, re.IGNORECASE)
    if week_match:
        week_idx = max(0, int(week_match.group(1)) - 1)

    cleaned_args = re.sub(r'week\s*\d+[:\s]*', '', raw_args, flags=re.IGNORECASE)
    numbers = [int(n) for n in re.findall(r'\b\d+\b', cleaned_args)]

    if not numbers:
        await update.message.reply_text("❌ Geen geldige nummers gevonden. Typ bijv: `/kies 1, 2, 4`", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(
        f"⏳ Bezig met inloggen en selecteren van gerechten `{numbers}` voor week {week_idx + 1}..."
    )

    success, msg, titles = await checker.select_and_save_meals(numbers, week_index=week_idx)

    if success:
        dishes_str = "\n".join([f"• *{t}*" for t in titles])
        text = (
            f"🎉 *Gelukt! Maaltijden zijn opgeslagen bij MarleenKookt!*\n\n"
            f"Gekozen gerechten:\n{dishes_str}\n\n"
            f"✅ {msg}"
        )
        await status_msg.edit_text(text, parse_mode="Markdown")
        await notifier.send_photo(
            checker.screenshot_path,
            caption="📸 Bevestigingsscherm van MarleenKookt",
            chat_id=str(chat_id)
        )
    else:
        await status_msg.edit_text(f"❌ *Niet gelukt:* {msg}\n\nBekijk eventueel /maaltijden om de juiste nummers te zien.", parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Performs an on-demand check on MarleenKookt."""
    status_msg = await update.message.reply_text("⏳ Bezig met controleren van MarleenKookt...")
    is_selected, reason, info = await checker.check_meals_selected()

    order_url = info.get("order_url", "https://app.marleenkookt.nl/bestellen") if info else "https://app.marleenkookt.nl/bestellen"
    date_info = f"\n📅 *Levering:* {info['date']} ({info.get('details', '')})" if info and info.get('date') else ""

    if is_selected is True:
        text = f"✅ *Status: Gekozen!*\n\n{reason}{date_info}\n\n_Wil je iets aanpassen? Typ /maaltijden._"
    elif is_selected is False:
        text = (
            f"⚠️ *Status: Nog NIET gekozen!*\n\n{reason}{date_info}\n\n"
            f"👉 Bekijk direct de maaltijden met `/maaltijden` of kies via `/kies [nummers]`!\n"
            f"Of ga naar [MarleenKookt site]({order_url})"
        )
    else:
        text = f"❓ *Status kon niet worden bepaald:*\n\n{reason}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Bekijk Menu", callback_data="show_menu_0")],
        [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
    ])
    await status_msg.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the last debug screenshot."""
    if not await notifier.send_photo(
        checker.screenshot_path,
        caption="📸 Meest recente screenshot van MarleenKookt",
        chat_id=str(update.effective_chat.id)
    ):
        await update.message.reply_text("Geen recente screenshot gevonden.")


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually triggers a morning reminder in the current chat."""
    _, _, info = await checker.check_meals_selected()
    await notifier.send_morning_reminder(chat_id=str(update.effective_chat.id), info=info)


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays Chat ID."""
    chat = update.effective_chat
    await update.message.reply_text(f"🏷️ Chat ID: `{chat.id}`", parse_mode="Markdown")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Combines all notification previews into one single test flow."""
    target_id = str(update.effective_chat.id)
    sample_info = {
        "date": "zondag 1 november",
        "details": "7 maaltijden beschikbaar · 19:00-20:00",
        "order_url": "https://app.marleenkookt.nl/bestellen"
    }

    await update.message.reply_text("🧪 *Start test van herinneringsberichten...*", parse_mode="Markdown")
    await notifier.send_morning_reminder(chat_id=target_id, info=sample_info)
    await asyncio.sleep(1)
    await notifier.send_already_selected_confirmation(chat_id=target_id, info=sample_info)
    await asyncio.sleep(1)
    await notifier.send_evening_escalation(chat_id=target_id, info=sample_info)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a complete overview of all available commands in the bot."""
    help_text = (
        "🤖 *AartvanderNeerbot — Overzicht van Commando's*\n\n"
        "Hieronder vind je alle beschikbare `/` functies:\n\n"
        "🏠 *Algemeen & Navigatie:*\n"
        "• `/start` of `/menu` — Open het hoofdmenu en activeer de menuknoppen\n"
        "• `/help` — Toon dit overzicht met alle functies\n"
        "• `/chatid` — Toon het Chat ID van deze groep/chat\n"
        "• `/test` — Test alle herinneringsberichten (preview)\n\n"
        "🍲 *MarleenKookt:*\n"
        "• `/marleen` — Open het MarleenKookt dashboard\n"
        "• `/maaltijden` — Bekijk het menu van de komende weken\n"
        "• `/kies 1, 2, 4` — Selecteer en bewaar maaltijden direct (bijv. `/kies 1, 2, 4` of `/kies week 2: 1, 3, 5`)\n"
        "• `/status` — Controleer live of de maaltijden voor de eerstvolgende box al gekozen zijn\n"
        "• `/remind` — Stuur handmatig direct de herinnering naar deze chat\n"
        "• `/screenshot` — Bekijk de meest recente schermafbeelding van de site\n\n"
        "🛒 *Boodschappenlijst:*\n"
        "• `/boodschappen` of `/lijst` — Bekijk de interactieve boodschappenlijst met afvink-knoppen\n"
        "• `/koop <items>` — Voeg artikelen toe (bijv. `/koop melk, eieren, koffie`)\n"
        "• `/wis` — Verwijder alle afgevinkte artikelen van de lijst\n\n"
        "💡 *Home Assistant:*\n"
        "• `/hass` of `/ha` — Open het Home Assistant bedieningspaneel\n"
        "• `/lichten` — Bekijk en schakel lampen aan/uit\n"
        "• `/schakelaars` — Bekijk en schakel apparaten/schakelaars aan/uit\n\n"
        "💡 _Tip: Je kunt ook altijd de vaste menuknoppen onderin je scherm gebruiken!_"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ==========================================
# CALLBACK QUERY ROUTER
# ==========================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central interactive button handler."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user

    # --- NAVIGATION ---
    if data == "nav_main_menu":
        text = (
            "🏠 *Hoofdmenu AartvanderNeerbot*\n\n"
            "Kies een taak om te starten:"
        )
        await query.edit_message_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "nav_marleen":
        text = (
            "🍲 *MarleenKookt Menu*\n\n"
            "Wat wil je doen voor MarleenKookt?\n\n"
            "• Bekijk het weekmenu en selecteer gerechten\n"
            "• Controleer of er al gekozen is\n"
            "• Bekijk een schermafbeelding van de site"
        )
        await query.edit_message_text(text, reply_markup=get_marleen_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "nav_groceries":
        text, keyboard = groceries.get_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "nav_hass":
        text, keyboard = await hass.get_dashboard_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "nav_status":
        ha_ok, ha_status = await hass.check_connection() if hass.is_configured() else (False, "Niet geconfigureerd")
        text = (
            "⚙️ *Systeem Status*\n\n"
            f"🤖 *Bot:* Online en actief\n"
            f"🍲 *MarleenKookt:* Inloggegevens aanwezig\n"
            f"💡 *Home Assistant:* {'🟢 ' + ha_status if ha_ok else '⚪ ' + ha_status}\n"
            f"🛒 *Boodschappenlijst:* {len(groceries._load())} items opgeslagen\n\n"
            f"📌 *Chat ID:* `{chat_id}`\n"
            f"👤 *Jouw User ID:* `{user.id}`"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    # --- GROCERIES ACTIONS ---
    if data.startswith("groc_toggle_"):
        item_id = int(data.split("_")[-1])
        groceries.toggle_item(item_id)
        text, keyboard = groceries.get_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "groc_clear_checked":
        groceries.clear_checked()
        text, keyboard = groceries.get_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "groc_clear_all":
        groceries.clear_all()
        text, keyboard = groceries.get_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "groceries_prompt_add":
        await query.answer("Tip: Typ direct in de chat: /koop melk, eieren, kaas", show_alert=True)
        return

    # --- HOME ASSISTANT ACTIONS ---
    if data == "hass_nav_main":
        text, keyboard = await hass.get_dashboard_view()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data.startswith("hass_list_"):
        domain = data.split("_")[-1]
        text, keyboard = await hass.get_domain_view(domain)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data.startswith("hass_toggle_"):
        entity_id = data.replace("hass_toggle_", "")
        success, msg = await hass.toggle_entity(entity_id)
        await query.answer(msg, show_alert=not success)
        # Refresh the domain view
        domain = entity_id.split(".")[0]
        text, keyboard = await hass.get_domain_view(domain)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data.startswith("hass_scene_"):
        scene_id = data.replace("hass_scene_", "")
        success, msg = await hass.activate_scene(scene_id)
        await query.answer(f"Scène geactiveerd: {scene_id}", show_alert=False)
        return

    # --- MARLEENKOOKT ACTIONS ---
    if data == "marleen_check_status":
        await query.edit_message_text("⏳ Bezig met controleren van MarleenKookt...")
        is_selected, reason, info = await checker.check_meals_selected()
        date_info = f"\n📅 *Levering:* {info['date']} ({info.get('details', '')})" if info and info.get('date') else ""
        if is_selected is True:
            text = f"✅ *Status: Gekozen!*\n\n{reason}{date_info}"
        elif is_selected is False:
            text = f"⚠️ *Status: Nog NIET gekozen!*\n\n{reason}{date_info}"
        else:
            text = f"❓ *Status kon niet worden bepaald:*\n\n{reason}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Bekijk Menu", callback_data="show_menu_0")],
            [InlineKeyboardButton("🔙 Terug", callback_data="nav_marleen")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data == "marleen_settings_reminder":
        cur_day = scheduler.get_reminder_day()
        cur_name = scheduler.get_reminder_day_name()
        text = (
            f"⏰ *Herinnering Instellen voor MarleenKookt*\n\n"
            f"Huidige herinneringsdag: *{cur_name}*\n"
            f"• Ochtendherinnering: `{MORNING_REMINDER_TIME}`\n"
            f"• Avond-escalatie: `{EVENING_REMINDER_TIME}`\n\n"
            f"Kies hieronder op welke dag je de wekelijkse herinnering wilt ontvangen:"
        )
        await query.edit_message_text(
            text,
            reply_markup=get_reminder_settings_keyboard(cur_day),
            parse_mode="Markdown"
        )
        return

    if data.startswith("set_rem_day_"):
        new_day_code = data.replace("set_rem_day_", "")
        new_day_name = scheduler.set_reminder_day(new_day_code)
        await query.answer(f"Herinnering ingesteld op {new_day_name}!", show_alert=True)
        text = (
            f"✅ *Herinneringsdag Aangepast!*\n\n"
            f"Jullie ontvangen de herinnering voortaan op *{new_day_name}*:\n"
            f"• Ochtendherinnering: `{MORNING_REMINDER_TIME}`\n"
            f"• Avond-escalatie (deadline): `{EVENING_REMINDER_TIME}`\n\n"
            f"Kies eventueel een andere dag of ga terug:"
        )
        await query.edit_message_text(
            text,
            reply_markup=get_reminder_settings_keyboard(new_day_code),
            parse_mode="Markdown"
        )
        return

    if data == "marleen_get_screenshot":
        await notifier.send_photo(checker.screenshot_path, caption="📸 Screenshot van MarleenKookt", chat_id=str(chat_id))
        return

    # Week switching / dish menu
    user_state = active_selections.setdefault(chat_id, {"week_index": 0, "selected": set()})

    if data.startswith("show_menu_") or data.startswith("menu_week_") or data.startswith("reload_menu_"):
        w_idx = int(data.split("_")[-1])
        user_state["week_index"] = w_idx
        await query.edit_message_text(
            "⏳ *We halen informatie op bij MarleenKookt, een ogenblik geduld alstublieft...*",
            parse_mode="Markdown"
        )

        weeks = cached_menus.get("data")
        if not weeks or data.startswith("reload_menu_"):
            fresh = await checker.get_all_menus()
            if "weeks" in fresh:
                weeks = fresh["weeks"]
                cached_menus["data"] = weeks
            else:
                await query.edit_message_text(f"❌ Kon het menu niet ophalen: {fresh.get('error', 'Onbekende fout')}")
                return

        current_week = next((w for w in weeks if w["week_index"] == w_idx), weeks[0])
        initial_selected = {d["index"] for d in current_week.get("dishes", []) if d.get("is_selected")}
        user_state["selected"] = set(initial_selected)

        menu_text = notifier.format_menu_text(current_week)
        keyboard = build_menu_keyboard(weeks, w_idx, user_state["selected"])
        await query.edit_message_text(menu_text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data.startswith("toggle_"):
        parts = data.split("_")
        w_idx = int(parts[1])
        dish_idx = int(parts[2])

        if dish_idx in user_state["selected"]:
            user_state["selected"].remove(dish_idx)
        else:
            user_state["selected"].add(dish_idx)

        current_week = next((w for w in weeks if w["week_index"] == w_idx), weeks[0])
        menu_text = notifier.format_menu_text(current_week)
        if user_state["selected"]:
            sel_sorted = sorted(list(user_state["selected"]))
            menu_text += f"\n\n🎯 *Jouw selectie:* Gerechten `{sel_sorted}`"

        keyboard = build_menu_keyboard(weeks, w_idx, user_state["selected"])
        await query.edit_message_text(menu_text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if data.startswith("save_"):
        w_idx = int(data.split("_")[-1])
        selected_indices = sorted(list(user_state.get("selected", set())))

        if not selected_indices:
            await query.answer("Kies eerst minimaal 1 gerecht door op de nummers te tikken!", show_alert=True)
            return

        current_week = next((w for w in weeks if w["week_index"] == w_idx), weeks[0])
        week_label = current_week.get("label", f"Week {w_idx + 1}")

        await query.edit_message_text(
            f"⏳ *Bezig met opslaan van gerechten {selected_indices} voor {week_label}...*\n"
            f"MarleenKookt wordt geopend...",
            parse_mode="Markdown"
        )

        success, msg, titles = await checker.select_and_save_meals(selected_indices, week_index=w_idx)

        if success:
            dishes_str = "\n".join([f"• *{t}*" for t in titles])
            result_text = (
                f"🎉 *Gelukt! Maaltijdkeuze is opgeslagen!*\n\n"
                f"📅 *{week_label}*\n"
                f"Gekozen gerechten:\n{dishes_str}\n\n"
                f"✅ {msg}"
            )
            await notifier.send_message(result_text, chat_id=str(chat_id))
            await notifier.send_photo(checker.screenshot_path, caption="📸 Bevestigingsscherm van MarleenKookt", chat_id=str(chat_id))
            user_state["selected"] = set()
        else:
            await notifier.send_message(f"❌ *Opslaan mislukt:* {msg}", chat_id=str(chat_id))


# ==========================================
# MAIN ENTRYPOINT
# ==========================================

async def post_init(application: Application):
    """Sets up official Telegram blue menu button commands on startup."""
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Hoofdmenu"),
            BotCommand("help", "ℹ️ Alle functies en uitleg"),
            BotCommand("boodschappen", "🛒 Boodschappenlijst"),
            BotCommand("marleen", "🍲 MarleenKookt Menu"),
            BotCommand("hass", "💡 Home Assistant"),
            BotCommand("status", "🔍 Status controleren")
        ])
        logger.info("Bot commands menu registered successfully.")
    except Exception as e:
        logger.warning(f"Could not register bot commands menu: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)


async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is empty! Please check your configuration.")
        return

    logger.info("Initializing Telegram bot application...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Core & Navigation
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("test", test_command))

    # Boodschappen
    application.add_handler(CommandHandler("boodschappen", boodschappen_command))
    application.add_handler(CommandHandler("lijst", boodschappen_command))
    application.add_handler(CommandHandler("koop", koop_command))
    application.add_handler(CommandHandler("add", koop_command))
    application.add_handler(CommandHandler("wis", wis_boodschappen_command))

    # Home Assistant
    application.add_handler(CommandHandler("hass", hass_command))
    application.add_handler(CommandHandler("ha", hass_command))
    application.add_handler(CommandHandler("lichten", lichten_command))
    application.add_handler(CommandHandler("schakelaars", schakelaars_command))

    # MarleenKookt
    application.add_handler(CommandHandler("marleen", marleen_command))
    application.add_handler(CommandHandler("maaltijden", menu_command))
    application.add_handler(CommandHandler("kies", kies_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(CommandHandler("screenshot", screenshot_command))

    # Bottom Persistent Menu Button Handler (when user taps buttons on their keyboard)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_button_handler))

    # Unified Callback Query Handler
    application.add_handler(CallbackQueryHandler(callback_handler))

    # Error handler
    application.add_error_handler(error_handler)

    # Start APScheduler
    scheduler.start()

    logger.info("Starting bot polling...")
    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("AartvanderNeerbot is active and ready!")

        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
