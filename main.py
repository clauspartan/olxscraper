import json
import os
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests

# ==========================================
# CONFIGURARE
# ==========================================
# Citim Webhook-ul din GitHub Secrets (pentru securitate) sau fallback direct
DISCORD_WEBHOOK_URL: str = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1541816768064921693/BCk0SodiPmtXuK3-OBdMRczoHl8SwhC6rDXBxYD5uhjpuEJ1aCMaAO7vvIM_HaOkGeK4",
)
SEARCH_QUERY: str = "ps3"
MIN_PRICE: int = 150
MAX_PRICE: int = 300
DB_FILE: str = "seen_listings.json"

BLACKLIST: list[str] = [
    "cazare", "hotelier", "husa", "canapea", "ikea",
    "volan", "pedale", "maneta", "controller", "controler",
    "ps5", "playstation 5", "ps4", "playstation 4",
    "ps2", "playstation 2", "ps1", "playstation 1",
    "xbox", "switch"
]


def load_seen_listings() -> dict[str, int]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_seen_listings(data: dict[str, int]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def send_discord_alert(
    title: str,
    price: int,
    link: str,
    is_price_drop: bool = False,
    old_price: int = 0,
) -> None:
    if not DISCORD_WEBHOOK_URL:
        return

    embed: dict[str, Any] = {
        "title": "🚨 PRICE DROP ALERT!" if is_price_drop else "🎮 NEW PS3 FOUND!",
        "description": f"**[{title}]({link})**",
        "color": 3066993 if not is_price_drop else 15158332,
        "fields": [
            {
                "name": "Price",
                "value": (
                    f"~~{old_price} RON~~ ➡️ **{price} RON**"
                    if is_price_drop
                    else f"**{price} RON**"
                ),
                "inline": True,
            },
            {"name": "Platform", "value": "OLX.ro", "inline": True},
        ],
        "footer": {"text": "clau original ps3 tracker™️"},
    }

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            data=json.dumps({"username": "Spidey Bot", "embeds": [embed]}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as e:
        print(f"[DISCORD ERROR] {e}")


def check_olx() -> None:
    url = (
        f"https://www.olx.ro/oferte/q-{SEARCH_QUERY}/"
        f"?search%5Bfilter_float_price%3Afrom%5D={MIN_PRICE}"
        f"&search%5Bfilter_float_price%3Ato%5D={MAX_PRICE}"
    )

    try:
        response = requests.get(url, impersonate="chrome", timeout=15)
        print(f"[DEBUG] HTTP Status: {response.status_code}")
        if response.status_code != 200:
            return

        soup = BeautifulSoup(response.text, "html.parser")
        listings = (
            soup.find_all("div", data_testid="l-card")
            or soup.find_all("div", {"data-cy": "l-card"})
            or soup.find_all("div", class_=lambda c: c and "card" in c.lower())
        )
        print(f"[DEBUG] Găsite {len(listings)} anunțuri pe OLX")

        seen_listings = load_seen_listings()
        has_changes = False

        for item in listings:
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            raw_href = str(link_elem["href"])
            if not ("/d/oferta/" in raw_href or raw_href.endswith(".html")):
                continue

            link = f"https://www.olx.ro{raw_href}" if raw_href.startswith("/") else raw_href
            ad_id = str(item.get("id")) if item.get("id") else raw_href.split("/")[-1]

            title_elem = item.find(["h4", "h6"])
            title = title_elem.text.strip() if (title_elem and title_elem.text.strip()) else link_elem.text.strip()
            if not title:
                title = "PS3 Console"

            price_elem = item.find(["p", "span", "div"], attrs={"data-testid": "ad-price"})
            price_text = price_elem.text.strip() if price_elem else ""
            raw_price = "".join(filter(str.isdigit, price_text))
            price = int(raw_price) if raw_price else 0

            if price < MIN_PRICE or price > MAX_PRICE:
                continue

            if any(word in title.lower() for word in BLACKLIST):
                continue

            # Verificare anunț nou sau scădere de preț
            if ad_id not in seen_listings:
                print(f"[NEW] {title} - {price} RON")
                seen_listings[ad_id] = price
                has_changes = True
                send_discord_alert(title, price, link)
            else:
                old_price = seen_listings[ad_id]
                if 0 < price < old_price:
                    print(f"[PRICE DROP] {title}: {old_price} -> {price} RON")
                    seen_listings[ad_id] = price
                    has_changes = True
                    send_discord_alert(title, price, link, is_price_drop=True, old_price=old_price)

        if has_changes:
            save_seen_listings(seen_listings)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    check_olx()
