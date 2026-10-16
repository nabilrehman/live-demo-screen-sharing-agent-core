"""What the shopper's page shows (the latest page_context snapshot), as a short note for the model, and which product
"this one", "the second one" or "the blue one" means."""

import json
import re
import time

from .catalog import ALIASES, PRODUCTS

RECENT_TOUCH_S = 10  # a click or hover counts as "this one" for this long
ORDINALS = {
    "first": 1, "1st": 1, "one": 1, "top": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
}  # fmt: skip
DEICTIC = re.compile(r"^(it|this|that|these|those|this one|that one|the one|same|the same one|current)$")
STOP = {"the", "a", "an", "one", "ones", "that", "this", "please", "product", "item"}


def _money(n) -> str:
    return f"${n:,.2f}"


class PageState:
    def __init__(self):
        self.ctx: dict = {}
        self.at = 0.0  # when the snapshot arrived (monotonic)
        self.last_mentioned: str | None = None  # the last product Kai named

    def update(self, ctx: dict) -> bool:
        """Keep the newest snapshot (the page numbers them); False if it's older than the one we have."""
        if ctx.get("seq", 0) < self.ctx.get("seq", 0):
            return False
        self.ctx, self.at = ctx, time.monotonic()
        return True

    def update_json(self, text: str) -> bool:
        try:
            return self.update(json.loads(text))
        except (ValueError, TypeError):
            return False

    def signature(self) -> str:
        """What the model should hear about again when it changes (not timings or sequence numbers)."""
        c = {k: v for k, v in self.ctx.items() if k not in ("seq", "last_interaction")}
        li = self.ctx.get("last_interaction")
        return json.dumps([c, li and (li["id"], li["type"])], sort_keys=True)

    def touched(self) -> str | None:
        """The product the shopper clicked or hovered in the last few seconds."""
        li = self.ctx.get("last_interaction")
        if not li:
            return None
        age = li.get("ms_ago", 0) / 1000 + time.monotonic() - self.at
        return li["id"] if age < RECENT_TOUCH_S and li["id"] in PRODUCTS else None

    def note(self) -> str:
        c = self.ctx
        if not c:
            return "<page_now>The page hasn't reported yet.</page_now>"
        lines = [f"Page: {c.get('page')} ({c.get('route')})"]
        if p := c.get("product"):
            v = p.get("variant") or {}
            chosen = ", ".join(x for x in (v.get("color"), v.get("option")) if x)
            stock = "sold out" if not p.get("in_stock") else (f"only {p['left']} left" if p.get("left") else "in stock")
            lines.append(
                f"Open product: {p['name']} [{p['id']}], {_money(p['price'])}{', selected ' + chosen if chosen else ''}, {stock}."
            )
            vs = p.get("variants") or {}
            if vs.get("colors"):
                lines.append("Colors: " + ", ".join(vs["colors"]) + ".")
            if vs.get("options"):
                lines.append("Options: " + ", ".join(vs["options"]) + ".")
        if vis := c.get("visible"):
            items = "; ".join(
                f"{v['pos']}. {v['name']} [{v['id']}] {_money(v['price'])}, {v['rating']} stars{', on sale' if v.get('deal') else ''}"
                for v in vis
            )
            more = f" (+{c['more']} more below)" if c.get("more") else ""
            lines.append(f"Listed in order: {items}{more}")
        if (f := c.get("filters")) is not None:
            lines.append(f"Search and filters: {json.dumps(f) if f else 'none'}; sort: {c.get('sort', 'best')}.")
        if t := self.touched():
            li = c["last_interaction"]
            lines.append(
                f"Shopper just {'clicked' if li['type'] == 'click' else 'pointed at'}: {PRODUCTS[t]['name']} [{t}]."
            )
        cart = c.get("cart") or {}
        if cart.get("count"):
            items = "; ".join(
                f"{l['name']}{' (' + l['variant'] + ')' if l.get('variant') else ''} x{l['qty']} [line {l['line_id']}]"
                for l in cart["lines"]
            )
            lines.append(f"Cart: {cart['count']} items, subtotal {_money(cart['subtotal'])}: {items}.")
        else:
            lines.append("Cart: empty.")
        return "<page_now>\n" + "\n".join(lines) + "\n</page_now>"

    def resolve(self, ref: str) -> tuple[str | None, str]:
        """A product id for what the shopper said, or (None, why) when it isn't clear.
        Order: an id or name; "this/that/it": the open product, then the one just touched, then the last one Kai
        named; "the second one": that position in the list; "the blue one": the one listed product with that color."""
        ref = (ref or "").strip()
        low = ref.lower().strip(" .?!")
        if ref in PRODUCTS:
            return ref, ""
        visible = [v["id"] for v in self.ctx.get("visible") or [] if v["id"] in PRODUCTS]
        open_id = (self.ctx.get("product") or {}).get("id")

        if not low or DEICTIC.match(re.sub(r"^(the )?(product|item) ", "", low)):
            pid = open_id or self.touched() or self.last_mentioned
            return (pid, "") if pid else (None, "It isn't clear which product they mean; ask them which one.")

        words = re.findall(r"[a-z0-9]+", low)
        if "last" in words and visible:
            return visible[-1], ""
        pos = next((ORDINALS[w] for w in words if w in ORDINALS), None)
        if pos is None and (m := re.search(r"(?:number|no|#)\s*(\d+)", low)):
            pos = int(m.group(1))
        if pos is not None and set(words) - STOP - set(ORDINALS) - {str(pos)} <= {
            "result",
            "listed",
            "on",
            "list",
            "in",
            "number",
            "no",
        }:
            if 1 <= pos <= len(visible):
                return visible[pos - 1], ""
            return None, f"There's no number {pos} in the list on their page."

        # a name ("the QuietMax", "sonique studio q8") anywhere in the catalog, listed products first
        for pid in sorted(PRODUCTS, key=lambda p: p not in visible):
            if any(re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", low) for a in ALIASES[pid]):
                return pid, ""

        # an attribute ("the blue one", "the cheaper one", "the earbuds") that fits exactly one listed product
        wanted = set(words) - STOP
        if wanted and visible:
            cands = [pid for pid in visible if wanted <= _attr_words(PRODUCTS[pid])]
            if len(cands) == 1:
                return cands[0], ""
            if {"cheaper", "cheapest", "cheap"} & wanted:
                pool = cands or visible
                return min(pool, key=lambda p: PRODUCTS[p]["price"]), ""
            if {"pricier", "expensive", "priciest"} & wanted:
                pool = cands or visible
                return max(pool, key=lambda p: PRODUCTS[p]["price"]), ""
            if len(cands) > 1:
                names = ", ".join(PRODUCTS[p]["name"] for p in cands[:3])
                return None, f"Several listed products fit '{ref}' ({names}); ask which one."
        return None, f"No product matches '{ref}'; ask them which one they mean."


def _attr_words(p: dict) -> set[str]:
    text = " ".join([p["name"], p["brand"], *p["colors"], *p["features"], p["cat"]])
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return (
        words
        | {w.rstrip("s") for w in words}
        | {w + "s" for w in words}
        | {"cheaper", "cheapest", "cheap", "pricier", "expensive", "priciest"}
    )
