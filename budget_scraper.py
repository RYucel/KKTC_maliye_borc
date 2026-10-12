"""
KKTC Maliye Bakanlığı Genel Gelir-Gider Raporu Çekme ve Ayrıştırma Aracı
Maliye Bakanlığı web sitesinden aylık PDF bütçe raporlarını otomatik bulur, indirir ve JSON formatına dönüştürür.
"""

import os
import re
import sys
import json
import time
from datetime import datetime
import urllib3
import requests
from bs4 import BeautifulSoup
import pdfplumber

sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
}

BASE_URL = "https://maliye.gov.ct.tr"
REPORTS_PAGE = "https://maliye.gov.ct.tr/tr/raporlar/"

MONTH_NAMES_TR = [
    "OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN",
    "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"
]

def clean_doubled(w: str) -> str:
    """PDF render hatası sonucu oluşan çift karakterleri (örn: '99,,55' -> '9,5') temizler."""
    if len(w) >= 2 and len(w) % 2 == 0 and all(w[i] == w[i+1] for i in range(0, len(w), 2)):
        return w[::2]
    return w

def clean_cell_text(text: str) -> str:
    """Hücre metnini normalize eder ve çift karakterleri düzeltir."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', str(text)).strip()
    words = text.split(' ')
    return ' '.join(clean_doubled(w) for w in words)

def parse_num(val) -> float:
    """Metin halindeki para tutarını sayıya dönüştürür ('12,595,174,770' -> 12595174770.0)."""
    if val is None:
        return 0.0
    s = clean_cell_text(str(val)).replace(" ", "").replace("\xa0", "")
    if not s or s == "-" or s == "--":
        return 0.0
    # Negatif işaret kontrolü
    is_neg = False
    if s.startswith("-"):
        is_neg = True
        s = s.lstrip("-")
    elif s.endswith("-"):
        is_neg = True
        s = s.rstrip("-")
    
    # Virgül ve nokta ayrıştırma
    # Örn: 12,595,174,770 veya 46.52 (yüzde)
    try:
        if "," in s and "." in s:
            # 12,595.50 gibi
            s = s.replace(",", "")
            res = float(s)
        elif "," in s:
            # Sadece virgül binlik ayracı: 12,595,174,770
            s = s.replace(",", "")
            res = float(s)
        else:
            res = float(s)
        return -res if is_neg else res
    except ValueError:
        return 0.0

def find_latest_report_pdf():
    """Maliye Bakanlığı web sitesini tarayarak en güncel genel gelir-gider PDF linkini ve adını bulur."""
    print("Maliye Bakanlığı web sitesi taranıyor...")
    pdf_candidates = []
    
    # 1. /tr/raporlar/ sayfasını tara
    try:
        r = requests.get(REPORTS_PAGE, headers=HEADERS, verify=False, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                txt = a.get_text(strip=True)
                if "gelir-gider" in href.lower() or "gelir-gider" in txt.lower():
                    # Link detay sayfasına gidiyorsa
                    full_link = href if href.startswith("http") else f"{BASE_URL}{href}"
                    # Eğer doğrudan PDF ise
                    if href.lower().endswith(".pdf"):
                        pdf_candidates.append((txt or "Rapor", full_link))
                    else:
                        # Rapor detay sayfasını çek ve içindeki PDF'i bul
                        try:
                            r_sub = requests.get(full_link, headers=HEADERS, verify=False, timeout=10)
                            if r_sub.status_code == 200:
                                sub_soup = BeautifulSoup(r_sub.text, "html.parser")
                                for sub_a in sub_soup.find_all("a", href=True):
                                    sub_href = sub_a.get("href")
                                    if sub_href.lower().endswith(".pdf") and "gelir-gider" in sub_href.lower():
                                        pdf_link = sub_href if sub_href.startswith("http") else f"{BASE_URL}{sub_href}"
                                        pdf_candidates.append((txt or "Rapor", pdf_link))
                                        break
                        except Exception:
                            pass
    except Exception as e:
        print(f"Web tarama uyarısı: {e}")

    # 2. Eğer candidates bulunamadıysa doğrudan ay şablonunu test et (2026-12'den geriye doğru)
    current_year = datetime.now().year
    years_to_check = [current_year, current_year - 1]
    
    for yr in years_to_check:
        for mo in range(12, 0, -1):
            test_url = f"{BASE_URL}/downloads/raporlar/genel-gelir-gider/{yr}-{mo:02d}-genel-gelir-gider-raporu.pdf"
            try:
                head_resp = requests.head(test_url, headers=HEADERS, verify=False, timeout=4)
                if head_resp.status_code == 200:
                    title = f"{yr} {MONTH_NAMES_TR[mo-1].title()} Genel Gelir Gider Raporu"
                    pdf_candidates.append((title, test_url))
                    break # Bulunan en yüksek ayı al
            except Exception:
                continue
        if pdf_candidates:
            break

    if pdf_candidates:
        # En güncel olanı (ilk bulunanı) dön
        print(f"En güncel rapor tespit edildi: {pdf_candidates[0][0]} ({pdf_candidates[0][1]})")
        return pdf_candidates[0][0], pdf_candidates[0][1]
    
    return None, None

def download_pdf(url: str, target_filename: str) -> bool:
    """PDF dosyasını indirir."""
    print(f"İndiriliyor: {url} -> {target_filename}")
    try:
        r = requests.get(url, headers=HEADERS, verify=False, timeout=30)
        if r.status_code == 200:
            with open(target_filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"İndirme hatası: {e}")
    return False

def parse_budget_pdf(pdf_path: str, title: str = "", source_url: str = "") -> dict:
    """
    pdfplumber kullanarak 4 sayfalık bütçe raporunu ayrıştırır ve yapılandırılmış JSON nesnesi döner.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF bulunamadı: {pdf_path}")

    print(f"Ayrıştırılıyor: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        if num_pages < 4:
            raise ValueError(f"Beklenen sayfa sayısı en az 4, bulunan: {num_pages}")

        # Başlık ve yıl/ay tespiti
        # 1. sayfadaki başlık metnini al
        p1_text = pdf.pages[0].extract_text() or ""
        year_match = re.search(r'(20\d\d)\s+BÜTÇESİ', p1_text, re.IGNORECASE)
        budget_year = int(year_match.group(1)) if year_match else 2026

        # Tabloları çıkart
        p1_tables = pdf.pages[0].extract_tables()
        p2_tables = pdf.pages[1].extract_tables()
        p3_tables = pdf.pages[2].extract_tables()
        p4_tables = pdf.pages[3].extract_tables()

        # Sayfa 4: Özet Denge Tablosu
        summary_table = None
        for t in p4_tables:
            for r in t:
                cleaned_name = clean_cell_text(r[0] if r else "").upper()
                if "GENEL GİDERLER" in cleaned_name or "GİDERLER / GELİRLER" in cleaned_name:
                    summary_table = t
                    break
            if summary_table:
                break

        # Aylar ve son aktif rapor ayı tespiti
        # Header sütunlarından ayları ve aktif ay sayısını çıkar
        header_row = summary_table[0] if summary_table else p1_tables[0][0]
        cleaned_headers = [clean_cell_text(c) for c in header_row]

        # Aktif aylar tespiti: Sütun 5'ten itibaren kontrol et.
        # Eğer başlıkta önceki yıl (örn. '2025') geçiyorsa veya boşsa, aktif aylar bitmiştir.
        active_months_count = 0
        prev_yr_str = str(budget_year - 1)
        for col_idx in range(5, 17):
            if col_idx < len(cleaned_headers):
                hdr = cleaned_headers[col_idx]
                # Eğer header önceki yılı içeriyorsa (örn: '2025 AĞUSTOS'), bu sonraki aya ait referanstır
                if prev_yr_str in hdr or not hdr:
                    break
                active_months_count += 1
            else:
                break
        
        if active_months_count == 0:
            active_months_count = 7  # Fallback

        active_month_names = MONTH_NAMES_TR[:active_months_count]
        report_period_str = f"{budget_year} {MONTH_NAMES_TR[active_months_count-1].title()}" if active_months_count > 0 else f"{budget_year}"

        def parse_row(row):
            if not row or len(row) < 19:
                return None
            name = clean_cell_text(row[0])
            if not name:
                return None
            
            b_prev = parse_num(row[1])
            act_prev_full = parse_num(row[2])
            b_curr = parse_num(row[3])
            b_curr_rev = parse_num(row[4])
            
            monthly = [parse_num(row[i]) for i in range(5, 17)]
            
            act_prev_ytd = parse_num(row[17]) if len(row) > 17 else 0.0
            act_curr_ytd = parse_num(row[18]) if len(row) > 18 else 0.0
            rate_prev = parse_num(row[19]) if len(row) > 19 else 0.0
            rate_curr = parse_num(row[20]) if len(row) > 20 else 0.0

            return {
                "name": name,
                "budget_prev": b_prev,
                "actual_prev_full": act_prev_full,
                "budget_curr": b_curr,
                "budget_curr_revised": b_curr_rev,
                "monthly": monthly,
                "actual_prev_ytd": act_prev_ytd,
                "actual_curr_ytd": act_curr_ytd,
                "rate_prev": rate_prev,
                "rate_curr": rate_curr
            }

        p4_rows = {}
        for t in p4_tables:
            for r in t:
                p_r = parse_row(r)
                if p_r:
                    key = p_r["name"].strip()
                    p4_rows[key] = p_r

        # Genel Giderler & Genel Gelirler & Açık
        genel_gider = p4_rows.get("GENEL GİDERLER")
        genel_gelir = p4_rows.get("GENEL GELİRLER")
        
        # Açık satırını bul (AÇIK genellikle summary tablosunda)
        acik_row = None
        for k, v in p4_rows.items():
            if k == "AÇIK" and acik_row is None:
                acik_row = v
                break

        # Yerel Giderler, Yerel Gelirler, Yerel Açık
        yerel_gider = p4_rows.get("YEREL GİDERLER")
        yerel_gelir = p4_rows.get("YEREL GELİRLER")
        
        yerel_acik_row = None
        # Sayfa 4 tablo 4'teki AÇIK satırı yerel açıktır
        if len(p4_tables) >= 4:
            for r in p4_tables[3]:
                pr = parse_row(r)
                if pr and pr["name"] == "AÇIK":
                    yerel_acik_row = pr
                    break

        # Avans ve Avans Dahil Açık
        avans_val = 0.0
        avans_dahil_acik = 0.0
        for t in p4_tables:
            for r in t:
                if len(r) > 18:
                    row_name = clean_cell_text(r[0]).upper()
                    if "AVANS DAHİL AÇIK" in row_name:
                        avans_dahil_acik = parse_num(r[18])
                    elif "AVANS" in row_name and "AÇIK" not in row_name:
                        avans_val = parse_num(r[18])

        # Aylık seri oluştur (Ocak'tan aktif aya kadar)
        monthly_series = []
        for i in range(active_months_count):
            m_name = MONTH_NAMES_TR[i].title()
            gider_val = genel_gider["monthly"][i] if genel_gider else 0.0
            gelir_val = genel_gelir["monthly"][i] if genel_gelir else 0.0
            # Bütçe dengesi: Gelir - Gider
            denge_val = gelir_val - gider_val
            
            y_gider_val = yerel_gider["monthly"][i] if yerel_gider else 0.0
            y_gelir_val = yerel_gelir["monthly"][i] if yerel_gelir else 0.0
            y_denge_val = y_gelir_val - y_gider_val
            
            monthly_series.append({
                "month_index": i + 1,
                "month_name": m_name,
                "expense": gider_val,
                "revenue": gelir_val,
                "balance": denge_val,
                "local_expense": y_gider_val,
                "local_revenue": y_gelir_val,
                "local_balance": y_denge_val
            })

        # Gider ve Gelir Kalemlerini parse et
        # Sayfa 1 ve 2: Gider Kalemleri
        expense_items = []
        for page_tables in [p1_tables, p2_tables]:
            for t in page_tables:
                for r in t:
                    pr = parse_row(r)
                    if pr and pr["name"] not in ["GİDERİN NEVİ", "GELİRİN NEVİ", "GİDERLER / GELİRLER"]:
                        expense_items.append(pr)

        # Sayfa 2 ve 3: Gelir Kalemleri
        revenue_items = []
        for page_tables in [p2_tables, p3_tables]:
            for t in page_tables:
                for r in t:
                    pr = parse_row(r)
                    if pr and pr["name"] not in ["GİDERİN NEVİ", "GELİRİN NEVİ", "GİDERLER / GELİRLER"]:
                        # Gelir tablosu başlangıcı 'GELİRLER GENEL TOPLAMI' veya 'VERGİ GELİRLERİ'
                        revenue_items.append(pr)

        # Temizle ve tekrar edenleri filtrele
        # Giderler:
        filtered_expenses = []
        seen_exp = set()
        for it in expense_items:
            # Gelirler listesine sızanları filtrele
            if "GELİRLER" in it["name"].upper() or "VERGİ" in it["name"].upper():
                continue
            if it["name"] not in seen_exp:
                seen_exp.add(it["name"])
                filtered_expenses.append(it)

        # Gelirler:
        filtered_revenues = []
        seen_rev = set()
        for it in revenue_items:
            if "GİDER" in it["name"].upper() or "PERSONEL" in it["name"].upper() or "MAAŞ" in it["name"].upper():
                continue
            if it["name"] not in seen_rev:
                seen_rev.add(it["name"])
                filtered_revenues.append(it)

        # Özet KPI'lar
        kpis = {
            "total_revenue": genel_gelir["actual_curr_ytd"] if genel_gelir else 0.0,
            "total_revenue_budget": genel_gelir["budget_curr_revised"] if genel_gelir else 0.0,
            "total_revenue_rate": genel_gelir["rate_curr"] if genel_gelir else 0.0,
            
            "total_expense": genel_gider["actual_curr_ytd"] if genel_gider else 0.0,
            "total_expense_budget": genel_gider["budget_curr_revised"] if genel_gider else 0.0,
            "total_expense_rate": genel_gider["rate_curr"] if genel_gider else 0.0,
            
            "budget_balance": (genel_gelir["actual_curr_ytd"] - genel_gider["actual_curr_ytd"]) if (genel_gelir and genel_gider) else 0.0,
            "advance_amount": avans_val,
            "balance_with_advance": avans_dahil_acik if avans_dahil_acik != 0.0 else ((genel_gelir["actual_curr_ytd"] - genel_gider["actual_curr_ytd"]) - avans_val if genel_gelir and genel_gider else 0.0),
            
            "local_revenue": yerel_gelir["actual_curr_ytd"] if yerel_gelir else 0.0,
            "local_expense": yerel_gider["actual_curr_ytd"] if yerel_gider else 0.0,
            "local_balance": (yerel_gelir["actual_curr_ytd"] - yerel_gider["actual_curr_ytd"]) if (yerel_gelir and yerel_gider) else 0.0,
            
            "prev_year_revenue_ytd": genel_gelir["actual_prev_ytd"] if genel_gelir else 0.0,
            "prev_year_expense_ytd": genel_gider["actual_prev_ytd"] if genel_gider else 0.0,
            "prev_year_balance_ytd": (genel_gelir["actual_prev_ytd"] - genel_gider["actual_prev_ytd"]) if (genel_gelir and genel_gider) else 0.0,
        }

        # Ana Gelir Dağılım Grupları
        rev_breakdown = []
        for r_item in filtered_revenues:
            n = r_item["name"].strip()
            if n in [
                "VERGİ GELİRLERİ", "Gelir Vergisi", "Kurumlar Vergisi", "Dahilde Alınan Katma Değer Vergisi",
                "İthalattan Alınan Katma Değer Vergisi", "Gümrük Vergileri", "Harçlar", "FON GELİRLERİ",
                "TC YARDIMLARI", "TC KREDİLERİ", "VERGİ DIŞI MAHALLİ GELİRLER", "SERMAYE GELİRLERİ"
            ]:
                rev_breakdown.append({
                    "name": n,
                    "amount": r_item["actual_curr_ytd"],
                    "budget": r_item["budget_curr_revised"] or r_item["budget_curr"],
                    "rate": r_item["rate_curr"]
                })

        # Ana Gider Dağılım Grupları
        exp_breakdown = []
        for e_item in filtered_expenses:
            n = e_item["name"].strip()
            if n in [
                "PERSONEL GİDERLERİ", "MAAŞ/ÜCRET", "EKMESİ", "SOSYAL GÜVENLİK",
                "(D) Hane Halkına Transferler", "Emekli Maaşları", "MAHALLİ YATIRIM",
                "TC YARDIM VE KREDİLERİ TOPLAMI", "SAVUNMA (CARİ YIL)", "TC YATIRIM (CARİ YIL)",
                "FİYAT İSTİKRAR FONU GİDERLERİ"
            ]:
                exp_breakdown.append({
                    "name": n,
                    "amount": e_item["actual_curr_ytd"],
                    "budget": e_item["budget_curr_revised"] or e_item["budget_curr"],
                    "rate": e_item["rate_curr"]
                })

        return {
            "metadata": {
                "budget_year": budget_year,
                "report_period": report_period_str,
                "active_months_count": active_months_count,
                "active_month_names": active_month_names,
                "title": title or f"{budget_year} Genel Gelir-Gider Raporu",
                "source_url": source_url,
                "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "kpis": kpis,
            "monthly_series": monthly_series,
            "revenue_breakdown": rev_breakdown,
            "expense_breakdown": exp_breakdown,
            "all_revenues": filtered_revenues,
            "all_expenses": filtered_expenses,
            "summary_rows": {
                "genel_gider": genel_gider,
                "genel_gelir": genel_gelir,
                "acik": acik_row,
                "yerel_gider": yerel_gider,
                "yerel_gelir": yerel_gelir,
                "yerel_acik": yerel_acik_row
            }
        }

def main():
    target_json = "budget_data.json"
    pdf_path = "latest_budget_report.pdf"

    print("=" * 60)
    print("KKTC Maliye Bakanlığı Gelir-Gider Raporu Çekme & Ayrıştırma")
    print("=" * 60)

    # 1. En güncel raporu bul veya var olan test dosyasını kullan
    title, url = find_latest_report_pdf()
    if url:
        print(f"Rapor URL: {url}")
        if not download_pdf(url, pdf_path):
            print("İndirme başarısız, yerel test PDF'e geçiliyor...")
            pdf_path = "test_2026_07.pdf"
            title = "2026 Temmuz Genel Gelir Gider Raporu"
            url = "https://maliye.gov.ct.tr/downloads/raporlar/genel-gelir-gider/2026-07-genel-gelir-gider-raporu.pdf"
    else:
        print("Web'de rapor bulunamadı, yerel test PDF'e geçiliyor...")
        pdf_path = "test_2026_07.pdf"
        title = "2026 Temmuz Genel Gelir Gider Raporu"
        url = "https://maliye.gov.ct.tr/downloads/raporlar/genel-gelir-gider/2026-07-genel-gelir-gider-raporu.pdf"

    # 2. PDF'i ayrıştır
    parsed_data = parse_budget_pdf(pdf_path, title=title, source_url=url)

    # 3. budget_data.json dosyasına yaz
    with open(target_json, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, ensure_ascii=False, indent=2)

    # 4. Ayrıca data.json içine de "budget" anahtarı olarak göm (frontend tek dosyadan da okuyabilmeli!)
    data_json_path = "data.json"
    if os.path.exists(data_json_path):
        try:
            with open(data_json_path, "r", encoding="utf-8") as f:
                data_json = json.load(f)
            data_json["budget"] = parsed_data
            data_json["budget_last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(data_json_path, "w", encoding="utf-8") as f:
                json.dump(data_json, f, ensure_ascii=False, indent=2)
            print("✓ data.json dosyasına 'budget' anahtarı eklendi.")
        except Exception as e:
            print(f"data.json güncelleme uyarısı: {e}")

    k = parsed_data["kpis"]
    print("\n" + "=" * 60)
    print(f"BAŞARIYLA TAMAMLANDI: {parsed_data['metadata']['report_period']}")
    print(f"Toplam Gelir:        {k['total_revenue']:,.0f} TL (%{k['total_revenue_rate']:.1f})")
    print(f"Toplam Gider:        {k['total_expense']:,.0f} TL (%{k['total_expense_rate']:.1f})")
    print(f"Bütçe Dengesi:       {k['budget_balance']:,.0f} TL")
    print(f"Avans Dahil Açık:    {k['balance_with_advance']:,.0f} TL")
    print(f"Yerel Bütçe Dengesi: {k['local_balance']:,.0f} TL")
    print(f"Aktif Aylar:         {len(parsed_data['monthly_series'])} ay")
    print("=" * 60)

if __name__ == "__main__":
    main()
