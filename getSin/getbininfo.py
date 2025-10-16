import aiohttp
import re
import os
import sqlite3
from bs4 import BeautifulSoup
from user_agent import generate_user_agent

# Path ng local database
DB_FOLDER = ".db"
DB_FILE_PATH = os.path.join(DB_FOLDER, "bin.db")

gBinInfoCache = {}

def getCountryFlag(code):
    return "".join(chr(ord(c.upper()) + 127397) for c in code) if isinstance(code, str) and len(code) == 2 else ""

async def initialize():
    # initialize-bin-module
    # Gagawa ng .db folder kung wala pa.
    os.makedirs(DB_FOLDER, exist_ok=True)
    if not os.path.exists(DB_FILE_PATH):
        print(f"[getSin] WARNING: Database file not found at '{DB_FILE_PATH}'.")
        #print("[getSin] Scraper will be used. For faster checking, please provide the bin.db file.")
    else:
        print("[getSin] Local BIN database found.")
    return True

async def getInfo(binPrefix):
    # get-bin-info
    binPrefix = binPrefix[:6]
    if binPrefix in gBinInfoCache:
        return gBinInfoCache[binPrefix]

    # Step 1: Subukang kunin mula sa local DB
    if os.path.exists(DB_FILE_PATH):
        try:
            with sqlite3.connect(DB_FILE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bin_info WHERE bin = ?", (binPrefix,))
                row = cursor.fetchone()
                if row:
                    binData = dict(row)
                    gBinInfoCache[binPrefix] = binData
                    return binData
        except Exception:
            pass # Kung mag-fail, ituloy lang sa pag-scrape

    # Step 2: Fallback - mag-scrape online kung wala sa DB
    try:
        async with aiohttp.ClientSession() as session:
            headers = {'User-Agent': generate_user_agent()}
            async with session.get(f"https://bincheck.io/details/{binPrefix}", headers=headers, timeout=10) as resp:
                if resp.status != 200: return {}
                text = await resp.text()
                soup = BeautifulSoup(text, 'html.parser')
                table = soup.find('table')
                if not table: return {}

                details = {cells[0].text.strip().lower(): cells[1].text.strip() for row in table.find_all('tr') if len(cells := row.find_all('td')) == 2}
                
                countryCodeMatch = re.search(r'ISO Country Code A2</td>\s*<td[^>]*>([^<]+)</td>', text)
                countryCode = countryCodeMatch.group(1).strip() if countryCodeMatch else ""
                flag = getCountryFlag(countryCode)
                
                binData = {
                    "brand": details.get('card brand', 'N/A'),
                    "type": details.get('card type', 'N/A'),
                    "level": details.get('card level', 'N/A'),
                    "bank": details.get('issuer name / bank', 'N/A').split('\n')[0].strip(),
                    "country": f"{details.get('iso country name', 'N/A').upper()} {flag}".strip()
                }
                gBinInfoCache[binPrefix] = binData
                return binData
    except Exception:
        return {}