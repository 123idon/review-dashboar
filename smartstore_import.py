"""Validate and merge seller-exported reviews without deleting historical data."""
import math
import re
from datetime import date


def validate_reviews(reviews):
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("후기 데이터가 비어 있습니다. 기존 데이터는 변경하지 않았습니다.")
    for i, row in enumerate(reviews, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{i}번째 후기 형식 오류")
        value = row.get("date", "")
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{i}번째 후기 날짜 형식 오류")
        date.fromisoformat(value)
        score = row.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 1 <= score <= 5:
            raise ValueError(f"{i}번째 후기 평점 오류")
        for key in ("content", "author", "product"):
            if not isinstance(row.get(key, ""), str):
                raise ValueError(f"{i}번째 후기 {key} 형식 오류")
        if not row.get("content", "").strip():
            raise ValueError(f"{i}번째 후기 내용이 비어 있습니다")
        if row.get("platform") not in ("naver", "smartstore"):
            raise ValueError(f"{i}번째 후기 플랫폼 오류")
    return reviews


def legacy_key(row):
    # Keep the dashboard's existing identity policy; product is not an identity.
    return (row.get("author", ""), row.get("date", ""), row.get("content", "")[:100])


def review_id(row):
    return str(row.get("review_no") or "").strip()


def merge_reviews(existing, incoming):
    validate_reviews(incoming)
    if not isinstance(existing, list) or any(not isinstance(r, dict) for r in existing):
        raise ValueError("기존 후기 파일 형식 오류. 덮어쓰기를 중단했습니다.")
    merged = [dict(r) for r in existing]
    ids = {review_id(r): i for i, r in enumerate(merged) if review_id(r)}
    keys = {legacy_key(r): i for i, r in enumerate(merged)}
    added = updated = 0
    for row in incoming:
        rid, key = review_id(row), legacy_key(row)
        index = ids.get(rid) if rid else None
        if index is None:
            index = keys.get(key)
        if index is None:
            index = len(merged)
            merged.append(dict(row))
            added += 1
        else:
            old = merged[index]
            combined = dict(old)
            # Exports without images or IDs must not erase previously known fields.
            combined.update({k: v for k, v in row.items() if v not in (None, "", [])})
            if combined != old:
                updated += 1
            merged[index] = combined
        keys[key] = index
        if rid:
            ids[rid] = index
    merged.sort(key=lambda r: r.get("date", ""), reverse=True)
    return merged, {"received": len(incoming), "added": added, "updated": updated,
                    "imported": len(merged), "previous": len(existing), "mode": "merge"}
