// The mockup's hotel booking engine (Bethlehem Book Now), modeled on Wind Creek's own:
// Dates of Stay -> Accommodations -> Confirm -> Booked!. Client-side and inert: no sign-in, no guest details, nothing
// is sent anywhere. Prices come from window.WC_BOOKING (captured from the public booking engine; see booking.json).
// Kai gets the safe steps as site actions: dates, next/back, clear, guests, room type, accessible, select a room
// (which opens Confirm). It has no action that completes a reservation, signs in or pays.
(function () {
  const B = window.WC_BOOKING;
  const $ = (s) => document.querySelector(s);
  const ICON = {
    expand: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
    access: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="4" r="2" fill="currentColor"/><path d="M5 8h14M12 8v6m0 0-3 8m3-8 3 8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
  };
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const st = { step: 'dates', in: null, out: null, guests: 1, type: 'All', accessible: false, room: null, month: new Date(today.getFullYear(), today.getMonth(), 1) };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const fmt = (d) => (d ? `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}/${d.getFullYear()}` : '');
  const nice = (d) => d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  const parse = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || '').trim()); if (!m) return null; const d = new Date(+m[1], +m[2] - 1, +m[3]); return isNaN(d) ? null : d; };
  const money = (n) => '$' + n.toLocaleString('en-US');
  const fromPrice = (d) => B.calendar_from[iso(d)];
  const nightsList = () => { const out = []; for (let d = new Date(st.in); d < st.out; d.setDate(d.getDate() + 1)) out.push(new Date(d)); return out; };
  const nights = () => (st.in && st.out ? nightsList().length : 0);
  // a room's nightly average for the chosen nights: its captured base rate, scaled by those nights' calendar prices
  const avgRate = (r) => {
    const ps = nightsList().map(fromPrice).filter(Boolean);
    const f = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length / B.base_from : 1;
    return Math.max(99, Math.round((r.avg * f) / 10) * 10 - 1);
  };
  const matches = () => B.rooms.filter((r) => r.guests >= st.guests && (st.type === 'All' || r.type === st.type) && (!st.accessible || r.accessible));
  const ORDER = ['dates', 'rooms', 'confirm', 'booked'];

  function show(step) {
    st.step = step;
    document.querySelectorAll('.wcb-stepper li').forEach((li) => {
      const i = ORDER.indexOf(li.dataset.step), cur = ORDER.indexOf(step);
      li.classList.toggle('on', i <= cur);
      li.classList.toggle('current', i === cur);
    });
    document.querySelectorAll('.wcb-step').forEach((s) => { s.hidden = s.id !== 'wcb-' + step; });
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function renderCal() {
    const m = st.month;
    $('#wcb-month').textContent = m.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    const first = new Date(m.getFullYear(), m.getMonth(), 1);
    const start = new Date(first); start.setDate(1 - first.getDay());
    let html = '';
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      if (i >= 35 && d.getMonth() !== m.getMonth()) break;
      const p = fromPrice(d);
      const isIn = st.in && +d === +st.in, isOut = st.out && +d === +st.out;
      const inRange = st.in && st.out && d > st.in && d < st.out;
      const canOut = st.in && !st.out && d > st.in;
      const open = d >= today && d.getMonth() === m.getMonth() && (p || canOut);
      const cls = ['wcb-day', open ? 'open' : 'closed', isIn || isOut ? 'sel' : '', inRange ? 'range' : ''].filter(Boolean).join(' ');
      const body = isIn ? '<em>Check-in</em>' : isOut ? '<em>Checkout</em>' : p && d >= today ? `<small>FROM</small><b>${money(p)}</b>` : '';
      html += `<button type="button" class="${cls}" data-date="${iso(d)}"${open ? '' : ' disabled'} aria-label="${d.toDateString()}${p ? ', from ' + money(p) : ''}"><span class="n">${d.getDate()}</span>${body}</button>`;
    }
    $('#wcb-days').innerHTML = html;
  }

  function renderRooms() {
    const list = matches();
    $('#wcb-count').textContent = `${list.length} MATCHES`;
    $('#wcb-roomlist').innerHTML = list.map((r) => `
      <article class="wcb-room">
        <div class="wcb-photo"><img src="/windcreek/img/rooms/${r.img}" alt="${r.name.toLowerCase()}">
          <span class="wcb-tag"><small>NIGHTLY<br>AVERAGE</small><b>${money(avgRate(r))}</b></span>
          <button type="button" class="wcb-expand" data-demo aria-label="Enlarge photo">${ICON.expand}</button></div>
        <div class="wcb-room-body">
          <div class="wcb-room-head"><h3>${r.name}</h3><button type="button" class="wcb-select" data-room="${B.rooms.indexOf(r)}">Select</button></div>
          <p class="wcb-spec">${r.spec}</p>
          <p>${r.desc}</p>
          ${r.pets ? '<p>Wind Creek Bethlehem is a pet and animal-free property; however, ADA service animals are permitted. Thank you for your understanding and cooperation.</p>' : ''}
          <p class="wcb-acc"><button type="button" data-demo>&#8964; Room Amenities</button><button type="button" data-demo>&#8964; Accessible Amenities</button></p>
        </div>
      </article>`).join('') || '<p class="wcb-none">No rooms match these filters. Try fewer guests or another room type.</p>';
  }

  function render() {
    document.querySelectorAll('.wcb-in').forEach((e) => { e.textContent = fmt(st.in) || 'mm/dd/yyyy'; e.classList.toggle('ph', !st.in); });
    document.querySelectorAll('.wcb-out').forEach((e) => { e.textContent = fmt(st.out) || 'mm/dd/yyyy'; e.classList.toggle('ph', !st.out); });
    $('#wcb-next').disabled = !(st.in && st.out);
    $('#wcb-guests').textContent = st.guests;
    $('#wcb-type').value = st.type;
    $('#wcb-accessible').checked = st.accessible;
    renderCal();
    if (st.step === 'rooms') renderRooms();
    if (st.room != null && st.in && st.out) {
      const r = B.rooms[st.room], n = nights(), rate = avgRate(r);
      $('#wcb-summary').innerHTML = `<h3>${r.name}</h3><p class="wcb-spec">${r.spec}</p>
        <dl><dt>Check-In</dt><dd>${nice(st.in)} · 4PM</dd><dt>Check-Out</dt><dd>${nice(st.out)} · 11AM</dd><dt>Guests</dt><dd>${st.guests}</dd>
        <dt>Nightly average</dt><dd>${money(rate)}</dd><dt>Room total, ${n} night${n > 1 ? 's' : ''}</dt><dd>${money(rate * n)} before taxes and fees</dd></dl>`;
    }
  }

  function pick(d) {
    if (!st.in || st.out || d <= st.in) { st.in = d; st.out = null; } else st.out = d;
    render();
  }
  function setMonthFor(d) { st.month = new Date(d.getFullYear(), d.getMonth(), 1); }

  document.addEventListener('click', (e) => {
    const t = e.target;
    const day = t.closest('.wcb-day.open');
    if (day) return pick(parse(day.dataset.date));
    if (t.closest('#wcb-prev')) { const p = new Date(st.month.getFullYear(), st.month.getMonth() - 1, 1); if (p >= new Date(today.getFullYear(), today.getMonth(), 1)) st.month = p; return render(); }
    if (t.closest('#wcb-nextm')) { st.month = new Date(st.month.getFullYear(), st.month.getMonth() + 1, 1); return render(); }
    if (t.closest('#wcb-clear')) { st.in = st.out = null; return render(); }
    if (t.closest('#wcb-next') && st.in && st.out) return show('rooms');
    if (t.closest('.wcb-back') || t.closest('#wcb-change')) return show(t.closest('[data-to]')?.dataset.to || 'dates');
    if (t.closest('#wcb-minus')) { st.guests = Math.max(1, st.guests - 1); return render(); }
    if (t.closest('#wcb-plus')) { st.guests = Math.min(4, st.guests + 1); return render(); }
    const sel = t.closest('[data-room]');
    if (sel) { st.room = +sel.dataset.room; return show('confirm'); }
    if (t.closest('#wcb-book')) { $('#wcb-conf').textContent = 'DEMO-' + Math.random().toString(36).slice(2, 7).toUpperCase(); return show('booked'); }
  });
  document.addEventListener('change', (e) => {
    if (e.target.id === 'wcb-type') { st.type = e.target.value; render(); }
    if (e.target.id === 'wcb-accessible') { st.accessible = e.target.checked; render(); }
  });

  // ---- Kai's allow-list on this page ----
  const roomByName = (q) => {
    const w = String(q || '').toLowerCase().split(/[^a-z0-9]+/).filter((x) => x && !['the', 'room', 'a'].includes(x));
    const scored = B.rooms.map((r, i) => ({ i, s: w.filter((x) => r.name.toLowerCase().includes(x)).length - r.name.split(' ').length / 100 }));
    scored.sort((a, b) => b.s - a.s);
    return scored[0] && scored[0].s >= Math.max(1, w.length - 1) ? scored[0].i : -1;
  };
  // the widget's Kai: this window's, or the presenter shell's when this page is shown in its frame
  const kaiApi = () => {
    if (window.Kai && window.Kai.registerAction) return window.Kai;
    try { if (window.parent !== window && window.parent.Kai && window.parent.Kai.registerAction) return window.parent.Kai; } catch (e) { /* cross-origin */ }
    return null;
  };
  const NAMES = ['select_dates', 'next_step', 'previous_step', 'clear_selection', 'filter_rooms', 'select_room'];
  function register() {
    const Kai = kaiApi();
    if (!Kai) return setTimeout(register, 200);
    if (Kai !== window.Kai) { // framed: when this page goes away, its actions stop working
      window.addEventListener('pagehide', () => NAMES.forEach((n) => Kai.registerAction(n, () => { throw new Error('Not available on this page.'); }, '(not available on this page)')));
    }
    Kai.registerAction('select_dates', ({ check_in, check_out }) => {
      const a = parse(check_in), b = parse(check_out);
      if (!a || !b) throw new Error('Pass check_in and check_out as YYYY-MM-DD.');
      if (a < today) throw new Error('Check-in is in the past.');
      if (b <= a) throw new Error('Check-out must be after check-in.');
      if (!fromPrice(a)) throw new Error('No availability shown for that check-in date.');
      st.in = a; st.out = b; setMonthFor(a);
      if (st.step !== 'dates') show('dates'); else render();
      const ps = nightsList().map((d) => `${nice(d)} from ${money(fromPrice(d) || 0)}`).join('; ');
      return `Dates set on the calendar: ${nice(a)} to ${nice(b)}, ${nights()} night(s). Nightly prices from: ${ps}. Next shows the rooms.`;
    }, 'Booking calendar: set the stay dates. Args: {"check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD"}.');
    Kai.registerAction('next_step', () => {
      if (st.step !== 'dates') throw new Error('Next only moves from the dates to the rooms.');
      if (!(st.in && st.out)) throw new Error('Set the dates first (select_dates).');
      show('rooms');
      return `${matches().length} room options are showing with nightly averages.`;
    }, 'Booking: go from the dates to the room options. No args.');
    Kai.registerAction('previous_step', () => { show(st.step === 'confirm' ? 'rooms' : 'dates'); return 'Went back one step.'; }, 'Booking: go back one step. No args.');
    Kai.registerAction('clear_selection', () => { st.in = st.out = null; show('dates'); return 'Dates cleared.'; }, 'Booking: clear the dates. No args.');
    Kai.registerAction('filter_rooms', ({ guests, room_type, accessible }) => {
      if (guests != null) { const g = +guests; if (!(g >= 1 && g <= 4)) throw new Error('Guests must be 1 to 4.'); st.guests = g; }
      if (room_type != null) { const t = String(room_type).replace(/s$/i, ''); const k = ['All', 'King', 'Queen', 'Suite'].find((x) => x.toLowerCase() === t.toLowerCase()); if (!k) throw new Error('Room type is All, King, Queen or Suite.'); st.type = k; }
      if (accessible != null) st.accessible = !!accessible;
      if (st.step !== 'rooms') { if (!(st.in && st.out)) { render(); return 'Filters set; choose dates to see rooms.'; } show('rooms'); } else render();
      return `${matches().length} matches: ` + matches().map((r) => `${r.name} ${money(avgRate(r))}`).join('; ');
    }, 'Booking rooms: filter. Args (any): {"guests": 1-4, "room_type": "All"|"King"|"Queen"|"Suite", "accessible": true|false}.');
    Kai.registerAction('select_room', ({ room }) => {
      if (!(st.in && st.out)) throw new Error('Set the dates first.');
      const i = roomByName(room);
      if (i < 0) throw new Error(`No room matches "${room}". Rooms: ${matches().map((r) => r.name).join('; ')}`);
      st.room = i; show('confirm');
      return `Confirm step open for ${B.rooms[i].name}. Stop here: the guest completes the reservation themselves.`;
    }, 'Booking rooms: press Select on one room (opens the Confirm step for review). Args: {"room": "<room name>"}. Never completes the booking.');
  }
  register();
  render();
})();
