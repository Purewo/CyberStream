// Compare declared application methods against the real old APK (not dependencies).
const fs = require('node:fs'), path = require('node:path');
const Zip = require('./project/node_modules/adm-zip');
function methods(apk) {
  const result = new Set();
  for (const entry of new Zip(apk).getEntries().filter(e => /^classes\d*\.dex$/.test(e.entryName))) {
    const b = entry.getData(), u32 = p => b.readUInt32LE(p), u16 = p => b.readUInt16LE(p);
    function uleb(state) { let n = 0, shift = 0, v; do { v = b[state.p++]; n |= (v & 127) << shift; shift += 7; } while (v & 128); return n >>> 0; }
    const strings = Array.from({length: u32(0x38)}, (_, i) => {
      const s = { p: u32(u32(0x3c) + i * 4) }; uleb(s);
      return b.toString('utf8', s.p, b.indexOf(0, s.p));
    });
    const types = Array.from({length: u32(0x40)}, (_, i) => strings[u32(u32(0x44) + i * 4)]);
    const protos = Array.from({length: u32(0x48)}, (_, i) => {
      const p = u32(0x4c) + i * 12, off = u32(p + 8);
      const args = off ? Array.from({length: u32(off)}, (_, j) => types[u16(off + 4 + j * 2)]).join('') : '';
      return `(${args})${types[u32(p + 4)]}`;
    });
    for(let i = 0; i < u32(0x60); i++) {
      const p = u32(0x64) + i * 32, cls = types[u32(p)], data = u32(p + 24);
      if (!cls.startsWith('Lcom/purewo/cyberstream/') || !data) continue;
      const state = {p: data}, counts = [uleb(state), uleb(state), uleb(state), uleb(state)];
      for(let j = 0; j < counts[0] + counts[1]; j++) { uleb(state); uleb(state); }
      for(const count of counts.slice(2)) {
        let id = 0;
        for(let j = 0; j < count; j++) {
          id += uleb(state); uleb(state); uleb(state);
          const m = u32(0x5c) + id * 8, name = strings[u32(m + 4)];
          // Synthetic/lambda numbering changes with compiler or source ordering.
          if (/\$|<clinit>/.test(name) || cls.includes('$$')) continue;
          result.add(`${cls}::${name}${protos[u16(m + 2)]}`);
        }
      }
    }
  }
  return result;
}
const original = methods(path.join(__dirname, 'original-apks/CyberStream-original-debug.apk'));
const rebuilt = methods(path.join(__dirname, 'project/android/app/build/outputs/apk/debug/app-debug.apk'));
const audit = { original: original.size, rebuilt: rebuilt.size, missing: [...original].filter(m => !rebuilt.has(m)), added: [...rebuilt].filter(m => !original.has(m)) };
fs.writeFileSync(path.join(__dirname, 'native-method-audit.json'), JSON.stringify(audit, null, 2));
console.log(JSON.stringify(audit, null, 2));
