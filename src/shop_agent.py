"""A voice shopping guide inside the shopper's own web page. No shared browser: the page sends its state up as a
page_context text stream and registers RPC methods that the agent's tools call to act on it. The store, its products and
the assistant's name all come from the store's catalog (CATALOG_URL, see inpage/catalog.py).

  uv run src/shop_agent.py dev        (AGENT_NAME, BRAIN=gemini-live|grok, WORKER_PORT; see brain.py for the models)
"""

import asyncio
import json
import logging
import os
import time
from typing import Literal

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))

from livekit import rtc
from livekit.agents import Agent, AgentServer, JobContext, ToolError, cli, function_tool

from demo_agent.brain import BRAIN, IS_GEMINI, MODEL, make_session
from inpage.catalog import Catalog, load
from inpage.page import DEICTIC, PageState

log = logging.getLogger("shop")
RPC_TIMEOUT_S = 3.0
CONFIRM_OVER = 1000.0  # confirm cart lines above this many dollars
RETRYABLE = {
    rtc.RpcError.ErrorCode.CONNECTION_TIMEOUT,
    rtc.RpcError.ErrorCode.RESPONSE_TIMEOUT,
    rtc.RpcError.ErrorCode.SEND_FAILED,
}
Sort = Literal["best", "price-asc", "price-desc", "rating"]


class ShopGuide(Agent):
    def __init__(self, room: rtc.Room, page: PageState, catalog: Catalog):
        self.base_prompt = catalog.prompt()
        super().__init__(instructions=self.base_prompt)
        self.room, self.page, self.catalog, self.products = room, page, catalog, catalog.products
        self.acting = 0  # page actions in flight; their results carry the new page state
        self.posted = ""  # signature of the page state the model last got
        self.changed = asyncio.Event()

    # ---------- the page ----------
    def shopper(self) -> str | None:
        for p in self.room.remote_participants.values():
            if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                return p.identity
        return None

    async def rpc(self, method: str, **args) -> str:
        """Call one of the page's methods; it returns the new page state. A timeout is retried once."""
        dest = self.shopper()
        if dest is None:
            raise ToolError("The shopper's page isn't connected.")
        payload = json.dumps({k: v for k, v in args.items() if v not in (None, "", [], False)})
        self.acting += 1
        try:
            for attempt in (1, 2):
                t = time.perf_counter()
                try:
                    resp = await self.room.local_participant.perform_rpc(
                        destination_identity=dest, method=method, payload=payload, response_timeout=RPC_TIMEOUT_S
                    )
                    log.info("rpc %s %s ok %.0f ms", method, payload, (time.perf_counter() - t) * 1000)
                    break
                except rtc.RpcError as e:
                    log.info("rpc %s %s error %s %s", method, payload, e.code, e.message)
                    if e.code in RETRYABLE and attempt == 1:
                        continue
                    if e.code in RETRYABLE or e.code >= 1400:
                        raise ToolError("Their page didn't respond. Say 'one sec' and try once more.") from e
                    raise ToolError(e.message) from e
        finally:
            self.acting -= 1
        self.page.update_json(resp)
        self.posted = self.page.signature()
        return self.page.note()

    async def post_page(self):
        """Tell the model what the page shows now. Gemini: one context item (re-sending the instructions would
        restart its turn); Inference realtime: the instructions plus the page note."""
        self.posted = self.page.signature()
        if IS_GEMINI:
            ctx = self.chat_ctx.copy()
            ctx.add_message(role="user", content=self.page.note())
            await self.update_chat_ctx(ctx)
        else:
            await self.update_instructions(
                self.base_prompt + "\n\n# What the shopper's page shows now\n" + self.page.note()
            )

    async def feed(self):
        """Keep the model's view of the page current between turns (at most every 0.6 s)."""
        while True:
            await self.changed.wait()
            self.changed.clear()
            await asyncio.sleep(0.6)
            if self.acting or self.page.signature() == self.posted:
                continue
            try:
                await self.post_page()
            except Exception as e:
                log.warning("page note: %s", e)

    def pick(self, product: str) -> str:
        """The product the shopper means. When they just named a position ("open the second one"), their words win
        over the model's choice: models tend to count on screen, not in the order the assistant said the products."""
        pid, why = self.page.resolve(product)
        heard = self.page.position_heard()
        if heard and heard != pid:
            log.info("position from the shopper's words: %s -> %s", product, heard)
            pid = heard
        if pid is None:
            raise ToolError(why)
        return pid

    def cart_line(self, item: str) -> dict:
        lines = (self.page.ctx.get("cart") or {}).get("lines") or []
        if not lines:
            raise ToolError("Their cart is empty.")
        for l in lines:
            if item == l["line_id"]:
                return l
        if len(lines) == 1 and (not item or DEICTIC.match(item.lower().strip(" .?!"))):
            return lines[0]
        pid = self.pick(item)
        same = [l for l in lines if l["id"] == pid]
        if not same:
            raise ToolError(f"{self.products[pid]['name']} isn't in their cart.")
        return same[0]

    def unit_price(self, pid: str, option: str | None) -> float:
        open_p = self.page.ctx.get("product") or {}
        if not option and open_p.get("id") == pid:  # what's selected on its page
            option = (open_p.get("variant") or {}).get("option")
        return self.catalog.price_of(pid, option)

    # ---------- tools ----------
    @function_tool
    async def search_products(
        self,
        query: str,
        max_price: float | None = None,
        min_price: float | None = None,
        brand: str | None = None,
        feature: str | None = None,
        attribute: str | None = None,
        on_sale: bool = False,
        sort: Sort = "best",
    ) -> str:
        """Search the store and show the results on the shopper's page.

        Args:
            query: What to look for, in the shopper's terms (a product type, a model, a need).
            max_price: Only show products up to this price in dollars ("under 300" -> 300).
            min_price: Only show products from this price in dollars.
            brand: Only this brand.
            feature: Only products with this feature (one of the catalog's features).
            attribute: Only products with this attribute, as "name: value" from the catalog's filters.
            on_sale: Only products on sale.
            sort: Order of the results.
        """
        if max_price is None:  # the shopper's own "under $300" still applies
            max_price = self.page.max_price_heard()
        note = await self.rpc(
            "search",
            query=query,
            price_max=max_price,
            price_min=min_price,
            brand=brand,
            feature=feature,
            attribute=attribute,
            deals=on_sale,
            sort=sort if sort != "best" else None,
        )
        return "Done; their page shows the results.\n" + note

    @function_tool
    async def filter_results(
        self,
        max_price: float | None = None,
        min_price: float | None = None,
        brand: str | None = None,
        feature: str | None = None,
        attribute: str | None = None,
        category: str | None = None,
        four_stars_and_up: bool = False,
        on_sale: bool = False,
    ) -> str:
        """Narrow the results the shopper is looking at (adds to the filters already on).

        Args:
            max_price: Up to this price in dollars.
            min_price: From this price in dollars.
            brand: Only this brand.
            feature: Only products with this feature (one of the catalog's features).
            attribute: Only products with this attribute, as "name: value" from the catalog's filters.
            category: A category id from the catalog.
            four_stars_and_up: Only products rated 4 stars and up.
            on_sale: Only products on sale.
        """
        note = await self.rpc(
            "apply_filter",
            price_max=max_price,
            price_min=min_price,
            brand=brand,
            feature=feature,
            attribute=attribute,
            category=category,
            rating=4 if four_stars_and_up else None,
            deals=on_sale,
        )
        return "Done.\n" + note

    @function_tool
    async def clear_filters(self) -> str:
        """Remove all filters from the results (keeps the search and category)."""
        return "Done.\n" + await self.rpc("clear_filters")

    @function_tool
    async def sort_results(self, by: Sort) -> str:
        """Sort the results on the shopper's page.

        Args:
            by: best (best match), price-asc (cheapest first), price-desc (priciest first) or rating (top rated).
        """
        return "Done.\n" + await self.rpc("sort", by=by)

    @function_tool
    async def open_product(self, product: str, color: str | None = None, option: str | None = None) -> str:
        """Open a product's page for the shopper.

        Args:
            product: The product id, or the shopper's words for it ("the second one", a model name, "this one").
            color: A color to show it in, if they asked for one.
            option: A size, bundle or configuration from the product's options, if they asked for one.
        """
        pid = self.pick(product)
        return "Done; it's open.\n" + await self.rpc("open_product", id=pid, color=color, option=option)

    @function_tool
    async def choose_variant(
        self, color: str | None = None, option: str | None = None, product: str = "this one"
    ) -> str:
        """Select a color, size or configuration on a product page.

        Args:
            color: The exact color name from the catalog.
            option: The exact option name from the catalog (size, bundle or configuration).
            product: Which product; defaults to the one open.
        """
        if not color and not option:
            raise ToolError("Say which color or option to select.")
        pid = self.pick(product)
        color = color or (None if option else self.page.color_heard(pid))
        return "Done; selected.\n" + await self.rpc("select_variant", id=pid, color=color, option=option)

    @function_tool
    async def add_to_cart(
        self,
        product: str = "this one",
        quantity: int = 1,
        color: str | None = None,
        option: str | None = None,
        confirmed: bool = False,
    ) -> str:
        """Add a product to the shopper's cart. Without a color or option, it adds what's selected on its page: call it
        rather than asking which option they want. Works for any product by id; there's no need to open it first.

        Args:
            product: The product id, or the shopper's words for it; defaults to the one open.
            quantity: How many.
            color: A color, if they named one.
            option: A size or configuration, if they named one.
            confirmed: True only after the shopper said yes to your confirmation question.
        """
        pid = self.pick(product)
        p = self.products[pid]
        color = color or self.page.color_heard(pid)
        total = self.unit_price(pid, option) * quantity
        if not confirmed and (quantity > 1 or total > CONFIRM_OVER):
            return (
                f"Not added yet. Ask them to confirm: {quantity} x {p['name']} for ${total:,.2f}. "
                "If they say yes, call add_to_cart again with confirmed=true."
            )
        note = await self.rpc("add_to_cart", id=pid, qty=quantity, color=color, option=option)
        return "Added; their cart badge updated.\n" + note

    @function_tool
    async def set_quantity(self, quantity: int, item: str = "it", confirmed: bool = False) -> str:
        """Change how many of a cart item the shopper wants ("make it two"). 0 removes it.

        Args:
            quantity: The new quantity.
            item: The product id, line id or the shopper's words for the cart item; defaults to the only item.
            confirmed: True only after the shopper said yes to your confirmation question.
        """
        line = self.cart_line(item)
        if quantity <= 0:
            return "Removed.\n" + await self.rpc("remove_from_cart", line_id=line["line_id"])
        if not confirmed and line["price"] * quantity > CONFIRM_OVER:
            return (
                f"Not changed yet. Ask them to confirm {quantity} x {line['name']} for ${line['price'] * quantity:,.2f}. "
                "If they say yes, call set_quantity again with confirmed=true."
            )
        return "Done.\n" + await self.rpc("update_qty", line_id=line["line_id"], qty=quantity)

    @function_tool
    async def remove_from_cart(self, item: str) -> str:
        """Remove an item from the shopper's cart.

        Args:
            item: The product id, line id or the shopper's words for the cart item.
        """
        line = self.cart_line(item)
        return "Removed.\n" + await self.rpc("remove_from_cart", line_id=line["line_id"])

    @function_tool
    async def show_cart(self) -> str:
        """Open the shopper's cart page."""
        return "Done; their cart is open.\n" + await self.rpc("show_cart")

    @function_tool
    async def compare_products(self, products: list[str]) -> str:
        """Open a side-by-side comparison of 2 to 4 products on the shopper's page.

        Args:
            products: Product ids, or the shopper's words for them ("the first two" -> ["first", "second"]).
        """
        ids = []
        for x in products:  # several positions at once: the model's list as given
            pid, why = self.page.resolve(x)
            if pid is None:
                raise ToolError(why)
            ids.append(pid)
        ids = list(dict.fromkeys(ids))
        return "Done; the comparison is open.\n" + await self.rpc("compare", ids=ids)

    @function_tool
    async def highlight(self, product: str) -> str:
        """Point a product out on the shopper's page (scrolls to it and rings it).

        Args:
            product: The product id, or the shopper's words for it.
        """
        return "Done.\n" + await self.rpc("highlight", id=self.pick(product))

    @function_tool
    async def go_to_checkout(self) -> str:
        """Open the checkout page. It's a demo store: checkout is disabled and no payment is ever taken."""
        return "Done; the checkout page says checkout is disabled in this demo.\n" + await self.rpc("go_to_checkout")


server = AgentServer(port=int(os.getenv("WORKER_PORT", 8095)))


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "live-demo-shop"))
async def entrypoint(ctx: JobContext):
    catalog = await load()
    log.info("catalog: %d products from %s", len(catalog.products), catalog.source)
    page = PageState(catalog)
    session = make_session(language=catalog.store.get("language"))
    guide = ShopGuide(ctx.room, page, catalog)

    def on_page(reader: rtc.TextStreamReader, _from: str):
        async def read():
            if page.update_json(await reader.read_all()):
                guide.changed.set()

        asyncio.create_task(read())

    ctx.room.register_text_stream_handler("page_context", on_page)

    @session.on("conversation_item_added")
    def _said(ev):
        role, text = getattr(ev.item, "role", None), getattr(ev.item, "text_content", None)
        if text and role == "assistant":
            page.kai_said(text)
        elif text and role == "user":
            page.shopper_said(text)

    await ctx.connect()
    await ctx.wait_for_participant()
    log.info("call %s: brain %s (%s)", ctx.room.name, BRAIN, MODEL)
    await session.start(agent=guide, room=ctx.room)
    try:  # the page's state before the greeting, in case its first snapshot came before we listened
        await guide.rpc("get_context")
        await guide.post_page()
    except Exception as e:
        log.warning("no page context at start: %s", e)
    asyncio.create_task(guide.feed())
    session.generate_reply(instructions=catalog.greeting())


if __name__ == "__main__":
    cli.run_app(server)
