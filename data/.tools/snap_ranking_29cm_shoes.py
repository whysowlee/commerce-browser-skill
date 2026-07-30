#!/usr/bin/env python3
"""29CM 여성슈즈 랭킹 top 100 스냅샷 수집 → data/snapshots/ (스킬 플레이북 준수)

스토리 C-1. 어댑터(references/29cm.md §2-1)의 확정 기준을 따른다:
  HOURLY(실시간) + POPULARITY(인기순) + gender=ALL, age=ALL, 요청 1회.
한 스냅샷은 한 시점이어야 하므로 페이지를 나눠 받지 않는다 — size=100 한 방이다.
"""
import json
import subprocess
import time
from datetime import datetime

REPO = "/Users/2000atelier/workspace/commerce-browser-skill"
API = "https://display-bff-api.29cm.co.kr/api/v1/plp/best/items"

TARGET = "여성슈즈"
LARGE_ID = 270100100  # 여성슈즈 (2026-07-30 확인: /best-products 칩 클릭 → categoryLargeCode)

BODY = {
    "pageRequest": {"page": 1, "size": 100},
    "userSegment": {"gender": "ALL", "age": "ALL"},
    "facets": {
        "categoryFacetInputs": [{"largeId": LARGE_ID}],
        "periodFacetInput": {"type": "HOURLY", "order": "DESC"},
        "rankingFacetInput": {"type": "POPULARITY"},
    },
}


def fetch():
    """실패하면 간격을 늘리며 2번까지 다시 시도한다(스킬 §지켜야 할 규칙)."""
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 * attempt)
        try:
            out = subprocess.run(
                ["curl", "-s", "-m", "20", "-A", "Claude-User",
                 "-H", "Content-Type: application/json",
                 "-X", "POST", API, "-d", json.dumps(BODY)],
                capture_output=True, text=True, check=True,
            )
            data = json.loads(out.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            last = exc
            continue
        # 함정: 필드명을 틀리면 400이 아니라 200 + 빈 목록이 온다
        if (data.get("data") or {}).get("list"):
            return data
        last = RuntimeError("빈 목록 — 요청 형식을 의심할 것")
    raise last


def category_name(props):
    """카테고리 이름은 itemEvent.eventProperties에 그대로 실려 온다.

    어댑터의 meta description 해석 경로가 필요 없다(2026-07-30 실측:
    large/middle 100%, small 94% 채워짐). small이 비면 middle → large로 내린다.
    """
    for key in ("smallCategoryName", "middleCategoryName", "largeCategoryName"):
        value = props.get(key)
        if value:
            return value
    return None


def main():
    data = fetch()
    entries = data["data"]["list"]

    records = []
    seen = set()
    off_category = 0
    for entry in entries:
        info = entry["itemInfo"]
        props = (entry.get("itemEvent") or {}).get("eventProperties") or {}
        item_id = str(entry["itemId"])
        # 29CM 목록은 중복이 나올 수 있다(어댑터). 랭킹 스냅샷에 중복은 허용되지 않는다.
        if item_id in seen:
            continue
        seen.add(item_id)
        if props.get("largeCategoryNo") != LARGE_ID:
            off_category += 1
        rate = info.get("saleRate")
        if isinstance(rate, float) and rate.is_integer():
            rate = int(rate)
        records.append({
            "product_id": item_id,
            "name": info.get("productName"),
            "url": "https://www.29cm.co.kr/products/%s" % item_id,
            "image_url": info.get("thumbnailUrl"),
            "brand": info.get("brandName"),
            "category": category_name(props),
            "price_original": info.get("originalPrice"),
            "price_sale": info.get("displayPrice"),  # 쿠폰적용가 — sellPrice가 아니다
            "discount_rate": rate,                    # saleRate는 displayPrice 기준이라 짝이 맞는다
            "review_count": info.get("reviewCount"),
            "rating": info.get("reviewScore"),        # 0~5 그대로
            "view_count": None, "view_count_display": None,
            "purchase_count": None, "purchase_count_display": None,
            "like_count": info.get("likeCount"),
            "viewers_now": None, "buyers_now": None,  # 29CM에는 실시간 지표가 없다
            "sold_out": bool(info.get("isSoldOut", False)),
            "rank": len(records) + 1,
        })

    now = datetime.now()
    path = "%s/data/snapshots/29cm-ranking-%s-%s.json" % (
        REPO, TARGET, now.strftime("%Y%m%d-%H%M"))
    doc = {
        "meta": {
            "site": "29cm", "story": "ranking-snapshot", "target": TARGET,
            "collected_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "item_count": len(records), "source_total": None, "incomplete": False,
            "notes": [
                "경로 A: BEST API(display-bff-api) categoryFacetInputs.largeId=%d, "
                "HOURLY + POPULARITY, gender=ALL age=ALL (요청 1회, size=100)" % LARGE_ID,
                "source_total은 null — 29CM BEST API는 총계를 주지 않는다(hasNext만). "
                "랭킹 top 100이 대상이라 카탈로그 전량이 기준이 아니다",
                "카테고리 이름은 itemEvent.eventProperties에서 직접 왔다 "
                "(small 미노출이면 middle → large 순으로 폴백)",
                "여성슈즈 랭킹이지만 주 카테고리가 여성슈즈가 아닌 상품이 %d건 섞여 있다 "
                "— 유니섹스 교차 노출이며 사이트가 이 목록에 실제로 올린 것이다" % off_category,
                "price_sale은 쿠폰적용가(displayPrice)다. sellPrice와 다른 상품이 다수이며 "
                "discount_rate(saleRate)도 같은 기준이다",
                "view_count·purchase_count·viewers_now·buyers_now는 29CM 미노출 → null",
                "화면 기본값은 개인화(gender=F&age=30)라 비로그인 화면 순서와는 다를 수 있다 "
                "— 축적 기준은 gender=ALL·age=ALL이다",
            ],
        },
        "items": records,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
    print("저장: %s (%d건)" % (path, len(records)))


if __name__ == "__main__":
    main()
