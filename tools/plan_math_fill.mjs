// 출제 제외로 20문항이 안 되는 수학 회차(2018~2020)를 2021년 이후 같은 단원 문항으로 채우는 계획을 만들어
// index.html 의 OFFICIAL_FILL 블록에 넣는다.  사용법: node tools/plan_math_fill.mjs
//
// - 현재(2021~) 고졸 수학 20문항 구성: 다항식 4 · 방정식과 부등식 6 · 도형의 방정식 4 · 집합과 명제 2 · 함수 2 · 경우의 수 2
// - 단원은 추출 텍스트의 핵심어로 판정한다(수식은 텍스트로 남지 않아도 한국어 발문은 남음).
// - 회차 이름으로 고정한 시드로 뽑으므로 다시 실행해도 결과가 같고, 회차끼리 같은 보충 문항을 쓰지 않는다.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const HTML = path.join(ROOT, 'index.html');
const Q = JSON.parse(await fs.readFile(path.join(ROOT, 'pdf', 'questions.json'), 'utf8'));
const src = await fs.readFile(HTML, 'utf8');

const BLUEPRINT = { P: 4, E: 6, G: 4, S: 2, F: 2, C: 2 };
const UNIT_ORDER = ['P', 'E', 'G', 'S', 'F', 'C'];
const UNIT_NAME = { P: '다항식', E: '방정식과 부등식', G: '도형의 방정식', S: '집합과 명제', F: '함수', C: '경우의 수' };
// 판정 순서가 중요: 구체적인 단원 표현을 먼저 본다
const RULES = [
  ['C', /경우의 수|순서대로|순서를|택하여|선택하는|뽑는|나열|방법의 수/],
  ['F', /역함수|합성|∘|유리함수|무리함수|함수 *→|함수 *:|대응|정의역|치역|공역|일대일|항등함수|상수함수|함수 의 그래프|의 그래프로 알맞은|함수 의 값/],
  ['S', /집합|명제|대우|의 역은|원소|조건/],
  ['P', /다항식|항등식|나머지|조립제법|인수분해|나누었을|나누어/],
  ['E', /복소수|켤레|실수 |이차방정식|삼차방정식|사차방정식|연립방정식|근이|근을|근에|이차함수|최댓값|최솟값|부등식|중근|실근/],
  ['G', /좌표평면|두 점|선분|내분|중점|직선|원의 방정식|반지름|지름|접하는|대칭이동|평행이동|사이의 거리/],
];
// 발문이 수식뿐이라 핵심어가 없는 문항 (원본 확인)
const MANUAL = { '2018-1|4': 'E' };
const unitOf = (key, q) => MANUAL[`${key}|${q.no}`] || (RULES.find(([, r]) => r.test(q.text)) || ['?'])[0];

// index.html 의 OFFICIAL_EXCLUDED 를 그대로 읽어 씀
const exBlock = src.match(/const OFFICIAL_EXCLUDED = (\{[\s\S]*?\n\});/);
if (!exBlock) throw new Error('OFFICIAL_EXCLUDED 를 찾을 수 없습니다.');
const EXCLUDED = Function(`return ${exBlock[1]}`)();

function rng(seedText) {   // mulberry32
  let a = [...seedText].reduce((h, c) => Math.imul(h ^ c.charCodeAt(0), 2654435761) >>> 0, 1779033703);
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

const keys = Object.keys(Q).sort();
const donors = keys.filter(k => k >= '2021');
const pool = {};
for (const k of donors) for (const q of Q[k]['수학']) {
  const u = unitOf(k, q);
  if (u !== '?') (pool[u] ||= []).push({ key: k, no: q.no });
}

const used = new Set(), plan = {}, report = [];
for (const key of keys) {
  const ex = (EXCLUDED[key] || {})['수학'] || {};
  const kept = Q[key]['수학'].filter(q => !ex[q.no]);
  if (kept.length >= 20 || !Object.keys(ex).length) continue;
  const have = {}; const lastNo = {};
  for (const q of kept) { const u = unitOf(key, q); have[u] = (have[u] || 0) + 1; lastNo[u] = q.no; }
  const rand = rng(`ged-math-fill-${key}`), picks = [];
  for (const u of UNIT_ORDER) {
    let need = Math.max(0, BLUEPRINT[u] - (have[u] || 0));
    const cands = pool[u].filter(c => !used.has(`${c.key}|${c.no}`));
    while (need-- > 0 && cands.length) {
      // 같은 회차 안에서는 출처 회차가 겹치지 않게 우선
      const fresh = cands.filter(c => !picks.some(p => p.key === c.key));
      const from = fresh.length ? fresh : cands;
      const c = from[Math.floor(rand() * from.length)];
      cands.splice(cands.indexOf(c), 1); used.add(`${c.key}|${c.no}`);
      // 같은 단원 마지막 문항 뒤에 끼움 (단원이 없으면 앞 단원 뒤)
      const prevUnits = UNIT_ORDER.slice(0, UNIT_ORDER.indexOf(u) + 1).reverse();
      const after = prevUnits.map(x => lastNo[x]).find(Boolean) || 0;
      picks.push({ key: c.key, no: c.no, unit: u, after });
    }
  }
  while (kept.length + picks.length < 20) throw new Error(`${key}: 보충 문항 부족`);
  plan[key] = { '수학': picks.map(p => [p.key, p.no, p.after]) };
  report.push(`${key}: 남은 ${kept.length} + 보충 ${picks.length} = ${kept.length + picks.length}  ` +
    picks.map(p => `${UNIT_NAME[p.unit]}←${p.key} ${p.no}번`).join(', '));
}

const body = '{\n' + Object.entries(plan).map(([k, v]) => `  "${k}": {"수학": ${JSON.stringify(v['수학'])}}`).join(',\n') + '\n}';
const re = /\/\*OFFICIAL_FILL\*\/[\s\S]*?\/\*END_OFFICIAL_FILL\*\//;
if (!re.test(src)) throw new Error('index.html 에서 OFFICIAL_FILL 마커를 찾을 수 없습니다.');
await fs.writeFile(HTML, src.replace(re, () => `/*OFFICIAL_FILL*/${body}/*END_OFFICIAL_FILL*/`));
console.log(report.join('\n'));
