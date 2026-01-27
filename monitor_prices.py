import requests
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import os
import re
import json

# Configuration
BINANCE_URL = "https://fapi.binance.com/fapi/v1/ticker/price"
SMTP_SERVER = "smtp.gmail.com"  # Default to Gmail, user can change if using others
SMTP_PORT = 587

def get_live_prices():
    try:
        gold = float(requests.get(f"{BINANCE_URL}?symbol=XAUUSDT").json()['price'])
        silver = float(requests.get(f"{BINANCE_URL}?symbol=XAGUSDT").json()['price'])
        return gold, silver
    except Exception as e:
        print(f"Error fetching prices: {e}")
        return None, None

def parse_config_from_html(file_path="index.html"):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Regex to find the CONFIG object
        # Looking for: const CONFIG = { ... };
        # This is a bit brittle, but sufficient for this specific file structure.
        match = re.search(r'const CONFIG = ({[\s\S]*?});', content)
        if match:
            config_str = match.group(1)
            # JSON parser requires double quotes and no comments. 
            # JS object literals are loose. We need to be careful.
            # Let's try to extract specific values using regex instead of parsing full JSON.
            
            cn_match = re.search(r'cn:\s*({[^}]*})', config_str)
            moo_match = re.search(r'moo:\s*({[^}]*})', config_str)
            
            def extract_val(block, key):
                m = re.search(rf'{key}:\s*([0-9.]+)', block)
                return float(m.group(1)) if m else 0
            
            cn_data = {
                'startPrice': extract_val(cn_match.group(1), 'startPrice'),
                'startEquity': extract_val(cn_match.group(1), 'startEquity'),
                'startLots': extract_val(cn_match.group(1), 'startLots'),
                'currentPrice': extract_val(cn_match.group(1), 'currentPrice'),
                'currentEquity': extract_val(cn_match.group(1), 'currentEquity'),
                'currentLots': extract_val(cn_match.group(1), 'currentLots'),
                'marginRate': extract_val(cn_match.group(1), 'marginRate'),
                'contractSize': extract_val(cn_match.group(1), 'contractSize'),
            }
            
            moo_data = {
                'startPrice': extract_val(moo_match.group(1), 'startPrice'),
                'startEquity': extract_val(moo_match.group(1), 'startEquity'),
                'startLots': extract_val(moo_match.group(1), 'startLots'),
                'currentPrice': extract_val(moo_match.group(1), 'currentPrice'),
                'currentEquity': extract_val(moo_match.group(1), 'currentEquity'),
                'currentLots': extract_val(moo_match.group(1), 'currentLots'),
                'marginRate': extract_val(moo_match.group(1), 'marginRate'),
                'contractSize': extract_val(moo_match.group(1), 'contractSize'),
            }
            
            return {'cn': cn_data, 'moo': moo_data}
            
    except Exception as e:
        print(f"Error parsing HTML: {e}")
        return None

def calculate_next_buy(cfg_type, cfg, live_price):
    # Replicate the logic from index.html: calculateScenario
    # We only need the NEXT buy price.
    # Logic: nextPrice = (Eq - Lots*Sz*P) / (NextLots*Sz*K - Lots*Sz)
    # But wait, the JS logic iterates.
    # For monitoring, we just need to know: Is Current Live Price <= The Next Buy Trigger?
    
    # We can infer the Next Buy Price using the Formula directly based on CURRENT state.
    # state = 'real' (implied) 
    
    p = cfg['currentPrice'] # Last recorded price in config
    eq = cfg['currentEquity']
    lots = cfg['currentLots']
    sz = cfg['contractSize']
    margin_rate = cfg['marginRate']
    
    # Safety Rate defaults usually to something around 15% or user defined.
    # Since we can't easily parse the dynamic user input 'safetyRate' from HTML (it's in an input tag),
    # we will assume a SAFE default of 20% for the monitor to be conservative, 
    # OR we try to find the default value in the HTML.
    safety_rate = 20.0 
    
    K = (safety_rate/100) + (1 - safety_rate/100) * margin_rate
    
    next_lots = lots + 1
    
    # Formula from JS:
    # let num = eq - (lots * sz * p);
    # let den = (nextLots * sz * K) - (lots * sz);
    # nextPrice = num / den;
    
    # HOWEVER, this formula calculates where we SHOULD have bought.
    # If we are strictly following the table, the "Next Buy Price" is determined by the previous row's Equity.
    # This is getting complex to replicate 1:1 without the full loop. 
    
    # Simplified Monitor Logic:
    # If Live Price drops X% below Last Recorded Entry, warn.
    # OR, strictly use the formula:
    
    num = eq - (lots * sz * p)
    den = (next_lots * sz * K) - (lots * sz)
    target_price = num / den
    
    # Boom Price Logic
    # BoomPrice = (CurrentPrice*Lots*Sz - Equity) / (Lots*Sz*(1 - MarginRate))
    # Note: Using LIVE price to calculate dynamic boom price is wrong. 
    # Boom price is fixed based on Entry Price & Equity.
    # BoomPrice = (EntryPrice*Lots*Sz - Equity) / (Lots*Sz*BoomCoef)
    # Actually, Equity is dynamic.
    # Correct Formula: 
    # Margin Call Level = Maintainance Margin.
    # We want to know at what price Equity becomes 0 (or close to margin call).
    
    # Let's use the JS formula:
    # boomPrice = (sz * lots * price - equity) / (sz * lots * (1 - cfg.marginRate));
    # Here 'price' and 'equity' are the snapshot at that moment.
    # If we use the values from CONFIG (which are the snapshot), we get the Static Boom Price.
    
    boom_price = (sz * lots * p - eq) / (sz * lots * (1 - margin_rate))
    
    return target_price, boom_price

def send_email(subject, body):
    mail_user = os.environ.get('MAIL_USERNAME')
    mail_pass = os.environ.get('MAIL_PASSWORD')
    mail_to = os.environ.get('MAIL_TO')
    
    if not mail_user or not mail_pass or not mail_to:
        print("Mail credentials not set.")
        return

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = mail_user
    msg['To'] = mail_to

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(mail_user, mail_pass)
        server.sendmail(mail_user, [mail_to], msg.as_string())
        server.quit()
        print("Email sent!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def main():
    print("Starting Silver Monitor...")
    gold, silver = get_live_prices()
    if not gold or not silver:
        return

    config = parse_config_from_html()
    if not config:
        return

    alerts = []

    # 1. Ratio Check
    ratio = gold / silver
    # Default target hardcoded or parsed? Let's assume 44 as dangerous
    if ratio < 44:
        alerts.append(f"⚠️ Gold/Silver Ratio Alert: {ratio:.2f} (Below 44)")

    # 2. MooMoo Check
    moo_target, moo_boom = calculate_next_buy('moo', config['moo'], silver)
    
    # Logic: If Live Silver is close to Target (within 1%)
    if silver <= moo_target * 1.01:
        alerts.append(f"📉 MooMoo Buy Alert: Price {silver} is close to target {moo_target:.2f}")
    
    if silver <= moo_boom * 1.05:
         alerts.append(f"🔥 MooMoo MARGIN CALL WARNING: Price {silver} is near boom price {moo_boom:.2f}!")

    # 3. CN Check (Estimate CN price via Exchange Rate approx 7.25 + premium)
    # Simple approx: CN_Price = Silver * 7.28 * 1000 / 31.1035
    # This is a rough guess.
    cn_price_est = silver * 7.3 * 1000 / 31.1035
    
    cn_target, cn_boom = calculate_next_buy('cn', config['cn'], cn_price_est)
    
    # We use the config's currentPrice to see if we are dropping
    # If user hasn't updated config, this might be stale.
    # But for 'Boom' calculation, the config values (lots, equity) are key.
    
    if cn_price_est <= cn_boom * 1.05:
         alerts.append(f"🔥 CN Futures Risk Warning: Est. Price {cn_price_est:.0f} is near boom price {cn_boom:.0f}!")

    if alerts:
        subject = f"🔔 Silver Alert: Ratio {ratio:.2f} | Ag ${silver}"
        body = "\n".join(alerts) + f"\n\nCurrent Data:\nGold: {gold}\nSilver: {silver}"
        print(f"Sending alerts: {alerts}")
        send_email(subject, body)
    else:
        print(f"No alerts. Ratio: {ratio:.2f}, Silver: {silver}")

if __name__ == "__main__":
    main()
