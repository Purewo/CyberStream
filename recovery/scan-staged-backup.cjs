// Narrow, local pre-push gate. Prints locations/rule names, never matched secrets.
// This is a focused leak check, not a claim of exhaustive security review.
const fs = require('node:fs'), cp = require('node:child_process');
const Zip = require('./android-20261020/project/node_modules/adm-zip');
const paths = cp.execFileSync('git', ['diff', '--cached', '--name-only', '-z'], {maxBuffer: 8e6}).toString().split('\0').filter(Boolean);
const rules = [
  ['private-key', /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/g],
  ['github-token', /\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}/g],
  ['api-secret-key', /\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}/g],
  ['aws-access-key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ['jwt', /\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}/g],
  ['url-credentials', /https?:\/\/[^\s/:"'<>]{2,}:[^\s/@"'<>]{6,}@/g],
];
const hits = [], suspiciousAssignments = [], large = [], forbidden = [], syntheticFixtures = [];
function inspect(name, data) {
  const content = data.toString('utf8');
  for(const [rule, expression] of rules) {
    expression.lastIndex = 0;
    for(const match of content.matchAll(expression)) {
      const line = content.slice(0,match.index).split('\n').length;
      const fullLine = content.split('\n')[line - 1];
      // Reviewed negative test for rejecting credentials, not a real account.
      if (rule === 'url-credentials' && name.endsWith('frontend/tests/pc-playback.test.mjs')
        && fullLine.includes('assert.throws') && fullLine.includes('@example.test/api')) {
        syntheticFixtures.push({file:name,line});
      } else hits.push({file:name,rule,line});
    }
  }
  const assignments = /(?:api[_-]?key|access[_-]?token|password|secret|token)["']?\s*[:=]\s*["']([^"'\r\n]{16,})["']/gi;
  for(const m of content.matchAll(assignments)) {
    if (/^(?:[A-Z_]+|[a-z_]+)$/.test(m[1]) || /test|example|dummy|placeholder|replace|process\.|os\.|getenv|env\.|localhost|127\.0\.0\.1|token$|password$|secret$/i.test(m[1])) continue;
    suspiciousAssignments.push({file:name,line:content.slice(0,m.index).split('\n').length});
  }
}
for(const name of paths) {
  if (/(^|\/)(?:\.env(?:\..*)?|Cookies|Login Data|Web Data|Local State|local\.properties|signing\.properties|key\.properties)$|\.(?:jks|keystore|pfx|p12|db|sqlite3?)$/i.test(name)
    && !/\.env\.(?:example|local\.example)$/.test(name)) forbidden.push(name);
  const data = cp.execFileSync('git', ['show', `:${name}`], {maxBuffer: 110 * 1024 * 1024});
  if(data.length > 50 * 1024 * 1024) large.push({file:name,bytes:data.length});
  if (/\.(?:apk|zip|aar)$/.test(name)) {
    for(const e of new Zip(data).getEntries()) {
      if(/(^|\/)(?:\.env(?:\..*)?|Cookies|Login Data|local\.properties)$|\.(?:jks|keystore|pfx|p12)$/i.test(e.entryName)) forbidden.push(`${name}!${e.entryName}`);
      if(!e.isDirectory && /\.(?:tsx?|jsx?|cjs|mjs|json|md|py|rs|toml|properties|xml|gradle|ps1)$/.test(e.entryName)) inspect(`${name}!${e.entryName}`,e.getData());
    }
  } else if (!data.subarray(0,8192).includes(0)) inspect(name,data);
}
console.log(JSON.stringify({stagedFiles:paths.length,highConfidenceHits:hits,reviewLocations:suspiciousAssignments,forbiddenPaths:forbidden,over50MiB:large,reviewedSyntheticFixtures:syntheticFixtures.length},null,2));
if(hits.length || forbidden.length || large.length) process.exitCode = 1;
