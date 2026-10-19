// Native players cannot access the WebView's HttpOnly session cookie.
// Exchange that session for a short-lived credential; keep it in memory only.
import { getApiBase } from '../platform';

interface CachedTicket {
  base: string;
  ticket: string;
  expiresAt: number;
}

let cached: CachedTicket | null = null;
let generation = 0;
let inflight: { base: string; generation: number; promise: Promise<string | null> } | null = null;

export function invalidateTicket(): void {
  generation += 1;
  cached = null;
  inflight = null;
}

export async function ensureTicket(): Promise<string | null> {
  const base = getApiBase().replace(/\/+$/, '');
  if (cached?.base === base && Date.now() < cached.expiresAt) return cached.ticket;
  if (inflight?.base === base && inflight.generation === generation) return inflight.promise;
  const requestGeneration = generation;
  const request = { base, generation: requestGeneration, promise: Promise.resolve<string | null>(null) };
  request.promise = (async () => {
    try {
      const response = await fetch(`${base}/v1/auth/playback-ticket`, {
        method: 'POST', credentials: 'include', cache: 'no-store',
      });
      if (!response.ok) return null;
      const body = await response.json();
      if (body?.code !== 200 && body?.code !== 20000) return null;
      const data = body.data;
      if (typeof data?.ticket !== 'string' || !data.ticket) return null;
      if (generation !== requestGeneration || getApiBase().replace(/\/+$/, '') !== base) return null;
      const now = Date.now();
      const expiresAt = Number(data.expires_at) * 1000;
      const ttl = Number(data.ttl) * 1000;
      // Never extend a credential whose server-provided expiry has passed.
      const expiry = Number.isFinite(expiresAt) && expiresAt > 0
        ? expiresAt : Number.isFinite(ttl) && ttl > 0 ? now + ttl : now;
      if (expiry <= now) return null;
      const margin = Math.min(5 * 60 * 1000, (expiry - now) / 10);
      cached = { base, ticket: data.ticket, expiresAt: expiry - margin };
      return data.ticket as string;
    } catch {
      return null;
    } finally {
      if (inflight === request) inflight = null;
    }
  })();
  inflight = request;
  return request.promise;
}

/** Only attach backend credentials to that backend's API, never a CDN URL. */
export function appendTicket(url: string, ticket: string | null): string {
  if (!url || !ticket) return url;
  try {
    const base = new URL(`${getApiBase().replace(/\/+$/, '')}/`);
    const target = new URL(url, base);
    if (target.origin !== base.origin || !target.pathname.startsWith(base.pathname)) return url;
    target.searchParams.set('ticket', ticket);
    return target.href;
  } catch {
    return url;
  }
}
