"""
KKTC Merkez Bankası DİBS İhale ve Stok Verisi Çekme Aracı
GitHub Actions ile otomatik çalıştırılır, data.json üretir.
"""

import requests
from bs4 import BeautifulSoup
import json
import urllib3
from datetime import datetime
import sys
import time
import os
import re

# SSL uyarılarını gizle (mb.gov.ct.tr sertifika sorunu var)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Tüm kaynak URL'ler
URLS = {
    "tlRaw":        "https://mb.gov.ct.tr/tr/dibs-ihaleleri",
    "fxRaw":        "https://mb.gov.ct.tr/tr/node/4717",
    "tlStockRaw":   "https://mb.gov.ct.tr/tr/dibs-stoku",
    "usdStockRaw":  "https://mb.gov.ct.tr/tr/node/4718",
    "eurStockRaw":  "https://mb.gov.ct.tr/tr/node/4779",
    "gbpStockRaw":  "https://mb.gov.ct.tr/tr/node/5694",
}

# Her kaynak için beklenen minimum sütun sayısı
MIN_COLUMNS = {
    "tlRaw": 7, "fxRaw": 8,
    "tlStockRaw": 4, "usdStockRaw": 4,
    "eurStockRaw": 4, "gbpStockRaw": 4,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
}

MAX_RETRIES = 3
BASE_DELAY = 5  # saniye


def fetch_page(url: str, retries: int = MAX_RETRIES) -> str | None:
    """URL'yi retry mantığıyla çeker."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url, headers=HEADERS,
                verify=False, timeout=20
            )
            resp.raise_for_status()
            # Türkçe karakterler için doğru encoding
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as e:
            print(f"  [Deneme {attempt}/{retries}] Hata: {e}")
            if attempt < retries:
                wait = BASE_DELAY * attempt
                print(f"  {wait}s bekleniyor...")
                time.sleep(wait)
    return None


def clean_cell(text: str) -> str:
    """Hücre metnini temizler: dipnot numaraları, fazla boşluklar."""
    text = text.strip()
    # Satır sonundaki bağımsız sayıları (dipnot işaretleri) temizle: "KKT250222T17 1" → "KKT250222T17"
    text = re.sub(r'\s+\d+$', '', text)
    # Çoklu boşlukları tek boşluğa indir
    text = re.sub(r'\s+', ' ', text)
    return text


def parse_table(html: str, min_cols: int = 4) -> list:
    """HTML'deki en büyük veri tablosunu ayrıştırır."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return []

    # En çok veri satırı olan tabloyu bul
    best_table = None
    max_data_rows = 0

    for table in tables:
        rows = table.find_all("tr")
        data_rows = sum(
            1 for r in rows
            if len(r.find_all("td")) >= min_cols
        )
        if data_rows > max_data_rows:
            max_data_rows = data_rows
            best_table = table

    if not best_table:
        return []

    result = []
    for row in best_table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < min_cols:
            continue
        cells = [clean_cell(td.get_text()) for td in tds]
        result.append(cells)

    return result


def main():
    output_file = sys.argv[1] if len(sys.argv) > 1 else "data.json"

    print("=" * 60)
    print("KKTC Merkez Bankası Veri Çekme Aracı")
    print("=" * 60)
    print(f"Çıktı: {output_file}")
    print(f"Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {}
    }

    success = 0
    total = len(URLS)

    for key, url in URLS.items():
        min_cols = MIN_COLUMNS.get(key, 4)
        print(f"[{key}] Çekiliyor: {url}")

        html = fetch_page(url)

        if html:
            parsed = parse_table(html, min_cols)
            data[key] = parsed
            data["sources"][key] = {
                "url": url,
                "rows": len(parsed),
                "status": "ok"
            }
            print(f"  ✓ {len(parsed)} satır")
            success += 1
        else:
            data[key] = []
            data["sources"][key] = {
                "url": url,
                "rows": 0,
                "status": "failed"
            }
            print(f"  ✗ Başarısız")

        # Sunucuyu yormamak için kısa bekleme
        time.sleep(1)

    # Dosyaya yaz
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(output_file) / 1024
    print()
    print("=" * 60)
    print(f"Sonuç: {success}/{total} kaynak başarılı")
    print(f"Dosya: {output_file} ({size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
