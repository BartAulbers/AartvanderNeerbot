import json
import logging
import os
from typing import List, Dict, Optional, Tuple
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import DATA_DIR

logger = logging.getLogger(__name__)

class GroceryManager:
    def __init__(self, data_dir: str = DATA_DIR):
        self.file_path = os.path.join(data_dir, "groceries.json")
        os.makedirs(data_dir, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load(self) -> List[Dict]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading groceries: {e}")
            return []

    def _save(self, items: List[Dict]):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving groceries: {e}")

    def add_items(self, raw_input: str, added_by: str = "") -> List[str]:
        """Parses comma or newline separated text and adds new items."""
        lines = [item.strip() for part in raw_input.replace("\n", ",").split(",") for item in [part.strip()] if item]
        if not lines:
            return []

        items = self._load()
        next_id = max([it.get("id", 0) for it in items], default=0) + 1

        added = []
        for name in lines:
            # Avoid exact duplicate of unchecked items
            exists = any(it["name"].lower() == name.lower() and not it.get("checked", False) for it in items)
            if not exists:
                items.append({
                    "id": next_id,
                    "name": name,
                    "checked": False,
                    "added_by": added_by
                })
                next_id += 1
                added.append(name)

        self._save(items)
        return added

    def toggle_item(self, item_id: int) -> Optional[Dict]:
        """Toggles the checked state of an item."""
        items = self._load()
        for it in items:
            if it.get("id") == item_id:
                it["checked"] = not it.get("checked", False)
                self._save(items)
                return it
        return None

    def clear_checked(self) -> int:
        """Removes all checked items."""
        items = self._load()
        remaining = [it for it in items if not it.get("checked", False)]
        removed_count = len(items) - len(remaining)
        self._save(remaining)
        return removed_count

    def clear_all(self) -> int:
        """Clears all items."""
        items = self._load()
        count = len(items)
        self._save([])
        return count

    def get_view(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Generates formatted message and interactive checklist buttons."""
        items = self._load()

        if not items:
            text = (
                "🛒 *Boodschappenlijst*\n\n"
                "_De lijst is momenteel helemaal leeg!_\n\n"
                "💡 *Items toevoegen:*\n"
                "• Typ direct in de chat: `/koop melk, eieren, koffie`\n"
                "• Of gebruik de knop hieronder!"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Item toevoegen", callback_data="groceries_prompt_add")],
                [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
            ])
            return text, keyboard

        unchecked = [it for it in items if not it.get("checked", False)]
        checked = [it for it in items if it.get("checked", False)]

        text = "🛒 *Boodschappenlijst*\n\n"
        buttons = []

        if unchecked:
            text += "*Nog te halen:*\n"
            row = []
            for it in unchecked:
                text += f"▫️ {it['name']}\n"
                row.append(InlineKeyboardButton(f"⬜ {it['name'][:18]}", callback_data=f"groc_toggle_{it['id']}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)

        if checked:
            text += "\n*Al afgevinkt:*\n"
            row = []
            for it in checked:
                text += f"▪️ ~{it['name']}~\n"
                row.append(InlineKeyboardButton(f"✅ {it['name'][:18]}", callback_data=f"groc_toggle_{it['id']}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)

        action_row = []
        if checked:
            action_row.append(InlineKeyboardButton("🧹 Afgevinkte wissen", callback_data="groc_clear_checked"))
        action_row.append(InlineKeyboardButton("🗑️ Alles wissen", callback_data="groc_clear_all"))

        buttons.append(action_row)
        buttons.append([
            InlineKeyboardButton("➕ Voeg toe via /koop", callback_data="groceries_prompt_add"),
            InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")
        ])

        return text, InlineKeyboardMarkup(buttons)
