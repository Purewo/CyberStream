const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/App.tsx'), 'utf8');
const ast = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const needed = ['withTimeout', 'getAndroidPlaybackCatalog', 'resolveAndroidNativeUrl', 'resolveAndroidArtworkUrl', 'createAndroidPlaybackSession'];
const declarations = new Map();
function visit(node) {
  if (ts.isVariableDeclaration(node) && needed.includes(node.name.getText(ast))) {
    declarations.set(node.name.getText(ast), `const ${node.getText(ast)};`);
  }
  ts.forEachChild(node, visit);
}
visit(ast);
for (const name of needed) assert.ok(declarations.has(name), `missing production function ${name}`);
const js = ts.transpileModule(needed.map(name => declarations.get(name)).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const base = 'https://pioneer.fan:884/api';
function runtime(groups = null) {
  const dependencies = {
    getApiBase: () => base,
    movieService: { getResources: async () => groups, getStreamUrl: id => `${base}/v1/resources/${id}/stream` },
    ensureTicket: async () => 'test-only-ticket',
    appendTicket: (url, ticket) => {
      if (!ticket) return url;
      const parsed = new URL(url);
      if (parsed.origin !== new URL(base).origin || !parsed.pathname.startsWith('/api/')) return url;
      parsed.searchParams.set('ticket', ticket);
      return parsed.href;
    },
    resolveAssetUrl: value => value,
    needsUserAgentRewrite: () => false,
    pickUserAgentForRewrite: () => undefined,
  };
  return new Function(...Object.keys(dependencies), `${js}\nreturn {${needed.join(',')}}`)(...Object.values(dependencies));
}
const resource = (id, extra = {}) => ({ id, filename: `${id}.mkv`, source_id: 1, source_name: 'test', ...extra });
test('native URLs retain API prefix and external CDN stays external', () => {
  const { resolveAndroidNativeUrl: resolve } = runtime();
  for (const input of ['/api/v1/resources/1/stream', '/v1/resources/1/stream']) {
    assert.equal(resolve(input), `${base}/v1/resources/1/stream`);
  }
  assert.equal(resolve('https://cdn.example/file.mkv'), 'https://cdn.example/file.mkv');
});
test('API unavailable falls back to embedded resources including season zero', async () => {
  const api = runtime();
  const item = resource('special', { season: 0, episode: 1 });
  const catalog = await api.getAndroidPlaybackCatalog({ id: 'show', resources: [item] });
  assert.equal(catalog.resources[0].id, 'special');
  assert.equal(catalog.seasons[0].season, 0);
});
test('version 2 session restores native metadata, seasons, subtitles and explicit cloud choices', async () => {
  const item = resource('episode-2', { season: 0, episode: 2, size_bytes: 1234,
    playback: { cloud_transcode: { supported: true, provider: 'test' },
      subtitles: { default_subtitle_id: 'sub', items: [{ id: 'sub', format: 'srt',
        web_player: { format: 'vtt', url: '/api/v1/subtitles/sub/stream', supported: true } }] } },
  });
  const session = await runtime().createAndroidPlaybackSession({ id: 7, title: 'Test', type: 'series' },
    { resourceId: item.id, startTime: 12 }, { resources: [item], seasons: [{ season: 0, displayTitle: 'Specials', resourceIds: [item.id] }] });
  assert.equal(session.version, 2);
  assert.equal(session.contentKind, 'series');
  assert.equal(session.startTimeMs, 12000);
  assert.equal(session.resources[0].season, 0);
  assert.equal(session.resources[0].technical.sizeBytes, 1234);
  assert.equal(session.resources[0].subtitles[0].mimeType, 'text/vtt');
  assert.equal(session.resources[0].subtitles[0].isDefault, true);
  assert.match(session.resources[0].cloudTranscode.qualitiesUrl, /\/api\/v1\/resources\/episode-2\/streaming-qualities\?ticket=/);
  assert.match(session.resources[0].onlineSubtitles.defaultKeyword, /S00E02/);
  assert.match(session.resources[0].onlineSubtitles.downloadUrl, /\/online\/download\?ticket=/);
});
test('alternate movie sources are not mislabeled as episodes', async () => {
  const session = await runtime().createAndroidPlaybackSession({ id: 1, title: 'Film', type: 'movie' }, {},
    { resources: [resource('a'), resource('b')], seasons: [] });
  assert.equal(session.contentKind, 'movie');
  assert.equal(session.initialResourceId, 'a');
});
test('artwork never leaks playback tickets to external CDN', () => {
  const api = runtime();
  assert.equal(api.resolveAndroidArtworkUrl('https://cdn.example/poster.jpg', 'test-only-ticket'), 'https://cdn.example/poster.jpg');
});
test('slow advisory work has a bounded fallback', async () => {
  assert.equal(await runtime().withTimeout(new Promise(() => {}), 10, 'fallback'), 'fallback');
});
test('recovery package identity cannot replace either old release or debug', () => {
  const gradle = fs.readFileSync(path.join(__dirname, '../android/app/build.gradle'), 'utf8');
  assert.match(gradle, /applicationIdSuffix '\.recovery'/);
  const config = fs.readFileSync(path.join(__dirname, '../capacitor.config.ts'), 'utf8');
  assert.match(config, /hostname: 'localhost'/);
});
