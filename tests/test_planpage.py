from demo_agent.planpage import GREETING, NO_PAGE, instructions, section_ids, section_title, viewing

PAGE = """Northwind Health Advantage Plus (HMO-POS) — 2027 Summary of Benefits

#summary Plan summary
- Monthly plan premium: $0 (You must continue to pay your Medicare Part B premium.)

#urgent-emergency Urgent and emergency care
- Emergency room: $115 per visit (Anywhere in the US.)
"""


def test_section_ids_come_from_header_lines():
    assert section_ids(PAGE) == ["summary", "urgent-emergency"]


def test_instructions_hold_the_page_and_the_greeting():
    text = instructions(PAGE)
    assert "#urgent-emergency Urgent and emergency care" in text
    assert GREETING in text


def test_instructions_without_a_page():
    assert NO_PAGE in instructions("  ")
    assert section_ids("") == []


def test_section_title():
    assert section_title(PAGE, "urgent-emergency") == "the Urgent and emergency care section"
    assert section_title(PAGE, "nope") == "another section"


def test_instructions_say_where_the_customer_is_looking():
    assert viewing(PAGE, "summary") in instructions(PAGE, "summary")
    assert "the Plan summary section (#summary)" in viewing(PAGE, "summary")
