"""What the shopper's page shows (the latest page_context snapshot), as a short note for the model, and which product
"this one", "the second one" or "the blue one" means."""

import json
import re
import time

from .catalog import Catalog

RECENT_TOUCH_S = 10  # a click or hover counts as "this one" for this long
SPOKEN_FOR_S = 30  # "the second one" means the second product the assistant just named, for this long
HEARD_FOR_S = 15  # the shopper's last words count for the tool call that follows, for this long
# a single position reference in what the shopper said: "the second one", "the last one", "the other one"
# a price ceiling in what the shopper said: "under 300 dollars", "below $1,000", "less than 50 bucks"
SAID_MAX_PRICE = re.compile(r"\b(?:under|below|less than|up to|max(?:imum)?|no more than)\s+\$?\s?(\d[\d,]*(?:\.\d+)?)")
SAID_POSITION = re.compile(r"\b(first|second|third|fourth|fifth|sixth|last|other)\s+(one|item|product)\b")
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
# other words a position reference may carry ("the second one you mentioned", "number 2 on the list")
POSITION_WORDS = {
    "result",
    "listed",
    "on",
    "list",
    "in",
    "number",
    "no",
    "of",
    "you",
    "mentioned",
    "said",
    "named",
    "just",
}


def _money(n) -> str:
    return f"${n:,.2f}"


class PageState:
    def __init__(self, catalog: Catalog):
        self.cat = catalog
        self.ctx: dict = {}
        self.at = 0.0  # when the snapshot arrived (monotonic)
        self.last_mentioned: str | None = None  # the last product the assistant named
        self.spoken: list[str] = []  # the products the assistant named in its latest reply, in order (when 2 or more)
        self.spoken_at = 0.0
        self.spoken_route = None  # the page route when he said them
        self.heard, self.heard_at = "", -1e9  # the shopper's latest words

    def kai_said(self, text: str):
        """Note the products the assistant named in a reply: positions refer to these while the shopper stays on that page."""
        names = list(dict.fromkeys(self.cat.mentioned(text)))
        if names:
            self.last_mentioned = names[-1]
        self.spoken = names if len(names) >= 2 else []
        self.spoken_at, self.spoken_route = time.monotonic(), self.ctx.get("route")

    def shopper_said(self, text: str):
        self.heard, self.heard_at = text, time.monotonic()

    def position_heard(self) -> str | None:
        """The product a position the shopper just said ("open the second one") points to, from their own words."""
        if time.monotonic() - self.heard_at > HEARD_FOR_S:
            return None
        m = SAID_POSITION.search(self.heard.lower())
        return self.resolve(f"the {m.group(1)} one")[0] if m else None

    def max_price_heard(self) -> float | None:
        """A price ceiling the shopper just said ("under 300 dollars"), for a search that left it out."""
        if time.monotonic() - self.heard_at > HEARD_FOR_S:
            return None
        m = SAID_MAX_PRICE.search(self.heard.lower())
        return float(m.group(1).replace(",", "")) if m else None

    def color_heard(self, pid: str) -> str | None:
        """The one color of this product the shopper just named ("a spool of black PLA"), for a call that left it out."""
        if time.monotonic() - self.heard_at > HEARD_FOR_S:
            return None
        said = set(re.findall(r"[a-z]+", self.heard.lower()))
        hits = [c for c in self.cat.colors(self.cat.products[pid]) if set(re.findall(r"[a-z]+", c.lower())) & said]
        return hits[0] if len(hits) == 1 else None

    def spoken_list(self) -> list[str]:
        fresh = time.monotonic() - self.spoken_at < SPOKEN_FOR_S and self.ctx.get("route") == self.spoken_route
        return self.spoken if fresh else []

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
        return li["id"] if age < RECENT_TOUCH_S and li["id"] in self.cat.products else None

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
                f"Shopper just {'clicked' if li['type'] == 'click' else 'pointed at'}: {self.cat.products[t]['name']} [{t}]."
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
        Order: an id or name; "this/that/it": the open product, then the one just touched, then the last one the
        named; "the second one": the second product the assistant just named out loud (2 or more, within 30 s, same page), else
        number 2 in the list on screen; "the other one": the other of the two it just named; "the blue one": the one
        listed product with that color."""
        ref = (ref or "").strip()
        low = ref.lower().strip(" .?!")
        if ref in self.cat.products:
            return ref, ""
        visible = [v["id"] for v in self.ctx.get("visible") or [] if v["id"] in self.cat.products]
        open_id = (self.ctx.get("product") or {}).get("id")

        if not low or DEICTIC.match(re.sub(r"^(the )?(product|item) ", "", low)):
            pid = open_id or self.touched() or self.last_mentioned
            return (pid, "") if pid else (None, "It isn't clear which product they mean; ask them which one.")

        words = re.findall(r"[a-z0-9]+", low)
        spoken = self.spoken_list()
        if "other" in words and set(words) - STOP - POSITION_WORDS <= {"other"}:
            current = open_id or self.touched()
            pair = spoken if len(spoken) == 2 else []
            if current in pair:
                return pair[1 - pair.index(current)], ""
            return None, "It isn't clear which one 'the other one' is; ask them."
        pos = -1 if "last" in words else next((ORDINALS[w] for w in words if w in ORDINALS), None)
        if pos is None and (m := re.search(r"(?:number|no|#)\s*(\d+)", low)):
            pos = int(m.group(1))
        if pos is not None and set(words) - STOP - set(ORDINALS) - POSITION_WORDS - {str(pos), "last"} == set():
            order, where = (spoken, "the products you just named") if spoken else (visible, "the list on their page")
            i = len(order) - 1 if pos == -1 else pos - 1
            if order and 0 <= i < len(order):
                return order[i], ""
            return None, f"There's no number {pos} in {where}."

        # a product's name, preferring one that's listed on the page
        if named := self.cat.mentioned(low):
            return next((pid for pid in named if pid in visible), named[0]), ""

        # an attribute ("the blue one", "the cheaper one", "the earbuds") that fits exactly one listed product
        wanted = set(words) - STOP
        if wanted and visible:
            cands = [pid for pid in visible if wanted <= self.cat.attr_words(pid)]
            if len(cands) == 1:
                return cands[0], ""
            if {"cheaper", "cheapest", "cheap"} & wanted:
                pool = cands or visible
                return min(pool, key=lambda p: self.cat.products[p]["price"]), ""
            if {"pricier", "expensive", "priciest"} & wanted:
                pool = cands or visible
                return max(pool, key=lambda p: self.cat.products[p]["price"]), ""
            if len(cands) > 1:
                names = ", ".join(self.cat.products[p]["name"] for p in cands[:3])
                return None, f"Several listed products fit '{ref}' ({names}); ask which one."
        return None, f"No product matches '{ref}'; ask them which one they mean."
