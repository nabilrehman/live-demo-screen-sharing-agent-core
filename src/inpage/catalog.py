"""The store's catalog and Kai's prompt, from knowledge/shop/.

voltline_catalog.json is exported from the store's catalog.js (the page is the source of truth). To refresh it, from the
store folder:
  node -e "global.window={};require('./catalog.js');const V=window.VOLT;require('fs').writeFileSync('voltline_catalog.json',
    JSON.stringify({categories:V.categories.map(c=>({id:c.id,name:c.name})),features:V.features,products:V.products.map(p=>({
    id:p.id,name:p.name,brand:p.brand,cat:p.cat,price:p.price,was:p.was||null,deal:!!p.deal,rating:p.rating,reviews:p.reviews,
    stock:p.stock,left:p.left||null,colors:(p.colors||[]).map(c=>c.name),options:p.options?{label:p.options.label,
    choices:p.options.choices.map(c=>({name:c.name,price:c.price}))}:null,features:p.features,highlights:p.highlights,
    specs:p.specs}))},null,1))"
"""

import json
import os
import re

KNOWLEDGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "knowledge", "shop"
)

with open(os.path.join(KNOWLEDGE, "voltline_catalog.json")) as f:
    CATALOG = json.load(f)
PRODUCTS: dict[str, dict] = {p["id"]: p for p in CATALOG["products"]}


# words that name the kind of product, not the model
# fmt: off
GENERIC = {
    "noise", "wireless", "over-ear", "on-ear", "anc", "earbuds", "headphones", "headset", "4k", "8k", "oled",
    "qled", "led", "mini-led", "full", "hd", "smart", "tv", "laptop", "ultralight", "gaming", "2-in-1",
    "touchscreen", "creator", "everyday", "student", "5g", "unlocked", "phone", "foldable", "console", "controller",
    "speaker", "video", "indoor", "cam", "robot", "self-emptying", "edition", "direct-drive", "racing", "wheel",
    "mechanical", "keyboard", "cable", "charger", "case", "sleeve", "system", "color", "bulbs", "plug",
    "thermostat", "mesh", "wi-fi", "6e", "2k", "qhd", "120hz", "144hz", "165hz", "tilting", "tempered", "usb-c",
    "65w", "hardshell", "clear", "magsnap", "with", "wired",
}
# fmt: on


def model_name(p: dict) -> str:
    """The model as people say it, without brand and product type: "Studio Q8", "QuietMax", "Nova S"."""
    words = p["name"][len(p["brand"]) :].split()
    out = []
    for w in words:
        if w.lower() in GENERIC or '"' in w or w in ("–", "-", "(4-Pack)"):
            break
        out.append(w)
    return " ".join(out)


def _money(n: float) -> str:
    return f"${n:,.2f}"


def product_line(p: dict) -> str:
    price = _money(p["price"]) + (
        f" (was {_money(p['was'])}{', deal of the day' if p['deal'] else ''})" if p["was"] else ""
    )
    stock = {"in": "in stock", "low": f"only {p['left']} left", "out": "sold out"}[p["stock"]]
    opts = (
        f"{p['options']['label']}: " + ", ".join(f"{c['name']} {_money(c['price'])}" for c in p["options"]["choices"])
        if p["options"]
        else "-"
    )
    feats = ", ".join(CATALOG["features"].get(f, f) for f in p["features"])
    specs = "; ".join(f"{k}: {v}" for k, v in p["specs"].items())
    return " | ".join(
        [
            p["id"],
            p["name"],
            price,
            f"{p['rating']} stars ({p['reviews']:,})",
            stock,
            ", ".join(p["colors"]) or "-",
            opts,
            feats,
            specs,
            "; ".join(p["highlights"]),
        ]
    )


def catalog_text() -> str:
    out = []
    for c in CATALOG["categories"]:
        out.append(f"\n## {c['name']}")
        out += [product_line(p) for p in CATALOG["products"] if p["cat"] == c["id"]]
    return "\n".join(out).strip()


def prompt() -> str:
    with open(os.path.join(KNOWLEDGE, "kai_prompt.md")) as f:
        return f.read().replace("{catalog}", catalog_text())


def _aliases() -> dict[str, list[str]]:
    """Names Kai may use for each product: brand + model, and the model alone when it's distinctive."""
    models = [model_name(p).lower() for p in CATALOG["products"]]
    out = {}
    for p in CATALOG["products"]:
        m = model_name(p).lower()
        names = [f"{p['brand'].lower()} {m}"] if m else []
        distinctive = len(m) >= 4 or (re.search(r"[a-z]", m) and re.search(r"\d", m))
        if m and models.count(m) == 1 and distinctive:
            names.append(m)
        out[p["id"]] = names
    return out


ALIASES = _aliases()


def mentioned(text: str) -> list[str]:
    """Products named in a line Kai said, in the order they appear (the longest name wins where names overlap)."""
    low = text.lower()
    spans = []
    for pid, names in ALIASES.items():
        for n in names:
            for m in re.finditer(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", low):
                spans.append((m.start(), m.end(), pid))
    kept: list[tuple[int, int, str]] = []
    for s, e, pid in sorted(spans, key=lambda x: x[0] - x[1]):
        if all(e <= ks or s >= ke for ks, ke, _ in kept):
            kept.append((s, e, pid))
    return [pid for _, _, pid in sorted(kept)]
