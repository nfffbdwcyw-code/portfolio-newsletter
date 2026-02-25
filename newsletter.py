#!/usr/bin/env python3
"""Portfolio Newsletter – Wöchentlicher Finanzbericht (freitags 17:00 Uhr)"""

import os
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import yfinance as yf
import anthropic

# ── Konfiguration (aus GitHub Secrets) ──────────────────────────────────────
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_PASSWORD   = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT        = os.environ["RECIPIENT_EMAIL"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]

# ── Portfolio ────────────────────────────────────────────────────────────────
# ticker:   Yahoo Finance Symbol (bei Bedarf anpassen)
# basis:    Einkaufspreis pro Einheit (in der jeweiligen Handelswährung)
# stueck:   Anzahl gehaltener Einheiten
PORTFOLIO = [
    {"name": "Southern Copper",                   "isin": "US84265V1052", "basis": 156.3477, "stueck": 32,   "ticker": "SCCO"},
    {"name": "VanEck Morningstar DM Dividend",     "isin": "NL0011683594", "basis": 48.2127,  "stueck": 323,  "ticker": "VDIV.AS"},
    {"name": "Bitcoin",                            "isin": "EU000A2YZK67", "basis": 30000.00, "stueck": 10,   "ticker": "BTC-EUR"},
    {"name": "iShares Automation & Robotics",      "isin": "IE00BYZK4552", "basis": 13.9970,  "stueck": 1600, "ticker": "RBOT.L"},
    {"name": "GE Vernova",                         "isin": "US36828A1016", "basis": 581.3684, "stueck": 19,   "ticker": "GEV"},
    {"name": "L&G Global Robotics",                "isin": "IE00BMW3QX54", "basis": 25.6500,  "stueck": 689,  "ticker": "ROBG.L"},
    {"name": "Constellation Energy",               "isin": "US21037T1097", "basis": 304.9000, "stueck": 17,   "ticker": "CEG"},
    {"name": "Krane Humanoid & Embodied Intell.",  "isin": "IE000O6Z73N7", "basis": 24.3700,  "stueck": 400,  "ticker": "KBOD.L"},
    {"name": "iShares Global Clean Energy",        "isin": "IE00B1XNHC34", "basis": 9.0100,   "stueck": 1065, "ticker": "IQQH.DE"},
    {"name": "VanEck Junior Gold Miners",          "isin": "IE00BQQP9G91", "basis": 102.6400, "stueck": 49,   "ticker": "GDXJ"},
    {"name": "iShares MSCI EM",                    "isin": "IE00B4L5YC18", "basis": 48.9440,  "stueck": 205,  "ticker": "IS3N.DE"},
    {"name": "Schneider Electric",                 "isin": "FR0000121972", "basis": 259.7500, "stueck": 32,   "ticker": "SU.PA"},
    {"name": "Freeport McMoran",                   "isin": "US35671D8570", "basis": 52.9200,  "stueck": 96,   "ticker": "FCX"},
    {"name": "Prysmian",                           "isin": "IT0004176001", "basis": 97.4000,  "stueck": 85,   "ticker": "PRY.MI"},
    {"name": "Vertiv Holdings",                    "isin": "US92537N1081", "basis": 212.5000, "stueck": 40,   "ticker": "VRT"},
    {"name": "Xetra Gold",                         "isin": "DE000A0S9GB0", "basis": 136.5600, "stueck": 60,   "ticker": "4GLD.DE"},
]

# ── Marktdaten ───────────────────────────────────────────────────────────────

def get_fx_to_eur(currency: str) -> float:
    """Wechselkurs zur Umrechnung in EUR. Gibt 1.0 zurück falls EUR."""
    if currency == "EUR":
        return 1.0
    try:
        rate = yf.Ticker(f"{currency}EUR=X").fast_info["lastPrice"]
        return float(rate)
    except Exception:
        return 1.0


def get_price_data(ticker: str) -> dict | None:
    """Aktueller Kurs + Woche/Monats-Performance von Yahoo Finance."""
    try:
        hist = yf.Ticker(ticker).history(period="35d", interval="1d")
        if hist.empty or len(hist) < 2:
            return None

        close = hist["Close"].dropna()
        current   = float(close.iloc[-1])
        week_ago  = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
        month_ago = float(close.iloc[0])

        try:
            currency = yf.Ticker(ticker).fast_info.get("currency", "USD")
        except Exception:
            currency = "USD"

        return {
            "current":     current,
            "week_pct":    (current - week_ago)  / week_ago  * 100,
            "month_pct":   (current - month_ago) / month_ago * 100,
            "currency":    currency,
        }
    except Exception:
        return None


def build_report_data() -> list[dict]:
    """Portfolio-Positionen mit Live-Kursdaten anreichern."""
    fx_cache: dict[str, float] = {}

    def fx(currency: str) -> float:
        if currency not in fx_cache:
            fx_cache[currency] = get_fx_to_eur(currency)
        return fx_cache[currency]

    report = []
    for pos in PORTFOLIO:
        entry = pos.copy()
        data  = get_price_data(pos["ticker"])

        if data:
            cur    = data["current"]
            curr   = data["currency"]
            rate   = fx(curr)
            cur_eur = cur * rate

            # G/V-Berechnung: % basiert auf nativem Kurs vs. Einkaufsbasis
            gv_pct   = (cur - pos["basis"]) / pos["basis"] * 100
            # EUR-Werte (Näherung: Einkaufsbasis in gleicher Währung angenommen)
            wert_eur = cur_eur * pos["stueck"]
            basis_eur = pos["basis"] * rate * pos["stueck"]
            gv_eur   = wert_eur - basis_eur

            entry.update({
                "current_price": cur,
                "currency":      curr,
                "current_eur":   cur_eur,
                "wert_eur":      wert_eur,
                "gv_pct":        gv_pct,
                "gv_eur":        gv_eur,
                "week_pct":      data["week_pct"],
                "month_pct":     data["month_pct"],
                "ok": True,
            })
        else:
            entry.update({
                "current_price": None, "currency": "?",
                "current_eur": None,   "wert_eur": None,
                "gv_pct": None,        "gv_eur": None,
                "week_pct": None,      "month_pct": None,
                "ok": False,
            })

        report.append(entry)
    return report

# ── KI-Kommentar ─────────────────────────────────────────────────────────────

def generate_ai_commentary(report_data: list[dict]) -> str:
    """Deutschen Marktkommentar via Claude API generieren."""
    lines = []
    for p in report_data:
        if p["ok"]:
            lines.append(
                f"- {p['name']}: Kurs {p['current_price']:.2f} {p['currency']}, "
                f"Δ Woche {p['week_pct']:+.1f}%, Δ Monat {p['month_pct']:+.1f}%, "
                f"G/V seit Kauf {p['gv_pct']:+.1f}%"
            )
        else:
            lines.append(f"- {p['name']}: Kursdaten nicht verfügbar (Ticker prüfen)")

    prompt = f"""Du bist ein sachkundiger Finanzanalyst. Erstelle einen deutschen Wochenkommentar für folgendes Anlageportfolio:

{chr(10).join(lines)}

Erstelle bitte:
1. Einen Gesamtkommentar (3–4 Sätze) zur Portfolioentwicklung der Woche als <p>-Tag.
2. Für jede Position einen knappen Kommentar (1–2 Sätze) zu aktuellen Markt- oder Branchentrends.
   Format: <strong>Positionsname</strong>: Kommentar<br>

Schreibe sachlich und präzise. Keine Anlageempfehlungen."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

# ── HTML-Aufbau ───────────────────────────────────────────────────────────────

def _pct(v) -> str:
    if v is None:
        return '<span style="color:#999">N/A</span>'
    color = "#27ae60" if v >= 0 else "#e74c3c"
    arrow = "▲" if v >= 0 else "▼"
    return f'<span style="color:{color};font-weight:600">{arrow}&nbsp;{abs(v):.1f}%</span>'


def _eur(v) -> str:
    if v is None:
        return '<span style="color:#999">N/A</span>'
    color = "#27ae60" if v >= 0 else "#e74c3c"
    sign  = "+" if v >= 0 else ""
    return f'<span style="color:{color};font-weight:600">{sign}{v:,.0f}&nbsp;€</span>'


def build_html(report_data: list[dict], commentary: str) -> str:
    today    = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    date_str = today.strftime("%d. %B %Y")

    ok_positions = [p for p in report_data if p["ok"]]
    total_wert   = sum(p["wert_eur"]                       for p in ok_positions)
    total_basis  = sum(p["basis"] * p["stueck"] *
                       get_fx_to_eur(p.get("currency", "EUR")) for p in ok_positions)
    total_gv     = total_wert - total_basis
    total_gv_pct = (total_gv / total_basis * 100) if total_basis else 0
    gv_color     = "#27ae60" if total_gv >= 0 else "#e74c3c"
    gv_sign      = "+" if total_gv >= 0 else ""

    rows = []
    for p in report_data:
        kurs  = f"{p['current_price']:.2f}&nbsp;{p['currency']}" if p["ok"] else "N/A"
        wert  = f"{p['wert_eur']:,.0f}&nbsp;€"                   if p["ok"] else "N/A"
        rows.append(f"""
        <tr>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-weight:500;white-space:nowrap">{p['name']}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right;color:#555">{kurs}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right">{_pct(p.get('week_pct'))}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right">{_pct(p.get('month_pct'))}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right;color:#555">{p['basis']:.2f}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right">{_pct(p.get('gv_pct'))}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right">{_eur(p.get('gv_eur'))}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:600">{wert}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:20px;background:#eef1f5;font-family:Arial,Helvetica,sans-serif">
<div style="max-width:920px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 6px 30px rgba(0,0,0,.12)">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:32px 40px">
    <div style="color:#7eb8d4;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px">Wöchentlicher Portfoliobericht</div>
    <div style="color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px">📊 Portfolioanalyse</div>
    <div style="color:#5a8fa8;font-size:14px;margin-top:6px">{date_str}</div>
  </div>

  <!-- Summary Cards -->
  <div style="display:flex;gap:14px;padding:24px 40px;background:#f7f9fc;flex-wrap:wrap">
    <div style="flex:1;min-width:150px;background:#fff;border-radius:10px;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,.07)">
      <div style="color:#8a9bb0;font-size:11px;text-transform:uppercase;letter-spacing:1px">Portfoliowert</div>
      <div style="color:#1a2a3a;font-size:22px;font-weight:700;margin-top:8px">{total_wert:,.0f}&nbsp;€</div>
    </div>
    <div style="flex:1;min-width:150px;background:#fff;border-radius:10px;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,.07)">
      <div style="color:#8a9bb0;font-size:11px;text-transform:uppercase;letter-spacing:1px">Gesamtrendite</div>
      <div style="color:{gv_color};font-size:22px;font-weight:700;margin-top:8px">{gv_sign}{total_gv:,.0f}&nbsp;€</div>
    </div>
    <div style="flex:1;min-width:150px;background:#fff;border-radius:10px;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,.07)">
      <div style="color:#8a9bb0;font-size:11px;text-transform:uppercase;letter-spacing:1px">Performance</div>
      <div style="color:{gv_color};font-size:22px;font-weight:700;margin-top:8px">{gv_sign}{total_gv_pct:.1f}%</div>
    </div>
    <div style="flex:1;min-width:150px;background:#fff;border-radius:10px;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,.07)">
      <div style="color:#8a9bb0;font-size:11px;text-transform:uppercase;letter-spacing:1px">Positionen</div>
      <div style="color:#1a2a3a;font-size:22px;font-weight:700;margin-top:8px">{len(PORTFOLIO)}</div>
    </div>
  </div>

  <!-- Positions Table -->
  <div style="padding:10px 40px 30px">
    <h2 style="color:#1a2a3a;font-size:15px;font-weight:700;margin:20px 0 14px;padding-top:10px">Einzelpositionen</h2>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#0f2027">
          <th style="padding:10px 12px;color:#7eb8d4;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Position</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Kurs</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Δ&nbsp;Woche</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Δ&nbsp;Monat</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Einkauf</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">G/V&nbsp;%</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">G/V&nbsp;€</th>
          <th style="padding:10px 12px;color:#7eb8d4;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap">Wert&nbsp;€</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>
    <p style="color:#aaa;font-size:11px;margin-top:10px">* EUR-Werte werden mit tagesaktuellen Wechselkursen umgerechnet. G/V basiert auf der eingetragenen Einkaufsbasis.</p>
  </div>

  <!-- AI Commentary -->
  <div style="margin:0 40px 32px;background:#f0f6fb;border-left:4px solid #2c5364;border-radius:0 10px 10px 0;padding:24px">
    <h2 style="color:#1a2a3a;font-size:15px;font-weight:700;margin:0 0 14px">🤖 KI-Marktkommentar</h2>
    <div style="color:#2c3e50;font-size:13px;line-height:1.75">{commentary}</div>
  </div>

  <!-- Footer -->
  <div style="background:#0f2027;padding:20px 40px;text-align:center">
    <div style="color:#3a5a70;font-size:11px">Automatisch generierter Bericht · Keine Anlageberatung · Kurse via Yahoo Finance · KI-Kommentar via Claude</div>
  </div>

</div>
</body>
</html>"""

# ── E-Mail versenden ──────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_PASSWORD)
        srv.send_message(msg)

# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    print("📊 Portfolio-Newsletter wird erstellt …")

    print("   → Kursdaten abrufen (Yahoo Finance) …")
    report_data = build_report_data()
    ok = sum(1 for p in report_data if p["ok"])
    print(f"   → {ok}/{len(PORTFOLIO)} Positionen mit Kursdaten")

    print("   → KI-Marktkommentar generieren (Claude) …")
    try:
        commentary = generate_ai_commentary(report_data)
    except Exception as e:
        commentary = f"<p><em>KI-Kommentar konnte nicht generiert werden: {e}</em></p>"

    today   = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    subject = f"📊 Portfolio-Newsletter – {today.strftime('%d.%m.%Y')}"
    html    = build_html(report_data, commentary)

    print(f"   → E-Mail versenden an {RECIPIENT} …")
    send_email(subject, html)
    print("✅ Newsletter erfolgreich versendet!")


if __name__ == "__main__":
    main()
