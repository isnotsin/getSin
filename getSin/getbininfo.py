import sqlite3
import aiohttp
import os
import re
from bs4 import BeautifulSoup
from user_agent import generate_user_agent

DB_REMOTE_URL = "https://isnotsin.com/db/bin.db"
DB_LOCAL_FILE = "bin.db"
g_bin_info_cache = {}

def _get_country_flag(code):
    return "".join(chr(ord(c.upper()) + 127397) for c in code) if isinstance(code, str) and len(code) == 2 else ""

async def _download_db():
    if os.path.exists(DB_LOCAL_FILE):
        return True
    
    print(f"[INFO] Local BIN database not found. Downloading from remote source...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DB_REMOTE_URL) as response:
                if response.status == 200:
                    with open(DB_LOCAL_FILE, "wb") as f:
                        f.write(await response.read())
                    print("[INFO] Database downloaded successfully.")
                    return True
                else:
                    print(f"[ERROR] Failed to download database. Status: {response.status}")
                    return False
    except Exception as e:
        print(f"[ERROR] An exception occurred while downloading the database: {e}")
        return False

async def initialize():
    """Initializes the module by ensuring the database is available."""
    return await _download_db()

async def get_info(bin_prefix):
    """
    Gets BIN information, checking cache, then local DB, and finally scraping online as a fallback.
    """
    bin_prefix = bin_prefix[:6]
    if bin_prefix in g_bin_info_cache:
        return g_bin_info_cache[bin_prefix]

    try:
        with sqlite3.connect(DB_LOCAL_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bin_info WHERE bin = ?", (bin_prefix,))
            row = cursor.fetchone()
            if row:
                bin_data = dict(row)
                g_bin_info_cache[bin_prefix] = bin_data
                return bin_data
    except Exception:
        pass

    try:
        async with aiohttp.ClientSession() as session:
            headers = {'User-Agent': generate_user_agent()}
            async with session.get(f"https://bincheck.io/details/{bin_prefix}", headers=headers) as resp:
                if resp.status != 200: return {}
                text = await resp.text()
                soup = BeautifulSoup(text, 'html.parser')
                table = soup.find('table')
                details = {cells[0].text.strip().lower(): cells[1].text.strip() for row in table.find_all('tr') if len(cells := row.find_all('td')) == 2}
                
                country_code_match = re.search(r'ISO Country Code A2</td>\s*<td[^>]*>([^<]+)</td>', text)
                country_code = country_code_match.group(1).strip() if country_code_match else ""
                flag = _get_country_flag(country_code)
                
                bin_data = {
                    "brand": details.get('card brand', 'N/A'), "type": details.get('card type', 'N/A'),
                    "level": details.get('card level', 'N/A'), "bank": details.get('issuer name / bank', 'N/A').split('\n')[0].strip(),
                    "country": f"{details.get('iso country name', 'N/A').upper()} {flag}".strip(),
                    "currency": details.get('iso currency name', 'N/A')
                }
                g_bin_info_cache[bin_prefix] = bin_data
                return bin_data
    except Exception:
        return {}