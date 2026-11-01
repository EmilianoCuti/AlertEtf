#!/usr/bin/env python3
"""Report tecnico giornaliero per i 10 ETF del top 10 AlertEtf."""
import sys
from pathlib import Path

BASE = Path(r"D:\AlertEtf")
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE))
import alrtetf as A

TOP10 = ["CAPE.MI", "JPNK.PA", "IBTS.MI", "AGGH.MI", "IBCI.MI",
         "SPYL.DE", "EMLC.MI", "WRDSC.MI", "COPA.MI", "IQSA.MI"]

def main():
    print("=== TOP10 ETF — DATI TECNICI GIORNALIERI ===")
    print(f"Data: {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print()
    for t in TOP10:
        try:
            a = A.analyze(t)
            print(f"--- {t} ---")
            print(f"Prezzo: {A.fmt(a['price'])} {a['currency']} ({a['change_pct']:+.2f}%)")
            print(f"Trend: {a['trend']} | RSI(14): {a['rsi']:.0f} | ATR: {A.fmt(a['atr'])}")
            print(f"SMA50: {A.fmt(a['sma50'])} | SMA200: {A.fmt(a['sma200'])}")
            print(f"Supporto: {A.fmt(a['support'])} | Resistenza: {A.fmt(a['resistance'])}")
            print(f"Zona acquisto tecnica: {A.fmt(a['buy'][0])}-{A.fmt(a['buy'][1])}")
            print(f"Zona vendita tecnica: {A.fmt(a['sell'][0])}-{A.fmt(a['sell'][1])}")
            print(f"Minimi: YTD {A.fmt(a['ytd_min'])} ({a['ytd_date']}) | 6M {A.fmt(a['six_min'])} ({a['six_date']})")
        except Exception as ex:
            print(f"--- {t} ---")
            print(f"ERRORE: {ex}")
        print()

if __name__ == "__main__":
    main()
