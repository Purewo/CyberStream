const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),out=path.join(__dirname,'project');
if(fs.existsSync(out))throw new Error('Recovery project already exists; refusing to overwrite');
fs.mkdirSync(out,{recursive:true});
for(const rel of ['src','public']){const src=path.join(root,'frontend',rel);if(fs.existsSync(src))fs.cpSync(src,path.join(out,rel),{recursive:true});}
for(const rel of ['index.html','tsconfig.json','vite.config.ts','tailwind.config.cjs','postcss.config.cjs']){const src=path.join(root,'frontend',rel);if(fs.existsSync(src))fs.copyFileSync(src,path.join(out,rel));}
const pkg=JSON.parse(fs.readFileSync(path.join(root,'frontend/package.json'),'utf8'));
pkg.name='cyberstream-android-recovery';pkg.version='1.21.1';
Object.assign(pkg.dependencies,{'@capacitor/core':'8.4.1','@capacitor/android':'8.4.1','@fontsource/orbitron':'5.2.6','@fontsource/rajdhani':'5.2.6','@fontsource/noto-sans-sc':'5.2.8'});
Object.assign(pkg.devDependencies,{'@capacitor/cli':'8.4.1'});
pkg.scripts['android:sync']='npm run build && cap sync android';
fs.writeFileSync(path.join(out,'package.json'),JSON.stringify(pkg,null,2)+'\n');
fs.writeFileSync(path.join(out,'capacitor.config.ts'),"import type { CapacitorConfig } from '@capacitor/cli';\n\nconst config: CapacitorConfig = {\n  appId: 'com.purewo.cyberstream',\n  appName: 'CyberStream',\n  webDir: 'dist'\n};\n\nexport default config;\n");
console.log(out);
