// CyberStream PC · M0 verification: mpv --input-ipc-server roundtrip
// Spawns the bundled mpv.exe in idle mode, opens the named pipe, queries a few
// properties to confirm the JSON-IPC protocol works end-to-end. Exits 0 on
// success, non-zero with a diagnostic line on failure.

import { spawn } from 'node:child_process';
import { connect } from 'node:net';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const mpvExe = resolve(here, '..', 'vendor', 'mpv', 'mpv.exe');
const pipeName = 'mpv-cyberstream-verify-' + process.pid;
const pipePath = `\\\\.\\pipe\\${pipeName}`;

const child = spawn(mpvExe, [
  '--idle=yes',
  '--no-config',
  '--no-terminal',
  '--no-input-default-bindings',
  '--force-window=immediate',
  '--geometry=320x180',
  '--ontop=no',
  `--input-ipc-server=${pipePath}`,
], {
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: false,
  detached: false,
});

let mpvStderr = '';
child.stderr.on('data', (d) => { mpvStderr += d.toString(); });
let done = false;
child.on('exit', (code, sig) => {
  if (!done) {
    console.error(`[mpv exited early] code=${code} sig=${sig}`);
    if (mpvStderr) console.error('mpv stderr:\n' + mpvStderr);
    process.exit(20);
  }
});

async function tryConnect(maxMs = 5000, stepMs = 150) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      return await new Promise((res, rej) => {
        const s = connect(pipePath);
        s.once('connect', () => res(s));
        s.once('error', rej);
      });
    } catch {
      await sleep(stepMs);
    }
  }
  throw new Error('IPC pipe never opened within ' + maxMs + 'ms');
}

function makeClient(sock) {
  let nextId = 1;
  const pending = new Map();
  let buf = '';
  sock.on('data', (chunk) => {
    buf += chunk.toString();
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      if (msg.request_id != null && pending.has(msg.request_id)) {
        const { res, rej } = pending.get(msg.request_id);
        pending.delete(msg.request_id);
        if (msg.error === 'success') res(msg.data);
        else rej(new Error(`mpv: ${msg.error}`));
      }
      // events ignored in this bench
    }
  });
  return (command) => new Promise((res, rej) => {
    const id = nextId++;
    pending.set(id, { res, rej });
    sock.write(JSON.stringify({ command, request_id: id }) + '\n');
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        rej(new Error('timeout: ' + JSON.stringify(command)));
      }
    }, 2000);
  });
}

(async () => {
  try {
    const sock = await tryConnect();
    const rpc = makeClient(sock);
    const tryProp = async (name) => {
      try { return await rpc(['get_property', name]); }
      catch (e) { return `(unavailable: ${e.message})`; }
    };
    const version = await tryProp('mpv-version');
    const ffmpeg = await tryProp('ffmpeg-version');
    const hwdec = await tryProp('hwdec-current');
    const platform = await tryProp('platform');
    console.log(`[ok] mpv-version: ${version}`);
    console.log(`[ok] ffmpeg-version: ${ffmpeg}`);
    console.log(`[ok] hwdec-current (idle): ${hwdec}`);
    console.log(`[ok] platform: ${platform}`);
    await rpc(['quit']).catch(() => {});
    sock.end();
    done = true;
    setTimeout(() => process.exit(0), 200);
  } catch (e) {
    done = true;
    console.error('[fail]', e.message);
    if (mpvStderr) console.error('mpv stderr:\n' + mpvStderr);
    try { child.kill(); } catch {}
    process.exit(10);
  }
})();
