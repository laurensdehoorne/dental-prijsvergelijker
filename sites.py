"""Zoeken en prijzen ophalen bij dentale webshops.

Elke site heeft een zoekfunctie en een 'is ingelogd'-check. Sessies (cookies +
localStorage) worden bewaard door login.py in sessions/<site>.json.
"""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

SESSIONS = Path(__file__).parent / "sessions"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


# ---------- sessies ----------

def load_state(site):
    f = SESSIONS / f"{site}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def cookie_header(site, domain_part):
    state = load_state(site) or {}
    cookies = [c for c in state.get("cookies", []) if domain_part in c.get("domain", "")]
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


class AnonSession:
    """Cookiejar voor anonieme bezoeken; bezoekt eerst een startpagina
    (nodig om bv. de Belgische winkel te kiezen)."""

    def __init__(self, warmup_url):
        self.warmup_url = warmup_url
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, url, headers=None):
        if not len(self.jar):
            self.opener.open(urllib.request.Request(self.warmup_url, headers={"User-Agent": UA}),
                             timeout=20).read()
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        with self.opener.open(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")


# ---------- hulpfuncties ----------

def parse_euro(s):
    """'€ 1.234,50' -> 1234.5 ; '5.50' -> 5.5 ; '4.-' -> 4.0"""
    s = html.unescape(s).replace("€", "").replace("\xa0", " ").strip()
    s = s.replace(".-", "").replace(",-", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s.replace(" ", ""))
    return float(m.group(0)) if m else None


UNITS = r"(?:st|stuks|stuk|pcs|ampullen|carpules|tips|vellen|vel|rollen|zakjes|doekjes|spuiten|capsules)"


def pack_size(text):
    """Aantal stuks uit een omschrijving ('2 x 100 st', '50 stuks', '(100)')."""
    t = text.lower()
    if re.search(r"\bper stuk\b", t):
        return 1
    m = re.search(rf"(\d+)\s*x\s*(\d+)\s*{UNITS}\b", t)
    if m:
        return int(m.group(1)) * int(m.group(2))
    m = re.search(rf"(\d+)\s*{UNITS}\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\((\d+)\)\s*$", t)
    if m:
        return int(m.group(1))
    return None


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def item(site, *, code="", name="", pack="", price=None, volume_price=None, old_price=None,
         url="", image="", brand=""):
    price = price or None  # 0,00 = geen echte prijs (bv. niet leverbaar)
    return {
        "site": site, "code": code, "name": name, "pack": pack, "price": price,
        # merk enkel apart bewaren als het niet al in de naam staat (telt mee in de matchscore)
        "brand": brand if brand and brand.lower() not in name.lower() else "",
        # laagste staffelprijs (bij grote aantallen), enkel als lager dan de gewone prijs
        "volume_price": volume_price if volume_price and price and volume_price < price else None,
        "old_price": old_price if old_price and price and old_price > price else None,
        "pieces": pack_size(pack) or pack_size(name), "url": url, "image": image,
    }


# ---------- Ordent-platform (Dentaldiscount, Hofmeester) ----------

class OrdentShop:
    def __init__(self, site, base, lang, home):
        self.site, self.base, self.lang, self.home = site, base, lang, home
        self.domain = urllib.parse.urlparse(base).hostname.replace("www.", "")
        self.anon = AnonSession(base + home)

    def _fetch(self, url):
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": self.base + self.home}
        ck = cookie_header(self.site, self.domain)
        if ck:
            return http_get(url, {**headers, "Cookie": ck})[1]
        return self.anon.get(url, headers)

    def logged_in(self):
        ck = cookie_header(self.site, self.domain)
        if not ck:
            return False
        try:
            _, body = http_get(self.base + self.home, {"Cookie": ck})
        except Exception:
            return False
        return "Uitloggen" in body or "logout" in body

    def search(self, query):
        params = urllib.parse.urlencode({
            "lang": self.lang, "page": 1, "page_mode": "search", "page_data": "",
            "page_query": query, "page_srt": "default", "page_view": "list",
        })
        body = self._fetch(self.base + "ajax/products.php?" + params)
        items = []
        for b in re.split(r'<div class="product-wrap', body)[1:]:
            name = re.search(r'<div class="product-name">\s*<a[^>]*>([\s\S]*?)</a>', b)
            if not name:
                continue
            href = re.search(r'href="((?:nl-[a-z]{2}/)?product/[^"]+)"', b)
            sku = re.search(r'<div class="product-sku">\s*<a[^>]*>([^<]+)</a>', b)
            brand = re.search(r'<div class="product-cat">\s*<a[^>]*>([\s\S]*?)</a>', b)
            img = re.search(r'<img[^>]+src="([^"]+)"', b)
            pb = re.search(r'<div class="product-price">([\s\S]*?)</div>', b)
            prices, old = [], None
            if pb:
                prices = [p for p in (parse_euro(x) for x in re.findall(r'<ins[^>]*>([\s\S]*?)</ins>', pb.group(1))) if p]
                o = re.search(r'<del[^>]*>([\s\S]*?)</del>', pb.group(1))
                old = parse_euro(o.group(1)) if o else None
            full = f"{strip_tags(brand.group(1)) if brand else ''} {strip_tags(name.group(1))}".strip()
            letters = [c for c in full if c.isalpha()]
            if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
                full = full.capitalize()  # Hofmeester: alles in hoofdletters
            items.append(item(
                self.site, code=strip_tags(sku.group(1)) if sku else "", name=full,
                # een vork 'min - max' is een staffel: max = prijs per stuk, min = bij grote aantallen
                price=max(prices) if prices else None, volume_price=min(prices) if prices else None,
                old_price=old, url=self.base + href.group(1) if href else self.base + self.home,
                image=img.group(1) if img else "",
            ))
        return items


dentaldiscount = OrdentShop("dentaldiscount", "https://www.dentaldiscount.com/", "nl-BE", "nl-be/")
hofmeester = OrdentShop("hofmeester", "https://www.hofmeester.nl/", "nl-NL", "")


# ---------- Basiq Dental (SAP Commerce / Spartacus) ----------

BQ_API = "https://prd-api.basiqdental.com/rest/v2/be-bd/"
BQ_SHOP = "https://www.basiqdental.be/nl_BE"


def basiq_token():
    """Spartacus bewaart het OAuth-token in localStorage (sleutel bevat 'auth')."""
    state = load_state("basiq") or {}
    for origin in state.get("origins", []):
        for entry in origin.get("localStorage", []):
            if "auth" not in entry["name"].lower():
                continue
            try:
                token = (json.loads(entry["value"]).get("token") or {}).get("access_token")
            except (ValueError, AttributeError):
                continue
            if token:
                return token
    return None


def basiq_logged_in():
    token = basiq_token()
    if not token:
        return False
    try:
        status, _ = http_get(BQ_API + "users/current?fields=BASIC", {"Authorization": f"Bearer {token}"})
        return status == 200
    except Exception:
        return False


def basiq_search(query):
    fields = ("products(code,name,brand(DEFAULT),packingContents,price(FULL),"
              "regularPrice(FULL),images(DEFAULT),url),pagination(DEFAULT)")
    params = urllib.parse.urlencode({
        "fields": fields, "query": query, "pageSize": 48, "lang": "nl_BE", "curr": "EUR",
    })
    headers = {"Accept": "application/json", "Origin": "https://www.basiqdental.be"}
    token = basiq_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        _, body = http_get(BQ_API + "products/search?" + params, headers)
    except urllib.error.HTTPError as e:
        if e.code != 401 or not token:
            raise
        headers.pop("Authorization")  # token verlopen: publieke prijzen
        _, body = http_get(BQ_API + "products/search?" + params, headers)
    items = []
    for p in json.loads(body).get("products", []):
        name = strip_tags(p.get("name", ""))
        brand = (p.get("brand") or {}).get("name", "")
        img = next((i.get("url") for i in p.get("images", []) if i.get("url")), "")
        if img.startswith("/"):
            img = "https://prd-api.basiqdental.com" + img
        items.append(item(
            "basiq", code=p.get("code", ""),
            name=name if brand.lower() in name.lower() else f"{brand} {name}".strip(),
            pack=p.get("packingContents") or "",
            price=(p.get("price") or {}).get("value"),
            old_price=(p.get("regularPrice") or {}).get("value"),
            url=BQ_SHOP + p.get("url", ""), image=img,
        ))
    return items


# ---------- Dental Addict (PrestaShop 1.6) ----------

DA_BASE = "https://www.dental-addict.be/nl/"
_da_anon = AnonSession(DA_BASE)


def _da_fetch(url):
    ck = cookie_header("dentaladdict", "dental-addict")
    if ck:
        return http_get(url, {"Cookie": ck})[1]
    return _da_anon.get(url)


def dentaladdict_logged_in():
    if not cookie_header("dentaladdict", "dental-addict"):
        return False
    try:
        return "mylogout" in _da_fetch(DA_BASE)
    except Exception:
        return False


def dentaladdict_search(query):
    params = urllib.parse.urlencode({
        "controller": "search", "orderby": "position", "orderway": "desc",
        "search_query": query, "n": 48,
    })
    body = _da_fetch(DA_BASE + "zoeken?" + params)
    items = []
    for b in re.split(r'<li class="ajax_block_product', body)[1:]:
        link = re.search(r'<h3 class="product-name"[^>]*>\s*<a href="([^"]+)"[^>]*>([\s\S]*?)</a>', b)
        if not link:
            continue
        price = re.search(r'<span class="price product-price">([\s\S]*?)</span>\s*(?:<span class="cdc|</div>)', b)
        old = re.search(r'<span class="old-price product-price">([\s\S]*?)</span>', b)
        pid = re.search(r'data-id-product="(\d+)"', b)
        img = re.search(r'data-src="([^"]+)"', b) or re.search(r'<img[^>]+src="([^"]+)"', b)
        items.append(item(
            "dentaladdict", code=pid.group(1) if pid else "",
            name=strip_tags(link.group(2)).title(),
            price=parse_euro(strip_tags(price.group(1)).replace(" ", "")) if price else None,
            old_price=parse_euro(strip_tags(old.group(1))) if old else None,
            url=html.unescape(link.group(1)).split("?")[0], image=img.group(1) if img else "",
        ))
    return items


# ---------- Denta (ASP.NET MVC) ----------

DENTA_BASE = "https://www.denta.be"
_denta_anon = AnonSession(DENTA_BASE + "/")


def _denta_fetch(url):
    ck = cookie_header("denta", "denta.be")
    if ck:
        return http_get(url, {"Cookie": ck})[1]
    return _denta_anon.get(url)


def denta_logged_in():
    if not cookie_header("denta", "denta.be"):
        return False
    try:
        return 'href="/aanmelden/"' not in _denta_fetch(DENTA_BASE + "/")
    except Exception:
        return False


def denta_search(query):
    body = _denta_fetch(DENTA_BASE + "/zoeken/" + urllib.parse.quote(query) + "/")
    items = []
    for b in re.split(r'<div class="single-product-item"', body)[1:]:
        name = re.search(r'<p class="h5 product-name[^"]*">([\s\S]*?)</p>', b)
        if not name:
            continue
        href = re.search(r'<a href="([^"]+)"', b)
        codes = re.findall(r'<p class="short-itemNo">([^<]*)</p>', b)
        pack = re.search(r'<p class="contentValue">([^<]*)</p>', b)
        brand = re.search(r'<span class="size">([\s\S]*?)</span>', b)
        img = re.search(r'<img[^>]+src="([^"]+)"', b)
        # ingelogd: <span class="price-regular"><span class="gtm-price">8,95</span></span>
        #           <span class="price-old">9,94</span>  (zonder €-teken)
        reg = re.search(r'class="price-regular">([\s\S]*?)</span>\s*</span>', b) or \
            re.search(r'class="gtm-price">([^<]*)<', b)
        old_m = re.search(r'class="price-old">([^<]*)<', b)
        price = parse_euro(strip_tags(reg.group(1))) if reg else None
        old = parse_euro(old_m.group(1)) if old_m else None
        items.append(item(
            "denta", code=strip_tags(codes[0]) if codes else "",
            name=strip_tags(name.group(1)), pack=strip_tags(pack.group(1)) if pack else "",
            price=price, old_price=old, brand=strip_tags(brand.group(1)) if brand else "",
            url=DENTA_BASE + href.group(1) if href else DENTA_BASE,
            image=urllib.parse.urljoin(DENTA_BASE, img.group(1)) if img else "",
        ))
    return items


# ---------- Henry Schein (ASP.NET WebForms) ----------

HS_BASE = "https://www.henryschein.be"
_hs_anon = AnonSession(HS_BASE + "/be-nl/dental/Default.aspx?did=dental")


def _hs_get(url):
    ck = cookie_header("henryschein", "henryschein")
    if ck:
        return http_get(url, {"Cookie": ck})[1]
    return _hs_anon.get(url)


def henryschein_logged_in():
    if not cookie_header("henryschein", "henryschein"):
        return False
    try:
        return "not-loggedin" not in _hs_get(HS_BASE + "/be-nl/dental/Default.aspx?did=dental")
    except Exception:
        return False


def _hs_prices(body, products, referer):
    """Ingelogd laadt Henry Schein prijzen via een aparte JSON-oproep."""
    n = re.search(r"var _n = '([^']*)'", body)
    ck = cookie_header("henryschein", "henryschein")
    if not n or not ck or not products:
        return {}
    arr = [{"ProductId": p["code"], "Qty": "1", "Uom": p["_uom"] or "ST", "CatalogName": "WEBDENT"}
           for p in products]
    data = urllib.parse.urlencode({
        "ItemArray": json.dumps({"ItemDataToPrice": arr}), "searchType": 6, "did": "dental",
        "catalogName": "WEBDENT", "endecaCatalogName": "WEBDENT", "culture": "be-nl",
        "showPriceToAnonymousUserFromCMS": "False", "isCallingFromCMS": "False",
    }).encode()
    req = urllib.request.Request(HS_BASE + "/webservices/JSONRequestHandler.ashx", data=data, headers={
        "User-Agent": UA, "Cookie": ck, "n": n.group(1), "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,  # zonder Referer geeft Henry Schein een leeg antwoord
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("iso-8859-15", "replace")  # € = 0xA4
    if not raw.strip():
        return {}
    out = {}
    for d in json.loads(raw).get("ItemDataToPrice", []):
        pid = str(d.get("ProductId", "")).replace("/", "")
        cust = parse_euro(str(d.get("CustomerPrice") or ""))
        cat = parse_euro(str(d.get("CatalogPrice") or ""))
        if cust:
            out[pid] = (cust, cat)
    return out


def henryschein_search(query):
    search_url = HS_BASE + "/be-nl/Search.aspx?searchkeyWord=" + urllib.parse.quote_plus(query)
    body = _hs_get(search_url)
    chunks = body.split('<h2 class="product-name">')
    products, seen = [], set()
    for i, b in enumerate(chunks[1:], 1):
        link = re.search(r'<a [^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', b)
        code = re.search(r'<strong>\s*(\d+)\s*</strong>', b)
        if not link or not code or code.group(1) in seen:
            continue
        seen.add(code.group(1))
        imgs = re.findall(r'data-img-url="([^"]+)"', chunks[i - 1])
        uom = re.search(r'hiddenUom" value="([^"]*)"', b)
        mfr = re.search(r'<small class="x-small"><strong>[^<]*</strong>\s*\|\s*([^<]*?)\s+-\s', b)
        pb = re.search(r'class="product-price"[^>]*>([\s\S]*?)</div>', b)
        prices = [p for p in (parse_euro(x) for x in
                  re.findall(r'(?:€|&euro;|&#8364;)\s*([\d.,]+)', pb.group(1) if pb else "")) if p]
        products.append({
            **item("henryschein", code=code.group(1), name=strip_tags(link.group(2)),
                   price=min(prices) if prices else None,
                   url=html.unescape(link.group(1)),
                   brand=strip_tags(mfr.group(1)) if mfr else "",
                   image=HS_BASE + imgs[-1] if imgs and imgs[-1].startswith("/") else ""),
            "_uom": uom.group(1) if uom else "",
        })
    if any(p["price"] is None for p in products):
        try:
            prices = _hs_prices(body, products, search_url)
        except Exception:
            prices = {}
        for p in products:
            if p["code"] in prices:
                p["price"], cat = prices[p["code"]]
                p["old_price"] = cat if cat and cat > p["price"] else None
    for p in products:
        p.pop("_uom")
    return products


# ---------- register ----------

SITES = {
    "dentaldiscount": {
        "label": "Dental Discount", "search": dentaldiscount.search,
        "logged_in": dentaldiscount.logged_in,
        "login_url": "https://www.dentaldiscount.com/nl-be/login",
        "note": "Toont ook staffelprijzen",
    },
    "basiq": {
        "label": "Basiq Dental", "search": basiq_search, "logged_in": basiq_logged_in,
        "login_url": "https://www.basiqdental.be/nl_BE/login",
        "note": "Publieke prijzen; login voor klantprijzen",
    },
    "dentaladdict": {
        "label": "Dental Addict", "search": dentaladdict_search,
        "logged_in": dentaladdict_logged_in,
        "login_url": "https://www.dental-addict.be/nl/authenticatie?back=my-account",
        "note": "Publieke prijzen; login voor groepsprijzen",
    },
    "hofmeester": {
        "label": "Hofmeester", "search": hofmeester.search, "logged_in": hofmeester.logged_in,
        "login_url": "https://www.hofmeester.nl/login",
        "note": "Prijzen enkel na login",
    },
    "denta": {
        "label": "Denta", "search": denta_search, "logged_in": denta_logged_in,
        "login_url": "https://www.denta.be/aanmelden/",
        "note": "Prijzen enkel na login",
    },
    "henryschein": {
        "label": "Henry Schein", "search": henryschein_search,
        "logged_in": henryschein_logged_in,
        "login_url": "https://www.henryschein.be/be-nl/Profiles/Login.aspx",
        "note": "Prijzen enkel na login",
    },
}


def refresh(site, code, name, cache=None):
    """Zoekt een bewaard product opnieuw op (eerst op naam, dan op artikelnummer)
    en geeft het actuele resultaat met hetzelfde artikelnummer terug, of None."""
    cache = {} if cache is None else cache
    for q in (name, code):
        if not q:
            continue
        key = (site, q.lower())
        if key not in cache:
            try:
                cache[key] = SITES[site]["search"](q)
            except Exception:
                cache[key] = []
        for it in cache[key]:
            if it["code"] == code:
                return it
    return None
