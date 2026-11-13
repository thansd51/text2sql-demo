# 설계: Text-to-SQL PoC

## 목적과 범위
- 상품시스템(InnoProduct 계열, EAV 구조) DB를 자연어로 조회하는 SQL을 **생성**한다. 핵심 산출물은 메타데이터다
- 이번 범위: SQL 생성까지. DB 접속과 SQL 실행은 없다 (실행은 고객사 시스템)
- 구성: 독립 Python 서버(FastAPI) + 별도 React 프런트(frontend/, Vite, JavaScript). 화면은 질문 화면 하나
- 서버 1대가 여러 프로젝트(datasource)를 처리한다

## 확정 사항
- LLM이 프로젝트의 **DB 종류와 버전 문법으로 SQL을 직접 작성**한다 (변환 없음). 서버는 방언 규칙 문구 제공, 검증, 행 제한 강제, 매크로 치환을 한다
- **생성하고 허용하는 SQL은 SELECT(DQL)뿐이다.** CREATE VIEW를 포함해 모든 CREATE는 거부한다. 뷰 생성문 변환은 후속 범위
- 컬럼 정의는 제품 공통(profile), 프로젝트 고유 값은 semantic에 둔다
- 대상 테이블: OBJ_MAIN, OBJ_INV
- 사용자에게 보이는 모든 문자열(오류 메시지, 로그)은 한국어. 오류 코드 상수는 영어
- 후속(이번 범위 밖): RAG, Importer, 웹 등록 화면(데이터소스 관리), 메타데이터 조회 화면, 질문 이력, 뷰 생성문 복사, MySQL/HANA, 인증 고도화, 배포

## 파일 구조
```
profiles/innoproduct.yml          제품 공통 정의 (YAML, 개발자가 관리)
datasources/<id>.json             프로젝트 등록 정보 (JSON, 후속에 웹 등록으로 대체)
semantic/<id>.json                프로젝트 값 (JSON, 후속에 웹 등록으로 대체, 파일은 선택)
```
- 파일명과 내부 id는 같아야 한다. 다르면 시작 실패. id 형식은 [a-z0-9_-]+
- semantic/<id>.json은 없어도 된다(빈 값). 대응하는 datasources/<id>.json이 없으면 오류
- 프로젝트별 데이터는 저장소 인터페이스(semantic/repository)로만 읽는다. 현재 구현은 파일(FileRepository), 후속에 DB 구현으로 교체
- 요청의 datasource_id로 파일 경로를 만들지 않는다. 시작 시 읽어 둔 레지스트리에서만 조회한다

## 필드 규칙
- datasources/<id>.json 필수: id, name, db_type(oracle|postgresql), db_version. 선택: profiles(기본 ["innoproduct"])
- profiles/<제품>.yml: product, views[name, description, definition, columns[name, type, description, synonyms]], relationships, glossary, examples
- semantic/<id>.json (모두 선택): type_catalog[{type_id, name}], glossary, examples, relationships
- definition은 모든 DB에서 통하는 기본 SQL과 매크로만 쓴다. 테이블 별칭에 AS를 쓰지 않는다(Oracle). 매크로: {{valid_now('별칭')}}
- examples는 기본 문법으로 쓰고 행 제한과 날짜 함수를 쓰지 않는다. 유형코드가 필요한 예시만 semantic에 둔다
- 컬럼 이름은 영문 snake_case, 한글은 description과 synonyms에 둔다
- type_id 같은 숫자형 코드는 문자열로 쓴다 ("100", "19c")
- 한 프로젝트에 제품이 여러 개면 profiles에 나열해 병합한다. 뷰 이름이 겹치면 시작 오류. 데이터소스는 DB 하나를 뜻한다

## 시작 시 동작
1. 파일 읽기 → Pydantic 검사 (오류는 파일명과 위치를 포함해 시작 실패, 메시지는 한국어)
2. 정의 SQL을 sqlglot으로 분석해 사용하는 물리 테이블 목록 추출 (최종 검증의 허용 목록)
3. 레지스트리에 저장. metadata_version = 파일 내용 해시

## 요청 처리
요청 { question, datasource_id } →
1 레지스트리에서 조회 (없으면 400)
2 프롬프트: 뷰, 컬럼, 동의어, 유형 카탈로그, 용어집, 예시, **db_type과 db_version에 맞는 방언 규칙 문구** (definition은 숨김)
3 LLM이 해당 DB 문법으로 SQL 작성
4 1차 검증: 허용 뷰와 컬럼만. 실패하면 오류를 넣어 재시도(최대 N회)
5 뷰 정의를 CTE로 삽입, 매크로 치환
6 행 제한 강제
7 최종 검증: 허용 물리 테이블만
8 응답: status, sql, references, metadata_version

## API 계약
- POST /api/v1/text-to-sql: 요청 { question, datasource_id } → 응답 { request_id, status, sql, references, metadata_version }
- GET /api/v1/datasources → [{ id, name, db_type, db_version }]
- GET /health
- 오류 응답: { code: 영어 상수, message: 한국어 }. 미등록 datasource_id는 400, LLM 사용 불가는 503

## SQL 검증 규칙
- 허용 목록 방식, 파싱은 대상 DB 문법(sqlglot read=db_type). 판단 불명은 거부
- 허용: SELECT(CTE, UNION 포함)만
- 금지: 모든 CREATE(CREATE VIEW, CREATE OR REPLACE 포함), DML과 기타 DDL, 다중 문장, SELECT INTO, 잠금 절, 위험 함수

## 대상 테이블 메모
- OBJ_MAIN: SID(PK)와 BIZCODE는 중복 없음. OBJ_NAME은 같은 TYPEID 안에서도 중복 가능(이름 조회는 여러 행을 반환할 수 있고, 식별은 biz_code/id로 한다). 개수는 COUNT(*)로 센다
- 사용 컬럼: BIZCODE(VARCHAR2 32), OBJ_NAME(NVARCHAR2 300), TYPEID(NUMBER), VF_DT와 VT_DT(VARCHAR2 19, YYYYMMDD, 종료일 기본 99991231), END_DT(삭제일자)
- 제외 조건: TYPEID = 0은 표준항목 허용값이라 제외. 삭제된 행(END_DT 값 있음)은 제외
- OBJ_INV: (컬럼 확정 대기)

## v_object 합의안 (profiles/innoproduct.yml의 뷰)
```yaml
views:
  - name: v_object
    description: 현재 유효한 오브젝트(상품 등) 목록
    definition: |
      SELECT m.SID AS id, m.BIZCODE AS biz_code, m.TYPEID AS type_id,
             m.OBJ_NAME AS obj_name, m.VF_DT AS valid_from, m.VT_DT AS valid_to
      FROM OBJ_MAIN m
      WHERE m.TYPEID <> 0
        AND (m.END_DT IS NULL OR m.END_DT = '')
        AND {{valid_now('m')}}
    columns:
      - {name: id, type: number, description: 오브젝트 내부 고유 ID (PK, 중복 없음)}
      - {name: biz_code, type: string, description: 오브젝트 코드 (중복 없음, 오브젝트 식별에 사용), synonyms: [상품코드, 코드]}
      - {name: type_id, type: number, description: 오브젝트 유형 코드}
      - {name: obj_name, type: string, description: 오브젝트명 (같은 유형 안에서도 중복될 수 있음, 식별자로 쓰지 말 것), synonyms: [상품명, 이름]}
      - {name: valid_from, type: string, description: 유효 시작일 (YYYYMMDD)}
      - {name: valid_to, type: string, description: 유효 종료일 (YYYYMMDD, 99991231은 종료일 없음)}
glossary:
  - 오브젝트명은 중복될 수 있다. 이름으로 조회할 때는 biz_code를 함께 조회하고, 개수는 COUNT(*)로 센다 (이름 기준 DISTINCT 금지)
```
- v_structure(OBJ_INV)는 컬럼 확정 후 추가한다

## 확인 필요
- END_DT가 삭제되지 않은 행에서 NULL인지 빈 문자열인지, VF_DT와 VT_DT의 실제 형식, 종료일 포함 여부
- 승인 상태(OK_FLAGS) 필터 필요 여부, Oracle 버전, OBJ_INV 컬럼과 INV_TYPE 값 의미
- 같은 OBJ_NAME이 다른 TYPEID에도 존재하는지