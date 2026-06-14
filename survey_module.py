"""
백년화편 고객만족 설문조사 연동 모듈
- 구글 서비스 계정으로 비공개 시트를 읽음 (시트는 공개하지 않음)
- 휴대폰번호는 수집 즉시 마스킹하여 저장 (원본은 서버에 남기지 않음)
- 통계 + 주관식 키워드 + 마스킹 원본을 제공

환경변수:
  GOOGLE_SERVICE_ACCOUNT_JSON : 서비스 계정 키 JSON 전체 문자열
  SURVEY_SHEET_ID             : (선택) 기본값은 아래 SHEET_ID
  SURVEY_SHEET_GID            : (선택) 기본값은 아래 SHEET_GID
"""
import json
import os
import re
import io
import csv
from pathlib import Path
from datetime import datetime
from collections import Counter

# ── 시트 식별자 (URL에서 확인된 값) ──
SHEET_ID = os.environ.get("SURVEY_SHEET_ID", "1UAbCrCM0KnnqlDn7MHeHObzMl13Xs3Fp80FwsCMwwt4")
SHEET_GID = os.environ.get("SURVEY_SHEET_GID", "1051173109")

SURVEY_PATH = Path("data/survey.json")

# ── 컬럼 인덱스 매핑 (캡처 확인 기준, 0-base) ──
# A 타임스탬프 / B 인지경로 / C 주문상품 / D 만족도 / E 만족이유
# F 주문경로 / G 상품개선 / H 주문과정개선 / I 성별 / J 나이
# K 휴대폰번호(마스킹대상) / L 기타(정체불명) / M 추천의향 / N 출시희망상품
COL = {
    "timestamp": 0,
    "channel": 1,     # 0. 처음 어떻게 알게 되었나
    "product": 2,     # 1. 주문 상품
    "satisfaction": 3,  # 2. 만족도 (1~5)
    "reason": 4,      # 3. 만족 이유 (주관식)
    "order_path": 5,  # 4. 주문 경로
    "improve_product": 6,  # 5. 상품 개선 (주관식)
    "improve_order": 7,    # 6. 주문과정 개선 (주관식)
    "gender": 8,      # 9-1 성별
    "age": 9,         # 9-2 나이
    "phone": 10,      # 9-3 휴대폰 (마스킹)
    "etc": 11,        # 10. (정체불명 - 일단 보존)
    "recommend": 12,  # 8. 추천 의향
    "wish_product": 13,  # 7. 출시 희망 상품
}

# 설문 전용 추가 불용어 (analyzer.STOPWORDS 위에 얹음)
SURVEY_EXTRA_STOP = {
    "백년화편", "파파공방", "동의", "동의합니", "없음", "없습니다", "없어요",
    "글쎄요", "모름", "모르겠어요", "특별히", "딱히", "그냥", "현재",
    "정도", "부분", "사항", "개선", "필요", "경우", "생각", "있으면",
    "했으면", "좋겠어요", "좋겠습니다", "좋을", "같아요", "거예요",
}


def _mask_phone(raw: str) -> str:
    """휴대폰번호를 010-****-XXXX 형태로 마스킹. 원본은 절대 반환하지 않음."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        head = digits[:3] if len(digits) >= 11 else digits[:3]
        tail = digits[-4:]
        return f"{head}-****-{tail}"
    return "****"  # 형식 불명은 통째 마스킹


def _norm_satisfaction(raw: str):
    """만족도 값을 1~5 정수로. 파싱 실패시 None."""
    if raw is None:
        return None
    m = re.search(r"[1-5]", str(raw))
    return int(m.group()) if m else None


def _parse_timestamp(raw: str) -> str:
    """구글폼 타임스탬프(예: '2024. 6. 12 오후 10:41:16')를 ISO 날짜(YYYY-MM-DD)로.
    실패시 원본 앞부분 반환."""
    if not raw:
        return ""
    s = raw.strip()
    # 흔한 패턴: 2024. 6. 12 ...
    m = re.match(r"(\d{4})[.\s]+(\d{1,2})[.\s]+(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # YYYY-MM-DD 형태
    m2 = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m2:
        y, mo, d = m2.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return s[:10]


def parse_csv(csv_text: str) -> list[dict]:
    """CSV 문자열을 설문 응답 레코드 리스트로 변환. 헤더 행은 건너뜀.
    휴대폰번호는 이 단계에서 마스킹되어 phone 필드에 저장됨 (원본 폐기)."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []
    records = []
    for i, row in enumerate(rows):
        if i == 0:
            continue  # 헤더
        if not any(cell.strip() for cell in row):
            continue  # 빈 행
        def g(key):
            idx = COL[key]
            return row[idx].strip() if idx < len(row) else ""
        rec = {
            "ts": _parse_timestamp(g("timestamp")),
            "channel": g("channel"),
            "product": g("product"),
            "satisfaction": _norm_satisfaction(g("satisfaction")),
            "reason": g("reason"),
            "order_path": g("order_path"),
            "improve_product": g("improve_product"),
            "improve_order": g("improve_order"),
            "gender": g("gender"),
            "age": g("age"),
            "phone": _mask_phone(g("phone")),   # ★ 즉시 마스킹
            "etc": g("etc"),
            "recommend": g("recommend"),
            "wish_product": g("wish_product"),
        }
        records.append(rec)
    return records


def fetch_sheet_csv() -> str:
    """서비스 계정으로 비공개 시트를 CSV로 읽어 문자열 반환.
    GOOGLE_SERVICE_ACCOUNT_JSON 환경변수 필요.
    실패시 예외를 던짐 (호출부에서 처리)."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON 환경변수가 없습니다. "
            "구글 서비스 계정 키를 Railway 환경변수에 등록하세요."
        )
    try:
        sa_info = json.loads(sa_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"서비스 계정 JSON 파싱 실패: {e}")

    # google 라이브러리는 무거우므로 함수 내부 임포트
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    # 시트(워크시트) 이름을 gid로 찾기
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    sheet_name = None
    for sh in meta.get("sheets", []):
        props = sh.get("properties", {})
        if str(props.get("sheetId")) == str(SHEET_GID):
            sheet_name = props.get("title")
            break
    if sheet_name is None:
        # gid 매칭 실패시 첫 번째 시트 사용
        sheet_name = meta["sheets"][0]["properties"]["title"]

    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=sheet_name,
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    values = result.get("values", [])

    # values(2차원 배열) → CSV 문자열로 변환
    out = io.StringIO()
    writer = csv.writer(out)
    for row in values:
        writer.writerow(row)
    return out.getvalue()


def service_account_email() -> str | None:
    """등록된 서비스 계정 이메일 반환 (시트 소유자에게 공유 요청할 대상)."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        return None
    try:
        return json.loads(sa_json).get("client_email")
    except Exception:
        return None


def collect_survey() -> dict:
    """시트를 읽어 파싱·마스킹 후 data/survey.json에 저장. 결과 요약 반환."""
    csv_text = fetch_sheet_csv()
    records = parse_csv(csv_text)
    payload = {
        "records": records,
        "count": len(records),
        "last_updated": datetime.now().isoformat(),
    }
    save_survey(payload)
    return {"count": len(records), "last_updated": payload["last_updated"]}


def save_survey(payload: dict):
    SURVEY_PATH.parent.mkdir(exist_ok=True)
    tmp = SURVEY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SURVEY_PATH)


def load_survey() -> dict:
    if not SURVEY_PATH.exists():
        return {"records": [], "count": 0, "last_updated": None}
    try:
        return json.loads(SURVEY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"records": [], "count": 0, "last_updated": None}


# ── 통계 계산 ──
def _extract_keywords(texts, top_n=15):
    """주관식 텍스트에서 키워드 빈도. analyzer.STOPWORDS + 설문 전용 불용어 적용."""
    try:
        from analyzer import STOPWORDS as BASE_STOP
    except Exception:
        BASE_STOP = set()
    stop = set(BASE_STOP) | SURVEY_EXTRA_STOP
    counter = Counter()
    for text in texts:
        if not text:
            continue
        words = re.findall(r"[가-힣]{2,8}", text)
        for w in words:
            if w not in stop:
                counter[w] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


def compute_survey_stats(payload: dict) -> dict:
    records = payload.get("records", [])
    total = len(records)

    # 만족도 분포
    sat_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    sat_sum, sat_cnt = 0, 0
    for r in records:
        s = r.get("satisfaction")
        if s in sat_dist:
            sat_dist[s] += 1
            sat_sum += s
            sat_cnt += 1
    avg_sat = round(sat_sum / sat_cnt, 2) if sat_cnt else None

    def dist(field):
        c = Counter()
        for r in records:
            v = (r.get(field) or "").strip()
            if v:
                c[v] += 1
        return [{"label": k, "count": v} for k, v in c.most_common()]

    # 기간
    dates = sorted([r["ts"] for r in records if r.get("ts")])
    period = {"from": dates[0] if dates else None, "to": dates[-1] if dates else None}

    return {
        "total": total,
        "period": period,
        "avg_satisfaction": avg_sat,
        "satisfaction_dist": [{"score": k, "count": v} for k, v in sat_dist.items()],
        "channel_dist": dist("channel"),
        "order_path_dist": dist("order_path"),
        "gender_dist": dist("gender"),
        "age_dist": dist("age"),
        "recommend_dist": dist("recommend"),
        "keywords": {
            "reason": _extract_keywords([r.get("reason", "") for r in records]),
            "improve_product": _extract_keywords([r.get("improve_product", "") for r in records]),
            "improve_order": _extract_keywords([r.get("improve_order", "") for r in records]),
            "wish_product": _extract_keywords([r.get("wish_product", "") for r in records]),
        },
        "last_updated": payload.get("last_updated"),
    }
