"""Kai in the bank page (src/inpage/bank.py): the account data adds up, the prompt is complete, and the page note and
"this one" resolution work."""

import itertools
import time

from inpage.bank import DATA, TX, BankPage, greeting, prompt

ACTIVITY = {
    "seq": 4,
    "tab": "activity",
    "balances": {"available": 1405.35, "current": 1450.72, "pending": -45.37, "pending_count": 2},
    "filters": {"category": "Restaurants", "date_range": "this-month"},
    "shown": 2,
    "total": 29,
    "visible": [
        {"id": "t1015-coffee-b", "date": "2026-10-15", "merchant": "Driftwood Coffee Co.", "amount": -6.75, "status": "pending", "category": "Restaurants"},
        {"id": "t1011-noodle", "date": "2026-10-11", "merchant": "Noodle Harbor", "amount": -27.8, "status": "posted", "category": "Restaurants"},
    ],
    "alerts": {"low_balance": {"on": True, "threshold": 100}, "large_purchase": {"on": False, "threshold": 250}, "deposits": {"on": True}},
}  # fmt: skip


def test_running_balances_add_up():
    txs = list(reversed(DATA["transactions"]))  # oldest first
    posted = [t for t in txs if t["status"] == "posted"]
    for prev, t in itertools.pairwise(posted):
        assert round(prev["balance_after"] + t["amount"], 2) == t["balance_after"], t["id"]
    a = DATA["account"]
    assert posted[-1]["balance_after"] == a["current_balance"]
    pending = [t for t in txs if t["status"] == "pending"]
    assert round(sum(t["amount"] for t in pending), 2) == a["pending_total"] and len(pending) == a["pending_count"]
    assert round(a["current_balance"] + a["pending_total"], 2) == a["available_balance"]


def test_fee_rows_follow_the_rules():
    od, cause = TX["t1001-od-fee"], TX["t1001-meridian"]
    assert od["amount"] == -12.00 and cause["balance_after"] < -50  # overdrawn by more than $50: the fee applies
    lisbon, fx = TX["t0923-lisbon"], TX["t0923-fx-fee"]
    assert round(lisbon["amount"] * 0.03, 2) == fx["amount"]  # 3% foreign transaction fee
    assert TX["t0927-atm-fee"]["amount"] == -3.00
    a, b = TX["t1015-coffee-a"], TX["t1015-coffee-b"]
    assert a["amount"] == b["amount"] and {a["status"], b["status"]} == {"posted", "pending"}
    assert TX["t0930-maint"]["waived"] == 5.00 and TX["t0930-maint"]["amount"] == 0
    assert all(r in {f["id"] for f in DATA["fee_rules"]} for r in (t.get("rule") for t in TX.values()) if r)
    assert all(rel in TX for t in TX.values() for rel in t.get("related", []))


def test_prompt_and_greeting_complete():
    p = prompt()
    assert "{" not in p.split("# The account page")[0] and "{account}" not in p
    assert "t1001-od-fee" in p and "3.80% APY" in p and "Alex Rivera" in p
    g = greeting()
    assert "AI assistant" in g and "Alex" in g and "{" not in g


def test_note_lists_filtered_rows_and_alerts():
    p = BankPage()
    p.update(ACTIVITY)
    n = p.note()
    assert "Filters: category Restaurants, date_range this-month. Showing 2 of 29" in n
    assert "t1015-coffee-b 2026-10-15 Driftwood Coffee Co. -$6.75 pending" in n
    assert "low_balance on at $100.00" in n and "deposits on" in n
    p.update({**ACTIVITY, "seq": 5, "filters": {}, "shown": 29})
    assert "No filters: all 29 transactions" in p.note()


def test_this_one_and_signature():
    p = BankPage()
    p.update(ACTIVITY)
    assert p.resolve("the coffee") == "the coffee"  # words go to the page as said
    assert p.resolve("this one") == "this one"  # nothing to point at: the page will ask
    p.update({**ACTIVITY, "seq": 6, "highlighted": ["t1001-od-fee"]})
    assert p.resolve("it") == "t1001-od-fee"
    p.update({**ACTIVITY, "seq": 7, "last_interaction": {"id": "t1011-noodle", "type": "click", "ms_ago": 300}})
    assert p.resolve("that charge") == "t1011-noodle"
    p.at = time.monotonic() - 60  # an old click no longer counts
    assert p.resolve("that charge") == "that charge"
    p.update({**ACTIVITY, "seq": 8, "open_transaction": {"id": "t0923-lisbon"}})
    assert p.resolve("this one") == "t0923-lisbon"
    sig = p.signature()
    p.update({**ACTIVITY, "seq": 9, "open_transaction": {"id": "t0923-lisbon"}})
    assert p.signature() == sig
    assert not p.update({**ACTIVITY, "seq": 1})
