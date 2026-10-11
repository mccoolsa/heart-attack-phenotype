"""Download the MIMIC-IV Clinical Database Demo v2.2 hosp tables and verify checksums.

Open access (ODbL 1.0), no PhysioNet credentialing needed:
https://physionet.org/content/mimic-iv-demo/2.2/
"""
import hashlib
import urllib.request
from pathlib import Path

BASE = "https://physionet.org/files/mimic-iv-demo/2.2/"
TABLES = ["patients", "admissions", "diagnoses_icd", "procedures_icd", "labevents",
          "d_icd_diagnoses", "d_icd_procedures", "d_labitems", "transfers"]
OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "mimic-iv-demo-2.2"


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())


def main() -> None:
    (OUT / "hosp").mkdir(parents=True, exist_ok=True)
    for name in ("SHA256SUMS.txt", "LICENSE.txt"):
        fetch(BASE + name, OUT / name)
    sums = dict(reversed(line.split()) for line in (OUT / "SHA256SUMS.txt").read_text().splitlines() if line.strip())
    for t in TABLES:
        rel = f"hosp/{t}.csv.gz"
        dest = OUT / rel
        if not dest.exists():
            fetch(BASE + rel, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        assert digest == sums[rel], f"checksum mismatch for {rel}"
        print(f"ok  {rel}")


if __name__ == "__main__":
    main()
