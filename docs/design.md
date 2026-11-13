# 설계: Text-to-SQL PoC

## 목적과 범위
- 상품시스템(InnoProduct 계열, EAV 구조) DB를 자연어로 조회하는 SQL을 **생성**한다. 핵심 산출물은 메타데이터다
- 이번 범위: SQL 생성까지. DB 접속과 SQL 실행은 없다 (실행은 고객사 시스템)
- 구성: 독립 Python 서버(FastAPI) + 별도 React 프런트(frontend/, Vite, JavaScript). 화면은 질문 화면 하나
- 서버 1대가 여러 프로젝트(datasource)를 처리한다
- 구성: 단일 서비스. FastAPI가 API와 React 빌드 결과(frontend/dist)를 함께 제공한다. 프런트는 frontend/ (Vite, JavaScript)에 있고 화면은 질문 화면 하나다
- 배포: Railway 단일 서비스. 기존 프로젝트에 붙일 수 있는 패키지 형태로 만든다

## 확정 사항
- LLM이 프로젝트의 **DB 종류와 버전 문법으로, 실제 테이블과 컬럼 이름으로 SQL을 직접 작성**한다 (변환 없음, 용도별 뷰 없음). 서버는 방언 규칙 문구 제공, 검증, 행 제한 강제를 한다
- **생성하고 허용하는 SQL은 SELECT(DQL)뿐이다.** CREATE VIEW를 포함해 모든 CREATE는 거부한다. 뷰 생성문 변환은 후속 범위
- 테이블과 컬럼 정의는 제품 공통(profile), 제품 공통 질문-SQL 예시는 examples, 프로젝트마다 다른 테이블 데이터(코드와 이름이 함께 있는 행 등)는 semantic에 둔다
- 대상 테이블: OBJ_MAIN, OBJ_INV, OBJINV_TYPE (OBJINV_TYPE은 상품구조·서비스뷰·관계규칙을 TYPE_GBN으로 구분하는 데 쓴다). 테이블은 수십 개로 늘어날 예정이라 profile에 테이블 파일 하나씩 더한다
- 사용자에게 보이는 모든 문자열(오류 메시지, 로그)은 한국어. 오류 코드 상수는 영어
- 후속(이번 범위 밖): RAG, Importer, 웹 등록 화면(데이터소스 관리), 메타데이터 조회 화면, 질문 이력, 뷰 생성문 복사, MySQL/HANA, 인증 고도화
- 통합: 기존 프로젝트에 소스를 붙여 쓸 수 있는 패키지 형태로 만든다. 엔드포인트는 APIRouter로 노출하고, 자체 인증은 만들지 않는다(호스트의 구글 로그인에 위임). 단독 공개 시에는 별도 인증이 필요하다
- 환경변수 접두사 TEXT2SQL_, 경로는 설정값으로 주입, 모듈 import 시 부작용 금지, 레지스트리는 앱 시작 시 생성
- 통합: 엔드포인트는 APIRouter로 노출하고 main.py는 포함만 한다. 환경변수 접두사 TEXT2SQL_, 경로는 설정값으로 주입, 모듈 import 시 부작용 금지, 레지스트리는 앱 시작 시 생성
- 배포: Railway가 주는 PORT 환경변수로 0.0.0.0에 바인딩한다. 헬스체크는 /health. 프런트와 API는 같은 출처이므로 프런트의 API 주소는 상대 경로(/api/v1)다. 로컬 개발은 Vite 프록시로 8085에 연결한다
- 데이터 파일(datasources, semantic, profiles)은 이미지에 포함된 읽기 전용으로 쓴다. Railway 파일시스템은 재배포 시 초기화되므로 서버가 파일을 쓰지 않는다 (웹 등록은 후속에 DB로)
- 비밀 값(LLM 키, 접속 키)은 환경변수로만 준다. 저장소에 올리지 않는다
- LLM_BASE_URL(TEXT2SQL_LLM_BASE_URL)은 배포 서버에서 접근 가능한 주소여야 한다
- LLM 종류는 TEXT2SQL_LLM_PROVIDER로 고른다. openai(기본)는 OpenAI 호환 API, anthropic은 Claude 공식 SDK(Messages API)를 쓴다. 둘 다 llm 폴더의 같은 인터페이스(LLMClient)를 구현하므로 파이프라인은 어느 쪽인지 모른다. Claude Opus 5.5는 temperature를 받지 않고 thinking을 끌 수 없어서 effort(기본 low)로 속도를 조절하고, 생각에 쓰는 토큰이 max_tokens에 들어가므로 4096 이상으로 둔다
- 인증: 기존 프로젝트의 구글 로그인에 위임하는 것이 목표다. 단독 공개 배포 동안에는 TEXT2SQL_ACCESS_KEY 환경변수를 필수로 하고(없으면 시작 실패, 로컬 개발은 TEXT2SQL_AUTH_DISABLED=true), 요청 헤더로 받는다. 프런트는 접속 키를 입력받아 헤더로 보낸다
- 고객사 실제 메타데이터를 저장소와 배포에 포함하기 전에 반출 허용을 확인한다. 확인 전에는 샘플·익명화 값만 사용한다

## 파일 구조
```
profiles/innoproduct/product.yml  제품 공통: 조인 키(relationships), 여러 테이블에 걸친 용어집 (YAML, 개발자가 관리)
profiles/innoproduct/tables/OBJ_MAIN.yml  테이블 하나의 정의: 컬럼, 동의어, 그 테이블의 사용 규칙 (파일 하나가 테이블 하나)
examples/innoproduct.yml          제품 공통 질문-SQL 예시 (YAML, 이 제품을 쓰는 모든 프로젝트가 함께 쓴다, 파일은 선택)
datasources/<id>.json             프로젝트 등록 정보 (JSON, 후속에 웹 등록으로 대체)
semantic/<id>.json                프로젝트마다 다른 테이블 데이터: 테이블 -> 행 목록 (JSON, 후속에 웹 등록으로 대체, 파일은 선택)
```
- 파일명과 내부 id는 같아야 한다 (제품은 디렉터리명과 product.yml의 product, 테이블은 파일명과 name). 대소문자도 구분한다. 다르면 시작 실패. id 형식은 [a-z0-9_-]+
- semantic/<id>.json과 examples/<제품>.yml은 없어도 된다(빈 값). 대응하는 datasources/<id>.json이 없는 semantic, 대응하는 profiles/<제품>/ 디렉터리가 없는 examples는 오류
- 프로젝트별 데이터는 저장소 인터페이스(semantic/repository)로만 읽는다. 현재 구현은 파일(FileRepository), 후속에 DB 구현으로 교체
- 요청의 datasource_id로 파일 경로를 만들지 않는다. 시작 시 읽어 둔 레지스트리에서만 조회한다

## 필드 규칙
- datasources/<id>.json 필수: id, name, db_type(oracle|postgresql), db_version. 선택: profiles(기본 ["innoproduct"])
- profiles/<제품>/product.yml: product, relationships[{from, to, note}], glossary. from과 to는 `테이블.컬럼`이다 (OBJ_INV.SID)
- profiles/<제품>/tables/<테이블>.yml: name, description, group, name_column, key_columns, rules, columns[name, type, description, synonyms]. group(업무 영역), name_column(행의 이름이 든 컬럼), key_columns(그 행을 조회할 때 조건으로 쓰는 컬럼들), rules는 선택이다. 한 제품에 테이블 파일이 1개 이상 있어야 하고, 테이블은 파일 이름순으로 읽는다
- examples/<제품>.yml: product, examples[question, sql]
- semantic/<id>.json (파일 자체가 선택): 최상위가 바로 {테이블: [행...]}이고, 행은 {컬럼: 값}이다. 행에는 그 테이블 정의(profile)의 컬럼을 모두 적고, 값이 없는 컬럼은 null이 아니라 ""(빈 값)로 둔다. 감싸는 키(table_data 등)는 없다
- 테이블과 컬럼 이름은 **실제 DB의 이름**이다 (OBJ_MAIN, TYPEID, R10_1). 모델도 이 이름으로 SQL을 쓴다. 한글은 description과 synonyms에 둔다
- 테이블은 한 번만 정의한다. 같은 테이블의 다른 용도(상품 객체와 항목 허용값 등)는 테이블을 나누지 않고 glossary와 examples로 알려 준다. 용도별 뷰는 만들지 않는다
- 테이블을 추가하려면 tables/<테이블>.yml을 하나 더하고, 조인 키는 product.yml의 relationships에 적는다. 그 테이블에만 해당하는 사용 규칙은 같은 파일의 rules에, 여러 테이블에 걸친 규칙만 product.yml의 glossary에 적는다
- rules는 프롬프트에서 해당 테이블 바로 아래에 `[규칙]`으로 나온다. 그 테이블이 쓰일 때 조건을 빠뜨리지 않게 하려는 것이다
- examples는 기본 문법으로 쓰고 행 제한과 날짜 함수를 쓰지 않는다. 모든 프로젝트가 함께 쓰므로 코드(TYPEID = 101)는 써도 되지만 코드의 이름(장기상품 등)은 쓰지 않는다
- semantic은 **실제 테이블의 행**을 적는다: `{"OBJ_MAIN": [{"TYPEID": "101", "OBJ_NAME": "장기상품", "R10_1": ""}, ...], "OBJINV_TYPE": [{"INV_TYPE": "11", "TYPE_GBN": "1", "TYPE_NAME": "기본 상품구조"}]}`. 이름(장기상품)은 TYPEID 컬럼의 속성이 아니라 같은 행의 OBJ_NAME 값이므로 행 단위로 적는다. 같은 코드도 프로젝트마다 이름이 다를 수 있고(101이 어느 프로젝트에서는 장기상품, 다른 프로젝트에서는 정기보험), 일부 코드는 특정 프로젝트에만 있을 수 있다
- 같은 테이블의 모든 행은 같은 컬럼을 갖는다 (행마다 컬럼이 다르면 시작 오류). 값은 문자열이어야 하고 null은 오류다. 같은 행을 두 번 적거나, 한 행에 대소문자만 다른 같은 컬럼을 두 번 적거나, 대소문자만 다른 테이블 키를 두 번 적으면 오류다. JSON 파서는 같은 키가 두 번 나오면 뒤의 값만 남기므로, 읽을 때 같은 키가 두 번 적힌 것을 직접 찾아 거부한다
- semantic의 테이블과 컬럼은 profile에 있어야 한다 (대소문자 무시). 없으면 시작 오류. relationships의 from과 to도 profile에 있는 테이블.컬럼이어야 한다
- 테이블이 달라도 컬럼 이름이 같으면 FK로 이어진다는 점은 profile의 relationships로 적는다. 프로젝트마다 다른 relationships나 glossary는 지원하지 않는다 (semantic은 테이블 데이터만 가진다)
- 코드 값(code)과 db_version 같은 숫자형 코드는 문자열로 쓴다 ("101", "19c")
- YAML 한 줄(플로) 스타일 `{name: x, description: a, b}`는 설명에 쉼표가 있으면 값이 잘린다. 컬럼은 블록 스타일로 쓴다. 따옴표 없는 문자열에 ` : `를 넣으면 "키: 값"으로 읽힌다
- 한 프로젝트에 제품이 여러 개면 profiles에 나열해 병합한다. 테이블 이름이 겹치면 시작 오류. 데이터소스는 DB 하나를 뜻한다
- 예전 형식(profiles/<제품>.yml 한 파일, semantic의 code_catalog·glossary·relationships)은 더 이상 읽지 않는다

## 시작 시 동작
1. 파일 읽기 → Pydantic 검사 (오류는 파일명과 위치를 포함해 시작 실패, 메시지는 한국어)
2. 데이터소스의 profile들을 병합하고 제품 공통 예시를 모은다 (테이블 이름 중복은 오류)
3. semantic의 테이블과 컬럼, relationships의 from, to가 profile에 있는지 확인
4. 공통 예시가 모든 프로젝트의 테이블과 DB 방언에서 통과하는지 확인 (하나라도 틀리면 시작 실패. 프로젝트마다 DB가 달라서 프로젝트별로 본다)
5. 데이터소스의 db_version을 방언 어댑터가 읽을 수 있는지 확인
6. 레지스트리에 저장. metadata_version = 파일 내용 해시

## 요청 처리
요청 { question, datasource_id } →
1 레지스트리에서 조회 (없으면 400)
2 프롬프트: 테이블, 컬럼, 동의어, 테이블 사이의 관계, 테이블 데이터(행), 용어집, 예시, **db_type과 db_version에 맞는 방언 규칙 문구**. 전체가 모델의 컨텍스트 예산을 넘으면 질문과 관련 있는 테이블만 넣는다 ("프롬프트 크기와 테이블 선택")
3 LLM이 해당 DB 문법으로, 실제 테이블과 컬럼 이름으로 SQL 작성
4 1차 검증: 허용 테이블과 컬럼만. 실패하면 오류를 넣어 재시도(최대 N회)
5 행 제한 강제
6 최종 검증: 허용 테이블만
7 응답: status, sql, references, metadata_version

## API 계약
- POST /api/v1/text-to-sql: 요청 { question, datasource_id } → 응답 { request_id, status, sql, references, metadata_version }
- GET /api/v1/datasources → [{ id, name, db_type, db_version }]
- GET /health
- 오류 응답: { code: 영어 상수, message: 한국어 }. 미등록 datasource_id는 400, LLM 사용 불가는 503
- 접속 키가 필요한 요청 헤더: X-Access-Key (GET /health 제외)

## SQL 검증 규칙
- 허용 목록 방식, 파싱은 대상 DB 문법(sqlglot read=db_type). 판단 불명은 거부
- 허용: SELECT(CTE, UNION 포함)만
- 금지: 모든 CREATE(CREATE VIEW, CREATE OR REPLACE 포함), DML과 기타 DDL, 다중 문장, SELECT INTO, 잠금 절, 위험 함수
- 허용 함수는 공통 목록에 어댑터가 알려 주는 현재 날짜 함수(Oracle SYSDATE, PostgreSQL CURRENT_DATE)를 더한 것이다. ADD_MONTHS, TRUNC 같은 날짜 계산 함수는 허용하지 않는다
- 허용된 테이블 이름과 같은 이름의 CTE는 거부한다 (테이블을 가리지 않게)

## 대상 테이블 메모
- OBJ_MAIN: SID(PK)와 BIZCODE는 중복 없음. OBJ_NAME은 같은 TYPEID 안에서도 중복 가능(이름 조회는 여러 행을 반환할 수 있고, 식별은 BIZCODE/SID로 한다). 개수는 COUNT(*)로 센다
- 사용 컬럼 형식: BIZCODE(VARCHAR2 32), OBJ_NAME(NVARCHAR2 300), TYPEID(NUMBER), VF_DT와 VT_DT(VARCHAR2 19, YYYYMMDD, 종료일 기본 99991231)
- OBJ_MAIN은 상품 객체(TYPEID <> 0)와 항목의 참조값(허용값)을 함께 저장한다. 허용값은 R10_1(항목코드)로 조회한다. R10_1은 상품 객체를 조회할 때는 거의 쓰지 않는다
- OBJ_MAIN 컬럼: SID(오브젝트 ID, 내부 Key), BIZCODE(업무 구분 Key), VERCODE(상품 버전코드, 사용 안 함이라 profile에서 뺌), TYPEID(세부유형 코드, 0은 허용값), R10_1(항목코드), OBJ_NAME(명칭), VF_DT와 VT_DT(시작일과 종료일)
- OBJ_INV: 상품 구조(상위 SID, 하위 SUBSID)와 관계규칙을 저장한다. 컬럼: INV_TYPE(관계구분 ID, OBJINV_TYPE.INV_TYPE), SID(상위 오브젝트, OBJ_MAIN.SID), SUBSID(하위 오브젝트, OBJ_MAIN.SID), SEQ(순번), VF_DT와 VT_DT(관계구조 버전 시작일과 종료일), PROP_SID(관계 오브젝트, OBJ_MAIN.SID), SET_SEQ(관계규칙 SET 그룹, 0부터. 같은 규칙 세트는 같은 값), BASIS(관계기준 여부 1/0), BASIS_YN(관계기준 여부 Y/N), REL_DESC(보험관계규칙 설명), RULEID(보험관계규칙에 등록된 룰)
- OBJINV_TYPE: INV_TYPE, TYPE_GBN(1 = 기본 상품구조, 6 = 서비스뷰, 4 = 관계규칙), TYPE_NAME, END_DT(종료일, 기본 99991231). 예제 쿼리에 나온 컬럼만 쓴다
- OBJ_INV와 OBJINV_TYPE은 INV_TYPE으로 조인하고 TYPE_GBN으로 구조(1, 6)와 관계규칙(4)을 가른다. OBJINV_TYPE은 END_DT = '99991231'인 것만 쓴다
- VF_DT와 VT_DT는 시작일과 종료일이며 모든 테이블 공통이다. 기준일자와 비교할 때 쓴다

## profile 구성 (profiles/innoproduct/, examples/innoproduct.yml)
profile 디렉터리와 공통 예시 파일이 기준이다. 아래는 구성 요약이다.

| 테이블 | 용도 | 컬럼 |
|---|---|---|
| OBJ_MAIN | 상품 객체와 항목 허용값 | SID, BIZCODE, TYPEID, R10_1, OBJ_NAME, VF_DT, VT_DT |
| OBJ_INV | 상품 구조와 관계규칙 | INV_TYPE, SID, SUBSID, SEQ, VF_DT, VT_DT, PROP_SID, SET_SEQ, BASIS, BASIS_YN, REL_DESC, RULEID |
| OBJINV_TYPE | 관계 종류 | INV_TYPE, TYPE_GBN, TYPE_NAME, END_DT |

- relationships: 조인 키(OBJ_INV.SID = OBJ_MAIN.SID 등)
- 테이블별 rules(해당 테이블 파일에 둔다): OBJ_MAIN은 오브젝트명이 중복될 수 있고 상품 객체는 TYPEID <> 0, 허용값은 R10_1로 조회 / OBJ_INV는 상품 구조를 OBJINV_TYPE과 조인해 TYPE_GBN으로 구분하고, 관계규칙은 TYPE_GBN = 4이며 같은 세트는 SET_SEQ가 같고, OBJ_MAIN을 상위와 하위로 두 번 조인할 때는 다른 별칭을 쓴다 / OBJINV_TYPE은 END_DT = '99991231'인 것만 쓴다
- glossary(여러 테이블에 걸친 규칙): 기준일자에 유효한 행은 VF_DT <= 기준일자 AND VT_DT >= 기준일자이고 '현재', '지금', '유효한'이 있으면 기준일자는 오늘
- 테이블 데이터는 프롬프트에 테이블별로 한 줄에 한 행씩 나온다. 테이블에 name_column(행의 이름이 든 컬럼, 예: OBJ_NAME)과 key_columns(예: TYPEID, R10_1)가 있으면 행을 `이름: 그 행을 가리키는 조건`(`장기상품: TYPEID = 101`, `보장기간: TYPEID = 0 AND R10_1 = '#S00000031'`)으로 바꿔 보여 준다. 조건에는 key_columns 중 값이 있는 컬럼만 쓰고(SID나 날짜 컬럼은 행에 있어도 쓰지 않는다), 숫자 컬럼은 따옴표 없이, 문자열 컬럼은 따옴표로 쓴다. name_column이나 key_columns가 없거나 이름·조건에 쓸 값이 비어 있는 행은 `TYPEID=101, OBJ_NAME=장기상품, R10_1=''`처럼 그대로 보여 준다(빈 값은 ''). "질문에 위 이름이 나오면 이름을 문자열로 비교하지 말고 같은 줄의 조건을 그대로 쓴다"는 안내가 바로 아래에 붙고, 데이터가 없는 프로젝트에는 이 절과 안내가 나오지 않는다. 행만 그대로 보여 주었을 때는 4B 로컬 모델이 이름 문자열로 비교해서 10개 질문 중 4개만 맞았고(규칙 문장을 더해도 4개), 이름: 조건 형태로 바꾸자 10개가 모두 맞았다 (같은 시험 질문, 한 번씩 실행)
- examples: 알려 준 쿼리 예제(유형별 조회, 허용값 조회, 상품 구조, 관계규칙)와 기준일자 비교, 이름 검색, 유형별 개수
- **서버가 대신 걸어 주는 조건은 없다.** 행 제한만 서버가 강제한다. TYPEID <> 0, 유효 기간, TYPE_GBN 같은 조건은 모델이 쓰므로 빠뜨릴 수 있다. 테이블별 rules, 용어집, 공통 예시로 줄이며, 효과는 실제 질문으로 확인한다

## 확인 필요
- OBJ_MAIN 컬럼 문서에 END_DT(삭제일자)가 없다. 실제로 있으면 profile에 컬럼과 삭제 제외 규칙을 추가한다 (지금 profile에는 없다)
- 항목 허용값 행이 정말 TYPEID = 0인지 (용어집은 TYPEID <> 0으로 상품 객체를 구분한다)
- VF_DT와 VT_DT의 실제 형식, 종료일 포함 여부 (기준일자 규칙은 종료일 포함으로 가정)
- 테이블 선택이 필요한 테이블을 놓치는 빈도와 글자 수 어림(1토큰당 1.8자)의 정확도. 실제 모델과 수십 개 테이블로 확인해야 한다
- 모델이 조건(TYPEID <> 0, 유효 기간, TYPE_GBN 등)을 빠뜨리는 빈도. 많으면 "이 테이블을 쓰면 이 조건이 필수" 같은 서버 검사를 추가한다
- BASIS와 BASIS_YN 중 무엇을 쓰는지, PROP_SID를 쓸 질문이 있는지
- OBJINV_TYPE의 나머지 컬럼과 END_DT = '99991231'의 정확한 의미 (예제 쿼리에 나온 컬럼만 확인함)
- 승인 상태(OK_FLAGS) 필터 필요 여부, Oracle 버전, INV_TYPE 값 의미 (프로젝트별 OBJINV_TYPE 행)
- 같은 OBJ_NAME이 다른 TYPEID에도 존재하는지

## 응답과 상태
- status는 OK 또는 REJECTED. REJECTED는 HTTP 200이며 sql은 null, 사유는 message(한국어)에 담는다
- references: [{table, columns: [...]}] 모델이 쓴 SQL에서 sqlglot으로 추출한다 (테이블 이름 순서, 컬럼은 profile에 선언한 순서)
- request_id: 서버가 uuid4 발급. X-Request-Id 헤더가 안전한 형식이면 그 값을 사용한다
- HTTP 상태: 400 잘못된 요청·미등록 datasource_id, 401 접속 키 오류, 503 LLM 사용 불가
- 설정값: max_rows, max_repair_attempts, max_question_length, llm_context_tokens, llm_chars_per_token

## 프롬프트 크기와 테이블 선택
테이블이 수십 개로 늘면 스키마 전체가 컨텍스트에 들어가지 않는다. 컨텍스트가 작은 로컬 모델(Ollama 등)은 넘치면 앞부분(규칙)부터 잘릴 수 있어서, 서버가 예산을 계산해 넘기지 않게 한다.
- 예산 = TEXT2SQL_LLM_CONTEXT_TOKENS - TEXT2SQL_LLM_MAX_TOKENS(답변) - 800(재시도 때 붙는 이전 답변과 오류). 토큰 수는 글자 수 / TEXT2SQL_LLM_CHARS_PER_TOKEN(기본 1.8)으로 넉넉하게 어림한다. 기본 1.8은 로컬 모델 토크나이저로 잰 값(1글자당 약 0.54토큰)보다 안전한 쪽이다. 모델이 다르면 값을 바꾼다
- 전체가 예산에 들어가면 줄이지 않는다 (컨텍스트가 큰 클라우드 모델). 환경마다 모드를 따로 두지 않고 설정값(컨텍스트 크기) 하나로 갈린다
- 넘으면 LLM을 쓰지 않고 서버가 점수로 테이블을 고른다. 질문에 테이블 이름, 컬럼 이름(3글자 이상), 동의어, 테이블 데이터의 값(장기상품 등. 숫자만으로 된 값은 뺀다), 업무 영역(group), 설명의 단어가 나오면 점수를 준다. 점수가 높은 순으로 담고, 고른 테이블과 조인 키(relationships)로 이어진 테이블을 더 담는다. 같은 입력이면 항상 같은 결과다
- 테이블(스키마)은 예산에서 규칙, 용어집, 질문을 뺀 나머지의 70%까지 쓰고(첫 테이블은 예시 몫까지 쓸 수 있다), 나머지는 예시에 남긴다. 줄인 스키마에 맞춰 관계, 테이블 데이터, 예시도 걸러 낸다. 예시는 쓰는 테이블이 모두 고른 테이블 안에 있을 때만 남긴다
- 단서가 하나도 없으면 파일 순서대로 예산이 찰 때까지 담는다
- 검증은 줄이기 전 전체 메타데이터 기준이다. 프롬프트에서 뺀 테이블이라도 실제로 있는 테이블이면 허용한다
- 테이블 하나도 담지 못하는 설정이면(규칙과 용어집만으로 예산을 넘거나, 테이블 하나가 예산을 넘음) 서버가 시작할 때 실패하고 TEXT2SQL_LLM_CONTEXT_TOKENS를 확인하라고 알린다. 질문 길이는 최대(max_question_length)로 계산한다
- 줄였을 때는 로그에 테이블 수, 예상 토큰, 고른 테이블 이름을 남긴다 (질문 내용은 남기지 않는다)
- 효과(선택이 필요한 테이블을 놓치는 빈도, 선택이 SQL 품질에 미치는 영향)와 글자 수 어림의 정확도는 실제 모델과 실제 테이블 수로 확인하지 못했다

## 검증과 방언의 경계
- Oracle 전용 점검(빈 문자열 비교, 11g의 FETCH FIRST 등)은 LLM이 쓴 SQL(1차)에만 적용한다. 최종 검증은 구조·허용 테이블·금지 노드만 본다
- 행 제한: Oracle은 버전과 무관하게 ROWNUM으로 감싼다. PostgreSQL은 LIMIT. db_version은 프롬프트의 방언 규칙 문구와 방언 점검에 쓴다
- 현재 날짜 함수는 어댑터가 DB마다 알려 주고 검증이 허용한다 (Oracle SYSDATE, PostgreSQL CURRENT_DATE). 쓰는 방법(TO_CHAR(..., 'YYYYMMDD'))은 방언 규칙 문구가 알려 준다
- validation과 dialects는 서로 import하지 않는다. pipeline이 연결한다

