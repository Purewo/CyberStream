import fs from 'node:fs/promises';
import path from 'node:path';

const apiBase = (process.env.OPENAPI_BASE_URL
  || 'https://apicyber.gameuniverse.top:40162/api/v1').replace(/\/+$/, '');

async function fetchText(route) {
  const response = await fetch(`${apiBase}${route}`);
  if (!response.ok) {
    throw new Error(`GET ${route} failed with HTTP ${response.status}`);
  }
  return response.text();
}

const docsEnvelope = JSON.parse(await fetchText('/docs'));
const docs = docsEnvelope?.data;
const version = docs?.openapi_version;
if (!version || !/^[0-9A-Za-z._-]+$/.test(version)) {
  throw new Error(`Invalid OpenAPI version: ${String(version)}`);
}

const spec = JSON.parse(await fetchText('/openapi.json'));
if (spec?.openapi !== '3.0.0' || spec?.info?.version !== version || !spec?.paths) {
  throw new Error('The backend returned an invalid or mismatched OpenAPI document');
}

const outputDirectory = path.resolve(`openapi-${version}`);
await fs.mkdir(outputDirectory, { recursive: true });
const formattedSpec = `${JSON.stringify(spec, null, 2)}\n`;
await fs.writeFile('openapi.json', formattedSpec, 'utf8');
await fs.writeFile(
  path.join(outputDirectory, `openapi-${version}.json`),
  formattedSpec,
  'utf8',
);
await fs.writeFile(
  path.join(outputDirectory, 'docs-index.json'),
  `${JSON.stringify(docsEnvelope, null, 2)}\n`,
  'utf8',
);

for (const document of docs.documents || []) {
  if (!/^[0-9A-Za-z._-]+$/.test(document.key)) continue;
  await fs.writeFile(
    path.join(outputDirectory, `${document.key}.md`),
    await fetchText(`/docs/${encodeURIComponent(document.key)}`),
    'utf8',
  );
}

console.log(
  `Synced OpenAPI ${version}: ${Object.keys(spec.paths).length} paths, `
  + `${(docs.documents || []).length} documents`,
);
