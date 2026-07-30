#!/usr/bin/env python3
"""무신사 바지 랭킹 top 100 스냅샷 수집 → data/snapshots/ (스킬 플레이북 준수)"""
import json, re, subprocess, sys, time
from datetime import datetime

REPO = "/Users/2000atelier/workspace/commerce-browser-skill"
URL = ("https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/199"
       "?storeCode=musinsa&gf=A&ageBand=AGE_BAND_ALL&period=REALTIME&categoryCode=003&page=1")

def fetch(url):
    out = subprocess.run(["curl", "-s", "-m", "20", "-A", "Claude-User", url],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)

def parse_korean_number(text):
    m = re.search(r"([\d.]+)(천|만)?", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "천":
        value *= 1000
    elif unit == "만":
        value *= 10000
    return int(value)

def _find_updated_at(data):
    """QUERY_UPDATEDAT 모듈의 information.updatedAt — 동일 랭킹 재수집 판정용."""
    for m in (data.get("data") or {}).get("modules") or []:
        if m.get("type") == "QUERY_UPDATEDAT":
            return (m.get("information") or {}).get("updatedAt")
    return None


def main():
    if datetime.now() >= datetime(2026, 7, 30, 10, 0):
        print('마감(2026-07-30 10:00) 경과 — 수집하지 않음')
        return
    data = fetch(URL)
    items = []
    def walk(obj):
        if isinstance(obj, dict):
            if "info" in obj and "image" in obj and "id" in obj:
                items.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
    # 어댑터 함정: BANNER_COLUMN(광고, 요청마다 바뀜)은 걸러낸다 — PRODUCT_COLUMN + rank만
    items = [i for i in items
             if isinstance(i.get("image"), dict) and i["image"].get("rank")
             and i.get("type", "PRODUCT_COLUMN") == "PRODUCT_COLUMN"]
    items.sort(key=lambda x: x["image"]["rank"])
    items = items[:100]

    records = []
    for it in items:
        info, image = it["info"], it["image"]
        final = info.get("finalPrice")
        ratio = info.get("discountRatio") or 0
        # 랭킹 목록은 정가 미노출(strikethrough는 불리언) — 노출된 판매가·할인율에서 산술 복원
        original = round(final / (1 - ratio / 100)) if (final and ratio) else final
        viewers = buyers = None
        for ai in info.get("additionalInformation") or []:
            text = ai.get("text", "")
            if "보는 중" in text:
                viewers = parse_korean_number(text)
            elif "구매 중" in text:
                buyers = parse_korean_number(text)
        purchase = None
        for lb in image.get("labels") or []:
            t = lb.get("text", "")
            if t.startswith("판매"):
                purchase = parse_korean_number(t)
        records.append({
            "product_id": str(it["id"]),
            "name": info.get("productName"),
            "url": (it.get("onClick") or {}).get("url"),
            "image_url": image.get("url"),
            "brand": info.get("brandName"),
            "category": "바지",
            "price_original": original,
            "price_sale": final,
            "discount_rate": ratio,
            "review_count": None, "rating": None,
            "view_count": None, "view_count_display": None,
            "purchase_count": purchase, "purchase_count_display": None,
            "like_count": None,
            "viewers_now": viewers, "buyers_now": buyers,
            "sold_out": bool(info.get("isSoldOut", False)),
            "rank": image["rank"],
        })

    now = datetime.now()
    path = f"{REPO}/data/snapshots/musinsa-ranking-바지-{now.strftime('%Y%m%d-%H%M')}.json"
    doc = {
        "meta": {
            "site": "musinsa", "story": "ranking-snapshot", "target": "바지",
            "collected_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "item_count": len(records), "source_total": None, "incomplete": False,
            "notes": [
                "updatedAt(원본 갱신 시각, epoch ms): %s" % _find_updated_at(data),
                "경로 A: sections/199 + categoryCode=003, period=REALTIME (요청 1회, 102건 중 top 100)",
                "price_original은 랭킹 목록 미노출 — 노출된 finalPrice·discountRatio에서 산술 복원",
                "purchase_count는 '판매 N개' 배지의 반올림 노출값(천/만 변환)",
                "review_count·rating·like_count는 랭킹 목록 미노출 → null",
            ],
        },
        "items": records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"저장: {path} ({len(records)}건)")

if __name__ == "__main__":
    main()
