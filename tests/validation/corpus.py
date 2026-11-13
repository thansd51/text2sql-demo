"""검증 정책용 공격 SQL / 정상 SQL 코퍼스.

테이블, 뷰, 컬럼 이름은 정책과 무관한 시험용 값이다. 특정 제품 스키마에 의존하지 않는다.
"""

# (방언, sql). 모든 항목은 1차와 최종 검증 양쪽에서 거부돼야 한다.
ATTACKS: list[tuple[str, str]] = [
    # DDL / DML / 기타 문장
    ("postgres", "DROP TABLE t"),
    ("oracle", "DROP TABLE t"),
    ("mysql", "DROP TABLE t"),
    ("postgres", "DELETE FROM t"),
    ("oracle", "DELETE FROM t WHERE 1 = 1"),
    ("mysql", "UPDATE t SET a = 1"),
    ("postgres", "INSERT INTO t VALUES (1)"),
    ("oracle", "INSERT INTO t SELECT * FROM t"),
    (
        "oracle",
        "MERGE INTO t USING s ON (t.a = s.a) WHEN MATCHED THEN UPDATE SET t.b = 1",
    ),
    ("postgres", "TRUNCATE TABLE t"),
    ("mysql", "TRUNCATE t"),
    ("oracle", "ALTER TABLE t ADD c INT"),
    ("postgres", "ALTER TABLE t DROP COLUMN c"),
    ("postgres", "GRANT ALL ON t TO u"),
    ("oracle", "GRANT SELECT ON t TO u"),
    ("postgres", "COPY t TO '/tmp/x'"),
    ("postgres", "SET search_path = x"),
    ("mysql", "SET @a = 1"),
    ("postgres", "COMMIT"),
    ("postgres", "ROLLBACK"),
    ("postgres", "CALL f()"),
    ("postgres", "DO $$ BEGIN PERFORM 1; END $$"),
    ("postgres", "EXPLAIN SELECT 1 FROM t"),
    ("oracle", "BEGIN NULL; END;"),
    ("oracle", "WITH FUNCTION f RETURN NUMBER IS BEGIN RETURN 1; END; SELECT f FROM t"),
    # 모든 CREATE (CREATE VIEW, CREATE OR REPLACE 포함)
    ("postgres", "CREATE VIEW v AS SELECT a FROM t"),
    ("oracle", "CREATE VIEW v AS SELECT a FROM t"),
    ("mysql", "CREATE VIEW v AS SELECT a FROM t"),
    ("postgres", "CREATE VIEW s.v AS SELECT a FROM t"),
    ("postgres", "CREATE OR REPLACE VIEW s.v AS SELECT a FROM t"),
    ("oracle", "CREATE OR REPLACE VIEW s.v AS SELECT a FROM t"),
    ("mysql", "CREATE OR REPLACE VIEW v AS SELECT a FROM t"),
    ("postgres", "CREATE MATERIALIZED VIEW s.v AS SELECT a FROM t"),
    ("postgres", "CREATE TEMP VIEW v AS SELECT a FROM t"),
    ("oracle", "CREATE FORCE VIEW s.v AS SELECT a FROM t"),
    ("postgres", "CREATE RECURSIVE VIEW v (a) AS SELECT 1"),
    ("postgres", "CREATE VIEW IF NOT EXISTS s.v AS SELECT a FROM t"),
    ("postgres", "CREATE VIEW s.v AS SELECT a FROM t WITH CHECK OPTION"),
    ("postgres", "CREATE VIEW v AS WITH c AS (SELECT a FROM t) SELECT a FROM c"),
    (
        "postgres",
        "CREATE VIEW s.v AS WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
    ),
    ("postgres", "CREATE VIEW s.v AS SELECT pg_sleep(1)"),
    ("postgres", "CREATE TABLE x (a INT)"),
    ("oracle", "CREATE TABLE x AS SELECT * FROM t"),
    ("postgres", "CREATE TABLE s.v AS SELECT a FROM t"),
    ("postgres", "CREATE INDEX i ON t (a)"),
    ("postgres", "CREATE SEQUENCE q"),
    ("postgres", "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql"),
    ("oracle", "CREATE USER u IDENTIFIED BY p"),
    # 여러 문장
    ("postgres", "SELECT 1 FROM t; DROP TABLE t"),
    ("postgres", "SELECT 1 FROM t; CREATE VIEW v AS SELECT 1 FROM t"),
    ("oracle", "SELECT 1 FROM t -- x\n; DROP TABLE t"),
    ("mysql", "SELECT 1 FROM t; DELETE FROM t"),
    # SELECT 루트 안에 숨은 DML
    ("postgres", "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"),
    ("postgres", "WITH u AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM u"),
    ("postgres", "WITH i AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM i"),
    # SELECT INTO / 잠금 절
    ("postgres", "SELECT * INTO x FROM t"),
    ("postgres", "SELECT 1 FROM t FOR UPDATE"),
    ("mysql", "SELECT 1 FROM t INTO OUTFILE '/tmp/x'"),
    ("mysql", "SELECT 1 FROM t LOCK IN SHARE MODE"),
    ("mysql", "SELECT 1 INTO @v FROM t"),
    # 위험 함수
    ("oracle", "SELECT UTL_HTTP.REQUEST('http://x') FROM t"),
    ("oracle", "SELECT SYS.DBMS_LOCK.SLEEP(1) FROM t"),
    ("oracle", "SELECT DBMS_RANDOM.VALUE FROM t"),
    ("oracle", "SELECT s.NEXTVAL FROM t"),
    ("oracle", "SELECT pkg.fn FROM t"),
    ("oracle", "SELECT UTL_HTTP.REQUEST('http://x') FROM dual"),
    ("postgres", "SELECT pg_sleep(10)"),
    ("postgres", "SELECT pg_read_file('/etc/passwd')"),
    ("postgres", "SELECT pg_terminate_backend(1)"),
    ("postgres", "SELECT nextval('s')"),
    ("postgres", "SELECT set_config('a', 'b', false)"),
    ("postgres", "SELECT lo_import('/etc/passwd')"),
    ("postgres", "SELECT * FROM dblink('x', 'select 1') AS t(a int)"),
    ("mysql", "SELECT SLEEP(10)"),
    ("mysql", "SELECT BENCHMARK(1000000, MD5('a'))"),
    ("mysql", "SELECT LOAD_FILE('/etc/passwd')"),
    # 허용 목록 밖의 테이블
    ("oracle", "SELECT * FROM t@remote_link"),
    ("postgres", "SELECT * FROM pg_catalog.pg_user"),
    ("oracle", "SELECT * FROM all_tables"),
    ("oracle", "SELECT * FROM t AS OF TIMESTAMP (SYSTIMESTAMP - 1)"),
    # 힌트
    ("oracle", "SELECT /*+ FULL(t) */ 1 FROM t"),
    # 질의 형태 규칙
    (
        "postgres",
        "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) SELECT n FROM r",
    ),
    ("postgres", "SELECT a FROM (SELECT a FROM t LIMIT 5) s"),
    ("postgres", "SELECT 1"),
    ("postgres", "SELECT a FROM t WHERE EXISTS (SELECT 1)"),
    # 구문 분석 불가
    ("postgres", "SELEC FROM"),
    ("postgres", ""),
]

# 방언 전용 점검(dialects가 제공)이 거부해야 하는 SQL은 dialects 단계의 테스트에서 다룬다.
# 여기서는 점검 함수를 주입하는 경로만 시험한다.

# 1차 검증을 통과해야 하는 SQL (시험용 뷰 v_object, v_item)
NORMAL_FIRST: list[str] = [
    "SELECT obj_name FROM v_object WHERE type_id = '100'",
    "SELECT type_id, COUNT(*) AS cnt FROM v_object GROUP BY type_id HAVING COUNT(*) > 1",
    "WITH c AS (SELECT obj_name FROM v_object) SELECT obj_name FROM c",
    "SELECT o.obj_name FROM v_object o WHERE EXISTS (SELECT 1 FROM v_item i WHERE i.object_id = o.id)",
    "SELECT o.obj_name, i.item_id FROM v_object o JOIN v_item i ON i.object_id = o.id",
    "SELECT obj_name FROM v_object UNION SELECT item_id FROM v_item",
    (
        "SELECT UPPER(TRIM(obj_name)), LOWER(obj_name), LENGTH(obj_name), "
        "obj_name || '-' || biz_code, CONCAT(obj_name, biz_code), "
        "SUBSTRING(obj_name, 1, 2) FROM v_object"
    ),
    "SELECT COALESCE(biz_code, 'N'), CASE WHEN type_id = '1' THEN 1 ELSE 0 END FROM v_object",
    (
        "SELECT obj_name FROM v_object WHERE type_id IN ('1', '2') AND obj_name LIKE '%x%' "
        "AND biz_code IS NOT NULL AND NOT (type_id BETWEEN '3' AND '4') OR biz_code = 'N'"
    ),
    "SELECT obj_name FROM v_object ORDER BY obj_name LIMIT 10",
    "SELECT CAST(type_id AS VARCHAR(20)), MIN(type_id), MAX(type_id), SUM(1), AVG(1) FROM v_object GROUP BY type_id",
    "SELECT obj_name, ROW_NUMBER() OVER (PARTITION BY type_id ORDER BY obj_name) FROM v_object",
]

# (방언, sql). 최종 검증(물리 테이블)을 통과해야 한다. 현재 날짜 함수는 서버가 삽입하는 것이다.
NORMAL_FINAL: list[tuple[str, str]] = [
    (
        "oracle",
        (
            "SELECT m.name FROM t m JOIN s d ON m.id = d.id "
            "WHERE d.vf <= TO_CHAR(SYSDATE, 'YYYYMMDD')"
        ),
    ),
    (
        "postgres",
        "SELECT m.name FROM t m WHERE m.vf <= TO_CHAR(CURRENT_DATE, 'YYYYMMDD')",
    ),
    (
        "oracle",
        "WITH v_object AS (SELECT id AS id FROM t) SELECT id FROM v_object",
    ),
]

# (방언, sql). 문자열 안의 ";"는 문장을 나누지 않는다.
SEMICOLON_IN_STRING: list[tuple[str, str]] = [
    ("oracle", "SELECT 'a;b' FROM t"),
    ("oracle", "SELECT q'[a;b]' FROM t"),
    ("postgres", "SELECT $$a;b$$ FROM t"),
]
