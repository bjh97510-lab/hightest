"""pdf/{회차}/정답.pdf 에서 고졸 7과목 정답을 추출해 pdf/answers.json 으로 저장.

사용법: python tools/extract_answers.py   (pip install pymupdf 필요)
정답표의 원문자(①~④)는 PDF에 실제 텍스트(U+2460~)로 들어 있어 OCR 없이 읽을 수 있다.
"""
import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SUBJECTS = {'국어': 25, '수학': 20, '영어': 25, '사회': 25, '과학': 25, '한국사': 25, '도덕': 25}
CIRCLED = {chr(0x2460 + i): i + 1 for i in range(5)}


def spans(page):
    for b in page.get_text('rawdict')['blocks']:
        for line in b.get('lines', []):
            for s in line['spans']:
                text = ''.join(c['c'] for c in s['chars'])
                if text.strip():
                    yield text.strip(), s['bbox']


def parse_page(page):
    items = list(spans(page))
    title = next((t for t, _ in items if '정답' in t and '표' in t), '')
    subject = next((s for s in SUBJECTS if title.replace(' ', '').startswith(s)), None)
    if not subject:
        return None, None
    nums = [(int(t), bb) for t, bb in items if re.fullmatch(r'\d{1,2}', t) and bb[1] > 180]
    marks = [(t, bb) for t, bb in items if any(c in CIRCLED for c in t) and bb[1] > 180]
    answers = {}
    for n, nb in nums:
        cy = (nb[1] + nb[3]) / 2
        # 같은 행에서 번호 오른쪽에 있는 가장 가까운 원문자 칸
        row = [(bb[0] - nb[2], t) for t, bb in marks if abs((bb[1] + bb[3]) / 2 - cy) < 6 and bb[0] > nb[2]]
        if not row:
            continue
        t = min(row)[1]
        answers[n] = [CIRCLED[c] for c in t if c in CIRCLED]
    return subject, answers


def main():
    out, problems = {}, []
    for pdf in sorted(ROOT.glob('pdf/*/정답.pdf')):
        key = pdf.parent.name
        doc = pymupdf.open(pdf)
        out[key] = {}
        for page in doc:
            subject, answers = parse_page(page)
            if not subject:
                continue
            n = SUBJECTS[subject]
            keys = sorted(answers)
            if keys != list(range(1, n + 1)):
                problems.append(f'{key} {subject}: 문항 {len(keys)}/{n} {keys}')
            multi = {k: v for k, v in answers.items() if len(v) != 1}
            if multi:
                problems.append(f'{key} {subject}: 복수/누락 정답 {multi}')
            # 단일 정답은 숫자, 복수 정답은 배열로 저장
            out[key][subject] = [answers.get(i, [0])[0] if len(answers.get(i, [])) == 1 else answers.get(i, []) for i in range(1, n + 1)]
        missing = [s for s in SUBJECTS if s not in out[key]]
        if missing:
            problems.append(f'{key}: 과목 누락 {missing}')
    (ROOT / 'pdf' / 'answers.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(f'{len(out)}개 회차 → pdf/answers.json')
    print('\n'.join(problems) if problems else '이상 없음')


if __name__ == '__main__':
    main()
