"""The store's catalog and the assistant's prompt.

The catalog is the store's own catalog.json, the file its pages render, fetched from CATALOG_URL at the start of each
call, so products, prices and the store's name change without redeploying the agent. knowledge/shop/catalog.json is the
fallback copy. The prompt is knowledge/shop/prompt.md filled in from the catalog's "store" section and its products.
"""

import json
import logging
import os
import re

import aiohttp

log = logging.getLogger("shop.catalog")
KNOWLEDGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "knowledge", "shop"
)
FALLBACK = os.path.join(KNOWLEDGE, "catalog.json")


async def load(url: str | None = None) -> "Catalog":
    url = url if url is not None else os.getenv("CATALOG_URL")
    if url:
        try:
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as http,
                http.get(url) as r,
            ):
                r.raise_for_status()
                return Catalog(await r.json(content_type=None), source=url)
        except Exception as e:
            log.warning("catalog from %s failed (%s); using the local copy", url, e)
    return load_local()


def load_local() -> "Catalog":
    with open(FALLBACK) as f:
        return Catalog(json.load(f), source=FALLBACK)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _money(n: float) -> str:
    return f"${n:,.2f}"


class Catalog:
    def __init__(self, data: dict, source: str = ""):
        self.data, self.source = data, source
        self.store: dict = data.get("store") or {}
        self.features: dict = data.get("features") or {}
        self.categories: list[dict] = data.get("categories") or []
        self.products: dict[str, dict] = {p["id"]: p for p in data["products"]}
        self.aliases = self._aliases()

    # ---------- product facts ----------
    @staticmethod
    def colors(p: dict) -> list[str]:
        return [c["name"] if isinstance(c, dict) else c for c in p.get("colors") or []]

    def price_of(self, pid: str, option: str | None = None) -> float:
        """A product's price with that option (size, bundle...), else with its default option."""
        p = self.products[pid]
        choices = (p.get("options") or {}).get("choices") or []
        for c in choices:
            if option and c["name"].lower() == option.lower():
                return c["price"]
        return choices[p.get("defOption", 0)]["price"] if choices else p["price"]

    def rating(self, p: dict) -> str:
        if p.get("rating"):
            return f"{p['rating']} stars ({p.get('reviews', 0):,} sample reviews)"
        scores = [r["score_5"] for r in p.get("expert_reviews") or [] if isinstance(r.get("score_5"), int | float)]
        if scores:
            return f"{sum(scores) / len(scores):.1f} of 5, average of {len(scores)} expert reviews"
        return ""

    def product_text(self, p: dict) -> str:
        price = _money(p["price"]) + (
            f" (was {_money(p['was'])}{', deal of the day' if p.get('deal') else ''})" if p.get("was") else ""
        )
        stock = {"in": "in stock", "low": f"only {p.get('left')} left", "out": "sold out"}.get(p.get("stock", "in"), "")
        parts = [f"{p['id']} | {p['name']} | {price} | {stock}"]
        if r := self.rating(p):
            parts.append(f"rating: {r}")
        if c := self.colors(p):
            parts.append("colors: " + ", ".join(c))
        if o := p.get("options"):
            default = o["choices"][p.get("defOption", 0)]["name"]
            parts.append(
                f"{o['label']} (default {default}): "
                + ", ".join(f"{c['name']} {_money(c['price'])}" for c in o["choices"])
            )
        if p.get("facets"):
            parts.append("; ".join(f"{k}: {v}" for k, v in p["facets"].items()))
        if p.get("features"):
            parts.append("features: " + ", ".join(self.features.get(f, f) for f in p["features"]))
        if p.get("specs"):
            parts.append("specs: " + "; ".join(f"{k}: {v}" for k, v in p["specs"].items()))
        if p.get("summary"):
            parts.append("about: " + p["summary"])
        elif p.get("highlights"):
            parts.append("highlights: " + "; ".join(p["highlights"]))
        if p.get("in_box"):
            parts.append("in the box: " + ", ".join(p["in_box"]))
        for q, a in p.get("qa") or []:
            parts.append(f"Q: {q} A: {a}")
        for r in p.get("expert_reviews") or []:
            score = f" {r['score_text']}" if r.get("score_text") else ""
            award = f" ({r['award']})" if r.get("award") else ""
            pros = f" Pros: {'; '.join(r['pros'])}." if r.get("pros") else ""
            cons = f" Cons: {'; '.join(r['cons'])}." if r.get("cons") else ""
            covered = f" [{r['model_reviewed']}]" if r.get("model_reviewed") else ""
            quote = f' Quote: "{r["quote"]}"' if r.get("quote") else ""
            parts.append(f"review, {r['publication']}{score}{award}{covered}: {r['verdict']}{pros}{cons}{quote}")
        return "\n  ".join(parts)

    def filters_text(self) -> str:
        """The attribute filters the store offers, from the products' facets."""
        facets: dict[str, list[str]] = {}
        for p in self.products.values():
            for k, v in (p.get("facets") or {}).items():
                facets.setdefault(k, [])
                if v not in facets[k]:
                    facets[k].append(v)
        lines = [f"- {k}: {' / '.join(vs)}" for k, vs in facets.items()]
        if self.features:
            lines.append("- features: " + ", ".join(self.features))
        return "\n".join(lines)

    def catalog_text(self) -> str:
        out = []
        for c in self.categories:
            out.append(f"\n## {c['name']} (category id: {c['id']})")
            out += [self.product_text(p) for p in self.products.values() if p["cat"] == c["id"]]
        return "\n".join(out).strip()

    def prompt(self) -> str:
        with open(os.path.join(KNOWLEDGE, "prompt.md")) as f:
            template = f.read()
        s = self.store
        fill = {
            "assistant": s.get("assistant", "the assistant"),
            "store": s.get("name", "the store"),
            "about": s.get("about", ""),
            "guide": "\n".join(f"- {g}" for g in s.get("guide") or []),
            "filters": self.filters_text(),
            "catalog": self.catalog_text(),
        }
        return re.sub(r"\{(\w+)\}", lambda m: fill.get(m.group(1), m.group(0)), template)

    def greeting(self) -> str:
        return (
            self.store.get("greeting") or "Greet the shopper in one short sentence and ask what they're shopping for."
        )

    # ---------- names ----------
    def _aliases(self) -> dict[tuple[str, ...], str]:
        """What the assistant may call each product, derived from the names: the brand plus the start of the model
        ("auralis pro", "halo 9 pro"), or the start of the model alone ("a1 mini", "quietmax") when it can only mean
        that product. A start shared by several products (like "a1" in "A1" and "A1 mini") means the one with the
        shortest name, if it holds a model number. Products may also list extra "aliases"."""
        name_words = {pid: words(p["name"]) for pid, p in self.products.items()}
        seen: dict[str, int] = {}
        for ws in name_words.values():
            for w in set(ws):
                seen[w] = seen.get(w, 0) + 1
        starts: dict[tuple[str, ...], list[str]] = {}
        for pid, p in self.products.items():
            full, brand = name_words[pid], words(p.get("brand", ""))
            while brand and full[: len(brand)] != brand:  # "Prusa CORE One+" by "Prusa Research": the brand is "prusa"
                brand = brand[:-1]
            model = full[len(brand) :]
            for k in range(1, len(model) + 1):
                cands = {tuple(model[:k])} | ({tuple(brand + model[:k])} if brand else set())
                for a in cands:
                    starts.setdefault(a, []).append(pid)

        def numbered(a: tuple[str, ...]) -> bool:
            return any(re.search(r"\d", w) for w in a)

        aliases: dict[tuple[str, ...], str] = {}
        for a, pids in starts.items():
            owner = min(pids, key=lambda x: (len(name_words[x]), x))
            single = len(a) == 1
            letters_and_digits = numbered(a) and re.search(r"[a-z]", a[0]) is not None
            distinctive = (
                not single or letters_and_digits or (len(a[0]) >= 5 and seen.get(a[0], 0) == 1 and len(pids) == 1)
            )
            if not distinctive:
                continue
            if len(pids) == 1 or (numbered(a) and (not single or letters_and_digits)):
                aliases[a] = owner
        for pid, p in self.products.items():
            for extra in p.get("aliases") or []:
                aliases[tuple(words(extra))] = pid
        return aliases

    def mentioned(self, text: str) -> list[str]:
        """Products named in a text, in the order they appear (the longest name wins where names overlap)."""
        ws = words(text)
        spans = []
        for i in range(len(ws)):
            for j in range(min(len(ws), i + 8), i, -1):
                if (pid := self.aliases.get(tuple(ws[i:j]))) is not None:
                    spans.append((i, j, pid))
                    break
        kept: list[tuple[int, int, str]] = []
        for s, e, pid in sorted(spans, key=lambda x: x[0] - x[1]):
            if all(e <= ks or s >= ke for ks, ke, _ in kept):
                kept.append((s, e, pid))
        return [pid for _, _, pid in sorted(kept)]

    def attr_words(self, pid: str) -> set[str]:
        """Words that describe a product, for "the blue one" or "the enclosed one"."""
        p = self.products[pid]
        text = " ".join(
            [
                p["name"],
                p.get("brand", ""),
                *self.colors(p),
                *p.get("features", []),
                p["cat"],
                *(p.get("facets") or {}).values(),
            ]
        )
        ws = set(words(text))
        return ws | {w.rstrip("s") for w in ws} | {w + "s" for w in ws}
