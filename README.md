# 📚 Daily Research Paper Slack Bot

내 연구 분야의 최신 논문을 매일 자동으로 탐색·수집하고, 최신 LLM(Google Gemini / OpenAI)을 통해 핵심을 한글로 요약하여 슬랙(Slack) 채널로 깔끔한 카드 메시지를 전송해 주는 자동화 프로그램입니다.

---

## ✨ 주요 기능

- 🔍 **다양한 학술 소스 지원**: arXiv API(CS, AI, Math, Physics 등) 및 PubMed E-utilities 기본 지원
- 🧠 **스마트 LLM 요약**:
  - 연구자의 관심 주제에 맞춰 논문 관련성 평가 및 랭킹 산정
  - 연구 배경, 제안 방법, 주요 의의 3단 핵심 요약 + 1줄 요약(TL;DR) 생성
- 🚫 **스마트 중복 제거**: SQLite DB(`data/history.db`)를 통해 이미 슬랙으로 전달받은 논문은 중복 발송되지 않음
- 💬 **깔끔한 슬랙 UI**: Slack Block Kit 기반의 정돈된 카드 레이아웃 (제목, 저자, 발표일, 요약, 태그, 원문/PDF 링크)
- ⏰ **완전 무료 자동화**: GitHub Actions를 통해 PC를 켜놓지 않아도 매일 아침(예: 08:30 KST) 무료 자동 실행 가능

---

## 📁 프로젝트 구조

```text
daily-paper-slack-bot/
├── config.yaml              # 연구 분야, 키워드, 모델, 슬랙 제목 등 설정
├── .env.example             # 환경변수 템플릿 (Slack Webhook URL, Gemini API Key)
├── requirements.txt         # 종속성 패키지 목록
├── main.py                  # 진입점 실행 스크립트
├── run_local.sh             # 로컬 실행 및 로그 기록 스크립트
├── src/
│   ├── config.py            # 설정 및 환경변수 로더
│   ├── db.py                # SQLite 중복 발송 방지 데이터베이스
│   ├── fetchers/            # 논문 수집기 (base, arxiv, pubmed)
│   ├── summarizer.py        # Gemini / OpenAI 요약기
│   └── notifier.py          # Slack Block Kit 메시지 생성 및 웹훅 발송
├── tests/
│   └── test_pipeline.py     # 단위 테스트
└── .github/
    └── workflows/
        └── daily_run.yml    # GitHub Actions 일일 자동 스케줄러
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 가상환경 생성 및 패키지 설치
```bash
cd /Users/jaehyeon/.gemini/antigravity/scratch/daily-paper-slack-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경변수 설정 (`.env`)
`.env.example` 파일을 복사하여 `.env`를 생성하고 API 키를 입력합니다.
```bash
cp .env.example .env
```

`.env` 파일 내용:
```env
# 1. 슬랙 웹훅 URL (필수)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../XXXXXX

# 2. Gemini API 키 (https://aistudio.google.com/ 에서 무료 발급)
GEMINI_API_KEY=AIzaSy...

# 3. 노션 연동 (선택: 슬랙 전송과 동시에 노션 DB에 자동 아카이빙할 경우)
NOTION_API_KEY=ntn_...
NOTION_DATABASE_ID=your_32_character_database_id
```

> **슬랙 Webhook URL 발급 방법 (1분 소요)**:
> 1. [Slack API Apps](https://api.slack.com/apps) 접속 후 **Create New App** 클릭
> 2. **From scratch** 선택 → 앱 이름 입력 및 워크스페이스 선택
> 3. 좌측 메뉴의 **Incoming Webhooks** 클릭 → 토글을 **On**으로 활성화
> 4. 하단의 **Add New Webhook to Workspace** 클릭 후 논문 요약을 받을 채널 선택
> 5. 생성된 `Webhook URL`을 복사하여 `.env`에 붙여넣기

> **노션(Notion) 연동 설정 방법 (2분 소요)**:
> 1. [Notion 내 통합(Integrations)](https://www.notion.so/profile/integrations)에서 **새 통합 만들기** (예: `Paper-Bot`) → `내부 통합 토큰(secret_...)` 복사 후 `NOTION_API_KEY`에 입력
> 2. 노션에서 논문을 저장할 데이터베이스 페이지를 생성하고, 우측 상단 `···` → `연결(Connect to)`에서 방금 만든 `Paper-Bot`을 추가하여 권한 부여
> 3. 데이터베이스 URL의 `notion.so/workspace/<32자리ID>?v=...` 에서 `<32자리ID>`를 복사하여 `NOTION_DATABASE_ID`에 입력
> 4. **권장 데이터베이스 컬럼 속성**:
>    - `제목` (Title) / `저자` (Text) / `출판연도` (Number) / `저널` (Select) / `DOI` (URL) / `분야/주제` (Multi-select) / `상태` (Status) / `읽은 날짜` (Date)
>    - 각 논문 페이지 본문에는 **💡 한 줄 요약, 🎯 풀려는 문제, ⚙️ 접근 방법, 📊 핵심 결과, ✨ 기여점/새로운 점, 📄 원문 초록**이 체계적으로 자동 기록됩니다.

---

## ⚙️ 내 연구 분야 맞춤 설정 (`config.yaml`)

현재 사용자의 요청에 따라 **양자컴퓨팅, 양자머신러닝, 양자알고리즘, 양자오류정정** 분야에 최적화되어 있습니다:

```yaml
arxiv:
  categories:
    - quant-ph  # Quantum Physics (핵심)
    - cs.ET     # Emerging Technologies (양자 하드웨어/아키텍처)
    - cs.LG     # Machine Learning (양자머신러닝 교차 게재)

  keywords:
    - "quantum computing"
    - "quantum machine learning"
    - "quantum algorithm"
    - "quantum error correction"
    - "fault-tolerant quantum"
    - "variational quantum"
    - "surface code"
    - "quantum circuit"

  max_results: 40  # 5~10편 선별을 위한 후보 풀
  lookback_days: 3 # 최근 3일 이내 발행 논문 (주말 공백 대비)

summarizer:
  provider: gemini
  model: gemini-2.5-flash
  min_k: 5         # 하루 최소 전송 논문 수
  max_k: 10        # 하루 최대 전송 논문 수
  language: ko     # 한국어 요약
  research_interest: >
    양자컴퓨팅(Quantum Computing), 양자머신러닝(Quantum Machine Learning / QML),
    양자알고리즘(Quantum Algorithms: VQE, QAOA 등),
    양자오류정정(Quantum Error Correction / QEC: 표면 코드, 결함 허용 양자 연산)
```

---

## 🧪 실행 및 테스트

### ① 슬랙 연결 테스트 (웹훅 작동 확인)
```bash
python3 main.py --test-slack
```
정상 연결 시 슬랙 채널에 축하 카드 메시지가 발송됩니다.

### ② 미리보기 모드 (Dry-run, 슬랙 전송 없이 터미널 출력)
```bash
python3 main.py --dry-run
```

### ③ 실제 1회 실행 (논문 요약 후 슬랙 전송 + DB 기록)
```bash
python3 main.py
```

---

## ⏰ 매일 자동 실행 설정 방법

### 방법 A: GitHub Actions (가장 추천: 컴퓨터를 켤 필요 없음)
1. 이 프로젝트 코드를 개인 GitHub 리포지토리(Private 추천)에 push합니다.
2. GitHub 리포지토리의 **Settings** → **Secrets and variables** → **Actions** 로 이동합니다.
3. **New repository secret**을 클릭하여 다음 2개의 Secret을 등록합니다:
   - `SLACK_WEBHOOK_URL` : 내 슬랙 웹훅 URL
   - `GEMINI_API_KEY` : 구글 Gemini API 키
4. `.github/workflows/daily_run.yml`에 의해 **매일 한국 시간 08:30 (UTC 23:30)** 에 자동으로 실행되며, 이미 발송된 논문 이력(`history.db`)이 자동으로 커밋되어 중복 발송을 방지합니다.

### 방법 B: Mac 로컬 스케줄러 (`crontab`)
개인 Mac에서 매일 아침 9시에 실행하고 싶은 경우:
```bash
crontab -e
```
아래 한 줄을 추가합니다:
```cron
0 9 * * * /Users/jaehyeon/.gemini/antigravity/scratch/daily-paper-slack-bot/run_local.sh
```
