"""
OG önizleme görseli üretici — og.png (1200x630)

data.json'dan güncel DİBS stokunu, son 24 ayın toplam stok eğrisini,
önümüzdeki 30 günün itfasını ve son TL ihale faizini çizer. Ardından
index.html'deki og:image / og:description etiketlerini günceller
(sürüm parametresi veriden türetilir; veri değişmezse dosyalar da değişmez).

Kullanım: python og.py [data.json] [og.png] [index.html]
"""

import hashlib
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "fonts"
SITE = "ryucel.github.io/KKTC_maliye_borc"
W, H, SS = 1200, 630, 2  # SS: süpersampling (kenar yumuşatma için 2x çizip küçült)

C = {  # sitenin renk paleti
    "bg": "#0a0f1a", "bg2": "#111827", "card": "#1a2235", "bdr": "#2a3654",
    "fg": "#e8edf5", "muted": "#8899b8", "accent": "#e63946", "accent2": "#f4a261",
    "TL": "#e63946", "USD": "#2ec4b6", "EUR": "#a78bfa", "GBP": "#38bdf8",
}
TR_AY = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
         "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
         "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12}
AY_KISA = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
FX_CODE = {"ABD DOLARI": "USD", "AVRO": "EUR", "İNGİLİZ STERLİNİ": "GBP"}


# ---------------------------------------------------------------- veri
def num(s):
    s = str(s).strip()
    if s in ("", "-", "—", "–"):
        return None
    s = re.sub(r"[^\d.,-]", "", s)
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        p = s.split(",")
        s = s.replace(",", "") if len(p) > 2 or len(p[-1]) == 3 else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def pdate(s):
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", str(s))
    if not m:
        return None
    y = int(m.group(3))
    return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))


def auctions(d):
    """TL ve döviz ihalelerini ortak bono kayıtlarına çevirir."""
    out = []
    for r in d.get("tlRaw", []):
        if len(r) < 10 or not re.match(r"^[A-Z]{3}\d", str(r[0])):
            continue
        i = 5 if str(r[4]).strip().lower() == "gün" else 4
        v, it, kabul = pdate(r[1]), pdate(r[2]), num(r[i + 1])
        if v and it and kabul:
            out.append(dict(cur="TL", v=v, i=it, nom=kabul, fx=1.0, ort=num(r[i + 4]), bil=num(r[i + 5])))
    for r in d.get("fxRaw", []):
        if len(r) < 12 or not re.match(r"^[A-Z]{3}\d", str(r[0])):
            continue
        cur = FX_CODE.get(str(r[1]).strip())
        if not cur:
            continue
        i = 6 if str(r[5]).strip().lower() == "gün" else 5
        v, it, kabul, tlk = pdate(r[2]), pdate(r[3]), num(r[i + 1]), num(r[i + 2])
        if v and it and kabul:
            out.append(dict(cur=cur, v=v, i=it, nom=kabul, fx=(tlk / kabul) if tlk else None,
                            ort=num(r[i + 5]), bil=num(r[i + 6])))
    out.sort(key=lambda b: b["v"])
    return out


def stock_series(rows):
    """MB aylık stok tablosu → {(yıl, ay): ay sonu stok}"""
    res, year = {}, None
    for r in rows:
        cells = [str(c).strip() for c in r]
        if cells and re.fullmatch(r"\d{4}", cells[0]):
            year, cells = int(cells[0]), cells[1:]
        if len(cells) < 4 or not year:
            continue
        mi = TR_AY.get(cells[0].lower())
        val = num(cells[3])
        if val is None and cells[3] in ("", "-", "—", "–"):
            val = 0.0  # MB tablosunda "-" = sıfır stok (veri yok değil)
        if mi and val is not None:
            res[(year, mi)] = val
    return res


def implied_fx(bills, cur, d):
    """Bir tarihteki örtük kur: o tarihe kadarki son döviz ihalesinin TL karşılığı / nominal."""
    rate = None
    for b in bills:
        if b["cur"] == cur and b["fx"]:
            if b["v"] <= d:
                rate = b["fx"]
            elif rate is None:
                return b["fx"]
    return rate


def metrics(d, today):
    bills = auctions(d)
    stk = {c: stock_series(d.get(k, [])) for c, k in
           (("TL", "tlStockRaw"), ("USD", "usdStockRaw"), ("EUR", "eurStockRaw"), ("GBP", "gbpStockRaw"))}
    rate = {c: implied_fx(bills, c, today) or 0 for c in ("USD", "EUR", "GBP")}
    rate["TL"] = 1.0

    latest = {c: (s[max(s)] if s else 0.0) for c, s in stk.items()}
    last_key = max(stk["TL"]) if stk["TL"] else None
    total = sum(latest[c] * rate[c] for c in latest)

    # Son 24 ay toplam stok (her ay o ayın örtük kuruyla)
    keys = sorted({k for s in stk.values() for k in s})[-24:]
    hist, carry = [], {c: 0.0 for c in stk}
    for k in sorted({k for s in stk.values() for k in s}):
        for c in stk:
            if k in stk[c]:
                carry[c] = stk[c][k]
        if k in keys:
            me = date(k[0] + (k[1] == 12), k[1] % 12 + 1, 1) - timedelta(days=1)
            hist.append((k, sum(carry[c] * (1 if c == "TL" else (implied_fx(bills, c, me) or rate[c])) for c in carry)))

    in30 = sum(b["nom"] * rate[b["cur"]] for b in bills if today <= b["i"] <= today + timedelta(days=30))
    tl = [b for b in bills if b["cur"] == "TL"]
    last_tl = tl[-1] if tl else None
    return dict(total=total, latest=latest, rate=rate, hist=hist, in30=in30, last_tl=last_tl,
                last_key=last_key, fx_share=(total - latest["TL"]) / total * 100 if total else 0)


# ---------------------------------------------------------------- çizim
def font(name, size, weight):
    f = ImageFont.truetype(str(FONTS / name), size * SS)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def tr_num(v, d=2):
    q = Decimal(str(v)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)  # 86,25 → 86,3 (sayfayla aynı)
    s = f"{q:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def hex2rgb(h, a=255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def draw_og(m, out_path, stamp):
    S = lambda v: int(v * SS)
    img = Image.new("RGBA", (S(W), S(H)), hex2rgb(C["bg"]))

    # Arka plan parıltıları (sitedeki yumuşak radyal gradyanlar)
    glow = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-90, -110, 150, 110], fill=hex2rgb(C["accent"], 34))
    gd.ellipse([W // 4 - 120, H // 4 - 70, W // 4 + 90, H // 4 + 110], fill=hex2rgb(C["USD"], 26))
    glow = glow.filter(ImageFilter.GaussianBlur(28)).resize(img.size, Image.BICUBIC)
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)

    PX = 64  # yatay kenar boşluğu
    # Üst şerit
    d.rectangle([0, 0, S(W), S(6)], fill=hex2rgb(C["accent"]))
    d.text((S(PX), S(42)), "KKTC MERKEZİ HÜKÜMET · DİBS BORÇ PANOSU", font=font("SourceSans3.ttf", 17, 600),
           fill=hex2rgb(C["accent2"]))
    d.text((S(PX), S(70)), "Borç İlerlemesi", font=font("PlayfairDisplay.ttf", 54, 900), fill=hex2rgb(C["fg"]))

    # Büyük rakam
    d.text((S(PX), S(170)), "Toplam DİBS stoku (TL karşılığı)", font=font("SourceSans3.ttf", 22, 400),
           fill=hex2rgb(C["muted"]))
    big = tr_num(m["total"] / 1e9)
    fb = font("PlayfairDisplay.ttf", 104, 900)
    d.text((S(PX - 4), S(196)), big, font=fb, fill=hex2rgb(C["fg"]))
    bw = d.textlength(big, font=fb) / SS
    d.text((S(PX + bw + 14), S(262)), "Mrd TL", font=font("SourceSans3.ttf", 34, 600), fill=hex2rgb(C["accent2"]))

    # Para cinsi çipleri
    chips = [("TL", f"{tr_num(m['latest']['TL'] / 1e9)} Mrd"), ("USD", f"{tr_num(m['latest']['USD'] / 1e6, 1)} M"),
             ("EUR", f"{tr_num(m['latest']['EUR'] / 1e6, 1)} M"), ("GBP", f"{tr_num(m['latest']['GBP'] / 1e6, 1)} M")]
    x, y = PX, 356
    fc, fv = font("SourceSans3.ttf", 17, 700), font("SourceSans3.ttf", 22, 600)
    for cur, val in chips:
        w = 30 + (d.textlength(cur, font=fc) + d.textlength(val, font=fv)) / SS + 18
        d.rounded_rectangle([S(x), S(y), S(x + w), S(y + 44)], radius=S(10), fill=hex2rgb(C["card"]),
                            outline=hex2rgb(C["bdr"]), width=S(1.5))
        d.ellipse([S(x + 14), S(y + 17), S(x + 24), S(y + 27)], fill=hex2rgb(C[cur]))
        d.text((S(x + 32), S(y + 12)), cur, font=fc, fill=hex2rgb(C[cur]))
        d.text((S(x + 32 + d.textlength(cur, font=fc) / SS + 8), S(y + 8)), val, font=fv, fill=hex2rgb(C["fg"]))
        x += w + 10

    # Alt bilgi satırı (3 gösterge)
    stats = [("Önümüzdeki 30 gün itfa", f"{tr_num(m['in30'] / 1e9)} Mrd TL"),
             ("Son TL ihalesi (bileşik)", f"%{tr_num(m['last_tl']['bil'] or m['last_tl']['ort'] or 0)}" if m["last_tl"] else "—"),
             ("Döviz payı", f"%{tr_num(m['fx_share'], 1)}")]
    x, y = PX, 448
    fl, fs = font("SourceSans3.ttf", 17, 400), font("SourceSans3.ttf", 30, 700)
    for i, (lbl, val) in enumerate(stats):
        if i:
            d.line([S(x - 22), S(y + 4), S(x - 22), S(y + 58)], fill=hex2rgb(C["bdr"]), width=S(1.5))
        d.text((S(x), S(y)), lbl, font=fl, fill=hex2rgb(C["muted"]))
        d.text((S(x), S(y + 22)), val, font=fs, fill=hex2rgb(C["fg"]))
        x += max(d.textlength(lbl, font=fl), d.textlength(val, font=fs)) / SS + 46

    # Sağ panel: son 24 ay toplam stok eğrisi
    hist = [(k, v / 1e9) for k, v in m["hist"] if v > 0]
    gx0, gy0, gx1, gy1 = 760, 150, W - PX, 420
    d.rounded_rectangle([S(gx0 - 26), S(gy0 - 46), S(gx1 + 26), S(gy1 + 54)], radius=S(16),
                        fill=hex2rgb(C["card"], 235), outline=hex2rgb(C["bdr"]), width=S(1.5))
    d.text((S(gx0 - 4), S(gy0 - 32)), "Toplam stok · son 24 ay (Mrd TL)", font=font("SourceSans3.ttf", 16, 600),
           fill=hex2rgb(C["muted"]))
    if len(hist) >= 2:
        vmax = max(v for _, v in hist) * 1.08
        pts = [(gx0 + (gx1 - gx0) * i / (len(hist) - 1), gy1 - (gy1 - gy0) * v / vmax) for i, (_, v) in enumerate(hist)]
        area = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ad = ImageDraw.Draw(area)
        ad.polygon([(S(px), S(py)) for px, py in pts] + [(S(gx1), S(gy1)), (S(gx0), S(gy1))],
                   fill=hex2rgb(C["accent2"], 46))
        img = Image.alpha_composite(img, area)
        d = ImageDraw.Draw(img)
        d.line([S(gx0), S(gy1), S(gx1), S(gy1)], fill=hex2rgb(C["bdr"]), width=S(1.5))
        d.line([(S(px), S(py)) for px, py in pts], fill=hex2rgb(C["accent2"]), width=S(4), joint="curve")
        lx, ly = pts[-1]
        d.ellipse([S(lx - 7), S(ly - 7), S(lx + 7), S(ly + 7)], fill=hex2rgb(C["accent2"]), outline=hex2rgb(C["bg"]),
                  width=S(2.5))
        fa = font("SourceSans3.ttf", 15, 400)
        (k0, _), (k1, _) = hist[0], hist[-1]
        d.text((S(gx0), S(gy1 + 10)), f"{AY_KISA[k0[1] - 1]} {k0[0]}", font=fa, fill=hex2rgb(C["muted"]))
        t1 = f"{AY_KISA[k1[1] - 1]} {k1[0]}"
        d.text((S(gx1) - d.textlength(t1, font=fa), S(gy1 + 10)), t1, font=fa, fill=hex2rgb(C["muted"]))
        if hist[0][1] > 0:
            chg = (hist[-1][1] / hist[0][1] - 1) * 100
            tag = f"{'+' if chg >= 0 else '−'}%{tr_num(abs(chg), 0)} · 24 ayda"
            ft = font("SourceSans3.ttf", 16, 700)
            tw = d.textlength(tag, font=ft) / SS
            d.rounded_rectangle([S(gx1 - tw - 18), S(gy0 - 38), S(gx1 + 4), S(gy0 - 12)], radius=S(8),
                                fill=hex2rgb(C["accent"], 50))
            d.text((S(gx1 - tw - 7), S(gy0 - 36)), tag, font=ft, fill=hex2rgb(C["accent2"]))

    # Alt kenar
    d.line([S(PX), S(H - 70), S(W - PX), S(H - 70)], fill=hex2rgb(C["bdr"]), width=S(1.5))
    ff = font("SourceSans3.ttf", 18, 400)
    d.text((S(PX), S(H - 54)), f"Kaynak: KKTC Merkez Bankası · Veri: {stamp}", font=ff, fill=hex2rgb(C["muted"]))
    fu = font("SourceSans3.ttf", 18, 700)
    d.text((S(W - PX) - d.textlength(SITE, font=fu), S(H - 54)), SITE, font=fu, fill=hex2rgb(C["fg"]))

    img.convert("RGB").resize((W, H), Image.LANCZOS).save(out_path, "PNG", optimize=True)


# ---------------------------------------------------------------- HTML meta güncelleme
def update_meta(html_path, m, version):
    p = Path(html_path)
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    desc = (f"Toplam DİBS stoku {tr_num(m['total'] / 1e9)} Mrd TL. Önümüzdeki 30 günde {tr_num(m['in30'] / 1e9)} Mrd TL "
            f"itfa. Ödeme takvimi, risk göstergeleri ve çevirme senaryo simülatörü.")
    new = re.sub(r'(<meta property="og:image" content="[^"?]+)(\?v=[^"]*)?"', rf'\1?v={version}"', s)
    new = re.sub(r'(<meta name="twitter:image" content="[^"?]+)(\?v=[^"]*)?"', rf'\1?v={version}"', new)
    new = re.sub(r'(<meta property="og:description" content=")[^"]*"', lambda mm: mm.group(1) + desc + '"', new)
    new = re.sub(r'(<meta name="twitter:description" content=")[^"]*"', lambda mm: mm.group(1) + desc + '"', new)
    new = re.sub(r'(<meta name="description" content=")[^"]*"', lambda mm: mm.group(1) + desc + '"', new)
    if new != s:
        p.write_text(new, encoding="utf-8")
        return True
    return False


def main():
    data_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "og.png"
    html_path = sys.argv[3] if len(sys.argv) > 3 else "index.html"
    d = json.loads(Path(data_path).read_text(encoding="utf-8"))

    # "Bugün" = verinin çekildiği gün; aynı veri her zaman aynı görseli üretir
    try:
        today = datetime.strptime(str(d.get("last_updated", ""))[:10], "%Y-%m-%d").date()
    except ValueError:
        today = date.today()
    m = metrics(d, today)
    stamp = today.strftime("%d.%m.%Y")
    if m["last_key"]:
        stamp += f" (stok: {AY_KISA[m['last_key'][1] - 1]} {m['last_key'][0]})"

    draw_og(m, out_path, stamp)
    # Sosyal ağlar görseli URL'ye göre önbelleğe alır; sürüm parametresi veri değişince yenilenir
    version = hashlib.sha1(Path(out_path).read_bytes()).hexdigest()[:10]
    changed = update_meta(html_path, m, version)
    print(f"og.png yazıldı ({tr_num(m['total'] / 1e9)} Mrd TL, v={version}); index.html meta "
          f"{'güncellendi' if changed else 'değişmedi'}")


if __name__ == "__main__":
    main()
