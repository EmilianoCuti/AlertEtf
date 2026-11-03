#!/usr/bin/env python3
"""Archivia un report giornaliero nel master _indice.md (D:\\Archivio_Finanziario)."""
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ARCHIVE = Path(r"D:\Archivio_Finanziario")
INDEX = ARCHIVE / "_indice.md"

def main():
    if len(sys.argv) < 3:
        print("Uso: archive_report.py <file_report> <titolo>")
        sys.exit(1)
    report_path = Path(sys.argv[1])
    title = sys.argv[2]
    if not report_path.exists():
        print(f"File non trovato: {report_path}")
        sys.exit(1)
    # Se il report è fuori dall'archivio (es. outbox), copialo in 03_Report
    try:
        report_path.resolve().relative_to(ARCHIVE.resolve())
    except ValueError:
        dest_dir = ARCHIVE / "03_Report"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / report_path.name
        shutil.copy2(report_path, dest)
        report_path = dest
    # numero progressivo
    text = INDEX.read_text(encoding="utf-8")
    nums = re.findall(r"^\|\s*(\d+)\s*\|", text, re.MULTILINE)
    last = max((int(n) for n in nums), default=0)
    new_num = last + 1
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    rel = report_path.resolve().relative_to(ARCHIVE.resolve())
    rel_posix = str(rel).replace("\\", "/")
    row = f"|{new_num}|{date_str}|{title}|Report|[MD](./{rel_posix})|\n"
    # append before trailing blank lines at end
    text = text.rstrip() + "\n" + row
    # update header count/date
    text = re.sub(r">Ultimo aggiornamento: .*", f">Ultimo aggiornamento: {date_str}", text)
    m = re.search(r">Documenti archiviati: (\d+)", text)
    if m:
        cnt = int(m.group(1)) + 1
        text = re.sub(r">Documenti archiviati: \d+", f">Documenti archiviati: {cnt}", text)
    INDEX.write_text(text, encoding="utf-8")
    print(f"Archiviato #{new_num}: {rel_posix}")

if __name__ == "__main__":
    main()
