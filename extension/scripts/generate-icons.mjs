// Generates the extension's PNG icons at build time with zero image-library
// dependencies: a hand-rolled PNG encoder (zlib for the DEFLATE stream) and a
// small software rasterizer for a rounded-square "flow" glyph.
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const outDirs = [resolve(root, "assets/icons"), resolve(root, "dist/assets/icons")];

const BG = [79, 70, 229]; // indigo-600
const FG = [255, 255, 255];

function crc32(buf) {
  let c;
  const table = crc32.table || (crc32.table = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c;
    }
    return t;
  })());
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

function encodePng(width, height, rgba) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0; // filter type: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, y * stride + stride);
  }
  const idatData = deflateSync(raw, { level: 9 });

  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", idatData),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function isInRoundedRect(x, y, size, radius) {
  const min = radius;
  const max = size - radius;
  if (x >= min && x <= max) return y >= 0 && y <= size;
  if (y >= min && y <= max) return x >= 0 && x <= size;
  const cx = x < min ? min : max;
  const cy = y < min ? min : max;
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= radius * radius;
}

// A simple forward/"resume" chevron-arrow glyph made of two overlapping
// triangles, evoking "queue -> resume".
function isInGlyph(nx, ny) {
  // nx, ny normalized to [0,1]
  function triangle(px, py, ax, ay, bx, by, cx, cy) {
    const d = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    const w1 = ((bx - px) * (cy - py) - (by - py) * (cx - px)) / d;
    const w2 = ((cx - px) * (ay - py) - (cy - py) * (ax - px)) / d;
    const w3 = 1 - w1 - w2;
    return w1 >= 0 && w2 >= 0 && w3 >= 0;
  }
  const t1 = triangle(nx, ny, 0.28, 0.2, 0.28, 0.8, 0.62, 0.5);
  const t2 = triangle(nx, ny, 0.5, 0.2, 0.5, 0.8, 0.84, 0.5);
  return t1 || t2;
}

function renderIcon(size) {
  const rgba = Buffer.alloc(size * size * 4);
  const radius = Math.round(size * 0.22);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const bg = isInRoundedRect(x, y, size, radius);
      const glyph = bg && isInGlyph(x / size, y / size);
      const color = glyph ? FG : bg ? BG : [0, 0, 0];
      const alpha = bg ? 255 : 0;
      rgba[i] = color[0];
      rgba[i + 1] = color[1];
      rgba[i + 2] = color[2];
      rgba[i + 3] = alpha;
    }
  }
  return encodePng(size, size, rgba);
}

for (const dir of outDirs) mkdirSync(dir, { recursive: true });

for (const size of [16, 32, 48, 128]) {
  const png = renderIcon(size);
  for (const dir of outDirs) {
    writeFileSync(resolve(dir, `icon-${size}.png`), png);
  }
}

console.log("[generate-icons] wrote icon-16/32/48/128.png");
