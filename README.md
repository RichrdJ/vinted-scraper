<div align="center">
  <img src="https://raw.githubusercontent.com/RichrdJ/vinted-scraper/main/docs/banner.svg" alt="Vinted Monitor" width="100%"/>
</div>

<br>

<div align="center">
  <a href="https://github.com/RichrdJ/vinted-scraper/pkgs/container/vinted-scraper"><img src="https://img.shields.io/badge/ghcr.io-vinted--scraper-09b1ba?style=flat-square&logo=docker&logoColor=white" alt="Docker"/></a>
  <a href="https://github.com/RichrdJ/vinted-scraper/actions"><img src="https://img.shields.io/github/actions/workflow/status/RichrdJ/vinted-scraper/docker.yml?style=flat-square&label=build&color=09b1ba" alt="Build"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-09b1ba?style=flat-square" alt="License"/></a>
</div>

<br>

Nooit meer een koopje missen op Vinted. Stel zoekopdrachten in en ontvang direct een
melding zodra er een nieuw artikel verschijnt — via **Telegram**, **ntfy** of een
**RSS-feed**, en beheer alles via de webinterface.

Werkt op elk Vinted-domein (`.nl`, `.be`, `.de`, `.fr`, …): plak gewoon de zoek-URL uit
je browser.

> (AGPL-3.0), herschreven met een eenvoudiger single-process ontwerp, een nieuwe
> webinterface en ntfy-ondersteuning.

---

## ✨ Functies

- **Meerdere zoekopdrachten**: monitor zoveel Vinted-URL's als je wilt, elk met een eigen naam
- **Alleen nieuwe artikelen**: de eerste run legt het startpunt vast zonder meldingen, daarna krijg je alleen wat er nieuw bijkomt
- **Telegram**: meldingen met foto, prijs, merk, maat en een "Open op Vinted"-knop, plus commando's om zoekopdrachten vanuit de chat te beheren
- **ntfy**: pushmeldingen op je telefoon via [ntfy.sh](https://ntfy.sh) of een eigen server
- **RSS**: abonneer je op `/feed.xml` in elke feedreader
- **Webinterface met dark mode**: dashboard, zoekopdrachten, gevonden artikelen, instellingen en logs
- **Land-allowlist**: alleen meldingen van verkopers uit gekozen landen
- **Banwoorden**: sla artikelen over met ongewenste woorden in de titel
- **Proxy-ondersteuning**: optionele proxypool met parallelle health-checks
- **Docker-ready**: één `docker-compose.yml` en je bent live, met image op GHCR
- **Persistente opslag**: SQLite met WAL-mode, data overleeft container-restarts

---

## 📸 Screenshots

<div align="center">
  <img src="docs/screenshots/dashboard.png" alt="Dashboard" width="100%"/>
  <br><sub><b>Dashboard</b>: statistieken, actieve kanalen en het laatst gevonden artikel</sub>
</div>

<br>

<div align="center">
  <img src="docs/screenshots/items.jpg" alt="Gevonden artikelen" width="100%"/>
  <br><sub><b>Gevonden artikelen</b>: met foto, prijs, merk en maat</sub>
</div>

<br>

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/searches.png" alt="Zoekopdrachten"/><br><sub><b>Zoekopdrachten</b>: plak een Vinted-URL en klaar</sub></td>
    <td width="50%"><img src="docs/screenshots/config.png" alt="Instellingen"/><br><sub><b>Instellingen</b>: Telegram, ntfy, RSS, proxies en allowlist</sub></td>
  </tr>
</table>

---

## 🚀 Snel starten

### Vereisten
- Docker + Docker Compose (of Portainer)
- Draait op `amd64` én `arm64` (Raspberry Pi, Synology, Apple Silicon)

### 1. Maak een `docker-compose.yml` (of plak dit als stack in Portainer)

```yaml
services:
  vinted-monitor:
    image: ghcr.io/richrdj/vinted-scraper:latest
    pull_policy: always
    container_name: vinted-monitor
    ports:
      - "8344:8344"
    volumes:
      - vinted_data:/app/data
    restart: unless-stopped
    environment:
      TZ: Europe/Amsterdam

volumes:
  vinted_data:
```

### 2. Start de container

```bash
docker compose up -d
```

### 3. Open de webinterface

Ga naar `http://localhost:8344` (of het IP van je server), schakel een kanaal in onder
**Config** en voeg een zoekopdracht toe onder **Searches**.

> **Updaten:** `docker compose pull && docker compose up -d`, of in Portainer
> *Update the stack* met *Re-pull image*. Je data blijft bewaard in het volume
> `vinted_data`.

Liever zelf bouwen? `git clone` deze repo en draai `docker build -t vinted-scraper .`.

## 🐍 Lokaal draaien

Vereist Python 3.9+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## ⚙️ Hoe het werkt

```
                ┌───────────────┐   nieuwe items   ┌──────────────┐
  APScheduler ─▶│  scrape_once  │─────────────────▶│  notifiers   │─▶ Telegram / ntfy
   (interval)   │ (catalog HTML)│                  └──────────────┘
                └──────┬────────┘
                       │ opslaan (dedupe)
                       ▼
                 SQLite (data/) ◀── Webinterface (Flask) ──▶ /feed.xml (RSS)
```

**Waarom HTML en geen API?** De JSON-API van Vinted (`/api/v2/catalog/items`) zit
tegenwoordig achter Cloudflare + DataDome bot-bescherming en geeft scripts een 404.
De gewone catalogus*pagina* laadt nog wel, dus vinted-scraper haalt die op met
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) (echte Chrome TLS-fingerprint) en
leest de artikelen uit de ingebedde Next.js-data. Dat is robuuster dan de oudere
API-aanpak.

**Nieuw-detectie** gebeurt op basis van het artikel-ID, dat bij Vinted alleen maar
oploopt. Per zoekopdracht wordt het hoogste gezien ID bewaard; alleen hogere ID's zijn
nieuw.

---

## 🔧 Configuratie

Alle instellingen staan in de database en zijn live aan te passen via **Config**.
Omgevingsvariabelen (in de `environment:`-sectie van je stack, of in `.env` bij lokaal
draaien, zie [`.env.example`](.env.example)) worden alleen bij de eerste start ingezaaid (zet `FORCE_` ervoor
om ze bij elke start te overschrijven). `WEB_HOST`, `WEB_PORT`, `WEB_USERNAME` en
`WEB_PASSWORD` komen altijd uit de omgeving. Met `WEB_USERNAME` en `WEB_PASSWORD`
zet je basic-auth op het dashboard.

### Telegram

1. Maak een bot via [@BotFather](https://t.me/BotFather) en kopieer de token.
2. Zoek je chat-ID (bijv. via [@userinfobot](https://t.me/userinfobot), of het ID van je groep).
3. Zet onder **Config → Telegram** het vinkje aan en vul token en chat-ID in.
4. Herstart om de commandobot te activeren en stuur `/help` naar je bot.

**Commando's:** `/add <url> [naam]`, `/queries`, `/remove <nr|all>`, `/allow <XX>`,
`/disallow <XX>`, `/allowlist`, `/status`.

### ntfy

1. Kies een moeilijk te raden topicnaam en abonneer je erop in de ntfy-app.
2. Zet onder **Config → ntfy** het vinkje aan en vul het topic in (plus een token als je server dat vereist).

### RSS

Zet RSS aan onder **Config → RSS** en abonneer je op `http://<host>:8344/feed.xml`.

### Proxies

Voeg proxies toe (gescheiden door `;`, bijv. `http://user:pass@host:port`) en/of een
URL met een proxylijst. Met *validate proxies* worden ze vooraf getest.

---

## 📁 Projectstructuur

| Pad | Doel |
|-----|------|
| `main.py` | Startpunt: scheduler + bot-thread + webinterface |
| `scraper.py` | URL-normalisatie, pollen, dedupe, meldingen versturen |
| `vinted/` | Vinted-client (HTML ophalen + parsen) |
| `notifiers/` | Telegram- en ntfy-kanalen |
| `bot.py` | Optionele Telegram-commandobot |
| `webui/` | Flask-dashboard (templates + static) |
| `db.py` / `schema.sql` | SQLite-opslag |
| `proxies.py` | Optionele proxypool |
| `config.py` | Instellingen inzaaien vanuit de omgeving |

---

## ⚠️ Goed om te weten

- Houd het interval redelijk (60 s of meer). Te vaak pollen kan leiden tot rate-limiting;
  verhoog dan het interval of gebruik proxies.
- Vinted kan de paginastructuur op elk moment wijzigen. Geven zoekopdrachten ineens 0
  resultaten, kijk dan in **Logs**; de parser in `vinted/client.py` moet dan mogelijk
  worden bijgewerkt.
- De land-allowlist kost één extra request per nieuw artikel (de zoekpagina bevat het
  land van de verkoper niet). Laat hem leeg als je hem niet nodig hebt.
- Bedoeld voor persoonlijk gebruik; respecteer de voorwaarden van Vinted.

## 📄 Licentie

AGPL-3.0, zie [LICENSE](LICENSE) en [NOTICE](NOTICE). Omdat dit project is afgeleid van
Fuyucch1/Vinted-Notifications geldt dezelfde licentie.
