#!/usr/bin/env python3
"""Nachrichten am Morgen – Tägliches Morning Intelligence Briefing (Mo–Fr 07:00 MEZ)

Ablauf:
  1. Gemini API (Google Search Grounding) → aktuelle News der letzten 24h in 3 Kategorien
  2. Claude API → strukturiertes HTML-Briefing aus den Gemini-Ergebnissen
  3. Gmail SMTP → Versand an RECIPIENT_EMAIL
"""

import os
import time
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import anthropic
from google import genai
from google.genai import types

# ── Konfiguration (aus GitHub Secrets) ──────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT      = os.environ["RECIPIENT_EMAIL"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_KEY     = os.environ["GEMINI_API_KEY"]

# ── Gemini: News der letzten 24h abrufen ─────────────────────────────────────

GEMINI_QUERIES = {
    "maerkte": (
        "Fasse die wichtigsten Marktbewegungen der letzten 24 Stunden zusammen. "
        "Fokus: S&P 500, DAX, Nikkei 225 (aktuelle Kursbewegungen und Begründung). "
        "10-jährige Anleiherenditen USA (Treasury) und Deutschland (Bund) – Richtung und Ursache. "
        "Gold (XAU/USD) und Öl (WTI + Brent) – Preisentwicklung und treibende Faktoren. "
        "Antworte auf Deutsch, präzise, keine Floskeln."
    ),
    "wirtschaft": (
        "Welche makroökonomischen Datenpublikationen aus Deutschland und den USA "
        "wurden in den letzten 24 Stunden veröffentlicht? "
        "Fokus: Inflation (CPI/PPI), BIP, Arbeitsmarkt (NFP, Erstanträge), Sentiment-Indizes. "
        "Bewerte jede Zahl kurz: besser oder schlechter als Markterwartung und die unmittelbare Marktreaktion. "
        "Maximal die Top 3 relevantesten Veröffentlichungen. "
        "Antworte auf Deutsch, präzise, keine Floskeln."
    ),
    "geopolitik": (
        "Welche geopolitischen Ereignisse der letzten 24 Stunden haben direkten Einfluss auf "
        "Lieferketten, Energiepreise oder Finanzmarktvolatilität? "
        "Ignoriere 'Soft News' ohne wirtschaftliche Konsequenz. "
        "Fokus: Handelskonflikte, Sanktionen, Energiepolitik, Konflikte mit Marktrelevanz, "
        "Zentralbankaussagen (Fed, EZB), geopolitische Spannungen mit Rohstoffbezug. "
        "Antworte auf Deutsch, präzise, keine Floskeln."
    ),
}


def fetch_news_via_gemini() -> dict[str, str]:
    """Ruft für jede Kategorie aktuelle News über Gemini mit Google Search Grounding ab.
    Wartet 10 Sekunden zwischen Abfragen und versucht bei 429 bis zu 3-mal mit Backoff."""
    client = genai.Client(api_key=GEMINI_KEY)

    results = {}
    for i, (key, query) in enumerate(GEMINI_QUERIES.items()):
        if i > 0:
            time.sleep(10)  # Pause zwischen Abfragen – verhindert RPM-Überschreitung

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=query,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                results[key] = response.text.strip()
                print(f"   → Gemini [{key}]: {len(results[key])} Zeichen abgerufen")
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 30 * (attempt + 1)  # 30s, 60s, 90s
                    print(f"   → Gemini [{key}]: 429 – warte {wait}s (Versuch {attempt+1}/3)")
                    time.sleep(wait)
                    if attempt == 2:
                        results[key] = f"Keine Daten verfügbar (Quota erschöpft: {e})"
                else:
                    results[key] = f"Keine Daten verfügbar (Fehler: {e})"
                    print(f"   → Gemini [{key}]: FEHLER – {e}")
                    break
    return results


# ── Claude: Briefing aus News-Daten erstellen ─────────────────────────────────

BRIEFING_PROMPT = """Du bist ein leitender Strategie-Analyst für globale Märkte und Makroökonomie.

Erstelle ein prägnantes "Morning Intelligence Briefing" der letzten 24 Stunden.
Dein Ziel: die Verbindung zwischen harten Marktdaten und geopolitischen Ereignissen aufzeigen.

INPUT-DATEN:

--- MÄRKTE (DE, USA, JP) ---
{maerkte}

--- WIRTSCHAFTSZAHLEN (DE, USA) ---
{wirtschaft}

--- GEOPOLITISCHE RISK-MAP ---
{geopolitik}

---

STRENGER FOKUS & STRUKTUR – antworte NUR mit validem HTML (kein Markdown, kein weiterer Text):

<section id="maerkte">
  <h2>📊 Marktlage</h2>
  <!-- Aktien: S&P 500, DAX, Nikkei – Bewegung + kurze Begründung -->
  <!-- Anleihen: 10J-Renditen USA + DE – Richtung + Zinspfad-Implikation -->
  <!-- Rohstoffe: Gold + Öl (WTI/Brent) – Preis + Treiber -->
</section>

<section id="wirtschaft">
  <h2>📈 Wirtschaftszahlen</h2>
  <!-- Nur Top-3-Veröffentlichungen: Besser/Schlechter als erwartet + Marktstimmung -->
</section>

<section id="geopolitik">
  <h2>🌍 Geopolitische Risk-Map</h2>
  <!-- Nur Ereignisse mit direktem Einfluss auf Lieferketten, Energie oder Volatilität -->
  <!-- Soft News ignorieren -->
</section>

TONALITÄT:
- Trocken, analytisch, keine Floskeln
- Bulletpoints für maximale Scannbarkeit (HTML <ul><li>)
- Bei widersprüchlichen Daten: Divergenz explizit benennen
- Sprache: Deutsch
"""


def generate_briefing(news: dict[str, str]) -> str:
    """Erstellt das strukturierte HTML-Briefing via Claude API."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = BRIEFING_PROMPT.format(
        maerkte=news.get("maerkte", "Keine Daten"),
        wirtschaft=news.get("wirtschaft", "Keine Daten"),
        geopolitik=news.get("geopolitik", "Keine Daten"),
    )
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── HTML-E-Mail zusammenbauen ─────────────────────────────────────────────────

def build_html(briefing_content: str) -> str:
    today    = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    date_str = today.strftime("%A, %d. %B %Y")
    weekday_map = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag",
        "Saturday": "Samstag", "Sunday": "Sonntag",
    }
    month_map = {
        "January": "Januar", "February": "Februar", "March": "März",
        "April": "April", "May": "Mai", "June": "Juni",
        "July": "Juli", "August": "August", "September": "September",
        "October": "Oktober", "November": "November", "December": "Dezember",
    }
    for en, de in {**weekday_map, **month_map}.items():
        date_str = date_str.replace(en, de)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body {{ margin:0; padding:20px; background:#0d1117; font-family:Arial,Helvetica,sans-serif; }}
    .wrapper {{ max-width:860px; margin:0 auto; background:#161b22; border-radius:14px;
                overflow:hidden; box-shadow:0 8px 40px rgba(0,0,0,.5); }}
    .header {{ background:linear-gradient(135deg,#0f2027,#203a43,#2c5364); padding:32px 40px; }}
    .header-label {{ color:#7eb8d4; font-size:11px; letter-spacing:3px;
                     text-transform:uppercase; margin-bottom:8px; }}
    .header-title {{ color:#ffffff; font-size:26px; font-weight:700; letter-spacing:-0.5px; }}
    .header-date  {{ color:#5a8fa8; font-size:13px; margin-top:6px; }}
    .content {{ padding:28px 40px 36px; color:#c9d1d9; }}
    section {{ margin-bottom:28px; background:#1f2937;
               border-radius:10px; padding:22px 26px; }}
    section h2 {{ color:#e6edf3; font-size:15px; font-weight:700;
                  margin:0 0 14px; text-transform:uppercase; letter-spacing:.5px;
                  border-bottom:1px solid #30363d; padding-bottom:10px; }}
    ul  {{ margin:6px 0 10px 18px; padding:0; }}
    li  {{ margin-bottom:7px; font-size:14px; line-height:1.7; color:#c9d1d9; }}
    li strong {{ color:#e6edf3; }}
    p   {{ font-size:14px; line-height:1.75; margin:6px 0; }}
    .footer {{ background:#0d1117; padding:18px 40px; text-align:center; }}
    .footer p {{ color:#484f58; font-size:11px; margin:0; }}
  </style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="header-label">Nachrichten am Morgen · Morning Intelligence Briefing</div>
    <div class="header-title">🌐 Markt &amp; Geopolitik</div>
    <div class="header-date">{date_str}</div>
  </div>

  <div class="content">
    {briefing_content}
  </div>

  <div class="footer">
    <p>Automatisch generiert · Keine Anlageberatung · News via Gemini/Google Search · Analyse via Claude</p>
  </div>

</div>
</body>
</html>"""


# ── E-Mail versenden ───────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_PASSWORD)
        srv.send_message(msg)


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main():
    print("🌐 Nachrichten am Morgen – Briefing wird erstellt …")

    print("   → News abrufen (Gemini + Google Search) …")
    news = fetch_news_via_gemini()

    print("   → Briefing generieren (Claude) …")
    try:
        briefing_html = generate_briefing(news)
    except Exception as e:
        briefing_html = f"<p><em>Briefing konnte nicht generiert werden: {e}</em></p>"
        print(f"   → FEHLER bei Claude: {e}")

    today   = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    subject = f"🌐 Nachrichten am Morgen – {today.strftime('%d.%m.%Y')}"
    html    = build_html(briefing_html)

    print(f"   → E-Mail versenden an {RECIPIENT} …")
    send_email(subject, html)
    print("✅ Briefing erfolgreich versendet!")


if __name__ == "__main__":
    main()
