const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const Zip = require('./project/node_modules/adm-zip');
const output = path.resolve(process.argv[2]);
if (fs.existsSync(output)) throw new Error('Refusing to overwrite an existing handoff');
fs.mkdirSync(output, {recursive: true});
const copy = (source, name) => fs.copyFileSync(path.join(__dirname, source), path.join(output, name));
copy('project/android/app/build/outputs/apk/debug/app-debug.apk', 'CyberStream-Android-recovery-20261020.apk');
copy('original-apks/CyberStream-original-debug.apk', 'CyberStream-original-debug.apk');
copy('original-apks/CyberStream-original-release.apk', 'CyberStream-original-release.apk');
copy('RESTORATION.md', '先读我-恢复说明.md');
const zip = new Zip();
const project = path.join(__dirname, 'project');
const excluded = new Set(['node_modules', 'dist', 'build', '.gradle', '.kotlin', '.git', 'capacitor-cordova-android-plugins']);
function add(directory, relative = '') {
  for (const entry of fs.readdirSync(directory, {withFileTypes:true})) {
    if (excluded.has(entry.name) || /^\.env|\.jks$|\.keystore$|\.log$|^local\.properties$|^hs_err_|^replay_pid/.test(entry.name)) continue;
    const rel = path.posix.join(relative, entry.name);
    if (rel.startsWith('android/app/src/main/assets/')) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) add(absolute, rel);
    else if (entry.isFile()) zip.addLocalFile(absolute, path.posix.join('project', path.posix.dirname(rel)));
  }
}
add(project);
for (const name of ['RESTORATION.md', 'native-method-audit.json', 'original-extraction-inventory.json', 'browser-verification.json', 'webview-verification.json', 'project-replay-audit.json', 'app-fragments-audit.json', 'reconstruct.cjs', 'recover-app-fragments.cjs', 'compare-native.cjs']) {
  zip.addLocalFile(path.join(__dirname, name), 'provenance');
}
zip.writeZip(path.join(output, 'CyberStream-Android-recovered-source-20261020.zip'));
const manifest = fs.readdirSync(output).map(name => {
  const data = fs.readFileSync(path.join(output, name));
  return {name, bytes: data.length, sha256: crypto.createHash('sha256').update(data).digest('hex')};
});
fs.writeFileSync(path.join(output, 'SHA256.json'), JSON.stringify(manifest, null, 2));
fs.writeFileSync(path.join(__dirname, 'handoff-manifest.json'), JSON.stringify({output,files:manifest}, null, 2));
console.log(JSON.stringify({output,files:manifest},null,2));
