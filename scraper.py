"""
KKTC Merkez Bankası DİBS İhale ve Stok Verisi Çekme Aracı
Geliştirilmiş sürüm: Header satırları, raw HTML snippet, debug bilgisi
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URLS = {
    "tlRaw":        "https://mb.gov.ct.tr/tr/dibs-ihaleleri",
    "fxRaw":        "https://mb.gov.ct.tr/tr/node/4717",
    "tlStockRaw":   "https://mb.gov.ct.tr/tr/dibs-stoku",
    "usdStockRaw":  "https://mb.gov.ct.tr/tr/node/4718",
    "eurStockRaw":  "https://mb.gov.ct.tr/tr/node/4779",
    "gbpStockRaw":  "https://mb.gov.ct.tr/tr/node/5694",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

MAX_RETRIES = 3
BASE_DELAY = 5


def fetch_page(url: str, retries: int = MAX_RETRIES) -> tuple:
    """URL'yi çeker. (html_str, status_code, error_msg) döner."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, verify=False, timeout=25)
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text, resp.status_code, None
        except requests.RequestException as e:
            print(f"  [Deneme {attempt}/{retries}] Hata: {e}")
            if attempt < retries:
                time.sleep(BASE_DELAY * attempt)
    return None, None, "Tüm denemeler başarısız"


def clean_cell(text: str) -> str:
    """Hücre metnini temizler."""
    if not text:
        return ""
    text = text.strip()
    # Satır sonundaki bağımsız sayıları (dipnot) temizle
    text = re.sub(r'\s+\d{1,2}$', '', text)
    # Çoklu boşlukları tek boşluğa
    text = re.sub(r'\s+', ' ', text)
    return text


def parse_table_enhanced(html: str, min_cols: int = 4) -> dict:
    """
    Geliştirilmiş tablo ayrıştırma.
    Header satırlarını ve veri satırlarını ayırır.
    Birden fazla tablo stratejisi dener.
    """
    if not html:
        return {"headers": [], "data": [], "rawSnippet": ""}

    soup = BeautifulSoup(html, "html.parser")

    # Raw HTML snippet (ilk 3000 karakter) — debug için
    raw_snippet = html[:3000]

    # Tüm tabloları bul
    tables = soup.find_all("table")
    if not tables:
        return {"headers": [], "data": [], "rawSnippet": raw_snippet}

    # Strateji 1: En çok td satırı olan tablo
    best_table = None
    max_data_rows = 0
    for table in tables:
        rows = table.find_all("tr")
        data_rows = sum(1 for r in rows if len(r.find_all("td")) >= min_cols)
        if data_rows > max_data_rows:
            max_data_rows = data_rows
            best_table = table

    # Strateji 2: Eğer hiç td bulunamadı, th satırlarını kontrol et
    if not best_table or max_data_rows == 0:
        for table in tables:
            rows = table.find_all("tr")
            th_rows = sum(1 for r in rows if len(r.find_all("th")) >= min_cols)
            td_rows = sum(1 for r in rows if len(r.find_all("td")) >= min_cols)
            total = th_rows + td_rows
            if total > max_data_rows:
                max_data_rows = total
                best_table = table

    if not best_table:
        return {"headers": [], "data": [], "rawSnippet": raw_snippet}

    headers = []
    data = []

    for row in best_table.find_all("tr"):
        # Önce th hücreleri
        th_cells = row.find_all("th")
        td_cells = row.find_all("td")

        if th_cells and len(th_cells) >= min_cols:
            # Bu bir header satırı
            headers = [clean_cell(tc.get_text()) for tc in th_cells]
        elif td_cells and len(td_cells) >= min_cols:
            # Bu bir veri satırı
            cells = [clean_cell(tc.get_text()) for tc in td_cells]
            data.append(cells)

    return {
        "headers": headers,
        "data": data,
        "rawSnippet": raw_snippet,
        "totalRowsInTable": len(best_table.find_all("tr")),
        "dataRowsExtracted": len(data)
    }


def main():
    output_file = sys.argv[1] if len(sys.argv) > 1 else "data.json"

    print("=" * 60)
    print("KKTC Merkez Bankası Veri Çekme Aracı v2")
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
        print(f"[{key}] Çekiliyor: {url}")

        html, status_code, error_msg = fetch_page(url)

        source_info = {"url": url, "status": "unknown"}

        if html:
            parsed = parse_table_enhanced(html)

            # Ana veri: geriye uyumlu — sadece data satırları
            data[key] = parsed["data"]

            # Header bilgisi kaydet
            data[key + "_headers"] = parsed["headers"]

            # Raw snippet kaydet (debug)
            data[key + "_debug"] = {
                "httpStatus": status_code,
                "headers": parsed["headers"],
                "totalRowsInTable": parsed.get("totalRowsInTable", 0),
                "dataRowsExtracted": parsed.get("dataRowsExtracted", 0),
                "rawSnippet": parsed["rawSnippet"][:2000] if parsed["rawSnippet"] else ""
            }

            source_info["status"] = "ok"
            source_info["rows"] = len(parsed["data"])
            source_info["httpStatus"] = status_code
            source_info["headersFound"] = len(parsed["headers"])
            print(f"  ✓ {len(parsed['data'])} satır, {len(parsed['headers'])} header")
            success += 1
        else:
            data[key] = []
            data[key + "_headers"] = []
            data[key + "_debug"] = {
                "httpStatus": None,
                "error": error_msg,
                "rawSnippet": ""
            }
            source_info["status"] = "failed"
            source_info["error"] = error_msg
            print(f"  ✗ Başarısız: {error_msg}")

        data["sources"][key] = source_info
        time.sleep(1.5)  # Sunucuyu yormamak için

    # Dosyaya yaz
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(output_file) / 1024
    print()
    print("=" * 60)
    print(f"Sonuç: {success}/{total} kaynak başarılı")
    print(f"Dosya: {output_file} ({size_kb:.1f} KB)")

    # Özet
    for key in URLS:
        rows = len(data.get(key, []))
        hdrs = len(data.get(key + "_headers", []))
        print(f"  {key}: {rows} satır, {hdrs} header")

    print("=" * 60)


if __name__ == "__main__":
    main()
