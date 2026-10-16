// Mints a join token for a fresh demo room and dispatches the agent to it.
// Env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, DEMO_PASSCODE, AGENT_NAME (default live-demo-lean).
//   GET/POST /api/token?code=<passcode>          -> 200 {url, token, room}
//   GET      /api/token?code=<passcode>&check=1  -> 200 {ok: true}, validates the code only (no room)
// 401 on a missing/wrong code (when DEMO_PASSCODE is set), 429 when the per-IP limit is hit.
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { AccessToken, RoomAgentDispatch, RoomConfiguration } from 'livekit-server-sdk';

const TTL = '2h';
const RATE_MAX = 5;                 // rooms per IP...
const RATE_WINDOW_MS = 10 * 60e3;   // ...per 10 minutes
// Best effort: lives per warm function instance, so it resets on cold starts and is not shared across regions.
const hits = new Map();             // ip -> [timestamps]

function clientIp(req) {
  const fwd = req.headers['x-forwarded-for'];
  if (fwd) return String(fwd).split(',')[0].trim();
  return req.headers['x-real-ip'] || req.socket?.remoteAddress || 'unknown';
}

function rateLimited(ip, now = Date.now()) {
  const recent = (hits.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (recent.length >= RATE_MAX) { hits.set(ip, recent); return Math.ceil((recent[0] + RATE_WINDOW_MS - now) / 1000); }
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 5000) for (const [k, v] of hits) if (!v.some((t) => now - t < RATE_WINDOW_MS)) hits.delete(k);
  return 0;
}

function codeOk(given) {
  const want = process.env.DEMO_PASSCODE;
  if (!want) return true;
  const h = (s) => createHash('sha256').update(String(s ?? '')).digest();
  return timingSafeEqual(h(given), h(want));
}

function queryParam(req, name) {
  if (req.query && req.query[name] !== undefined) return [].concat(req.query[name])[0];
  return new URL(req.url, 'http://x').searchParams.get(name);
}

function send(res, status, body, headers = {}) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
  res.end(JSON.stringify(body));
}

export default async function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'POST') return send(res, 405, { error: 'method not allowed' }, { Allow: 'GET, POST' });

  if (!codeOk(queryParam(req, 'code'))) return send(res, 401, { error: 'access code required' });
  if (queryParam(req, 'check')) return send(res, 200, { ok: true });

  const { LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET } = process.env;
  if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET) return send(res, 500, { error: 'server not configured' });

  const retry = rateLimited(clientIp(req));
  if (retry) return send(res, 429, { error: 'too many demos started, try again later', retry_after_s: retry }, { 'Retry-After': String(retry) });

  const room = 'faan-live-' + randomBytes(3).toString('hex');
  const at = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, { identity: 'customer', name: 'Customer', ttl: TTL });
  at.addGrant({ roomJoin: true, room, canUpdateOwnMetadata: true });   // the page sets faan.mode
  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: process.env.AGENT_NAME || 'live-demo-lean' })],
  });
  return send(res, 200, { url: LIVEKIT_URL, token: await at.toJwt(), room });
}
