// Quick & dirty icon generator: produce a 1024x1024 PNG with a cyber-cyan
// gradient and a black 'C' glyph centered. Output file goes to argv[2].
// Used once at M0 to seed `cargo tauri icon`. Replace with the real artwork
// before M5.
const { PNG } = require('pngjs');
const fs = require('node:fs');

const W = 1024, H = 1024;
const out = process.argv[2];
if (!out) { console.error('usage: gen_seed_icon.cjs <out.png>'); process.exit(1); }

const png = new PNG({ width: W, height: H });

function color(x, y) {
  // Diagonal gradient #050505 -> #00f3ff
  const t = (x + y) / (W + H);
  return [
    Math.round(0x05 * (1 - t) + 0x00 * t),
    Math.round(0x05 * (1 - t) + 0xf3 * t),
    Math.round(0x05 * (1 - t) + 0xff * t),
    255,
  ];
}

// Crude 'C' mask: outer ring of a circle + open right side
function isC(x, y) {
  const cx = W / 2, cy = H / 2;
  const dx = x - cx, dy = y - cy;
  const r = Math.sqrt(dx * dx + dy * dy);
  const rOuter = W * 0.40, rInner = W * 0.30;
  if (r > rOuter || r < rInner) return false;
  // Open the right side (angles between -45 and +45 deg from +X)
  const ang = Math.atan2(dy, dx); // -PI..PI
  if (ang > -Math.PI / 5 && ang < Math.PI / 5) return false;
  return true;
}

for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4;
    if (isC(x, y)) {
      png.data[i] = 0x00; png.data[i + 1] = 0x00; png.data[i + 2] = 0x00; png.data[i + 3] = 255;
    } else {
      const [r, g, b, a] = color(x, y);
      png.data[i] = r; png.data[i + 1] = g; png.data[i + 2] = b; png.data[i + 3] = a;
    }
  }
}

png.pack().pipe(fs.createWriteStream(out)).on('finish', () => {
  console.log('wrote', out);
});
