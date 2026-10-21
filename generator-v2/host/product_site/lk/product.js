/* LiveKit demo generator - product layer on the main demo page (additive; loaded by one <script> tag).
 * - "Sign in" / "My demos" pill (top left), "Analytics" for admins
 * - builds started from the Generate modal are tied to the signed-in account (adds lk_session to POST /api/generate)
 * - links to generated demos carry a scoped lk_u token so demo sessions are attributed to the person
 * - gallery opens are counted for the analytics page
 * Everything fails silently: the page works exactly as before if the build host is unreachable. */
(function () {
  var API = window.LK_GEN_API || 'https://sb-mgs5l8pw3lep.vercel.run';
  var ls = window.localStorage;
  function get(k) { try { return ls.getItem(k); } catch (e) { return null; } }
  function user() { try { return JSON.parse(get('lk.user')); } catch (e) { return null; } }
  var anon = get('lk.anon') || ('anon-' + Math.random().toString(36).slice(2, 12)); try { ls.setItem('lk.anon', anon); } catch (e) {}
  function track(evs) {
    try {
      var b = JSON.stringify({ session: get('lk.session') || undefined, uid: get('lk.session') ? undefined : anon, events: evs });
      if (navigator.sendBeacon) navigator.sendBeacon(API + '/api/p/event', new Blob([b], { type: 'text/plain' }));
      else fetch(API + '/api/p/event', { method: 'POST', body: b, headers: { 'Content-Type': 'text/plain' }, keepalive: true });
    } catch (e) {}
  }
  window.LKProduct = { track: track, api: API, user: user };

  // 1) attach the account to builds started from the Generate modal
  var of = window.fetch;
  if (of) window.fetch = function (input, init) {
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var s = get('lk.session');
      if (s && init && /\/api\/generate(\?|$)/.test(url) && String(init.method || '').toUpperCase() === 'POST' && typeof init.body === 'string') {
        var b = JSON.parse(init.body); b.lk_session = s; init = Object.assign({}, init, { body: JSON.stringify(b) });
      }
    } catch (e) {}
    return of.call(this, input, init);
  };

  // 2) attribute generated-demo opens + count gallery opens
  document.addEventListener('click', function (ev) {
    try {
      var a = ev.target.closest && ev.target.closest('a[href]');
      if (a && a.href.indexOf(API + '/v2/') === 0) {
        var v = get('lk.view');
        if (v && a.href.indexOf('lk_u=') < 0) a.href += (a.href.indexOf('?') < 0 ? '?' : '&') + 'lk_u=' + encodeURIComponent(v);
        var m = a.href.match(/\/v2\/([a-z0-9-]+)\//); track([{ t: 'gallery_open', demo: m ? m[1] : 'generated', where: 'generated' }]);
        return;
      }
      var t = ev.target.closest && ev.target.closest('.demos nav button, .demos nav a, .seg button, .talk');
      if (t) track([{ t: 'gallery_open', demo: (t.classList.contains('talk') ? 'talk:' : '') + ((document.querySelector('.demos nav .on, .seg button.on') || t).textContent || '').trim().slice(0, 60), where: t.classList.contains('talk') ? 'talk' : 'tab' }]);
      if (ev.target.closest && ev.target.closest('.aigen-btn')) track([{ t: 'generate_click' }]);
    } catch (e) {}
  }, true);

  // 3) account pill
  var css = document.createElement('style');
  css.textContent =
    '.lkp-pill{position:fixed;top:46px;left:24px;z-index:2147483000;display:inline-flex;align-items:center;gap:8px;height:34px;padding:0 14px 0 6px;border-radius:999px;' +
    'background:rgba(17,18,20,.86);border:1px solid #2a2d33;color:#e8e9eb;font:500 13px/1 Inter,ui-sans-serif,system-ui,sans-serif;text-decoration:none;' +
    'backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);transition:border-color .15s,color .15s}' +
    '.lkp-pill:hover{border-color:#1fd5f9;color:#fff}.lkp-pill:focus-visible{outline:2px solid #1fd5f9;outline-offset:2px}' +
    '.lkp-av{width:24px;height:24px;border-radius:50%;background:#1fd5f9;color:#031317;display:grid;place-items:center;font-weight:700;font-size:11px;overflow:hidden}' +
    '.lkp-av img{width:100%;height:100%;object-fit:cover}.lkp-g{width:24px;height:24px;border-radius:50%;background:#fff;display:grid;place-items:center}' +
    '.lkp-an{position:fixed;top:86px;left:24px;z-index:2147483000;font:500 12px/1 Inter,system-ui,sans-serif;color:#8a8f98;text-decoration:none;padding:6px 8px}.lkp-an:hover{color:#1fd5f9}' +
    '@media (max-width:700px){.lkp-pill{top:auto;bottom:16px;left:12px}.lkp-an{display:none}}';
  document.head.appendChild(css);
  function esc(s) { return String(s || '').replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var G = '<span class="lkp-g"><svg width="14" height="14" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.6 13.3l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.3 6.9-17.7z"/><path fill="#FBBC05" d="M10.5 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C.9 16.6 0 20.2 0 24s.9 7.4 2.6 10.7l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.7-6c-2.2 1.5-5 2.3-8.2 2.3-6.3 0-11.6-4.2-13.5-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z"/></svg></span>';
  function render() {
    var u = user(), el = document.getElementById('lkp-pill');
    if (!el) { el = document.createElement('a'); el.id = 'lkp-pill'; el.className = 'lkp-pill'; document.body.appendChild(el); }
    el.href = '/account/';
    el.innerHTML = u ? '<span class="lkp-av">' + (u.picture ? '<img alt="" src="' + esc(u.picture) + '">' : esc((u.name || u.email)[0].toUpperCase())) + '</span>My demos'
                     : G + 'Sign in';
    el.title = u ? 'Signed in as ' + u.email : 'Sign in with Google to keep your demos in one place';
    var an = document.getElementById('lkp-an');
    if (u && u.admin && !an) { an = document.createElement('a'); an.id = 'lkp-an'; an.className = 'lkp-an'; an.href = '/analytics/'; an.textContent = 'Analytics \u2192'; document.body.appendChild(an); }
  }
  function boot() {
    render();
    track([{ t: 'page', path: '/', where: 'main' }]);
    if (/[?&]generate=1/.test(location.search)) setTimeout(function () { var b = document.querySelector('.aigen-btn'); if (b) b.click(); }, 600);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
