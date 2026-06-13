# 플러그인 개선 계획 — ompb-apps 최근 변경의 core 승격 & 코칭 표면 확장

ompb-apps(end-user surfaces)가 최근 추가한 대형 도메인 기능을, 이 플러그인
(`oh-my-personal-best` = 코칭 두뇌)으로 **"core 승격 → 코칭 표면 노출"** 두 축으로
가져오는 단계적 계획. 목표는 ① 아키텍처 부채(앱 레이어에 갇힌 도메인 로직) 해소와
② Claude Code 코칭 경험을 웹앱과 기능 패리티로 끌어올리는 것.

## 0. 배경 — 왜 이 계획인가

```
oh-my-personal-best (이 플러그인)   ←── ompb-apps 가 git 의존성으로 pin (@d43a787)
= 코칭 두뇌                                = web(FastAPI/Fly)·Discord·admin surfaces
  • ompb_core (facade, 303줄)
  • scripts/ (결정론적 로직)
  • agents/*.md (8 전문가)
  • skills/ + CLAUDE.md 라우팅
```

`PLATFORMS.md`의 설계 원칙: **"가치 있는 부분은 AI 플랫폼에 결합되지 않은
platform-neutral core."** 그런데 ompb-apps는 최근 그 원칙과 반대로, surface-agnostic
도메인 로직을 앱 레이어에만 축적했다.

| ompb-apps 신규 도메인 모듈 | 줄수 | core 호출 | 플러그인 보유 |
|---|---|---|---|
| `review.py` (한 주 훈련 리뷰) | 837 | — | 부분 (`weekly-adapt` 스킬) |
| `coach.py` (대화형 코치·모델 티어링) | 573 | — | 아니오 |
| `analysis.py` | 566 | — | 부분 (scripts 분산) |
| `injury.py` (에피소드·복귀 래더·가드레일) | 441 | — | **아니오** (physio 프롬프트만) |
| `weather.py` (예보·AQI·조언) | 421 | — | **아니오** |
| `body.py` (체중·연료) | 341 | — | **아니오** (fuel 프롬프트만) |
| `status.py`/`readiness.py` | 242/131 | — | **아니오** |
| `insights.py` + `insight_detectors/`(17모듈) | 121+ | — | **아니오** |
| `zones.py` | 149 | — | 부분 (config hrmax만) |

ompb-apps가 `ompb_core`에서 실제 쓰는 심볼은 **4개뿐**(`get_state`,
`resolve_home`, `import_file`, `analyze_activity`). 수천 줄의 코칭 도메인 로직이
앱에만 있어, 두 surface가 단일 진실 원천을 공유하지 못한다.

**채택 방식(사용자 확정):** "둘 다 단계적" — Tier별로 `승격(core/scripts) + 노출
(state-schema·agent·skill·routing)`을 한 묶음으로 진행. 한 기능씩 core로 올리고
동시에 플러그인 표면에 노출해 매 단계가 완결되게.

**대상 영역(사용자 확정):** Injury+Readiness(안전) / Weather / Insights / Weekly Review.

---

## 승격 원칙 (모든 Tier 공통)

1. **단일 소스 계약.** core 승격 후 ompb-apps는 해당 모듈을 **core에서 import**하도록
   전환(중복 제거). 승격은 "복붙"이 아니라 "core가 owner, 앱은 consumer"로 만드는 것.
   앱의 surface-specific 부분(Discord 카드 텍스트, FastAPI 라우터, HTML 템플릿)은 앱에 남고,
   **계산/판정/상태 로직만** core로.
2. **결정론·stdlib 우선.** core는 `anthropic`/Claude API 호출 없음. 네트워크가 필요한
   `weather`는 timeout/retry 내장 + 캐시 TTL. LLM 판단이 필요한 부분(리뷰 서술,
   부상 코칭 톤)은 core가 아니라 **agent 프롬프트**가 담당.
3. **facade + 얇은 CLI.** 각 도메인은 `ompb_core`에 read 함수로 노출하고, write/render는
   기존 패턴대로 `scripts/<name>.py` 서브프로세스 CLI로(dedup·integrity guard·summary 계약 유지).
4. **STATE-SCHEMA 먼저.** 새 상태 파일(`injuries.jsonl`·`body.jsonl`·`weather.json`)과
   config 신규 키(`hrmax`·`wx_*`)를 `docs/STATE-SCHEMA.md`에 정의하고 나서 코드 승격.
5. **안전 게이트 유지.** 부상·플랜 변경은 `plan-critic` 게이트와 "no self-approval"
   원칙을 우회하지 않는다. 부상 상태는 plan-architect/session-coach의 **입력 가드레일**로.
6. **한계 비노출.** 메모리 원칙 `dont-expose-analysis-limits` 준수 — 분류기/데이터/롤아웃
   한계는 러너 산출물이 아니라 `docs/IMPROVEMENTS.md` 백로그로.

---

## Phase 0 — 기반 (선행, 1회)

승격 파이프라인을 깔고 이후 Phase가 같은 패턴을 반복하게 만든다.

- [ ] **레이어 경계 합의 문서화.** 어떤 함수가 core(계산/상태)이고 어떤 게 앱(surface)인지
      모듈별 경계선을 이 문서 부록에 표로. ompb-apps와의 dedup 순서(먼저 core 추가 →
      앱이 core import로 전환 → 앱 중복 코드 제거) 명시.
- [ ] **`docs/STATE-SCHEMA.md` 확장:** `injuries.jsonl`, `body.jsonl`, `weather.json`(캐시),
      `config.json`의 `hrmax`/`wx_lat`/`wx_lon`/`wx_place`/`wx_tz` 추가 정의.
- [ ] **`ompb_core` facade 확장 계약:** read 함수 시그니처 컨벤션 확정
      (`home: Optional[str]` 우선 인자, KST 오늘 처리, 빈/부분 home에도 안전 반환).
- [ ] **회귀 테스트 골격:** core 승격 모듈마다 `tests/test_<domain>.py`를 앱에서 가져와
      core 경로로 재배선(앱 테스트가 이미 존재 — `tests/test_injury*.py`, `test_body.py`,
      `test_weather.py`, `test_review_weekly.py` 등).

---

## Phase 1 — Injury + Readiness (Tier 1, 안전)

가장 먼저. 안전 레인 직결이고, `review`/`analysis`/`status`가 이미 injury에 의존하므로
하위 의존성이기도 하다.

### 1a. Injury 상태 모델 → core 승격
앱 `injury.py`(441줄)는 이미 깔끔한 surface-agnostic 모듈:
- `injuries.jsonl`(에피소드 1줄) + `snapshot(home)` = **모든 surface가 읽는 단일 소스**.
- 복귀 래더 `PHASES = rest→walk→walk_run→easy_only→build→full`, 통증 임계
  (`PAIN_OK=2`, `PAIN_FLARE=6`, `ADVANCE_STREAK=2`), `parse_mention(text)` 자연어 파싱,
  `next_phase`/`prev_phase`, `injured_dates(home,start,end)`.
- 이미 `analysis._normalize_week_plan`(플랜 가드레일: 주간 부하 캡·허용 워크아웃 제한),
  `review.week_overview`(부상일=페널티 대신 회복 처리)에 통합됨.

작업:
- [ ] `scripts/injury.py`로 승격 + `ompb_core`에 `injury_snapshot(home)`,
      `log_injury(...)`(서브프로세스 write), `injured_dates(...)` 노출.
- [ ] STATE-SCHEMA에 `injuries.jsonl` 스키마 추가.
- [ ] ompb-apps를 core import로 전환, 앱 중복 제거.

### 1b. 코칭 표면 노출
- [ ] **`physio-advisor.md` 강화:** 프롬프트-only → injury 상태를 **읽고/갱신**하도록.
      복귀 래더 단계·통증 체크인을 상태로 추적, 진행/후퇴 판정을 snapshot 기반으로.
- [ ] **plan-architect/session-coach 가드레일 입력:** 활성 부상 시 주간 부하 캡·허용 타입
      제한을 plan 생성 입력으로(이미 `analysis` 가드레일 로직 존재 → core 경유 재사용).
- [ ] **신규 스킬 `pb-injury`** (또는 physio-advisor 직접 라우팅): "무릎 아파" → 부상 로깅 →
      복귀 래더 제시 → plan 가드레일 반영. `/pb-injury` 디스패처.
- [ ] **CLAUDE.md `<routing>`** 행 추가: 통증/부상 → physio-advisor(상태 기록) FIRST.

### 1c. Readiness — 정직한 분리
앱 `readiness.py`는 **온보딩 단계 머신**(connect→goal→pb→diagnosis→week_plan→ready)이지
일일 훈련 readiness가 아니다. 두 갈래로:
- [ ] **온보딩 readiness → `pb-setup` 스킬에 흡수.** `STEPS`/`data_sufficiency`(thin/ok 임계)를
      core 헬퍼로, pb-setup이 "다음 할 일"을 안내.
- [ ] **일일 훈련 readiness(신규 합성).** 앱에 없는 능력 — `weekly_load` + injury snapshot +
      body 신호를 합쳐 간단한 부하/피로 게이팅 신호로. **새 합성이므로 보수적으로**,
      과대주장 금지. session-coach가 "오늘 충분히 회복됐나" 입력으로 사용.

---

## Phase 2 — Weather 인지 코칭 (Tier 2)

앱 `weather.py`(421줄): Met.no 예보 + Open-Meteo AQI, 위치는 config.json
(`wx_lat/lon/place/tz`)에 1회 캐시(Strava athlete city 또는 수동), 예보는 `weather.json`
2h TTL 캐시. `forecast(home)`, `advise(d)`(러닝 조언), `geocode`/`set_location`.

- [ ] **`scripts/weather.py` 승격** + `ompb_core.weather_forecast(home)` /
      `weather_advise(...)`. 네트워크는 timeout/retry/2h 캐시 그대로 — 라이브 질의당 최소 호출.
- [ ] STATE-SCHEMA에 `weather.json` 캐시 + config `wx_*` 키 추가.
- [ ] **session-coach·pb-week에 주입:** 오늘 세션/주간 카드에 예보·AQI·체감온도 기반
      조언(폭염 시 강도/시간 조정, 미세먼지 시 실내 권고). coach.py가 이미 forecast를
      코치 컨텍스트에 넣는 패턴(`coach.py:305`) — agent 입력으로 재현.
- [ ] **신규 스킬 `pb-weather`** (또는 session-coach 라우팅): "오늘 뛰기 어때?" →
      예보 + 러닝 조언. `/pb-weather` 디스패처.
- [ ] **CLAUDE.md `<routing>`** 행: 날씨/오늘 컨디션 → weather 주입된 session-coach.
- [ ] 한국 도시 자동완성(`kr_cities.py`)은 surface(UI) 성격 → 우선순위 낮음, 위치 수동
      입력 폴백만 core에.

---

## Phase 3 — Insights / 와우 모먼트 (Tier 2)

앱 `insights.py` + `insight_detectors/`(17 detector 모듈: aerobic, form_cadence,
goal_progress, hr_zones, load_recovery, pace_execution, records_milestones,
temporal_patterns, volume_distance, comparative, consistency_rhythm,
elevation_terrain, anomaly_fun 등). `detect(home, max_cards=8)`가 카드 리스트 반환.
ctx는 plan/goal/profile/diagnosis/body + `analyze_activity` 심층(`_deep_recent`)에서 빌드.

- [ ] **`scripts/insights.py` + `insight_detectors/` 패키지 승격.** 순수 계산 — core에 적합.
      `ompb_core.detect_insights(home, max_cards=8)`.
- [ ] **rate-limit 주의:** `_deep_recent`가 `analyze_activity`를 호출(Strava API) →
      "bulk 금지" 원칙대로 최근 N건만, 사용자 의도당 1회.
- [ ] **pb-report에 통합:** 와우 모먼트 섹션을 리포트에 추가(셀프-PR·숨은 신호·추세).
      `build_report.py`가 `detect_insights` 결과를 렌더.
- [ ] **신규 스킬 `pb-insights`** (또는 race-analyst 보조): "내 하이라이트" / "뭐 좋아졌어?"
      → 와우 모먼트 카드. `/pb-insights` 디스패처.
- [ ] **CLAUDE.md `<routing>`** 행: 하이라이트/성취/추세 → insights.

---

## Phase 4 — Weekly Review 풍부화 (Tier 2)

플러그인은 `weekly-adapt` 스킬을 이미 보유하나, 앱 `review.py`(837줄)는 훨씬 풍부:
- `week_overview(home, offset)`: adherence(계획 대비 수행), `day_status`(완료/미수행/회복),
  주 메타, 부상일 회복 처리, 대표 런 추출.
- 주 완료 시 자동 트리거(앱 #57/#58/#61), 미완료 주에는 처방 생성 금지(#61 fix),
  adherence 바.
- `build_prompt_for`/`context_for`: 런별 리뷰 프롬프트 + 컨텍스트(목표·최근 런·주간 부하).

작업:
- [ ] **`scripts/review.py`로 계산부 승격** + `ompb_core.week_overview(home, offset)`,
      `week_adherence(...)`. **서술(LLM)은 agent가** — core는 adherence/day_status/대표런
      같은 결정론적 계산만.
- [ ] **`weekly-adapt` 스킬 강화:** data-logger(actuals) → core `week_overview`(adherence
      계산) → race-analyst(컴플라이언스/피로) → plan-architect(다음 주 조정) → plan-critic 게이트.
      **미완료 주에는 처방 금지**(앱 #61 회귀 교훈을 스킬 가드로 명문화).
- [ ] **`pb-week`/`pb-report`에 adherence 바** 렌더(계획 대비 수행 시각화).
- [ ] **CLAUDE.md `<routing>`** 행 보강: "지난주 어땠어"/주 완료 → weekly-adapt(adherence 리뷰).

---

## Phase 5 — Body / 체중·연료 (Tier 3, 후속)

원래 Tier 3지만 fuel-advisor를 상태 기반으로 만들면 가치 큼. 4개 우선영역 외라 후순위.
- 앱 `body.py`(341줄): `body.jsonl`, `log_weight`, `trend`, 목표체중(goal.json),
  언더퓨얼링/안전 감량률(`_SAFE_LOSS_PCT_WK=0.01`) 신호.
- [ ] `scripts/body.py` 승격 + `ompb_core.body_trend(home)`/`log_weight(...)`.
- [ ] STATE-SCHEMA에 `body.jsonl` + goal.json `target_weight_kg` 추가.
- [ ] **fuel-advisor.md 강화:** 체중 추세·레이스 체중·언더퓨얼링을 상태로 읽고 조언.
- [ ] (선택) `zones.py` → `ompb_core.zones(home)` 얇은 조회 + `/pb-zones`. config `hrmax`
      override는 이미 core에 있음 → 조회 표면만.

---

## 의존성 & 순서

```
Phase 0 (기반: state-schema·facade·테스트 골격)
   └─> Phase 1 (Injury+Readiness)   ← review/analysis/status가 injury에 의존, 안전 최우선
          ├─> Phase 4 (Weekly Review)  ← week_overview가 injured_dates 사용
          ├─> Phase 2 (Weather)        ← 독립
          └─> Phase 3 (Insights)       ← ctx에 body/diagnosis 참조(부분 독립)
   └─> Phase 5 (Body)  ← Insights body detector가 참조하므로 3과 함께면 시너지
```

Phase 2·3·4는 Phase 1 이후 병렬 가능. Phase 5는 후속.

## 산출물 체크리스트 (Phase마다 반복)
- [ ] core 모듈/스크립트 + `ompb_core` facade 함수
- [ ] `docs/STATE-SCHEMA.md` 상태 정의
- [ ] agent 강화 또는 신규(`agents/*.md`)
- [ ] skill + `/pb-*` 디스패처 + `CLAUDE.md <routing>` 행
- [ ] core로 옮긴 로직의 회귀 테스트(앱 테스트 재배선)
- [ ] ompb-apps를 core import로 전환(중복 제거) — 별도 PR

## 비대상 / 보류
- **러닝화 로테이션**(`shoe_*`): 앱에서 이미 아카이빙(#46) — 보류.
- **모델 티어링/캐시**(`coach.py` #42): 앱의 비용 최적화 관심사 — 플러그인은 Claude Code가
  모델 라우팅을 하므로 비대상.
- **Discord/web 라우터·HTML 템플릿**: surface-specific — 앱에 잔류.
- **Strava 공식 MCP**: `docs/STRAVA-MCP-STRATEGY.md`가 별도 추적(eligible:false 대기 중).
