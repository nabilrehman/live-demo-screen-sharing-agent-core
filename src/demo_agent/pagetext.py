"""Rich, compact DOM text of the shared browser for the voice LLM: headings, dialog, selected tabs,
toggles/checkboxes with ON/OFF, inputs/selects with values, field labels, visible buttons and short body text."""

JS = r"""(maxChars) => {
  const vis = e => { if (!e || !e.getBoundingClientRect) return false; const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom < 0 || r.top > innerHeight * 1.5) return false;
    const s = getComputedStyle(e); return s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const lab = e => { let t = e.getAttribute('aria-label') || '';
    const lb = e.getAttribute('aria-labelledby'); if (!t && lb) t = lb.split(' ').map(i => (document.getElementById(i)||{}).innerText||'').join(' ');
    if (!t && e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) t = l.innerText; }
    if (!t) { const l = e.closest('label'); if (l) t = l.innerText; }
    if (!t) { let p = e.parentElement; for (let i = 0; i < 4 && p && !t; i++, p = p.parentElement) { const x = clean(p.innerText); if (x && x.length < 120) t = x; } }
    return clean(t).slice(0, 70); };
  const dlg = [...document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open]')].filter(vis).pop();
  const root = dlg || document.querySelector('main') || document.body;
  const out = [`PAGE: ${document.title} (${location.pathname})`];
  if (dlg) out.push('OPEN DIALOG: ' + clean((dlg.querySelector('h1,h2,h3,[class*=title]')||dlg).innerText).slice(0, 80));
  const hs = [...root.querySelectorAll('h1,h2,h3,h4,legend')].filter(vis).map(e => clean(e.innerText).slice(0, 60)).filter(Boolean);
  if (hs.length) out.push('HEADINGS: ' + [...new Set(hs)].slice(0, 25).join(' | '));
  const tabs = [...document.querySelectorAll('[role=tab]')].filter(vis).map(e => (e.getAttribute('aria-selected') === 'true' ? '[' + clean(e.innerText) + ']' : clean(e.innerText))).filter(Boolean);
  if (tabs.length) out.push('TABS ([]=selected): ' + tabs.slice(0, 15).join(' | '));
  const tg = [...root.querySelectorAll('[role=switch],input[type=checkbox],input[type=radio],[role=checkbox],[role=radio]')].filter(e => vis(e) || vis(e.parentElement)).map(e => {
    const on = e.getAttribute('aria-checked') ?? e.getAttribute('data-state') ?? (e.checked ? 'true' : 'false');
    return `${lab(e) || '(unlabeled)'}=${/true|checked|on/.test(on) ? 'ON' : 'OFF'}`; });
  if (tg.length) out.push('TOGGLES: ' + [...new Set(tg)].slice(0, 30).join(' | '));
  const ins = [...root.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea,select,[role=combobox]')].filter(vis).map(e => {
    let v = e.tagName === 'SELECT' ? (e.selectedOptions[0]||{}).text : (e.value ?? '') || clean(e.innerText);
    const l = lab(e) || e.placeholder || e.name; return l ? `${l}: "${clean(v).slice(0, 60)}"` : ''; }).filter(Boolean);
  if (ins.length) out.push('FIELDS: ' + ins.slice(0, 25).join(' | '));
  const btns = [...new Set([...root.querySelectorAll('button,a[role=button],[role=menuitem],[role=option]')].filter(e => vis(e) && !e.closest('nav,aside,[data-sidebar]'))
    .map(e => clean(e.getAttribute('aria-label') || e.innerText).slice(0, 40)).filter(x => x.length > 1))];
  if (btns.length) out.push('BUTTONS: ' + btns.slice(0, 40).join(' | '));
  const nav = [...new Set([...document.querySelectorAll('nav a,aside a,[data-sidebar] a,[data-sidebar] button')].filter(vis).map(e => clean(e.innerText).slice(0, 30)).filter(Boolean))];
  if (nav.length) out.push('SIDEBAR: ' + nav.slice(0, 20).join(' | '));
  let s = out.join('\n'); const body = clean(root.innerText);
  const room = maxChars - s.length - 20; if (room > 200) s += '\nVISIBLE TEXT: ' + body.slice(0, room);
  return s.slice(0, maxChars);
}"""


async def page_text(page, max_chars: int = 2400) -> str:
    try:
        return await page.evaluate(JS, max_chars)
    except Exception as e:
        return f"(page text failed: {e})"
