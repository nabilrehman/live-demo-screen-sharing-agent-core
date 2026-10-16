"""The page note and "which product" resolution for Kai in the store page (src/inpage)."""

import time

from inpage.catalog import Catalog, load_local
from inpage.page import PageState

CATALOG = load_local()

RESULTS = {
    "seq": 3,
    "route": "#/search?q=noise+cancelling+headphones&pmax=300",
    "page": "results",
    "visible": [
        {
            "pos": 1,
            "id": "pulsewave-quietmax",
            "name": "Pulsewave QuietMax",
            "price": 229.99,
            "rating": 4.3,
            "deal": True,
        },
        {
            "pos": 2,
            "id": "pulsewave-airbuds-2",
            "name": "Pulsewave AirBuds 2",
            "price": 129.99,
            "rating": 4.4,
            "deal": True,
        },
        {"pos": 3, "id": "auralis-pro-anc", "name": "Auralis Pro ANC", "price": 279.99, "rating": 4.7, "deal": True},
    ],
    "filters": {"q": "noise cancelling headphones", "pmax": "300"},
    "sort": "best",
    "cart": {"count": 0, "subtotal": 0, "total": 0, "lines": []},
}


def page(**extra) -> PageState:
    p = PageState(CATALOG)
    p.update({**RESULTS, **extra})
    return p


def test_positions_and_names():
    p = page()
    assert p.resolve("the second one") == ("pulsewave-airbuds-2", "")
    assert p.resolve("number 3")[0] == "auralis-pro-anc"
    assert p.resolve("the last one")[0] == "auralis-pro-anc"
    assert p.resolve("the QuietMax")[0] == "pulsewave-quietmax"
    assert p.resolve("auralis-pro-anc")[0] == "auralis-pro-anc"
    assert p.resolve("the fifth one")[0] is None


def test_attributes():
    p = page()
    assert p.resolve("the lilac one")[0] == "pulsewave-airbuds-2"
    assert p.resolve("the earbuds")[0] == "pulsewave-airbuds-2"
    assert p.resolve("the cheapest one")[0] == "pulsewave-airbuds-2"
    assert p.resolve("the black one")[0] is None  # all three come in black: ask


def test_this_one_order():
    p = page()
    assert p.resolve("this one")[0] is None
    p.last_mentioned = "auralis-pro-anc"
    assert p.resolve("that one")[0] == "auralis-pro-anc"
    p.update({**RESULTS, "seq": 4, "last_interaction": {"id": "pulsewave-quietmax", "type": "hover", "ms_ago": 500}})
    assert p.resolve("this one")[0] == "pulsewave-quietmax"
    p.at = time.monotonic() - 30  # an old touch no longer counts
    assert p.resolve("this one")[0] == "auralis-pro-anc"
    p.update({**RESULTS, "seq": 5, "page": "product", "product": {"id": "sonique-studio-q8"}})
    assert p.resolve("it")[0] == "sonique-studio-q8"


def test_stale_snapshot_ignored():
    p = page()
    assert not p.update({**RESULTS, "seq": 1, "page": "home"})
    assert p.ctx["page"] == "results"


def test_note_and_signature():
    p = page()
    note = p.note()
    assert "2. Pulsewave AirBuds 2 [pulsewave-airbuds-2] $129.99" in note and "Cart: empty." in note
    sig = p.signature()
    p.update({**RESULTS, "seq": 9})
    assert p.signature() == sig  # a new sequence number alone is no news


def test_catalog_prompt_and_mentions():
    assert len(CATALOG.products) > 40 and "{catalog}" not in CATALOG.prompt()
    assert CATALOG.mentioned("The Halo 9 Pro beats the Sonique Studio Q8 and the QuietMax.") == [
        "halo-9-pro",
        "sonique-studio-q8",
        "pulsewave-quietmax",
    ]
    assert CATALOG.mentioned("the Halo 9 or the Auralis Pro, rated 4.9") == ["halo-9", "auralis-pro-anc"]
    assert CATALOG.mentioned("the second one") == []


def test_aliases_come_from_the_names():
    cat = Catalog(
        {
            "products": [
                {"id": "a1", "name": "Bambu Lab A1 3D Printer", "brand": "Bambu Lab", "cat": "p", "price": 1},
                {"id": "a1m", "name": "Bambu Lab A1 mini 3D Printer", "brand": "Bambu Lab", "cat": "p", "price": 1},
                {"id": "p1s", "name": "Bambu Lab P1S 3D Printer", "brand": "Bambu Lab", "cat": "p", "price": 1},
                {"id": "one", "name": "Orbix One Phone", "brand": "Orbix", "cat": "x", "price": 1},
            ]
        }
    )
    assert cat.mentioned("The A1 mini has a smaller bed than the A1; the P1S is enclosed.") == ["a1m", "a1", "p1s"]
    assert cat.mentioned("the Orbix One, or the second one") == ["one"]


def test_positions_follow_what_kai_just_named():
    p = page()
    p.kai_said("I found five, including the Pulsewave QuietMax at two thirty and the Auralis Pro at two eighty.")
    assert p.resolve("the second one") == ("auralis-pro-anc", "")  # not AirBuds 2, number 2 on screen
    assert p.resolve("the first one")[0] == "pulsewave-quietmax"
    assert p.resolve("the last one you mentioned")[0] == "auralis-pro-anc"
    assert p.resolve("the third one")[0] is None  # he named two
    assert p.resolve("the blue one")[0] is None  # attributes still use the page


def test_spoken_order_expires():
    p = page()
    p.kai_said("The QuietMax or the Auralis Pro are both great.")
    p.spoken_at -= 31  # too long ago
    assert p.resolve("the second one")[0] == "pulsewave-airbuds-2"
    p.kai_said("The QuietMax or the Auralis Pro are both great.")
    p.update({**RESULTS, "seq": 7, "route": "#/search?cat=tvs"})  # the shopper went to another page
    assert p.resolve("the second one")[0] == "pulsewave-airbuds-2"
    p.update({**RESULTS, "seq": 8})
    p.kai_said("The Auralis Pro has the best noise cancelling.")  # a newer reply naming one product
    assert p.resolve("the second one")[0] == "pulsewave-airbuds-2"


def test_the_other_one():
    p = page()
    p.kai_said("The QuietMax or the Auralis Pro are both great.")
    p.update({**RESULTS, "seq": 6, "last_interaction": {"id": "auralis-pro-anc", "type": "click", "ms_ago": 200}})
    assert p.resolve("the other one")[0] == "pulsewave-quietmax"
    assert p.resolve("other one")[0] == "pulsewave-quietmax"


def test_shopper_position_words_win():
    p = page()
    p.kai_said("I'd recommend the Auralis Pro, or the Pulsewave QuietMax.")
    p.shopper_said("Open the second one.")
    assert p.position_heard() == "pulsewave-quietmax"  # whatever id the model picked
    p.shopper_said("What's the difference between the first two?")
    assert p.position_heard() is None
    p.shopper_said("Open the second one.")
    p.heard_at -= 16
    assert p.position_heard() is None


def test_price_ceiling_from_the_shoppers_words():
    p = page()
    p.shopper_said("I'm a beginner. I want a small 3D printer under $300.")
    assert p.max_price_heard() == 300
    p.shopper_said("Something below 1,000 dollars please")
    assert p.max_price_heard() == 1000
    p.shopper_said("Open the second one.")
    assert p.max_price_heard() is None


def test_color_from_the_shoppers_words():
    p = page()
    p.shopper_said("Add it with a spool of black PLA.")
    assert p.color_heard("pulsewave-airbuds-2") == "Midnight Black"
    assert p.color_heard("kestrel-monitor-x") == "Midnight Black"
    p.shopper_said("Add it to my cart.")
    assert p.color_heard("pulsewave-airbuds-2") is None


def test_price_of_with_and_without_options():
    assert CATALOG.price_of("pulsewave-quietmax") == CATALOG.products["pulsewave-quietmax"]["price"]
    with_opts = next(p for p in CATALOG.products.values() if p.get("options"))
    last = with_opts["options"]["choices"][-1]
    assert CATALOG.price_of(with_opts["id"], last["name"]) == last["price"]
    assert CATALOG.price_of(with_opts["id"], "no such option") == with_opts["options"]["choices"][0]["price"]
