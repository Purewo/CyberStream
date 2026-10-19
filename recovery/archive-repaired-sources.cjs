const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const Zip=require('../frontend/node_modules/adm-zip');
const root=path.resolve(__dirname,'..');
const mode=process.argv[2]||'';
if(!['','final','ui-controls'].includes(mode))throw new Error('Unknown snapshot label');
const suffix=mode?'-'+mode:'';
const archivePath=path.join(__dirname,'CyberStream-PC-recovered-source-20260930'+suffix+'.zip');
if(fs.existsSync(archivePath))throw new Error('Preserve the existing recovery archive; do not overwrite');
const directories=['frontend/src','frontend/tests','pc/src-tauri/src','pc/src-tauri/icons','pc/src-tauri/capabilities','pc/scripts'];
const files=['frontend/package.json','frontend/package-lock.json','frontend/index.html','frontend/vite.config.ts','frontend/tsconfig.json','frontend/tailwind.config.cjs','frontend/postcss.config.cjs','pc/src-tauri/Cargo.toml','pc/src-tauri/Cargo.lock','pc/src-tauri/build.rs','pc/src-tauri/tauri.conf.json','pc/src-tauri/splash.html','pc/README.md','docs/PC_RECOVERY_2026-09-30.md'];
function walk(relative){for(const e of fs.readdirSync(path.join(root,relative),{withFileTypes:true})){const p=relative+'/'+e.name;if(e.isDirectory())walk(p);else if(e.isFile()&&!e.name.startsWith('.env'))files.push(p);}}
directories.forEach(walk);
const zip=new Zip(),manifest=[];
for(const relative of [...new Set(files)].sort()){
  const file=path.join(root,relative);if(!fs.existsSync(file))continue;
  const content=fs.readFileSync(file);
  zip.addFile(relative,content);
  manifest.push({path:relative,bytes:content.length,sha256:crypto.createHash('sha256').update(content).digest('hex')});
}
zip.addFile('SOURCE-MANIFEST.json',Buffer.from(JSON.stringify(manifest,null,2)));
zip.writeZip(archivePath);
const reopened=new Zip(archivePath);
for(const item of manifest){const content=reopened.readFile(item.path);if(!content||crypto.createHash('sha256').update(content).digest('hex')!==item.sha256)throw new Error('Archive verification failed: '+item.path);}
const result={archive:path.basename(archivePath),files:manifest.length,bytes:fs.statSync(archivePath).size,sha256:crypto.createHash('sha256').update(fs.readFileSync(archivePath)).digest('hex'),verified:true,excludesEnvDatabaseAndBinaries:true};
fs.writeFileSync(path.join(__dirname,'SOURCE-ARCHIVE'+suffix+'.json'),JSON.stringify(result,null,2),{flag:'wx'});
console.log(JSON.stringify(result,null,2));
