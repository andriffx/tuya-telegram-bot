"""Guard privasi: repo ini publik, jadi tidak boleh ada ID Telegram asli di dalamnya.

Yang dicek: deretan angka 9-10 digit (panjang ID Telegram) di file teks yang di-track.
Angka dummy yang dipakai dokumentasi/test masuk allowlist.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".example", ".yml", ".yaml", ".toml", ".sh", ".html", ".js", ".css"}
ID_PATTERN = re.compile(r"\b\d{9,10}\b")

# Hanya angka dummy. Tambahkan di sini bila butuh contoh baru — jangan pakai ID asli.
ALLOWED_NUMBERS = {
    "123456789",   # contoh di .env.example / README / teks bot
    "987654321",   # contoh format daftar ID
    "111111111",   # fixture test migrasi JSON
    "222222222",   # fixture test migrasi JSON
}


def _tracked_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
            yield path


def test_no_personal_telegram_ids_in_repo_files():
    offenders = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in ID_PATTERN.finditer(text):
            if match.group() not in ALLOWED_NUMBERS:
                offenders.append(f"{path.relative_to(ROOT)}: {match.group()}")

    assert not offenders, (
        "Angka mirip ID Telegram asli ditemukan di repo publik: "
        + ", ".join(offenders)
        + " — ganti dengan dummy atau tambahkan ke ALLOWED_NUMBERS bila memang dummy."
    )


IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Alamat yang boleh muncul di dokumentasi: loopback, alamat fiktif untuk contoh,
# dan default jaringan Docker. Alamat infrastruktur sungguhan TIDAK boleh ada.
ALLOWED_IPS = {
    "127.0.0.1",
    "0.0.0.0",
    "10.0.0.1",
    "10.0.0.2",
    "172.17.0.0",
    "172.17.0.1",
    "172.18.0.0",
    "172.18.0.1",
}

DOC_SUFFIXES = {".md", ".example"}


def test_no_real_infrastructure_ips_in_docs():
    """Repo ini publik: dokumentasi hanya boleh memakai alamat contoh/fiktif."""
    offenders = []
    for path in _tracked_text_files():
        if path.suffix not in DOC_SUFFIXES and path.name != ".env.example":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in IPV4_PATTERN.finditer(text):
            if match.group() not in ALLOWED_IPS:
                offenders.append(f"{path.relative_to(ROOT)}: {match.group()}")

    assert not offenders, (
        "Alamat IP infrastruktur ditemukan di dokumentasi publik: "
        + ", ".join(sorted(set(offenders)))
        + " — ganti dengan contoh fiktif (mis. 10.0.0.2)."
    )
