const fs = require('node:fs');
const path = require('node:path');
const root = 'C:/Users/28788/.claude/projects/G--AI-AI-private-Cluade-code-projects-CyberStream-repo';
const calls = new Map(), results = new Map();
for (const name of fs.readdirSync(root).filter(n=>n.endsWith('.jsonl'))) {
  for (const [i,line] of fs.readFileSync(path.join(root,name),'utf8').split(/\r?\n/).entries()) {
    let r; try {r=JSON.parse(line);} catch {continue;}
    if (!Array.isArray(r.message?.content)) continue;
    for(const b of r.message.content) {
      if(b.type==='tool_use') calls.set(b.id,{...b,time:r.timestamp,source:name,line:i+1});
      if(b.type==='tool_result') results.set(b.tool_use_id,{...b,extra:r.toolUseResult,line:i+1});
    }
  }
}
const names=['tauri.conf.json','Cargo.toml','build.rs','src/lib.rs','src/proxy.rs','src/splash.rs','src/media_proxy.rs','src/external_player.rs'];
const files=new Map(),history=[];
for(const c of [...calls.values()].sort((a,b)=>a.time.localeCompare(b.time))) {
  const file=c.input?.file_path?.replaceAll('\\','/');
  if(!file?.includes('/pc/src-tauri/'))continue;
  const relative=file.split('/pc/src-tauri/')[1];
  if(!names.includes(relative))continue;
  const r=results.get(c.id);
  if(!r||r.is_error||!['Edit','Write'].includes(c.name))continue;
  let text;
  if(c.name==='Edit') {
    if(typeof r.extra?.originalFile!=='string') continue;
    const orig=r.extra.originalFile,old=c.input.old_string;
    if(!old||!orig.includes(old))continue;
    text=c.input.replace_all?orig.split(old).join(c.input.new_string):orig.replace(old,()=>c.input.new_string);
  } else if(typeof c.input.content==='string'&&r.extra?.content===c.input.content) text=c.input.content;
  else continue;
  const evidence={relative,source:c.source,line:c.line,resultLine:r.line,time:c.time};
  files.set(relative,{text,evidence});history.push(evidence);
}
const out=path.join(__dirname,'shell-source-candidate');
fs.mkdirSync(out,{recursive:true});
for(const [relative,{text}]of files){const target=path.join(out,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,text);}
fs.writeFileSync(path.join(out,'provenance.json'),JSON.stringify(history,null,2));
console.log(JSON.stringify([...files].map(([relative,v])=>({...v.evidence,bytes:Buffer.byteLength(v.text)})),null,2));
