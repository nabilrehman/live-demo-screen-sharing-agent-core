// Join token for an AI-generated demo (pages at /v2/<slug>/, published to Vercel Blob by generator-v2/host/publish.py).
// Dispatches the shared LiveKit Cloud agent (GEN_AGENT_NAME, default demo-gen) with {slug, v}: v is the demo's newest
// knowledge-pack version, so an Edit reaches the next call with no redeploy. No passcode, like the build host it replaces.
// Env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, BLOB_READ_WRITE_TOKEN, GEN_PACK_PREFIX, GEN_AGENT_NAME.
//   GET /api/gen-token?brain=<slug>-grok   -> 200 {url, token, room}; 404 when the demo isn't published (or was deleted)
import { randomBytes } from 'node:crypto';
import { list } from '@vercel/blob';
import { AccessToken, RoomAgentDispatch, RoomConfiguration } from 'livekit-server-sdk';

const RATE_MAX = 30, RATE_WINDOW_MS = 10 * 60e3;
const hits = new Map();   // best effort, per warm instance (same as api/token.js)

function rateLimited(ip, now = Date.now()) {
  const recent = (hits.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (recent.length >= RATE_MAX) { hits.set(ip, recent); return Math.ceil((recent[0] + RATE_WINDOW_MS - now) / 1000); }
  recent.push(now); hits.set(ip, recent);
  return 0;
}

function send(res, status, body, headers = {}) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
  res.end(JSON.stringify(body));
}

// newest complete version: the manifest is written last
async function packVersion(slug) {
  const prefix = `${process.env.GEN_PACK_PREFIX}/${slug}/`;
  const { blobs } = await list({ prefix, limit: 1000 });
  const vs = blobs.filter((b) => b.pathname.endsWith('/manifest.json')).map((b) => b.pathname.slice(prefix.length).split('/')[0]);
  return vs.sort().pop();
}

export default async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'POST') return send(res, 405, { error: 'method not allowed' }, { Allow: 'GET, POST' });
  const q = new URL(req.url, 'http://x').searchParams;
  const m = /^([a-z0-9][a-z0-9-]{0,63}?)-grok$/.exec(q.get('brain') || '');
  if (!m) return send(res, 400, { error: 'unknown demo' });
  const slug = m[1];

  const { LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, GEN_PACK_PREFIX } = process.env;
  if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET || !GEN_PACK_PREFIX) return send(res, 500, { error: 'server not configured' });

  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'unknown';
  const retry = rateLimited(ip);
  if (retry) return send(res, 429, { error: 'too many demos started, try again later', retry_after_s: retry }, { 'Retry-After': String(retry) });

  const v = await packVersion(slug);
  if (!v) return send(res, 404, { error: 'This demo is not live (it may have been deleted)' });

  const room = `gen-${slug}-` + randomBytes(3).toString('hex');
  const at = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, { identity: 'customer', name: 'Customer', ttl: '2h' });
  at.addGrant({ roomJoin: true, room, canUpdateOwnMetadata: true });
  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: process.env.GEN_AGENT_NAME || 'demo-gen', metadata: JSON.stringify({ slug, v }) })],
  });
  return send(res, 200, { url: LIVEKIT_URL, token: await at.toJwt(), room });
}
