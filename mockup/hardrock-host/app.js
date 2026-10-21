/* Hard Rock Host Companion (demo): the host's app. Screens are drawn from window.HRH_DATA (data.js, generated from
   data.py, the same source as the agent's knowledge). Hash routes: #/briefing, #/player/<slug>/<section>.
   Site actions for the LiveKit voice companion (window.LiveKitAgent.registerAction): open_player, show_section,
   next_player, back_to_briefing. Every "Offer" button is inert (Demo only). */
(function () {
  'use strict';
  const DATA = window.HRH_DATA;
  const B = DATA.base;
  const P = DATA.players;
  const SECTIONS = ['profile', 'comps', 'preferences', 'recommendations'];
  const LABEL = { profile: 'Profile', comps: 'Comps', preferences: 'Preferences', recommendations: 'Tonight' };
  const GAME_IMG = { delane: 'gen/baccarat-table.jpg', marchetti: 'gen/slots-high-limit.jpg', castellano: 'gen/craps.jpg', liang: 'gen/poker-room.jpg', brooks: 'gen/blackjack.jpg', bellamy: 'gen/floor-aisle.jpg' };
  const main = document.getElementById('main');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const usd = (n) => '$' + Math.abs(n).toLocaleString('en-US');
  const wl = (n) => (n === 0 ? '<span class="wl0">No rated play</span>' : n < 0 ? `<span class="wl neg">−${usd(n)}</span>` : `<span class="wl pos">+${usd(n)}</span>`);
  const k = (n) => (n >= 1000 ? '$' + (n / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 }) + 'K' : usd(n));
  const img = (path, small) => `${B}/img/${small ? path.replace(/^(gen|real)\//, '$1/s/') : path}`;
  const initials = (n) => n.split(' ').map((w) => w[0]).join('').slice(0, 2);
  const tier = (t) => `<span class="tier tier-${t.toLowerCase()}">${t === 'X' ? 'X Card' : esc(t)}</span>`;
  const tablet = window.matchMedia('(min-width: 768px) and (max-width: 1199px)');

  function flags(p) {
    const out = [];
    const c = p.prefs.celebrations.toLowerCase();
    if (c.includes('anniversary')) out.push(['celebrate', 'Anniversary']);
    if (c.includes('birthday') && !c.includes('march')) out.push(['celebrate', 'Birthday']);
    if (p.responsible_gaming) out.push(['rg', 'Play limit on file']);
    if (p.tier === 'X') out.push(['vip', 'Top player']);
    if (/icon this year|short of icon/i.test(p.notes)) out.push(['up', 'Near Icon']);
    if (/14 months/.test(p.last_visit)) out.push(['up', 'Welcome back']);
    return out.map(([cls, t]) => `<span class="flag flag-${cls}">${esc(t)}</span>`).join('');
  }

  let state = { view: 'briefing', id: null, section: 'profile' };

  // ---------- briefing ----------
  function briefing() {
    const theo = P.reduce((s, p) => s + p.trip_theo, 0);
    const budget = P.reduce((s, p) => s + p.budget, 0);
    const rows = P.map((p, i) => `
      <li><a class="arrival" href="#/player/${p.slug}/profile" data-player="${p.slug}">
        <span class="when"><b>${esc(p.arrival.time.replace(' PM', ''))}</b><small>${p.arrival.time.slice(-2)}</small></span>
        <span class="mono" aria-hidden="true">${initials(p.name)}</span>
        <span class="who">
          <h3>${esc(p.name)}</h3>
          <span class="line">${tier(p.tier)}<span class="id">${esc(p.id)}</span></span>
          <span class="meta">${esc(p.room.split(' (')[0])} · ${esc(p.party.split('.')[0])}</span>
          <span class="flags">${flags(p)}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </a></li>`).join('');
    const tonight = ['light-show', 'council-oak', 'daer', 'kuro'].map((id) => DATA.venues[id]);
    return `
      <section class="hero brief-hero" style="--bg:url('${img('real/casino-floor.jpg')}')">
        <p class="eyebrow">Today's briefing · ${esc(DATA.day)}</p>
        <h1>Good afternoon, ${esc(DATA.host.first)}</h1>
        <p class="sub">${P.length} VIPs arriving today at ${esc(DATA.property)}.</p>
        <dl class="stats">
          <div><dt>Arrivals</dt><dd>${P.length}</dd></div>
          <div><dt>Trip theo</dt><dd>${k(theo)}</dd></div>
          <div><dt>Comp budget</dt><dd>${k(budget)}</dd></div>
        </dl>
      </section>
      <section class="block" id="arrivals">
        <div class="block-h"><h2>VIP arrivals</h2><span class="count">${P.length} today</span></div>
        <ol class="arrivals">${rows}</ol>
      </section>
      <section class="block" id="tonight-property">
        <div class="block-h"><h2>Tonight at the property</h2></div>
        <p class="note">No Hard Rock Live show tonight. Next: <b>Blake Shelton</b>, Saturday Oct 24, 8 PM · <b>Brand New</b>, Sunday Oct 25 · <b>Ed Sheeran</b>, Oct 29 and 30.</p>
        <div class="venues">${tonight.map((v) => venueCard(v)).join('')}</div>
      </section>`;
  }

  function venueCard(v, why) {
    return `<article class="venue"><img src="${img(v.img, true)}" alt="" loading="lazy"><div class="vbody"><span class="kind">${esc(v.kind)}</span><h3>${esc(v.name)}</h3><p>${esc(v.what)}</p>${why ? `<p class="why"><b>Why it fits:</b> ${esc(why)}</p>` : ''}</div></article>`;
  }

  // ---------- player ----------
  function panels(p) {
    const kpi = (label, val, cls = '') => `<div class="kpi ${cls}"><dt>${label}</dt><dd>${val}</dd></div>`;
    const profile = `
      <section class="panel" id="profile" data-section="profile">
        <h2>Gaming profile</h2>
        <dl class="kpis">
          ${kpi('ADT (avg daily theo)', usd(p.adt), 'big')}
          ${kpi('Average bet', usd(p.avg_bet), 'big')}
          ${kpi('Trip theo', usd(p.trip_theo))}
          ${kpi('12-month theo', usd(p.theo_12m))}
          ${kpi('Last trip W/L', wl(p.last_trip_wl))}
          ${kpi('12-month W/L', wl(p.wl_12m))}
          ${kpi('Trips per year', p.trips_per_year)}
          ${kpi('Last visit', esc(p.last_visit))}
          ${kpi('Credit line', p.credit_line ? usd(p.credit_line) : 'None')}
          ${kpi('Front money', p.front_money ? usd(p.front_money) : 'None')}
        </dl>
        <h3>Games played</h3>
        <ul class="games">${p.games.map((g) => `<li><b>${esc(g.game)}</b><span>${esc(g.detail)}</span></li>`).join('')}<li><b>Session</b><span>${esc(p.trip_hours)}</span></li></ul>
        <p class="wl-note">W/L is the player's result (− means the player lost).</p>
        <h3>Host notes</h3>
        <p class="notes">${esc(p.notes)}</p>
        <div class="approach"><h3>On the floor</h3><p>${esc(p.approach)}</p></div>
      </section>`;
    const used = Math.round((p.used / p.budget) * 100);
    const comps = `
      <section class="panel" id="comps" data-section="comps">
        <h2>Authorized comps</h2>
        <div class="budget">
          <div class="brow"><span>Trip comp budget</span><b>${usd(p.budget)}</b></div>
          <div class="bar" role="img" aria-label="${used}% used"><i style="width:${Math.max(used, 1)}%"></i></div>
          <div class="brow small"><span>Used ${usd(p.used)}</span><span><b>${usd(p.remaining)}</b> remaining</span></div>
        </div>
        ${p.responsible_gaming ? `<p class="rg"><b>Responsible gaming:</b> ${esc(p.responsible_gaming)}</p>` : ''}
        <ul class="comps">${p.comps.map((c) => `
          <li class="comp"><div><h3>${esc(c.item)}</h3><p>${esc(c.limit)}</p><span class="val">Value up to ≈ ${usd(c.value)}</span></div>
          <button type="button" class="offer" data-demo>Offer</button></li>`).join('')}</ul>
        <div class="approval"><h3>Needs manager approval</h3><ul>${p.needs_approval.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
        <p>Above an item's limit, past the trip budget, or not on this list: ask ${esc(DATA.approver)}.</p></div>
      </section>`;
    const pr = p.prefs;
    const row = (label, v) => `<div class="pref"><dt>${label}</dt><dd>${esc(v)}</dd></div>`;
    const prefs = `
      <section class="panel" id="preferences" data-section="preferences">
        <h2>Preferences</h2>
        <dl class="prefs">
          ${row('Games &amp; tables', pr.games)}
          ${row('Drinks', pr.drinks)}
          ${row('Dining', pr.dining)}
          ${row('Entertainment', pr.entertainment)}
          ${row('Celebrations', pr.celebrations)}
          ${row('Dislikes', pr.dislikes)}
        </dl>
      </section>`;
    const show = p.show ? `<article class="show"><img src="${img('real/hard-rock-live.jpg', true)}" alt=""><div><span class="kind">Hard Rock Live · this stay</span><h3>${esc(p.show.name)}</h3><p>${esc(p.show.when)}</p></div></article>` : '';
    const recs = `
      <section class="panel" id="recommendations" data-section="recommendations">
        <h2>Tonight's picks for ${esc(p.salutation)}</h2>
        ${show}
        <div class="venues">${p.tonight.map((v) => venueCard(v, v.why)).join('')}</div>
      </section>`;
    return { profile, comps, preferences: prefs, recommendations: recs };
  }

  function player(p, section) {
    const i = P.indexOf(p);
    const next = P[(i + 1) % P.length];
    const ps = panels(p);
    const tabs = SECTIONS.map((s) => `<a role="tab" href="#/player/${p.slug}/${s}" aria-selected="${s === section}" data-tab="${s}">${LABEL[s]}</a>`).join('');
    // phone and desktop frame: the chosen section only; tablet: profile beside the chosen one (comps for profile)
    const side = section === 'profile' ? 'comps' : section;
    const shown = tablet.matches ? ['profile', side] : [section];
    return `
      <nav class="crumbs" aria-label="Player navigation"><a href="#/briefing" class="back">‹ Briefing</a><a href="#/player/${next.slug}/profile" class="next">Next: ${esc(next.name)} ›</a></nav>
      <section class="hero player-hero" style="--bg:url('${img(GAME_IMG[p.slug])}')">
        <div class="ph-top"><span class="mono big" aria-hidden="true">${initials(p.name)}</span>
          <div><p class="eyebrow">Arrival ${i + 1} of ${P.length} · ${esc(p.arrival.time)}</p><h1>${esc(p.name)}</h1>
          <p class="line">${tier(p.tier)}<span class="id">${esc(p.id)}</span><span class="since">Member since ${p.since}</span></p></div></div>
        <p class="arr">${esc(p.arrival.how)}. ${esc(p.arrival.stay)}.</p>
        <p class="arr">${esc(p.room)}. ${esc(p.party)}.</p>
        <p class="flags">${flags(p)}</p>
      </section>
      <div class="tabs" role="tablist" aria-label="Player sections">${tabs}</div>
      <div class="panels${shown.length > 1 ? ' two' : ''}">${shown.map((s) => ps[s]).join('')}</div>`;
  }

  // ---------- routing ----------
  function find(q) {
    const s = String(q || '').toLowerCase().replace(/^(mr|mrs|ms|miss)\.?\s+/, '').trim();
    if (!s) return null;
    return P.find((p) => p.slug === s || p.id.toLowerCase() === s || p.name.toLowerCase() === s)
      || P.find((p) => s.includes(p.slug) || p.name.toLowerCase().split(' ').some((w) => w === s || s.split(/\s+/).includes(w)))
      || P.find((p) => p.id.endsWith(s.replace(/\D/g, '')) && s.replace(/\D/g, '').length >= 2);
  }

  function render(scroll = true) {
    const p = state.view === 'player' ? P.find((x) => x.slug === state.id) : null;
    main.innerHTML = p ? player(p, state.section) : briefing();
    document.title = (p ? `${p.name} · ${LABEL[state.section]}` : "Today's briefing") + ' | Host Companion (demo mockup)';
    if (scroll) window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
    if (p && state.section !== 'profile' && !tablet.matches) {
      const t = document.querySelector('.tabs');
      if (t && scroll) t.scrollIntoView({ block: 'start' });
    }
  }

  function fromHash() {
    const m = location.hash.match(/^#\/player\/([^/]+)(?:\/([a-z]+))?/);
    const p = m && find(m[1]);
    state = p ? { view: 'player', id: p.slug, section: SECTIONS.includes(m[2]) ? m[2] : 'profile' } : { view: 'briefing', id: null, section: 'profile' };
    render();
  }
  function go(hash) { // synchronous, so the voice companion's snapshot right after an action shows the new screen
    if (location.hash !== hash) history.pushState(null, '', location.pathname + location.search + hash);
    fromHash();
  }
  window.addEventListener('hashchange', fromHash);
  tablet.addEventListener('change', () => render(false));

  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-demo]');
    if (!b) return;
    e.preventDefault();
    const t = document.getElementById('demo-toast');
    t.hidden = false;
    clearTimeout(t._h);
    t._h = setTimeout(() => { t.hidden = true; }, 2400);
  });

  // ---------- what the voice companion sees and can do ----------
  window.LiveKitContext = () => {
    const p = state.view === 'player' ? P.find((x) => x.slug === state.id) : null;
    return { app: 'Hard Rock Host Companion (sample data, fictional players)', screen: state.view, player: p ? `${p.name} (${p.slug})` : null, section: p ? state.section : null };
  };
  const ACTIONS = {
    open_player: [({ player }) => {
      const p = find(player);
      if (!p) return `No arriving player matches "${player}". Players: ${P.map((x) => x.slug).join(', ')}.`;
      go(`#/player/${p.slug}/profile`);
      return `Opened ${p.name}'s profile.`;
    }, 'Open an arriving player\'s profile. Args {"player": last name, full name or Unity ID, e.g. "delane"}'],
    show_section: [({ section }) => {
      const s = String(section || '').toLowerCase();
      const sec = { tonight: 'recommendations', recommendation: 'recommendations', comp: 'comps', prefs: 'preferences', preference: 'preferences' }[s] || s;
      if (!SECTIONS.includes(sec)) return `No section "${section}". Sections: ${SECTIONS.join(', ')}.`;
      if (state.view !== 'player') return 'Open a player first (open_player).';
      go(`#/player/${state.id}/${sec}`);
      return `Showing ${LABEL[sec]} for ${P.find((x) => x.slug === state.id).name}.`;
    }, 'On a player\'s screen, show one section. Args {"section": "profile" | "comps" | "preferences" | "recommendations"}'],
    next_player: [() => {
      const i = state.view === 'player' ? P.findIndex((x) => x.slug === state.id) : -1;
      const p = P[(i + 1) % P.length];
      go(`#/player/${p.slug}/profile`);
      return `Opened the next arrival: ${p.name}.`;
    }, 'Open the next arriving player after the one on screen (the first one from the briefing). No args.'],
    back_to_briefing: [() => { go('#/briefing'); return "Showing today's briefing."; }, "Go back to today's briefing (the VIP arrivals list). No args."],
  };
  (function register(n) {
    const a = window.LiveKitAgent;
    if (a && a.registerAction) {
      for (const [name, [fn, desc]] of Object.entries(ACTIONS)) a.registerAction(name, (args) => fn(args || {}), desc);
    } else if (n < 200) setTimeout(() => register(n + 1), 50);
  })(0);

  fromHash();
})();
