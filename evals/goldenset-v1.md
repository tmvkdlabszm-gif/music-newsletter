# 골든셋 v1 — music-newsletter (매일 LLM 출력 품질)

- 상태: **DRAFT (검수·승인 전)** → 사람 승인 후 FROZEN
- 작업: "그날 수집한 플랫폼별 게시물 → 3줄 요약 + 추천 게시물(pick) + 분석 3단계(why/point/apply)"
- 공통 입력(고정): 하루치 실행 1건 = TikTok·Instagram·Reddit 3개 플랫폼 출력 묶음. 모든 항목이 이 묶음을 본다.
- 채점자: 생성과 분리된 세션(grade.py, gpt-5)
- 채점 단위: 항목 단위. 한 항목의 criteria가 **3개 플랫폼 모두에서 "예"**여야 통과. 점수 = 통과/전체.
- 변경 규칙: 항목 몰래 변경 금지. 오류 시 v2로 버전업 + 사유.
- 독자 맥락: 이훈 — 독학 음악 엔지니어/작곡가(믹싱·사운드디자인·인디팝·R&B·신스팝). "따라하기"가 아니라 **응용 포인트**를 원함.

## 객관 항목 (grade.py 절대 채점)

### summary-substance
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] 3줄 요약이 단순 데이터 나열("N건 수집·평균 재생 X·자주 등장: …")이 아니라, 그날 씬의 **흐름·인사이트**를 자연어 문장으로 전달한다.
  - [ ] 세 줄이 서로 다른 정보를 담는다(중복·통계 반복 아님).

### summary-format
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] 정확히 3줄, 한국어, 각 줄 한 문장 수준으로 간결.
  - [ ] 군더더기·서론·이모지 떡칠 없음.

### pick-music-relevance
- type: rubric / subjective: no / confidence: med
- criteria:
  - [ ] 추천 게시물이 음악 제작·창작·씬과 **유의미하게 관련**된 것(단순 바이럴/랜덤/맥락 없는 인기글 아님).
  - [ ] title·channel·reason 필드가 모두 채워져 있다.

### pick-reason-specific
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] pick의 reason이 "오늘 가장 높은 재생 X" 같은 **데이터 반복이 아니라**, 왜 봐야 하는지 구체적 근거를 준다.

### analysis-grounded
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] why/point/apply 3줄이 모두 존재하고, 그 추천 게시물에 **특정적**이다(제네릭 템플릿 채우기 아님).
  - [ ] 세 줄이 서로 다른 정보를 담는다(why=원인, point=핵심, apply=적용 — 같은 말 반복 아님).

### analysis-actionable
- type: rubric / subjective: no / confidence: high
- criteria:
  - [ ] apply가 이훈의 음악 작업에 **바로 적용할 구체적 행동**을 제시한다("상위 게시물의 포맷·키워드를 참고점으로 활용" 같은 제네릭 문구 아님).

## 분리 항목 (오프라인 채점 불가 — 사후)
- reality-01: 추천한 게시물·분석이 실제로 이훈의 다음 작업에 쓸모가 있었는가. 본 채점 제외, 사후 사람 판단.

## 주관 항목 (compare.py 비교 판정 — 챔피언 vs 후보, 추후)
### 비교 차원
1. 인사이트 깊이: 데이터 요약 < 트렌드 해석 < 응용 가능한 통찰.
2. 추천 적합성: 바이럴/뉴스 < 음악 창작에 배울 점이 있는 게시물.
3. 적용 구체성: 제네릭 조언 < 이훈 장르·역할에 맞춘 다음 행동.
- note: 절대 루브릭 천장 회피. 상대 평가라 가끔 현실 닻 점검.

## 의도적으로 안 보는 것 (착각 방지)
- 사실 정확성(부고·인물 정보 등 외부 사실 검증)은 이번 버전에서 안 봄 → v2 후보.
- 카드 디자인·HTML 렌더 품질은 별개(이 시험지는 LLM 텍스트 출력만).
- → 만점 나와도 "이 6개 항목만 통과"라는 뜻.
