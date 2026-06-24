import requests
from bs4 import BeautifulSoup
import json
import urllib3
from datetime import datetime

# SSL uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Tüm kaynak URL'ler
URLS = {
    "tlRaw": 'https://mb.gov.ct.tr/tr/dibs-ihaleleri',
    "fxRaw": 'https://mb.gov.ct.tr/tr/node/4717',
    "tlStockRaw": 'https://mb.gov.ct.tr/tr/dibs-stoku',
    "usdStockRaw": 'https://mb.gov.ct.tr/tr/node/4718',
    "eurStockRaw": 'https://mb.gov.ct.tr/tr/node/4779',
    "gbpStockRaw": 'https://mb.gov.ct.tr/tr/node/5694'
}

def parse_table(html):
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables: return []
    
    # En çok veri satırı olan tabloyu bul
    best_table = None
    max_rows = 0
    for table in tables:
        rows = table.find_all('tr')
        # Sütun sayısı en az 4 olan (Stok tabloları için toleranslı) satırları say
        data_rows = sum(1 for r in rows if len(r.find_all('td')) >= 4)
        if data_rows > max_rows:
            max_rows = data_rows
            best_table = table
            
    if not best_table: return []
    
    result = []
    for row in best_table.find_all('tr'):
        tds = row.find_all('td')
        if len(tds) < 4: continue
        # Hücre içeriklerini temizle
        cells = [td.get_text(strip=True) for td in tds]
        result.append(cells)
    return result

def main():
    print("KKTC Merkez Bankası'ndan ihale ve STOK verileri çekiliyor...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Tüm linkleri sırayla dön ve verileri çek
    for key, url in URLS.items():
        try:
            req = requests.get(url, headers=headers, verify=False, timeout=15)
            parsed_data = parse_table(req.text)
            data[key] = parsed_data
            print(f"[{key}] başarıyla çekildi -> {len(parsed_data)} satır")
        except Exception as e:
            print(f"[HATA] {key} çekilemedi: {e}")
            data[key] = []
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("Tüm veriler data.json dosyasına başarıyla kaydedildi.")

if __name__ == "__main__":
    main()
