const DB_NAMES = { oracle: "Oracle", postgresql: "PostgreSQL" };

/** "oracle", "19c" -> "Oracle 19c" */
export function dbLabel(dbType, dbVersion) {
  return `${DB_NAMES[dbType] ?? dbType} ${dbVersion}`.trim();
}

// 최상위(괄호 밖)에서 줄을 바꿀 절. 긴 것부터 맞춘다.
const CLAUSES = [
  "UNION ALL",
  "GROUP BY",
  "ORDER BY",
  "FETCH FIRST",
  "LEFT JOIN",
  "RIGHT JOIN",
  "INNER JOIN",
  "FULL JOIN",
  "CROSS JOIN",
  "SELECT",
  "FROM",
  "WHERE",
  "HAVING",
  "UNION",
  "LIMIT",
  "JOIN",
];

const isWordChar = (ch) => ch !== undefined && /[A-Za-z0-9_]/.test(ch);

function clauseAt(sql, index) {
  if (isWordChar(sql[index - 1])) return null;
  const rest = sql.slice(index).toUpperCase();
  for (const clause of CLAUSES) {
    if (rest.startsWith(clause) && !isWordChar(sql[index + clause.length])) {
      return clause;
    }
  }
  return null;
}

/** text[open]의 "("와 짝이 맞는 ")"의 위치. 문자열과 따옴표 식별자 안은 건너뛴다. 없으면 -1. */
function matchingParen(text, open) {
  let depth = 0;
  let quote = null;
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === "'" || ch === '"') {
      quote = ch;
    } else if (ch === "(") {
      depth += 1;
    } else if (ch === ")") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

// "AS (" 다음에 질의가 오는 괄호는 CTE 본문이다
const CTE_BODY_BEFORE = /\bAS\s*$/i;
const QUERY_START = /^\s*(SELECT|WITH)\b/i;

/**
 * 읽기 쉽도록 최상위 절 앞에서 줄을 바꾼다. 화면 표시용이다.
 * CTE 본문(`AS ( SELECT ... )`)은 들여쓰기해서 같은 방식으로 나눈다.
 * 문자열('...')과 따옴표 식별자("...") 안, 그 밖의 괄호 안(하위 질의)은 건드리지 않고,
 * 공백이 아닌 글자는 하나도 바꾸지 않는다.
 */
export function formatSql(sql) {
  const text = sql.replace(/\s+/g, " ").trim();
  let out = "";
  let depth = 0;
  let quote = null;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      out += ch;
      if (ch === quote) quote = null; // '' 로 이스케이프된 따옴표는 닫고 바로 다시 연다
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      out += ch;
      continue;
    }
    if (ch === "(" && depth === 0 && CTE_BODY_BEFORE.test(out)) {
      const close = matchingParen(text, i);
      const inner = close === -1 ? "" : text.slice(i + 1, close);
      if (close !== -1 && QUERY_START.test(inner)) {
        const body = formatSql(inner)
          .split("\n")
          .map((line) => `  ${line}`)
          .join("\n");
        out += `(\n${body}\n)`;
        i = close;
        continue;
      }
    }
    if (ch === "(") depth += 1;
    if (ch === ")") depth = Math.max(0, depth - 1);
    if (depth === 0) {
      const clause = clauseAt(text, i);
      if (clause) {
        if (out.trim() !== "") out = `${out.trimEnd()}\n`;
        out += text.slice(i, i + clause.length);
        i += clause.length - 1;
        continue;
      }
    }
    out += ch;
  }
  return out;
}
