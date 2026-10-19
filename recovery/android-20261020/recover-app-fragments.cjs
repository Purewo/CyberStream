// Data-only reconstruction of independently anchored historical App hunks.
// A hunk is accepted only when its full preimage occurs exactly once.
const fs = require('node:fs');
const path = require('node:path');
const events = JSON.parse(fs.readFileSync(path.join(__dirname, 'successful-changes.json'), 'utf8'));
const destination = path.join(__dirname, 'App.fragments.tsx');
if (fs.existsSync(destination)) throw new Error('Preserve existing candidate');
let lines = fs.readFileSync(path.join(__dirname, '../../frontend/src/App.tsx'), 'utf8').replace(/\r\n/g, '\n').split('\n');
const audit = [];
events.forEach((event, eventIndex) => {
  if (event.file !== 'src/App.tsx' || !event.unified_diff) return;
  const hunks = [];
  let h;
  for (const line of event.unified_diff.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('@@ ')) { h = { header: line, before: [], after: [] }; hunks.push(h); }
    else if (h && line.startsWith(' ')) { h.before.push(line.slice(1)); h.after.push(line.slice(1)); }
    else if (h && line.startsWith('-')) h.before.push(line.slice(1));
    else if (h && line.startsWith('+')) h.after.push(line.slice(1));
  }
  hunks.forEach((h, hunkIndex) => {
    const matches = fragment => {
      if (!fragment.length) return [];
      const result = [];
      for (let i = 0; i <= lines.length - fragment.length; i++) {
        if (fragment.every((s, j) => lines[i + j] === s)) result.push(i);
      }
      return result;
    };
    const positions = matches(h.before);
    let status;
    if (positions.length === 1) { lines.splice(positions[0], h.before.length, ...h.after); status = 'applied'; }
    else if (matches(h.after).length === 1) status = 'already-present';
    else status = 'unresolved';
    audit.push({eventIndex, hunkIndex, header: h.header, status, before: status === 'unresolved' ? h.before : undefined, after: status === 'unresolved' ? h.after : undefined});
  });
});
fs.writeFileSync(destination, lines.join('\n'));
fs.writeFileSync(path.join(__dirname, 'app-fragments-audit.json'), JSON.stringify(audit, null, 2));
console.log(JSON.stringify({applied: audit.filter(x => x.status === 'applied').length, alreadyPresent: audit.filter(x => x.status === 'already-present').length, unresolved: audit.filter(x => x.status === 'unresolved')}));
