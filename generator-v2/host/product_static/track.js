/* LiveKit demo generator - demo-session tracker (injected by host/product.py into every /v2/<slug>/ page).
 * Who: lk_u=<scoped token> from the main site link (kept in localStorage), else an anonymous id.
 * What: open/page, heartbeat every 15 s (active + voice seconds, cumulative per tab session), voice start/end,
 *       and an rrweb DOM recording (inputs masked) streamed to /api/p/replay/<sid> for the analytics page player.
 * Never blocks the demo: everything is wrapped, failures are silent. */
(function () {
  try {
    var m = location.pathname.match(/^\/v2\/([a-z0-9-]+)\//); if (!m) return;
    var slug = m[1], API = location.origin, q = new URLSearchParams(location.search), ls = window.localStorage, ss = window.sessionStorage;
    var tok = q.get('lk_u'); if (tok) { try { ls.setItem('lk.u', tok); } catch (e) {} }
    tok = tok || (function () { try { return ls.getItem('lk.u'); } catch (e) { return null; } })();
    var anon = (function () { try { var a = ls.getItem('lk.anon'); if (!a) { a = 'anon-' + Math.random().toString(36).slice(2, 12); ls.setItem('lk.anon', a); } return a; } catch (e) { return 'anon'; } })();
    var key = 'lk.track.' + slug, st = (function () { try { return JSON.parse(ss.getItem(key)) || null; } catch (e) { return null; } })();
    var fresh = !st;
    if (!st) st = { sid: slug + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8), active: 0, voice: 0 };
    function save() { try { ss.setItem(key, JSON.stringify(st)); } catch (e) {} }
    save();
    function payload(evs) { return JSON.stringify({ session: tok || undefined, uid: tok ? undefined : anon, events: evs }); }
    function send(evs, beacon) {
      var b = payload(evs.map(function (e) { e.slug = slug; e.sid = st.sid; e.path = location.pathname.replace('/v2/' + slug, '') || '/'; return e; }));
      try { if (beacon && navigator.sendBeacon) { navigator.sendBeacon(API + '/api/p/event', new Blob([b], { type: 'text/plain' })); return; } } catch (e) {}
      try { fetch(API + '/api/p/event', { method: 'POST', body: b, headers: { 'Content-Type': 'text/plain' }, keepalive: true }); } catch (e) {}
    }
    send([{ t: fresh ? 'open' : 'page', title: document.title }]);
    // active + voice time: tick every second while the tab is visible / while a call is live
    function live() { var r = document.getElementById('lk-root') || document.getElementById('kai-root'); return !!(r && r.classList.contains('live')); }
    var wasLive = false, n = 0;
    setInterval(function () {
      var vis = document.visibilityState === 'visible', l = live();
      if (vis) st.active++; if (l) st.voice++;
      if (l && !wasLive) send([{ t: 'voice_start' }]);
      if (!l && wasLive) send([{ t: 'voice_end', voice_s: st.voice }]);
      wasLive = l; save();
      if (++n % 15 === 0) send([{ t: 'hb', active_s: st.active, voice_s: st.voice }]);
    }, 1000);
    addEventListener('pagehide', function () { send([{ t: 'unload', active_s: st.active, voice_s: st.voice }], true); flush(true); });
    // optional PostHog (only if configured on the host)
    fetch(API + '/api/p/config').then(function (r) { return r.json(); }).then(function (c) {
      if (!c.posthog_key) return;
      !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys onSessionId".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
      window.posthog.init(c.posthog_key, { api_host: c.posthog_host, person_profiles: 'identified_only', session_recording: { maskAllInputs: true } });
      var who = null; try { who = tok ? JSON.parse(atob(tok.split('.')[0].replace(/-/g, '+').replace(/_/g, '/'))) : null; } catch (e) {}
      if (who && who.e) window.posthog.identify(who.e, { name: who.n });
      window.posthog.register({ demo: slug, lk_sid: st.sid });
    }).catch(function () {});
    // rrweb recording -> /api/p/replay/<sid>
    var buf = [], bytes = 0, stopped = false;
    function flush(beacon) {
      if (!buf.length) return; var evs = buf; buf = [];
      var b = JSON.stringify({ slug: slug, uid: tok ? 'user' : anon, events: evs }); bytes += b.length;
      if (bytes > 25e6) { stopped = true; return; }
      try { if (beacon && navigator.sendBeacon && b.length < 60000) { navigator.sendBeacon(API + '/api/p/replay/' + st.sid, new Blob([b], { type: 'text/plain' })); return; } } catch (e) {}
      try { fetch(API + '/api/p/replay/' + st.sid, { method: 'POST', body: b, headers: { 'Content-Type': 'text/plain' }, keepalive: b.length < 60000 }); } catch (e) {}
    }
    var s = document.createElement('script'); s.src = API + '/p/rrweb-record.min.js'; s.async = true;
    s.onload = function () {
      try {
        var rec = (window.rrwebRecord && (window.rrwebRecord.record || window.rrwebRecord.default)) || null; if (!rec) return;
        rec({ emit: function (e) { if (!stopped) buf.push(e); if (buf.length > 400) flush(); }, maskAllInputs: true,
              sampling: { mousemove: 80, scroll: 150, input: 'last' }, inlineStylesheet: true, collectFonts: false, recordCanvas: false,
              blockSelector: '[data-lk-noreplay]' });
        setInterval(function () { flush(); }, 5000);
      } catch (e) {}
    };
    (document.head || document.documentElement).appendChild(s);
  } catch (e) { /* never break the demo */ }
})();
