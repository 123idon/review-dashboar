"""Import normalized Naver reviews. Preview by default; --apply commits a safe merge."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartstore_import import merge_reviews, validate_reviews


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file", type=Path)
    p.add_argument("--base", default="https://web-production-ce7ca1.up.railway.app")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    base = args.base.rstrip("/")
    if urlparse(base).scheme != "https":
        p.error("HTTPS URL이 필요합니다")
    rows = validate_reviews(json.loads(args.file.read_text(encoding="utf-8")))

    def api(path, body=None):
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = Request(base + path, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    status = api("/api/smartstore-status")
    if status.get("import_mode") != "merge":
        raise SystemExit("서버 병합 기능이 배포되지 않았습니다. 업로드를 중단했습니다.")
    unique, _ = merge_reviews([], rows)
    print(json.dumps({"received": len(rows), "unique_in_file": len(unique),
                      "from": min(r["date"] for r in rows), "to": max(r["date"] for r in rows),
                      "server_latest": status.get("last_review_date"), "apply": args.apply}, ensure_ascii=False), flush=True)
    if not args.apply:
        return
    sid = uuid4().hex
    for offset in range(0, len(rows), 500):
        result = api("/api/import-smartstore-chunk", dict(reviews=rows[offset:offset+500],
                     replace=offset == 0, import_id=sid))
        if not result.get("ok") or result.get("total") != min(offset + 500, len(rows)):
            raise SystemExit("청크 전송 검증 실패. 최종 병합은 실행하지 않았습니다.")
        print(f"staged {result['total']}/{len(rows)}", flush=True)
    result = api(f"/api/import-smartstore-done?import_id={sid}&expected_count={len(rows)}", {})
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not result.get("ok"):
        raise SystemExit("병합 실패")
    verified = api("/api/smartstore-status")
    if verified.get("last_review_date", "") < max(r["date"] for r in rows):
        raise SystemExit("최신 후기 날짜 검증 실패")
    print("Verified latest review date: " + verified["last_review_date"])


if __name__ == "__main__":
    main()
