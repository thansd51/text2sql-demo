import SqlBlock from "./SqlBlock";

function References({ references }) {
  if (!references?.length) return null;
  return (
    <section className="refs" aria-label="사용한 테이블과 컬럼">
      <h3 className="refs__title">사용한 테이블과 컬럼</h3>
      <ul className="refs__list">
        {references.map((ref) => (
          <li key={ref.table} className="refs__item">
            <code className="chip chip--table">{ref.table}</code>
            <span className="refs__columns">
              {ref.columns.length ? (
                ref.columns.map((column) => (
                  <code key={column} className="chip">
                    {column}
                  </code>
                ))
              ) : (
                <span className="muted">특정 컬럼 없음</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Meta({ data, elapsedMs }) {
  return (
    <dl className="meta">
      <div>
        <dt>소요 시간</dt>
        <dd>{(elapsedMs / 1000).toFixed(1)}초</dd>
      </div>
      <div>
        <dt>메타데이터 버전</dt>
        <dd>
          <code>{data.metadata_version}</code>
        </dd>
      </div>
      <div>
        <dt>요청 ID</dt>
        <dd>
          <code>{data.request_id}</code>
        </dd>
      </div>
    </dl>
  );
}

export default function ResultCard({ data, elapsedMs }) {
  const ok = data.status === "OK";
  return (
    <article className="card result" aria-labelledby="result-title">
      <header className="result__header">
        <h2 id="result-title" className="card__title">
          결과
        </h2>
        <span className={`pill ${ok ? "pill--ok" : "pill--warn"}`}>
          {ok ? "생성 완료" : "생성하지 못함"}
        </span>
      </header>

      {ok ? (
        <>
          <SqlBlock sql={data.sql} />
          <References references={data.references} />
        </>
      ) : (
        <div className="notice notice--warn" role="status">
          <strong>{data.message}</strong>
          <span>질문을 조금 더 구체적으로 바꿔 다시 시도해 보세요.</span>
        </div>
      )}

      <Meta data={data} elapsedMs={elapsedMs} />
    </article>
  );
}
