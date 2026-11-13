import { describe, expect, it } from "vitest";
import { dbLabel, formatSql } from "./format";

// 공백만 다르고 글자는 같은지 비교한다
const strip = (text) => text.replace(/\s+/g, "");

describe("dbLabel", () => {
  it("DB 종류를 읽기 좋은 이름으로 바꾼다", () => {
    expect(dbLabel("oracle", "19c")).toBe("Oracle 19c");
    expect(dbLabel("postgresql", "14")).toBe("PostgreSQL 14");
  });

  it("모르는 종류는 그대로 보여 준다", () => {
    expect(dbLabel("hana", "2.0")).toBe("hana 2.0");
  });
});

describe("formatSql", () => {
  it("최상위 절 앞에서 줄을 바꾼다", () => {
    const sql = "SELECT a, b FROM v_object WHERE a = 1 GROUP BY a HAVING COUNT(*) > 1 ORDER BY a";

    expect(formatSql(sql)).toBe(
      ["SELECT a, b", "FROM v_object", "WHERE a = 1", "GROUP BY a", "HAVING COUNT(*) > 1", "ORDER BY a"].join("\n"),
    );
  });

  it("UNION과 FETCH FIRST도 새 줄에서 시작한다", () => {
    const sql = "SELECT a FROM t UNION SELECT a FROM s ORDER BY a FETCH FIRST 5 ROWS ONLY";

    expect(formatSql(sql).split("\n")).toEqual([
      "SELECT a",
      "FROM t",
      "UNION",
      "SELECT a",
      "FROM s",
      "ORDER BY a",
      "FETCH FIRST 5 ROWS ONLY",
    ]);
  });

  it("JOIN 종류를 한 덩어리로 다룬다", () => {
    const lines = formatSql("SELECT 1 FROM a LEFT JOIN b ON a.id = b.id JOIN c ON c.id = a.id").split("\n");

    expect(lines).toEqual(["SELECT 1", "FROM a", "LEFT JOIN b ON a.id = b.id", "JOIN c ON c.id = a.id"]);
  });

  it("CTE 본문은 들여쓰기해서 나누고, 그 밖의 괄호 안(하위 질의)은 줄을 바꾸지 않는다", () => {
    const sql = "WITH c AS (SELECT a FROM t WHERE b = 1) SELECT a FROM c WHERE a IN (SELECT a FROM s)";

    expect(formatSql(sql).split("\n")).toEqual([
      "WITH c AS (",
      "  SELECT a",
      "  FROM t",
      "  WHERE b = 1",
      ")",
      "SELECT a",
      "FROM c",
      "WHERE a IN (SELECT a FROM s)",
    ]);
  });

  it("CTE가 여럿이어도 각각 나눈다", () => {
    const sql = "WITH a AS (SELECT 1 FROM t), b AS (SELECT 2 FROM s) SELECT * FROM a JOIN b ON a.x = b.x";

    expect(formatSql(sql).split("\n")).toEqual([
      "WITH a AS (",
      "  SELECT 1",
      "  FROM t",
      "), b AS (",
      "  SELECT 2",
      "  FROM s",
      ")",
      "SELECT *",
      "FROM a",
      "JOIN b ON a.x = b.x",
    ]);
  });

  it("행 제한으로 감싼 Oracle 질의의 하위 질의는 한 줄로 둔다", () => {
    const sql = "SELECT * FROM (SELECT a FROM t ORDER BY a) WHERE ROWNUM <= 5";

    expect(formatSql(sql).split("\n")).toEqual([
      "SELECT *",
      "FROM (SELECT a FROM t ORDER BY a)",
      "WHERE ROWNUM <= 5",
    ]);
  });

  it("AS 다음 괄호가 질의가 아니면(CAST 등) 그대로 둔다", () => {
    expect(formatSql("SELECT CAST(a AS VARCHAR(20)) FROM t")).toBe("SELECT CAST(a AS VARCHAR(20))\nFROM t");
  });

  it("CTE 본문 안의 문자열에 괄호가 있어도 짝을 잘못 찾지 않는다", () => {
    const sql = "WITH c AS (SELECT ')' AS p FROM t) SELECT p FROM c";

    expect(formatSql(sql).split("\n")).toEqual(["WITH c AS (", "  SELECT ')' AS p", "  FROM t", ")", "SELECT p", "FROM c"]);
  });

  it("문자열 안의 키워드는 건드리지 않는다", () => {
    const sql = "SELECT a FROM t WHERE name = 'SELECT FROM WHERE' AND note = 'it''s ORDER BY x'";

    expect(formatSql(sql)).toBe(
      "SELECT a\nFROM t\nWHERE name = 'SELECT FROM WHERE' AND note = 'it''s ORDER BY x'",
    );
  });

  it("따옴표 식별자 안의 키워드도 건드리지 않는다", () => {
    expect(formatSql('SELECT "FROM" FROM t')).toBe('SELECT "FROM"\nFROM t');
  });

  it("식별자의 일부인 키워드는 절로 보지 않는다", () => {
    const sql = "SELECT from_date, order_by, where_x FROM t";

    expect(formatSql(sql)).toBe("SELECT from_date, order_by, where_x\nFROM t");
  });

  it("소문자 키워드도 처리한다", () => {
    expect(formatSql("select a from t where b = 1")).toBe("select a\nfrom t\nwhere b = 1");
  });

  it("공백이 아닌 글자는 하나도 바꾸지 않는다", () => {
    const samples = [
      "WITH v_object AS (SELECT m.SID AS id, m.OBJ_NAME AS obj_name FROM OBJ_MAIN m WHERE m.TYPEID <> 0 AND (m.END_DT IS NULL OR m.END_DT = '') AND (m.VF_DT <= TO_CHAR(SYSDATE, 'YYYYMMDD'))) SELECT * FROM (SELECT obj_name FROM v_object WHERE id = 1) WHERE ROWNUM <= 1000",
      "SELECT a, COUNT(*) AS n FROM v_object WHERE b <> '99991231' GROUP BY a ORDER BY n DESC FETCH FIRST 10 ROWS ONLY",
      "WITH c AS (SELECT a FROM t) SELECT * FROM (SELECT a FROM c) WHERE ROWNUM <= 5",
      "SELECT o.a FROM v_object o WHERE EXISTS (SELECT 1 FROM v_item i WHERE i.x = o.id) AND o.t LIKE '%보험%'",
    ];

    for (const sql of samples) {
      expect(strip(formatSql(sql))).toBe(strip(sql));
    }
  });

  it("앞뒤 공백과 줄바꿈이 섞인 입력을 정리한다", () => {
    expect(formatSql("  SELECT a\n   FROM   t  ")).toBe("SELECT a\nFROM t");
  });

  it("빈 문자열도 안전하다", () => {
    expect(formatSql("")).toBe("");
  });
});
