// The mockup's booking engine (/book), modeled on reservations.hardrockhotels.com for Hard Rock Hotel New York:
// Dates (two-month price calendar, guests) -> Rooms (filters, room cards) -> Rates (per room) -> Guest details, where the
// demo stops. Client-side and inert: no sign-in, no guest details, nothing is sent anywhere. Rooms and rates come from
// window.HR_BOOKING (knowledge/hardrock/booking.json); nightly prices scale the published weekday/weekend prices by a
// deterministic per-date factor, so the page and LiveKit always agree.
// LiveKit gets the safe steps as site actions: select_dates, set_guests, search, filter_rooms, select_room,
// select_rate (which adds to the cart and opens the Guest details stop), back. Nothing completes a reservation.
(function () {
  const B = window.HR_BOOKING;
  const H = B.hotels['new-york'];
  const $ = (s) => document.querySelector(s);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const q = new URLSearchParams(location.search);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const nice = (d) => d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
  const parse = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || '').trim()); if (!m) return null; const d = new Date(+m[1], +m[2] - 1, +m[3]); return isNaN(d) ? null : d; };
  const money = (n) => '$' + Math.round(n).toLocaleString('en-US');
  const st = {
    step: 'dates', in: null, out: null, adults: 2, children: 0, filter: 'All', room: null, rate: null,
    month: new Date(today.getFullYear(), today.getMonth(), 1),
  };

  // ---- prices ----
  const hash = (s) => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; };
  const weekend = (d) => d.getDay() === 5 || d.getDay() === 6; // Friday and Saturday nights
  const factor = (d) => 0.82 + 0.36 * hash(iso(d));
  const soldOut = (d) => !weekend(d) && d - today > 3 * 864e5 && hash('so' + iso(d)) < 0.05;
  const nightly = (r, d) => Math.round(((weekend(d) ? r.from_weekend : r.from_weekday) * factor(d)) / 5) * 5;
  const nightsList = () => { const out = []; for (let d = new Date(st.in); d < st.out; d.setDate(d.getDate() + 1)) out.push(new Date(d)); return out; };
  const nights = () => (st.in && st.out ? nightsList().length : 0);
  const avg = (r) => { const ns = nightsList(); return ns.reduce((a, d) => a + nightly(r, d), 0) / ns.length; };
  const cheapest = (d) => Math.min(...H.rooms.filter((r) => r.max_guests >= st.adults + st.children && r.from_weekday < 5000).map((r) => nightly(r, d)));
  const guests = () => st.adults + st.children;
  const kind = (r) => [r.type, r.balcony || /balcony/i.test(r.name) ? 'Balcony' : ''];
  const matches = () => H.rooms.filter((r) => r.max_guests >= guests() && (st.filter === 'All' || kind(r).includes(st.filter)));
  function rateOk(rate) {
    const n = nights();
    if (rate.min_nights && n < rate.min_nights) return `needs ${rate.min_nights}+ nights`;
    if (rate.book_by && today > parse(rate.book_by)) return 'booking window has closed';
    if (rate.stay_through && st.in > parse(rate.stay_through)) return `stays through ${rate.stay_through} only`;
    if (rate.advance_days && st.in - today < rate.advance_days * 864e5) return `book ${rate.advance_days} days ahead`;
    if (rate.room_types && !rate.room_types.includes(st.room?.name)) return 'not for this room';
    return '';
  }
  const ratePrice = (rate, r) => (rate.add_per_night ? avg(r) + rate.add_per_night : avg(r) * (rate.multiplier || 1));

  // ---- render ----
  const ORDER = ['dates', 'rooms', 'rates', 'guest'];
  function show(step) {
    st.step = step;
    document.querySelectorAll('.be-steps li').forEach((li) => {
      const i = ORDER.indexOf(li.dataset.step), cur = ORDER.indexOf(step);
      li.classList.toggle('on', i === cur);
      li.classList.toggle('done', i < cur);
    });
    $('#be-dates').hidden = !(step === 'dates');
    $('#be-rooms').hidden = !(step === 'rooms' || step === 'rates');
    $('#be-guest').hidden = step !== 'guest';
    render();
    window.scrollTo({ top: step === 'dates' ? 0 : 300, behavior: 'smooth' });
  }
  function renderCal() {
    [0, 1].forEach((k) => {
      const m = new Date(st.month.getFullYear(), st.month.getMonth() + k, 1);
      $(`#be-m${k}`).textContent = m.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
      let html = '';
      for (let i = 0; i < m.getDay(); i++) html += '<span class="be-day blank"></span>';
      for (let d = new Date(m); d.getMonth() === m.getMonth(); d.setDate(d.getDate() + 1)) {
        const past = d < today, so = !past && soldOut(d);
        const isIn = st.in && +d === +st.in, isOut = st.out && +d === +st.out;
        const range = st.in && st.out && d > st.in && d < st.out;
        const cls = ['be-day', past ? 'past' : '', so ? 'sold' : '', isIn || isOut ? 'sel' : '', range ? 'range' : ''].filter(Boolean).join(' ');
        const price = past || so ? '' : `<small>${money(cheapest(d))}</small>`;
        html += `<button type="button" class="${cls}" data-date="${iso(d)}"${past || so ? ' disabled' : ''} aria-label="${d.toDateString()}${price ? ', from ' + money(cheapest(d)) : so ? ', sold out' : ''}">${d.getDate()}${price}</button>`;
      }
      $(`#be-d${k}`).innerHTML = html;
    });
  }
  function rateRows(r) {
    return H.rates.map((rate) => {
      const why = rateOk(rate);
      if (why) return '';
      const p = ratePrice(rate, r), base = avg(r);
      const perks = (rate.perks || []).join(' · ');
      return `<div class="be-rate"><div><h4>${rate.name}</h4><p>${perks ? perks + '<br>' : ''}${rate.cancellation}</p></div>
        <div class="amt">${p < base - 1 ? `<s>${money(base)}</s>` : ''}<b>${money(p)}</b>avg/night</div>
        <button type="button" class="be-btn" data-rate="${rate.code}">Select</button></div>`;
    }).join('') + `<p class="be-fine" style="padding:8px 20px">${H.rates.filter((x) => rateOk(x)).map((x) => `${x.name}: ${rateOk(x)}`).join(' · ')}</p>`;
  }
  function renderRooms() {
    const list = matches();
    $('#be-roomlist').innerHTML = list.map((r) => {
      const open = st.room === r;
      return `<article class="be-room" data-room-card="${r.name}"><img src="${B.pics[r.name] || B.hero}" alt="${r.name}">
        <div class="rb"><h3>${r.name}</h3><div class="rspec">${r.bed} · ${r.size_sqft} sq. ft. · ${r.view} · Sleeps up to ${r.max_guests}</div>
        <p class="rdesc">${r.desc}</p>
        <div class="rfoot"><button type="button" class="be-btn ${open ? 'black' : ''}" data-room="${r.name}">${open ? 'Hide Rates' : 'View Rates'}</button>
        <div class="price">Starting from<b>${money(Math.min(...H.rates.filter((x) => !rateOk(x)).map((x) => ratePrice(x, r))))}</b>avg/night, before taxes &amp; fees</div></div></div>
        ${open ? `<div class="be-rates" aria-label="Rates for ${r.name}">${rateRows(r)}</div>` : ''}</article>`;
    }).join('') || '<p class="be-alert">No rooms match. Try fewer guests or another room type.</p>';
    document.querySelectorAll('#be-filter button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === st.filter)));
  }
  function renderCart() {
    if (!(st.room && st.rate)) { $('#be-count').textContent = '0 Items'; $('#be-cartbody').innerHTML = ''; return; }
    const n = nights(), p = ratePrice(st.rate, st.room), fees = H.fees_per_night * n;
    $('#be-count').textContent = '1 Item';
    $('#be-cartbody').innerHTML = `<dl><dt>Room</dt><dd>${st.room.name}</dd><dt>Rate</dt><dd>${st.rate.name}</dd>
      <dt>Check-in</dt><dd>${nice(st.in)}</dd><dt>Check-out</dt><dd>${nice(st.out)}</dd><dt>Guests</dt><dd>${st.adults} adult${st.adults > 1 ? 's' : ''}${st.children ? `, ${st.children} child${st.children > 1 ? 'ren' : ''}` : ''}</dd>
      <dt>${n} night${n > 1 ? 's' : ''} × ${money(p)}</dt><dd>${money(p * n)}</dd><dt>Destination fee + tax</dt><dd>${money(fees)}</dd></dl>
      <div class="total"><span>Total before taxes</span><b>${money(p * n + fees)}</b></div>`;
  }
  function render() {
    $('#be-in').textContent = st.in ? nice(st.in) : 'Select a date';
    $('#be-out').textContent = st.out ? nice(st.out) : 'Select a date';
    $('#be-guests').textContent = `${guests()} guest${guests() > 1 ? 's' : ''}, 1 room`;
    $('#be-adults').textContent = st.adults;
    $('#be-children').textContent = st.children;
    $('#be-search').disabled = !(st.in && st.out);
    renderCal();
    if (st.step === 'rooms' || st.step === 'rates') renderRooms();
    renderCart();
  }
  function pick(d) {
    if (!st.in || st.out || d <= st.in) { st.in = d; st.out = null; } else st.out = d;
    st.room = st.rate = null;
    render();
  }

  // ---- clicks ----
  document.addEventListener('click', (e) => {
    const t = e.target;
    const day = t.closest('.be-day[data-date]:not([disabled])');
    if (day) return pick(parse(day.dataset.date));
    if (t.closest('#be-prev')) { const p = new Date(st.month.getFullYear(), st.month.getMonth() - 1, 1); if (p >= new Date(today.getFullYear(), today.getMonth(), 1)) st.month = p; return render(); }
    if (t.closest('#be-next')) { st.month = new Date(st.month.getFullYear(), st.month.getMonth() + 1, 1); return render(); }
    if (t.closest('#be-clear')) { st.in = st.out = st.room = st.rate = null; return render(); }
    if (t.closest('#be-search') && st.in && st.out) return show('rooms');
    const g = t.closest('.be-step');
    if (g) { st[g.dataset.g] = Math.max(g.dataset.g === 'adults' ? 1 : 0, Math.min(4, st[g.dataset.g] + +g.dataset.d)); return render(); }
    const f = t.closest('#be-filter button');
    if (f) { st.filter = f.dataset.f; return render(); }
    const rb = t.closest('[data-room]');
    if (rb) { const r = H.rooms.find((x) => x.name === rb.dataset.room); st.room = st.room === r ? null : r; st.rate = null; st.step = st.room ? 'rates' : 'rooms'; return show(st.step); }
    const rt = t.closest('[data-rate]');
    if (rt) { st.rate = H.rates.find((x) => x.code === rt.dataset.rate); return show('guest'); }
    const back = t.closest('.be-back');
    if (back) { st.rate = null; return show(st.room ? 'rates' : 'rooms'); }
  });

  // ---- LiveKit's allow-list on this page ----
  const STOP = /\b(the|a|an|room|rooms|please)\b/g;
  const byName = (list, qs, key = 'name') => {
    const w = String(qs || '').toLowerCase().replace(STOP, ' ').split(/[^a-z0-9]+/).filter(Boolean);
    if (!w.length) return null;
    let best = null;
    for (const x of list) {
      const n = x[key].toLowerCase();
      const hit = w.filter((y) => n.includes(y) || (y.endsWith('s') && n.includes(y.slice(0, -1)))).length;
      const s = hit - n.split(' ').length / 100 - (/accessible/.test(n) && !w.includes('accessible') ? 1 : 0);
      if (hit && (!best || s > best.s)) best = { x, s, hit };
    }
    return best && best.hit >= Math.max(1, w.length - 1) ? best.x : null;
  };
  const ratesText = (r) => H.rates.filter((x) => !rateOk(x)).map((x) => `${x.name} ${money(ratePrice(x, r))}/night (${x.refundable ? 'refundable' : 'non-refundable'}${x.members_only ? ', Unity members' : ''})`).join('; ');
  function ensureDates() { if (!(st.in && st.out)) throw new Error('Set the dates first with select_dates.'); }
  function register() {
    const A = window.LiveKitAgent;
    if (!(A && A.registerAction)) return setTimeout(register, 200);
    A.registerAction('select_dates', ({ check_in, check_out }) => {
      const a = parse(check_in), b = parse(check_out) || (a && new Date(a.getFullYear(), a.getMonth(), a.getDate() + 1));
      if (!a) throw new Error('Pass check_in (and check_out) as YYYY-MM-DD.');
      if (a < today) throw new Error('Check-in is in the past.');
      if (b <= a) throw new Error('Check-out must be after check-in.');
      st.in = a; st.out = b; st.room = st.rate = null; st.month = new Date(a.getFullYear(), a.getMonth(), 1);
      const sold = nightsList().filter(soldOut);
      if (sold.length) { st.in = st.out = null; render(); throw new Error(`Sold out on ${sold.map(nice).join(', ')}. Try other dates.`); }
      show('rooms');
      return `Dates set: ${nice(a)} to ${nice(b)}, ${nights()} night(s), ${guests()} guest(s). The room list is showing, ${matches().length} rooms; lowest from ${money(Math.min(...matches().map(avg)))} a night before taxes and fees.`;
    }, 'Set the stay dates and show the rooms. Args: {"check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD"} (check_out defaults to one night).');
    A.registerAction('set_guests', ({ adults, children }) => {
      if (adults != null) st.adults = Math.max(1, Math.min(4, +adults || 1));
      if (children != null) st.children = Math.max(0, Math.min(4, +children || 0));
      st.room = st.rate = null; render();
      return `Guests: ${st.adults} adult(s), ${st.children} child(ren).`;
    }, 'Set the number of guests. Args: {"adults": 2, "children": 0}.');
    A.registerAction('filter_rooms', ({ type }) => {
      const t = String(type || 'All').toLowerCase();
      st.filter = /king/.test(t) ? 'King' : /queen/.test(t) ? 'Queen' : /suite|studio/.test(t) ? 'Suite' : /balcon|terrace/.test(t) ? 'Balcony' : 'All';
      ensureDates();
      st.room = st.rate = null; show('rooms');
      return `Showing ${st.filter} rooms: ${matches().map((r) => `${r.name} from ${money(avg(r))}`).join('; ')}.`;
    }, 'Filter the room list. Args: {"type": "All" | "King" | "Queen" | "Suite" | "Balcony"}.');
    A.registerAction('select_room', ({ room }) => {
      ensureDates();
      const r = byName(H.rooms.filter((x) => x.max_guests >= guests()), room);
      if (!r) throw new Error(`No room "${room}" for ${guests()} guest(s). Rooms: ${matches().map((x) => x.name).join(', ')}.`);
      if (st.filter !== 'All' && !kind(r).includes(st.filter)) st.filter = 'All';
      st.room = r; st.rate = null; show('rates');
      setTimeout(() => document.querySelector(`[data-room-card="${r.name}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
      return `${r.name} (${r.bed}, ${r.size_sqft} sq ft, sleeps ${r.max_guests}) for ${nice(st.in)} to ${nice(st.out)}. Rates: ${ratesText(r)}. Plus $${H.fees_per_night} a night destination fee and tax. Not available for these dates: ${H.rates.filter((x) => rateOk(x)).map((x) => `${x.name} (${rateOk(x)})`).join(', ') || 'none'}.`;
    }, 'Open a room\'s rates (Rates step). Args: {"room": "Classic King"}.');
    A.registerAction('select_rate', ({ rate }) => {
      ensureDates();
      if (!st.room) throw new Error('Select a room first with select_room.');
      const r = byName(H.rates.filter((x) => !rateOk(x)), rate);
      if (!r) throw new Error(`No rate "${rate}". Rates: ${ratesText(st.room)}.`);
      st.rate = r; show('guest');
      return `Added to the cart: ${st.room.name}, ${r.name}, ${money(ratePrice(r, st.room))} a night, ${nights()} night(s). The page is now at Guest details, where the guest enters their own name, contact and payment. Stop here.`;
    }, 'Choose a rate for the selected room; adds it to the cart and opens Guest details (the demo stops there). Args: {"rate": "Best Flexible Rate"}.');
    A.registerAction('back', ({ to }) => {
      const s = ['dates', 'rooms'].includes(to) ? to : st.step === 'guest' ? 'rates' : 'dates';
      if (s === 'dates') { st.room = st.rate = null; }
      if (s === 'rooms') { st.room = st.rate = null; }
      show(s);
      return `Back to ${s}.`;
    }, 'Go back a step. Args: {"to": "dates" | "rooms"}.');
  }

  // ---- boot ----
  $('#be-hero-img').src = B.hero;
  $('#be-hotel').textContent = H.name;
  st.adults = Math.max(1, Math.min(4, +q.get('adults') || 2));
  st.children = Math.max(0, Math.min(4, +q.get('children') || 0));
  const qin = parse(q.get('in')), qout = parse(q.get('out'));
  if (qin && qin >= today) { st.in = qin; st.out = qout && qout > qin ? qout : new Date(qin.getFullYear(), qin.getMonth(), qin.getDate() + 1); st.month = new Date(qin.getFullYear(), qin.getMonth(), 1); }
  const qroom = q.get('room') && byName(H.rooms, q.get('room'));
  if (st.in && st.out && qroom) { st.room = qroom; show('rates'); } else if (st.in && st.out) show('rooms'); else render();
  window.LiveKitContext = () => ({
    booking_step: st.step, check_in: st.in && iso(st.in), check_out: st.out && iso(st.out), adults: st.adults, children: st.children,
    room: st.room && st.room.name, rate: st.rate && st.rate.name, filter: st.filter,
  });
  register();
})();
