[English](README.md) | 한국어

# oh-my-personal-best

[![Release](https://img.shields.io/github/v/release/seungwee-choi/oh-my-personal-best?color=f97316)](https://github.com/seungwee-choi/oh-my-personal-best/releases)
[![License: MIT](https://img.shields.io/github/license/seungwee-choi/oh-my-personal-best?color=green)](https://github.com/seungwee-choi/oh-my-personal-best/blob/main/LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-Plugin-d97757)](https://docs.anthropic.com/claude-code)

**마라톤 기록 단축(10K / Half / Full)을 위한 멀티 에이전트 오케스트레이션. 학습 곡선 제로.**

_러닝을 공부하지 마세요. 그냥 목표 기록만 말하세요._

[시작하기](#빠른-시작) • [동작 원리](#동작-원리) • [데이터 입력](#데이터-입력) • [상태](#상태) • [안전](#안전)

---

## 빠른 시작

**Step 1: 설치**

Claude Code 슬래시 커맨드입니다 — **한 줄씩** 입력하세요:

```bash
/plugin marketplace add https://github.com/seungwee-choi/oh-my-personal-best
```

다음:

```bash
/plugin install oh-my-personal-best
```

**Step 2: `/pb-setup` 실행**

설치 후 `/pb-setup`을 실행하세요 (COROS/Garmin export 파일이나 CSV 경로를 선택적으로 전달할 수 있습니다):

```
/pb-setup
/pb-setup /path/to/coros-export.zip
```

`/pb-setup`은 데이터 디렉토리(OMPB_HOME, 기본값 `~/.ompb`)를 확인하고, 의존성을 점검하며, 기존 활동 데이터를 임포트해 러너 프로필과 PB 이력을 초기화합니다. 이어서 초기 체력 진단을 실행하고 첫 번째 분석 덱을 만들어 줍니다 — 지금 상태를 한눈에 파악하고 시작할 수 있습니다. 셋업이 완료되면 일상 루프는 `/pb-today`, `/pb-log`, `/pb-deck`, `/pb-plan`입니다.

---

**Step 3: 목표를 말하세요**

설정 양식 없습니다. 그냥 자연어로 원하는 걸 말하면 됩니다:

```
"풀코스 sub-3:30 만들고 싶어"
"10K 50분인데 45분 가고 싶어, 16주 남음"
```

처음이라면 OMPB가 최소한의 정보(최근 레이스 또는 현재 PB, 주간 마일리지, 목표, 대회 날짜)만 먼저 물어본 뒤 계획을 만듭니다.

**Step 4: 한 주를 돌리세요**

```
"오늘 뭐 뛰어?"
"12km 이지로 뛰었어, 평균 심박 142"
"이번 주 계획 조정해줘"
```

끝입니다. 모든 말이 알맞은 전문가에게 자동으로 라우팅됩니다.

### 어디서 시작해야 할지 모르겠다면?

지금 상태와 가고 싶은 곳만 말하세요 — _"하프 첫 도전, 10K는 55분, 12주 남음."_ OMPB가 현재 체력을 진단하고, 목표가 현실적인지 판단한 뒤, 그 격차를 메우는 계획을 만듭니다. 템포런이나 테이퍼가 뭔지 몰라도 됩니다.

---

## 세션 내 단축 명령

쓸 필요 없습니다 — 자연어만으로 충분합니다. 하지만 명시적 명령을 선호한다면 얇은 디스패처가 준비돼 있습니다:

| 커맨드 | 라우팅 | 효과 |
|---|---|---|
| `/pb-setup [경로]` | `pb-setup` 스킬 | 첫 실행 온보딩: 데이터 임포트, 프로필 초기화, 초기 덱 생성 |
| `/pb-plan "16주 sub-3:30 풀코스"` | `race-plan` 스킬 | 완성된 주기화 훈련 계획 생성 |
| `/pb-today` | `session-coach` | 오늘 세션 받기 |
| `/pb-log <경로 또는 텍스트>` | `data-logger` | 기록 입력 (.fit/.zip/CSV 파일, 또는 자연어) |
| `/pb-deck` | `pb-deck` 스킬 | 분석을 self-contained HTML 슬라이드 덱으로 렌더 |
| `/pb-report` | `pb-report` 스킬 | 인쇄·PDF용 종합 훈련 리포트 생성 |
| `/pb-connect-strava` | `pb-connect-strava` 스킬 | Strava 연동 (최초 1회) 및 활동 동기화 |

| 이렇게 말하면 (예시) | 라우팅 |
|---|---|
| "풀코스 sub-3:30" / "훈련 계획" / 목표 기록 | `race-plan` (진단 → 주기화 → 게이트 → 전달) |
| "오늘 뭐 뛰어?" | `session-coach` |
| "무릎이 아픈데 롱런 해도 돼?" | `physio-advisor` (안전 게이트 우선) |
| "레이스 3일 전인데 뭐 먹어?" | `fuel-advisor` + `pace-strategist` |
| "지난주 기록 어땠어?" / "12km 이지 뛰었어" | `data-logger` |
| "이번 주 계획 조정해줘" | `weekly-adapt` |
| "다음 주가 대회야" / "테이퍼" | `race-week` (병렬 협의) |

---

## 왜 oh-my-personal-best인가?

- **학습 곡선 제로** — 러닝 용어 불필요. 목표만 말하면 전문가가 나머지를 합니다.
- **전문가 라우팅** — 4개 레인의 코칭 에이전트 8명, 매번 알맞은 전문가가 호출됩니다.
- **모델 라우팅** — 진단·설계·게이트는 Opus, 세션 처방은 Sonnet, 로깅은 Haiku. 중요한 곳엔 품질, 그 외엔 저비용.
- **Self-approve 금지** — 모든 계획은 별도의 생리학적 안전 게이트를 통과한 뒤에야 노출됩니다.
- **안전 우선** — 통증 신호는 계획을 무시하고 우선합니다. 코치이지, 의사가 아닙니다.
- **데이터 통합** — CSV 업로드와 자연어 보고가 하나의 훈련 로그로 정규화됩니다.

---

## 동작 원리

4개 레인에 걸친 8명의 전문가 에이전트. 사용자가 에이전트를 고르지 않습니다 — OMPB가 말에 따라 라우팅합니다.

### 8명의 에이전트

| 레인 | 에이전트 | 모델 | 역할 |
|---|---|---|---|
| **진단** | `race-analyst` | Opus | PB / GPS / HR 기반 체력 진단 — 당신의 #1 약점을 특정 |
| **진단** | `data-logger` | Haiku | 세션 기록, CSV 업로드와 자연어 보고를 정규화 |
| **계획** | `plan-architect` | Opus | 주기화 설계: Base → Build → Peak → Taper |
| **계획** | `session-coach` | Sonnet | 구체적 일일 세션 처방 — 인터벌·템포·롱런 |
| **계획** | `pace-strategist` | Sonnet | 레이스 스플릿, 페이스 전략, 플랜 B |
| **지원** | `physio-advisor` | Sonnet | 부상 예방, 회복, 통증 신호 안전 게이트 |
| **지원** | `fuel-advisor` | Sonnet | 영양, 카보로딩, 레이스 연료 스케줄 |
| **게이트** | `plan-critic` | Opus | 생리학적 품질 게이트 — 승인 없이는 어떤 계획도 노출되지 않음 |

### 4개의 스킬

4개 워크플로우가 훈련 전 주기를 커버합니다:

| 스킬 | 하는 일 |
|---|---|
| `race-plan` | 목표 → 완성 계획 한 번에: 진단 → 주기화 → 세션 채움 → 게이트 → 전달 |
| `weekly-adapt` | 주간 적응 루프: 실제 로그 → 피로 평가 → 다음 주 조정 → 게이트 |
| `race-week` | 레이스 직전 병렬 협의: 페이스 + 연료 + 피지오 동시 → 하나의 레이스데이 브리프 |
| `pb-deck` | 분석 → self-contained HTML 슬라이드 덱 (인라인 SVG 차트, 오프라인 실행) |
| `pb-report` | 분석 → 인쇄·PDF용 종합 리포트 문서 (`pb-deck` 슬라이드 덱의 문서 버전) |

게이트 레인이 일반 AI 어시스턴트와의 핵심 차이입니다: **`plan-critic`이 모든 계획을 당신이 보기 전에 검토합니다.** Self-approve 없음. 위험한 적재량 증가나 부족한 테이퍼가 담긴 계획은 절대 당신에게 도달하지 않습니다.

---

## 데이터 입력

모든 경로가 동일한 `training-log.jsonl` 스키마로 정규화됩니다. 어떤 경로인지 신경 쓸 필요 없습니다 — `data-logger`가 라우팅을 처리합니다.

**현재 사용 가능**
- **기기 파일 (`.fit`)** — COROS / Garmin export 폴더·개별 파일·`.zip`을 `scripts/import_fit.py`로 파싱. 러닝은 거리로 easy/long 분류, 그 외 종목(사이클·수영 등)은 `cross`로 적재해 총 훈련 부하를 포착. 재임포트는 활동 ID로 중복 제거. `fitdecode` 필요 (`requirements.txt` 참고).
- **CSV 업로드** — Strava 활동 export를 `scripts/import_csv.py`로 파싱 (표준 라이브러리만 사용)
- **자연어** — "12km 이지로 5:30에 뛰었어" → 파싱 후 적재
- **Strava API** — `/pb-connect-strava`로 최초 1회 연동 (본인 Strava 앱 + localhost OAuth); `import_strava.py`가 액세스 토큰을 자동 갱신하고 모든 활동을 동기화합니다. 인증 정보는 `~/.ompb/strava.json`에 저장됩니다 (chmod 600, 절대 커밋하지 마세요).

**Garmin / COROS**
- 이들은 **개인용 API가 없습니다** — Garmin·COROS 개발자 프로그램은 기업/파트너 전용이라 개인이 per-user OAuth를 쓸 수 없습니다. 대신 위의 두 경로를 쓰세요: `.fit`을 export 해서 `/pb-log` 하거나, **워치의 Strava 자동 연동**(Garmin/COROS 앱에서 토글 하나)을 켠 뒤 `/pb-connect-strava` 실행 — Garmin/COROS 활동이 Strava를 거쳐 들어옵니다. 분석 에이전트는 통합 로그만 읽으므로 출처는 무관합니다.

---

## 상태

모든 것은 OMPB_HOME (`~/.ompb` 기본값) 아래 지속됩니다:

| 파일 | 내용 |
|---|---|
| `runner-profile.json` | 나이, 성별, 현재 PB(10K / Half / Full), 주간 마일리지, 부상 이력 |
| `goal.json` | 목표 종목, 목표 기록, 대회 날짜, 남은 주차 |
| `training-log.jsonl` | 추가 전용 일일 세션 — 계획 vs 실제: 거리, 페이스, 심박, RPE |
| `pb-history.json` | 대회 날짜가 포함된 PB 타임라인 |
| `plan-state.json` | 현재 단계, 주차, 이번 주 목표 적재량, `critic_approved` 플래그 |

`plan-state.json`의 `critic_approved`가 `true`여야만 계획이 노출됩니다. `plan-critic`만 이 값을 설정할 수 있습니다.

---

## 안전

- **통증, 부상, 또는 신체 증상** → `physio-advisor`가 즉시 인계받습니다. GREEN 또는 YELLOW 클리어런스가 나올 때까지 훈련 처방은 억제됩니다.
- **RED 판정** → 모든 계획 생성이 중단되고, OMPB가 스포츠 의학 검진을 권고합니다. 레이스 일정은 러너의 안전에 종속됩니다.
- **점진적 과부하** → 주간 적재량 증가는 ~10%/주로 제한됩니다. `plan-critic`이 이를 위반하는 계획을 반려합니다.
- **코치이지 의사가 아님** → OMPB는 코칭 시스템입니다. 의학적 진단이나 약물 처방을 하지 않습니다. 의심되면 스포츠 의학 전문가를 찾으세요.

---

## 비범위

OMPB가 하지 않는 것: 의학적 진단·치료, 엘리트 선수를 위한 공인 코치 대체, 비러닝 종목 주기화 관리, 특정 완주 기록 보장.

---

## 요구사항

- [Claude Code](https://docs.anthropic.com/claude-code) CLI
- Claude Max/Pro 구독 또는 Anthropic API 키
- `scripts/import_csv.py`용 Python 3 (stdlib만 사용)

---

## 라이선스

MIT

---

<div align="center">

**학습 곡선 제로. 더 빠른 결승선.**

</div>
