// pdf/explanations/{회차}/{과목}.json 들을 모아 앱이 <script>로 읽는 pdf/explanations.js 생성
// 사용법: node tools/embed_explanations.mjs
// 입력 형식: {"1": {"explanation": "...", "flag": "(선택) 검토 메모"}, ...}
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DIR = path.join(ROOT, 'pdf', 'explanations');
const out = {}, flags = [];
let count = 0;

for (const key of (await fs.readdir(DIR).catch(() => [])).sort()) {
  const sub = path.join(DIR, key);
  if (!(await fs.stat(sub)).isDirectory()) continue;
  for (const file of (await fs.readdir(sub)).filter(f => f.endsWith('.json'))) {
    const subject = path.basename(file, '.json');
    const data = JSON.parse(await fs.readFile(path.join(sub, file), 'utf8'));
    for (const [no, v] of Object.entries(data)) {
      const text = typeof v === 'string' ? v : v.explanation;
      if (!text) continue;
      ((out[key] ||= {})[subject] ||= {})[no] = text.trim();
      count++;
      if (v.flag) flags.push(`${key} ${subject} ${no}번: ${v.flag}`);
    }
  }
}
await fs.writeFile(path.join(ROOT, 'pdf', 'explanations.js'), 'window.GED_EXPLANATIONS = ' + JSON.stringify(out) + ';\n');
console.log(`해설 ${count}개 → pdf/explanations.js`);
if (flags.length) console.log('검토 표시:\n' + flags.join('\n'));
