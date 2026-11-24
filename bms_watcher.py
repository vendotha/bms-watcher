"""
BookMyShow watcher (personal use, free).

Setup:
  pip install playwright requests
  playwright install chromium

Environment variables (set only the channels you want):
  BMS_URL            Showtimes page URL for your movie + city + date
  CHECK_MINUTES      Base interval between checks (default 5)

  # Email (Gmail: enable 2FA, create an App Password)
  EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO

  # Telegram (free, reliable): create bot with @BotFather
  TG_BOT_TOKEN, TG_CHAT_ID

  # WhatsApp (free, personal use): https://www.callmebot.com/blog/free-api-whatsapp-messages/
  CALLMEBOT_PHONE (e.g. 919876543210), CALLMEBOT_APIKEY
"""
import json
import os
import random
import re
import smtplib
import time
import urllib.parse
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BMS_URL = os.environ["BMS_URL"]
CHECK_MINUTES = float(os.getenv("CHECK_MINUTES", "5"))
STATE_FILE = Path("state.json")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s?(AM|PM)$", re.I)


# ---------------------------------------------------------------- scraping
# Runs inside the page. Finds every showtime chip (e.g. "07:30 PM") and walks
# up the DOM to find the theatre name. BMS changes its markup often, so if
# results look wrong, adjust this function only.
JS_EXTRACT = """
() => {
  const timeRe = /^\\d{1,2}:\\d{2}\\s?(AM|PM)$/i;
  const out = [];
  document.querySelectorAll('a, div, span, li').forEach(el => {
    const t = (el.innerText || '').trim().split('\\n')[0].trim();
    if (el.children.length > 2 || !timeRe.test(t)) return;
    let node = el.parentElement, venue = '';
    for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
      const lines = (node.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
      const name = lines.find(l => !timeRe.test(l) && l.length > 4 && !/^(\\d|₹|Rs)/.test(l));
      if (name && lines.length > 1) { venue = name; break; }
    }
    out.push({venue, time: t.toUpperCase().replace(/\\s+/, ' ')});
  });
  return out;
}
"""


def fetch_shows(page):
    page.goto(BMS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)  # let the JS render
    rows = page.evaluate(JS_EXTRACT)
    return sorted({f"{r['venue']} | {r['time']}" for r in rows if r["venue"]})


# ----------------------------------------------------------- notifications
def notify(title, body):
    msg = f"{title}\n\n{body}\n\n{BMS_URL}"
    print(f"[{datetime.now():%H:%M:%S}] NOTIFY: {title}")

    if os.getenv("EMAIL_USER"):
        try:
            m = EmailMessage()
            m["Subject"], m["From"], m["To"] = title, os.environ["EMAIL_USER"], os.environ["EMAIL_TO"]
            m.set_content(msg)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(os.environ["EMAIL_USER"], os.environ["EMAIL_APP_PASSWORD"])
                s.send_message(m)
        except Exception as e:
            print("email failed:", e)

    if os.getenv("TG_BOT_TOKEN"):
        try:
            requests.post(
                f"https://api.telegram.org/bot{os.environ['TG_BOT_TOKEN']}/sendMessage",
                data={"chat_id": os.environ["TG_CHAT_ID"], "text": msg}, timeout=20)
        except Exception as e:
            print("telegram failed:", e)

    if os.getenv("CALLMEBOT_APIKEY"):
        try:
            requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": os.environ["CALLMEBOT_PHONE"],
                        "apikey": os.environ["CALLMEBOT_APIKEY"], "text": msg},
                timeout=20)
        except Exception as e:
            print("whatsapp failed:", e)


# -------------------------------------------------------------------- main
def load_state():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return None


def save_state(shows):
    STATE_FILE.write_text(json.dumps(sorted(shows), indent=1))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="en-IN",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))
        page = ctx.new_page()
        failures = 0

        while True:
            try:
                current = set(fetch_shows(page))
                previous = load_state()
                print(f"[{datetime.now():%H:%M:%S}] {len(current)} shows found")

                if not current:
                    failures += 1
                    if failures == 6:
                        notify("BMS watcher: no data", "6 checks in a row returned nothing. "
                               "Possibly blocked or markup changed.")
                else:
                    failures = 0
                    if previous is None:
                        notify("BMS watcher started", f"{len(current)} shows currently listed.")
                    else:
                        new = current - previous
                        if new:
                            notify(f"{len(new)} new show(s) on BookMyShow", "\n".join(sorted(new)))
                    save_state(current)
            except Exception as e:
                print("check failed:", e)

            if os.getenv("RUN_ONCE"):  # used by GitHub Actions: one check per run
                break
            time.sleep(CHECK_MINUTES * 60 * random.uniform(0.8, 1.2))


if __name__ == "__main__":
    main()
