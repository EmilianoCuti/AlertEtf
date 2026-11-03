#!/usr/bin/env python3
"""Invia via wacli il contenuto di un file (chunked per limite argv Windows)."""
import subprocess
import sys
from pathlib import Path

WA_CLI = r"C:\Users\emili\Tools\wacli\wacli.exe"
GROUP = "120363430097651361@g.us"  # Top10

def main():
    if len(sys.argv) < 2:
        print("Uso: send_whatsapp.py <file>")
        sys.exit(1)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
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
        res = subprocess.run([WA_CLI, "send", "text", "--to", GROUP, "--message", c],
                             capture_output=True, text=True, timeout=90)
        if "Sent" not in (res.stdout + res.stderr):
            ok_all = False
            print(f"[WA errore] {res.stdout} {res.stderr}")
    print("WhatsApp: inviato" if ok_all else "WhatsApp: FALLITO")
    sys.exit(0 if ok_all else 1)

if __name__ == "__main__":
    main()
