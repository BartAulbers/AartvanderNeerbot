# AartvanderNeerbot 🤖🏠

Een centrale, veelzijdige Telegram assistent voor jullie huishouden (geschikt voor Synology NAS / Docker).

---

## 🌟 Wat kan de bot allemaal?

### 1. 🍲 MarleenKookt Beheer
- **Instelbare herinneringen:** Kies zelf via de knop **⏰ Herinnering Instellen** op welke dag van de week (bijv. Woensdag of Zondag) jullie de ochtend- (09:00) en avondherinnering (21:00) willen ontvangen. Keuzes worden opgeslagen en blijven bewaard na herstarts!
- **Menu bekijken:** Haalt live het menu op van alle komende weken (`/maaltijden` of via het menu) met directe laadmelding.
- **Direct bestellen in Telegram:** Typ bijvoorbeeld `/kies 1, 2, 4` of tik op de interactieve knoppen om gerechten te kiezen en direct op te slaan bij MarleenKookt.

### 2. 🛒 Gedeelde Boodschappenlijst
- **Interactieve afvinklijst:** Bekijk de lijst met `/lijst` of `/boodschappen`.
- **Snel toevoegen:** Typ in de chat:
  ```text
  /koop melk, eieren, koffiebonen, brood
  ```
- **Afvinken:** Tik op de knop van het artikel in Telegram om het direct af te vinken (`✅`) of weer terug te zetten (`⬜`).
- **Opschonen:** Verwijder alle afgevinkte artikelen met één druk op de knop (`🧹 Afgevinkte wissen`).
- **Bewaard op Synology:** De lijst wordt bewaard in `/app/data/groceries.json` en blijft bewaard na herstarts!

### 3. 💡 Home Assistant Integratie
- **Bediening via Telegram:** Schakel lampen en schakelaars direct in of uit via interactieve knoppen.
- **Scènes & Sensoren:** Activeer scènes (bijv. *Film kijken*, *Alles uit*) en bekijk live temperaturen en statussen.
- **Snelcommando's:**
  - `/hass` — Open het Home Assistant bedieningspaneel
  - `/lichten` — Overzicht van alle lampen met aan/uit schakelaars
  - `/schakelaars` — Overzicht van schakelaars

---

## 💬 Overzicht van Commando's

| Commando | Omschrijving |
|---|---|
| `/start` of `/menu` | **🏠 Hoofdmenu:** Open het centrale dashboard met alle subtaken |
| **Boodschappen** | |
| `/boodschappen` of `/lijst` | Toon de interactieve boodschappenlijst |
| `/koop <items>` | Voeg artikelen toe (bijv. `/koop melk, appels, kaas`) |
| `/wis` | Verwijder alle afgevinkte artikelen van de lijst |
| **Home Assistant** | |
| `/hass` of `/ha` | Open het Home Assistant paneel |
| `/lichten` | Bekijk en schakel verlichting |
| `/schakelaars` | Bekijk en schakel apparaten/schakelaars |
| **MarleenKookt** | |
| `/marleen` | Open het MarleenKookt menu |
| `/maaltijden` | Bekijk de actuele gerechten van alle boxen |
| `/kies 1, 2, 4` | Selecteer direct gerechten en bewaar ze bij MarleenKookt |
| `/status` | Controleer live of de maaltijden al gekozen zijn |
| `/screenshot` | Ontvang een screenshot van de MarleenKookt pagina |
| **Systeem** | |
| `/test` | Test alle drie de herinneringsberichten |
| `/chatid` | Toon het Chat ID en jouw persoonlijke User ID |

---

## 🛠️ Installatie op Synology NAS

### 1. Configuratie (.env)
Kopieer `.env.example` naar `.env` en vul je gegevens in:
```bash
cp .env.example .env
```

Belangrijke variabelen:
- `TELEGRAM_BOT_TOKEN`: Jouw bot token.
- `TELEGRAM_CHAT_ID`: Groeps-ID van jullie gezin/huishouden.
- `ADMIN_USER_ID`: `12528644` (jouw persoonlijke Telegram ID).
- `MARLEENKOOKT_EMAIL`: Jouw MarleenKookt e-mailadres.
- `MARLEENKOOKT_PASSWORD`: Jouw MarleenKookt wachtwoord.
- `HASS_URL`: URL naar Home Assistant (bijv. `http://192.168.1.100:8123` of `http://homeassistant.local:8123`).
- `HASS_TOKEN`: Long-Lived Access Token (in Home Assistant linksonder bij Profiel -> Beveiliging).

### 2. Draaien via Container Manager
1. Plaats de map `AartvanderNeerbot` in `/volume1/docker/AartvanderNeerbot`.
2. Zorg dat je `.env` bestand aanwezig is.
3. Open **Container Manager** op DSM:
   - Ga naar **Project** -> **Maken**.
   - Geef het project een naam: `aartvanderneerbot`.
   - Selecteer het pad `/volume1/docker/AartvanderNeerbot`.
   - Kies "Bestaande docker-compose.yml gebruiken".
   - Start het project!
