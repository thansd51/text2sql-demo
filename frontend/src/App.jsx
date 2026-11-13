import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchDatasources, getAccessKey, requestSql, setAccessKey } from "./api";
import ResultCard from "./components/ResultCard";
import { dbLabel } from "./format";

const EXAMPLES = [
  "상품 목록을 보여줘",
  "유형별 오브젝트 수를 알려줘",
  "코드가 A100인 오브젝트의 이름은?",
];

const STORAGE_KEYS = { datasource: "text2sql.datasourceId", question: "text2sql.question" };

// 저장소를 쓸 수 없는 환경(시크릿 모드 등)에서도 화면은 동작해야 한다
function load(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // 저장은 편의 기능이다
  }
}

function Elapsed({ since }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds(Math.floor((performance.now() - since) / 1000)), 500);
    return () => clearInterval(id);
  }, [since]);
  return <span>{seconds}초 경과</span>;
}

function ErrorBox({ error, onRetry }) {
  return (
    <div className="notice notice--error" role="alert">
      <strong>{error.message}</strong>
      {error.code && <code className="notice__code">{error.code}</code>}
      {onRetry && (
        <button type="button" className="button button--ghost" onClick={onRetry}>
          다시 시도
        </button>
      )}
    </div>
  );
}

const UNAUTHORIZED = "UNAUTHORIZED";

/** 서버가 접속 키를 요구할 때(401) 보여 준다. 이미 키를 넣었는데도 거부됐다면 그 사유를 알린다. */
function AccessKeyCard({ onSave, rejected }) {
  const [value, setValue] = useState("");
  function handleSubmit(event) {
    event.preventDefault();
    if (value.trim() !== "") onSave(value.trim());
  }
  return (
    <form className="card" onSubmit={handleSubmit} noValidate>
      <h2 className="card__title">접속 키</h2>
      <p className="muted">이 서비스는 접속 키가 있어야 사용할 수 있습니다.</p>
      {rejected && (
        <div className="notice notice--error" role="alert">
          <strong>접속 키가 올바르지 않습니다. 다시 확인해 주세요.</strong>
        </div>
      )}
      <div className="field">
        <label htmlFor="access-key" className="field__label">
          접속 키
        </label>
        <input
          id="access-key"
          type="password"
          className="input"
          autoComplete="off"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
      <div className="actions">
        <button type="submit" className="button button--primary" disabled={value.trim() === ""}>
          확인
        </button>
      </div>
    </form>
  );
}

export default function App() {
  const [datasources, setDatasources] = useState({ state: "loading", items: [], error: null });
  const [datasourceId, setDatasourceId] = useState(() => load(STORAGE_KEYS.datasource) ?? "");
  const [question, setQuestion] = useState(() => load(STORAGE_KEYS.question) ?? "");
  const [run, setRun] = useState({ state: "idle" }); // idle | loading | done | error
  const requestController = useRef(null);

  const loadDatasources = useCallback((signal) => {
    setDatasources({ state: "loading", items: [], error: null });
    fetchDatasources(signal)
      .then((items) => {
        setDatasources({ state: "ready", items, error: null });
        // 저장된 선택이 더 이상 없으면 첫 번째 데이터소스를 고른다
        setDatasourceId((current) =>
          items.some((item) => item.id === current) ? current : (items[0]?.id ?? ""),
        );
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setDatasources({ state: "error", items: [], error });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadDatasources(controller.signal);
    return () => controller.abort();
  }, [loadDatasources]);

  useEffect(() => () => requestController.current?.abort(), []);

  const trimmed = question.trim();
  const loading = run.state === "loading";
  const canSubmit = trimmed !== "" && datasourceId !== "" && !loading;

  async function submit() {
    if (!canSubmit) return;
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const startedAt = performance.now();
    setRun({ state: "loading", startedAt });
    try {
      const data = await requestSql({ question: trimmed, datasourceId }, controller.signal);
      setRun({ state: "done", data, elapsedMs: performance.now() - startedAt });
    } catch (error) {
      if (error?.name === "AbortError") return;
      setRun({
        state: "error",
        error:
          error instanceof ApiError
            ? error
            : new ApiError({ code: "UNKNOWN", message: "알 수 없는 오류가 발생했습니다", status: 0 }),
      });
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  }

  function changeQuestion(value) {
    setQuestion(value);
    save(STORAGE_KEYS.question, value);
  }

  function changeDatasource(value) {
    setDatasourceId(value);
    save(STORAGE_KEYS.datasource, value);
  }

  const noDatasource = datasources.state === "ready" && datasources.items.length === 0;
  const needsKey = datasources.state === "error" && datasources.error?.code === UNAUTHORIZED;
  const runNeedsKey = run.state === "error" && run.error.code === UNAUTHORIZED;

  function saveAccessKey(value) {
    setAccessKey(value);
    setRun({ state: "idle" });
    loadDatasources();
  }

  return (
    <div className="page">
      <header className="header">
        <span className="logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="28" height="28">
            <rect width="32" height="32" rx="8" fill="currentColor" />
            <path d="M9 11h14M9 16h14M9 21h8" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
        </span>
        <div>
          <h1 className="header__title">Text-to-SQL</h1>
          <p className="header__sub">자연어 질문을 데이터소스의 DB 문법에 맞는 SQL로 바꿔 드립니다</p>
        </div>
      </header>

      <main className="main">
        {needsKey ? (
          <AccessKeyCard onSave={saveAccessKey} rejected={getAccessKey() !== ""} />
        ) : (
          <form className="card" onSubmit={handleSubmit} noValidate>
            <h2 className="card__title">질문하기</h2>

            {datasources.state === "error" && (
              <ErrorBox error={datasources.error} onRetry={() => loadDatasources()} />
            )}
            {noDatasource && (
              <div className="notice notice--warn" role="status">
                <strong>등록된 데이터소스가 없습니다.</strong>
                <span>서버의 datasources 폴더를 확인하세요.</span>
              </div>
            )}

            <div className="field">
              <label htmlFor="datasource" className="field__label">
                데이터소스
              </label>
              <select
                id="datasource"
                className="input"
                value={datasourceId}
                onChange={(event) => changeDatasource(event.target.value)}
                disabled={datasources.state !== "ready" || noDatasource}
              >
                {datasources.state === "loading" && <option value="">불러오는 중…</option>}
                {datasources.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {dbLabel(item.db_type, item.db_version)}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="question" className="field__label">
                질문
              </label>
              <textarea
                id="question"
                className="input input--textarea"
                rows={4}
                value={question}
                placeholder="예: 유형별 오브젝트 수를 알려줘"
                onChange={(event) => changeQuestion(event.target.value)}
                onKeyDown={handleKeyDown}
              />
              <div className="chips" aria-label="질문 예시">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="chip chip--button"
                    onClick={() => changeQuestion(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>

            <div className="actions">
              <button type="submit" className="button button--primary" disabled={!canSubmit}>
                {loading ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    생성 중…
                  </>
                ) : (
                  "SQL 생성"
                )}
              </button>
              <span className="actions__hint" aria-live="polite">
                {loading ? <Elapsed since={run.startedAt} /> : "Ctrl + Enter로도 실행할 수 있어요"}
              </span>
            </div>
          </form>
        )}

        <div aria-live="polite">
          {runNeedsKey && <AccessKeyCard onSave={saveAccessKey} rejected />}
          {run.state === "error" && !runNeedsKey && (
            <div className="card">
              {/* 400처럼 요청 자체가 잘못된 경우는 같은 요청을 다시 보내도 소용없다 */}
              <ErrorBox
                error={run.error}
                onRetry={run.error.status === 0 || run.error.status >= 500 ? submit : undefined}
              />
            </div>
          )}
          {run.state === "done" && <ResultCard data={run.data} elapsedMs={run.elapsedMs} />}
        </div>
      </main>
    </div>
  );
}
