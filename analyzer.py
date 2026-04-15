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
    "조회","삭제","수정","목록","추천","신고","이전글","다음글",
    "비밀번호","입력하세요","삭제하려면","회원에게만","댓글","작성",
    "권한","이전","다음","관련","보기","번호","상품명","작성자","작성일",
    "리뷰","후기","사용","구매후기","평점","등록된","네이버","페이",
    "구매평","브이리뷰","작성된","입니다","쇼핑","스토어","결제",
    "창억떡","명가삼대떡집","명가","창억","all","rights","reserved",
    "copyright","https","www","com","kr",
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
        # 네이버페이 구매평 패턴 제거
        text = re.sub(r"\d{4}-\d{2}-\d{2}[^\n]*등록된[^\n]*구매평[^\n]*", "", text)
        text = re.sub(r"\(브이리뷰[^)]*\)", "", text)
        words = re.findall(r"[가-힣]{2,6}", text)
        for w in words:
            if w not in STOPWORDS:
                counter[w] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


def compute_stats(reviews: list[dict]) -> dict:
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
        return round(sum(r["score"] for r in lst if r.get("score", 0) > 0) / max(1, sum(1 for r in lst if r.get("score", 0) > 0)), 1)

    dist = {str(i): 0 for i in range(1, 6)}
    for r in all_reviews:
        s = str(r.get("score", 0))
        if s in dist:
            dist[s] += 1

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
            "negative": sum(1 for r in v if 0 < r.get("score", 5) <= 3),
        }
        for k, v in weekly.items()
    ], key=lambda x: x["week"])[-8:]

    platforms: dict[str, list] = {}
    for r in all_reviews:
        p = r.get("platform", "direct")
        platforms.setdefault(p, []).append(r)
    platform_stats = {
        p: {
            "count": len(lst),
            "avg_score": avg_score(lst),
            "negative": sum(1 for r in lst if 0 < r.get("score", 5) <= 3),
        }
        for p, lst in platforms.items()
    }

    products: dict[str, list] = {}
    for r in all_reviews:
        name = r.get("product", "").strip()
        if name and "rights" not in name.lower() and "reserved" not in name.lower() and len(name) > 4:
            products.setdefault(name, []).append(r)

    week_products: dict[str, list] = {}
    for r in week_reviews:
        name = r.get("product", "").strip()
        if name and "rights" not in name.lower() and len(name) > 4:
            week_products.setdefault(name, []).append(r)

    def top_products_by_count(prod_map, top_n=3):
        return sorted([
            {
                "product": name,
                "count": len(lst),
                "avg_score": avg_score(lst),
                "negative": sum(1 for r in lst if 0 < r.get("score", 5) <= 3),
            }
            for name, lst in prod_map.items()
        ], key=lambda x: -x["count"])[:top_n]

    def top_products_by_negative(prod_map, top_n=3):
        return sorted([
            {
                "product": name,
                "count": len(lst),
                "avg_score": avg_score(lst),
                "negative": sum(1 for r in lst if 0 < r.get("score", 5) <= 3),
            }
            for name, lst in prod_map.items()
            if sum(1 for r in lst if 0 < r.get("score", 5) <= 3) > 0
        ], key=lambda x: -x["negative"])[:top_n]

    valid_reviews = [r for r in all_reviews if r.get("score", 0) > 0]
    pos_texts = [(r.get("content") or "") for r in valid_reviews if r.get("score", 0) >= 4]
    neg_texts = [(r.get("content") or "") for r in valid_reviews if r.get("score", 0) <= 3]
    pos_texts_week = [(r.get("content") or "") for r in week_reviews if r.get("score", 0) >= 4]
    neg_texts_week = [(r.get("content") or "") for r in week_reviews if r.get("score", 0) <= 3]

    total_neg = sum(1 for r in all_reviews if 0 < r.get("score", 5) <= 3)
    week_neg = sum(1 for r in week_reviews if 0 < r.get("score", 5) <= 3)

    return {
        "total_count": len(all_reviews),
        "total_negative": total_neg,
        "week_count": len(week_reviews),
        "week_negative": week_neg,
        "avg_score": avg_score(valid_reviews),
        "score_distribution": dist,
        "weekly_trend": trend,
        "platform_stats": platform_stats,
        "top_products_all": top_products_by_count(products),
        "top_products_week": top_products_by_count(week_products),
        "top_negative_products": top_products_by_negative(products),
        "positive_keywords_all": extract_keywords(pos_texts, 5),
        "negative_keywords_all": extract_keywords(neg_texts, 5),
        "positive_keywords_week": extract_keywords(pos_texts_week, 5),
        "negative_keywords_week": extract_keywords(neg_texts_week, 5),
        "reviews": sorted(all_reviews, key=lambda x: x.get("date", ""), reverse=True)[:500],
    }
