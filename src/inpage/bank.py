"""The bank account page Kai explains: its data, prompt and greeting from knowledge/bank/ (BANK_KNOWLEDGE to swap in
another bank), and what the customer's page shows now (the latest page_context snapshot) as a short note.

harborline_account.json is the page's data: the page's data.js is `window.HARBOR_DATA = <this JSON>;`. To refresh the
page from it, from the page folder:
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));open('data.js','w').write('window.HARBOR_DATA = '+json.dumps(d,ensure_ascii=False)+';\\n')" <repo>/knowledge/bank/harborline_account.json
"""

import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE = os.getenv("BANK_KNOWLEDGE", os.path.join(ROOT, "knowledge", "bank"))
RECENT_TOUCH_S = 15  # a click on a row counts as "this one" for this long
DEICTIC = re.compile(
    r"^(it|this|that|this one|that one|the one|this charge|that charge|this transaction|that transaction)$"
)


def _load(name: str) -> str:
    with open(os.path.join(KNOWLEDGE, name)) as f:
        return f.read()


DATA: dict = json.loads(_load(next(n for n in sorted(os.listdir(KNOWLEDGE)) if n.endswith("_account.json"))))
TX: dict[str, dict] = {t["id"]: t for t in DATA["transactions"]}


def money(n: float | None, sign: bool = False) -> str:
    if n is None:
        return "-"
    s = f"${abs(n):,.2f}"
    return f"-{s}" if n < 0 else (f"+{s}" if sign and n > 0 else s)


def tx_line(t: dict) -> str:
    parts = [
        t["id"],
        f"{t['date']} {t['time']}",
        t["merchant"],
        money(t["amount"], sign=True),
        t["status"],
        t["category"],
        DATA["types"].get(t["type"], t["type"]),
        f"balance after {money(t['balance_after'])}" if "balance_after" in t else "not in balance yet",
    ]
    if t.get("waived"):
        parts.append(f"fee {money(t['waived'])} waived")
    if f := t.get("foreign"):
        parts.append(f"original {f['local']} at {f['rate']}")
    if t.get("flag"):
        parts.append("flag: " + t["flag"].replace("_", " "))
    if t.get("related"):
        parts.append("related: " + ", ".join(t["related"]))
    if t.get("note"):
        parts.append(t["note"])
    return " | ".join(parts)


def account_text() -> str:
    d, a = DATA, DATA["account"]
    out = [
        f"Customer: {d['customer']['name']}. Account: {a['product']} {a['mask']}. Debit card: {a['card']}. "
        f"Linked savings: {a['linked_savings']}. Today: {d['as_of_label']}.",
        f"Available balance {money(a['available_balance'])}; current (posted) balance {money(a['current_balance'])}; "
        f"pending {money(a['pending_total'])} across {a['pending_count']} transactions.",
        "\n## Transactions, last 30 days, newest first",
        "Format: id | date time | merchant | amount | status | category | type | running balance | details",
        *[tx_line(t) for t in d["transactions"]],
        "\n## Monthly maintenance fee status",
        *[f"{k.capitalize()}: {v}" for k, v in d["maintenance_status"].items()],
        "\n## Statements",
        *[
            f"{s['period']} ({s['dates']}): opening {money(s['opening'])}, closing "
            f"{'in progress' if s['closing'] is None else money(s['closing'])}, deposits {money(s['deposits'])}, "
            f"fees {money(s['fees'])}. {s['note']}"
            for s in d["statements"]
        ],
        "\n## Fees & limits tab (section ids in brackets)",
    ]
    for r in d["fee_rules"]:
        out.append(f"### {r['title']} [{r['id']}]: {r['fee']}")
        out += [f"- {line}" for line in r["lines"]]
    out.append("\n## Alerts tab (ids in brackets; demo switches, nothing is sent)")
    out += [
        f"{x['label']} [{x['id']}]: {x['help']}; {'on' if x['on'] else 'off'} at page load"
        + (f", amount {money(x['threshold'])}" if x["threshold"] is not None else ", no amount")
        for x in d["alerts"]
    ]
    return "\n".join(out)


def prompt() -> str:
    return (
        _load("kai_prompt.md")
        .replace("{bank}", DATA["bank"])
        .replace("{assistant}", DATA["assistant"])
        .replace("{account}", account_text())
    )


def greeting() -> str:
    g = _load("greeting.md").strip()
    for k, v in (
        ("{bank}", DATA["bank"]),
        ("{assistant}", DATA["assistant"]),
        ("{customer}", DATA["customer"]["name"].split()[0]),
    ):
        g = g.replace(k, v)
    return g


class BankPage:
    def __init__(self):
        self.ctx: dict = {}
        self.at = 0.0  # when the snapshot arrived (monotonic)

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
        return json.dumps([c, li and li["id"]], sort_keys=True)

    def touched(self) -> str | None:
        """The transaction the customer clicked in the last few seconds."""
        li = self.ctx.get("last_interaction")
        if not li:
            return None
        age = li.get("ms_ago", 0) / 1000 + time.monotonic() - self.at
        return li["id"] if age < RECENT_TOUCH_S and li["id"] in TX else None

    def resolve(self, ref: str) -> str:
        """A transaction id for "this one" / "it": the open details, then a row just clicked, then the one highlighted
        row. Anything else goes to the page as said (an id, or words it matches against merchants)."""
        low = (ref or "").lower().strip(" .?!")
        if low and not DEICTIC.match(low):
            return ref
        hl = [h for h in self.ctx.get("highlighted") or [] if h in TX]
        pick = (self.ctx.get("open_transaction") or {}).get("id") or self.touched() or (hl[0] if len(hl) == 1 else None)
        return pick or ref

    def note(self) -> str:
        c = self.ctx
        if not c:
            return "<page_now>The page hasn't reported yet.</page_now>"
        lines = [f"Tab: {c.get('tab')}."]
        if c.get("tab") == "activity":
            f = c.get("filters") or {}
            if f:
                rows = "; ".join(
                    f"{v['id']} {v['date']} {v['merchant']} {money(v['amount'], True)} {v['status']}"
                    for v in c.get("visible") or []
                )
                lines.append(
                    "Filters: " + ", ".join(f"{k} {v}" for k, v in f.items()) + f". Showing {c.get('shown')} of "
                    f"{c.get('total')}: {rows or 'nothing matches'}."
                )
            else:
                lines.append(f"No filters: all {c.get('shown')} transactions from the last 30 days are listed.")
        if o := c.get("open_transaction"):
            lines.append(
                f"Details open: {o['merchant']} {money(o['amount'], True)} on {o['date']} ({o['status']}) [{o['id']}]"
                + (", with the how-to-dispute panel." if o.get("dispute_panel") else ".")
            )
        if h := c.get("highlighted"):
            lines.append("Highlighted: " + ", ".join(h) + ".")
        for k, v in (c.get("section_status") or {}).items():
            lines.append(f"The highlighted {k} section's status box says: {v}")
        if al := c.get("alerts"):
            lines.append(
                "Alerts: "
                + "; ".join(
                    f"{k} {'on' if v.get('on') else 'off'}"
                    + (f" at {money(v['threshold'])}" if "threshold" in v else "")
                    for k, v in al.items()
                )
                + "."
            )
        if t := self.touched():
            tx = TX[t]
            lines.append(f"Customer just clicked: {tx['merchant']} {money(tx['amount'], True)} on {tx['date']} [{t}].")
        return "<page_now>\n" + "\n".join(lines) + "\n</page_now>"
