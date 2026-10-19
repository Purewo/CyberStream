// Restore successful file-change events as data; never execute historical commands.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..');
const session='C:/Users/28788/.codex/sessions/2026/07/10/rollout-2026-07-10T05-28-16-019f48c8-07b3-77c2-91ef-4deb1b6da6f7.jsonl';
const oldRoot='G:/AI/AI_private/Cluade_code_projects/CyberStream-frontend-hosted-beta/';
const integrate=process.argv.includes('--project');
const out=path.join(__dirname,integrate?'project':'historical');
const auditPath=path.join(__dirname,integrate?'project-replay-audit.json':'reconstruction-audit.json');
if(integrate&&fs.existsSync(auditPath))throw new Error('Project already replayed; preserve its subsequent edits');
const state=new Map(),audit=[],events=[];
const seeded=new Set(),deleted=new Set();
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const normalize=s=>s.replace(/\r\n/g,'\n');
function relative(p){p=p.replaceAll('\\','/');if(!p.toLowerCase().startsWith(oldRoot.toLowerCase()))return null;const rel=p.slice(oldRoot.length);if(rel.includes('..')||/(^|\/)\.env(?:\.|$)|keystore|\.jks$|local\.properties|gradle\.properties/i.test(rel))return null;return rel;}
function applyDiff(text,diff){
  const lines=normalize(text).split('\n');if(lines.at(-1)==='')lines.pop();
  const hunks=[];let h;
  for(const line of normalize(diff).split('\n')){
    const m=line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if(m){h={start:Number(m[1]),old:[],next:[]};hunks.push(h);continue;}
    if(!h||line.startsWith('\\'))continue;
    if(line.startsWith(' ')){h.old.push(line.slice(1));h.next.push(line.slice(1));}
    else if(line.startsWith('-'))h.old.push(line.slice(1));
    else if(line.startsWith('+'))h.next.push(line.slice(1));
  }
  if(!hunks.length)throw new Error('No unified hunks');
  let shift=0;
  for(const h of hunks){
    const match=p=>p>=0&&p+h.old.length<=lines.length&&h.old.every((s,i)=>lines[p+i]===s);
    let pos=Math.max(0,h.start-1)+shift;
    if(!match(pos)){
      if(!h.old.length)throw new Error('Unanchored insertion');
      const positions=[];for(let p=0;p<=lines.length-h.old.length;p++)if(match(p))positions.push(p);
      if(positions.length!==1)throw new Error('Context matches '+positions.length+' locations');
      pos=positions[0];
    }
    lines.splice(pos,h.old.length,...h.next);shift=pos-Math.max(0,h.start-1)+h.next.length-h.old.length;
  }
  return lines.join('\n')+'\n';
}
let lineNo=0;
for(const line of fs.readFileSync(session,'utf8').split(/\r?\n/)){
  lineNo++;let r;try{r=JSON.parse(line)}catch{continue;}
  const p=r.payload;if(r.type!=='event_msg'||p?.type!=='patch_apply_end'||p.success!==true)continue;
  for(const [file,change]of Object.entries(p.changes||{})){
    const rel=relative(file);if(!rel)continue;
    if(integrate&&!seeded.has(rel)){
      seeded.add(rel);const target=path.join(out,rel);
      if(fs.existsSync(target))state.set(rel,normalize(fs.readFileSync(target,'utf8')));
    }
    const record={file:rel,time:r.timestamp,line:lineNo,callId:p.call_id,type:change.type};
    const event={...record,...change};events.push(event);
    try{
      if(change.type==='add'){state.set(rel,normalize(change.content));deleted.delete(rel);record.status='restored-add';}
      else if(change.type==='delete'){state.delete(rel);deleted.add(rel);record.status='deleted-by-history';}
      else if(change.type==='update'){
        if(!state.has(rel))throw new Error('Baseline absent');
        state.set(rel,applyDiff(state.get(rel),change.unified_diff));record.status='replayed-update';
      }else throw new Error('Unknown change type');
      if(state.has(rel))record.sha256=hash(state.get(rel));
    }catch(e){record.status='needs-baseline-or-merge';record.reason=e.message;}
    audit.push(record);
  }
}
fs.mkdirSync(out,{recursive:true});
for(const [rel,content]of state){const dest=path.join(out,rel);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,content);}
if(integrate)for(const rel of deleted){const dest=path.resolve(out,rel);if(!dest.startsWith(out+path.sep))throw new Error('Unsafe deletion');if(fs.existsSync(dest))fs.unlinkSync(dest);}
const files=[...state].map(([file,text])=>({file,bytes:Buffer.byteLength(text),sha256:hash(text),lines:text.split('\n').length}));
if(!integrate)fs.writeFileSync(path.join(__dirname,'successful-changes.json'),JSON.stringify(events,null,2));
fs.writeFileSync(auditPath,JSON.stringify({session,files,audit},null,2));
console.log(JSON.stringify({files:files.length,restoredAdd:audit.filter(r=>r.status==='restored-add').length,replayedUpdate:audit.filter(r=>r.status==='replayed-update').length,needsMerge:audit.filter(r=>r.status==='needs-baseline-or-merge').length,androidFiles:files.filter(r=>r.file.startsWith('android/')),missing:[...new Set(audit.filter(r=>r.status==='needs-baseline-or-merge').map(r=>r.file))]},null,2));
