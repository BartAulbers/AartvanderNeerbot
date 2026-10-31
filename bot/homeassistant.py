import logging
from typing import List, Dict, Optional, Tuple, Any
import httpx
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import HASS_URL, HASS_TOKEN

logger = logging.getLogger(__name__)

class HomeAssistantClient:
    def __init__(self, url: str = HASS_URL, token: str = HASS_TOKEN):
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.url and self.token)

    async def check_connection(self) -> Tuple[bool, str]:
        if not self.is_configured():
            return False, "Home Assistant is nog niet geconfigureerd in `.env` (vul `HASS_URL` en `HASS_TOKEN` in)."

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.url}/api/", headers=self.headers)
                if res.status_code == 200:
                    data = res.json()
                    return True, data.get("message", "API running.")
                elif res.status_code == 401:
                    return False, "Authenticatie mislukt: controleer je `HASS_TOKEN` in `.env`."
                else:
                    return False, f"Server gaf HTTP status {res.status_code}."
        except httpx.ConnectError:
            return False, f"Kon geen verbinding maken met {self.url}. Controleer of Home Assistant bereikbaar is vanaf je NAS."
        except Exception as e:
            return False, f"Verbindingsfout: {e}"

    async def get_states(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches states of entities, optionally filtered by domain (e.g. 'light', 'switch', 'scene')."""
        if not self.is_configured():
            return []

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(f"{self.url}/api/states", headers=self.headers)
                if res.status_code != 200:
                    logger.error(f"Failed to fetch HASS states: {res.status_code}")
                    return []
                states = res.json()
                if domain:
                    states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
                return states
        except Exception as e:
            logger.error(f"Error fetching states from Home Assistant: {e}")
            return []

    async def call_service(self, domain: str, service: str, entity_id: str) -> Tuple[bool, str]:
        """Calls a Home Assistant service like light.toggle or scene.turn_on."""
        if not self.is_configured():
            return False, "Home Assistant is niet geconfigureerd."

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                payload = {"entity_id": entity_id}
                res = await client.post(
                    f"{self.url}/api/services/{domain}/{service}",
                    headers=self.headers,
                    json=payload
                )
                if res.status_code in (200, 201):
                    return True, f"Actie {domain}.{service} succesvol uitgevoerd op {entity_id}."
                else:
                    return False, f"Fout bij uitvoeren actie: HTTP {res.status_code} ({res.text[:100]})."
        except Exception as e:
            logger.error(f"Error calling HASS service: {e}")
            return False, f"Verbindingsfout: {e}"

    async def toggle_entity(self, entity_id: str) -> Tuple[bool, str]:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "toggle", entity_id)

    async def activate_scene(self, scene_id: str) -> Tuple[bool, str]:
        return await self.call_service("scene", "turn_on", scene_id)

    async def get_dashboard_view(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Main Home Assistant overview in Telegram."""
        if not self.is_configured():
            text = (
                "💡 *Home Assistant*\n\n"
                "⚠️ *Nog niet gekoppeld!*\n\n"
                "Koppel Home Assistant door in je `.env` bestand het volgende in te vullen:\n"
                "```env\n"
                "HASS_URL=http://<ip-of-naam-van-homeassistant>:8123\n"
                "HASS_TOKEN=jouw_long_lived_access_token\n"
                "```\n"
                "_(Je genereert een token in Home Assistant linksonder bij je profielnaam -> Beveiliging -> Tokens voor lange levensduur)._"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
            ])
            return text, keyboard

        ok, msg = await self.check_connection()
        if not ok:
            text = (
                f"💡 *Home Assistant*\n\n"
                f"❌ *Verbinding mislukt:*\n_{msg}_\n\n"
                f"URL: `{self.url}`\n"
                f"Controleer of de URL klopt en Home Assistant aanstaat."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Opnieuw proberen", callback_data="hass_nav_main")],
                [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
            ])
            return text, keyboard

        text = (
            "💡 *Home Assistant Bediening*\n\n"
            "Verbonden met je slimme woning! Kies wat je wilt bedienen of bekijken:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💡 Verlichting", callback_data="hass_list_light"),
                InlineKeyboardButton("⚡ Schakelaars", callback_data="hass_list_switch")
            ],
            [
                InlineKeyboardButton("🎬 Scènes", callback_data="hass_list_scene"),
                InlineKeyboardButton("🌡️ Sensoren / Status", callback_data="hass_list_sensor")
            ],
            [
                InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")
            ]
        ])
        return text, keyboard

    async def get_domain_view(self, domain: str) -> Tuple[str, InlineKeyboardMarkup]:
        """Lists entities for a specific domain with toggle buttons."""
        states = await self.get_states(domain=domain)

        domain_titles = {
            "light": ("💡 *Verlichting*", "lampen"),
            "switch": ("⚡ *Schakelaars*", "schakelaars"),
            "scene": ("🎬 *Scènes*", "scènes"),
            "sensor": ("🌡️ *Belangrijke Sensoren*", "sensoren")
        }
        title, noun = domain_titles.get(domain, (f"📦 *{domain.capitalize()}*", domain))

        if not states:
            text = f"{title}\n\n_Geen {noun} gevonden in Home Assistant._"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Terug naar Home Assistant", callback_data="hass_nav_main")],
                [InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")]
            ])
            return text, keyboard

        text = f"{title}\nTik op een knop om te schakelen:\n\n"
        buttons = []

        # Sort by friendly name
        states = sorted(states, key=lambda s: s.get("attributes", {}).get("friendly_name", s["entity_id"]))

        if domain in ("light", "switch"):
            for s in states[:15]:  # limit to top 15 to fit in Telegram markup
                eid = s["entity_id"]
                name = s.get("attributes", {}).get("friendly_name", eid.split(".")[-1])[:20]
                is_on = s.get("state") == "on"
                icon = "🟢" if is_on else "⚪"
                buttons.append([InlineKeyboardButton(f"{icon} {name}", callback_data=f"hass_toggle_{eid}")])
        elif domain == "scene":
            for s in states[:12]:
                eid = s["entity_id"]
                name = s.get("attributes", {}).get("friendly_name", eid.split(".")[-1])[:22]
                buttons.append([InlineKeyboardButton(f"▶️ {name}", callback_data=f"hass_scene_{eid}")])
        elif domain == "sensor":
            # Filter to interesting sensors like temperature, humidity, power
            interesting = [
                s for s in states
                if any(k in s["entity_id"] or k in s.get("attributes", {}).get("device_class", "")
                       for k in ["temp", "humid", "battery", "power", "energy", "climate"])
            ][:15]
            if not interesting:
                interesting = states[:15]
            for s in interesting:
                name = s.get("attributes", {}).get("friendly_name", s["entity_id"].split(".")[-1])
                val = s.get("state", "?")
                unit = s.get("attributes", {}).get("unit_of_measurement", "")
                text += f"• *{name}:* `{val} {unit}`\n"

        buttons.append([
            InlineKeyboardButton("🔄 Verversen", callback_data=f"hass_list_{domain}"),
            InlineKeyboardButton("🔙 Terug", callback_data="hass_nav_main")
        ])
        buttons.append([InlineKeyboardButton("🏠 Hoofdmenu", callback_data="nav_main_menu")])

        return text, InlineKeyboardMarkup(buttons)
