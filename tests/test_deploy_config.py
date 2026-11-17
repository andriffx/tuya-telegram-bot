"""Guard untuk artefak deploy: Dockerfile dan docker-compose.

Tujuannya menahan regresi yang mahal: API terbuka ke publik, container jalan
sebagai root, atau volume persisten hilang sehingga database SQLite ikut terhapus
saat redeploy.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = ROOT / "docker-compose.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile"


@pytest.fixture(scope="module")
def service():
    data = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return data["services"]["tuyabot"]


def test_no_settings_hardcoded_in_compose(service):
    """Compose hanya mengatur struktur; semua nilai datang dari .env."""
    assert "environment" not in service, (
        "jangan menaruh nilai konfigurasi di compose — pindahkan ke .env"
    )
    assert service["env_file"], "compose harus membaca .env"
    paths = [item["path"] if isinstance(item, dict) else item for item in service["env_file"]]
    assert ".env" in paths


def test_env_example_documents_bind_and_paths():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "API_HOST=127.0.0.1" in text
    assert "API_PORT=8080" in text
    assert "SQLITE_PATH=data/tuyabot.db" in text
    assert "TZ=" in text


def test_api_default_is_loopback_not_public():
    """Kalau .env lupa diisi, bind default harus tetap aman."""
    source = (ROOT / "src/tuyabot/main.py").read_text(encoding="utf-8")
    assert 'os.getenv("API_HOST", "127.0.0.1")' in source
    assert 'os.getenv("API_HOST", "0.0.0.0")' not in source


def test_database_path_points_to_mounted_volume(service):
    """SQLITE_PATH relatif terhadap WORKDIR /app, jadi ./data/tuyabot.db ikut volume."""
    volumes = " ".join(service["volumes"])
    assert "./data:/app/data" in volumes
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SQLITE_PATH=data/tuyabot.db" in text


def test_container_is_hardened(service):
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
    # Hanya capability yang dibutuhkan entrypoint (chown + setpriv).
    assert set(service["cap_add"]) == {"CHOWN", "SETUID", "SETGID"}
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["logging"]["options"]["max-size"] == "10m"


def test_persistent_volumes_present(service):
    volumes = " ".join(service["volumes"])
    for expected in ("./logs:/app/logs", "./data:/app/data", "./backup:/app/backup"):
        assert expected in volumes, f"volume {expected} hilang"


def test_entrypoint_fixes_ownership_then_drops_privileges():
    """Volume yang dimiliki root harus diperbaiki otomatis, bukan oleh operator."""
    text = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    for directory in ("/app/logs", "/app/data", "/app/backup"):
        assert directory in text
    assert "chown -R" in text
    assert "setpriv" in text and "--reuid" in text
    # Wajib exec: kalau tidak, aplikasi jalan sebagai child dan sinyal shutdown
    # (SIGTERM) tidak sampai ke proses Python.
    assert text.count("exec ") >= 2

    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]' in dockerfile
    assert 'CMD ["python", "-m", "tuyabot.main"]' in dockerfile


def test_compiler_kept_out_of_runtime_stage():
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    runtime_stage = text.split("FROM python:3.11-slim AS runtime", 1)
    assert len(runtime_stage) == 2, "stage runtime tidak ditemukan"
    assert "build-essential" not in runtime_stage[1], "compiler tidak boleh ikut ke image akhir"


def test_migration_dependency_only_in_migration_stage():
    """mysql-connector tidak boleh masuk runtime, tapi harus ada untuk skrip migrasi."""
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    runtime_and_after = text.split("FROM python:3.11-slim AS runtime", 1)[1]
    runtime_only = runtime_and_after.split("FROM runtime AS migration", 1)[0]
    migration_only = runtime_and_after.split("FROM runtime AS migration", 1)[1]

    assert "mysql-connector-python" not in runtime_only
    assert "mysql-connector-python" in migration_only
    assert "AS migration" in text
