"""Optional housekeeping for the LiveKit dashboard demo, not part of the demo itself. Off unless DEMO_PROJECT_URL is set.

At the start of a call it deletes the Builder agents earlier demos created in the demo project, so the project's agent
quota has room for a new one. Code-deployed agents are never touched. It runs in a separate hidden browser context,
never on the shared screen."""

import asyncio
import logging
import os
import re

log = logging.getLogger("cleanup")
PROJECT = os.getenv("DEMO_PROJECT_URL", "")  # the dashboard project URL; empty = no cleanup

LIST_JS = r"""() => [...document.querySelectorAll('table tbody tr')].map(r => { const td = [...r.querySelectorAll('td')].map(x => x.innerText.trim());
  const a = r.querySelector('a[href*="/agents/CA_"]'); const id = a ? a.getAttribute('href').split('/agents/')[1].split(/[/?]/)[0] : (td.join(' ').match(/CA_[A-Za-z0-9]+/) || [''])[0];
  return { id, builder: td.some(t => /^Builder$/i.test(t)) }; })"""


async def builder_agent_ids(page) -> list[str]:
    await page.goto(PROJECT + "/agents", wait_until="domcontentloaded")
    await page.locator("table tbody tr").first.wait_for(timeout=15000)
    ids = []
    for _ in range(30):  # pages of the agents table
        await asyncio.sleep(0.6)
        ids += [r["id"] for r in await page.evaluate(LIST_JS) if r["builder"] and r["id"]]
        nxt = page.get_by_role("button", name=re.compile("next page", re.I)).first
        if not await nxt.count() or await nxt.is_disabled():
            break
        await nxt.click()
    return list(dict.fromkeys(ids))


async def delete_agent(page, agent_id: str) -> bool:
    try:
        await page.goto(f"{PROJECT}/agents/{agent_id}", wait_until="domcontentloaded")
        await page.get_by_role("button", name="Agent actions").click(timeout=10000)
        await page.get_by_role("menuitem", name=re.compile("^Delete agent", re.I)).click(timeout=5000)
        dlg = page.get_by_role("alertdialog")
        await dlg.get_by_role("button", name=re.compile("^Delete agent$", re.I)).click(timeout=5000)
        await dlg.wait_for(state="hidden", timeout=10000)
        return True
    except Exception as e:
        log.warning("delete %s: %s", agent_id, str(e)[:120])
        return False


async def clean(context, trace=None) -> int:
    """Delete every Builder agent in the demo project, from a separate browser context with the same login (the shared
    context redirects new tabs into the shared one). Returns how many."""
    if not PROJECT:
        return 0
    ctx2 = await context.browser.new_context(
        storage_state=await context.storage_state(), viewport={"width": 1400, "height": 900}
    )
    page = await ctx2.new_page()
    try:
        ids = await builder_agent_ids(page)  # only agents that exist NOW: never the one this demo is about to create
        n = 0
        for i in ids:
            n += await delete_agent(page, i)
        if trace:
            trace("cleanup", found=len(ids), deleted=n)
        return n
    except Exception as e:
        if trace:
            trace("cleanup_error", error=str(e)[:160])
        return 0
    finally:
        await ctx2.close()
