import asyncio
import logging
import os
import re
from typing import Tuple, Optional, Dict, Any, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bot.config import MARLEENKOOKT_EMAIL, MARLEENKOOKT_PASSWORD, DATA_DIR

logger = logging.getLogger(__name__)

class MarleenChecker:
    def __init__(self):
        self.data_dir = DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.screenshot_path = os.path.join(self.data_dir, "debug_screenshot.png")
        self.storage_state_path = os.path.join(self.data_dir, "marleen_state.json")

    async def _login_and_navigate(self, page, target_url: str = "https://app.marleenkookt.nl/bestellen"):
        """Helper to ensure logged in state and navigate to target URL."""
        await page.goto("https://app.marleenkookt.nl/login", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2000)

        # Handle cookie banner
        try:
            cookie_btn = page.locator("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll, button:has-text('Sta Cookies toe')")
            if await cookie_btn.count() > 0 and await cookie_btn.first.is_visible():
                await cookie_btn.first.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        email_input = page.locator("input#email, input[type='email']")
        if await email_input.count() > 0 and await email_input.first.is_visible():
            logger.info("Logging into MarleenKookt...")
            await email_input.first.fill(MARLEENKOOKT_EMAIL)
            pw_input = page.locator("input#password, input[type='password']")
            if await pw_input.count() > 0:
                await pw_input.first.fill(MARLEENKOOKT_PASSWORD)
            submit_btn = page.locator("button[type='submit'], button:has-text('Inloggen')")
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
                await page.wait_for_timeout(4000)

        # Navigate to target if needed
        if target_url not in page.url:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)

    async def check_meals_selected(self) -> Tuple[Optional[bool], str, Optional[Dict[str, Any]]]:
        """
        Logs into app.marleenkookt.nl and inspects upcoming meal deliveries.
        """
        if not MARLEENKOOKT_EMAIL or not MARLEENKOOKT_PASSWORD:
            logger.warning("MarleenKookt credentials not configured in environment variables.")
            return None, "Geen inloggegevens ingesteld in .env (MARLEENKOOKT_EMAIL / MARLEENKOOKT_PASSWORD).", None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )

            context_kwargs = {
                "viewport": {"width": 1280, "height": 900},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
            if os.path.exists(self.storage_state_path):
                context_kwargs["storage_state"] = self.storage_state_path

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            try:
                await self._login_and_navigate(page, "https://app.marleenkookt.nl/")
                await page.screenshot(path=self.screenshot_path, full_page=True)

                # Extract all upcoming deliveries from the dashboard
                deliveries = await page.evaluate('''() => {
                    const results = [];
                    const dayRegex = /(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\\s+\\d+/i;
                    
                    // Look in sections or main containers
                    const elements = Array.from(document.querySelectorAll("button, a, div.relative"));
                    
                    for (const el of elements) {
                        const text = el.innerText ? el.innerText.trim() : "";
                        const lines = text.split("\\n").map(l => l.trim()).filter(l => l.length > 0);
                        if (lines.length >= 2 && dayRegex.test(lines[0])) {
                            // Check if already captured same date to avoid nested duplicates
                            const date = lines[0];
                            if (!results.some(r => r.date === date)) {
                                const href = el.getAttribute("href") || (el.querySelector("a") ? el.querySelector("a").getAttribute("href") : null);
                                results.push({
                                    date: date,
                                    details: lines.slice(1).join(" · "),
                                    rawText: text,
                                    href: href
                                });
                            }
                        }
                    }
                    return results;
                }''')

                if not deliveries:
                    # Fallback check on full page text
                    body_text = (await page.inner_text("body")).lower()
                    if "nog kiezen" in body_text:
                        return False, "Nog maaltijden te kiezen gevonden op het dashboard.", None
                    if "gekozen" in body_text:
                        return True, "Maaltijden lijken al gekozen te zijn.", None
                    return None, "Geen leveringen gevonden op het dashboard.", None

                # Find the first upcoming box that has not been delivered yet
                # Filter out boxes that are already past/delivered ('Bezorgd')
                active_deliveries = []
                for d in deliveries:
                    text_lower = d["rawText"].lower()
                    if "bezorgd" in text_lower or "afgeleverd" in text_lower:
                        continue
                    active_deliveries.append(d)

                if not active_deliveries:
                    # All visible deliveries were already marked as delivered
                    return True, "Alle zichtbare leveringen zijn al bezorgd.", None

                # The first upcoming delivery is active_deliveries[0]
                target = active_deliveries[0]
                date_str = target["date"]
                details = target["details"]
                card_href = target["href"]
                if card_href and not card_href.startswith("http"):
                    card_href = f"https://app.marleenkookt.nl{card_href}"

                info = {
                    "date": date_str,
                    "details": details,
                    "order_url": card_href or "https://app.marleenkookt.nl/bestellen"
                }

                target_text = target["rawText"].lower()

                # Check if this box is already chosen / on its way
                if "komt eraan" in target_text or "gekozen" in target_text or "bevestigd" in target_text:
                    return True, f"Al geregeld voor eerstvolgende levering: {date_str} ({details})", info
                elif "nog kiezen" in target_text:
                    return False, f"Nog niet gekozen voor eerstvolgende levering: {date_str} ({details})", info
                else:
                    return False, f"Status niet eenduidig voor eerstvolgende levering: {date_str}", info

            except Exception as e:
                logger.error(f"Error checking meal status: {e}", exc_info=True)
                return None, f"Fout bij controleren: {e}", None
            finally:
                await browser.close()

    async def get_all_menus(self) -> Dict[str, Any]:
        """
        Scrapes all available week boxes and the complete dish list for each week.
        """
        if not MARLEENKOOKT_EMAIL or not MARLEENKOOKT_PASSWORD:
            return {"error": "Geen inloggegevens ingesteld in .env."}

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                await self._login_and_navigate(page, "https://app.marleenkookt.nl/bestellen")

                # Locate week tabs
                week_btns = page.locator("button:has-text('Week ')")
                week_count = await week_btns.count()

                weeks_data = []
                for w_idx in range(min(week_count, 3)):  # Normally 3 upcoming weeks
                    btn = week_btns.nth(w_idx)
                    btn_text = (await btn.inner_text()).replace("\n", " ").strip()
                    if w_idx > 0:
                        await btn.click()
                        await page.wait_for_timeout(1200)

                    # Extract all dishes on this week
                    dishes = await page.evaluate('''() => {
                        const results = [];
                        const buttons = Array.from(document.querySelectorAll("button[aria-label='Maaltijd toevoegen'], button[aria-label='Meer']"));
                        for (let i = 0; i < buttons.length; i++) {
                            const btn = buttons[i];
                            let card = btn.closest(".group") || btn.closest(".relative") || btn.parentElement.parentElement;
                            let heading = card.querySelector("h2, h3, h4, [class*='font-bold'], [class*='font-semibold']");
                            let title = heading ? heading.innerText.trim() : card.innerText.split("\\n")[0].trim();
                            
                            // Check if minus button exists (indicates item has quantity selected!)
                            const allButtons = Array.from(card.querySelectorAll("button"));
                            const hasMinus = allButtons.some(b => b.getAttribute("aria-label") === "Minder" || b.innerText.includes("−") || b.innerText.includes("-"));

                            let quantity = 0;
                            if (hasMinus) {
                                quantity = 1;
                                const textLines = card.innerText.split("\\n").map(l => l.trim());
                                for (const l of textLines) {
                                    if (/^[1-9][0-9]?x?$/i.test(l)) {
                                        quantity = parseInt(l);
                                        break;
                                    }
                                }
                            }

                            // Extract badges/tags and deduplicate
                            const rawTags = Array.from(card.querySelectorAll("span, [class*='badge']"))
                                .map(s => s.innerText.trim())
                                .filter(t => t.length > 0 && t !== "+" && t !== "−" && t !== "-" && t !== title && !/^[0-9]+$/.test(t));
                            const tags = Array.from(new Set(rawTags));

                            results.push({
                                index: i + 1,
                                title: title,
                                tags: tags.slice(0, 3),
                                is_selected: hasMinus || quantity > 0,
                                quantity: quantity
                            });
                        }
                        return results;
                    }''')

                    weeks_data.append({
                        "week_index": w_idx,
                        "label": btn_text,
                        "dishes": dishes
                    })

                return {"weeks": weeks_data}
            except Exception as e:
                logger.error(f"Error scraping menus: {e}", exc_info=True)
                return {"error": str(e)}
            finally:
                await browser.close()

    async def select_and_save_meals(self, dish_indices: List[int], week_index: int = 0) -> Tuple[bool, str, List[str]]:
        """
        Selects dishes by their 1-based index for a specific week and clicks 'Opslaan'.
        
        Returns:
            Tuple[bool, str, List[str]]:
                (success, message, list_of_selected_meal_titles)
        """
        if not MARLEENKOOKT_EMAIL or not MARLEENKOOKT_PASSWORD:
            return False, "Geen inloggegevens ingesteld in .env.", []

        if not dish_indices:
            return False, "Geen maaltijdnummers opgegeven.", []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                await self._login_and_navigate(page, "https://app.marleenkookt.nl/bestellen")

                # Switch to desired week if needed
                week_btns = page.locator("button:has-text('Week ')")
                week_count = await week_btns.count()
                if week_index < week_count:
                    await week_btns.nth(week_index).click()
                    await page.wait_for_timeout(2000)

                # Reset any already added items to start fresh
                minus_btns = page.locator("button[aria-label='Minder']")
                m_count = await minus_btns.count()
                for _ in range(m_count * 2):
                    if await minus_btns.count() > 0:
                        try:
                            await minus_btns.first.click()
                            await page.wait_for_timeout(300)
                        except Exception:
                            break
                    else:
                        break

                # Extract titles for all dishes on page
                dishes = await page.evaluate('''() => {
                    const buttons = Array.from(document.querySelectorAll("button[aria-label='Maaltijd toevoegen'], button[aria-label='Meer']"));
                    return buttons.map((btn, i) => {
                        let card = btn.closest(".group") || btn.closest(".relative") || btn.parentElement.parentElement;
                        let heading = card.querySelector("h2, h3, h4, [class*='font-bold'], [class*='font-semibold']");
                        return heading ? heading.innerText.trim() : "Gerecht " + (i + 1);
                    });
                }''')

                selected_titles = []
                # Click the add button for each requested dish
                add_buttons = page.locator("button[aria-label='Maaltijd toevoegen'], button[aria-label='Meer']")
                total_buttons = await add_buttons.count()

                for idx in dish_indices:
                    zero_based = idx - 1
                    if 0 <= zero_based < total_buttons:
                        btn = add_buttons.nth(zero_based)
                        await btn.click()
                        await page.wait_for_timeout(600)
                        dish_name = dishes[zero_based] if zero_based < len(dishes) else f"Gerecht #{idx}"
                        selected_titles.append(dish_name)
                    else:
                        logger.warning(f"Dish index {idx} out of range (max {total_buttons})")

                if not selected_titles:
                    return False, "Geen geldige gerechten gevonden voor de opgegeven nummers.", []

                # Now locate and click the 'Opslaan' button
                await page.wait_for_timeout(1000)
                save_btn = page.locator("button:has-text('Opslaan'), button:has-text('Keuze opslaan')")
                if await save_btn.count() == 0 or await save_btn.first.is_disabled():
                    # Fallback: check if 'Kies maaltijden' or bottom bar exists
                    save_btn = page.locator("div[class*='fixed'] button:has-text('Kies maaltijden')")

                if await save_btn.count() > 0:
                    logger.info("Clicking 'Opslaan' button...")
                    await save_btn.first.click()
                    await page.wait_for_timeout(4000)

                    # Save screenshot of confirmation
                    await page.screenshot(path=self.screenshot_path, full_page=True)

                    # Check tab text
                    tab_text = (await page.inner_text("body")).lower()
                    success = "opgeslagen" in tab_text or "gekozen" in tab_text or "bevestigd" in tab_text or "dank" in tab_text

                    return True, "Maaltijdkeuze succesvol opgeslagen bij MarleenKookt!", selected_titles
                else:
                    await page.screenshot(path=self.screenshot_path, full_page=True)
                    return False, "Knop 'Opslaan' kon niet worden gevonden of was uitgeschakeld.", selected_titles

            except Exception as e:
                logger.error(f"Error selecting meals: {e}", exc_info=True)
                return False, f"Fout bij selecteren: {e}", []
            finally:
                await browser.close()
