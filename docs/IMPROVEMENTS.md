# IMPROVEMENTS — 알려진 한계 · 고칠점 백로그

분석/코칭 파이프라인의 알려진 한계와 개선 과제를 모아두는 내부 문서입니다.
**러너에게 노출되는 산출물(리포트·주간 카드·진단)에는 이런 한계 언급을 넣지 않습니다** —
대신 여기에 기록하고 도구·프롬프트에서 고칩니다.

---

## 1. 세션 타입 분류는 세션 aggregate만 본다 (부분 완화)

**증상.** `interval`/`tempo`로 분류된 세션 중 일부가 9:04/km, 7:38/km처럼 느리고
들쭉날쭉한 페이스로 찍혀, 리포트에서 "워크아웃인데 페이스가 quality work가 아니다"라는
모순이 드러났다.

**원인.** `scripts/classify.py`의 `refine()`은 세션 **aggregate(평균/최대 HR, 평균 페이스)**
만 보고 타입을 정한다. interval 판정이 `max_hr ≥ 0.89×HRmax` + 큰 `avg→max` 스윙만
요구해서, 더위·언덕·심박 드리프트·신호 정지 후 재가속으로 **단 한 번 HR이 치솟은**
느린 easy run(예: avgHR 113, maxHR 173인 18 km 7:09/km)이 interval로 오분류됐다.
per-lap/stream 데이터를 보지 않으니 진짜 반복 구조와 우발적 HR 스파이크를 구분 못 한다.

**완화 (2026-05, 완료).** `refine()`에 **페이스 sanity guard**를 추가했다 —
세션 평균 페이스가 러너의 easy-slow 밴드(P72)보다 느리면 quality 라벨(interval/tempo)을
부여하지 않는다. 페이스 데이터가 없으면 가드를 끄고 기존 HR 로직을 유지한다.
기존 로그는 `reclassify.py` 재실행으로 정정(이 러너 기준 interval 82→62, 20건 easy/recovery로).
회귀 테스트: `tests/test_classify.py::test_pace_guard_withholds_quality_on_slow_runs`.

**남은 과제 (근본 해결).** aggregate 기반인 한 경계선 세션은 여전히 불완전하다.
`scripts/analyze_activity.py`는 이미 lap/stream으로 반복 구조·hard-effort 카운트를
정확히 뽑는다 — 이 stream 신호를 `reclassify` 경로에 (선택적으로, rate-limit 안에서)
흘려넣어 HR-aggregate 추정을 stream 근거로 대체/보강하면 경계 사례까지 잡을 수 있다.

## 2. race-analyst가 분류 한계를 러너에게 노출했다 (완료)

**증상.** race-analyst가 위 오분류 세션을 보고 "세션 목적이 흐려졌다"는 식으로,
분류기의 한계를 마치 러너의 훈련 문제처럼 진단에 적었다.

**수정 (2026-05, 완료).** `agents/race-analyst.md`의 `<Constraints>`에 가드 추가 —
타입 라벨과 실제 페이스가 모순되는 세션은 분류기 한계(훈련 문제가 아님)로 보고,
러너용 진단에 노출하지 말고 내부적으로 low-confidence로 down-weight하도록 명시했다.

## 3. ompb-apps 도메인 로직의 core 승격 — 후속 과제 (2026-06)

ompb-apps(end-user surfaces)가 앱 레이어에만 쌓아둔 도메인 로직을 플러그인 core로 승격하고
코칭 표면에 노출했다 (계획: `docs/PLUGIN-PARITY-PLAN.md`). 완료분과 후속분:

**완료.** `scripts/injury.py`·`body.py`·`weather.py`·`zones.py`·`review.py`(+`logquery.py`·
`weekplan.py`)·`insights.py`(+`insight_detectors/`)를 stdlib-only로 승격, `ompb_core`에 노출
(`injury_*`/`body_*`/`weather_*`/`zones`/`week_*`/`detect_insights`), STATE-SCHEMA·CLAUDE.md
라우팅·agents(physio/fuel/session/plan)·skills(pb-injury/weather/body/insights)·테스트 추가.
`ompb_core.query_log`/`weekly_load`는 `logquery`로 위임해 단일 소스화.

**후속 (별도 PR).**
- [ ] **ompb-apps dedup.** core 새 버전 릴리스 후 ompb-apps가 자기 `injury.py`/`body.py`/
  `weather.py`/`zones.py`/`review.py`/`insights*` 대신 `ompb_core`를 소비하도록 전환 →
  중복 제거(두 진실 소스 방지). core 의존 SHA bump이 트리거.
- [ ] **build_report HTML 와우 모먼트 섹션.** 현재 pb-report는 insights를 `diagnosis.observations`로
  녹여 렌더(템플릿 무변경). 전용 카드 섹션은 `templates/report*.html` + `build_report.py`
  편집이 필요 — 후속.
- [ ] **adherence 바 렌더.** `week_review_aggregate`의 adherence%는 계산·노출되지만, pb-week/
  pb-report 카드의 시각 바는 템플릿 작업 필요 — 후속.
- [ ] **일일 readiness 합성 신호.** 앱 `readiness.py`는 온보딩 단계 머신일 뿐 — 일일 훈련
  readiness(load+injury+body 합성)는 신규. 보수적으로 설계해 session-coach 입력으로.
- [ ] **strava athlete-city.** `weather.get_location`의 Strava 도시 자동조회는 플러그인에 해당
  헬퍼가 없어 수동 위치 입력 폴백만 동작 — Strava 연동 경로에서 city를 채우면 자동화 가능.
- [ ] **insights deep 신호.** `detect_insights(deep=True)`는 최근 Strava 런 ≤4건만 analyze
  (rate-limit). zone/decoupling detector는 deep 없으면 no-op — 의도된 제한.
