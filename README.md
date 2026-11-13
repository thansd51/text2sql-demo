# Text-to-SQL PoC 서버

자연어 질문을 **프로젝트(데이터소스)의 DB 문법에 맞는 SELECT 문으로 생성**하는 서버와 화면입니다.

| 하는 것 | 하지 않는 것 |
|---|---|
| Oracle·PostgreSQL 문법에 맞는 SELECT 생성, 행 수 제한 강제, 허용 테이블·컬럼 검증 | DB에 접속하거나 SQL을 **실행하지 않습니다** |
| 프로젝트마다 다른 코드·이름(예: 101 = 장기상품 / 정기보험)을 메타데이터로 반영 | SELECT 이외(CREATE 포함 모든 DDL·DML)는 만들지도 허용하지도 않습니다 |
| 로컬 모델, OpenAI, Claude 중 선택 | 자체 로그인은 없습니다 (접속 키 하나로 보호) |

- 백엔드: Python 3.12, FastAPI, Pydantic v2, sqlglot (패키지 관리는 uv)
- 화면: React + Vite (JavaScript). 빌드 결과를 FastAPI가 함께 제공합니다
- LLM: OpenAI 호환 API(OpenAI, Ollama, llama.cpp 등) 또는 Claude(Anthropic) 공식 API

> 이 저장소의 `datasources/`, `semantic/` 값(프로젝트 p001~p006, 코드 이름)은 **시험용 더미 값**입니다.

---

## 1. 빠른 시작 (Ubuntu)

Ubuntu 24.04(WSL2)에서 확인했습니다. 22.04는 확인 못 했습니다.

### 준비물

| 필요한 것 | 용도 | 설치 |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 파이썬 패키지 관리 (파이썬 3.12는 uv가 알아서 받습니다) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js 22 이상 | 화면 빌드 | [nodejs.org](https://nodejs.org) 또는 nvm (apt의 nodejs는 오래된 경우가 많습니다) |
| Docker | 로컬 모델, `docker compose` | [설치 안내](https://docs.docker.com/engine/install/ubuntu/) 후 `sudo usermod -aG docker $USER` |
| 메모리 8GB 이상 권장 | 로컬 모델 (모델 파일 2.3GB, 실행 중 메모리는 컨텍스트 크기에 따라 달라지며 정확한 값은 확인 못 함) | |

외부 LLM(OpenAI, Claude)만 쓰면 Docker와 모델은 필요 없습니다.

### 스크립트

모두 `scripts/` 폴더에 있습니다. zip으로 받아 실행 권한이 없다면 `chmod +x scripts/*.sh`를 한 번 하세요.

| 스크립트 | 하는 일 |
|---|---|
| `./scripts/setup.sh` | 처음 한 번: 필요한 프로그램 확인, `.env` 만들기, 파이썬·화면 패키지 설치, 화면 빌드 |
| `./scripts/download-model.sh` | 로컬 모델(Qwen3-4B-Instruct-2507, Q4_K_M, 약 2.3GB)을 `models/`에 받고 체크섬 확인 |
| `./scripts/llm-start.sh` / `llm-stop.sh` | 로컬 모델 서버(llama.cpp, Docker)를 켜고 끔. 이 PC(127.0.0.1)에서만 접근 가능 |
| `./scripts/run.sh` | 서버 + 화면 실행 (`--dev`: 화면 개발 서버와 자동 재시작) |
| `./scripts/docker-up.sh` / `docker-down.sh` | 앱과 로컬 모델을 Docker로 한 번에 켜고 끔 (파이썬·Node 설치 불필요) |
| `./scripts/test.sh` | 자동 테스트 전체 (린트, 서식, 백엔드, 화면). 실제 LLM은 부르지 않음 |
| `uv run python scripts/live_check.py` | 실행 중인 서버에 대표 질문을 보내 SQL을 확인 (**실제 모델**을 부르므로 모델이 켜져 있어야 함) |

### 방법 A. 내 PC에서 직접 실행 (로컬 모델)

```bash
./scripts/setup.sh            # 1) 설치와 화면 빌드
./scripts/download-model.sh   # 2) 모델 받기 (약 2.3GB, 끊겨도 다시 실행하면 이어서 받음)
./scripts/llm-start.sh        # 3) 모델 서버 켜기 (Docker)
./scripts/run.sh              # 4) 서버 실행 → http://127.0.0.1:8085
```

`.env.example` 기본값이 위 모델 서버(포트 8083)에 맞춰져 있어서 `.env`를 고치지 않아도 됩니다. 기본 `.env`는 **접속 키 검사가 꺼진 로컬 시험용**입니다.
브라우저에서 데이터소스를 고르고 질문하세요. 예: `장기상품 목록을 보여줘` → `TYPEID = 101` 조건이 붙은 SQL.

### 방법 B. Docker Compose (설치 없이 한 번에)

```bash
./scripts/download-model.sh   # 모델은 미리 받아 둡니다
./scripts/docker-up.sh        # 앱 + 모델 서버를 빌드해서 실행. 접속 키를 한 번 보여 줍니다
```

- 모델 서버는 밖으로 포트를 열지 않고, 앱만 `127.0.0.1:8085`에 열립니다.
- 접속 키가 필요합니다. 없으면 무작위로 만들어 한 번 보여 주고, 같은 키를 계속 쓰려면 `.env`에 `TEXT2SQL_ACCESS_KEY=<키>`를 적습니다.
- 끄기: `./scripts/docker-down.sh`

### 방법 C. 외부 LLM (OpenAI, Claude)

모델 없이 `.env`만 고치면 됩니다. `./scripts/setup.sh` 후 `.env`를 열어 아래 값을 바꾸고 `./scripts/run.sh`를 실행하세요.

| | OpenAI | Claude (Anthropic) |
|---|---|---|
| `TEXT2SQL_LLM_PROVIDER` | `openai` | `anthropic` |
| `TEXT2SQL_LLM_BASE_URL` | `https://api.openai.com/v1` | (쓰지 않음) |
| `TEXT2SQL_LLM_MODEL` | 사용할 모델 이름 | `claude-opus-5-5` 등 |
| `TEXT2SQL_LLM_API_KEY` | OpenAI API 키 | Anthropic API 키 (`sk-ant-...`) |
| `TEXT2SQL_LLM_CONTEXT_TOKENS` | 모델의 컨텍스트 크기 (예: `128000`) | `200000` |
| `TEXT2SQL_LLM_MAX_TOKENS` | `512` (추론 계열 모델은 `4096`과 `TEXT2SQL_LLM_SEND_TEMPERATURE=false`) | `4096` (생각에 쓰는 토큰도 포함) |

API 키는 `.env`(또는 배포 환경의 환경변수)에만 적고 저장소에는 올리지 않습니다. 호출 비용은 사용자 계정으로 청구됩니다.

### 문제가 생기면

| 증상 | 확인할 것 |
|---|---|
| `uv: command not found` | 설치 후 새 터미널을 여세요 |
| 모델 서버가 안 뜸 | `docker logs text2sql-llm` (메모리 부족이 흔합니다). `LLM_CTX=8192 ./scripts/llm-start.sh`로 컨텍스트를 줄여 보세요 (`.env`의 `TEXT2SQL_LLM_CONTEXT_TOKENS`도 같게) |
| 질문하면 `LLM_UNAVAILABLE`(503) | 모델 서버가 켜져 있는지, API 키·모델 이름이 맞는지. 서버 로그에 HTTP 상태코드와 오류 종류가 남습니다 |
| 서버가 시작하지 않고 `메타데이터 오류 N건` | 메시지에 **파일 이름과 위치**가 나옵니다. 그 파일을 고치세요 (3장 참고) |
| `접속 키가 설정되지 않았습니다` | `.env`에 `TEXT2SQL_ACCESS_KEY`를 적거나, 로컬 시험이면 `TEXT2SQL_AUTH_DISABLED=true` |
| 첫 질문이 매우 느림 | CPU 로컬 모델의 특성입니다. 프로젝트마다 첫 질문은 프롬프트를 처음 읽느라 20~30초 걸렸습니다 (측정값은 `docs/test-results.md`) |

---

## 2. 구조 한눈에

```
브라우저(React) ──▶ FastAPI ──▶ 파이프라인 ──▶ LLM (로컬 모델 / OpenAI / Claude)
   접속 키 입력        api        pipeline        llm
                                    │
                    ┌───────────────┼───────────────┐
                 semantic        validation       dialects
              (메타데이터)     (SQL 검증)     (Oracle·PostgreSQL)
```

### 한 번의 요청이 처리되는 순서

1. 요청 `{question, datasource_id}`를 받는다. 등록되지 않은 `datasource_id`는 400.
2. **프롬프트 만들기** — 이 프로젝트의 테이블·컬럼·관계·테이블 데이터·용어집·예시와 DB 방언 규칙을 합친다. 모델의 컨텍스트를 넘으면 질문과 관련 있는 테이블만 넣는다.
3. **LLM이 해당 DB 문법으로, 실제 테이블·컬럼 이름으로 SQL을 쓴다** (변환 없음).
4. **1차 검증** — SELECT만, 허용된 테이블·컬럼만. 실패하면 오류를 알려 주고 다시 쓰게 한다 (최대 2번).
5. **행 수 제한 강제** — Oracle은 `ROWNUM`, PostgreSQL은 `LIMIT`.
6. **최종 검증** — 허용 테이블만, 금지 노드 없음.
7. 응답 `{status, sql, references(사용한 테이블·컬럼), metadata_version}`. 답할 수 없으면 `REJECTED`.

### 코드 폴더 (`src/text2sql/`)

| 폴더 | 역할 |
|---|---|
| `api/` | 엔드포인트, 오류 응답(`{code, message}`), 접속 키 검사 |
| `pipeline/` | 프롬프트, 토큰 예산·테이블 선택, 생성·검증·재시도, 참조 추출 |
| `semantic/` | 메타데이터 모델, 파일 저장소, 시작 시 검사(레지스트리) |
| `validation/` | SQL 허용 목록 검증 (SELECT만, 위험 함수·다중 문장 금지) |
| `dialects/` | DB별 규칙 문구, 행 수 제한, 현재 날짜 함수 (Oracle, PostgreSQL) |
| `llm/` | LLM 클라이언트 (OpenAI 호환, Claude). 같은 인터페이스라 교체 가능 |

의존 방향은 `api → pipeline → (semantic, validation, dialects, llm)`입니다. 자세한 설계는 [docs/design.md](docs/design.md).

---

## 3. 메타데이터 정의 — 어떻게 관리하나

SQL 품질은 모델보다 **메타데이터**가 좌우합니다. 메타데이터는 모두 **파일**이고(Git으로 관리), 서버는 시작할 때 한 번 읽어 검사합니다. 서버가 파일을 쓰지는 않습니다.

### 3.1 큰 그림 — 폴더 4개

```
datasources/p001.json ── profiles: ["innoproduct"] ──▶ profiles/innoproduct/      테이블 정의 (제품 공통)
        │                                                ├─ product.yml                 관계(FK), 여러 테이블에 걸친 규칙
        │                                                └─ tables/OBJ_MAIN.yml …       테이블당 파일 하나
        │                                              ▲
        │                              examples/innoproduct.yml                   질문-SQL 예시 (제품 공통)
        │
        └────────── 같은 id ───────────▶ semantic/p001.json                         이 프로젝트만의 테이블 데이터(행)
```

| 폴더 | 한 줄 설명 | 같이 쓰는 범위 | 필수 |
|---|---|---|---|
| `datasources/<id>.json` | **프로젝트 등록**: 이름, DB 종류·버전, 쓰는 제품 | 프로젝트 하나 | 필수 |
| `profiles/<제품>/` | **테이블 정의**: 실제 테이블·컬럼, 동의어, 관계(FK), 사용 규칙 | 같은 제품을 쓰는 모든 프로젝트 | 필수 |
| `examples/<제품>.yml` | **질문-SQL 예시** | 같은 제품을 쓰는 모든 프로젝트 | 선택 |
| `semantic/<id>.json` | **프로젝트마다 다른 테이블 데이터**: 코드와 이름이 함께 있는 행 | 프로젝트 하나 | 선택 |

**나눈 기준**: 제품이 같으면 테이블 구조는 같으므로 `profiles`와 `examples`에 한 번만 적고, 같은 코드(`TYPEID = 101`)라도 이름이 프로젝트마다 다르면(장기상품 / 정기보험) 그 값만 `semantic`에 둡니다.
샘플은 프로젝트 6개가 모두 `innoproduct` 제품 하나를 공유합니다.

| 샘플 | DB | 설명 |
|---|---|---|
| p001 | Oracle 19c | 기본 샘플 (`OBJ_MAIN`과 `OBJINV_TYPE`의 행) |
| p002 | PostgreSQL 14 | 같은 코드, 다른 이름 (정기보험·종신보험) |
| p003 | Oracle 11g | 11g 방언 (FETCH FIRST 불가) |
| p004 | Oracle 12c | semantic 파일이 `{}` (데이터 없음) |
| p005 | PostgreSQL 16 | 항목(허용값) 행이 여러 개 |
| p006 | Oracle 19c | semantic 파일 자체가 없음 |

### 3.2 파일 형식

**`datasources/p001.json`** — 프로젝트 등록

```json
{ "id": "p001", "name": "샘플 프로젝트 1", "db_type": "oracle", "db_version": "19c" }
```
`db_type`은 `oracle` 또는 `postgresql`. `profiles`를 적지 않으면 `["innoproduct"]`를 씁니다. 파일 이름과 `id`는 같아야 합니다.

**`profiles/innoproduct/tables/OBJ_MAIN.yml`** — 테이블 하나 (파일 이름 = 테이블 이름)

```yaml
name: OBJ_MAIN                  # 실제 DB의 테이블 이름. 파일 이름과 같아야 한다
description: 상품 객체와 항목의 허용값을 저장한다
group: 상품                     # 업무 영역 (선택)
name_column: OBJ_NAME           # 행의 "이름"이 들어 있는 컬럼 (선택, semantic 행을 보여 줄 때 쓴다)
key_columns: [TYPEID, R10_1]    # 그 행을 조회할 때 조건으로 쓰는 컬럼 (선택)
rules:                          # 이 테이블을 쓸 때 반드시 지킬 조건. 프롬프트에서 테이블 바로 아래에 나온다
  - 상품 객체를 조회할 때는 TYPEID <> 0 조건을 쓴다
columns:
  - name: TYPEID                # 실제 DB의 컬럼 이름
    type: number                # number | string
    description: 오브젝트 유형 코드
    synonyms: [유형코드, 세부유형]   # 질문에 나올 수 있는 한글 표현
```

**`profiles/innoproduct/product.yml`** — 제품 공통

```yaml
product: innoproduct
relationships:                  # FK. 테이블이 달라도 같은 컬럼으로 이어지는 조인 키 (from, to는 테이블.컬럼)
  - from: OBJ_INV.SID
    to: OBJ_MAIN.SID
    note: 상위 오브젝트
glossary:                       # 여러 테이블에 걸친 규칙만 (한 테이블 규칙은 그 테이블의 rules에)
  - 시작일(VF_DT)과 종료일(VT_DT)은 YYYYMMDD 문자열이다 ...
```

**`semantic/p001.json`** — 프로젝트의 테이블 데이터. **최상위가 바로 `테이블명: [행 목록]`** 입니다.

```json
{
  "OBJ_MAIN": [
    { "SID": "1001", "BIZCODE": "TYPE101", "TYPEID": "101", "R10_1": "", "OBJ_NAME": "장기상품", "VF_DT": "20200101", "VT_DT": "99991231" },
    { "SID": "2001", "BIZCODE": "ITEM0031", "TYPEID": "0", "R10_1": "#S00000031", "OBJ_NAME": "보장기간", "VF_DT": "20200101", "VT_DT": "99991231" }
  ],
  "OBJINV_TYPE": [
    { "INV_TYPE": "11", "TYPE_GBN": "1", "TYPE_NAME": "기본 상품구조", "END_DT": "99991231" }
  ]
}
```

**`examples/innoproduct.yml`** — 모든 프로젝트가 함께 쓰는 예시

```yaml
product: innoproduct
examples:
  - question: 유형코드가 101인 오브젝트의 코드와 이름
    sql: SELECT BIZCODE, OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101
```

### 3.3 규칙

- **테이블·컬럼 이름은 실제 DB의 이름**입니다. 모델도 이 이름으로 SQL을 씁니다. 한글은 `description`과 `synonyms`에 둡니다.
- **semantic의 행**은 실제 테이블의 행입니다. 이름(`장기상품`)은 `TYPEID`의 속성이 아니라 **같은 행의 `OBJ_NAME` 값**입니다.
  - 행에는 **그 테이블 정의의 컬럼을 모두** 적고, 값이 없으면 `null`이 아니라 **`""`** 로 둡니다. 숫자도 문자열(`"101"`)로 적습니다.
  - 같은 테이블의 모든 행은 같은 컬럼을 가져야 합니다.
- **예시**는 기본 문법으로 쓰고 행 제한과 날짜 함수는 쓰지 않습니다 (서버가 DB에 맞게 처리). 코드(`TYPEID = 101`)는 써도 되지만 이름(장기상품)은 프로젝트마다 달라서 쓰지 않습니다.
- 규칙을 어디에 적을지: **한 테이블에만 해당하면** 그 테이블 파일의 `rules`, **여러 테이블에 걸치면** `product.yml`의 `glossary`.
- YAML에서 따옴표 없는 문자열에 ` : `를 넣으면 "키: 값"으로 읽힙니다. 설명에 쉼표가 있으면 컬럼은 위 예시처럼 블록 스타일로 씁니다.

### 3.4 모델에게는 이렇게 보입니다

`name_column`과 `key_columns`를 지정하면 semantic의 행이 **`이름: 그 행을 가리키는 조건`** 으로 프롬프트에 들어갑니다. `SID`나 날짜 같은 컬럼은 행에 있어도 조건으로 보여 주지 않습니다.

```
테이블 데이터 (실제 행에서 뽑은 것. ...):
OBJ_MAIN:
- 장기상품: TYPEID = 101
- 보장기간: TYPEID = 0 AND R10_1 = '#S00000031'
OBJINV_TYPE:
- 기본 상품구조: INV_TYPE = 11 AND TYPE_GBN = 1 AND END_DT = '99991231'
질문에 위 이름이 나오면 그 이름을 문자열로 비교하지 말고 같은 줄의 조건을 그대로 씁니다.
```

이렇게 한 이유: 행을 그대로 보여 주었을 때 4B 로컬 모델이 `OBJ_NAME = '장기상품'`처럼 이름 문자열로 비교해서 10개 질문 중 4개만 맞았고, 이 형태로 바꾸자 10개가 모두 맞았습니다 ([docs/test-results.md](docs/test-results.md)).

### 3.5 시작할 때 검사합니다

문제가 하나라도 있으면 서버가 **시작하지 않고** 한국어로 파일 이름과 위치를 알려 줍니다 (여러 문제를 한꺼번에 모아서). 예:
`profiles/innoproduct/tables/OBJ_MAIN.yml: columns[1].type: 필수 항목이 없습니다`

- 파일 이름과 `id`·`name`이 다름, 알 수 없는 항목(오타), 같은 이름·키 중복, 필수 항목 누락
- semantic의 테이블·컬럼이나 `relationships`가 profile에 없는 것을 가리킴, 같은 테이블의 행마다 컬럼이 다름, 값이 `null`
- 공통 예시가 프로젝트의 테이블과 DB 문법에서 통과하지 못함 (프로젝트마다 DB가 달라서 각각 검사)
- `db_version`을 읽을 수 없음, 모델 컨텍스트 설정이 너무 작아 테이블 하나도 못 담음

### 3.6 자주 하는 작업

| 하고 싶은 일 | 방법 |
|---|---|
| 테이블 추가 | `profiles/<제품>/tables/<테이블>.yml`을 추가하고, 조인 키는 `product.yml`의 `relationships`에 적는다 |
| 코드·이름 추가·수정 | 해당 프로젝트의 `semantic/<id>.json`에서 그 테이블의 행을 추가·수정한다 (컬럼은 모두 적고, 값이 없으면 `""`) |
| 새 프로젝트 등록 | `datasources/<id>.json`을 추가한다 (필요하면 `semantic/<id>.json`도) |
| 모델이 조건을 자꾸 빠뜨림 | 해당 테이블 파일의 `rules`에 규칙을 적거나, 비슷한 질문의 예시를 `examples`에 추가한다 |
| 질문의 표현을 못 알아들음 | 컬럼의 `synonyms`를 추가한다 |

수정한 뒤에는 `./scripts/test.sh`로 샘플 검증을 돌리고, 서버를 시작해서 시작 검사를 통과하는지 확인하세요. 모델 동작은 `scripts/live_check.py`로 확인합니다.

### 3.7 버전과 반영

- 응답의 `metadata_version`은 그 프로젝트를 이루는 파일들의 내용 해시입니다. 파일이 바뀌면 값이 바뀌므로 어떤 메타데이터로 만든 SQL인지 구분할 수 있습니다.
- 서버는 시작할 때만 파일을 읽습니다. **파일을 고친 뒤 서버를 다시 시작**해야 반영됩니다 (Docker 이미지는 다시 빌드). 웹에서 등록·수정하는 기능은 후속 범위입니다.
- 실제 고객사 메타데이터를 저장소에 올리기 전에는 반출 허용을 확인하세요. 확인 전에는 샘플이나 익명화한 값만 씁니다.

---

## 4. 설정 (환경변수)

접두사는 모두 `TEXT2SQL_`입니다. 전체 목록과 설명은 [`.env.example`](.env.example)에 있습니다. 비밀 값(API 키, 접속 키)은 `.env` 또는 배포 환경의 환경변수에만 둡니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`(OpenAI 호환 API) 또는 `anthropic`(Claude) |
| `LLM_BASE_URL` | `http://localhost:8084/v1` | OpenAI 호환 서버 주소 (`.env.example`은 로컬 모델 `8083`) |
| `LLM_MODEL`, `LLM_API_KEY` | `default`, 없음 | 모델 이름, API 키 |
| `LLM_CONTEXT_TOKENS` | `16384` | 모델이 받을 수 있는 토큰. 프롬프트가 넘치면 관련 테이블만 넣는다. Ollama는 `num_ctx`와 같게 |
| `LLM_MAX_TOKENS` | `512` | 답변 최대 토큰 (Claude·추론 모델은 `4096` 이상) |
| `ACCESS_KEY` | 없음 | 접속 키(`X-Access-Key`). **없으면 서버가 시작하지 않습니다** |
| `AUTH_DISABLED` | `false` | `true`면 접속 키 검사를 끕니다. **로컬 시험에서만** |
| `MAX_REPAIR_ATTEMPTS` | `2` | 검증에 실패했을 때 다시 쓰게 하는 최대 횟수 |
| `MAX_QUESTION_LENGTH` | `500` | 질문 최대 글자 수 |
| `MAX_ROWS` | `1000` | 결과 행 수 상한 (최종 SQL에 강제) |

---

## 5. 배포와 보안

- **이미지**: `Dockerfile`이 화면을 빌드하고 서버 이미지를 만듭니다 (일반 사용자 권한, 읽기 전용 파일시스템에서 동작). 포트는 `PORT` 환경변수를 씁니다. 헬스체크 `GET /health`.
- **환경변수**(배포 서비스의 Variables)에 `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_CONTEXT_TOKENS`, `ACCESS_KEY`를 넣습니다. `AUTH_DISABLED`는 넣지 않습니다.
- **접속 키**: 모든 API(`/health` 제외)는 `X-Access-Key`가 맞아야 합니다. 화면이 키 입력 카드를 보여 주고, 키는 그 탭을 닫으면 사라집니다. 키가 없으면 서버가 시작하지 않습니다.
- 인증을 켠 상태에서는 `/docs`, `/redoc`, `/openapi.json`을 닫습니다. 소스 파일과 `.env`는 서빙하지 않습니다.
- **알려진 보안 한계**: 접속 키를 틀려도 요청 횟수 제한이 없습니다(초당 약 130회 시도 가능). 키를 **길고 무작위**로 만드세요. 점검 결과는 [docs/test-results.md](docs/test-results.md).
- 내 PC를 임시로 공개할 때(Cloudflare 임시 터널 등)는 **접속 키를 반드시 켜고**, 모델 서버 포트(8083)를 터널에 연결하지 마세요.

---

## 6. 테스트와 검증

```bash
./scripts/test.sh                       # 자동 테스트: 백엔드 966건 + 화면 64건 (실제 LLM 호출 없음)
uv run python scripts/live_check.py     # 실제 모델로 대표 질문 11개 확인 (모델이 켜져 있어야 함)
```

| 항목 | 결과 |
|---|---|
| 자동 테스트 | 백엔드 966건, 화면 64건 통과. 린트·서식 통과 |
| 실제 모델(Qwen3-4B, CPU) | 대표 질문 10개 **10/10** (이름 → 코드 조건 변환). 이전 방식은 3~4/10 |
| 깨끗한 환경(zip을 푼 상태) | `setup.sh` → `test.sh` → `run.sh` 모두 성공, Docker 앱 컨테이너 정상 |
| 보안 점검 | 키 없는 요청·잘못된 키·경로 조작·대용량 본문·주입 시도 모두 차단 |

자세한 내용과 **확인하지 못한 것**은 [docs/test-results.md](docs/test-results.md)에 있습니다.

---

## 7. 유지보수·확장 계획

상세는 [docs/roadmap.md](docs/roadmap.md)입니다. 요약:

| 시기 | 항목 |
|---|---|
| 실제 DB 컬럼 문서와 대조(확인 필요 목록), 평가 질문 확대와 조건 누락 자동 점검, 실서비스 모델 확정 후 품질·속도 측정, 접속 키 요청 제한 |
| 메타데이터 DB 저장과 등록 화면, DB 카탈로그에서 profile 초안 생성(Importer), 질문 이력·피드백, 프롬프트 캐싱·동시 처리 |
| MySQL·HANA 방언, 질문과 비슷한 예시 검색(RAG), 호스트 서비스 로그인 연동, `CREATE VIEW` 생성문 변환, 고객사 시스템과의 실행 연동 |

확장하기 쉽도록 **교체 지점**(`llm/`의 LLM, `dialects/`의 DB 방언, `semantic/`의 저장소)은 인터페이스로 분리했습니다. 새 테이블·프로젝트는 파일만 추가하면 됩니다 (3.6).

---

## 8. 알려진 한계

- **DB를 실행하지 않아** 생성한 SQL이 실제 데이터에서 맞는지는 확인하지 않았습니다. 문법과 허용 목록만 검증합니다.
- 4B 로컬 모델은 질문에 없는 조건을 빠뜨리거나 추가할 수 있습니다. 규칙(`rules`)과 예시로 줄이지만 보장하지는 않습니다.
- 테이블이 수십 개일 때의 테이블 선택 품질, 동시 사용자, OpenAI·Claude 연동은 실제로 확인하지 못했습니다 (`docs/test-results.md`).
- 샘플의 일부 가정(예: 항목 허용값 행의 `TYPEID`가 0)은 실제 DB로 확인하지 못했습니다 (`docs/design.md`의 "확인 필요").

---

## 폴더

```
src/text2sql/   서버 코드 (api, pipeline, semantic, validation, dialects, llm)
profiles/       테이블 정의 (제품별 폴더: product.yml + tables/<테이블>.yml)
examples/       질문-SQL 예시 (제품 공통)
datasources/    프로젝트 등록 정보
semantic/       프로젝트마다 다른 테이블 데이터
frontend/       React 화면
scripts/        설치·실행·모델·Docker·테스트 스크립트
tests/          백엔드 테스트
docs/           design.md(설계), test-results.md(시험 결과), roadmap.md(계획)
Dockerfile, docker-compose.yml, .env.example
```
