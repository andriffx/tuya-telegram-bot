"""
Script pembantu untuk scan perangkat Tuya di jaringan lokal.
Jalankan ini sebelum menjalankan bot untuk mendapatkan informasi perangkat.
"""

import tinytuya
import json


def scan_devices():
    """Scan perangkat Tuya di jaringan lokal."""
    print("🔍 Scanning perangkat Tuya di jaringan lokal...")
    print("=" * 50)
    
    # Scan network
    devices = tinytuya.deviceScan(verbose=False, maxretry=15)
    
    if not devices:
        print("❌ Tidak ada perangkat Tuya ditemukan.")
        print("\nTips:")
        print("• Pastikan perangkat sudah terpasang dan menyala")
        print("• Pastikan PC/handphone di jaringan WiFi yang SAMA")
        print("• Coba jalankan lagi setelah beberapa detik")
        return
    
    print(f"✅ Ditemukan {len(devices)} perangkat:\n")
    
    for ip, info in devices.items():
        print(f"📱 Device Name: {info.get('name', 'Unknown')}")
        print(f"   IP Address : {ip}")
        print(f"   Device ID  : {info.get('id', 'N/A')}")
        print(f"   Product    : {info.get('productKey', 'N/A')}")
        print(f"   Version    : {info.get('version', 'N/A')}")
        print("-" * 50)
    
    print("\n📝 Salin informasi di atas ke file config.py")
    print("   Pastikan juga Anda memiliki LOCAL KEY dari Tuya Cloud.")


def scan_with_cloud():
    """Scan menggunakan Tuya Cloud API (memerlukan API key)."""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    api_key = os.getenv("TUYA_API_KEY")
    api_secret = os.getenv("TUYA_API_SECRET")
    region = os.getenv("TUYA_REGION", "eu")
    
    if not api_key or not api_secret:
        print("❌ TUYA_API_KEY dan TUYA_API_SECRET belum di-set di .env")
        return
    
    print(f"☁️ Menghubungkan ke Tuya Cloud ({region})...")
    
    c = tinytuya.Cloud(
        apiRegion=region,
        apiKey=api_key,
        apiSecret=api_secret,
        apiDeviceID=os.getenv("TUYA_DEVICE_ID", "")
    )
    
    # Get list of devices
    devices = c.getdevices()
    
    print(f"✅ Ditemukan {len(devices)} perangkat di cloud:\n")
    
    for dev in devices:
        print(f"📱 Name      : {dev.get('name', 'Unknown')}")
        print(f"   ID        : {dev.get('id', 'N/A')}")
        print(f"   Local Key : {dev.get('key', 'N/A')}")
        print(f"   IP        : {dev.get('ip', 'N/A')}")
        print(f"   Version   : {dev.get('version', 'N/A')}")
        print("-" * 50)


if __name__ == "__main__":
    print("Pilih metode scan:")
    print("1. Scan jaringan lokal (tanpa cloud)")
    print("2. Scan via Tuya Cloud API (memerlukan API key)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == "1":
        scan_devices()
    elif choice == "2":
        scan_with_cloud()
    else:
        print("Pilihan tidak valid.")
