import { useEffect, useRef, useState } from "react";
import { formatSql } from "../format";

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 클립보드 API를 쓸 수 없는 환경(비보안 출처 등)을 위한 대체 방법
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      document.body.removeChild(area);
    }
  }
}

export default function SqlBlock({ sql }) {
  const [copied, setCopied] = useState("idle"); // idle | done | failed
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function handleCopy() {
    // 원본 SQL을 복사한다 (화면의 줄바꿈은 표시용이다)
    const ok = await copyText(sql);
    setCopied(ok ? "done" : "failed");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied("idle"), 2000);
  }

  const label = { idle: "복사", done: "복사됨", failed: "복사 실패" }[copied];

  return (
    <div className="sql-block">
      <div className="sql-block__bar">
        <span className="sql-block__title">SQL</span>
        <button
          type="button"
          className="button button--ghost"
          onClick={handleCopy}
          aria-live="polite"
        >
          {label}
        </button>
      </div>
      <pre className="sql-block__code">
        <code>{formatSql(sql)}</code>
      </pre>
    </div>
  );
}
