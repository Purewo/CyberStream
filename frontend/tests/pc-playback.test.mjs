import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

function loadModule(path, mocks = {}, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports, URL, Date, console,
    require: (specifier) => {
      assert.ok(Object.hasOwn(mocks, specifier), `Unexpected dependency: ${specifier}`);
      return mocks[specifier];
    }, ...globals,
  }, { filename: path });
  return exports;
}

function ticketClient(fetchImpl, getApiBase = () => 'https://backend.example/api') {
  return loadModule('api/playbackTicket.ts', { '../platform': { getApiBase } }, { fetch: fetchImpl });
}

const ticketResponse = (ticket, ttl = 60) => ({
  ok: true,
  json: async () => ({ code: 200, data: { ticket, ttl, expires_at: Math.floor(Date.now() / 1000) + ttl } }),
});

test('native ticket requests carry session cookies, deduplicate and cache short valid TTLs', async () => {
  let requests = 0;
  const api = ticketClient(async (url, options) => {
    requests += 1;
    assert.equal(url, 'https://backend.example/api/v1/auth/playback-ticket');
    assert.equal(options.credentials, 'include');
    assert.equal(options.method, 'POST');
    return ticketResponse('test-ticket');
  });
  assert.deepEqual(await Promise.all([api.ensureTicket(), api.ensureTicket()]), ['test-ticket', 'test-ticket']);
  assert.equal(await api.ensureTicket(), 'test-ticket');
  assert.equal(requests, 1);
});

test('logout invalidation discards a pending old-session ticket', async () => {
  let completeOld;
  let calls = 0;
  const api = ticketClient(async () => {
    calls += 1;
    if (calls === 1) return new Promise(resolve => { completeOld = resolve; });
    return ticketResponse('new-session');
  });
  const old = api.ensureTicket();
  api.invalidateTicket();
  assert.equal(await api.ensureTicket(), 'new-session');
  completeOld(ticketResponse('old-session'));
  assert.equal(await old, null);
  assert.equal(await api.ensureTicket(), 'new-session');
});

test('changing the backend never reuses or accepts the previous backend ticket', async () => {
  let base = 'https://old.example/api';
  let completeOld;
  const api = ticketClient(async url => url.startsWith('https://old.example/')
    ? new Promise(resolve => { completeOld = resolve; }) : ticketResponse('new-backend'), () => base);
  const old = api.ensureTicket();
  base = 'https://new.example/api';
  assert.equal(await api.ensureTicket(), 'new-backend');
  completeOld(ticketResponse('old-backend'));
  assert.equal(await old, null);
  assert.equal(await api.ensureTicket(), 'new-backend');
});

test('expired or malformed tickets fail closed', async () => {
  assert.equal(await ticketClient(async () => ticketResponse('expired', -1)).ensureTicket(), null);
  assert.equal(await ticketClient(async () => ({ ok: true, json: async () => ({ code: 200, data: { ticket: 'no-expiry' } }) })).ensureTicket(), null);
  assert.equal(await ticketClient(async () => ({ ok: false })).ensureTicket(), null);
});

test('ticket URLs preserve parameters/fragments, replace stale tickets, and never leak to external origins', () => {
  const { appendTicket } = ticketClient(() => { throw new Error('No request expected'); });
  const value = appendTicket('https://backend.example/api/v1/resources/id/stream?subtitle_id=x&ticket=stale#fragment', 'valid + ticket');
  const parsed = new URL(value);
  assert.equal(parsed.searchParams.get('subtitle_id'), 'x');
  assert.deepEqual(parsed.searchParams.getAll('ticket'), ['valid + ticket']);
  assert.equal(parsed.hash, '#fragment');
  for (const url of ['https://cdn.example/api/v1/file', 'https://backend.example/unrelated', '//evil.example/api/v1/stream']) {
    assert.equal(appendTicket(url, 'sensitive'), url);
  }
  assert.equal(appendTicket('/api/v1/resources/id/stream', 'valid'), 'https://backend.example/api/v1/resources/id/stream?ticket=valid');
});

test('history sorting uses actual last_watched and preserves specials season zero', async () => {
  const module = loadModule('api/user.ts', {
    '../platform': { getApiBase: () => 'https://backend.example/api' },
    './core': {
      fetchApi: async (_path, options) => {
        assert.equal(options.cache, 'no-store');
        return { items: [
          { resource_id: 'old', last_watched: '2026-01-01T00:00:00', movie: { id: 'm1' } },
          { resource_id: 'new', last_watched: '2026-02-01T00:00:00', season: 0, movie: { id: 'm2', target_season: 2 } },
          { resource_id: 'missing', movie: { id: 'm3' } },
        ] };
      },
      mapApiMovieToUi: movie => movie,
    },
  });
  const history = await module.userService.getHistory();
  assert.deepEqual(Array.from(history, item => item.resourceId), ['new', 'old', 'missing']);
  assert.equal(history[0].target_season, 0);
  assert.equal(history[0].user_data.season, 0);
});

test('native bridge forwards the ticket and detailed subtitle metadata to Rust', async () => {
  let invoked;
  const bridge = loadModule('platform/nativePlayer.ts', {
    '@tauri-apps/api/core': { invoke: async (command, args) => { invoked = { command, args }; } },
    '../api/user': { unlockBehaviorAchievement: async () => false },
  });
  await bridge.launchNativePlayer({
    url: 'https://backend.example/api/v1/resources/r/stream?ticket=valid',
    apiBase: 'https://backend.example', deviceId: 'device', playbackTicket: 'valid',
    currentResourceId: 'r', movie: { id: 'm', title: 'Movie', resources: [{
      id: 'r', url: 'stream', subtitles: [{ id: 's', url: 'subtitle', language: '简体中文', source: 'online_bound', providerName: 'provider' }],
    }] },
  });
  assert.equal(invoked.command, 'open_pc_player');
  assert.equal(invoked.args.options.playbackTicket, 'valid');
  assert.equal(invoked.args.options.apiBase, 'https://backend.example');
  assert.equal(invoked.args.options.movie.resources[0].subtitles[0].language, '简体中文');
});

test('PC backend configuration accepts root URLs and preserves explicit loopback choices', () => {
  const stored = new Map();
  const localStorage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) };
  const pc = loadModule('platform/pc.ts', {}, { localStorage });
  const platform = pc.createPcPlatform();
  pc.setApiBase(' https://backend.example:884/ ');
  assert.equal(platform.getApiBase(), 'https://backend.example:884/api');
  pc.setApiBase('http://localhost:5004/api/');
  assert.equal(platform.getApiBase(), 'http://localhost:5004/api');
  assert.throws(() => pc.setApiBase('file:///private'));
  assert.throws(() => pc.setApiBase('https://user:password@example.test/api'));
  assert.equal(platform.getApiBase(), 'http://localhost:5004/api');
});
