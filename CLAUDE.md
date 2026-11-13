# 프로젝트: Text-to-SQL PoC 서버

## 언어
- 답변, 코드 주석, 사용자에게 보이는 모든 문자열(API 오류 메시지, 로그, 검증 오류)은 한국어
- 변수·함수·파일명, 오류 코드 상수, 커밋 메시지는 영어
- API 오류 응답은 { code: 영어 상수, message: 한국어 } 형태

## 스택과 명령어
- 백엔드: Python 3.12, uv, FastAPI, Pydantic v2, pydantic-settings, PyYAML, sqlglot, pytest, ruff
- 프런트: frontend/ 에 React + Vite (JavaScript만, TypeScript 금지)
- 실행: uv run uvicorn text2sql.main:app --reload --port 8085
- 테스트: uv run pytest -q
- 린트: uv run ruff check . && uv run ruff format .
- 패키지 추가: uv add <pkg> (pip install 금지)
- 프런트: cd frontend && npm run dev
- 프런트 빌드: cd frontend && npm run build
- 운영 실행: uv run uvicorn text2sql.main:app --host 0.0.0.0 --port $PORT

## 구조 (src/text2sql)
- api, pipeline, semantic, validation, dialects, llm. 폴더 하나가 개념 하나
- 의존 방향: api → pipeline → (semantic, validation, dialects, llm)
- 교체가 필요한 것(llm, dialects, 프로젝트 데이터 저장소)만 해당 폴더 안에 인터페이스를 둔다
- 프로젝트별 데이터는 저장소 인터페이스를 통해서만 접근한다 (파이프라인에서 파일 직접 읽기 금지)
- 요청 값(datasource_id 등)으로 파일 경로를 만들지 않는다. 시작 시 읽은 레지스트리에서만 조회한다
- 프런트는 docs/design.md의 API 계약으로만 백엔드와 통신한다
- 엔드포인트는 APIRouter로 만들고 main.py는 포함만 한다. 자체 인증은 만들지 않는다
- 환경변수 접두사는 TEXT2SQL_. 경로는 설정에서 주입받고 현재 실행 위치에 의존하지 않는다
- 엔드포인트는 APIRouter로 만들고 main.py는 포함만 한다. main.py가 frontend/dist가 있으면 정적 파일로 제공한다
- 환경변수 접두사는 TEXT2SQL_. 경로는 설정에서 주입받고 실행 위치에 의존하지 않는다
- 서버는 파일을 쓰지 않는다 (배포 환경의 파일시스템이 초기화됨)
- 접속 키 인증 외의 자체 로그인은 만들지 않는다

## 규칙
- 구현 전에 docs/design.md를 먼저 읽고 읽은 문서를 알려줄 것. 설계와 다르면 구현하지 말고 물어볼 것
- 한 번에 요청한 단계만 진행하고 멈출 것. 다음 단계로 임의로 넘어가지 말 것
- 이번 단계는 SQL 생성까지. DB 접속과 SQL 실행 코드는 작성하지 않는다
- 생성하고 허용하는 SQL은 SELECT(DQL)뿐이다. CREATE VIEW를 포함한 모든 CREATE는 거부한다
- 숫자와 사실은 직접 확인한 것만 보고한다. 확인하지 않은 것은 "확인 못 함"이라고 쓴다
- 테스트에서 실제 LLM을 호출하지 않는다 (가짜 클라이언트 사용)
- .env와 비밀 정보는 읽거나 커밋하지 않는다
- 커밋은 사용자가 한다. 커밋 메시지만 제안한다
- _legacy/는 참고용 이전 코드다. 수정하지 않고 import하지 않는다