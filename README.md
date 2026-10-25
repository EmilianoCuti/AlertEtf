# AlrtEtf — Monitor ETF con analisi tecnica e alert email

App da terminale che analizza una lista di ETF, calcola le zone di acquisto/vendita
e i minimi intraday, e invia alert via email tramite **Autoclaw** (Gmail già connesso)
oppure via SMTP diretto.

## Installazione rapida

```bash
pip install pandas yfinance
```

Poi modifica `config.json` impostando la **tua email** nel campo `email.to`
e verifica la lista ETF in `etfs`. Avvio:

```bash
python3 alrtetf.py analyze     # panoramica su tutti gli ETF
python3 alrtetf.py once        # un controllo + accoda gli alert scattati
```

## ETF monitorati (22)

| ETF | Mercato | Valuta |
|-----|---------|--------|
| SWDA.MI | Borsa Italiana | EUR |
| VWRL.MI | Borsa Italiana | EUR |
| USDV.MI | Borsa Italiana | EUR |
| VWCE.MI | Borsa Italiana | EUR |
| SEGA.MI | Borsa Italiana | EUR |
| SGLD.MI | Borsa Italiana | EUR |
| IBZL.MI | Borsa Italiana | EUR |
| EIMI.MI | Borsa Italiana | EUR |
| EQQQ.MI | Borsa Italiana | EUR |
| IUSN.DE | Xetra | EUR |
| ZPRV.DE | Xetra | EUR |
| AGGH.MI | Borsa Italiana | EUR |
| SEME.MI | Borsa Italiana | EUR |
| AVWC.DE | Xetra | EUR |
| AIGA.MI | Borsa Italiana | EUR |
| AINF.MI | Borsa Italiana | EUR |
| DFND.MI | Borsa Italiana | EUR |
| VUAA.MI | Borsa Italiana | EUR |
| EUNA.DE | Xetra | EUR |
| SXLP.MI | Borsa Italiana | EUR |
| JEPI.MI | Borsa Italiana | EUR |
| SMH.MI | Borsa Italiana | EUR |

## Cosa calcola

- **Analisi tecnica**: prezzo, SMA50, SMA200, RSI(14), ATR(14), supporto, resistenza, trend
- **Zona acquisto consigliata**: supporto ± volatilità (ATR)
- **Zona vendita consigliata**: resistenza ± volatilità (ATR)
- **Minimo intraday da inizio anno (YTD)**
- **Minimo intraday degli ultimi 6 mesi**

## Comandi

| Comando | Descrizione |
|---------|-------------|
| `python3 alrtetf.py analyze` | Tabella riassuntiva di tutti gli ETF |
| `python3 alrtetf.py analyze VWCE.MI` | Dettaglio di un singolo ETF |
| `python3 alrtetf.py once` | Un controllo + accoda gli alert scattati |
| `python3 alrtetf.py watch` | Controllo continuo (ogni 30 min) |
| `python3 alrtetf.py outbox` | Mostra gli alert in attesa di invio |
| `python3 alrtetf.py mark-sent <id>` | Segna un alert come inviato |
| `python3 alrtetf.py test-alert` | Accoda un alert di prova |
| `python3 alrtetf.py add SWDA.MI` | Aggiunge un ETF |
| `python3 alrtetf.py remove SWDA.MI` | Rimuove un ETF |
| `python3 alrtetf.py list` | Mostra la lista ETF |
| `python3 alrtetf.py --json analyze` | Output JSON |

## Come funzionano gli alert

1. `once` controlla ogni ETF e rileva tre tipi di segnale:
   - **Zona d'ingresso** — il prezzo entra nella zona di acquisto calcolata dall'analisi tecnica
   - **Zona di vendita** — il prezzo entra nella zona di vendita calcolata dall'analisi tecnica
   - **Acquisto urgente** — il prezzo (o il minimo intraday di giornata) raggiunge il minimo
     da inizio anno o quello degli ultimi 6 mesi
2. Ogni segnale viene accodato come file JSON in `outbox/`.
3. Autoclaw legge l'outbox e invia la mail tramite l'integrazione **Gmail già connessa**
   (oppure si usa l'invio SMTP diretto, vedi sotto).
4. Dopo l'invio l'alert viene rimosso dall'outbox con `mark-sent`.

Ogni mail contiene: quotazione attuale e variazione di seduta, minimo e massimo di oggi,
trend, SMA50/SMA200, RSI con interpretazione, ATR, supporto e resistenza, entrambe le
zone operative con il posizionamento del prezzo, e i minimi YTD/6 mesi con la distanza
percentuale dal prezzo.

Note:
- L'alert urgente scatta anche se il minimo viene toccato **intraday** e poi il prezzo rimbalza
  (usa il minimo di giornata, non solo il prezzo di chiusura).
- Se zona di acquisto e zona di vendita si sovrappongono (supporto e resistenza molto vicini),
  prevale l'alert di acquisto e la mail lo segnala.
- Anti-spam: massimo **10 alert per tipo/ETF/giorno** (configurabile con `max_alerts_per_day` in `config.json`).

### Esecuzione automatica

Con Autoclaw si può creare un cron job ogni 30 minuti che esegue `once`, legge l'outbox
e invia gli alert via Gmail.

### Invio SMTP diretto (opzionale)

Se preferisci l'invio diretto senza passare da Autoclaw, copia `.env.example` in `.env`
e compila con credenziali SMTP valide (`SMTP_USER`, `SMTP_PASSWORD`). Il codice rileva
i segnaposto e in quel caso usa automaticamente l'outbox.

## Configurazione

| Campo in `config.json` | Significato |
|------------------------|-------------|
| `etfs` | Lista dei ticker da monitorare |
| `email.to` | Destinatario degli alert |
| `email.smtp_host` / `smtp_port` | Server SMTP (solo per invio diretto) |
| `urgent_tolerance_pct` | Tolleranza % per l'alert urgente sui minimi (default 0.3) |
| `max_alerts_per_day` | Max alert per tipo/ETF/giorno (default 10) |
| `check_interval_minutes` | Intervallo del comando `watch` (default 30) |

## File non versionati

`state.json`, `outbox/` e `.env` sono in `.gitignore` perché contengono stato locale
e dati personali. `state.json` viene creato automaticamente al primo avvio.

## Disclaimer

Non è consulenza finanziaria. I dati sono con ritardo fino a ~15 minuti.
