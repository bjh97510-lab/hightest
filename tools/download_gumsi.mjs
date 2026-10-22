// 검정고시지원센터(gumsi.or.kr) 고졸 기출문제 PDF 일괄 다운로드
// 사용법: node --use-system-ca tools/download_gumsi.mjs
//   (사이트 인증서 체인이 불완전하여 Node 기본 CA로는 검증 실패 → 시스템 CA 사용, Node 22.15+ 필요)
// 결과:   pdf/{연도}-{차수}/{과목}.pdf, pdf/{연도}-{차수}/정답.pdf, pdf/manifest.json
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = 'https://www.gumsi.or.kr';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'pdf');
const SUBJECTS = ['국어', '수학', '영어', '사회', '과학', '한국사', '도덕'];
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36';
let cookie = '';

async function req(url, opts = {}) {
  const res = await fetch(BASE + url, { ...opts, headers: { 'User-Agent': UA, Cookie: cookie, ...(opts.headers || {}) } });
  const sc = res.headers.get('set-cookie');
  if (sc) cookie = sc.split(',').map(c => c.split(';')[0].trim()).filter(c => c.includes('=')).join('; ');
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const decode = s => s.replace(/&#40;/g, '(').replace(/&#41;/g, ')').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').trim();

async function listPage(page) {
  const res = await req('/ged/usr/data/getSearchPrevexamList.do', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', Referer: BASE + '/ged/usr/data/prevexamList.do' },
    body: JSON.stringify({ page: String(page), mode: '3', bbsId: '3' })
  });
  return res.json();
}

async function detail(no) {
  const res = await req('/ged/usr/data/prevexamDtl.do', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Referer: BASE + '/ged/usr/data/prevexamList.do' },
    body: `bbsId=3&bbscttNo=${no}&mode=3&page=1`
  });
  const html = await res.text();
  const meta = k => (html.match(new RegExp(`<li>${k}</li>\\s*<li>([^<]*)</li>`)) || [])[1]?.trim() || '';
  const files = [...html.matchAll(/atchflDl\((\d+),\s*(\d+)\);">\s*([^<]*?)\s*<\/a>/g)].map(m => ({ flId: m[1], flSn: m[2], name: decode(m[3]) }));
  return { year: parseInt(meta('년도')), cls: meta('분류'), step: parseInt(meta('차수')), files };
}

async function main() {
  await req('/ged/usr/data/prevexamList.do');
  const first = await listPage(1);
  const pages = parseInt(first.totalPageCnt) || 1;
  const rows = [];
  for (let p = 1; p <= pages; p++) {
    const d = p === 1 ? first : await listPage(p);
    const re = /list__tag--red">([^<]*)<\/span><span class="list__tag--gray">([^<]*)<\/span><\/div><a[^>]*dtlView\((\d+)[^>]*>([^<]*)<\/a>/g;
    for (const m of d.list.matchAll(re)) rows.push({ level: m[1], no: +m[3], title: decode(m[4]) });
    process.stdout.write(`\r목록 ${p}/${pages}`);
  }
  console.log();
  const targets = rows.filter(r => r.level === '고졸' && (SUBJECTS.includes(r.title) || r.title.startsWith('정답')));
  console.log(`고졸 대상 게시글 ${targets.length}건`);

  const manifest = {};
  for (const t of targets) {
    const d = await detail(t.no);
    if (!d.year || !d.step || !d.files.length) { console.warn(`  건너뜀: #${t.no} ${t.title}`); continue; }
    const key = `${d.year}-${d.step}`;
    const name = t.title.startsWith('정답') ? '정답' : t.title;
    const file = d.files.find(f => /\.pdf$/i.test(f.name)) || d.files[0];
    const ext = path.extname(file.name) || '.pdf';
    const rel = `pdf/${key}/${name}${ext}`;
    const dest = path.join(ROOT, rel);
    await fs.mkdir(path.dirname(dest), { recursive: true });
    const exists = await fs.stat(dest).then(s => s.size > 0).catch(() => false);
    if (!exists) {
      const res = await req(`/ged/cmmn/brd/fileDownload.do?flId=${file.flId}&flSn=${file.flSn}`, { headers: { Referer: BASE + '/ged/usr/data/prevexamDtl.do' } });
      await fs.writeFile(dest, Buffer.from(await res.arrayBuffer()));
      await sleep(300);
    }
    (manifest[key] ||= {})[name] = { file: rel, title: t.title, source: file.name };
    console.log(`  ${exists ? '보유' : '저장'}: ${rel}`);
  }
  await fs.mkdir(OUT, { recursive: true });
  await fs.writeFile(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`완료: ${Object.keys(manifest).length}개 회차 → pdf/manifest.json`);
}

main().catch(e => { console.error('실패:', e.message); process.exit(1); });
