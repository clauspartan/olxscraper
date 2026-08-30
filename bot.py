import json
import os
import asyncio
from typing import Any
import discord
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv

# ==========================================
# CONFIGURARE BOT DISCORD
# ==========================================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SEARCHES_FILE = "searches.json"
SEEN_FILE = "seen_listings.json"


def load_json(filepath: str) -> dict | list:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [] if "searches" in filepath else {}


def save_json(filepath: str, data: Any) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ==========================================
# LOGICA DE SCRAPING DINAMICĂ
# ==========================================
def scrape_item(search_config: dict, seen_listings: dict) -> list[dict]:
    query = search_config["query"]
    min_price = search_config["min_price"]
    max_price = search_config["max_price"]
    size_id = search_config.get("size_id")

    blacklist_raw = search_config.get("blacklist", "")
    blacklist = [word.strip().lower() for word in blacklist_raw.split(",") if word.strip()]

    new_alerts = []

    def is_blacklisted(title_text: str) -> bool:
        title_lower = title_text.lower()
        return any(bad_word in title_lower for bad_word in blacklist)

    # 1. Scraping Vinted
    try:
        session = requests.Session()
        session.get("https://www.vinted.ro", impersonate="chrome", timeout=15)

        url_vinted = f"https://www.vinted.ro/api/v2/catalog/items?search_text={query.replace(' ', '%20')}&price_from={min_price}&price_to={max_price}&order=newest_first"
        if size_id:
            url_vinted += f"&size_ids[]={size_id}"

        headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0"}
        res = session.get(url_vinted, headers=headers, impersonate="chrome", timeout=15)

        if res.status_code == 200:
            for item in res.json().get("items", []):
                title = item.get("title", query)

                if is_blacklisted(title):
                    continue

                price = float(item.get("price", {}).get("amount", 0))
                ad_id = f"vinted_{item.get('id')}"
                link = item.get("url") or f"https://www.vinted.ro/items/{item.get('id')}"

                if min_price <= price <= max_price:
                    if ad_id not in seen_listings:
                        seen_listings[ad_id] = price
                        new_alerts.append({"title": title, "price": price, "link": link, "platform": "Vinted", "is_drop": False})
                    elif 0 < price < seen_listings[ad_id]:
                        old_p = seen_listings[ad_id]
                        seen_listings[ad_id] = price
                        new_alerts.append({"title": title, "price": price, "link": link, "platform": "Vinted", "is_drop": True, "old_price": old_p})
    except Exception as e:
        print(f"[ERROR VINTED {query}] {e}")

    # 2. Scraping OLX
    try:
        url_olx = f"https://www.olx.ro/oferte/q-{query.replace(' ', '-')}/?search%5Bfilter_float_price%3Afrom%5D={int(min_price)}&search%5Bfilter_float_price%3Ato%5D={int(max_price)}"
        res = requests.get(url_olx, impersonate="chrome", timeout=15)

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
                title = title_elem.text.strip() if title_elem else query

                if is_blacklisted(title):
                    continue

                price_elem = item.find(["p", "span", "div"], attrs={"data-testid": "ad-price"})
                raw_price = "".join(filter(str.isdigit, price_elem.text.strip())) if price_elem else ""
                price = float(raw_price) if raw_price else 0.0

                if min_price <= price <= max_price:
                    if ad_id not in seen_listings:
                        seen_listings[ad_id] = price
                        new_alerts.append({"title": title, "price": price, "link": link, "platform": "OLX.ro", "is_drop": False})
                    elif 0 < price < seen_listings[ad_id]:
                        old_p = seen_listings[ad_id]
                        seen_listings[ad_id] = price
                        new_alerts.append({"title": title, "price": price, "link": link, "platform": "OLX.ro", "is_drop": True, "old_price": old_p})
    except Exception as e:
        print(f"[ERROR OLX {query}] {e}")

    return new_alerts


# ==========================================
# LOOP-UL DE FUNDAL (CORRECTED)
# ==========================================
@tasks.loop(minutes=10)
async def check_all_searches():
    searches = load_json(SEARCHES_FILE)
    seen_listings = load_json(SEEN_FILE)

    if not searches:
        return

    valid_searches = []

    for config in searches:
        channel_id = config.get("channel_id")

        # Încearcă să ia canalul din cache sau prin fetch direct
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                print(f"[CLEANUP] Canalul ID {channel_id} nu mai există sau botul nu are acces. Ștergem căutarea '{config.get('query')}'.")
                continue  # Sare peste căutările ale căror canale au fost șterse

        valid_searches.append(config)
        alerts = scrape_item(config, seen_listings)

        for alert in alerts:
            is_drop = alert.get("is_drop", False)
            embed = discord.Embed(
                title=f"🚨 PRICE DROP ALERT! ({alert['platform']})" if is_drop else f"NEW ITEM FOUND! ({alert['platform']})",
                description=f"**[{alert['title']}]({alert['link']})**",
                color=discord.Color.red() if is_drop else discord.Color.blue()
            )

            price_text = f"~~{alert.get('old_price')} RON~~ ➡️ **{alert['price']} RON**" if is_drop else f"**{alert['price']} RON**"
            embed.add_field(name="Price", value=price_text, inline=True)
            embed.add_field(name="Platform", value=alert['platform'], inline=True)
            embed.set_footer(text=f"Tracker: {config['query']}")

            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                print(f"[SEND ERROR] Nu am putut trimite mesajul pe canalul {channel_id}: {e}")

            await asyncio.sleep(1)

    # Actualizăm searches.json eliminând căutările invalide
    if len(valid_searches) != len(searches):
        save_json(SEARCHES_FILE, valid_searches)

    save_json(SEEN_FILE, seen_listings)

# ==========================================
# COMENZI SLASH DISCORD
# ==========================================
GUILD_ID = 1322587821760057364
@bot.event
async def on_ready():
    print(f"✅ Bot conectat ca: {bot.user.name}")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"Sincronizate {len(synced)} comenzi Slash.")
    except Exception as e:
        print(f"Eroare la sync: {e}")

    if not check_all_searches.is_running():
        check_all_searches.start()


@bot.tree.command(name="search", description="Creează un tracker nou pentru un produs")
@app_commands.describe(
    query="Cuvântul cheie (ex: balenciaga track 43 sau ps5 pro)",
    min_price="Preț minim (RON)",
    max_price="Preț maxim (RON)",
    size_id="ID marime Vinted (opțional)",
    blacklist="Cuvinte de ignorat separate prin virgulă (ex: sparta, defect, cutie)"
)
async def add_search(interaction: discord.Interaction, query: str, min_price: float, max_price: float, size_id: str = None, blacklist: str = None):
    await interaction.response.defer()

    guild = interaction.guild
    # Caută sau creează categoria "TRACKERS"
    category = discord.utils.get(guild.categories, name="TRACKERS")
    if not category:
        category = await guild.create_category("TRACKERS")

    # Creează canalul de text curățând numele
    channel_name = f"find-{query}".replace(" ", "-").lower()[:30]
    channel = await guild.create_text_channel(name=channel_name, category=category)

    # Definire dicționar config
    config = {
        "query": query,
        "min_price": min_price,
        "max_price": max_price,
        "size_id": size_id,
        "blacklist": blacklist or "",
        "channel_id": channel.id
    }

    # Salvează configurarea
    searches = load_json(SEARCHES_FILE)
    if not isinstance(searches, list):
        searches = []
    searches.append(config)
    save_json(SEARCHES_FILE, searches)

    msg = f"✅ Am creat tracker-ul pentru **{query}**!"
    if blacklist:
        msg += f" (Blacklist: `{blacklist}`)"
    await interaction.followup.send(f"{msg} Vei primi notificări pe canalul {channel.mention}.")

    # Execută prima căutare imediată
    seen_listings = load_json(SEEN_FILE)
    if not isinstance(seen_listings, dict):
        seen_listings = {}

    alerts = scrape_item(config, seen_listings)

    for alert in alerts:
        is_drop = alert.get("is_drop", False)
        embed = discord.Embed(
            title=f"🚨 PRICE DROP ALERT! ({alert['platform']})" if is_drop else f"NEW ITEM FOUND! ({alert['platform']})",
            description=f"**[{alert['title']}]({alert['link']})**",
            color=discord.Color.red() if is_drop else discord.Color.blue()
        )

        price_text = f"~~{alert.get('old_price')} RON~~ ➡️ **{alert['price']} RON**" if is_drop else f"**{alert['price']} RON**"
        embed.add_field(name="Price", value=price_text, inline=True)
        embed.add_field(name="Platform", value=alert['platform'], inline=True)
        embed.set_footer(text=f"Tracker: {config['query']}")

        await channel.send(embed=embed)
        await asyncio.sleep(1)

    save_json(SEEN_FILE, seen_listings)

@bot.tree.command(name="list_searches", description="Afișează toate căutările active")
async def list_searches(interaction: discord.Interaction):
    searches = load_json(SEARCHES_FILE)
    if not searches:
        await interaction.response.send_message("Nu există nicio căutare activă în acest moment.")
        return

    msg = "**Căutări active:**\n"
    for idx, item in enumerate(searches, 1):
        msg += f"{idx}. **{item['query']}** ({item['min_price']}-{item['max_price']} RON) -> <#{item['channel_id']}>\n"

    await interaction.response.send_message(msg)

# ========================
# AUTOCOMPLETE PENTRU DELETE
# ========================
async def search_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    searches = load_json(SEARCHES_FILE)
    if not isinstance(searches, list):
        return []

    choices = []
    for s in searches:
        query_text = s.get("query", "")
        if current.lower() in query_text.lower():
            choices.append(app_commands.Choice(name=query_text, value=query_text))
    return choices[:25]
# ============================
# COMANDA: DELETE SEARCH
# ============================
@bot.tree.command(name="delete_search", description="Șterge un tracker activ și canalul său")
@app_commands.autocomplete(query=search_autocomplete)
@app_commands.describe(query="Alege tracker-ul pe care vrei să îl elimini")
async def delete_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    searches = load_json(SEARCHES_FILE)
    if not isinstance(searches, list) or not searches:
        await interaction.followup.send("Nu există căutări active de șters.")
        return

    target = None
    remaining_searches = []
    for item in searches:
        if item.get("query").lower() == query.lower() and target is None:
            target = item
        else:
            remaining_searches.append(item)

    if not target:
        await interaction.followup.send(f"❌ Nu am găsit niciun tracker activ pentru **{query}**.")
        return

    save_json(SEARCHES_FILE, remaining_searches)

    channel_id = target.get("channel_id")
    channel = interaction.guild.get_channel(channel_id) if interaction.guild else None

    if channel:
        try:
            await channel.delete(reason=f"Tracker șters de {interaction.user.name}")
            await interaction.followup.send(f"🗑️ Am șters tracker-ul **{query}** și canalul #{channel.name}.")
        except Exception as e:
            await interaction.followup.send(f"⚠️ Am scos tracker-ul **{query}**, dar nu am putut șterge canalul: {e}")
    else:
        await interaction.followup.send(f"🗑️ Am șters tracker-ul **{query}** din baza de date.")
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
