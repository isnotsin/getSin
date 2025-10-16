import aiohttp
import re
from bs4 import BeautifulSoup
from user_agent import generate_user_agent

gBinInfoCache = {}

def getCountryFlag(code):
    return "".join(chr(ord(c.upper()) + 127397) for c in code) if isinstance(code, str) and len(code) == 2 else ""

async def initialize():
    # initialize-bin-module
    print("[getSin] BIN Info module initialized (Online Scrape Mode).")
    return True

async def getInfo(binPrefix):
    # get-bin-info
    binPrefix = binPrefix[:6]
    if binPrefix in gBinInfoCache:
        return gBinInfoCache[binPrefix]

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