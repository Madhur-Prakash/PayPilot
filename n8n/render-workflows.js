// Fill in the workflow templates at container start (Render).
//
//   node render-workflows.js <templates-dir> <out-dir>
//
// The image is built once, but the three values the workflows need - the shared
// HMAC secret, the backend URL and the merchant id - only exist as environment
// variables on the running service (Render generates the secret). So the image
// carries workflows with placeholders and this fills them in just before import.
//
// The values land inside JavaScript string literals inside JSON strings, so they
// are restricted to characters that need no escaping in either. Anything else is
// refused rather than escaped: a secret that cannot be embedded safely should fail
// the boot loudly, not produce a workflow that quietly signs with the wrong key.

const fs = require('fs');
const path = require('path');

const [, , inDir, outDir] = process.argv;
if (!inDir || !outDir) {
  console.error('usage: node render-workflows.js <templates-dir> <out-dir>');
  process.exit(2);
}

function fail(message) {
  console.error(`[pga] ${message}`);
  process.exit(1);
}

const secret = process.env.N8N_WEBHOOK_SECRET || '';
if (!/^[A-Za-z0-9+/=_.~-]{16,}$/.test(secret)) {
  fail('N8N_WEBHOOK_SECRET is missing, shorter than 16 characters, or contains characters that cannot be embedded safely.');
}

const backend = (process.env.PGA_BACKEND_URL || '').replace(/\/+$/, '');
if (!/^https?:\/\/[A-Za-z0-9.:_-]+$/.test(backend)) {
  fail('PGA_BACKEND_URL must be a bare origin such as https://paypilot-api.onrender.com (no path, no spaces).');
}

// Optional: only the two scheduled workflows need it, and they say so clearly when
// it is missing, so the event router and the health check still come up.
const merchant = process.env.PGA_MERCHANT_ID || '';
if (merchant && !/^[0-9a-fA-F-]{36}$/.test(merchant)) {
  fail('PGA_MERCHANT_ID must be a UUID.');
}
if (!merchant) {
  console.warn('[pga] PGA_MERCHANT_ID is not set - the 02:00 sweep and 06:30 growth scan will refuse to run until it is.');
}

const replacements = [
  ['__PGA_SECRET__', secret],
  ['__PGA_BACKEND_URL__', backend],
  ['__PGA_MERCHANT_ID__', merchant],
];

fs.mkdirSync(outDir, { recursive: true });
let count = 0;
for (const name of fs.readdirSync(inDir).filter((f) => f.endsWith('.json'))) {
  let text = fs.readFileSync(path.join(inDir, name), 'utf8');
  for (const [placeholder, value] of replacements) {
    text = text.split(placeholder).join(value);
  }
  if (text.includes('__PGA_')) {
    fail(`${name} still contains an unfilled placeholder.`);
  }
  JSON.parse(text); // refuse to hand n8n something it cannot import
  fs.writeFileSync(path.join(outDir, name), text);
  count += 1;
}
console.log(`[pga] rendered ${count} workflows -> ${outDir} (backend ${backend})`);
