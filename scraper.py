import requests
from bs4 import BeautifulSoup
import json
import urllib3
from datetime import datetime

# SSL uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TL_URL = 'https://mb.gov.ct.tr/tr/dibs-ihaleleri'
FX_URL = 'https://mb.gov.ct.tr/tr/node/4717'

def parse_table(html):
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables: return []
    
    # En çok veri satırı olan tabloyu bul
    best_table = None
    max_rows = 0
    for table in tables:
        rows = table.find_all('tr')
        data_rows = sum(1 for r in rows if len(r.find_all('td')) >= 5)
        if data_rows > max_rows:
            max_rows = data_rows
            best_table = table
            
    if not best_table: return []
    
    result = []
    for row in best_table.find_all('tr'):
        tds = row.find_all('td')
        if len(tds) < 5: continue
        # Hücre içeriklerini temizle
        cells = [td.get_text(strip=True) for td in tds]
        result.append(cells)
    return result

def main():
    print("KKTC Merkez Bankası verileri çekiliyor...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    tl_req = requests.get(TL_URL, headers=headers, verify=False, timeout=15)
    fx_req = requests.get(FX_URL, headers=headers, verify=False, timeout=15)
    
    tl_raw = parse_table(tl_req.text)
    fx_raw = parse_table(fx_req.text)
    
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tlRaw": tl_raw,
        "fxRaw": fx_raw
    }
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Başarılı! TL: {len(tl_raw)} satır, FX: {len(fx_raw)} satır kaydedildi.")

if __name__ == "__main__":
    main()
