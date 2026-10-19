// Extract only application assets/code, never device data or credentials.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const Zip = require('./project/node_modules/adm-zip');
const target = path.join(__dirname, 'original-debug-unpacked');
if (fs.existsSync(target)) throw new Error('Preserve existing original extraction');
const zip = new Zip(path.join(__dirname, 'original-apks/CyberStream-original-debug.apk'));
const inventory = [];
for (const entry of zip.getEntries()) {
  if (entry.isDirectory || !/^(assets\/public\/|assets\/capacitor|classes\d*\.dex$|lib\/)/.test(entry.entryName)) continue;
  const name = entry.entryName;
  if (name.split('/').includes('..')) throw new Error('Unsafe APK entry');
  const bytes = entry.getData(), file = path.join(target, name);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, bytes);
  inventory.push({name, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex')});
}
fs.writeFileSync(path.join(__dirname, 'original-extraction-inventory.json'), JSON.stringify(inventory, null, 2));
console.log(JSON.stringify({ files: inventory.length, bytes: inventory.reduce((n, f) => n + f.bytes, 0), sourceMaps: inventory.filter(f => f.name.endsWith('.map')).length }));
