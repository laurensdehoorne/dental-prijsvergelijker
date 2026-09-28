"""Winkelmandjes: toevoegen, uitlezen en verwijderen per webwinkel.

Werkt met de ingelogde sessie (zie login.py). De app bestelt nooit: afrekenen
gebeurt altijd door de gebruiker zelf in de webwinkel.

Elke winkel levert bij read() hetzelfde formaat:
  {"items": [{"code", "name", "qty", "unit", "total", "line"}], "subtotal", "count",
   "free_shipping_left" (door de winkel zelf berekend, anders None), "url"}
'line' is wat remove() nodig heeft om die regel te verwijderen.
"""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import sites
from sites import UA, cookie_header, http_get, parse_euro, strip_tags


class CartError(Exception):
    pass


def _req(url, *, data=None, headers=None, method=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _need(cookie, label):
    if not cookie:
        raise CartError(f"Log eerst in bij {label}.")
    return cookie


# ---------- Basiq Dental (SAP Commerce OCC) ----------

class Basiq:
    label = "Basiq Dental"
    url = "https://www.basiqdental.be/nl_BE/cart"
    Q = "lang=nl_BE&curr=EUR"

    def _call(self, method, path, body=None):
        token = sites.basiq_token()
        if not token:
            raise CartError("Log eerst in bij Basiq Dental.")
        try:
            raw = _req(sites.BQ_API + path, method=method,
                       data=json.dumps(body).encode() if body is not None else None,
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                "Content-Type": "application/json"})
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise CartError("Basiq-login verlopen: log opnieuw in.")
            if e.code in (400, 404) and method == "GET":
                return None  # nog geen mandje
            raise

    def _cart_code(self):
        c = self._call("GET", f"users/current/carts/current?fields=code&{self.Q}")
        if c and c.get("code"):
            return c["code"]
        return self._call("POST", f"users/current/carts?fields=code&{self.Q}")["code"]

    def add(self, item, qty):
        code = self._cart_code()
        r = self._call("POST", f"users/current/carts/{code}/entries?{self.Q}",
                       {"product": {"code": item["code"]}, "quantity": qty})
        if r.get("statusCode") not in ("success", None):
            raise CartError(f"Basiq: {r.get('statusCode')}")

    def read(self):
        c = self._call("GET", "users/current/carts/current?fields=code,totalItems,subTotal(value),"
                              "entries(entryNumber,quantity,product(code,name),basePrice(value),totalPrice(value))&" + self.Q)
        items = [{
            "code": e["product"]["code"], "name": strip_tags(e["product"].get("name", "")), "qty": e["quantity"],
            "unit": (e.get("basePrice") or {}).get("value"), "total": (e.get("totalPrice") or {}).get("value"),
            "line": f"{c['code']}:{e['entryNumber']}",
        } for e in (c or {}).get("entries", [])]
        return {"items": items, "subtotal": ((c or {}).get("subTotal") or {}).get("value", 0.0),
                "free_shipping_left": 0.0, "url": self.url}

    def remove(self, line):
        code, entry = line.split(":")
        self._call("DELETE", f"users/current/carts/{code}/entries/{entry}?{self.Q}")


# ---------- Ordent (Dental Discount, Hofmeester) ----------

class Ordent:
    def __init__(self, shop, label, cart_path):
        self.shop, self.label = shop, label
        self.url = shop.base + cart_path

    def _get(self, path):
        ck = _need(cookie_header(self.shop.site, self.shop.domain), self.label)
        return _req(self.shop.base + path, headers={"Cookie": ck, "X-Requested-With": "XMLHttpRequest",
                                                     "Referer": self.shop.base + self.shop.home}).decode("utf-8", "replace")

    def _set(self, sku, count):
        self._get("ajax/cart-update.php?" + urllib.parse.urlencode(
            {"action": "custom", "sku": sku, "count": count, "unit": 1}))

    def add(self, item, qty):
        current = {i["code"]: i["qty"] for i in self.read()["items"]}
        self._set(item["code"], current.get(item["code"], 0) + qty)  # 'custom' = aantal instellen

    def read(self):
        body = self._get("ajax/cart-items.php")
        items = []
        for row in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', body):
            sku = re.search(r'data-sku="([^"]+)"', row)
            if not sku:
                continue
            brand = re.search(r'<small class="d-block text-grey"><a[^>]*>([^<]*)</a>', row)
            name = re.findall(r'<a href="product/[^"]*">([^<]+)</a>', row)
            qty = re.search(r'name="quantity"[^>]*value="(\d+)"', row) or re.search(r'value="(\d+)"[^>]*data-sku', row)
            unit = re.search(r'class="product-subtotal[^"]*">\s*<span[^>]*>([^<]+)</span>', row)
            total = re.search(r'class="product-price">\s*<span[^>]*>([^<]+)</span>', row)
            title = next((n.strip() for n in name if n.strip() and not n.strip().startswith("Artikelnr")
                          and (not brand or n.strip() != brand.group(1).strip())), "")
            items.append({
                "code": sku.group(1),
                "name": strip_tags(f"{brand.group(1) if brand else ''} {title}"),
                "qty": int(qty.group(1)) if qty else 1,
                "unit": parse_euro(unit.group(1)) if unit else None,
                "total": parse_euro(total.group(1)) if total else None,
                "line": sku.group(1),
            })
        return {"items": items, "subtotal": round(sum(i["total"] or 0 for i in items), 2),
                "free_shipping_left": None, "url": self.url}

    def remove(self, line):
        self._set(line, 0)


# ---------- Dental Addict (PrestaShop 1.6) ----------

class DentalAddict:
    label = "Dental Addict"
    url = "https://www.dental-addict.be/nl/bestelling"
    endpoint = "https://www.dental-addict.be/index.php"

    def _ck(self):
        return _need(cookie_header("dentaladdict", "dental-addict"), self.label)

    def _token(self):
        _, page = http_get(sites.DA_BASE, {"Cookie": self._ck()})
        m = re.search(r"static_token\s*=\s*'([^']+)'", page)
        if not m:
            raise CartError("Dental Addict: sessie niet geldig, log opnieuw in.")
        return m.group(1)

    def _post(self, params):
        raw = _req(self.endpoint, data=urllib.parse.urlencode(params).encode(), headers={
            "Cookie": self._ck(), "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded"})
        return json.loads(raw)

    def add(self, item, qty):
        r = self._post({"controller": "cart", "add": 1, "ajax": "true", "qty": qty,
                        "id_product": item["code"], "ipa": 0, "token": self._token()})
        if r.get("hasError"):
            raise CartError("Dental Addict: " + "; ".join(map(str, r.get("errors", []))))

    def read(self):
        c = self._post({"controller": "cart", "ajax": "true", "token": self._token()})
        items = [{
            "code": str(p["id"]), "name": strip_tags(p.get("name", "")).title(), "qty": int(p.get("quantity", 1)),
            "unit": None, "total": p.get("price_float"),
            # voor verwijderen zijn ook variant- en adresnummer nodig
            "line": f"{p['id']}:{p.get('idCombination') or 0}:{p.get('idAddressDelivery') or 0}",
        } for p in c.get("products", [])]
        for i in items:
            i["unit"] = round(i["total"] / i["qty"], 2) if i["total"] and i["qty"] else None
        # de winkel berekent zelf hoeveel er nog ontbreekt voor gratis verzending
        if c.get("free_ship"):
            left = 0.0
        elif c.get("freeShippingFloat") is not None:
            left = max(0.0, round(float(c["freeShippingFloat"]), 2))
        else:
            left = None
        return {"items": items, "subtotal": round(sum(i["total"] or 0 for i in items), 2),
                "free_shipping_left": left, "url": self.url}

    def remove(self, line):
        pid, ipa, addr = line.split(":")
        self._post({"controller": "cart", "delete": 1, "ajax": "true", "id_product": pid, "ipa": ipa,
                    "id_address_delivery": addr, "token": self._token()})


# ---------- Denta (ASP.NET MVC) ----------

class Denta:
    label = "Denta"
    url = "https://www.denta.be/winkelmand/"

    def _ck(self):
        return _need(cookie_header("denta", "denta.be"), self.label)

    def add(self, item, qty):
        # zoals de knop 'In winkelmandje' op de productpagina: eerst de pagina lezen
        _, page = http_get(item["url"], {"Cookie": self._ck()})
        ap = re.search(r'<[^>]+id="AddProduct"[^>]*>', page)
        item_no = re.search(r'id="ItemNo"[^>]*>([^<]*)<', page)
        if not ap or not item_no:
            raise CartError("Denta: dit product kan niet rechtstreeks in het mandje (open de productpagina).")
        attr = lambda n: html.unescape((re.search(rf'data-{n}="([^"]*)"', ap.group(0)) or [None, ""])[1])
        uom = re.search(r'id="UOMItem"[^>]*value="([^"]*)"', page)
        form = {"itemTitle": attr("title"), "type": "product", "itemNo": item_no.group(1).strip(),
                "uom": uom.group(1) if uom else "", "basketType": 0, "itemType": attr("type"),
                "itemUrl": attr("url"), "allItems": "", "family": "", "gamma": "", "subgamma": "",
                "query": attr("qry"), "quantity": qty}

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        req = urllib.request.Request("https://www.denta.be/catalogus-addproduct/",
                                     data=urllib.parse.urlencode(form).encode(),
                                     headers={"User-Agent": UA, "Cookie": self._ck(), "Referer": item["url"],
                                              "Content-Type": "application/x-www-form-urlencoded"})
        try:
            urllib.request.build_opener(NoRedirect).open(req, timeout=25)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303):
                raise

    def read(self):
        _, page = http_get(self.url, {"Cookie": self._ck()})
        items = []
        for b in page.split('<div class="gtm-product product">')[1:]:
            no = re.search(r'gtm-product-number">\s*([^<]+?)\s*<', b)
            name = re.search(r'class="gtm-item-title"[^>]*>([^<]+)<', b)
            price = re.search(r'class="gtm-product-price">([^<]+)<', b)
            qty = re.search(r'id="ProductQuantity_\d+"[^>]*value="(\d+)"', b)
            rm = re.search(r'href="(/remove-product/[^"]+)"', b)
            unit = parse_euro(price.group(1)) if price else None
            q = int(qty.group(1)) if qty else 1
            items.append({"code": no.group(1).strip() if no else "", "name": strip_tags(name.group(1)) if name else "",
                          "qty": q, "unit": unit, "total": round(unit * q, 2) if unit else None,
                          "line": rm.group(1) if rm else ""})
        return {"items": items, "subtotal": round(sum(i["total"] or 0 for i in items), 2),
                "free_shipping_left": None, "url": self.url}

    def remove(self, line):
        if not line.startswith("/remove-product/"):
            raise CartError("Denta: onbekende regel.")
        http_get("https://www.denta.be" + line, {"Cookie": self._ck()})


# ---------- Henry Schein (ASP.NET WebForms) ----------

class HenrySchein:
    label = "Henry Schein"
    url = "https://www.henryschein.be/be-nl/Shopping/CurrentCart.aspx"

    def _ck(self):
        return _need(cookie_header("henryschein", "henryschein"), self.label)

    def _json(self, data, referer):
        _, page = http_get(referer, {"Cookie": self._ck()})
        if "not-loggedin" in page:
            raise CartError("Henry Schein-login verlopen: log opnieuw in.")
        n = re.search(r"var _n = '([^']*)'", page)
        raw = _req(sites.HS_BASE + "/webservices/JSONRequestHandler.ashx", data=urllib.parse.urlencode(data).encode(),
                   headers={"Cookie": self._ck(), "n": n.group(1) if n else "", "X-Requested-With": "XMLHttpRequest",
                            "Referer": referer, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        return json.loads(raw.decode("iso-8859-15", "replace") or "{}")

    def add(self, item, qty):
        add = {"ItemDataToAdd": [{"ProductId": item["code"], "Qty": str(qty), "Uom": item.get("uom") or "ST"}]}
        r = self._json({"ItemArray": json.dumps(add), "searchType": 5, "did": "dental", "catalogName": "WEBDENT",
                        "endecaCatalogName": "WEBDENT", "culture": "be-nl"}, self.url)
        bad = [s for s in r.get("ItemsStatus", []) if s.get("Status") != "Success"]
        if bad:
            raise CartError(f"Henry Schein: {bad[0].get('Status')}")

    def read(self):
        _, page = http_get(self.url, {"Cookie": self._ck()})
        if "not-loggedin" in page:
            raise CartError("Henry Schein-login verlopen: log opnieuw in.")
        m = re.search(r"'event' : 'view_cart'[\s\S]*?'items': \[([\s\S]*?)\]\s*\}", page)
        lines = re.findall(r'hdnItemId" value="([^"]+)"', page)
        items = []
        for i, obj in enumerate(re.findall(r'\{([^{}]*)\}', m.group(1) if m else "")):
            f = dict(re.findall(r"'(\w+)'\s*:\s*'?([^',]*)'?", obj))
            qty = int(float(f.get("quantity", 1) or 1))
            unit = float(f["price"]) if f.get("price") else None
            items.append({"code": f.get("item_id", ""), "name": html.unescape(f.get("item_name", "")),
                          "qty": qty, "unit": unit, "total": round(unit * qty, 2) if unit else None,
                          "line": lines[i] if i < len(lines) else ""})
        return {"items": items, "subtotal": round(sum(i["total"] or 0 for i in items), 2),
                "free_shipping_left": None, "url": self.url}

    def remove(self, line):
        self._json({"lineItemId": line, "cartId": "", "userId": "", "did": "dental", "catalogName": "WEBDENT",
                    "endecaCatalogName": "WEBDENT", "searchType": 12, "culture": "be-nl"}, self.url)


CARTS = {
    "dentaldiscount": Ordent(sites.dentaldiscount, "Dental Discount", "nl-be/cart"),
    "basiq": Basiq(),
    "dentaladdict": DentalAddict(),
    "hofmeester": Ordent(sites.hofmeester, "Hofmeester", "cart"),
    "denta": Denta(),
    "henryschein": HenrySchein(),
}

# Verzendvoorwaarden (excl. btw), overschrijfbaar via settings.json / Instellingen in de app.
DEFAULT_SHIPPING = {
    "dentaldiscount": {"free_from": 175, "cost": 7.95},
    "basiq": {"free_from": 0, "cost": 0},
    "dentaladdict": {"free_from": 150, "cost": 9.00},
    "hofmeester": {"free_from": 100, "cost": 4.95},
    "denta": {"free_from": 150, "cost": 6.50},
    "henryschein": {"free_from": None, "cost": None},
}
