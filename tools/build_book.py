"""교재 『검정고시 고졸 만점 뽀개기 실전모의고사』 사진(모의고사.Zip)을 문항·해설 이미지 DB(book/questions.js)로 만든다.

사용법:
  1) powershell -ExecutionPolicy Bypass -File tools/ocr_windows.ps1 -InDir <압축 푼 사진 폴더> -OutDir book/ocr
  2) python tools/build_book.py [모의고사.Zip]          (pip install pymupdf numpy)

- 사진 → 회차·과목·쪽 대응은 아래 PAGES 표(사진 파일 이름 순서 기준)로 고정한다. OCR이 바닥글을 잘못 읽어도 흔들리지 않게 하려는 것.
- 문항: 'N.' 표지, 지문 묶음: '[a~b]' 표지, 해설: 'N 정답' 표지를 OCR 좌표로 찾아 다음 표지까지를 한 영역으로 자른다.
- 사진의 조명 얼룩을 지우고(배경 나누기) 흑백으로 정리해 스캔본처럼 만든다.
- 교재 저작물이므로 book/ 폴더는 .gitignore 로 저장소에서 제외한다.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'book'
OCR = OUT / 'ocr'
SUBJECTS = {'국어': 25, '수학': 20, '영어': 25, '사회': 25, '과학': 25, '한국사': 25, '도덕': 25}
ORDER = list(SUBJECTS)

# 정답표 (교재 102쪽 4회, 138쪽 5회 '정답' 표를 옮김)
ANSWERS = {
    '4회': {
        '국어': '2323443242433213222311141',
        '수학': '14223321441113323342',
        '영어': '4224432113212422431222311',
        '사회': '3114223323342112123142133',
        '과학': '1223244133412243311431241',
        '한국사': '3423433212111413143422423',
        '도덕': '3223411133332243234323422',
    },
    '5회': {
        '국어': '3143443123313142433211234',
        '수학': '14234421223424123124',
        '영어': '1221433143132124332433121',
        '사회': '3123332443323132444244422',
        '과학': '3312412413412324313421224',
        '한국사': '4134234214133132442141442',
        '도덕': '1424232433444341343443424',
    },
}

# 사진(파일 이름 정렬 순서) → 쪽 정보. 문항 쪽: (회차, 과목, 쪽), 해설 쪽: 교재 쪽 번호
def page_table(names):
    q = {}
    def put(start, kind, subject, pages):
        for k, p in enumerate(pages):
            q[names[start + k]] = (kind, subject, p)
    # 4회 문제지 (뒤쪽부터 찍힘)
    put(69, '4회', '도덕', [4, 3, 2, 1]); put(73, '4회', '한국사', [4, 3, 2, 1]); put(77, '4회', '과학', [5, 4, 3, 2])
    put(81, '4회', '영어', [1]); put(82, '4회', '수학', [5, 4, 3, 2, 1]); put(87, '4회', '국어', [10, 9, 8, 7, 6, 5, 4])
    # 5회 문제지
    put(94, '5회', '사회', [3, 2, 1]); put(97, '5회', '영어', [5, 4, 3, 2, 1]); put(102, '5회', '수학', [5, 4, 3, 2, 1])
    put(107, '5회', '국어', [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
    exp = {names[i]: 171 - i for i in range(68)}   # 사진 0~67 = 해설 171~104쪽 (102쪽 정답표는 따로 읽음)
    return q, exp


# 두 번째로 받은 사진(새 폴더.zip): 빠졌던 쪽. 바닥글 + 해설 대조로 회차를 확인했고, 같은 쪽을 두 번 찍은 것은 하나만 씀
EXTRA_PAGES = {
    'KakaoTalk_20261023_000411084_08': ('4회', '국어', 1), 'KakaoTalk_20261023_000411084_07': ('4회', '국어', 2),
    'KakaoTalk_20261023_000411084_06': ('4회', '국어', 3),
    'KakaoTalk_20261023_000411084_05': ('4회', '영어', 2), 'KakaoTalk_20261023_000411084_04': ('4회', '영어', 3),
    'KakaoTalk_20261023_000411084_03': ('4회', '영어', 4), 'KakaoTalk_20261023_000411084_02': ('4회', '영어', 5),
    'KakaoTalk_20261023_000331411_10': ('4회', '사회', 1), 'KakaoTalk_20261023_000331411_09': ('4회', '사회', 2),
    'KakaoTalk_20261023_000331411': ('4회', '사회', 3), 'KakaoTalk_20261023_000331411_08': ('4회', '사회', 4),
    'KakaoTalk_20261023_000331411_07': ('4회', '과학', 1),
    'KakaoTalk_20261023_000331411_06': ('5회', '사회', 4),
    'KakaoTalk_20261023_000331411_05': ('5회', '과학', 1), 'KakaoTalk_20261023_000331411_04': ('5회', '과학', 2),
    'KakaoTalk_20261023_000331411_03': ('5회', '과학', 3), 'KakaoTalk_20261023_000331411_02': ('5회', '과학', 4),
    'KakaoTalk_20261023_000331411_01': ('5회', '과학', 5),
    'KakaoTalk_20261023_000310731_07': ('5회', '한국사', 1), 'KakaoTalk_20261023_000310731_06': ('5회', '한국사', 2),
    'KakaoTalk_20261023_000310731_05': ('5회', '한국사', 3), 'KakaoTalk_20261023_000310731_04': ('5회', '한국사', 4),
    'KakaoTalk_20261023_000310731_03': ('5회', '도덕', 1), 'KakaoTalk_20261023_000310731_02': ('5회', '도덕', 2),
    'KakaoTalk_20261023_000310731_01': ('5회', '도덕', 3), 'KakaoTalk_20261023_000310731': ('5회', '도덕', 4),
}


def load_ocr(name):
    return json.loads((OCR / (Path(name).stem + '.json')).read_text(encoding='utf-8'))


def gray_page(data):
    """사진 → 흰 배경으로 정규화한 흑백 numpy 배열."""
    pix = pymupdf.Pixmap(data)
    if pix.n > 1:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].astype(np.float32)
    # 조명 얼룩: 축소 영상의 국소 최댓값(종이 밝기)으로 나눔
    f = 16
    h, w = a.shape
    small = a[:h // f * f, :w // f * f].reshape(h // f, f, w // f, f).max(axis=(1, 3))
    k = 5
    pad = np.pad(small, k, mode='edge')
    win = np.lib.stride_tricks.sliding_window_view(pad, (2 * k + 1, 2 * k + 1))
    bg = np.percentile(win.reshape(*win.shape[:2], -1), 90, axis=2)
    bg = np.repeat(np.repeat(bg, f, axis=0), f, axis=1)
    bg = np.pad(bg, ((0, h - bg.shape[0]), (0, w - bg.shape[1])), mode='edge')
    n = np.clip(a / np.maximum(bg, 1) * 255, 0, 255)
    # 대비: 밝은 쪽은 하얗게, 글자는 진하게
    n = np.clip((n - 70) * (255 / (215 - 70)), 0, 255)
    return n.astype(np.uint8)


def column_split(lines, w):
    """줄 상자들이 가장 적게 걸치는 x(가운데 35~65% 구간)를 단 경계로."""
    cover = np.zeros(w, np.int32)
    for l in lines:
        x0, _, x1, _ = l['box']
        if x1 - x0 < w * 0.6:   # 쪽 전체를 가로지르는 제목 줄은 무시
            cover[max(0, x0):min(w, x1)] += 1
    lo, hi = int(w * 0.35), int(w * 0.65)
    seg = cover[lo:hi]
    best = np.flatnonzero(seg == seg.min())
    return lo + int(best[len(best) // 2])


Q_RE = re.compile(r'^\s*(\d{1,2})\s*[.,·]\s*')
# '[14~16]' — OCR이 닫는 괄호를 '1'로, '0'을 '이'로 읽는 경우가 많아 뒤쪽은 느슨하게
G_RE = re.compile(r'^\s*[\[(（|]\s*(\d{1,2})\s*[~∼～〜\-－]\s*(\d{1,3})')


def group_range(g):
    a, b = int(g.group(1)), g.group(2)
    if len(b) == 3 and b.endswith('1'):          # '161' = '16]'
        b = b[:2]
    b = int(b)
    if b < a:                                     # '9~1이' = '9~10'
        b = b * 10 if b * 10 >= a else a + 1
    if b > a + 5:                                 # '21]'→'211' 같은 잔여 오인식
        b = int(str(b)[:-1]) if int(str(b)[:-1]) >= a else a + 1
    return a, b


def bracket_box(line):
    """줄 맨 앞 '[a~b]' 토큰 영역 (한글·영문이 처음 나오는 단어 앞까지) — 이미지에서 원래 번호를 지울 때 사용."""
    words = line.get('words') or []
    x1 = line['box'][0]
    for w in words:
        if re.search(r'[가-힣A-Za-z]', w['t']):
            break
        x1 = w['b'][2]
    nxt = next((w['b'][0] for w in words if w['b'][0] >= x1), None)
    return [line['box'][0], line['box'][1], x1, line['box'][3], nxt]
E_RE = re.compile(r'^\s*(\d{1,2})\s*정\s*답')


def slots_for(pages, kind):
    """읽기 순서대로 단(slot) 목록: page 순서, 왼쪽 → 오른쪽."""
    slots = []
    for pg in pages:
        o = pg['ocr']
        w, h = o['w'], o['h']
        lines = [l for l in o['lines'] if l['text'].strip()]
        foot = [l for l in lines if l['box'][1] > h * 0.85 and (re.search(r'고\s*졸\s*[(（]', l['text']) or re.search(r'실전\s*모의|만점|정답과|^\s*\d{3}\s*$', l['text']))]
        bottom = min(l['box'][1] for l in foot) - 8 if foot else int(h * 0.94)
        body = [l for l in lines if l['box'][3] < bottom]
        mid = column_split(body, w)
        for x0, x1 in ((0, mid), (mid, w)):
            col = [l for l in body if (l['box'][0] + l['box'][2]) / 2 >= x0 and (l['box'][0] + l['box'][2]) / 2 < x1]
            slots.append({'page': pg, 'x0': x0, 'x1': x1, 'bottom': bottom, 'lines': sorted(col, key=lambda l: l['box'][1])})
    return slots


def looks_like_stem(lines, k):
    """문항 표지다운지: 번호만 단독(영어 어휘 문항)이거나 2줄 안에 '?'·'고르' 가 있는 발문."""
    m = Q_RE.match(lines[k]['text'])
    ahead = ' '.join(x['text'] for x in lines[k:k + 3])
    return not lines[k]['text'][m.end():].strip() or '?' in ahead or '고르' in ahead


def find_markers(slots, kind, start=None, n=25):
    """표지를 순서대로 찾음. 번호는 이어져야 하며, 시작 번호를 모르면 처음 찾은 번호부터."""
    out, expect = [], start
    for si, s in enumerate(slots):
        if not s['lines']:
            continue
        lefts = sorted(l['box'][0] for l in s['lines'])
        base = lefts[max(0, len(lefts) // 10)]
        for l in s['lines']:
            t = l['text']
            if kind == 'q':
                if l['box'][0] > base + 45:
                    continue
                g = G_RE.match(t)
                if g and (expect is None or int(g.group(1)) == expect):
                    a, b = group_range(g)
                    # 안내문은 OCR 오류가 있어 글자 대신 이미지에 남기고, 앞의 원래 번호 '[a~b]'만 지움
                    out.append({'type': 'g', 'slot': si, 'y': l['box'][1], 'y1': l['box'][3], 'a': a, 'b': b, 'numbox': bracket_box(l)})
                    expect = a
                    continue
                m = Q_RE.match(t)
            else:
                if l['box'][0] > base + 60:
                    continue
                m = E_RE.match(t)
            if m and kind == 'q' and not looks_like_stem(s['lines'], s['lines'].index(l)):
                # 지문 속 개요 번호('3. 금융 이해력을…')일 수 있음: 같은 번호의 더 그럴듯한 후보가 뒤(이 단·다음 단)에 있으면 건너뜀
                num = int(m.group(1))
                later = [(x, slots[sj]['lines']) for sj in (si, si + 1) if sj < len(slots) for x in slots[sj]['lines']
                         if (sj > si or x['box'][1] > l['box'][1])]
                if any((mm := Q_RE.match(x['text'])) and int(mm.group(1)) == num and looks_like_stem(ls, ls.index(x)) for x, ls in later):
                    m = None
            if m:
                num = int(m.group(1))
                if (expect is None and num <= n) or num == expect:
                    ws = l.get('words') or []
                    first = list(ws[0]['b']) if ws else list(l['box'])
                    first.append(ws[1]['b'][0] if len(ws) > 1 else None)   # 다음 단어 시작 x (번호와의 거리는 OCR 어긋남과 무관)
                    out.append({'type': kind, 'slot': si, 'y': l['box'][1], 'y1': l['box'][3], 'no': num, 'numbox': first})
                    expect = num + 1
    return out


E_ANCHOR = re.compile(r'정\s*[답담]\s*알\s*기')        # 'N 정답 ③' 바로 아래 '|정답알기|' (굵은 번호보다 OCR이 잘 읽음)
GRID_ROW = re.compile(r'^(\s*\d{1,2}\s+){4,}\d{1,2}\s*$')   # 과목 첫머리 정답표의 번호 줄


# 해설에서 과목이 시작되는 (교재 쪽, 단 0=왼쪽 1=오른쪽) — 사진에서 확인한 값으로 고정
SECTIONS = {
    '4회': {'국어': (104, 0), '수학': (110, 1), '영어': (115, 0), '사회': (118, 1), '과학': (123, 0), '한국사': (126, 1), '도덕': (132, 0)},
    '5회': {'국어': (140, 0), '수학': (146, 0), '영어': (150, 0), '사회': (153, 1), '과학': (158, 0), '한국사': (161, 1), '도덕': (167, 0)},
}


def explanation_markers(slots, kind):
    """해설 표지: 'N 정답' 줄(번호 신뢰) + 번호를 못 읽은 '|정답알기|' 줄(번호 추정). 과목 경계는 SECTIONS 표."""
    starts = {}
    for subject, (page_no, col) in SECTIONS[kind].items():
        si = next(i for i, s in enumerate(slots) if s['page']['p'] == page_no and i % 2 == col)
        heads = [l for l in slots[si]['lines'] if '교시' in l['text'] or GRID_ROW.match(l['text'])]
        starts[subject] = (si, heads[0]['box'][1] if heads else 0)
    bounds = sorted((v, s) for s, v in starts.items())

    def subject_at(si, y):
        cur = None
        for (bsi, by), s in bounds:
            if (si, y) >= (bsi, by):
                cur = s
        return cur

    raw = {s: [] for s in ORDER}
    for si, s in enumerate(slots):
        lefts = sorted(l['box'][0] for l in s['lines']) or [0]
        base = lefts[max(0, len(lefts) // 10)]
        found = []
        for l in s['lines']:
            m = E_RE.match(l['text'])
            if m and l['box'][0] <= base + 70:
                found.append(l['box'][1]); raw_add = (si, l['box'][1], int(m.group(1)))
                subj = subject_at(si, l['box'][1])
                if subj: raw[subj].append(raw_add)
        for l in s['lines']:
            if l['box'][0] <= base + 70 and E_ANCHOR.search(l['text']) and not any(0 <= l['box'][1] - y <= 110 for y in found):
                subj = subject_at(si, l['box'][1] - 64)
                if subj: raw[subj].append((si, l['box'][1] - 64, None))

    out = []
    for subject in ORDER:
        evs = sorted(raw[subject])
        n = SUBJECTS[subject]
        known = [num for _, _, num in evs if num]
        marks, last = [], 0
        for i, (si, y, num) in enumerate(evs):
            # 뒤에 올 확실한 번호(현재보다 큰 것) — 추정 번호가 넘지 않게
            nxt = next((k for _, _, k in evs[i + 1:] if k and k > last), n + 1)
            if num and last < num <= n:
                pass
            elif last + 1 < nxt:
                num = last + 1
            else:
                continue   # 자리가 없으면 앞 영역에 합침
            marks.append({'type': 'e', 'slot': si, 'y': y, 'y1': y, 'no': num, 'subject': subject})
            last = num
        for i, m in enumerate(marks):
            m['span'] = (marks[i + 1]['no'] if i + 1 < len(marks) else n + 1) - m['no']
        # 과목 첫 표지 앞 번호(1번 등)를 놓친 경우 첫 영역이 그 번호도 맡음
        if marks and marks[0]['no'] > 1:
            marks[0]['span'] += marks[0]['no'] - 1; marks[0]['no'] = 1
        out += marks
    return sorted(out, key=lambda m: (m['slot'], m['y']))


def regions(slots, markers):
    out = []
    for i, m in enumerate(markers):
        y = m['y'] - 6
        nxt = markers[i + 1] if i + 1 < len(markers) else None
        parts, si = [], m['slot']
        while si < len(slots):
            s = slots[si]
            end = nxt['y'] - 8 if nxt and nxt['slot'] == si else s['bottom']
            if end - y > 10:
                parts.append((s, y, end))
            if nxt is None or nxt['slot'] == si:
                break
            # 다음 단은 맨 위 글줄부터 (빈 단이면 건너뜀)
            si += 1
            if si < len(slots):
                y = (slots[si]['lines'][0]['box'][1] - 6) if slots[si]['lines'] else slots[si]['bottom']
        out.append(parts)
    return out


def erase_number(a, box, y0, x0):
    """줄 맨 앞의 원래 번호('12.' 또는 '[3~4]')를 지움.
    사진에 따라 OCR 상자가 실제 글자와 좌우로 15~40px 어긋나므로 좌표를 그대로 쓰지 않는다.
    그 줄 높이에서 잉크를 띄어쓰기 간격으로 덩어리(cluster)로 나누고,
    '번호 덩어리 시작 → 다음 덩어리 시작' 거리가 OCR의 '번호 → 다음 단어' 거리와 가장 비슷한 덩어리를 번호로 본다
    (어긋남은 줄 전체에 똑같이 적용되므로 상대 거리는 믿을 수 있음)."""
    bx0, by0, bx1, by1 = box[:4]
    nx = box[4] if len(box) > 4 else None
    r0, r1 = max(0, by0 - 4 - y0), max(0, by1 + 4 - y0)
    pad = int((by1 - by0) * 0.3)
    e0, e1 = max(0, r0 - pad), r1 + pad
    band = a[r0:r1] < 150
    if not band.size:
        return
    cs = band.sum(axis=0)
    cols = (cs > 1) & (cs < band.shape[0] * 0.85)          # 띠 전체를 꿰뚫는 단 경계선·상자 테두리는 제외
    lo, hi = max(0, bx0 - x0 - 80), min(len(cols), bx1 - x0 + 80)
    xs = lo + np.flatnonzero(cols[lo:hi])
    if not xs.size:
        return
    gap = max(9, int((by1 - by0) * 0.33))                   # 숫자·마침표 사이는 좁고 띄어쓰기는 넓음
    clusters, st, en = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - en >= gap:
            clusters.append((st, en)); st = x
        en = x
    clusters.append((st, en))
    want_w = bx1 - bx0
    def score(i):
        c0, c1 = clusters[i]
        s = abs((c1 - c0) - want_w)                          # 번호 폭이 비슷할수록
        if nx is not None:
            nxt = clusters[i + 1][0] if i + 1 < len(clusters) else None
            s += abs((nxt - c0) - (nx - bx0)) if nxt is not None else 60
        # OCR 위치에서 너무 먼 덩어리는 불리하게 (다음 단어가 한 글자일 때 '질 높은' 같은 글자를 고르는 것 방지)
        s += abs(c0 - (bx0 - x0)) * (0.5 if nx is None else 0.35)
        return s
    i = min(range(len(clusters)), key=score)
    c0, c1 = clusters[i]
    # '12.'처럼 숫자 사이가 넓어 두 덩어리로 갈린 경우: 바로 앞의 좁은 덩어리(숫자 한 개 폭)를 합침
    h = by1 - by0
    while i > 0 and clusters[i - 1][1] - clusters[i - 1][0] < h * 0.8 and c0 - clusters[i - 1][1] < gap * 1.8:
        i -= 1; c0 = clusters[i][0]
    if c1 - c0 > want_w + 30:                                # 글자와 붙어 버린 덩어리면 번호 폭만큼만
        c1 = c0 + want_w
    a[e0:e1, max(0, c0 - 3):c1 + 3] = 255


def render(parts, path, erase=None, scale=0.88, parts_out=None):
    pieces = []
    for s, y0, y1 in parts:
        g = s['page']['gray']
        a = g[max(0, int(y0)):int(y1), int(s['x0']):int(s['x1'])].copy()
        if erase is not None and erase[0] is s['page']:
            erase_number(a, erase[1], int(y0), int(s['x0']))
        ink = a < 150
        # 단 경계 근처의 세로선·종이 가장자리 그림자 제거: 가장자리 8px 비우기
        ink[:, :8] = False; ink[:, -8:] = False
        # 사진 잡티(점 몇 개)와 바닥글 위 가로 괘선(폭 85% 이상)은 내용으로 보지 않음
        rc = ink.sum(axis=1)
        content = (rc > 3) & (rc < ink.shape[1] * 0.85)
        # 위아래로 고립된 한두 줄짜리 잡티 제거: 앞뒤 3줄 안에 다른 내용 행이 있어야 인정
        near = np.convolve(content.astype(int), np.ones(7, int), 'same')
        rows = np.flatnonzero(content & (near >= 3))
        # 끝부분: 큰 빈칸(60px+) 아래 낮은 덩어리(30px 미만: 잡티·괘선)는 버림
        while rows.size > 1:
            cut = np.flatnonzero(np.diff(rows) > 60)
            if not cut.size or rows[-1] - rows[cut[-1] + 1] >= 30:
                break
            rows = rows[:cut[-1] + 1]
        cols = np.flatnonzero(ink[rows].sum(axis=0) > 1) if rows.size else np.array([])
        if rows.size and cols.size:
            pieces.append(a[max(0, rows[0] - 6):rows[-1] + 8, max(0, cols[0] - 8):cols[-1] + 10])
    if not pieces:
        return None
    W = max(p.shape[1] for p in pieces)
    pieces = [np.pad(p, ((0, 0), (0, W - p.shape[1])), constant_values=255) for p in pieces]
    gap = np.full((14, W), 255, np.uint8)
    out = np.vstack([x for i, p in enumerate(pieces) for x in ((gap, p) if i else (p,))])
    size = save_png(out, path, scale)
    if parts_out is not None and len(pieces) > 1:
        # 여러 단에 걸친 긴 지문: 인쇄 때 단을 넘겨 흐르도록 단별 조각도 따로 저장
        for k, p in enumerate(pieces, 1):
            pp = path.with_name(f'{path.stem}_{k}.png')
            parts_out.append({'img': pp.relative_to(ROOT).as_posix(), 'size': list(save_png(p, pp, scale))})
    return size


def save_png(out, path, scale):
    # 크기: 인쇄 엔진이 공식 기출 이미지와 같은 비율로 다루도록 축소
    h2, w2 = int(out.shape[0] * scale), int(out.shape[1] * scale)
    ys = (np.arange(h2) / scale).astype(int); xs = (np.arange(w2) / scale).astype(int)
    out = out[ys][:, xs]
    out = (np.round(out / 255 * 7) * (255 / 7)).astype(np.uint8)   # 8단계 흑백: PNG 용량 절감
    out = np.ascontiguousarray(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    pymupdf.Pixmap(pymupdf.csGRAY, out.shape[1], out.shape[0], out.tobytes(), False).save(path)
    return out.shape[1], out.shape[0]


def text_of(parts):
    lines = [l['text'] for s, y0, y1 in parts for l in s['lines'] if l['box'][1] >= y0 - 2 and l['box'][3] <= y1 + 2]
    return re.sub(r'\s+', ' ', ' '.join(lines)).strip()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    # 첫 번째 zip(문제·해설 사진)은 page_table, 추가 zip(빠진 쪽)은 EXTRA_PAGES 로 쪽을 정함
    zpath = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / '모의고사.Zip'
    extra = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / '새 폴더.zip'
    zf = zipfile.ZipFile(zpath)
    names = sorted(n for n in zf.namelist() if n.lower().endswith(('.jpg', '.jpeg', '.png')))
    qmap, emap = page_table(names)
    owner = {n: zf for n in names}
    if extra.exists():
        zx = zipfile.ZipFile(extra)
        for n in zx.namelist():
            stem = Path(n).stem
            if stem in EXTRA_PAGES:
                owner[n] = zx
                qmap[n] = EXTRA_PAGES[stem]
    cache = {}
    def page(name):
        if name not in cache:
            cache[name] = {'name': name, 'ocr': load_ocr(name), 'gray': gray_page(owner[name].read(name))}
        return cache[name]

    db, report = {}, []
    # ---------- 해설: 교재 쪽 순서로 한 줄로 늘어놓고, 번호가 1로 돌아가면 다음 과목 ----------
    exp = {}
    for kind, lo, hi in (('4회', 104, 137), ('5회', 140, 171)):
        pages = [dict(page(n), p=p) for n, p in sorted(emap.items(), key=lambda x: x[1]) if lo <= p <= hi]
        slots = slots_for(pages, 'e')
        marks = explanation_markers(slots, kind)
        regs = regions(slots, marks)
        for m, parts in zip(marks, regs):
            size = render(parts, OUT / kind / m['subject'] / f'e{m["no"]}.png', scale=0.88)
            if not size:
                continue
            info = {'img': f'book/{kind}/{m["subject"]}/e{m["no"]}.png', 'size': list(size), 'text': text_of(parts)}
            # OCR이 표지를 놓쳐 한 영역에 여러 문항 해설이 들어간 경우: 빠진 번호에도 같은 이미지를 연결
            for no in range(m['no'], m['no'] + m.get('span', 1)):
                exp.setdefault(kind, {}).setdefault(m['subject'], {})[no] = info
        for s in ORDER:
            got = sorted(exp.get(kind, {}).get(s, {}))
            miss = [i for i in range(1, SUBJECTS[s] + 1) if i not in got]
            report.append(f'해설 {kind} {s}: {len(got)}/{SUBJECTS[s]}' + (f' 누락 {miss}' if miss else ''))

    # ---------- 문항 ----------
    groups = {}
    for name, (kind, subject, p) in qmap.items():
        groups.setdefault((kind, subject), []).append((p, name))
    for (kind, subject), lst in sorted(groups.items(), key=lambda x: (x[0][0], ORDER.index(x[0][1]))):
        lst.sort()
        pages = [page(n) for p, n in lst]
        slots = slots_for(pages, 'q')
        start = 1 if lst[0][0] == 1 else None
        marks = find_markers(slots, 'q', start=start, n=SUBJECTS[subject])
        regs = regions(slots, marks)
        ans = ANSWERS[kind][subject]
        items, group = [], None
        for m, parts in zip(marks, regs):
            d = OUT / kind / subject
            if m['type'] == 'g':
                pieces = []
                size = render(parts, d / f'g{m["a"]}.png', erase=(parts[0][0]['page'], m['numbox']) if parts else None, parts_out=pieces)
                # instrInImg: 안내문이 이미지 첫 줄에 들어 있음 → 앱은 새 번호 '[x~y]'만 붙임
                group = {'id': f'book|{kind}|{subject}|{m["a"]}', 'end': m['b'], 'instr': '', 'instrInImg': True,
                         'img': f'book/{kind}/{subject}/g{m["a"]}.png' if size else '', 'size': list(size or (0, 0)), 'parts': pieces}
                continue
            if group and m['no'] > group['end']:
                group = None
            erase = (parts[0][0]['page'], m['numbox']) if parts else None
            size = render(parts, d / f'{m["no"]}.png', erase=erase)
            if not size:
                continue
            e = exp.get(kind, {}).get(subject, {}).get(m['no'], {})
            item = {'no': m['no'], 'img': f'book/{kind}/{subject}/{m["no"]}.png', 'size': list(size), 'text': text_of(parts)[:300],
                    'answer': int(ans[m['no'] - 1]), 'expImg': e.get('img', ''), 'expSize': e.get('size'), 'expText': e.get('text', '')[:600]}
            if group:
                item['group'] = {k: group[k] for k in ('id', 'instr', 'instrInImg', 'img', 'size', 'parts')}
            items.append(item)
        nos = [i['no'] for i in items]
        gaps = [x for x in range(nos[0], nos[-1] + 1) if x not in nos] if nos else []
        report.append(f'문항 {kind} {subject}: {len(items)}문항 ({nos[0] if nos else "-"}~{nos[-1] if nos else "-"}번)' + (f' 빠진 번호 {gaps}' if gaps else ''))
        db.setdefault(kind, {})[subject] = items

    (OUT / 'questions.json').write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'questions.js').write_text('window.GED_BOOK_QUESTIONS = ' + json.dumps(db, ensure_ascii=False) + ';\n', encoding='utf-8')
    print('\n'.join(report))


if __name__ == '__main__':
    main()
