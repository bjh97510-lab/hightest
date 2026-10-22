// pdf/answers.json(공식 정답표)을 index.html 의 OFFICIAL_KEYS 블록에 삽입
// 사용법: node tools/embed_answers.mjs
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = path.join(ROOT, 'index.html');
const keys = JSON.parse(await fs.readFile(path.join(ROOT, 'pdf', 'answers.json'), 'utf8'));

const body = '{\n' + Object.keys(keys).sort().map(k =>
  `  "${k}": {` + Object.entries(keys[k]).map(([s, a]) => `"${s}":${JSON.stringify(a)}`).join(', ') + '}'
).join(',\n') + '\n}';

const src = await fs.readFile(html, 'utf8');
const re = /\/\*OFFICIAL_KEYS\*\/[\s\S]*?\/\*END_OFFICIAL_KEYS\*\//;
if (!re.test(src)) throw new Error('index.html 에서 OFFICIAL_KEYS 마커를 찾을 수 없습니다.');
await fs.writeFile(html, src.replace(re, () => `/*OFFICIAL_KEYS*/${body}/*END_OFFICIAL_KEYS*/`));
console.log(`${Object.keys(keys).length}개 회차 정답을 index.html 에 반영했습니다.`);
