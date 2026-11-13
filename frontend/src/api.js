// 백엔드와는 docs/design.md의 API 계약으로만 통신한다. 주소는 같은 출처의 상대 경로다.
const BASE = "/api/v1";

// 접속 키는 탭을 닫으면 사라지도록 sessionStorage에만 둔다 (localStorage에 남기지 않는다).
// 저장소를 쓸 수 없는 환경에서도 이 탭이 열려 있는 동안은 메모리에 들고 있는다.
const KEY_STORAGE = "text2sql.accessKey";
let memoryKey = "";

export function getAccessKey() {
  if (memoryKey) return memoryKey;
  try {
    return window.sessionStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setAccessKey(value) {
  memoryKey = value;
  try {
    if (value) window.sessionStorage.setItem(KEY_STORAGE, value);
    else window.sessionStorage.removeItem(KEY_STORAGE);
  } catch {
    // 저장은 편의 기능이다
  }
}

const authHeaders = () => {
  const key = getAccessKey();
  return key ? { "X-Access-Key": key } : {};
};

/** 서버가 돌려준 { code, message } 오류, 또는 연결/해석 실패를 같은 모양으로 다룬다. */
export class ApiError extends Error {
  constructor({ code, message, status }) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

const badResponse = (status) =>
  new ApiError({
    code: "BAD_RESPONSE",
    message: `서버 응답을 해석할 수 없습니다 (HTTP ${status})`,
    status,
  });

async function errorFrom(response) {
  try {
    const body = await response.json();
    if (typeof body?.code === "string" && typeof body?.message === "string") {
      return new ApiError({
        code: body.code,
        message: body.message,
        status: response.status,
      });
    }
  } catch {
    // JSON이 아닌 본문
  }
  return badResponse(response.status);
}

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, options);
  } catch (error) {
    if (error?.name === "AbortError") throw error; // 호출한 쪽이 취소한 것
    throw new ApiError({
      code: "NETWORK_ERROR",
      message: "서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.",
      status: 0,
    });
  }
  if (!response.ok) throw await errorFrom(response);
  try {
    return await response.json();
  } catch {
    throw badResponse(response.status);
  }
}

/** GET /api/v1/datasources -> [{ id, name, db_type, db_version }] */
export function fetchDatasources(signal) {
  return request("/datasources", { headers: authHeaders(), signal });
}

/** POST /api/v1/text-to-sql -> { request_id, status, sql, references, metadata_version, message } */
export function requestSql({ question, datasourceId }, signal) {
  return request("/text-to-sql", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ question, datasource_id: datasourceId }),
    signal,
  });
}
