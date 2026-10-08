#!/usr/bin/env python3
"""Deon's Deals - daily deals updater (zero-token).

Fetches DesiDime's public hot-deals feed (https://t.me/s/desidime),
keeps genuine electronics price drops, resolves the buy link,
re-tags Amazon links with the associate tag, strips third-party
affiliate params from Flipkart links, and writes deals.json
for the static site.

Usage: python3 update_deals.py  (run from the site root)
"""
import json, os, re, html as htmllib, sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests

SITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_JSON = os.path.join(SITE_ROOT, "deals.json")
AFFILIATE_TAG = "deonsdeals-21"
FEED_URL = "https://t.me/s/desidime"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MIN_DISCOUNT = 20
MAX_DEALS = 24
MAX_AGE_HOURS = 72

ELECTRONICS_KW = [
    "phone", "mobile", "smartphone", "iphone", "galaxy", "oneplus", "redmi",
    "realme", "iqoo", "poco", "vivo", "oppo", "samsung", "pixel", "nothing",
    "laptop", "macbook", "notebook", "tablet", "ipad",
    "earbuds", "earphone", "headphone", "airpods", "airdopes", "speaker",
    "soundbar", "home theatre", "woofer",
    "watch", "smartwatch", "band", "amazfit", "noise", "boat", "fire-boltt",
    "tv", "television", "oled", "qled", "4k tv", "smart tv",
    "camera", "gopro", "dslr", "drone",
    "console", "ps5", "xbox", "nintendo", "controller",
    "refrigerator", "fridge", "washing machine", "microwave", "air conditioner",
    "chimney", "vacuum", "air fryer", "mixer", "grinder",
    "keyboard", "mouse", "monitor", "printer", "ssd", "hdd", "pendrive",
    "power bank", "charger", "cable", "adapter", "router", "wifi",
]
EXCLUDE_KW = [
    "recharge", "plan", "data pack", "validity", "supercoin", "luck by naam",
    "win ", "giveaway", "lottery", "ghee", "oil", "atta", "rice", "dal",
    "grocery", "soap", "shampoo", "diaper", "mattress", "bedsheet",
]

CATEGORY_MAP = [
    ("mobiles", ["phone", "mobile", "smartphone", "iphone", "galaxy", "oneplus",
                 "redmi", "realme", "iqoo", "poco", "vivo", "oppo", "pixel",
                 "nothing"]),
    ("laptops", ["laptop", "macbook", "notebook"]),
    ("audio", ["earbuds", "earphone", "headphone", "airpods", "airdopes",
               "speaker", "soundbar", "home theatre", "woofer"]),
    ("wearables", ["watch", "smartwatch", "band", "amazfit", "fire-boltt"]),
    ("tv", ["tv", "television", "oled", "qled", "smart tv", "refrigerator",
             "fridge", "washing machine", "microwave", "air conditioner",
             "chimney", "vacuum", "air fryer"]),
    ("accessories", ["keyboard", "mouse", "monitor", "printer", "ssd", "hdd",
                     "pendrive", "power bank", "charger", "cable", "adapter",
                     "router", "wifi", "camera", "gopro", "drone", "console",
                     "ps5", "xbox", "controller", "tablet", "ipad"]),
    ("fashion", ["jeans", "t-shirt", "tshirt", "shirt", "kurta", "saree",
                 "lehenga", "dress", "gown", "shoes", "sneakers", "sandals",
                 "slippers", "heels", "backpack", "handbag", "sunglasses",
                 "perfume", "apparel", "clothing", "ethnic", "footwear"]),
]


def fetch_feed():
    r = requests.get(FEED_URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def parse_blocks(page_html):
    blocks = re.split(r'<div class="tgme_widget_message_wrap', page_html)[1:]
    out = []
    for b in blocks:
        m = re.search(r'data-post="desidime/(\d+)"', b)
        if not m:
            continue
        post_id = m.group(1)
        t = re.search(r'datetime="([^"]+)"', b)
        try:
            ts = datetime.fromisoformat(t.group(1)) if t else None
        except ValueError:
            ts = None
        txt = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                        b, re.S)
        text = htmllib.unescape(re.sub(r"<[^>]+>", " ", txt.group(1))).strip() \
            if txt else ""
        text = re.sub(r"\s+", " ", text)
        links = re.findall(r'href="(https://ddime\.in/[^"]+)"', b)
        photo = re.search(r"background-image:url\('(https://cdn[^)]+)'\)", b)
        out.append({
            "id": post_id,
            "ts": ts,
            "text": text,
            "buy_url": links[-1] if links else None,   # last = Buy Now
            "photo": photo.group(1) if photo else None,
        })
    return out


def clean_title(title):
    emoji_re = re.compile(
        "[" "\U0001F600-\U0001F64F" "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF" "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0" "\U000024C2-\U0001F251" "]+",
        flags=re.UNICODE)
    title = emoji_re.sub("", title)
    return re.sub(r"\s+", " ", title).strip(" -–:")


def parse_deal(item):
    """Extract (discount_pct, title, price) from DesiDime post text."""
    text = item["text"]
    m = re.search(r"(\d+)\s*%\s*off", text, re.I)
    if not m:
        return None
    pct = int(m.group(1))
    pm = re.search(r"[Rr]s\.?\s*([\d,]*\d)", text)
    price = int(pm.group(1).replace(",", "")) if pm else None
    title = re.sub(r"^\s*\d+\s*%\s*off\s*(on\s*)?[-–:]*\s*", "", text, flags=re.I)
    title = re.split(r"\s*[-–]\s*Rs\.?", title)[0]
    title = re.split(r"\s+Read More\s*-", title)[0].strip(" -–:")
    title = clean_title(title)
    return {"pct": pct, "title": title[:120], "price": price}


def categorize(title):
    low = title.lower()
    for cat, kws in CATEGORY_MAP:
        if any(k in low for k in kws):
            return cat
    return "accessories"


def wanted(title, pct):
    if pct < MIN_DISCOUNT:
        return False
    low = title.lower()
    # word-boundary match: avoids "rice" matching "price", "atta" in "battery", etc.
    if any(re.search(r"\b" + re.escape(k.strip()) + r"\b", low) for k in EXCLUDE_KW):
        return False
    return any(k in low for k in ELECTRONICS_KW + FASHION_KW)


FASHION_KW = [
    "jeans", "t-shirt", "tshirt", "shirt", "kurta", "saree", "lehenga",
    "dress", "gown", "shoes", "sneakers", "sandals", "slippers",
    "heels", "backpack", "handbag", "sunglasses", "perfume",
    "apparel", "clothing", "ethnic", "footwear",
]


def resolve_buy(url):
    """Follow ddime.in redirect -> final merchant URL. Returns None on failure."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
        final = r.url
        if "ddime.in" in urlparse(final).netloc:
            return None
        return final
    except Exception:
        return None


def strip_affiliates(url):
    """Drop third-party affiliate/tracking params from a scraped Flipkart URL.

    DesiDime's feed links carry its own affiliate tag (affid=salescueli);
    passing them through untouched would credit commissions to DesiDime's
    account, not Deon's. Flipkart traffic earns via his EarnKaro shortlinks
    (curated picks), so scraped Flipkart links go out clean.
    """
    drop = {"affid", "affextparam1", "affextparam2", "affextparam3",
            "affextparam4", "affextparam5"}
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query) if k.lower() not in drop]
    return urlunparse(u._replace(query=urlencode(q)))


def retag(url):
    """Amazon -> associate-tagged dp link. Flipkart -> as-is. Others -> None."""
    host = urlparse(url).netloc.lower()
    if "amazon.in" in host:
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
        if not m:
            return None
        return f"https://www.amazon.in/dp/{m.group(1)}?tag={AFFILIATE_TAG}"
    if "flipkart.com" in host or "fkrt.cc" in host:
        return strip_affiliates(url)
    return None


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    page_html = fetch_feed()
    items = parse_blocks(page_html)
    deals = []
    for item in items:
        if item["ts"] and item["ts"] < cutoff:
            continue
        if not item["buy_url"]:
            continue
        parsed = parse_deal(item)
        if not parsed:
            continue
        if not wanted(parsed["title"], parsed["pct"]):
            continue
        final = resolve_buy(item["buy_url"])
        if not final:
            continue
        link = retag(final)
        if not link:
            continue
        deals.append({
            "id": f"dd-{item['id']}",
            "title": parsed["title"],
            "category": categorize(parsed["title"]),
            "price": parsed["price"],
            "off_pct": parsed["pct"],
            "url": link,
            "image": item["photo"],
            "merchant": "amazon" if "amazon.in" in link else "flipkart",
            "posted_at": item["ts"].isoformat() if item["ts"] else None,
        })
        if len(deals) >= MAX_DEALS:
            break

    # Merge curated picks (EarnKaro BBD phones, sheet recommendations).
    # They persist across daily refreshes and sit on top; skipped only
    # if a live feed deal already covers the same model (word-boundary).
    import glob
    feed_titles = " ".join(x["title"].lower() for x in deals)
    pinned = []
    for path in sorted(glob.glob(os.path.join(SITE_ROOT, "scripts",
                                              "curated_*.json"))):
        try:
            with open(path) as f:
                curated = json.load(f)
        except (OSError, ValueError):
            continue
        for c in curated:
            key = c.pop("match", "")
            if key and re.search(r"\b" + re.escape(key.lower()) + r"\b",
                                 feed_titles):
                continue
            c = dict(c)
            c["posted_at"] = now.isoformat()
            pinned.append(c)
    deals = pinned + deals

    # Site focus: phones & audio only (his call 2026-10-08).
    deals = [d for d in deals if d.get("category") in ("mobiles", "audio")]

    payload = {
        "updated": now.isoformat(),
        "count": len(deals),
        "deals": deals,
    }
    with open(DEALS_JSON, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"wrote {len(deals)} deals -> {DEALS_JSON}")


if __name__ == "__main__":
    sys.exit(main())
