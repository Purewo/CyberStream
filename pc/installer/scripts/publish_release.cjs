// 一次性发布脚本：创建 GitHub release + 上传 lite 资产。
// token 从 stdin 第一行读，绝不写盘、绝不打印。用完即弃。
const fs = require('fs');
const https = require('https');

const REPO = 'Purewo/CyberStream';
const TAG = 'v1.21.1-pc.5';
const NAME = 'CyberStream PC 1.21.1-pc.5';
const NOTES = 'pc/RELEASE_NOTES_1.21.1-pc.5.md';
const ASSET = 'pc/installer/dist/CyberStream_1.21.1-pc.5_lite_x64_setup.exe';

const token = fs.readFileSync(0, 'utf8').trim();
if (!token) { console.error('no token on stdin'); process.exit(1); }

function req(opts, body) {
  return new Promise((resolve, reject) => {
    const r = https.request(opts, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks) }));
    });
    r.on('error', reject);
    if (body) r.write(body);
    r.end();
  });
}

(async () => {
  const notes = fs.readFileSync(NOTES, 'utf8');
  const payload = JSON.stringify({
    tag_name: TAG, name: NAME, body: notes, draft: false, prerelease: false,
  });

  // 1) create release
  const create = await req({
    method: 'POST',
    hostname: 'api.github.com',
    path: `/repos/${REPO}/releases`,
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github+json',
      'User-Agent': 'cyberstream-release',
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  }, payload);

  if (create.status !== 201) {
    console.error(`create release failed: HTTP ${create.status}`);
    console.error(create.body.toString().slice(0, 800));
    process.exit(1);
  }
  const rel = JSON.parse(create.body.toString());
  console.log(`release created: id=${rel.id}`);
  console.log(`html_url: ${rel.html_url}`);

  // 2) upload asset
  const data = fs.readFileSync(ASSET);
  const assetName = ASSET.split('/').pop();
  console.log(`uploading ${assetName} (${(data.length / 1048576).toFixed(1)} MB)...`);
  const up = await req({
    method: 'POST',
    hostname: 'uploads.github.com',
    path: `/repos/${REPO}/releases/${rel.id}/assets?name=${encodeURIComponent(assetName)}`,
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github+json',
      'User-Agent': 'cyberstream-release',
      'Content-Type': 'application/octet-stream',
      'Content-Length': data.length,
    },
  }, data);

  if (up.status !== 201) {
    console.error(`asset upload failed: HTTP ${up.status}`);
    console.error(up.body.toString().slice(0, 800));
    console.error(`NOTE: release ${rel.id} exists but has no asset — fix or delete it.`);
    process.exit(1);
  }
  const asset = JSON.parse(up.body.toString());
  console.log(`asset uploaded: ${asset.name} state=${asset.state} size=${asset.size}`);
  console.log(`download: ${asset.browser_download_url}`);
})().catch((e) => { console.error(e); process.exit(1); });
