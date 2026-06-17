# 골든셋 v2 — music-newsletter (한 플랫폼의 하루 LLM 출력)

- 상태: **DRAFT (검수·승인 전)** → 사람 승인 후 FROZEN
- v1→v2 사유: critique 지적 ① "3플랫폼 모두 예"는 올-오어-낫싱이라 변별력 손실 → **플랫폼별로 따로 채점**(이 시험지는 한 플랫폼 출력 1세트를 본다). ② "객관"이라던 항목 다수가 판단 개입 → 정직하게 confidence 표기 + **음성/양성 앵커** 추가. ③ 필드 형식·근거 기준 구체화.
- 작업: "한 플랫폼이 그날 수집한 게시물 → 3줄 요약 + 추천 게시물(pick) + 분석 3단계(why/point/apply)"
- 채점 단위: 항목별 예/아니오. 한 플랫폼당 점수 = 통과/6. **전체 점수 = (3플랫폼 통과 합)/(6×3=18).**
- 채점자: 생성과 분리된 세션(grade.py, gpt-5)
- 독자 맥락: 이훈 — 독학 음악 엔지니어/작곡가(믹싱·사운드디자인·인디팝·R&B·신스팝). "따라하기" 아닌 **응용 포인트**.
- 변경 규칙: 항목 몰래 변경 금지. 오류 시 v3 + 사유.

## 객관 항목 (grade.py 절대 채점)

### summary-format
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] 정확히 3줄, 한국어, 각 줄 한 문장(종결어미로 끝남).
  - [ ] 서론·메타설명 없음, 이모지는 줄당 0~1개 이하(떡칠 아님).

### pick-fields
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] pick에 title·channel·reason이 모두 비어있지 않게 채워짐(‘-’·한 글자·N/A 아님).
  - [ ] channel이 실제 출처 형태(핸들/계정 또는 서브레딧)다.

## 판단 항목 (grade.py 루브릭 채점 — 앵커 기준)

### summary-substance
- subjective: yes(경미) / confidence: med
- criteria:
  - [ ] 3줄이 단순 통계 나열이 아니라 그날 씬의 **흐름·인사이트**를 자연어로 전달.
  - [ ] 세 줄이 서로 다른 정보(통계 반복 아님).
- 앵커:
  - ❌ "오늘 16건 수집 · 평균 재생 109,468 · 최고 674,000" / "자주 등장: newmusic, fyp"
  - ✅ "이번 주 금요일 릴리즈를 겨냥한 티저·프리세이브 독려가 여러 아티스트에 걸쳐 쏟아졌다"

### pick-relevance
- subjective: yes(경미) / confidence: med
- criteria:
  - [ ] 추천 게시물이 음악 **제작·사운드·창작·씬**과 유의미하게 관련(단순 바이럴/지표 1위라서가 아님). 마케팅·인물·뉴스라도 *배울 점*이 분석으로 연결되면 인정.
- 앵커:
  - ❌ pick이 단지 "재생 1위"라서 뽑힘 + 음악 창작과 연결 안 됨
  - ✅ "Polivoks 창시자 부고" → 분석이 '불완전한 음색을 개성으로'라는 사운드디자인 교훈으로 연결

### pick-reason-specific
- subjective: yes(경미) / confidence: high
- criteria:
  - [ ] reason이 지표 반복("오늘 가장 높은 재생 X")이 아니라 **왜 봐야 하는지** 구체적 근거.
- 앵커:
  - ❌ "오늘 가장 높은 재생 674,000"
  - ✅ "비주얼 중심 음악 홍보의 교과서 같은 사례라서"

### analysis-grounded
- subjective: yes(경미) / confidence: high
- criteria:
  - [ ] why/point/apply 3줄이 모두 존재하고 그 픽에 **특정적**(제네릭 템플릿 아님).
  - [ ] 세 줄이 역할대로 서로 다름(why=원인 / point=핵심 / apply=적용).
- 앵커:
  - ❌ point="(채널)의 게시물 — 자주 등장: newmusic, fyp" (태그 나열)
  - ✅ point="음원 링크보다 아티스트 세계관을 담은 한 장의 이미지가 참여율을 만든다"

### analysis-actionable
- subjective: yes(경미) / confidence: med
- criteria:
  - [ ] apply가 이훈의 음악 작업에 **바로 적용할 구체적 행동**(장르·믹싱·사운드디자인 맥락). 제네릭 금지.
- 앵커:
  - ❌ "상위 게시물의 포맷·키워드를 내 작업 방향의 참고점으로 활용"
  - ✅ "다음 릴리즈 때 음원 링크만 올리지 말고 컨셉 사진 한 장 + 한 줄 CTA를 함께 올려보자"

## 분리 항목 (오프라인 채점 불가 — 사후)
- source-match: pick이 당일 수집 목록 안의 게시물인가(수집본 매칭). source_id 도입 시 자동화 가능.
- fact-accuracy: 부고·인물·장비 사실의 정확성. 본 채점 제외.
- reality-01: 추천·분석이 실제 다음 작업에 쓸모 있었나. 사후 사람 판단.

## 주관 비교 항목 (compare.py — 챔피언 루프, 추후)
1. 인사이트 깊이: 데이터 < 트렌드 해석 < 응용 통찰
2. 적용 구체성: 제네릭 < 이훈 장르·역할 맞춤 행동

## 의도적으로 안 보는 것
- 사실 정확성·출처 매칭·HTML 렌더 품질은 이번 버전 제외 → v3 후보. 만점=이 6항목만 통과.
