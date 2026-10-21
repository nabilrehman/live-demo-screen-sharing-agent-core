# Adding Kai to windcreek.com: integration guide

Kai is a voice concierge that runs inside the page. It is one script tag. It reads the page it is on, talks with the
guest, and can move them around the site. It never touches accounts, bookings or forms.

## 1. Add the tag
Add this to the site template, just before `</body>`, on every page where Kai should be available. You can also
inject it from your tag manager as a custom HTML tag that fires on all pages.

```html
<script src="https://live-demos-sa.vercel.app/embed/windcreek/kai.js" defer></script>
```

Optional attributes:

| Attribute | Default | Meaning |
|---|---|---|
| `data-site-root` | `/` | The path the site lives under. Paths Kai sees and opens are relative to it. |
| `data-token-url` | `/api/token` on the script's origin | Where the widget gets a LiveKit join token (see section 6). |
| `data-code` | `open` | Access code passed to the token endpoint. |
| `data-property` | the first path segment | Pins the property for this page, for example `bethlehem`. |

The widget renders inside a shadow DOM: it can't change your styles, and your CSS can't reach in. It adds one fixed
`<div id="kai-root">` and one `@font-face` style. The voice client (livekit-client 2.22.3) and the fonts are
self-hosted next to `kai.js`. Nothing loads from third-party CDNs.

## 2. Content Security Policy
If you send a CSP header, allow:

```
script-src   https://live-demos-sa.vercel.app
style-src    https://live-demos-sa.vercel.app 'unsafe-inline'
font-src     https://live-demos-sa.vercel.app
connect-src  https://live-demos-sa.vercel.app wss://*.livekit.cloud https://*.livekit.cloud
media-src    blob:
```

`'unsafe-inline'` is only needed for the one `@font-face` block. When you self-host the files (section 6), swap in
your own origin.

## 3. What the widget reads (and doesn't)
It reads generic DOM only, from `<main>` (or `<body>` without one), and skips header, nav, footer and anything
`aria-hidden`:

- the URL path, the title, and the property (from the path)
- h1 to h4 headings, the section in view, and the visible text (trimmed to 4 KB)
- links in view (label and path)
- the text of the last element clicked

It never reads form fields (`input`, `select`, `textarea`), cookies, local storage or account data. To hide any other
element from Kai, mark it `data-kai-private`.

**Richer context (optional).** Give Kai structured data by setting `window.KaiContext`, either an object or a
function that returns one. It's sent as `site_context` with every snapshot:

```js
window.KaiContext = () => ({
  property: 'bethlehem',
  promotions: [{ id: 'choose-your-ride', date: '2026-10-25', title: '$255,000 Choose Your Ride' }],
  // only with the guest's consent and once they're signed in:
  // rewards: { tier: 'Escape', tier_points: 23150 }
});
```

## 4. What Kai can do on the page (allow-list)
Kai can only do the following. Each action returns a fresh page snapshot:

| Action | What it does |
|---|---|
| `navigate` | Opens another page of the same site. It never opens sign-in, sign-up, password, profile, account, reservations, win/loss, careers, application, checkout, payment or cart pages, or anything off-site. The agent and the widget each enforce this list. |
| `scroll_to` | Scrolls to a heading. |
| `highlight` | Draws a glow over headings, cards, table columns or rows, or buttons. It's an overlay, so your DOM is never changed. |
| `read_section` | Reads the text under one heading. |
| `clear_highlight` | Removes the glow. |

Kai never fills in forms, clicks booking or payment buttons, or signs anyone in.

**Your own actions.** Register a function and it becomes available to Kai, by name, with your description. Kai can't
call anything you haven't registered:

```js
window.Kai.registerAction('show_map', ({ venue }) => openPropertyMap(venue), 'Open the property map at a venue');
```

## 5. Multi-page behavior, privacy and consent
- **Across page loads.** The call keeps going when the page changes. The room and token are kept in `sessionStorage`
  (this tab only), the next page rejoins the same conversation, and the agent waits up to 30 seconds. **End** clears
  it.
- **Consent.** The panel says Kai is an AI, that it sees the page but not the account, that it doesn't book, sign in
  or ask for personal details, and gives the 21+ and 1-800-GAMBLER line. The microphone turns on only after the guest
  presses **Start talking**.
- **Data.** Each conversation produces one structured summary: intents, entities, pages, actions, unanswered
  questions, hand-offs and latency. It contains no names, contact details, account or payment data, and you choose
  where it goes. Audio isn't recorded unless you turn recording on.
- **Responsible gaming copy.** Kai is told to never encourage gambling or chasing losses, to give no odds or strategy,
  and to give 1-800-GAMBLER when someone signals a problem. This is tested on every eval run.

## 6. Moving it to your own backend
1. **Token endpoint.** Host an endpoint that mints a LiveKit access token for one room and dispatches the agent. It's
   about 30 lines with `livekit-server-sdk`. Point `data-token-url` at it. Keep the API secret server-side, add rate
   limits, and allow CORS from your own origins only.
2. **Agent.** The agent is open source (LiveKit Agents, Python). Run it on LiveKit Cloud or self-host it. Choose the
   model with one setting: Gemini Live, Grok, OpenAI, or open-weight models.
3. **Widget files.** Self-host `kai.js`, `kai.css`, `livekit-client.umd.js` and the fonts on your CDN, then update the
   tag and your CSP.

## 7. Presenter bookmarklet (demo only)
This shows Kai on the live windcreek.com without changing the site. Make a bookmark whose URL is:

```
javascript:(function(){if(window.__kai){window.Kai&&Kai.open();return}var s=document.createElement('script');s.src='https://live-demos-sa.vercel.app/embed/windcreek/kai.js';s.dataset.mode='shell';s.dataset.siteRoot='/';document.body.appendChild(s)})();
```

<!-- bookmarklet -->

Open windcreek.com and click the bookmark. The widget keeps the call in the current tab, and the site's own pages load
in a full-window frame underneath it. This works because windcreek.com allows same-origin framing. The token endpoint
must allow CORS from `https://windcreek.com`. A reload ends the call; click the bookmark again to start over.
