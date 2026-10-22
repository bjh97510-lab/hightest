"""공식 기출 PDF를 문항 단위로 잘라 이미지 + 텍스트 DB(pdf/questions.js)를 만든다.

사용법: python tools/build_questions.py [회차 ...]     예) python tools/build_questions.py 2026-2 2026-1
        (인자 없으면 pdf/ 아래 모든 회차, pip install pymupdf numpy 필요)

- 시험지는 2단 편집이므로 (페이지, 왼쪽/오른쪽 단) 순서로 읽으며 ‘N.’ 문항 표지와
  ‘[a～b]’ 지문 묶음 표지를 찾고, 다음 표지까지를 한 문항 영역으로 본다.
  영역이 단·페이지를 넘어가면 여러 조각 이미지로 저장한다.
- 수식·그림·밑줄은 텍스트로 추출되지 않으므로 앱은 이미지를 문항 본문으로 쓰고,
  추출 텍스트는 검색·오답노트 요약용으로만 쓴다.
- 이미지 속 원래 문항 번호는 흰색으로 지워, 랜덤 조합 시 새 번호와 충돌하지 않게 한다.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / 'pdf'
SUBJECTS = {'국어': 25, '수학': 20, '영어': 25, '사회': 25, '과학': 25, '한국사': 25, '도덕': 25}
ZOOM = 2.0
Q_RE = re.compile(r'^\s*(\d{1,2})\s*\.(?:\s|$)')
G_RE = re.compile(r'^\s*\[\s*(\d{1,2})\s*[～~∼〜\-－]\s*(\d{1,2})\s*\]\s*(.*)$')
CIRC = '①②③④⑤'


def column_slots(doc):
    """읽기 순서대로 (page, x0, x1, top, bottom, blocks) 단 목록."""
    slots = []
    for pi, page in enumerate(doc):
        W = page.rect.width
        raw = page.get_text('rawdict')['blocks']
        lines = []
        for b in raw:
            for ln in b.get('lines', []):
                chars = [c for s in ln['spans'] for c in s['chars']]
                text = ''.join(c['c'] for c in chars)
                if text.strip():
                    lines.append({'bbox': ln['bbox'], 'text': text, 'chars': chars})
        footer = [l for l in lines if re.match(r'^\s*고졸\s*\(', l['text']) and l['bbox'][1] > page.rect.height * 0.85]
        bottom = min(l['bbox'][1] for l in footer) - 6 if footer else page.rect.height - 60
        for ci, (x0, x1) in enumerate(((30, W / 2 - 1), (W / 2 + 1, W - 25))):
            col = [l for l in lines if x0 <= l['bbox'][0] < x1 and l['bbox'][1] < bottom]
            slots.append({'page': pi, 'x0': x0, 'x1': x1, 'bottom': bottom, 'lines': col})
    return slots


def find_markers(slots, n):
    """문항/지문 표지를 읽기 순서로 찾는다. 번호가 순서대로 이어질 때만 인정."""
    markers, expect = [], 1
    for si, s in enumerate(slots):
        if not s['lines']:
            continue
        base = min(l['bbox'][0] for l in s['lines'])
        # 같은 줄(y)이 여러 블록으로 쪼개질 수 있으므로 y 순 정렬
        for l in sorted(s['lines'], key=lambda l: (round(l['bbox'][1]), l['bbox'][0])):
            if l['bbox'][0] > base + 5 or expect > n:
                continue
            g = G_RE.match(l['text'])
            if g and int(g.group(1)) == expect:
                markers.append({'type': 'g', 'slot': si, 'y': l['bbox'][1], 'y1': l['bbox'][3], 'a': int(g.group(1)), 'b': int(g.group(2)), 'instr': g.group(3).strip()})
                continue
            q = Q_RE.match(l['text'])
            if q and int(q.group(1)) == expect:
                # 원래 번호 글자("12.") 영역 → 이미지에서 지움
                num = f'{expect}.'
                acc, box = '', None
                for c in l['chars']:
                    if c['c'].isspace() and not acc:
                        continue
                    acc += c['c']
                    r = pymupdf.Rect(c['bbox'])
                    box = r if box is None else box | r
                    if acc.replace(' ', '') == num:
                        break
                markers.append({'type': 'q', 'slot': si, 'y': l['bbox'][1], 'no': expect, 'numbox': box})
                expect += 1
    return markers, expect - 1


def page_tops(slots, markers):
    """각 페이지 본문 시작 y: 첫 페이지는 첫 표지 위, 나머지는 단 내 첫 줄 위."""
    tops = {}
    for m in markers:
        p = slots[m['slot']]['page']
        tops.setdefault(p, m['y'] - 4)
    for s in slots:
        if s['page'] not in tops and s['lines']:
            tops[s['page']] = min(l['bbox'][1] for l in s['lines']) - 4
    for s in slots:
        if s['page'] != 0 and s['lines']:
            tops[s['page']] = min(tops.get(s['page'], 1e9), min(l['bbox'][1] for l in s['lines']) - 4)
    return tops


def regions(slots, markers, tops):
    """표지 i ~ 표지 i+1 사이 영역을 단 조각 목록으로."""
    out = []
    for i, m in enumerate(markers):
        start_y = m['y1'] + 1 if m['type'] == 'g' else m['y'] - 3
        nxt = markers[i + 1] if i + 1 < len(markers) else None
        parts, si, y = [], m['slot'], start_y
        while si < len(slots):
            s = slots[si]
            end = nxt['y'] - 4 if nxt and nxt['slot'] == si else s['bottom']
            if end - y > 4:
                parts.append((s['page'], pymupdf.Rect(s['x0'], y, s['x1'], end)))
            if nxt is None or nxt['slot'] == si:
                break
            si += 1
            y = tops.get(slots[si]['page'], 60)
        out.append(parts)
    return out


def render(doc, parts, out_path, erase=None):
    """조각들의 흰 여백(상하좌우)을 잘라 세로로 이어 붙인 PNG로 저장. 반환: (폭, 높이) 또는 None."""
    arrs = []
    for pi, rect in parts:
        pix = doc[pi].get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=rect, colorspace=pymupdf.csGRAY, alpha=False)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].copy()
        if erase is not None and erase[0] == pi and rect.intersects(erase[1]):
            e = (erase[1] + (-1.5, -1.5, 1.5, 1.5)) & rect
            a[max(0, int((e.y0 - rect.y0) * ZOOM)):int((e.y1 - rect.y0) * ZOOM) + 1,
              max(0, int((e.x0 - rect.x0) * ZOOM)):int((e.x1 - rect.x0) * ZOOM) + 1] = 255
        ink = a < 235
        rows = np.flatnonzero(ink.any(axis=1))
        if rows.size:
            arrs.append((a[max(0, rows[0] - 4):rows[-1] + 6], ink))
    if not arrs:
        return None
    # 좌우 여백은 모든 조각 공통으로 잘라 들여쓰기 정렬을 유지
    cols = np.flatnonzero(np.any([ink.any(axis=0)[:min(x.shape[1] for x, _ in arrs)] for _, ink in arrs], axis=0))
    x0, x1 = max(0, cols[0] - 6), cols[-1] + 8
    pieces = [x[:, x0:x1] for x, _ in arrs]
    width = max(p.shape[1] for p in pieces)  # 왼쪽/오른쪽 단 폭이 조금 달라 오른쪽을 흰색으로 맞춤
    pieces = [np.pad(p, ((0, 0), (0, width - p.shape[1])), constant_values=255) for p in pieces]
    gap = np.full((10, width), 255, np.uint8)
    out = np.vstack([p if i == 0 else np.vstack([gap, p]) for i, p in enumerate(pieces)])
    out = np.ascontiguousarray(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pymupdf.Pixmap(pymupdf.csGRAY, out.shape[1], out.shape[0], out.tobytes(), False).save(out_path)
    return out.shape[1], out.shape[0]


def clean(t):
    # 수식 글꼴의 사용자 정의 영역 문자(U+E000~F8FF)는 의미 없는 기호이므로 제거
    t = re.sub(r'[-]', '', t.replace('　', ' '))
    return re.sub(r'[ \t]+', ' ', t).strip()


def extract_text(doc, parts):
    text = '\n'.join(doc[pi].get_text('text', clip=r) for pi, r in parts)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()
    first = min((text.find(c) for c in CIRC if c in text), default=-1)
    stem, opts = (text[:first], text[first:]) if first >= 0 else (text, '')
    options = [clean(o) for o in re.split(r'[①②③④⑤]', opts)[1:]] if opts else []
    stem = clean(Q_RE.sub('', stem, count=1).replace('\n', ' '))
    return stem, options


def build_subject(key, subject, n, answers):
    path = PDF / key / f'{subject}.pdf'
    doc = pymupdf.open(path)
    slots = column_slots(doc)
    markers, found = find_markers(slots, n)
    tops = page_tops(slots, markers)
    regs = regions(slots, markers, tops)
    outdir = PDF / key / 'q' / subject
    items, group = [], None
    for m, parts in zip(markers, regs):
        if m['type'] == 'g':
            gid = f'{key}|{subject}|{m["a"]}'
            size = render(doc, parts, outdir / f'g{m["a"]}.png')
            group = {'id': gid, 'end': m['b'], 'instr': m['instr'], 'img': f'pdf/{key}/q/{subject}/g{m["a"]}.png' if size else '', 'size': list(size or (0, 0))}
            continue
        if group and m['no'] > group['end']:
            group = None
        first_page = parts[0][0] if parts else 0
        size = render(doc, parts, outdir / f'{m["no"]}.png', erase=(first_page, m['numbox']) if m['numbox'] else None)
        stem, options = extract_text(doc, parts)
        ans = answers[m['no'] - 1] if m['no'] <= len(answers) else 0
        item = {'no': m['no'], 'img': f'pdf/{key}/q/{subject}/{m["no"]}.png' if size else '', 'size': list(size or (0, 0)),
                'text': stem, 'options': options, 'answer': ans}
        if group:
            item['group'] = {k: group[k] for k in ('id', 'instr', 'img', 'size')}
        items.append(item)
    return items, found


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    answers = json.loads((PDF / 'answers.json').read_text(encoding='utf-8'))
    keys = sys.argv[1:] or sorted(answers, reverse=True)
    db_path = PDF / 'questions.json'
    db = json.loads(db_path.read_text(encoding='utf-8')) if db_path.exists() else {}
    problems = []
    for key in keys:
        db[key] = {}
        for subject, n in SUBJECTS.items():
            if not (PDF / key / f'{subject}.pdf').exists():
                problems.append(f'{key} {subject}: PDF 없음')
                continue
            items, found = build_subject(key, subject, n, answers.get(key, {}).get(subject, []))
            db[key][subject] = items
            noimg = [i['no'] for i in items if not i['img']]
            if found != n or noimg:
                problems.append(f'{key} {subject}: 문항 {found}/{n}' + (f', 이미지 없음 {noimg}' if noimg else ''))
        print(f'{key}: ' + ', '.join(f'{s} {len(v)}' for s, v in db[key].items()))
    db = {k: db[k] for k in sorted(db, reverse=True)}
    db_path.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding='utf-8')
    # file:// 에서도 <script>로 읽을 수 있도록 JS로도 저장
    (PDF / 'questions.js').write_text('window.GED_OFFICIAL_QUESTIONS = ' + json.dumps(db, ensure_ascii=False) + ';\n', encoding='utf-8')
    print('\n'.join(problems) if problems else '이상 없음')


if __name__ == '__main__':
    main()
