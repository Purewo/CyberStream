import fs from 'node:fs';

const historyPath = 'C:/Users/28788/.claude/projects/G--AI-AI-private-Cluade-code-projects-CyberStream-repo/b1a4dd9d-b98c-406f-879d-cc5c9eabc9db.jsonl';
const rows = fs.readFileSync(historyPath, 'utf8').split('\n').filter(Boolean).map((s, i) => ({ row: JSON.parse(s), line: i + 1 }));
const uses = new Map();
const results = new Map();
for (const { row, line } of rows) {
  for (const block of row.message?.content ?? []) {
    if (block.type === 'tool_use') uses.set(block.id, { ...block, line, timestamp: row.timestamp });
    if (block.type === 'tool_result') results.set(block.tool_use_id, { ...block, line, toolUseResult: row.toolUseResult });
  }
}
const targets = /CyberStream-frontend-hosted-beta[\\/]src[\\/](platform[\\/](nativePlayer|pc)\.ts|api[\\/](auth|user)\.ts|App\.tsx)$/i;
const matched = [...uses.values()].filter(u => targets.test(u.input?.file_path ?? ''));
if (process.argv[2] === 'installed-evidence') {
  const bundlePath = 'recovery/installed-pc-20260930/extracted/assets/index-Bdh2Yexe.js';
  const bundle = fs.readFileSync(bundlePath, 'utf8');
  const markers = ['playbackTicket', 'auth/playback-ticket', 'last_watched', 'cyber_theme', 'user/preferences', 'subtitle_error', '1.21.1-pc.7'];
  console.log(JSON.stringify(markers.map(marker => {
    const offset = bundle.indexOf(marker);
    return { marker, offset, found: offset >= 0, context: offset >= 0 ? bundle.slice(Math.max(0, offset - 70), offset + marker.length + 110) : '' };
  }), null, 2));
} else if (process.argv[2] === 'integrated-snapshot-patch') {
  const paths = ['App.tsx', 'api/user.ts'];
  console.log(JSON.stringify({ patch: '*** Begin Patch\n' + paths.map(path => {
    const content = fs.readFileSync(`frontend/src/${path}`, 'utf8').replaceAll('\r\n', '\n');
    return `*** Add File: recovery/pc-source-candidate/frontend/${path}\n` + content.split('\n').map(line => '+' + line).join('\n') + '\n';
  }).join('') + '*** End Patch' }));
} else if (process.argv[2] === 'list-src') {
  const paths = new Map();
  for (const u of uses.values()) {
    if (!/CyberStream-frontend-hosted-beta[\\/]src[\\/]/i.test(u.input?.file_path ?? '')) continue;
    const path = u.input.file_path;
    paths.set(path, [...(paths.get(path) ?? []), { line: u.line, name: u.name, originalType: typeof results.get(u.id)?.toolUseResult?.originalFile }]);
  }
  console.log(JSON.stringify([...paths], null, 2));
} else if (process.argv[2] === 'fragment-patch') {
  const entries = [...uses.values()].filter(u => /CyberStream-frontend-hosted-beta[\\/]src[\\/]/i.test(u.input?.file_path ?? '') && ['Edit', 'Write'].includes(u.name) && results.has(u.id) && !results.get(u.id).is_error);
  const proof = entries.map(u => ({ line: u.line, resultLine: results.get(u.id).line, timestamp: u.timestamp, toolUseId: u.id, name: u.name, input: u.input, fullOriginalAvailable: typeof results.get(u.id).toolUseResult?.originalFile === 'string' }));
  const files = [['historical-successful-edits.json', JSON.stringify(proof, null, 2)]];
  for (const u of entries.filter(u => [15695, 17437].includes(u.line))) {
    const relative = u.input.file_path.replace(/^.*CyberStream-frontend-hosted-beta[\\/]src[\\/]/i, '').replaceAll('\\', '/');
    files.push([relative, u.input.content]);
  }
  console.log(JSON.stringify({ patch: '*** Begin Patch\n' + files.map(([path, content]) => `*** Add File: recovery/pc-source-candidate/frontend/${path}\n` + content.replaceAll('\r\n', '\n').split('\n').map(line => '+' + line).join('\n') + '\n').join('') + '*** End Patch' }));
} else if (process.argv[2] === 'source-detail') {
  for (const u of [...uses.values()].filter(u => process.argv.slice(3).includes(String(u.line)))) console.log(JSON.stringify({ use: u, result: results.get(u.id) }, null, 2));
} else if (process.argv[2] === 'list') {
  console.log(JSON.stringify(matched.map(u => ({ line: u.line, name: u.name, path: u.input.file_path, error: results.get(u.id)?.is_error, originalType: typeof results.get(u.id)?.toolUseResult?.originalFile, read: results.get(u.id)?.toolUseResult?.file ? { ...results.get(u.id).toolUseResult.file, content: '<omitted>' } : null })), null, 2));
} else if (process.argv[2] === 'detail') {
  for (const u of matched.filter(u => process.argv.slice(3).includes(String(u.line)))) {
    console.log(JSON.stringify({ use: u, result: results.get(u.id) }, null, 2));
  }
} else if (process.argv[2] === 'edits') {
  for (const u of matched.filter(u => u.name === 'Edit')) console.log(JSON.stringify({ line: u.line, input: u.input }, null, 2));
} else if (process.argv[2] === 'candidate-patch') {
  const latest = new Map();
  for (const u of matched) {
    const result = results.get(u.id);
    if (!result || result.is_error || u.name !== 'Edit' || typeof result.toolUseResult?.originalFile !== 'string') continue;
    const { old_string, new_string, replace_all } = u.input;
    let content = result.toolUseResult.originalFile;
    if (!content.includes(old_string)) throw new Error(`Edit ${u.line} does not match its originalFile`);
    content = replace_all ? content.split(old_string).join(new_string) : content.replace(old_string, new_string);
    const relative = u.input.file_path.replace(/^.*CyberStream-frontend-hosted-beta[\\/]src[\\/]/i, '').replaceAll('\\', '/');
    latest.set(relative, { content, line: u.line, resultLine: result.line, timestamp: u.timestamp, toolUseId: u.id });
  }
  const manifest = [...latest].map(([path, { content, ...evidence }]) => ({ path, ...evidence, source: historyPath }));
  const files = [...latest].map(([path, entry]) => [path, entry.content]);
  files.push(['evidence.json', JSON.stringify(manifest, null, 2) + '\n']);
  console.log(JSON.stringify({ patch: '*** Begin Patch\n' + files.map(([path, content]) => `*** Add File: recovery/pc-source-candidate/frontend/${path}\n` + content.replaceAll('\r\n', '\n').split('\n').map(line => '+' + line).join('\n') + '\n').join('') + '*** End Patch' }));
}
