import json
import os
from typing import Any
from bs4 import BeautifulSoup
from curl_cffi import requests

# ==========================================
# CONFIGURARE WEBHOOKS
# ==========================================
WEBHOOK_PS3 = os.getenv("DISCORD_WEBHOOK_URL")
WEBHOOK_TRACKS = os.getenv("DISCORD_WEBHOOK_TRACKS")

DB_FILE: str = "seen_listings.json"


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
    webhook_url: str,
    title: str,
    price: float,
    link: str,
    platform: str,
    bot_name: str,
    footer_text: str,
    is_price_drop: bool = False,
    old_price: float = 0.0,
) -> None:
    if not webhook_url:
        print(f"[DISCORD] Skip: Lipsesc variabilele de webhook.")
        return

    embed: dict[str, Any] = {
        "title": f"🚨 PRICE DROP ALERT! ({platform})" if is_price_drop else f"NEW ITEM FOUND! ({platform})",
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
        "footer": {"text": footer_text},
    }

    try:
        requests.post(
            webhook_url,
            data=json.dumps({"username": bot_name, "embeds": [embed]}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as e:
        print(f"[DISCORD ERROR] {e}")


# ==========================================
# 1. TRACKER BALENCIAGA TRACK (Mărimea 43)
# ==========================================
def run_track_finder(seen_listings: dict[str, float]) -> bool:
    if not WEBHOOK_TRACKS:
        return False

    has_changes = False
    min_price, max_price = 300.0, 600.0
    blacklist = ["hoodie", "shirt", "bluza", "pantalon", "geaca", "tricou", "hanorac", "parfum", "sosete", "cutie", "box"]

    # --- VINTED ---
    try:
        session = requests.Session()
        session.get("https://www.vinted.ro", impersonate="chrome", timeout=15)
        api_url = f"https://www.vinted.ro/api/v2/catalog/items?search_text=balenciaga%20track&price_from={min_price}&price_to={max_price}&size_ids[]=786&order=newest_first"
        headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0"}

        api_res = session.get(api_url, headers=headers, impersonate="chrome", timeout=15)
        if api_res.status_code == 200:
            for item in api_res.json().get("items", []):
                title = item.get("title", "Balenciaga Track 43")
                price_amount = float(item.get("price", {}).get("amount", 0))
                ad_id = f"vinted_{item.get('id')}"
                url = item.get("url") or f"https://www.vinted.ro/items/{item.get('id')}"

                if price_amount < min_price or price_amount > max_price:
                    continue
                if any(w in title.lower() for w in blacklist):
                    continue

                if ad_id not in seen_listings:
                    seen_listings[ad_id] = price_amount
                    has_changes = True
                    send_discord_alert(WEBHOOK_TRACKS, title, price_amount, url, "Vinted", "Charizard", "clau Balenci TrackER™️")
                elif 0 < price_amount < seen_listings[ad_id]:
                    old_p = seen_listings[ad_id]
                    seen_listings[ad_id] = price_amount
                    has_changes = True
                    send_discord_alert(WEBHOOK_TRACKS, title, price_amount, url, "Vinted", "Charizard", "clau Balenci TrackER™️", True, old_p)
    except Exception as e:
        print(f"[TRACK VINTED ERROR] {e}")

    # --- OLX ---
    try:
        url = f"https://www.olx.ro/oferte/q-balenciaga-track-43/?search%5Bfilter_float_price%3Afrom%5D={int(min_price)}&search%5Bfilter_float_price%3Ato%5D={int(max_price)}"
        res = requests.get(url, impersonate="chrome", timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            listings = soup.find_all("div", data_testid="l-card") or soup.find_all("div", {"data-cy": "l-card"})

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
                title = title_elem.text.strip() if title_elem else "Balenciaga Track 43"
                price_elem = item.find(["p", "span", "div"], attrs={"data-testid": "ad-price"})
                raw_price = "".join(filter(str.isdigit, price_elem.text.strip())) if price_elem else ""
                price = float(raw_price) if raw_price else 0.0

                if price < min_price or price > max_price or any(w in title.lower() for w in blacklist) or "43" not in title.lower():
                    continue

                if ad_id not in seen_listings:
                    seen_listings[ad_id] = price
                    has_changes = True
                    send_discord_alert(WEBHOOK_TRACKS, title, price, link, "OLX.ro", "Charizard", "clau Balenci TrackER™️")
                elif 0 < price < seen_listings[ad_id]:
                    old_p = seen_listings[ad_id]
                    seen_listings[ad_id] = price
                    has_changes = True
                    send_discord_alert(WEBHOOK_TRACKS, title, price, link, "OLX.ro", "Charizard", "clau Balenci TrackER™️", True, old_p)
    except Exception as e:
        print(f"[TRACK OLX ERROR] {e}")

    return has_changes


# ==========================================
# MAIN EXECUTOR
# ==========================================
if __name__ == "__main__":
    seen_listings = load_seen_listings()

    # Rulează trackerul de Balenciaga Track
    tracks_changed = run_track_finder(seen_listings)

    # Dacă vrei să reactivezi PS3 pe alt canal în viitor, adaugi o funcție similară run_ps3_finder() aici!

    if tracks_changed:
        save_seen_listings(seen_listings)
