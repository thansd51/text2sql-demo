import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchDatasources, getAccessKey, requestSql, setAccessKey } from "./api";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("fetchDatasources", () => {
  it("상대 경로 /api/v1/datasources를 GET으로 부른다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([{ id: "p001" }]));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchDatasources();

    expect(result).toEqual([{ id: "p001" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/datasources");
  });
});

describe("requestSql", () => {
  it("question과 datasource_id를 JSON으로 POST한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "OK" }));
    vi.stubGlobal("fetch", fetchMock);

    await requestSql({ question: "상품 목록", datasourceId: "p001" });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/text-to-sql");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ question: "상품 목록", datasource_id: "p001" });
  });

  it("서버의 { code, message } 오류를 ApiError로 바꾼다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "DATASOURCE_NOT_FOUND", message: "등록되지 않은 데이터소스입니다" }, 400),
      ),
    );

    const error = await requestSql({ question: "q", datasourceId: "x" }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("DATASOURCE_NOT_FOUND");
    expect(error.message).toBe("등록되지 않은 데이터소스입니다");
    expect(error.status).toBe(400);
  });

  it("503도 같은 형식으로 다룬다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ code: "LLM_UNAVAILABLE", message: "LLM을 사용할 수 없습니다" }, 503)),
    );

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error.code).toBe("LLM_UNAVAILABLE");
    expect(error.status).toBe(503);
  });

  it("JSON이 아닌 오류 응답은 한국어 안내로 바꾼다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 })));

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error.code).toBe("BAD_RESPONSE");
    expect(error.message).toBe("서버 응답을 해석할 수 없습니다 (HTTP 502)");
    expect(error.message).not.toContain("html");
  });

  it("code나 message가 없는 JSON 오류도 안전하게 처리한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Not Found" }, 404)));

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error.code).toBe("BAD_RESPONSE");
    expect(error.status).toBe(404);
  });

  it("성공 응답이 JSON이 아니면 오류로 본다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("ok", { status: 200 })));

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error.code).toBe("BAD_RESPONSE");
  });

  it("연결 실패는 NETWORK_ERROR와 한국어 메시지로 바꾼다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("NETWORK_ERROR");
    expect(error.status).toBe(0);
    expect(error.message).toContain("서버에 연결할 수 없습니다");
    expect(error.message).not.toContain("Failed to fetch");
  });

  it("호출한 쪽이 취소한 요청(AbortError)은 그대로 전달한다", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));

    const error = await requestSql({ question: "q", datasourceId: "p001" }).catch((e) => e);

    expect(error.name).toBe("AbortError");
  });
});

describe("접속 키", () => {
  afterEach(() => setAccessKey(""));

  it("키가 없으면 헤더를 붙이지 않는다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await fetchDatasources();

    expect(fetchMock.mock.calls[0][1].headers).toEqual({});
  });

  it("저장한 키를 두 요청 모두에 X-Access-Key 헤더로 보낸다", async () => {
    // Response는 본문을 한 번만 읽을 수 있어서 호출마다 새로 만든다
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse([])));
    vi.stubGlobal("fetch", fetchMock);
    setAccessKey("비밀-key");

    await fetchDatasources();
    await requestSql({ question: "q", datasourceId: "p001" });

    expect(fetchMock.mock.calls[0][1].headers["X-Access-Key"]).toBe("비밀-key");
    const post = fetchMock.mock.calls[1][1].headers;
    expect(post["X-Access-Key"]).toBe("비밀-key");
    expect(post["Content-Type"]).toBe("application/json");
  });

  it("키는 sessionStorage에만 저장하고 localStorage에는 남기지 않는다", () => {
    setAccessKey("abc");

    expect(getAccessKey()).toBe("abc");
    expect(window.sessionStorage.getItem("text2sql.accessKey")).toBe("abc");
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("abc");

    setAccessKey("");
    expect(getAccessKey()).toBe("");
    expect(window.sessionStorage.getItem("text2sql.accessKey")).toBeNull();
  });

  it("저장소를 쓸 수 없어도 이 탭에서는 키를 기억한다", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("차단됨");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("차단됨");
    });

    setAccessKey("memory-only");

    expect(getAccessKey()).toBe("memory-only");
    vi.restoreAllMocks();
  });

  it("401 응답을 UNAUTHORIZED 오류로 바꾼다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "UNAUTHORIZED", message: "접속 키가 없거나 올바르지 않습니다" }, 401),
      ),
    );

    const error = await fetchDatasources().catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("UNAUTHORIZED");
    expect(error.status).toBe(401);
  });
});
