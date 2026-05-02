"""
Script test koneksi ke perangkat Tuya.
Jalankan ini untuk mendiagnosis masalah jaringan.
"""

import socket
import sys
from config import DEVICES


def test_ping(ip: str, timeout: int = 3) -> bool:
    """Test apakah IP bisa di-ping (TCP connect ke port 6668)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, 6668))
        sock.close()
        return result == 0
    except Exception:
        return False


def test_device(name: str, info: dict):
    """Test koneksi ke satu perangkat."""
    print(f"\n{'='*50}")
    print(f"📱 TEST: {name.upper()}")
    print(f"{'='*50}")
    print(f"   Device ID : {info['id']}")
    print(f"   IP        : {info.get('ip', '(auto)')}")
    print(f"   Version   : {info.get('version', '3.3')}")
    print(f"   DPS Switch: {info.get('dps_switch', 1)}")

    ip = info.get("ip", "")
    if not ip:
        print(f"\n   ⚠️  IP kosong — tidak bisa test koneksi.")
        print(f"   Jalankan: python -m tinytuya scan")
        return

    # Test 1: Ping port 6668
    print(f"\n   🔌 Test TCP port 6668 ...")
    if test_ping(ip):
        print(f"   ✅ Port 6668 TERBUKA — perangkat online!")
    else:
        print(f"   ❌ Port 6668 TIDAK bisa diakses")
        print(f"\n   🔍 Kemungkinan penyebab:")
        print(f"      • PC ini dan perangkat beda jaringan WiFi")
        print(f"      • Perangkat mati atau offline")
        print(f"      • IP salah (perangkat dapat IP baru dari DHCP)")
        print(f"      • Firewall/router memblok port 6668")
        return

    # Test 2: Coba konek pakai tinytuya
    print(f"\n   🔌 Test tinytuya connection ...")
    try:
        import tinytuya
        d = tinytuya.Device(
            dev_id=info["id"],
            address=ip,
            local_key=info["local_key"],
            version=info.get("version", 3.3)
        )
        status = d.status()
        print(f"   ✅ tinytuya BERHASIL connect!")
        print(f"   📊 Status: {status}")
    except Exception as e:
        print(f"   ❌ tinytuya GAGAL: {e}")
        print(f"\n   🔍 Kemungkinan:")
        print(f"      • Local Key salah")
        print(f"      • Versi protokol salah (coba 3.1, 3.3, 3.4, 3.5)")


def main():
    print("🧪 TUYA CONNECTION TESTER")
    print("=" * 50)
    print("\n📋 Perangkat yang terkonfigurasi:")
    for name, info in DEVICES.items():
        ip = info.get("ip", "(auto)")
        print(f"   • {name}: {ip}")

    # Test network interface
    print(f"\n🌐 Network Info:")
    try:
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        print(f"   Hostname : {hostname}")
        print(f"   Local IP : {local_ip}")
    except Exception:
        pass

    for name, info in DEVICES.items():
        test_device(name, info)

    print(f"\n{'='*50}")
    print("📖 Troubleshooting:")
    print("=" * 50)
    print("""
1. Pastikan PC/server ini di jaringan WiFi YANG SAMA dengan perangkat Tuya
2. Coba scan ulang IP perangkat:
   python -m tinytuya scan
3. Jika IP berbeda, update di file .env:
   DEVICE_AIR_IP=xxx.xxx.xxx.xxx
   DEVICE_LAMPU_IP=xxx.xxx.xxx.xxx
4. Jika bot berjalan di VPS/cloud — tinytuya lokal TIDAK akan bekerja.
   Solusi: jalankan bot di PC/Raspberry Pi di rumah, atau pakai Tuya Cloud API.
5. Cek apakah port 6668 diblok firewall:
   sudo ufw allow 6668/tcp   (Linux)
   
""")


if __name__ == "__main__":
    main()
