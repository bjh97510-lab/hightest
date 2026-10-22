"""검정고시지원센터 『성인학습자 맞춤형 검정고시 학습자료』 e-book 의 '기출문제 도전하기' 문항·정답·해설을 추출한다.

사용법:
  1) e-book 페이지 이미지와 OCR 준비 (EBOOK 아래)
       pages/<책>/NNN.png|jpg   — http://218.38.12.36/.../files/page/N.(png|jpg)
       ocr/<책>/NNN.json        — powershell -File tools/ocr_windows.ps1 -InDir pages/<책> -OutDir ocr/<책>
  2) python tools/build_ebook.py <EBOOK 폴더> [책 ...]      (pip install pymupdf numpy)
  결과: ebook/questions.js (window.GED_EBOOK_QUESTIONS), ebook/<과목>/<단원>/{N.png, eN.png}

- 문항 쪽: 단원 끝 '기출문제 도전하기' 쪽(바닥글로 판별)에서 두 자리 번호 표지(01, 02, …)를 차례로 찾아 다음 표지까지 자름
- 정답·해설: 책 뒤 '기출문제 도전하기 정답 및 해설'의 'NN ────▶ ③' 줄. 번호가 01 로 돌아가면 다음 단원
- 정답 원문자(①~④)는 OCR이 못 읽어, 원 안쪽 숫자 모양을 견본(circ_templates.npy)과 비교해 판별
- 저작권: 공공기관 학습자료지만 재배포 허락이 확인되지 않아 ebook/ 폴더는 .gitignore 로 저장소에서 제외
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'ebook'
BOOKS = {   # 책 폴더 → (과목, 정답·해설 시작 쪽, 정답·해설 끝 쪽, 번호 표지 색 RGB, 배치)  — 쪽은 이미지 파일 번호
    # 배치  back: 책 뒤 '정답 및 해설'에 단원별로 모음 · after: 단원 문제 쪽 바로 뒤 '정답 및 해설' 쪽 · inline: 문항 바로 아래 해설
    'h_science': ('과학', 147, 165, (239, 83, 189), 'back'),
    'h_korean': ('국어', 259, 271, (239, 83, 189), 'back'),
    'h_math': ('수학', 999, 999, (216, 90, 70), 'after'),
    'h_english': ('영어', 999, 999, (216, 90, 70), 'inline'),
}
# 자동 판별이 실패한 정답을 사람이 해설 이미지·지문을 보고 확인해 고정한 값: (과목, 단원, 번호) → 정답
OVERRIDES = {
    ('영어', '03', 4): 4,     # 해설 '정답 ④' (원문자 인식 실패)
    ('영어', '11', 13): 2,    # 해설이 다음 쪽으로 넘어가 잘림 — 주어진 문장은 'wrong with the color' 뒤 ②
}
TEMPL = Path(__file__).resolve().parent / 'circ_templates.npy'


def gray(path):
    p = pymupdf.Pixmap(str(path))
    if p.n > 1:
        p = pymupdf.Pixmap(pymupdf.csGRAY, p)
    return np.frombuffer(p.samples, np.uint8).reshape(p.height, p.stride)[:, :p.width].copy()


def feat(cr, n=16):
    """원문자 이미지 → 바깥 원을 지우고 안쪽 숫자만 꼭 맞게 잘라 n×n 으로 맞춘 모양 특징(글꼴·크기 차이에 강함)."""
    ink = (cr < 170)
    h, w = ink.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((yy - (h - 1) / 2) / max(h, 1), (xx - (w - 1) / 2) / max(w, 1))
    inner = ink & (r < 0.33)
    ys, xs = np.flatnonzero(inner.any(axis=1)), np.flatnonzero(inner.any(axis=0))
    if not ys.size:
        return np.zeros(n * n)
    d = inner[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1].astype(np.float32)
    # 가로세로 비율을 유지하며 정사각형에 놓음 ('1'이 가늘다는 정보 보존)
    s_ = max(d.shape)
    pad = np.zeros((s_, s_), np.float32)
    oy, ox = (s_ - d.shape[0]) // 2, (s_ - d.shape[1]) // 2
    pad[oy:oy + d.shape[0], ox:ox + d.shape[1]] = d
    idx = (np.arange(n) * s_ / n).astype(int)
    a_ = pad[idx][:, idx].ravel()
    return a_ / (np.linalg.norm(a_) + 1e-6)


def blobs(band, gap=3):
    cols = np.flatnonzero(band.sum(axis=0) > 0)
    out = []
    for c in cols:
        if out and c - out[-1][1] <= gap:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def classify(g, x0, x1, y0, y1, templ, side='right'):
    """[x0,x1]×[y0,y1] 띠에서 원문자 덩어리(정사각형에 가까운 것)를 찾아 1~4로 판별. (정답, 확신도)"""
    band = g[y0:y1, x0:x1] < 160
    cands = []
    for c0, c1 in blobs(band):
        sub = band[:, c0:c1 + 1]
        rows = np.flatnonzero(sub.sum(axis=1) > 0)
        if not rows.size:
            continue
        w, h = c1 - c0 + 1, rows[-1] - rows[0] + 1
        if h >= 8 and 0.75 <= w / h <= 1.3:
            cands.append((c0, c1, rows[0], rows[-1]))
    if not cands:
        return 0, 0.0, None
    c0, c1, r0, r1 = cands[-1] if side == 'right' else cands[0]
    box = [int(x0 + c0), int(y0 + r0), int(x0 + c1 + 1), int(y0 + r1 + 1)]
    sc = templ @ feat(g[box[1]:box[3], box[0]:box[2]])
    s = np.sort(sc)
    return int(np.argmax(sc)) + 1, float(s[-1] - s[-2]), box


class Page:
    def __init__(self, book_dir, ocr_dir, num):
        self.num = num
        self.ocr = json.loads((ocr_dir / f'{num:03d}.json').read_text(encoding='utf-8'))
        self.path = next(book_dir.glob(f'{num:03d}.*'))
        self.w, self.h = self.ocr['w'], self.ocr['h']
        self.lines = [l for l in self.ocr['lines'] if l['text'].strip()]
        self._g = None

    @property
    def g(self):
        if self._g is None:
            self._g = gray(self.path)
        return self._g

    _rgb = None

    @property
    def rgb(self):
        if self._rgb is None:
            p = pymupdf.Pixmap(str(self.path))
            if p.n == 1:
                p = pymupdf.Pixmap(pymupdf.csRGB, p)
            self._rgb = np.frombuffer(p.samples, np.uint8).reshape(p.height, p.stride)[:, :p.width * p.n].reshape(p.height, p.width, p.n)[:, :, :3].astype(np.int16)
        return self._rgb

    def text(self, y0=0.0, y1=1.0):
        return ' '.join(l['text'] for l in self.lines if self.h * y0 <= l['box'][1] <= self.h * y1)


def columns(page):
    """본문 단 나누기: 글줄 상자가 하나도 걸치지 않는 세로 빈 띠(15px 이상)를 단 사이로 봄 → 1·2·3단 모두 처리.
    머리·바닥글은 제외."""
    w, h = page.w, page.h
    top, bottom = h * 0.06, h * 0.93
    body = [l for l in page.lines if top < l['box'][1] < bottom]
    cover = np.zeros(w, np.int32)
    for l in body:
        x0, y0, x1, _ = l['box']
        # 쪽 위쪽의 큰 제목(여러 단에 걸침)은 단 나누기에서 무시
        if x1 - x0 < w * 0.9 and not (y0 < h * 0.16 and x1 - x0 > w * 0.2):
            cover[max(0, x0):min(w, x1)] += 1
    # 가운데 세로 구분선이 있으면 그것이 단 경계 (글이 적은 쪽도 정확히 나뉨)
    g = page.g
    y_a, y_b = int(h * 0.15), int(h * 0.9)
    lo_, hi_ = int(w * 0.38), int(w * 0.62)
    dark = (g[y_a:y_b, lo_:hi_] < 200).mean(axis=0)
    if dark.size and dark.max() > 0.45:
        mid = lo_ + int(np.argmax(dark))
        cols = []
        for x0, x1 in ((0, mid), (mid + 3, w)):
            ls = sorted([l for l in body if x0 <= (l['box'][0] + l['box'][2]) / 2 < x1], key=lambda l: l['box'][1])
            if x1 == w and ls:
                x1 = min(w, int(np.percentile([l['box'][2] for l in ls], 95)) + 14)
            cols.append({'page': page, 'x0': x0, 'x1': x1, 'top': top, 'bottom': bottom, 'lines': ls})
        return cols
    occupied = np.flatnonzero(cover > 0)
    if not occupied.size:
        return []
    segs, s0, prev = [], occupied[0], occupied[0]
    for x in occupied[1:]:
        if x - prev > 15:
            segs.append((s0, prev)); s0 = x
        prev = x
    segs.append((s0, prev))
    # 너무 좁은 조각(표 안 칸·여백 글자)은 이웃 단에 붙임
    merged = []
    for s_ in segs:
        if merged and (s_[1] - s_[0] < w * 0.18 or merged[-1][1] - merged[-1][0] < w * 0.18):
            merged[-1] = (merged[-1][0], s_[1])
        else:
            merged.append(s_)
    cols = []
    for i, (a0, a1) in enumerate(merged):
        x0 = 0 if i == 0 else (merged[i - 1][1] + a0) // 2
        x1 = min(w, a1 + 14) if i == len(merged) - 1 else (a1 + merged[i + 1][0]) // 2
        ls = sorted([l for l in body if x0 <= (l['box'][0] + l['box'][2]) / 2 < x1], key=lambda l: l['box'][1])
        cols.append({'page': page, 'x0': x0, 'x1': x1, 'top': top, 'bottom': bottom, 'lines': ls})
    return cols


GRP_RE = re.compile(r'^\s*\[\s*(\d{1,2})\s*[~∼～〜\-－]\s*(\d{1,2})\s*\]')
NUM_RE = re.compile(r'^\s*[0Oo]?(\d{1,2})\b')


def marker_lines(col, kind):
    """단 왼쪽 끝에서 시작하는 두 자리 번호 줄."""
    ls = col['lines']
    if not ls:
        return []
    lefts = sorted(l['box'][0] for l in ls)
    base = lefts[max(0, len(lefts) // 8)]
    # 정답 격자 칸 번호(같은 높이에 두 자리 숫자가 여럿)는 제외
    solo = [l for l in col['page'].lines if re.fullmatch(r'\s*\d{2}\s*', l['text'])]
    def in_grid(l):
        return sum(1 for o in solo if o is not l and abs(o['box'][1] - l['box'][1]) < 8) >= 2
    out = []
    for l in ls:
        if kind == 'e' and in_grid(l):
            continue
        t = l['text'].strip()
        m = re.match(r'^([0O]\d|[1-3]\d)(?:\s|$)', t) if kind == 'q' else re.fullmatch(r'([0O]\d|[1-3]\d)', t)
        if m and l['box'][0] <= base + 25:
            out.append((int(m.group(1).replace('O', '0')), l))
    return out


def color_markers(col, ref, kind):
    """단 왼쪽 끝의 번호 표지(정해진 색의 굵은 두 자리 숫자)를 색으로 찾음 → [(y0, y1, x0, x1)].
    정답 격자(같은 줄에 번호가 3개 이상)는 해설 표지가 아니므로 뺌."""
    page = col['page']
    x0, x1 = int(col['x0']), int(col['x1'])
    y0, y1 = int(col['top']), int(col['bottom'])
    a = page.rgb[y0:y1, x0:x1]
    mask = np.abs(a - np.array(ref, np.int16)).sum(axis=2) < 130
    w = x1 - x0
    # 홀수·짝수 쪽 여백이 달라 단 왼쪽 끝이 아니라 '본문 글줄이 시작하는 x'부터 살핌
    lefts = sorted(l['box'][0] for l in col['lines'] if l['box'][0] >= x0 - 2) or [x0]   # 이웃 단에서 넘어온 줄 제외
    base = max(0, lefts[0] - x0 - 15)
    zone = np.zeros_like(mask)
    zone[:, base:base + int(w * 0.14)] = mask[:, base:base + int(w * 0.14)]
    rows = np.flatnonzero(zone.sum(axis=1) > 0)
    out, band = [], []
    for r in list(rows) + [10 ** 9]:
        if band and r - band[-1] > 2:
            b0, b1 = band[0], band[-1]
            h = b1 - b0 + 1
            sub = zone[b0:b1 + 1]
            # 번호 덩어리만 (오른쪽으로 이어지는 같은 색 가로선은 떼어 냄)
            bl = blobs(sub, gap=max(3, h // 2))
            cs = np.arange(bl[0][0], bl[0][1] + 1) if bl else np.array([])
            if 8 <= h <= 60 and cs.size:
                bw = cs[-1] - cs[0] + 1
                full = mask[b0:b1 + 1]
                blobs_in_row = len([b for b in blobs(full, gap=max(3, h // 2)) if b[1] - b[0] + 1 >= h * 0.6])
                # 해설 표지는 '01 ─────▶ ③' 처럼 오른쪽으로 가로선이 이어짐 (본문 속 색 글자와 구별)
                rule = True
                if kind == 'e':
                    g = page.g[y0 + b0 - 2:y0 + b1 + 3, x0 + cs[-1] + 6:x1 - 30] < 235
                    rule = g.size > 0 and g.any(axis=0).mean() > 0.6
                # 정답 격자 행: 같은 높이 OCR 글줄에 두 자리 번호가 2개 이상('01 ② 02 ④ 03 ④')
                cy = y0 + (b0 + b1) / 2
                row_txt = ' '.join(l['text'] for l in col['lines'] if abs((l['box'][1] + l['box'][3]) / 2 - cy) < 8)
                if kind == 'e' and len(re.findall(r'(?<!\d)\d{2}(?!\d)', row_txt)) >= 2:
                    band = []
                    band.append(r)
                    continue
                # 흰 바탕 위의 번호만 (제목 띠의 큰 단원 번호·색 상자 안 글자 제외)
                bx0, bx1 = x0 + cs[0], x0 + cs[-1]
                ring = page.g[max(0, y0 + b0 - 6):y0 + b1 + 7, max(0, bx0 - 8):bx1 + 9].astype(int)
                white_bg = (ring > 235).mean() > 0.45
                width_ok = (0.5 * h <= bw <= 2.8 * h or (kind == 'e' and bw <= 2.8 * h)) and white_bg   # 해설 표지는 가로선으로 확인되므로 폭은 상한만
                if width_ok and h <= 40 and rule and not (kind == 'e' and blobs_in_row >= 5):
                    out.append((y0 + b0, y0 + b1, x0 + cs[0], x0 + cs[-1]))
            band = []
        band.append(r)
    return out


def cut(parts, path, scale=1.0, erase=None):
    pieces = []
    for col, y0, y1 in parts:
        g = col['page'].g
        a = g[max(0, int(y0)):int(y1), int(col['x0']):int(col['x1'])].copy()
        if erase is not None and erase[0] is col['page']:
            ex0, ey0, ex1, ey1 = erase[1]
            ex0 = max(int(col['x0']), int(ex0 - (ey1 - ey0) * 1.1))   # 두 자리 번호 중 한 자리만 잡혔을 때 대비
            a[max(0, ey0 - 3 - int(y0)):max(0, ey1 + 3 - int(y0)), max(0, ex0 - 3 - int(col['x0'])):max(0, ex1 + 3 - int(col['x0']))] = 255
        ink = a < 200
        ink[:, :4] = False; ink[:, -4:] = False
        rc = ink.sum(axis=1)
        rows = np.flatnonzero((rc > 1) & (rc < ink.shape[1] * 0.9))
        cols = np.flatnonzero(ink[rows].sum(axis=0) > 0) if rows.size else np.array([])
        if rows.size and cols.size:
            pieces.append(a[max(0, rows[0] - 4):rows[-1] + 6, max(0, cols[0] - 6):cols[-1] + 8])
    if not pieces:
        return None
    W = max(p.shape[1] for p in pieces)
    pieces = [np.pad(p, ((0, 0), (0, W - p.shape[1])), constant_values=255) for p in pieces]
    gap = np.full((10, W), 255, np.uint8)
    out = np.vstack([x for i, p in enumerate(pieces) for x in ((gap, p) if i else (p,))])
    if scale != 1.0:
        h2, w2 = int(out.shape[0] * scale), int(out.shape[1] * scale)
        out = out[(np.arange(h2) / scale).astype(int)][:, (np.arange(w2) / scale).astype(int)]
    out = np.ascontiguousarray(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    pymupdf.Pixmap(pymupdf.csGRAY, out.shape[1], out.shape[0], out.tobytes(), False).save(path)
    return out.shape[1], out.shape[0]


def is_topic_tag(l, col):
    """문항 위 오른쪽에 붙은 작은 단원 표시('③ 별의 탄생과 진화')."""
    x0, y0, x1, y1 = l['box']
    return x0 > (col['x0'] + col['x1']) / 2 - 40 and (y1 - y0) < 18 and len(l['text']) < 25


def regions(cols, marks, stop_lines=()):
    """표지 i → 표지 i+1 직전까지의 단 조각 목록. stop_lines: 영역을 끊는 줄(다음 단원 머리 등)."""
    out = []
    for i, (ci, y, _) in enumerate(marks):
        nxt = marks[i + 1] if i + 1 < len(marks) else None
        parts, cj, yy = [], ci, y - 4
        while cj < len(cols):
            col = cols[cj]
            end = nxt[1] - 5 if nxt and nxt[0] == cj else col['bottom']
            # 다음 문항 바로 위의 단원 표시는 이 문항에 넣지 않음
            for l in col['lines']:
                if yy < l['box'][1] < end and (end - l['box'][3]) < 30 and nxt and nxt[0] == cj and is_topic_tag(l, col):
                    end = min(end, l['box'][1] - 4)
                for s in stop_lines:
                    if s[0] == cj and yy < s[1] < end:
                        end = s[1] - 6
            if end - yy > 6:
                parts.append((col, yy, end))
            if nxt is None or nxt[0] == cj or any(s[0] == cj and yy < s[1] for s in stop_lines if s[1] <= col['bottom']):
                break
            cj += 1
            yy = cols[cj]['lines'][0]['box'][1] - 4 if cj < len(cols) and cols[cj]['lines'] else 0
        out.append(parts)
    return out


def question_sections(pages, ans_start):
    """'기출문제 도전하기' 단원 문항 묶음: [(시작 쪽, [Page…])]. 바닥글(홀수 쪽) 또는 큰 제목으로 판별."""
    def tagged(p):
        t = p.text(0.9, 1.0) + ' ' + p.text(0.0, 0.16)
        return '도전' in t and '정답' not in p.text(0.0, 0.12)
    secs, cur = [], None
    nums = sorted(pages)
    for n in nums:
        if n >= ans_start:
            break
        p = pages[n]
        if tagged(p):
            title = '도전' in p.text(0.0, 0.16)          # 큰 제목 쪽은 항상 새 묶음의 시작
            if cur and n - cur[-1] <= 2 and not title:
                cur += [m for m in range(cur[-1] + 1, n + 1)]
            else:
                cur = [n]; secs.append(cur)
    # 마지막 쪽 다음의 짝수 쪽도 문항이 이어지면 포함(다음 쪽이 새 단원이 아닐 때)
    for s in secs:
        n = s[-1] + 1
        while n in pages and n < ans_start and not tagged(pages[n]) and 'CHAPTER' not in pages[n].text(0, 0.2).upper() and 'PART' not in pages[n].text(0, 0.2).upper() and '정답' not in pages[n].text(0, 0.12):
            if not any(marker_lines(c, 'q') for c in columns(pages[n])):
                break
            s.append(n); n += 1
    return [[pages[n] for n in s] for s in secs]


def label_boxes(col, y_from, y_to):
    """단 왼쪽의 색 채운 작은 이름표(해석·해설·어휘·정답) 상자 → [(y0, y1, x0, x1)] (위에서 아래로)."""
    page = col['page']
    lefts = sorted(l['box'][0] for l in col['lines'] if l['box'][0] >= col['x0'] - 2) or [int(col['x0'])]
    x0 = max(int(col['x0']), lefts[0] - 12)
    x1 = min(int(col['x1']), x0 + int((col['x1'] - col['x0']) * 0.16))
    y0, y1 = max(0, int(y_from)), int(y_to)
    a = page.rgb[y0:y1, x0:x1]
    m = ((a.max(axis=2) - a.min(axis=2)) > 30) & (a.sum(axis=2) < 690)
    rows = np.flatnonzero(m.sum(axis=1) > 1)
    out, band = [], []
    for r in list(rows) + [10 ** 9]:
        if band and r - band[-1] > 1:
            b0, b1 = band[0], band[-1]
            h = b1 - b0 + 1
            cs = np.flatnonzero(m[b0:b1 + 1].sum(axis=0) > 0)
            if 9 <= h <= 40 and cs.size and 1.4 * h <= cs[-1] - cs[0] + 1 <= 4 * h and m[b0:b1 + 1, cs[0]:cs[-1] + 1].mean() > 0.12:   # 채운 상자(해석·해설) + 테두리 상자(어휘·정답)
                out.append((y0 + b0, y0 + b1, x0 + cs[0], x0 + cs[-1], float(m[b0:b1 + 1, cs[0]:cs[-1] + 1].mean())))
            band = []
        band.append(r)
    return out


def answer_after_label(col, line, templ):
    """'정답 ④' 줄에서 '정답' 글자 뒤의 원문자를 판별."""
    words = line.get('words') or []
    x = line['box'][0]
    for w in words:
        x = w['b'][2]
        if '답' in w['t']:
            # '정답③'처럼 원문자가 한 단어로 붙어 읽히면 '답' 글자 끝 위치까지만
            t = w['t']
            k = t.index('답') + 1
            if k < len(t):
                x = w['b'][0] + (w['b'][2] - w['b'][0]) * k / len(t)
            break
    y0, y1 = line['box'][1], line['box'][3]
    return classify(col['page'].g, int(x) + 2, int(col['x1']) - 2, int(y0) - 6, int(y1) + 6, templ, side='left')


INLINE_SPLIT = re.compile(r'^\s*(해석|해설|헤석|해섹)')
LABEL_ANS = re.compile(r'^\s*정\s*답')


def ocr_number(col, y0, y1):
    """색 표지와 같은 높이의 OCR 줄에서 두 자리 번호를 읽음(없으면 None) — 검증용."""
    for l in col['lines']:
        if abs((l['box'][1] + l['box'][3]) / 2 - (y0 + y1) / 2) < 10:
            m = re.match(r'^\s*([0O]?\d)\s?(\d)?', l['text'])
            if m:
                return int((m.group(1) + (m.group(2) or '')).replace('O', '0'))
    return None


def build_book(edir, book, templ):
    subject, ans_start, ans_end, color, layout = BOOKS[book]
    bdir, odir = edir / 'pages' / book, edir / 'ocr' / book
    pages = {int(p.stem): Page(bdir, odir, int(p.stem)) for p in sorted(odir.glob('*.json'))}
    report, items_by_ch, inline_expl, sections = [], [], {}, []

    # ---------- 문항: 단원별 '기출문제 도전하기' 쪽에서 색 표지 순서대로 01, 02, … (+ '[01~03]' 지문 묶음) ----------
    for si, sec in enumerate(question_sections(pages, ans_start)):
        sections.append(sec)
        cols = [c for p in sec for c in columns(p)]
        events = []
        for ci, c in enumerate(cols):
            title_page = '도전' in c['page'].text(0, 0.15)
            for (y0, y1, x0, x1) in color_markers(c, color, 'q'):
                if title_page and y0 < c['page'].h * 0.15:     # 제목 띠(큰 단원 번호·띠 가장자리)
                    continue
                events.append((ci, y0, ('q', (y0, y1, x0, x1))))
            lefts = sorted(l['box'][0] for l in c['lines']) or [0]
            for l in c['lines']:
                m = GRP_RE.match(l['text'])
                if m and l['box'][0] <= lefts[0] + 30:
                    words = l.get('words') or []
                    bx1 = l['box'][0]
                    for wd in words:
                        if re.search(r'[가-힣A-Za-z]', wd['t']):
                            break
                        bx1 = wd['b'][2]
                    events.append((ci, l['box'][1], ('g', (int(m.group(1)), int(m.group(2)), (l['box'][0], l['box'][1], bx1, l['box'][3])))))
        events.sort(key=lambda e: (e[0], e[1]))
        regs = regions(cols, events)
        qs, bad, group, no = [], [], None, 0
        cid = len(items_by_ch)          # 단원 번호 (영어처럼 쪽 묶음 안에서 01로 다시 시작하면 새 단원)
        d = OUT / subject / f'{cid + 1:02d}'
        for (ci, y, (kind, info)), parts in zip(events, regs):
            if kind == 'g':
                a_, b_, bbox = info
                size = cut(parts, d / f'g{a_}.png', erase=(cols[ci]['page'], bbox))
                group = {'id': f'ebook|{subject}|{cid + 1:02d}|{a_}', 'end': b_, 'instr': '', 'instrInImg': True,
                         'img': f'ebook/{subject}/{cid + 1:02d}/g{a_}.png' if size else '', 'size': list(size or (0, 0))}
                continue
            if layout == 'inline' and no > 0 and ocr_number(cols[ci], info[0], info[1]) == 1:
                items_by_ch.append(qs); qs, group, no = [], None, 0
                cid = len(items_by_ch); d = OUT / subject / f'{cid + 1:02d}'
            no += 1
            if group and no > group['end']:
                group = None
            y0, y1, x0, x1 = info
            read = ocr_number(cols[ci], y0, y1)
            if read is not None and read != no:
                bad.append(f'{no}≠{read}')
            eparts = []
            if layout == 'inline':
                # 문항 번호 표지(영역 맨 위)는 이름표가 아님
                labs = [(pc, lb) for pc in parts for lb in label_boxes(pc[0], pc[1], pc[2]) if lb[0] > y1 + 4 or pc is not parts[0]]
                # 해설 시작 = 처음 나오는 '채운' 이름표(해석/해설). 문항 상자 모서리 같은 테두리만 있는 것은 제외
                filled = [(pc, lb) for pc, lb in labs if lb[4] > 0.5]
                if filled:
                    (col_, a0, a1), first = filled[0]
                    k = next(i for i, pc in enumerate(parts) if pc[0] is col_ and pc[1] == a0)
                    eparts = [(col_, first[0] - 4, a1)] + parts[k + 1:]
                    parts = parts[:k] + ([(col_, a0, first[0] - 8)] if first[0] - 8 - a0 > 6 else [])
                    # 정답 = 해설 시작 뒤 이름표 중 오른쪽에 원문자가 있는 마지막 것
                    # 정답 이름표: 해설 시작 이름표 뒤의 이름표 중 바로 오른쪽(이름표 높이의 2배 안)에 원문자가 있는 마지막 것
                    after = [(pc, lb) for pc, lb in labs if labs.index((pc, lb)) > labs.index(filled[0])]
                    ans, conf, abox, lcol = 0, 0.0, None, col_
                    for (pc, lb) in reversed(after):
                        ly0, ly1, lx0, lx1 = lb[:4]
                        r = classify(pc[0]['page'].g, lx1 + 3, min(int(pc[0]['x1']) - 2, lx1 + 3 + int((ly1 - ly0) * 2.2)), ly0 - 6, ly1 + 6, templ, side='left')
                        if r[2] is not None and r[1] > 0.05:
                            ans, conf, abox = r; lcol = pc[0]
                            # 정답 이름표 아래(다음 소단원 머리 등)는 해설에서 뺌
                            j = next((i for i, (c_, y_a, y_b) in enumerate(eparts) if c_ is pc[0] and y_a - 2 <= ly1 <= y_b + 2), None)
                            if j is not None:
                                c_, y_a, y_b = eparts[j]
                                eparts = eparts[:j] + [(c_, y_a, min(y_b, ly1 + 10))]
                            break
                    esize = cut(eparts, d / f'e{no}.png')
                    inline_expl[(cid, no)] = {'answer': ans, 'conf': round(conf, 3), 'ansSrc': [str(lcol['page'].path), abox],
                                             'expImg': f'ebook/{subject}/{cid + 1:02d}/e{no}.png' if esize else '', 'expSize': list(esize or (0, 0))}
            size = cut(parts, d / f'{no}.png', erase=(cols[ci]['page'], (x0, y0, x1, y1)))
            if size:
                text = re.sub(r'\s+', ' ', ' '.join(x['text'] for col, a0, a1 in parts for x in col['lines'] if a0 - 2 <= x['box'][1] <= a1))
                q = {'no': no, 'img': f'ebook/{subject}/{cid + 1:02d}/{no}.png', 'size': list(size), 'text': text[:300], 'page': sec[0].num}
                if group:
                    q['group'] = {k: group[k] for k in ('id', 'instr', 'instrInImg', 'img', 'size')}
                qs.append(q)
        if bad:
            report.append(f'  문항 번호 확인 필요 단원{cid + 1:02d}: {bad}')
        items_by_ch.append(qs)

    if layout == 'inline':
        expl = inline_expl
    elif layout == 'after':
        expl = after_explanations(pages, sections, subject, color, templ, report)
    else:
        expl = back_explanations(pages, ans_start, ans_end, subject, color, templ, report)
    return merge(subject, items_by_ch, expl, report)


def after_explanations(pages, sections, subject, color, templ, report):
    """단원 문제 쪽 바로 뒤 '정답 및 해설' 쪽: 'NN 정답 ④' 줄이 표지."""
    expl = {}
    nums = sorted(pages)
    for si, sec in enumerate(sections):
        ap, n = [], sec[-1].num + 1
        while n in pages:
            top = pages[n].text(0, 0.15)
            if ap and re.search(r'Chapter|CHAPTER|Part|PART|도전', top):
                break
            if not ap and '정답' not in top:
                break
            ap.append(pages[n]); n += 1
        cols = [c for p in ap for c in columns(p)]
        marks = []
        for ci, c in enumerate(cols):
            for (y0, y1, x0, x1) in color_markers(c, color, 'q'):
                # 같은 줄(번호 오른쪽)에 '정답'이 이어지는지 — OCR이 번호와 '정답'을 따로 읽기도 하므로 합쳐서 봄
                row = sorted([l for l in c['lines'] if abs((l['box'][1] + l['box'][3]) / 2 - (y0 + y1) / 2) < 14 and l['box'][0] >= x0 - 45],
                             key=lambda l: l['box'][0])
                joined = ' '.join(l['text'] for l in row)
                line = next((l for l in row if '답' in l['text']), None) if re.match(r'^\s*\S{0,3}\s*정\s*답', joined) else None
                if line:
                    marks.append((ci, y0, ((y0, y1, x0, x1), line)))
        regs = regions(cols, marks)
        for k, ((ci, y, (box, line)), parts) in enumerate(zip(marks, regs)):
            no = k + 1
            ans, conf, abox = answer_after_label(cols[ci], line, templ)
            y0, y1, x0, x1 = box
            size = cut(parts, OUT / subject / f'{si + 1:02d}' / f'e{no}.png', erase=(cols[ci]['page'], (x0, y0, x1, y1)))
            expl[(si, no)] = {'answer': ans, 'conf': round(conf, 3), 'ansSrc': [str(cols[ci]['page'].path), abox],
                              'expImg': f'ebook/{subject}/{si + 1:02d}/e{no}.png' if size else '', 'expSize': list(size or (0, 0))}
    return expl


def back_explanations(pages, ans_start, ans_end, subject, color, templ, report):
    """책 뒤 '정답 및 해설': 'CHAPTER' 제목마다 새 단원, 색 표지('01 ───▶ ③') 순서대로 01, 02, …"""
    ans_pages = [pages[n] for n in sorted(pages) if ans_start <= n <= ans_end]
    cols = [c for p in ans_pages for c in columns(p)]
    events = []
    for ci, c in enumerate(cols):
        for l in c['lines']:
            if re.search(r'CHAPTER|CHAPTE|어AP|대AP|^\s*PART\s*0\d', l['text'], re.I) and l['box'][3] - l['box'][1] < 40:
                events.append((ci, l['box'][1], 'ch', None))
            elif GRP_RE.match(l['text']):
                events.append((ci, l['box'][1], 'stop', None))
        for (y0, y1, x0, x1) in color_markers(c, color, 'e'):
            events.append((ci, y0, 'm', (y0, y1, x0, x1)))
    events.sort(key=lambda e: (e[0], e[1]))
    marks, stops, chap, num, bad = [], [], -1, 0, []
    for ci, y, kind, box in events:
        if kind == 'ch':
            if num > 0 or chap < 0:      # 'PART 01' 바로 뒤 'CHAPTER 01' 처럼 연달아 나온 제목은 한 번만
                chap += 1
            num = 0; stops.append((ci, y)); continue
        if kind == 'stop':
            stops.append((ci, y)); continue
        if chap < 0:
            continue
        num += 1
        read = ocr_number(cols[ci], box[0], box[1])
        if read is not None and read != num:
            bad.append(f'단원{chap + 1:02d} {num}≠{read}')
        marks.append((ci, y, (chap, num, box)))
    regs = regions(cols, marks, stop_lines=stops)
    expl = {}
    for (ci, y, (chap, n, box)), parts in zip(marks, regs):
        col = cols[ci]
        y0, y1, x0, x1 = box
        ans, conf, abox = classify(col['page'].g, x1 + 5, int(col['x1']) - 2, y0 - 8, y1 + 8, templ)
        size = cut(parts, OUT / subject / f'{chap + 1:02d}' / f'e{n}.png', erase=(col['page'], (x0, y0, x1, y1)))
        expl[(chap, n)] = {'answer': ans, 'conf': round(conf, 3), 'ansSrc': [str(col['page'].path), abox], 'expImg': f'ebook/{subject}/{chap + 1:02d}/e{n}.png' if size else '', 'expSize': list(size or (0, 0))}
    if bad:
        report.append(f'  해설 번호 확인 필요: {bad[:20]}')
    return expl


def merge(subject, items_by_ch, expl, report):
    out = {}
    for ch, qs in enumerate(items_by_ch):
        ne = sum(1 for (c, n) in expl if c == ch)
        lowconf = [q['no'] for q in qs if expl.get((ch, q['no']), {}).get('conf', 0) < 0.08]
        for q in qs:
            q.update(expl.get((ch, q['no']), {'answer': 0, 'expImg': ''}))
            fix = OVERRIDES.get((subject, f'{ch + 1:02d}', q['no']))
            if fix:
                q['answer'], q['conf'] = fix, 1.0
        report.append(f'{subject} 단원{ch + 1:02d} (p{qs[0]["page"] if qs else "?"}): 문항 {len(qs)} / 해설 {ne}'
                      + ('' if len(qs) == ne else '  ⚠ 개수 불일치') + (f'  확신 낮음 {lowconf}' if lowconf else ''))
        out[f'{ch + 1:02d}'] = qs
    return subject, out, report


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    edir = Path(sys.argv[1])
    books = sys.argv[2:] or list(BOOKS)
    templ = np.load(TEMPL)
    db_path = OUT / 'questions.json'
    db = json.loads(db_path.read_text(encoding='utf-8')) if db_path.exists() else {}
    for b in books:
        subject, data, report = build_book(edir, b, templ)
        db[subject] = data
        print('\n'.join(report))
    OUT.mkdir(exist_ok=True)
    db_path.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'questions.js').write_text('window.GED_EBOOK_QUESTIONS = ' + json.dumps(db, ensure_ascii=False) + ';\n', encoding='utf-8')


if __name__ == '__main__':
    main()
