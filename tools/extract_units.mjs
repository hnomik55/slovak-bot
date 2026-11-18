// Извлекает массив UNITS из HTML-тренажёра в JSON.
// Использование: node tools/extract_units.mjs <path-to-slovencina.html>
// Печатает JSON в stdout, ошибки — в stderr с кодом 1.

import fs from 'node:fs';

const src = process.argv[2];
if (!src) {
  console.error('usage: node extract_units.mjs <html>');
  process.exit(1);
}

const html = fs.readFileSync(src, 'utf8');

const marker = 'const UNITS =';
const at = html.indexOf(marker);
if (at < 0) {
  console.error('не найдено "const UNITS =" в ' + src);
  process.exit(1);
}

// Ищем закрывающую скобку массива, пропуская строковые литералы и комментарии.
const start = html.indexOf('[', at);
let depth = 0;
let end = -1;
let i = start;
let quote = null;

while (i < html.length) {
  const ch = html[i];
  const next = html[i + 1];

  if (quote) {
    if (ch === '\\') { i += 2; continue; }
    if (ch === quote) quote = null;
    i += 1;
    continue;
  }

  if (ch === '"' || ch === "'" || ch === '`') { quote = ch; i += 1; continue; }

  if (ch === '/' && next === '/') {
    const nl = html.indexOf('\n', i);
    i = nl < 0 ? html.length : nl + 1;
    continue;
  }
  if (ch === '/' && next === '*') {
    const close = html.indexOf('*/', i);
    i = close < 0 ? html.length : close + 2;
    continue;
  }

  if (ch === '[' || ch === '{') depth += 1;
  else if (ch === ']' || ch === '}') {
    depth -= 1;
    if (depth === 0) { end = i; break; }
  }
  i += 1;
}

if (end < 0) {
  console.error('не удалось найти конец массива UNITS');
  process.exit(1);
}

const literal = html.slice(start, end + 1);

let units;
try {
  // eslint-disable-next-line no-new-func
  units = new Function('return ' + literal)();
} catch (e) {
  console.error('не удалось распарсить UNITS: ' + e.message);
  process.exit(1);
}

const unitsJson = JSON.stringify(units);
process.stdout.write(unitsJson);
