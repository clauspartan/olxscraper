import json
import os
from typing import Any
from bs4 import BeautifulSoup
from curl_cffi import requests

# ==========================================
# CONFIGURARE
# ==========================================
DISCORD_WEBHOOK_URL: str = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1541816768064921693/BCk0SodiPmtXuK3-OBdMRczoHl8SwhC6rDXBxYD5uhjpuEJ1aCMaAO7vvIM_HaOkGeK4",
)
SEARCH_QUERY: str = "ps3"
MIN_PRICE: float = 150.0
MAX_PRICE: float = 300.0
DB_FILE: str = "seen_listings.json"

BLACKLIST: list[str] = [
    "cazare", "hotelier", "husa", "canapea", "ikea",
    "volan", "pedale", "maneta", "controller", "controler",
    "ps5", "playstation 5", "ps4", "playstation 4",
    "ps2", "playstation 2", "ps1", "playstation 1",
    "xbox", "switch"
]


def load_seen_listings() -> dict[str, float]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_seen_listings(data: dict[str, float]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def send_discord_alert(
    title: str,
    price: float,
    link: str,
    platform: str = "OLX.ro",
    is_price_drop: bool = False,
    old_price: float = 0.0,
) -> None:
    if not DISCORD_WEBHOOK_URL:
        return

    embed: dict[str, Any] = {
        "title": f"🚨 PRICE DROP ALERT! ({platform})" if is_price_drop else f"🎮 NEW PS3 FOUND! ({platform})",
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
            {"name": "Platform", "value": platform, "inline": True},
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


def check_olx(seen_listings: dict[str, float]) -> bool:
    has_changes = False
    url = (
        f"https://www.olx.ro/oferte/q-{SEARCH_QUERY}/"
        f"?search%5Bfilter_float_price%3Afrom%5D={int(MIN_PRICE)}"
        f"&search%5Bfilter_float_price%3Ato%5D={int(MAX_PRICE)}"
    )

    try:
        response = requests.get(url, impersonate="chrome", timeout=15)
        print(f"[OLX] Status: {response.status_code}")
        if response.status_code != 200:
            return False

        soup = BeautifulSoup(response.text, "html.parser")
        listings = (
            soup.find_all("div", data_testid="l-card")
            or soup.find_all("div", {"data-cy": "l-card"})
            or soup.find_all("div", class_=lambda c: c and "card" in c.lower())
        )

        for item in listings:
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            raw_href = str(link_elem["href"])
            if not ("/d/oferta/" in raw_href or raw_href.endswith(".html")):
                continue

            link = f"https://www.olx.ro{raw_href}" if raw_href.startswith("/") else raw_href
            ad_id = f"olx_{item.get('id') or raw_href.split('/')[-1]}"

            title_elem = item.find(["h4", "h6"])
            title = title_elem.text.strip() if (title_elem and title_elem.text.strip()) else link_elem.text.strip()
            if not title:
                title = "PS3 Console"

            price_elem = item.find(["p", "span", "div"], attrs={"data-testid": "ad-price"})
            price_text = price_elem.text.strip() if price_elem else ""
            raw_price = "".join(filter(str.isdigit, price_text))
            price = float(raw_price) if raw_price else 0.0

            if price < MIN_PRICE or price > MAX_PRICE:
                continue

            if any(word in title.lower() for word in BLACKLIST):
                continue

            if ad_id not in seen_listings:
                print(f"[OLX NEW] {title} - {price} RON")
                seen_listings[ad_id] = price
                has_changes = True
                send_discord_alert(title, price, link, platform="OLX.ro")
            else:
                old_price = seen_listings[ad_id]
                if 0 < price < old_price:
                    print(f"[OLX DROP] {title}: {old_price} -> {price} RON")
                    seen_listings[ad_id] = price
                    has_changes = True
                    send_discord_alert(title, price, link, platform="OLX.ro", is_price_drop=True, old_price=old_price)

    except Exception as e:
        print(f"[OLX ERROR] {e}")

    return has_changes


def check_vinted(seen_listings: dict[str, float]) -> bool:
    has_changes = False
    session = requests.Session()

    try:
        # Step 1: Obținem cookie-ul de sesiune de pe Vinted.ro
        init_res = session.get("https://www.vinted.ro", impersonate="chrome", timeout=15)
        if init_res.status_code != 200:
            print(f"[VINTED] Init status: {init_res.status_code}")
            return False

        # Step 2: Apelăm API-ul intern de căutare (prețurile pe Vinted RO vin convertite automat în RON)
        api_url = (
            f"https://www.vinted.ro/api/v2/catalog/items?"
            f"search_text={SEARCH_QUERY}&price_from={MIN_PRICE}&price_to={MAX_PRICE}&order=newest_first"
        )

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        api_res = session.get(api_url, headers=headers, impersonate="chrome", timeout=15)
        print(f"[VINTED] API Status: {api_res.status_code}")

        if api_res.status_code != 200:
            return False

        data = api_res.json()
        items = data.get("items", [])

        for item in items:
            title = item.get("title", "PS3 Console")
            price_amount = float(item.get("price", {}).get("amount", 0))
            item_id = str(item.get("id"))
            ad_id = f"vinted_{item_id}"
            url = item.get("url") or f"https://www.vinted.ro/items/{item_id}"

            if price_amount < MIN_PRICE or price_amount > MAX_PRICE:
                continue

            if any(word in title.lower() for word in BLACKLIST):
                continue

            if ad_id not in seen_listings:
                print(f"[VINTED NEW] {title} - {price_amount} RON")
                seen_listings[ad_id] = price_amount
                has_changes = True
                send_discord_alert(title, price_amount, url, platform="Vinted")
            else:
                old_price = seen_listings[ad_id]
                if 0 < price_amount < old_price:
                    print(f"[VINTED DROP] {title}: {old_price} -> {price_amount} RON")
                    seen_listings[ad_id] = price_amount
                    has_changes = True
                    send_discord_alert(title, price_amount, url, platform="Vinted", is_price_drop=True, old_price=old_price)

    except Exception as e:
        print(f"[VINTED ERROR] {e}")

    return has_changes


if __name__ == "__main__":
    seen_listings = load_seen_listings()

    olx_changed = check_olx(seen_listings)
    vinted_changed = check_vinted(seen_listings)

    if olx_changed or vinted_changed:
        save_seen_listings(seen_listings)
