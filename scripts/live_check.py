"""실행 중인 서버에 대표 질문을 보내 SQL이 기대한 조건을 갖췄는지 확인한다 (수동 확인용 스크립트).

자동 테스트(pytest)는 실제 LLM을 호출하지 않는다. 이 스크립트는 **실제 모델**을 부르므로 모델이 켜져
있어야 하고, 외부 API를 쓰면 호출 비용이 든다. 결과는 모델과 설정에 따라 달라질 수 있다.

사용법:
  uv run python scripts/live_check.py                       # 기본: http://127.0.0.1:8085
  uv run python scripts/live_check.py --url http://127.0.0.1:8085 --key <접속 키>
  uv run python scripts/live_check.py --only p001           # 한 프로젝트만
접속 키는 --key 대신 환경변수 TEXT2SQL_ACCESS_KEY로 줄 수도 있다 (접속 키를 끈 서버에는 필요 없다).
종료 코드: 모두 통과하면 0, 하나라도 실패하면 1.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# (프로젝트, 질문, SQL에 있어야 하는 정규식들, SQL에 없어야 하는 정규식들)
# 이름(장기상품 등)이 코드 조건(TYPEID = 101)으로 바뀌는지, 이름 문자열로 비교하지 않는지 본다.
CASES: list[tuple[str, str, list[str], list[str]]] = [
    (
        "p001",
        "장기상품 목록을 보여줘",
        [r"TYPEID\s*=\s*101"],
        [r"OBJ_NAME\s*=\s*'장기상품'"],
    ),
    (
        "p001",
        "일반상품 개수는?",
        [r"TYPEID\s*=\s*102", r"COUNT"],
        [r"OBJ_NAME\s*=\s*'일반상품'"],
    ),
    ("p001", "보장기간 항목의 허용값 목록", [r"R10_1\s*=\s*'#S00000031'"], []),
    (
        "p001",
        "필수 관계규칙에 해당하는 관계 구분 ID는?",
        [r"INV_TYPE\s*=\s*41|TYPE_GBN\s*=\s*4"],
        [],
    ),
    (
        "p002",
        "종신보험 목록을 보여줘",
        [r"TYPEID\s*=\s*102"],
        [r"OBJ_NAME\s*=\s*'종신보험'"],
    ),
    ("p002", "특약 목록", [r"TYPEID\s*=\s*111"], [r"OBJ_NAME\s*=\s*'특약'"]),
    (
        "p003",
        "연금상품 개수는?",
        [r"TYPEID\s*=\s*101", r"COUNT"],
        [r"OBJ_NAME\s*=\s*'연금상품'"],
    ),
    ("p003", "연금개시연령 항목의 허용값", [r"R10_1\s*=\s*'#S00000031'"], []),
    (
        "p005",
        "개인상품 이름 목록",
        [r"TYPEID\s*=\s*102"],
        [r"OBJ_NAME\s*=\s*'개인상품'"],
    ),
    ("p005", "가입연령 항목의 허용값 목록", [r"R10_1\s*=\s*'#S00000002'"], []),
    ("p004", "유형별 상품 개수", [r"GROUP BY"], []),
]


def ask(url: str, key: str | None, project: str, question: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Access-Key"] = key
    body = json.dumps({"question": question, "datasource_id": project}).encode()
    request = urllib.request.Request(
        f"{url}/api/v1/text-to-sql", data=body, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e)
        except ValueError:
            detail = {}
        return {
            "status": f"HTTP {e.code}",
            "sql": None,
            "message": detail.get("message", ""),
        }
    except urllib.error.URLError as e:
        return {"status": "연결 실패", "sql": None, "message": str(e.reason)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8085")
    parser.add_argument("--key", default=os.environ.get("TEXT2SQL_ACCESS_KEY"))
    parser.add_argument("--only", help="이 프로젝트(p001 등)만 확인한다")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.only or c[0] == args.only]
    passed = 0
    for project, question, must, never in cases:
        started = time.time()
        result = ask(args.url.rstrip("/"), args.key, project, question)
        sql = result.get("sql") or ""
        missing = [m for m in must if not re.search(m, sql, re.IGNORECASE)]
        forbidden = [n for n in never if re.search(n, sql, re.IGNORECASE)]
        ok = result.get("status") == "OK" and not missing and not forbidden
        passed += ok
        print(
            f"{'통과' if ok else '실패'} [{project}] {question} ({time.time() - started:.1f}초)"
        )
        print(
            f"     {sql or result.get('status')} {result.get('message') or ''}".rstrip()
        )
        if missing:
            print(f"     빠진 조건: {missing}")
        if forbidden:
            print(f"     있으면 안 되는 조건: {forbidden}")
    print(f"\n통과 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
