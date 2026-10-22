# 고졸 검정고시 AI 무한 모의고사

`index.html` 하나로 동작하는 고졸 검정고시 모의고사 웹앱입니다. 브라우저에서 파일을 열면 바로 실행됩니다.

- **공식 기출 원본**: 2018년 제1회 ~ 2026년 제2회 (18회차) 실제 시험지와 공식 정답으로 응시·채점
- **🎲 무한 랜덤 모의고사**: 기출 3,060문항(문항 이미지)에서 과목별 무작위 조합, 지문 세트는 묶어서 출제
- **현재 교육과정 반영**: 2018~2020년 수학의 부등식의 영역·수열·지수·로그 34문항은 출제에서 제외 (`index.html`의 `OFFICIAL_EXCLUDED`)하고, 빈 자리는 2021년 이후 같은 단원 문항으로 보충해 회차당 20문항 유지 (`OFFICIAL_FILL`, `node tools/plan_math_fill.mjs`로 재생성)
- **응시 모드**: 실전 CBT(타이머·OMR·검토 표시), 연습(즉시 채점·해설), 종이 시험지 인쇄(A4 2단, 문항이 페이지에서 잘리지 않음)
- **채점 리포트·오답노트**: 과목별 40점 과락, 평균 60점 합격 판정, 틀린 문항 자동 저장
- **해설**: 2026년 제2회 국어·사회·한국사·도덕 (계속 추가 예정)
- **기출 DB 관리**: JSON·간편 텍스트로 문항 직접 추가

## 교재 실전모의고사 (개인 학습용, 저장소에 없음)

갖고 있는 교재를 사진으로 찍어 `모의고사.Zip`으로 두면 문항·해설 이미지로 만들어 앱에서 함께 풀 수 있습니다.
시중 교재는 저작물이라 `book/`과 zip 파일은 `.gitignore`로 저장소에서 제외됩니다.

```
powershell -ExecutionPolicy Bypass -File tools/ocr_windows.ps1 -InDir <압축 푼 사진 폴더> -OutDir book/ocr   # Windows 한국어 OCR
python tools/build_book.py 모의고사.Zip                                                                     # 문항·해설 이미지 + book/questions.js
```

사진 순서와 회차·과목·쪽의 대응, 정답표는 `tools/build_book.py`의 `page_table`·`ANSWERS`에 있습니다(다른 교재는 이 부분을 바꿔야 함).

## 폴더 구성

| 경로 | 내용 |
| --- | --- |
| `index.html` | 앱 본체 (공식 정답표 내장) |
| `pdf/{연도}-{차수}/` | 원본 시험지·정답 PDF, `q/` 문항별 이미지 |
| `pdf/questions.js` | 문항 이미지·추출 텍스트 DB |
| `pdf/explanations/`, `pdf/explanations.js` | 해설 |
| `print/` | 미리 만든 인쇄용 PDF |
| `tools/` | 데이터 수집·생성 스크립트 |

`index.html`과 `pdf/` 폴더는 같은 위치에 있어야 합니다.

## 새 회차 반영

```
node --use-system-ca tools/download_gumsi.mjs   # 원본 PDF 다운로드 (Node 22.15+)
python tools/extract_answers.py                 # 정답표 추출 (pip install pymupdf numpy)
node tools/embed_answers.mjs                     # 정답을 index.html에 반영
python tools/build_questions.py                 # 문항 이미지·텍스트 DB 생성
node tools/embed_explanations.mjs                # 해설 JSON → pdf/explanations.js
```

## 출처

기출문제·정답: [검정고시지원센터](https://www.gumsi.or.kr/ged/usr/data/prevexamList.do) (국가평생교육진흥원). 원본 시험지의 저작권은 해당 기관에 있습니다. 내장 샘플 문항과 해설은 이 프로젝트에서 작성했습니다.
