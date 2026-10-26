#!/usr/bin/env python3
"""
AlrtEtf - Monitor ETF da terminale con analisi tecnica e alert email.

Comandi:
  python alrtetf.py analyze              # tabella riassuntiva tutti gli ETF
  python alrtetf.py analyze VWCE.DE      # dettaglio di un singolo ETF
  python alrtetf.py once                 # un controllo + accoda gli alert
  python alrtetf.py watch                # controllo continuo (ogni N minuti)
  python alrtetf.py outbox               # mostra gli alert in attesa di invio
  python alrtetf.py mark-sent <id>       # segna un alert come inviato
  python alrtetf.py test-alert           # accoda un alert di prova
  python alrtetf.py add SWDA.MI          # aggiunge un ETF alla lista
  python alrtetf.py remove SWDA.MI       # rimuove un ETF
  python alrtetf.py list                 # mostra la lista ETF configurata
  python alrtetf.py --json analyze       # output in formato JSON

Modalita di invio:
  - Se in .env sono presenti SMTP_USER e SMTP_PASSWORD, l'alert viene inviato
    direttamente via SMTP.
  - Altrimenti l'alert viene accodato in outbox/ e puo essere inviato da
    Autoclaw tramite l'integrazione Gmail gia connessa.

Requisiti:
  pip install pandas yfinance
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "state.json"
ENV_FILE = BASE / ".env"
OUTBOX_DIR = BASE / "outbox"

# WhatsApp via wacli (stesso canale di MfMonitor)
WA_CLI = r"C:\Users\emili\Tools\wacli\wacli.exe"
WA_GROUP_DEFAULT = "120363428742063440@g.us"

DEFAULT_CONFIG = {
    "etfs": ["SWDA.MI", "VWRL.MI", "USDV.MI", "VWCE.MI", "SEGA.MI", "SGLD.MI",
             "IBZL.MI", "EIMI.MI", "EQQQ.MI", "IUSN.DE", "ZPRV.DE", "AGGH.MI",
             "SEME.MI", "AVWC.DE", "AIGA.MI", "AINF.MI", "DFND.MI", "VUAA.MI",
             "EUNA.DE", "SXLP.MI", "JEPI.MI", "SMH.MI", "KOR.MI", "FLXK.MI",
             "EUCL.DE", "QDVE.DE", "QDVG.DE", "DBMF.PA", "SXLE.MI", "2B70.DE",
             "BUG.MI", "QNTM.MI", "IS20.DE", "IB1T.DE", "IUSS.DE", "ETHW.AS",
             "BRNT.L", "KOID.MI", "DIVW.MI", "PCOM.MI", "EEAS.DE", "BTC.MI",
             "NUCL.MI", "2B7A.DE", "COPA.MI", "4GLD.DE", "SBIO.MI", "ASWC.DE",
             "VEUR.MI", "CSSPX.MI", "SJPA.MI", "NDIA.MI", "IEMB.MI", "IHYG.MI"],
    "email": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "to": "tua-email@example.com"
    },
    "whatsapp": {
        "to": WA_GROUP_DEFAULT
    },
    "urgent_tolerance_pct": 0.3,
    "alert_cooldown_pct": 0.5,
    "move_alert_pct": 4.0,
    "max_alerts_per_day": 10,
    "check_interval_minutes": 30,
}


# ------------------------------------------------------------ config --------
def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def alert_count_today(state, key, today):
    """Quanti alert dello stesso tipo/ETF sono gia stati emessi oggi."""
    v = state.get(key)
    if isinstance(v, dict):
        if v.get("date") == today:
            return int(v.get("count", 0))
        return 0
    if v == today:  # formato storico: un solo alert al giorno
        return 1
    return 0


def bump_alert_count(state, key, today):
    """Registra un alert emesso oggi per tipo/ETF."""
    n = alert_count_today(state, key, today) + 1
    state[key] = {"date": today, "count": n}
    return n


# --------------------------------------------------------- indicatori -------
def rsi(close, n=14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down
    return 100 - 100 / (1 + rs)


def atr(df, n=14):
    prev = df["Close"].shift()
    tr = pd.concat(
        [df["High"] - df["Low"],
         (df["High"] - prev).abs(),
         (df["Low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def swing_points(series, window=5, kind="low"):
    """Minimi/massimi locali confermati (punto estremo in una finestra centrata)."""
    roll = series.rolling(2 * window + 1, center=True)
    ext = roll.min() if kind == "low" else roll.max()
    mask = series.eq(ext)
    return series[mask].dropna()


# ----------------------------------------------------------- analisi --------
def analyze(ticker):
    """Restituisce un dizionario con analisi tecnica completa per un ETF."""
    ticker = ticker.upper().strip()
    tk = yf.Ticker(ticker)
    df = tk.history(period="2y", interval="1d", auto_adjust=False)
    df = df.dropna(subset=["Close"])
    if len(df) < 210:
        raise ValueError(f"dati insufficienti per {ticker} ({len(df)} candele, servono >= 210)")

    close = df["Close"]
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else price
    day_low = float(df["Low"].iloc[-1])
    day_high = float(df["High"].iloc[-1])
    change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(close).iloc[-1])
    atr14 = float(atr(df).iloc[-1])

    try:
        currency = tk.fast_info.get("currency", "")
    except Exception:
        currency = ""

    # Supporto / resistenza piu vicini dagli swing degli ultimi 120 giorni
    recent = df.iloc[-120:]
    lows = swing_points(recent["Low"], kind="low")
    highs = swing_points(recent["High"], kind="high")
    sup_c = lows[lows < price]
    res_c = highs[highs > price]
    support = float(sup_c.max()) if len(sup_c) else float(recent["Low"].min())
    resistance = float(res_c.min()) if len(res_c) else float(recent["High"].max())

    # Zone consigliate (ampiezza basata sulla volatilita, ATR)
    buy_low, buy_high = support - 0.25 * atr14, support + 0.5 * atr14
    sell_low, sell_high = resistance - 0.5 * atr14, resistance + 0.25 * atr14

    # Minimi intraday (Low giornaliero)
    tz = df.index.tz
    now = pd.Timestamp.now(tz=tz)
    today_in_data = df.index[-1].date() == now.date()
    ref = df.iloc[:-1] if today_in_data else df

    ytd_start = pd.Timestamp(year=now.year, month=1, day=1, tz=tz)
    six_start = now - pd.DateOffset(months=6)

    def min_of(frame, start):
        sub = frame[frame.index >= start]["Low"]
        if len(sub) == 0:
            return None, None
        return float(sub.min()), sub.idxmin().date()

    ytd_prev, _ = min_of(ref, ytd_start)
    six_prev, _ = min_of(ref, six_start)
    ytd_min, ytd_date = min_of(df, ytd_start)
    six_min, six_date = min_of(df, six_start)

    return {
        "ticker": ticker, "price": price, "sma50": sma50, "sma200": sma200,
        "rsi": rsi14, "atr": atr14, "currency": currency,
        "prev_close": prev_close, "day_low": day_low, "day_high": day_high,
        "change_pct": change_pct,
        "support": support, "resistance": resistance,
        "buy": (buy_low, buy_high), "sell": (sell_low, sell_high),
        "ytd_min": ytd_min, "ytd_date": str(ytd_date) if ytd_date else None, "ytd_prev": ytd_prev,
        "six_min": six_min, "six_date": str(six_date) if six_date else None, "six_prev": six_prev,
        "trend": "rialzista" if price > sma200 else "ribassista",
    }


def evaluate(a, tol_pct, move_pct=4.0):
    """Restituisce l'elenco dei segnali scattati.

    L'alert urgente usa il minimo intraday di giornata (day_low), non solo il
    prezzo: cosi scatta anche quando il minimo viene toccato e poi il prezzo
    rimbalza.
    """
    tol = 1 + tol_pct / 100
    low = a["price"]
    if a.get("day_low") is not None:
        low = min(low, a["day_low"])
    signals = []
    if a["ytd_prev"] is not None and low <= a["ytd_prev"] * tol:
        signals.append(("urgent", "raggiungimento del minimo da inizio anno (YTD)"))
    if a["six_prev"] is not None and low <= a["six_prev"] * tol:
        signals.append(("urgent", "raggiungimento del minimo degli ultimi 6 mesi"))
    if a["price"] <= a["buy"][1] * tol:
        signals.append(("entry", "raggiungimento della zona d'ingresso tecnica"))
    if a["price"] >= a["sell"][0] / tol:
        signals.append(("sell", "raggiungimento della zona di vendita"))
    if abs(a.get("change_pct", 0.0)) >= move_pct:
        direction = "rialzo" if a["change_pct"] >= 0 else "ribasso"
        signals.append(("move", f"variazione percentuale giornaliera >= {move_pct:g}% ({a['change_pct']:+.2f}%, {direction})"))
    return signals


# ------------------------------------------------------------- output -------
def fmt(x):
    if x is None:
        return "n/d"
    return f"{x:,.2f}"


def print_table(results):
    head = f"{'ETF':<12}{'Prezzo':>10}{'RSI':>5}{'Trend':>11}  {'Zona acquisto':<20}{'Zona vendita':<20}{'Min YTD':>10}{'Min 6M':>10}"
    print(head)
    print("-" * len(head))
    for a in results:
        buy = f"{fmt(a['buy'][0])}-{fmt(a['buy'][1])}"
        sell = f"{fmt(a['sell'][0])}-{fmt(a['sell'][1])}"
        print(f"{a['ticker']:<12}{fmt(a['price']):>10}{a['rsi']:>5.0f}{a['trend']:>11}  "
              f"{buy:<20}{sell:<20}{fmt(a['ytd_min']):>10}{fmt(a['six_min']):>10}")


def rsi_label(v):
    if v < 30:
        return "ipervenduto"
    if v < 40:
        return "debole"
    if v <= 60:
        return "neutro"
    if v <= 70:
        return "forte"
    return "ipercomprato"


def pct_distance(from_price, to_level):
    """Distanza percentuale da from_price a to_level."""
    if not from_price or to_level is None:
        return "n/d"
    return f"{(to_level / from_price - 1) * 100:+.2f}%"


def pct_above(price, level):
    """Quanto il prezzo e sopra un livello, in percentuale."""
    if not level:
        return "n/d"
    return f"{(price / level - 1) * 100:+.2f}%"


def details(a, when=None):
    c = a["currency"]
    cur = f" {c}" if c else ""
    when = when or datetime.now().strftime("%d/%m/%Y %H:%M")
    buy_lo, buy_hi = a["buy"]
    sell_lo, sell_hi = a["sell"]

    zone_status = []
    if a["price"] <= buy_hi:
        zone_status.append("prezzo DENTRO la zona di acquisto")
    else:
        gap = abs((a["price"] / buy_hi - 1) * 100)
        zone_status.append(f"prezzo sopra la zona di acquisto del {gap:.2f}%")
    if a["price"] >= sell_lo:
        zone_status.append("prezzo DENTRO la zona di vendita")
    else:
        gap = abs((sell_lo / a["price"] - 1) * 100)
        zone_status.append(f"prezzo sotto la zona di vendita del {gap:.2f}%")

    return (
        f"ETF: {a['ticker']}\n"
        f"Quotazione attuale: {fmt(a['price'])}{cur}  ({a['change_pct']:+.2f}% sulla seduta precedente)\n"
        f"Minimo di oggi: {fmt(a['day_low'])}{cur}  |  Massimo di oggi: {fmt(a['day_high'])}{cur}\n"
        f"\n--- ANALISI TECNICA ---\n"
        f"Trend: {a['trend']} (prezzo {'sopra' if a['trend'] == 'rialzista' else 'sotto'} la SMA200)\n"
        f"SMA50: {fmt(a['sma50'])}{cur}  |  SMA200: {fmt(a['sma200'])}{cur}\n"
        f"RSI(14): {a['rsi']:.0f} ({rsi_label(a['rsi'])})\n"
        f"ATR(14): {fmt(a['atr'])}{cur} (volatilità media giornaliera)\n"
        f"Supporto: {fmt(a['support'])}{cur}  |  Resistenza: {fmt(a['resistance'])}{cur}\n"
        f"\n--- ZONE OPERATIVE ---\n"
        f"Zona acquisto consigliata: {fmt(buy_lo)} - {fmt(buy_hi)}{cur}\n"
        f"Zona vendita consigliata:  {fmt(sell_lo)} - {fmt(sell_hi)}{cur}\n"
        f"Posizionamento: {zone_status[0]}; {zone_status[1]}\n"
        f"\n--- MINIMI INTRADAY ---\n"
        f"Minimo da inizio anno: {fmt(a['ytd_min'])}{cur} ({a['ytd_date'] or 'n/d'}) - distanza dal minimo: {pct_above(a['price'], a['ytd_min'])}\n"
        f"Minimo ultimi 6 mesi:  {fmt(a['six_min'])}{cur} ({a['six_date'] or 'n/d'}) - distanza dal minimo: {pct_above(a['price'], a['six_min'])}\n"
        f"\nRilevato il: {when}\n"
        f"Dati con ritardo fino a ~15 minuti. Non è consulenza finanziaria."
    )


def to_json(results):
    return json.dumps(results, indent=2, ensure_ascii=False, default=str)


# ------------------------------------------------------- alert delivery -----
def _looks_like_placeholder(value):
    """True se il valore e ancora un segnaposto del .env.example."""
    if not value:
        return True
    v = value.strip().lower()
    if "…" in v or "..." in v:
        return True
    for marker in ("la-tua", "tuo-indirizzo", "your-", "<", ">"):
        if marker in v:
            return True
    return len(v) < 6


def smtp_configured(cfg):
    return bool(
        os.environ.get("SMTP_USER")
        and os.environ.get("SMTP_PASSWORD")
        and not _looks_like_placeholder(os.environ.get("SMTP_USER"))
        and not _looks_like_placeholder(os.environ.get("SMTP_PASSWORD"))
        and cfg.get("email", {}).get("to")
    )


def send_email_smtp(cfg, subject, body):
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")
    e = cfg.get("email", {})
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, e["to"], subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(e["smtp_host"], e["smtp_port"], context=ssl.create_default_context()) as s:
        s.login(user, pwd)
        s.send_message(msg)


def queue_alert(cfg, ticker, kind, subject, body):
    """Salva l'alert in outbox/ per l'invio tramite Autoclaw (integrazione Gmail)."""
    OUTBOX_DIR.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    aid = f"{stamp}-{ticker}-{kind}"
    payload = {
        "id": aid,
        "ticker": ticker,
        "kind": kind,
        "to": cfg.get("email", {}).get("to", ""),
        "subject": subject,
        "body": body,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUTBOX_DIR / f"{aid}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return aid


def pending_alerts():
    if not OUTBOX_DIR.exists():
        return []
    out = []
    for f in sorted(OUTBOX_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def mark_sent(alert_id):
    if not OUTBOX_DIR.exists():
        return False
    for f in OUTBOX_DIR.glob(f"*{alert_id}*.json"):
        f.unlink()
        return True
    return False


def deliver(cfg, ticker, kind, subject, body):
    """Invia via SMTP se configurato, altrimenti accoda per Autoclaw.

    Se l'invio SMTP fallisce, l'alert viene comunque accodato per non perdere
    il segnale.
    """
    if smtp_configured(cfg):
        try:
            send_email_smtp(cfg, subject, body)
            return ("smtp", None)
        except Exception as ex:
            aid = queue_alert(cfg, ticker, kind, subject, body)
            return (f"queued (smtp fallito: {ex})", aid)
    return ("queued", queue_alert(cfg, ticker, kind, subject, body))


def get_wa_group(cfg):
    return (cfg.get("whatsapp", {}) or {}).get("to") or WA_GROUP_DEFAULT


def send_wa(text, group=None):
    """Invia un messaggio WhatsApp tramite wacli (stesso canale di MfMonitor)."""
    import subprocess
    grp = group or WA_GROUP_DEFAULT
    try:
        # Windows CreateProcess ha un limite ~32767 caratteri per l'argv:
        # messaggi troppo lunghi fanno fallire wacli con WinError 206.
        CHUNK = 28000
        if len(text) <= CHUNK:
            chunks = [text]
        else:
            chunks = []
            buf = ""
            for line in text.splitlines(keepends=True):
                if len(buf) + len(line) > CHUNK and buf:
                    chunks.append(buf)
                    buf = line
                else:
                    buf += line
            if buf:
                chunks.append(buf)
        ok_all = True
        for c in chunks:
            res = subprocess.run([WA_CLI, "send", "text", "--to", grp, "--message", c],
                                 capture_output=True, text=True, timeout=90)
            if "Sent" not in (res.stdout + res.stderr):
                ok_all = False
        return ok_all
    except Exception as e:
        print(f"[WA errore] {e}")
        return False


def check_and_notify(cfg, tickers, state, json_out=False):
    """Controlla gli ETF e accoda/invia gli alert.

    Limite: max `max_alerts_per_day` alert per tipo/ETF/giorno (default 10).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    max_per_day = int(cfg.get("max_alerts_per_day", 10))
    fired = []
    wa_messages = []
    wa_group = get_wa_group(cfg)
    for t in tickers:
        try:
            a = analyze(t)
        except Exception as ex:
            print(f"[{t}] errore: {ex}")
            fired.append({"ticker": t, "error": str(ex)})
            continue
        signals = evaluate(a, cfg.get("urgent_tolerance_pct", 0.3), cfg.get("move_alert_pct", 4.0))
        kinds = {k for k, _ in signals}
        # Se acquisto e vendita scattano insieme le zone si sovrappongono
        # (supporto e resistenza troppo vicini): in quel caso prevale l'acquisto.
        overlap = {"entry", "sell"} <= kinds
        if overlap:
            kinds.discard("sell")
        print(f"[{datetime.now():%H:%M:%S}] {t} {fmt(a['price'])}  segnali: {sorted(kinds) or '-'}"
              + ("  (zone sovrapposte: prevale l'acquisto)" if overlap else ""))

        SUBJECTS = {
            "urgent": "ACQUISTO URGENTE {t}: Alert per raggiungimento dei minimi",
            "entry": "ALERT {t}: raggiungimento della zona d'ingresso tecnica",
            "sell": "ALERT {t}: raggiungimento della zona di vendita",
            "move": "ALERT {t}: variazione percentuale giornaliera",
        }
        NOTES = {
            "urgent": "Il prezzo ha raggiunto il minimo di riferimento: valutare l'ingresso con priorità (Acquisto urgente).",
            "entry": "Il prezzo è entrato nella zona di acquisto calcolata dall'analisi tecnica (Alert per raggiungimento della zona d'ingresso tecnica).",
            "sell": "Il prezzo è entrato nella zona di vendita calcolata dall'analisi tecnica (Alert per raggiungimento della zona di vendita).",
            "move": "Variazione di seduta superiore alla soglia configurata (Alert per variazione percentuale).",
        }

        for kind in ("urgent", "entry", "sell", "move"):
            if kind not in kinds:
                continue
            key = f"{t}|{kind}"
            if alert_count_today(state, key, today) >= max_per_day:
                continue
            cooldown_pct = float(cfg.get("alert_cooldown_pct", 0.5))
            rec = state.get(key)
            last_price = None
            if isinstance(rec, dict) and rec.get("date") == today:
                last_price = rec.get("last_price")
            ref_price = a["price"]
            if kind in ("urgent", "entry"):
                if a.get("day_low") is not None:
                    ref_price = min(a["price"], a["day_low"])
            if last_price is not None:
                if kind in ("urgent", "entry"):
                    if ref_price > last_price * (1 - cooldown_pct / 100.0):
                        print(f"   · cooldown: nessun nuovo movimento ({ref_price:.2f} vs {last_price:.2f})")
                        continue
                elif kind == "move":
                    if abs(ref_price / last_price - 1) * 100 < cooldown_pct:
                        print(f"   · cooldown: nessun nuovo movimento ({ref_price:.2f} vs {last_price:.2f})")
                        continue
                else:
                    if ref_price < last_price * (1 + cooldown_pct / 100.0):
                        print(f"   · cooldown: nessun nuovo movimento ({ref_price:.2f} vs {last_price:.2f})")
                        continue
            reasons = "; ".join(r for k, r in signals if k == kind)
            if not reasons:
                continue
            subject = SUBJECTS[kind].format(t=t, r=reasons)
            note = NOTES[kind]
            if overlap and kind == "entry":
                note += (" Nota: in questa fase la zona di acquisto e quella di vendita "
                         "si sovrappongono (supporto e resistenza molto vicini).")
            body = f"{note}\nMotivo: {reasons}\n\n{details(a)}"
            try:
                mode, aid = deliver(cfg, t, kind, subject, body)
                n = alert_count_today(state, key, today) + 1
                state[key] = {"date": today, "count": n, "last_price": ref_price}
                save_state(state)
                fired.append({"ticker": t, "kind": kind, "subject": subject,
                              "status": mode, "alert_id": aid, "n_today": n})
                print(f"   -> alert '{kind}' {mode}" + (f" (id {aid})" if aid else "")
                      + f" [{n}/{max_per_day} oggi]")
                wa_messages.append(f"{subject}\n{body}")
            except Exception as ex:
                fired.append({"ticker": t, "kind": kind, "status": f"errore: {ex}"})
                print(f"   ! invio alert fallito: {ex}")
            if kind == "urgent":
                ek = f"{t}|entry"
                n_entry = alert_count_today(state, ek, today) + 1
                state[ek] = {"date": today, "count": n_entry, "last_price": ref_price}
                save_state(state)
                break
    if wa_messages:
        wa_ok = send_wa("\n\n".join(wa_messages), group=wa_group)
        print(f"WhatsApp: {'inviato' if wa_ok else 'FALLITO'} ({len(wa_messages)} alert) -> {wa_group}")
    if json_out:
        print(json.dumps(fired, indent=2, ensure_ascii=False))
    return fired


# ---------------------------------------------------------------- main ------
def main():
    load_env()
    p = argparse.ArgumentParser(description="AlrtEtf - monitor ETF con alert WhatsApp + email")
    p.add_argument("cmd", choices=["analyze", "once", "watch", "outbox", "mark-sent",
                                   "test-alert", "test-email", "add", "remove", "list",
                                   "doctor"])
    p.add_argument("tickers", nargs="*")
    p.add_argument("--json", action="store_true", help="output in formato JSON")
    args = p.parse_args()
    cfg = load_config()

    if args.cmd == "list":
        print("ETF configurati:")
        for t in cfg.get("etfs", []):
            print(f"  - {t}")
        return

    if args.cmd == "doctor":
        import subprocess
        print("AlrtEtf doctor")
        print(f"  BASE: {BASE}")
        print(f"  config: {CONFIG_FILE.exists()}")
        cfg = load_config()
        print(f"  ETF: {len(cfg.get('etfs', []))}")
        print(f"  WA gruppo: {get_wa_group(cfg)}")
        print("  wacli:")
        try:
            res = subprocess.run([WA_CLI, "doctor"], capture_output=True, text=True, timeout=60)
            out = res.stdout + res.stderr
            print("   ", "✓ autenticato" if "AUTHENTICATED     true" in out else "✗ non autenticato")
            print("   ", "connesso" if "CONNECTED         true" in out else "disconnesso (si riconnette all'invio)")
        except Exception as ex:
            print(f"   ✗ {ex}")
        return

    if args.cmd == "outbox":
        alerts = pending_alerts()
        if not alerts:
            print("Nessun alert in attesa.")
            return
        if args.json:
            print(json.dumps(alerts, indent=2, ensure_ascii=False))
            return
        print(f"{len(alerts)} alert in attesa di invio:")
        for a in alerts:
            print(f"\n[{a['id']}] {a['subject']}\n  a: {a['to']}\n  creato: {a['created_at']}")
        return

    if args.cmd == "mark-sent":
        if not args.tickers:
            print("Specifica l'id dell'alert: mark-sent <id>")
            return
        ok = all(mark_sent(i) for i in args.tickers)
        print("Alert segnati come inviati." if ok else "Alert non trovato.")
        return

    if args.cmd == "test-alert":
        aid = queue_alert(cfg, "TEST", "test",
                          "Test AlrtEtf - alert di prova",
                          "Questo e un alert di prova generato da AlrtEtf.\n"
                          "Se lo ricevi, la catena di invio funziona correttamente.")
        print(f"Alert di prova accodato: {aid}")
        return

    if args.cmd == "test-email":
        if not smtp_configured(cfg):
            print("SMTP non configurato. Usa 'test-alert' per accodare un alert "
                  "e inviarlo tramite Autoclaw.")
            return
        send_email_smtp(cfg, "Test AlrtEtf", "La configurazione SMTP di AlrtEtf funziona.")
        print("Email di prova inviata via SMTP.")
        return

    if args.cmd in ("add", "remove"):
        for t in (x.upper() for x in args.tickers):
            if args.cmd == "add" and t not in cfg["etfs"]:
                cfg["etfs"].append(t)
            if args.cmd == "remove" and t in cfg["etfs"]:
                cfg["etfs"].remove(t)
        save_config(cfg)
        print("Lista ETF:", ", ".join(cfg["etfs"]) or "(vuota)")
        return

    tickers = [t.upper() for t in args.tickers] or cfg.get("etfs", [])

    if args.cmd == "analyze":
        results = []
        for t in tickers:
            try:
                results.append(analyze(t))
            except Exception as ex:
                print(f"[{t}] errore: {ex}")
        if results:
            if args.json:
                print(to_json(results))
            else:
                print_table(results)
                print()
                for a in results:
                    print(details(a), end="\n\n")
    elif args.cmd == "once":
        check_and_notify(cfg, tickers, load_state(), json_out=args.json)
    elif args.cmd == "watch":
        interval = cfg.get("check_interval_minutes", 30) * 60
        print(f"Monitoraggio di {', '.join(tickers)} ogni {interval // 60} min. Ctrl+C per uscire.")
        state = load_state()
        try:
            while True:
                check_and_notify(cfg, tickers, state, json_out=args.json)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nInterrotto.")


if __name__ == "__main__":
    sys.exit(main())
