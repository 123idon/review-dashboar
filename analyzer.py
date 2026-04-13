from datetime import datetime, timedelta
from collections import Counter
import re

STOPWORDS = {
    "이","가","은","는","을","를","의","도","로","으로","에","에서",
    "와","과","이고","고","하고","한","하는","있는","없는","있어요",
    "없어요","해요","합니다","했어요","있습니다","없습니다","그","이것",
    "저","제","너무","정말","진짜","완전","아주","매우","좀","좋은",
    "좋아요","좋고","또","다시","번","번째","개","세트","구매","주문",
    "배송","상품","제품","포장","선물","가격","감사","합니다","했습니다",
    "드립니다","드려요","같아요","같습니다","것","거","때","더","수",
    "잘","못","안","다","처음","다음","입니다","이에요","네요","요",
    "부터","까지","만","라도","라고","하여","하면","하지","하니",
}


def parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%y.%m.%d"):
        try:
            d = datetime.strptime(s[:10], fmt)
            if d.year < 2000:
                d = d.replace(year=d.year + 2000)
            return d
        except ValueError:
            continue
    return None


def extract_keywords(texts: list[str], top_n: int = 5) -> list[dict]:
    counter: Counter = Counter()
    for text in texts:
        words = re.findall(r"[가-힣]{2,6}", text)
        for w in words:
            if w not in STOPWORDS:
                counter[w] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


def compute_stats(reviews: list[dict]) -> dict:
    """하나의 가게 리뷰 목록으로 대시보드용 통계 계산"""
    now = datetime.now()
    yesterday_end = datetime(now.year, now.month, now.day) - timedelta(seconds=1)
    week_start = yesterday_end - timedelta(days=6)

    all_reviews = [r for r in reviews if parse_date(r.get("date", ""))]
    week_reviews = [
        r for r in all_reviews
        if week_start <= parse_date(r["date"]) <= yesterday_end
    ]

    def avg_score(lst):
        if not lst:
            return 0
        return round(sum(r["score"] for r in lst) / len(lst), 1)

    # 별점 분포
    dist = {str(i): 0 for i in range(1, 6)}
    for r in all_reviews:
        s = str(r.get("score", 0))
        if s in dist:
            dist[s] += 1

    # 주간 트렌드 (최근 8주)
    weekly: dict[str, list] = {}
    for r in all_reviews:
        d = parse_date(r["date"])
        if not d:
            continue
        week_key = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        weekly.setdefault(week_key, []).append(r)
    trend = sorted([
        {
            "week": k,
            "count": len(v),
            "avg_score": avg_score(v),
            "negative": sum(1 for r in v if r.get("score", 5) <= 3),
        }
        for k, v in weekly.items()
    ], key=lambda x: x["week"])[-8:]

    # 플랫폼별 통계
    platforms: dict[str, list] = {}
    for r in all_reviews:
        p = r.get("platform", "direct")
        platforms.setdefault(p, []).append(r)
    platform_stats = {
        p: {
            "count": len(lst),
            "avg_score": avg_score(lst),
            "negative": sum(1 for r in lst if r.get("score", 5) <= 3),
        }
        for p, lst in platforms.items()
    }

    # 상품별 통계
    products: dict[str, list] = {}
    for r in all_reviews:
        name = r.get("product", "").strip()
        if name:
            products.setdefault(name, []).append(r)

    week_products: dict[str, list] = {}
    for r in week_reviews:
        name = r.get("product", "").strip()
        if name:
            week_products.setdefault(name, []).append(r)

    def top_products_by_count(prod_map, top_n=3):
        return sorted([
            {
                "product": name,
                "count": len(lst),
                "avg_score": avg_score(lst),
                "negative": sum(1 for r in lst if r.get("score", 5) <= 3),
            }
            for name, lst in prod_map.items()
        ], key=lambda x: -x["count"])[:top_n]

    def top_products_by_negative(prod_map, top_n=3):
        return sorted([
            {
                "product": name,
                "count": len(lst),
                "avg_score": avg_score(lst),
                "negative": sum(1 for r in lst if r.get("score", 5) <= 3),
            }
            for name, lst in prod_map.items()
            if sum(1 for r in lst if r.get("score", 5) <= 3) > 0
        ], key=lambda x: -x["negative"])[:top_n]

    # 키워드 분석 (긍/부정 분리)
    pos_texts = [
        (r.get("content") or r.get("title") or "")
        for r in all_reviews if r.get("score", 0) >= 4
    ]
    neg_texts = [
        (r.get("content") or r.get("title") or "")
        for r in all_reviews if r.get("score", 0) <= 3
    ]
    pos_texts_week = [
        (r.get("content") or r.get("title") or "")
        for r in week_reviews if r.get("score", 0) >= 4
    ]
    neg_texts_week = [
        (r.get("content") or r.get("title") or "")
        for r in week_reviews if r.get("score", 0) <= 3
    ]

    return {
        # 요약 카드
        "total_count": len(all_reviews),
        "total_negative": sum(1 for r in all_reviews if r.get("score", 5) <= 3),
        "week_count": len(week_reviews),
        "week_negative": sum(1 for r in week_reviews if r.get("score", 5) <= 3),
        "avg_score": avg_score(all_reviews),
        # 차트
        "score_distribution": dist,
        "weekly_trend": trend,
        "platform_stats": platform_stats,
        # 상품 분석
        "top_products_all": top_products_by_count(products),
        "top_products_week": top_products_by_count(week_products),
        "top_negative_products": top_products_by_negative(products),
        # 키워드
        "positive_keywords_all": extract_keywords(pos_texts, 5),
        "negative_keywords_all": extract_keywords(neg_texts, 5),
        "positive_keywords_week": extract_keywords(pos_texts_week, 5),
        "negative_keywords_week": extract_keywords(neg_texts_week, 5),
        # 리뷰 목록 (최신순, 최대 200건)
        "reviews": sorted(all_reviews, key=lambda x: x.get("date", ""), reverse=True)[:200],
    }
