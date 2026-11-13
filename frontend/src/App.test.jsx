import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { getAccessKey } from "./api";

const DATASOURCES = [
  { id: "p001", name: "샘플 프로젝트 1", db_type: "oracle", db_version: "19c" },
  { id: "p002", name: "PostgreSQL 프로젝트", db_type: "postgresql", db_version: "14" },
];

const OK_RESPONSE = {
  request_id: "req-1",
  status: "OK",
  sql: "SELECT * FROM (SELECT OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101) WHERE ROWNUM <= 1000",
  references: [{ table: "OBJ_MAIN", columns: ["TYPEID", "OBJ_NAME"] }],
  metadata_version: "abc123def456",
  message: null,
};

const REJECTED_RESPONSE = {
  request_id: "req-2",
  status: "REJECTED",
  sql: null,
  references: [],
  metadata_version: "abc123def456",
  message: "이 질문은 현재 스키마로 답할 수 없습니다",
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** fetch를 가짜로 바꾼다. sqlHandler가 POST /text-to-sql 응답을 정한다. */
function mockServer({ datasources = () => json(DATASOURCES), sqlHandler = () => json(OK_RESPONSE) } = {}) {
  const calls = [];
  const fetchMock = vi.fn((url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/v1/datasources") return Promise.resolve(datasources(calls));
    if (url === "/api/v1/text-to-sql") return Promise.resolve(sqlHandler(options, calls));
    return Promise.reject(new Error(`예상하지 못한 요청: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

const posts = (calls) => calls.filter((call) => call.url === "/api/v1/text-to-sql");
const bodyOf = (call) => JSON.parse(call.options.body);

async function renderReady() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
  return user;
}

const questionBox = () => screen.getByLabelText("질문");
const submitButton = () => screen.getByRole("button", { name: /SQL 생성|생성 중/ });

beforeEach(() => {
  mockServer();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("데이터소스", () => {
  it("목록을 불러와 이름과 DB 종류·버전을 보여 준다", async () => {
    await renderReady();

    expect(screen.getByRole("option", { name: "샘플 프로젝트 1 · Oracle 19c" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "PostgreSQL 프로젝트 · PostgreSQL 14" })).toBeInTheDocument();
    expect(screen.getByLabelText("데이터소스")).toHaveValue("p001");
  });

  it("불러오는 동안에는 선택할 수 없다", () => {
    mockServer({ datasources: () => new Promise(() => {}) });
    render(<App />);

    expect(screen.getByLabelText("데이터소스")).toBeDisabled();
    expect(screen.getByRole("option", { name: "불러오는 중…" })).toBeInTheDocument();
  });

  it("목록을 불러오지 못하면 오류와 다시 시도 버튼을 보여 주고, 다시 시도하면 복구된다", async () => {
    let first = true;
    mockServer({
      datasources: () => {
        if (first) {
          first = false;
          return json({ code: "INTERNAL_ERROR", message: "서버 내부 오류입니다" }, 500);
        }
        return json(DATASOURCES);
      },
    });
    const user = userEvent.setup();
    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("서버 내부 오류입니다");
    await user.click(within(alert).getByRole("button", { name: "다시 시도" }));

    expect(await screen.findByRole("option", { name: /샘플 프로젝트 1/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("등록된 데이터소스가 없으면 안내하고 질문을 보낼 수 없다", async () => {
    mockServer({ datasources: () => json([]) });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("등록된 데이터소스가 없습니다.")).toBeInTheDocument();
    await user.type(questionBox(), "상품 목록");
    expect(submitButton()).toBeDisabled();
    expect(screen.getByLabelText("데이터소스")).toBeDisabled();
  });

  it("저장된 데이터소스 선택을 복원한다", async () => {
    window.localStorage.setItem("text2sql.datasourceId", "p002");
    await renderReady();

    expect(screen.getByLabelText("데이터소스")).toHaveValue("p002");
  });

  it("저장된 데이터소스가 목록에 없으면 첫 번째를 고른다", async () => {
    window.localStorage.setItem("text2sql.datasourceId", "gone");
    await renderReady();

    expect(screen.getByLabelText("데이터소스")).toHaveValue("p001");
  });
});

describe("질문 입력", () => {
  it("질문이 비어 있거나 공백뿐이면 보낼 수 없다", async () => {
    const user = await renderReady();
    expect(submitButton()).toBeDisabled();

    await user.type(questionBox(), "   ");
    expect(submitButton()).toBeDisabled();

    await user.type(questionBox(), "상품");
    expect(submitButton()).toBeEnabled();
  });

  it("예시를 누르면 질문 칸이 채워진다", async () => {
    const user = await renderReady();

    await user.click(screen.getByRole("button", { name: "유형별 오브젝트 수를 알려줘" }));

    expect(questionBox()).toHaveValue("유형별 오브젝트 수를 알려줘");
    expect(submitButton()).toBeEnabled();
  });

  it("마지막 질문을 저장해 두었다가 다시 열면 복원한다", async () => {
    const user = userEvent.setup();
    const first = render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    await user.type(questionBox(), "저장될 질문");
    expect(window.localStorage.getItem("text2sql.question")).toBe("저장될 질문");
    first.unmount();

    render(<App />);

    expect(questionBox()).toHaveValue("저장될 질문");
  });

  it("저장소를 쓸 수 없어도 화면은 동작한다", async () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("차단됨");
    });
    const setSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("차단됨");
    });
    const user = await renderReady();

    await user.type(questionBox(), "질문");

    expect(submitButton()).toBeEnabled();
    spy.mockRestore();
    setSpy.mockRestore();
  });
});

describe("SQL 생성", () => {
  it("질문을 보내고 SQL, 사용한 테이블과 컬럼, 메타 정보를 보여 준다", async () => {
    const { calls } = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "  TYPEID가 101인 오브젝트 이름  ");
    await user.click(submitButton());

    const result = await screen.findByRole("article");
    expect(within(result).getByText("생성 완료")).toBeInTheDocument();
    // 화면에는 절마다 줄을 나눠 보여 준다
    expect(
      within(result).getByText(/SELECT \*\s+FROM \(SELECT OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101\)\s+WHERE ROWNUM <= 1000/),
    ).toBeInTheDocument();
    const refs = within(result).getByLabelText("사용한 테이블과 컬럼");
    expect(within(refs).getByText("OBJ_MAIN")).toBeInTheDocument();
    expect(within(refs).getByText("TYPEID")).toBeInTheDocument();
    expect(within(refs).getByText("OBJ_NAME")).toBeInTheDocument();
    expect(within(result).getByText("abc123def456")).toBeInTheDocument();
    expect(within(result).getByText("req-1")).toBeInTheDocument();
    expect(within(result).getByText(/\d+\.\d초/)).toBeInTheDocument();

    const [post] = posts(calls);
    expect(bodyOf(post)).toEqual({ question: "TYPEID가 101인 오브젝트 이름", datasource_id: "p001" });
  });

  it("선택한 데이터소스로 요청한다", async () => {
    const { calls } = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.selectOptions(screen.getByLabelText("데이터소스"), "p002");
    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());
    await screen.findByRole("article");

    expect(bodyOf(posts(calls)[0]).datasource_id).toBe("p002");
    expect(window.localStorage.getItem("text2sql.datasourceId")).toBe("p002");
  });

  it("요청하는 동안 버튼을 막고 경과 시간을 보여 준다", async () => {
    const pending = deferred();
    const { calls } = mockServer({ sqlHandler: () => pending.promise });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());

    expect(screen.getByRole("button", { name: /생성 중/ })).toBeDisabled();
    expect(screen.getByText(/초 경과/)).toBeInTheDocument();
    // 눌러도 두 번째 요청이 나가지 않는다
    await user.click(screen.getByRole("button", { name: /생성 중/ }));
    expect(posts(calls)).toHaveLength(1);

    pending.resolve(json(OK_RESPONSE));
    await screen.findByRole("article");
    expect(submitButton()).toBeEnabled();
  });

  it("Ctrl+Enter로도 실행한다", async () => {
    const { calls } = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "상품 목록{Control>}{Enter}{/Control}");

    await screen.findByRole("article");
    expect(posts(calls)).toHaveLength(1);
    expect(questionBox()).toHaveValue("상품 목록"); // 줄바꿈이 들어가지 않는다
  });

  it("그냥 Enter는 줄바꿈이고 요청하지 않는다", async () => {
    const { calls } = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "첫 줄{Enter}둘째 줄");

    expect(posts(calls)).toHaveLength(0);
    expect(questionBox()).toHaveValue("첫 줄\n둘째 줄");
  });

  it("질문이 비어 있으면 Ctrl+Enter도 무시한다", async () => {
    const { calls } = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "{Control>}{Enter}{/Control}");

    expect(posts(calls)).toHaveLength(0);
  });

  it("거부되면 사유를 알려 주고 SQL은 보여 주지 않는다", async () => {
    mockServer({ sqlHandler: () => json(REJECTED_RESPONSE) });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "지난달 매출");
    await user.click(submitButton());

    const result = await screen.findByRole("article");
    expect(within(result).getByText("생성하지 못함")).toBeInTheDocument();
    expect(within(result).getByText("이 질문은 현재 스키마로 답할 수 없습니다")).toBeInTheDocument();
    expect(within(result).getByText(/더 구체적으로/)).toBeInTheDocument();
    expect(within(result).queryByText("SQL")).not.toBeInTheDocument();
    expect(within(result).queryByRole("button", { name: "복사" })).not.toBeInTheDocument();
  });

  it("실행용 SQL이 아니라는 임시 안내 없이 결과만 보여 준다", async () => {
    const user = await renderReady();

    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());

    await screen.findByRole("article");
    expect(screen.queryByText(/이름 기준 SQL입니다/)).not.toBeInTheDocument();
  });

  it("모델이 쓴 CTE가 있는 SQL을 들여쓰기해서 보여 주고, 복사는 원본 그대로 한다", async () => {
    const finalSql =
      "WITH recent AS (SELECT BIZCODE, OBJ_NAME FROM OBJ_MAIN WHERE TYPEID <> 0) " +
      "SELECT * FROM (SELECT OBJ_NAME FROM recent WHERE BIZCODE = 'A0001') WHERE ROWNUM <= 1000";
    mockServer({ sqlHandler: () => json({ ...OK_RESPONSE, sql: finalSql }) });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());

    const code = (await screen.findByRole("article")).querySelector("code");
    expect(code.textContent).toBe(
      [
        "WITH recent AS (",
        "  SELECT BIZCODE, OBJ_NAME",
        "  FROM OBJ_MAIN",
        "  WHERE TYPEID <> 0",
        ")",
        "SELECT *",
        "FROM (SELECT OBJ_NAME FROM recent WHERE BIZCODE = 'A0001')",
        "WHERE ROWNUM <= 1000",
      ].join("\n"),
    );
  });

  it("컬럼이 없는 참조(COUNT(*))는 안내 문구로 보여 준다", async () => {
    mockServer({
      sqlHandler: () =>
        json({ ...OK_RESPONSE, sql: "SELECT COUNT(*) FROM OBJ_MAIN", references: [{ table: "OBJ_MAIN", columns: [] }] }),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "몇 개야");
    await user.click(submitButton());

    expect(await screen.findByText("특정 컬럼 없음")).toBeInTheDocument();
  });

  it("새 요청을 보내면 이전 결과는 새 결과로 바뀐다", async () => {
    let count = 0;
    mockServer({
      sqlHandler: () => {
        count += 1;
        return json(count === 1 ? OK_RESPONSE : REJECTED_RESPONSE);
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });

    await user.type(questionBox(), "첫 질문");
    await user.click(submitButton());
    expect(await screen.findByText("생성 완료")).toBeInTheDocument();

    await user.click(submitButton());
    expect(await screen.findByText("생성하지 못함")).toBeInTheDocument();
    expect(screen.queryByText("생성 완료")).not.toBeInTheDocument();
  });
});

describe("오류", () => {
  async function submitWith(sqlHandler) {
    const server = mockServer({ sqlHandler });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());
    return { user, ...server };
  }

  it("서버가 알려 준 한국어 메시지와 코드를 그대로 보여 준다 (400)", async () => {
    await submitWith(() =>
      json({ code: "DATASOURCE_NOT_FOUND", message: "등록되지 않은 데이터소스입니다" }, 400),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("등록되지 않은 데이터소스입니다");
    expect(alert).toHaveTextContent("DATASOURCE_NOT_FOUND");
    // 요청 자체가 잘못된 경우에는 같은 요청을 다시 보내라고 권하지 않는다
    expect(within(alert).queryByRole("button", { name: "다시 시도" })).not.toBeInTheDocument();
  });

  it("LLM을 쓸 수 없을 때 (503) 다시 시도할 수 있다", async () => {
    let attempt = 0;
    const { user, calls } = await submitWith(() => {
      attempt += 1;
      return attempt === 1
        ? json({ code: "LLM_UNAVAILABLE", message: "LLM을 사용할 수 없습니다" }, 503)
        : json(OK_RESPONSE);
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("LLM을 사용할 수 없습니다");
    await user.click(within(alert).getByRole("button", { name: "다시 시도" }));

    expect(await screen.findByText("생성 완료")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(posts(calls)).toHaveLength(2);
  });

  it("서버에 연결할 수 없을 때 한국어 안내를 보여 준다", async () => {
    const server = mockServer();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    server.fetchMock.mockImplementation((url) =>
      url === "/api/v1/text-to-sql" ? Promise.reject(new TypeError("Failed to fetch")) : Promise.resolve(json(DATASOURCES)),
    );

    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("서버에 연결할 수 없습니다");
    expect(alert).not.toHaveTextContent("Failed to fetch");
    expect(within(alert).getByRole("button", { name: "다시 시도" })).toBeInTheDocument();
  });

  it("오류가 난 뒤 성공하면 오류 표시가 사라진다", async () => {
    let attempt = 0;
    const { user } = await submitWith(() => {
      attempt += 1;
      return attempt === 1 ? json({ code: "INTERNAL_ERROR", message: "서버 내부 오류입니다" }, 500) : json(OK_RESPONSE);
    });
    await screen.findByRole("alert");

    await user.click(submitButton());

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(await screen.findByText("생성 완료")).toBeInTheDocument();
  });
});

describe("SQL 복사", () => {
  it("원본 SQL을 클립보드에 복사하고 잠시 '복사됨'으로 바뀐다", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    // userEvent.setup()이 clipboard를 가로채므로 그 뒤에 덮어쓴다
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());
    await screen.findByRole("article");

    await user.click(screen.getByRole("button", { name: "복사" }));

    // 줄바꿈을 넣은 표시용 문자열이 아니라 서버가 준 SQL 그대로 복사한다
    expect(writeText).toHaveBeenCalledWith(OK_RESPONSE.sql);
    expect(await screen.findByRole("button", { name: "복사됨" })).toBeInTheDocument();
  });

  it("복사에 실패하면 알려 준다", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("거부됨"));
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    document.execCommand = vi.fn().mockReturnValue(false);
    render(<App />);
    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    await user.type(questionBox(), "상품 목록");
    await user.click(submitButton());
    await screen.findByRole("article");

    await user.click(screen.getByRole("button", { name: "복사" }));

    expect(await screen.findByRole("button", { name: "복사 실패" })).toBeInTheDocument();
  });
});

describe("접속 키", () => {
  const UNAUTHORIZED = { code: "UNAUTHORIZED", message: "접속 키가 없거나 올바르지 않습니다" };

  /** 올바른 키(open-sesame)가 있을 때만 데이터소스를 돌려주는 가짜 서버 */
  function lockedServer() {
    return mockServer({
      datasources: (calls) => {
        const key = calls.at(-1).options.headers?.["X-Access-Key"];
        return key === "open-sesame" ? json(DATASOURCES) : json(UNAUTHORIZED, 401);
      },
      sqlHandler: (options) =>
        options.headers["X-Access-Key"] === "open-sesame" ? json(OK_RESPONSE) : json(UNAUTHORIZED, 401),
    });
  }

  it("서버가 키를 요구하면 입력 카드만 보여 주고, 처음에는 오류 문구를 띄우지 않는다", async () => {
    lockedServer();
    render(<App />);

    expect(await screen.findByLabelText("접속 키")).toHaveAttribute("type", "password");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "질문" })).not.toBeInTheDocument();
  });

  it("키를 입력하면 헤더에 실어 다시 불러오고 질문 화면으로 넘어간다", async () => {
    const { calls } = lockedServer();
    const user = userEvent.setup();
    render(<App />);

    await user.type(await screen.findByLabelText("접속 키"), "open-sesame");
    await user.click(screen.getByRole("button", { name: "확인" }));

    await screen.findByRole("option", { name: /샘플 프로젝트 1/ });
    expect(calls.at(-1).options.headers["X-Access-Key"]).toBe("open-sesame");
    expect(getAccessKey()).toBe("open-sesame");
    expect(screen.queryByLabelText("접속 키")).not.toBeInTheDocument();
  });

  it("틀린 키는 거부하고 다시 입력받는다", async () => {
    lockedServer();
    const user = userEvent.setup();
    render(<App />);

    await user.type(await screen.findByLabelText("접속 키"), "wrong");
    await user.click(screen.getByRole("button", { name: "확인" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("접속 키가 올바르지 않습니다");
    expect(screen.getByLabelText("접속 키")).toHaveValue("");
  });

  it("빈 키는 보낼 수 없다", async () => {
    lockedServer();
    const user = userEvent.setup();
    render(<App />);

    await screen.findByLabelText("접속 키");
    expect(screen.getByRole("button", { name: "확인" })).toBeDisabled();
    await user.type(screen.getByLabelText("접속 키"), "   ");
    expect(screen.getByRole("button", { name: "확인" })).toBeDisabled();
  });

  it("키가 필요 없는 서버에서는 입력 카드를 보여 주지 않는다", async () => {
    mockServer();
    await renderReady();

    expect(screen.queryByLabelText("접속 키")).not.toBeInTheDocument();
  });

  it("질문을 보내는 도중 키가 거부되면 입력 카드를 다시 띄운다", async () => {
    const { calls } = mockServer({
      sqlHandler: () => json(UNAUTHORIZED, 401),
    });
    const user = await renderReady();

    await user.type(screen.getByRole("textbox", { name: "질문" }), "상품 목록");
    await user.click(screen.getByRole("button", { name: "SQL 생성" }));

    expect(await screen.findByLabelText("접속 키")).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);
  });
});
