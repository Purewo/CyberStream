// Recover only native Rust edits with matching successful tool results.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const historyRoot = 'C:/Users/28788/.claude/projects/G--AI-AI-private-Cluade-code-projects-CyberStream-repo';
const repoRoot = path.resolve(__dirname, '..');
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(dir, e.name)) : e.name.endsWith('.jsonl') ? [path.join(dir, e.name)] : []);
}
const calls = new Map();
const results = new Map();
for (const file of walk(historyRoot)) {
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    let row;
    try { row = JSON.parse(lines[i]); } catch { continue; }
    if (!Array.isArray(row.message?.content)) continue;
    for (const c of row.message.content) {
      if (c.type === 'tool_use') calls.set(c.id, { ...c, timestamp: row.timestamp, source: path.relative(historyRoot, file), line: i + 1 });
      if (c.type === 'tool_result') results.set(c.tool_use_id, { ...c, extra: row.toolUseResult, source: path.relative(historyRoot, file), line: i + 1 });
    }
  }
}
const selected = [...calls.values()].filter(c => /[\\/]pc[\\/]src-tauri[\\/]src[\\/]/.test(c.input?.file_path || '')).sort((a,b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
if (process.argv.includes('--list')) {
  for (const c of selected) {
    const r = results.get(c.id);
    console.log(JSON.stringify({ date: c.timestamp, name: c.name, id: c.id, path: c.input.file_path, line: c.line, source: c.source, chars: c.input.new_string?.length || c.input.content?.length || 0, result: r ? { is_error: r.is_error, keys: Object.keys(r.extra || {}), line: r.line } : null }));
  }
}
if (process.argv.includes('--sample')) {
  const pick = process.argv[process.argv.indexOf('--sample') + 1];
  const c = pick ? selected.find(c=>c.id===pick) : selected.findLast(c => c.name === 'Edit' && results.has(c.id));
  const r = results.get(c.id);
  console.log(JSON.stringify({ input: { ...c, input: Object.keys(c.input) }, result: { ...r, content: String(r.content).slice(0,300), extra: Object.fromEntries(Object.entries(r.extra || {}).map(([k,v])=>[k, {type: typeof v, chars: typeof v === 'string' ? v.length : undefined, keys: v && typeof v === 'object' ? Object.keys(v) : undefined}])) } }, null, 2));
}
if (process.argv.includes('--edits')) {
  for(const c of selected.filter(c=>c.timestamp>'2026-05-31'&&c.name==='Edit')) {
    console.log(JSON.stringify({date:c.timestamp,id:c.id,source:c.source,line:c.line,path:c.input.file_path,old:c.input.old_string.slice(0,70),new:c.input.new_string.slice(0,90)}));
  }
}
if (process.argv.includes('--commands')) {
  for (const c of calls.values()) {
    const command = c.input?.command || '';
    if (c.name === 'Bash' && c.timestamp > '2026-05-31' && /native_player/.test(command)) {
      console.log(JSON.stringify({date:c.timestamp,source:c.source,line:c.line,id:c.id,chars:command.length,head:command.slice(0,220)}));
    }
  }
  const c = selected.findLast(c=>c.name==='Read' && /native_player/.test(c.input.file_path));
  const r = results.get(c.id);
  console.log(JSON.stringify({readSample:{id:c.id,input:c.input,extra:r.extra}},null,2));
}
if (process.argv.includes('--emit-native-patch')) {
  let patch = '*** Begin Patch\n';
  for (const name of fs.readdirSync(path.join(repoRoot,'pc/src-tauri/src/native_player'))) {
    if (!name.endsWith('.rs')) continue;
    const current = 'pc/src-tauri/src/native_player/' + name;
    const candidate = 'recovery/pc-source-candidate/' + current;
    let diff;
    try { diff = execFileSync('git',['diff','--no-index','--',current,candidate],{cwd:repoRoot,encoding:'utf8'}); }
    catch (e) { if(e.status!==1) throw e; diff=e.stdout; }
    if(!diff) continue;
    const body = diff.split('\n').filter(x=>!/^diff --git |^index |^--- |^\+\+\+ |^\\ No newline/.test(x)).map(x=>/^@@/.test(x)?'@@':x).join('\n').trimEnd();
    patch += '*** Update File: ' + current + '\n' + body + '\n';
  }
  patch += '*** End Patch';
  process.stdout.write(patch);
}
if (process.argv.includes('--recover')) {
  const latest = new Map();
  const audit = [];
  const readChecks = [];
  const cutoff = '2026-05-31T11:40:12.000Z';
  const nativeDir = path.join(repoRoot, 'pc/src-tauri/src/native_player');
  for (const name of fs.readdirSync(nativeDir)) {
    if (!name.endsWith('.rs')) continue;
    const relative = 'src-tauri/src/native_player/' + name;
    const content = execFileSync('git',['show','d853118d2d98299161fae284dd88026fb6406a65:pc/'+relative],{cwd:repoRoot,encoding:'utf8'}).replace(/\r\n/g,'\n');
    latest.set(relative,{ timestamp: cutoff, source: 'git:d853118d2d98299161fae284dd88026fb6406a65', method:'baseline', content, sha256:crypto.createHash('sha256').update(content).digest('hex'), relative });
  }
  for (const c of selected) {
    if (c.timestamp <= cutoff) continue;
    // The June 12 self-hosted checkout and the June 21 hosted checkout
    // were divergent branches, not one linear edit stream.
    if (!c.input.file_path.includes('CyberStream-frontend-hosted-beta')) continue;
    const r = results.get(c.id);
    if (!r || r.is_error) continue;
    const extra = r.extra;
    const record = { timestamp: c.timestamp, source: c.source, callLine: c.line, resultLine: r.line, id: c.id, path: c.input.file_path, method: c.name };
    const relative = c.input.file_path.replaceAll('\\','/').split('/pc/')[1];
    if (!relative || !relative.startsWith('src-tauri/src/') || !relative.endsWith('.rs') || relative.includes('..')) throw new Error('Unsafe candidate path');
    if (c.name === 'Read') {
      const f = extra?.file;
      const current = latest.get(relative)?.content;
      if (f?.content && current && /native_player/.test(relative)) {
        const excerpt = current.split('\n').slice(f.startLine-1,f.startLine-1+f.numLines).join('\n');
        readChecks.push({...record,status:excerpt.trimEnd()===f.content.trimEnd()?'matched':'mismatch',startLine:f.startLine,numLines:f.numLines});
      }
      continue;
    }
    if (!['Edit', 'Write'].includes(c.name)) continue;
    let content;
    if (c.name === 'Edit') {
      if (!extra || !String(r.content).includes('updated successfully')) { audit.push({...record,status:'unverified-edit'}); continue; }
      const original = typeof extra.originalFile === 'string' ? extra.originalFile : latest.get(relative)?.content;
      if (typeof original !== 'string') { audit.push({...record, status:'missing-original'}); continue; }
      const oldText = extra.oldString;
      const newText = extra.newString;
      if (oldText !== c.input.old_string || newText !== c.input.new_string || !oldText) { audit.push({...record, status:'mismatched-result'}); continue; }
      const count = original.split(oldText).length - 1;
      if (count < 1 || (count > 1 && !extra.replaceAll)) {
        audit.push({...record,status:'ambiguous-edit',count});
        if (process.argv.includes('--details') && /native_player/.test(relative)) {
          const firstLine = oldText.split('\n').find(x => x.trim().length > 15)?.trim();
          const pos = original.indexOf(firstLine);
          console.log(JSON.stringify({id:c.id, relative, old:oldText.slice(0,600), nearby:pos<0?'NOT_FOUND':original.slice(pos, pos+650), extraKeys:Object.keys(extra), cr:oldText.includes('\r') }));
        }
        continue;
      }
      content = extra.replaceAll ? original.split(oldText).join(newText) : original.replace(oldText, () => newText);
    } else {
      if (!extra || typeof c.input.content !== 'string' || extra.content !== c.input.content) { audit.push({...record,status:'unverified-write'}); continue; }
      content = c.input.content;
    }
    const sha256 = crypto.createHash('sha256').update(content).digest('hex');
    latest.set(relative, { ...record, content, sha256, relative });
    audit.push({...record,status:'verified',sha256});
  }
  const out = path.join(__dirname, 'pc-source-candidate');
  const files = [];
  for (const [relative, value] of latest) {
    const target = path.join(out,'pc',relative);
    fs.mkdirSync(path.dirname(target), {recursive:true});
    fs.writeFileSync(target, value.content, 'utf8');
    const {content,...provenance}=value;
    files.push({...provenance,bytes:Buffer.byteLength(content),lines:content.split('\n').length});
  }
  fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'native-source-provenance.json'),JSON.stringify({files,audit,readChecks},null,2)+'\n');
  console.log(JSON.stringify({files:files.map(x=>({relative:x.relative,lines:x.lines,timestamp:x.timestamp})),verified:audit.filter(x=>x.status==='verified').length,readMatched:readChecks.filter(x=>x.status==='matched').length,readMismatches:readChecks.filter(x=>x.status!=='matched'),skipped:audit.filter(x=>x.status!=='verified')},null,2));
}
