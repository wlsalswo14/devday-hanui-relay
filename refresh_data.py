"""Download pinned public references and rebuild the small curated demo library.

No AI, API keys or private DB. Only allowlisted official URLs; raw downloads stay local.
Run python refresh_data.py. A failed download preserves the existing seed.
"""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
ORIGIN_URL = "https://nikom.or.kr/board/boardFile/download/106/565789/36154.do"
ORIGIN_HASH = "86bc628e072da11fcdbf4dedde559e7ccc67a7fda6c9a34b8d467c7d35ae3ab0"
ORIGINS = {
    "마황": "초마황·중마황·목적마황의 초질경", "복령": "복령의 균핵",
    "숙지황": "지황 뿌리의 포제 가공품", "백출": "삽주 또는 백출의 뿌리줄기",
    "육계": "육계의 줄기껍질", "천궁": "천궁 또는 중국천궁의 뿌리줄기",
    "용안육": "용안의 헛씨껍질", "작약": "작약 또는 동속근연식물의 뿌리",
    "산사": "산사나무 및 변종의 익은 열매", "갈근": "칡의 뿌리",
    "향부자": "향부자의 뿌리줄기", "후박": "일본목련·후박·요엽후박의 줄기껍질",
    "시호": "시호 또는 변종의 뿌리", "산약": "마 또는 참마의 주피를 제거한 뿌리줄기",
    "맥문동": "맥문동 또는 소엽맥문동 뿌리의 팽대부", "계지": "육계의 어린가지",
    "당귀": "참당귀의 뿌리", "황련": "황련·중국황련·삼각엽황련·운련의 뿌리줄기",
    "사인": "녹각사 또는 양춘사의 익은 열매나 씨 덩어리", "택사": "질경이택사의 덩이줄기",
    "길경": "도라지의 뿌리", "황금": "속썩은풀의 뿌리", "대추": "대추나무 또는 보은대추나무의 익은 열매",
    "구기자": "구기자나무 또는 영하구기의 열매", "인삼": "인삼의 뿌리",
    "진피": "귤나무 또는 감귤나무의 익은 열매껍질 (KP 품목)",
    "오미자": "오미자의 익은 열매", "박하": "박하의 지상부", "생강": "생강의 신선한 뿌리줄기",
    "산조인": "산조의 익은 씨",
}

FACTS = [
    ("licorice-root", "감초: 연구 근거와 일반 안전성", "herb", ["감초", "안전성", "상호작용"],
     "NCCIH는 감초의 특정 질환 사용을 명확히 뒷받침하는 고품질 근거가 부족하다고 설명한다. 글리시리진은 부정맥 등 심각한 부작용을 일으킬 수 있고 코르티코스테로이드와의 상호작용이 보고됐다. 개인별 복용 여부는 이 자료로 결정하지 않는다."),
    ("astragalus", "황기: 연구 근거와 일반 안전성", "herb", ["황기", "안전성", "상호작용"],
     "NCCIH는 황기가 건강 상태에 유용한지 판단할 충분히 신뢰할 과학적 근거가 없다고 설명한다. 면역억제제와 상호작용할 수 있으며 자가면역질환·임신 중 안전성에 주의가 필요하다. 개별 연구 소개는 개인별 치료 추천이 아니다."),
    ("ginger", "생강: 원료와 일반 안전성", "herb", ["생강", "안전성", "상호작용"],
     "생강의 뿌리줄기는 식품과 건강 목적에 사용된다. NCCIH는 생강 제품의 경구 사용에서 복부 불편감·속쓰림·설사 등의 부작용 가능성과 약물 병용 전 상담의 필요성을 설명한다. 식품과 보충제 연구의 결과를 동일시하지 않는다."),
    ("asian-ginseng", "인삼: 일반 안전성과 근거의 범위", "herb", ["인삼", "안전성", "상호작용"],
     "NCCIH는 아시아 인삼 연구가 대체로 소규모·단기간이며 불면이 흔한 부작용이라고 설명한다. 약물과 상호작용 가능성이 있고 임신·수유 중 안전성 정보에 한계가 있다. 연구 소개를 개인별 피로 치료나 자가 복용 권고로 해석하지 않는다."),
    ("stress", "스트레스와 생활 관찰", "lifestyle", ["스트레스", "긴장", "수면", "생활관리"],
     "NCCIH는 스트레스를 삶의 도전에 대한 신체·정서 반응으로 설명한다. 장기간 스트레스는 수면·소화 등의 문제와 연관될 수 있으며 이완·마음챙김 등의 접근은 연구와 적용 범위를 따져 읽어야 한다. 일상의 변화와 불편감을 기록할 수 있지만 앱 기록은 진단이나 치료 효과 검증이 아니다."),
]


def download(url, filename):
    folder = ROOT / "data" / "source-documents"
    folder.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "HanuiDemo/1.0 (official public reference download)"})
    with urlopen(req, timeout=30) as response:
        blob = response.read(8_000_001)
        if len(blob) > 8_000_000:
            raise ValueError("Reference exceeds download limit")
    (folder / filename).write_bytes(blob)
    return {"url": url, "file": filename, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}


def main():
    downloads = []
    pinned = ROOT / "data" / "source-documents" / "herb-origins.pdf"
    if not pinned.exists():
        downloads.append(download(ORIGIN_URL, "herb-origins.pdf"))
    if hashlib.sha256(pinned.read_bytes()).hexdigest() != ORIGIN_HASH:
        raise ValueError("The origin reference changed; review it before rebuilding the library")
    records = json.loads((ROOT / "data" / "knowledge.seed.json").read_text(encoding="utf-8-sig"))
    records = [r for r in records if not r["id"].startswith(("curated-origin-", "nccih-"))]
    for index, (name, origin) in enumerate(ORIGINS.items(), 1):
        records.append({"id": f"curated-origin-{index:03d}", "title": f"{name}: 공정서상 기원·약용 부위",
            "category": "herb", "tags": [name, "기원", "약용부위", "한약재"],
            "body": f"한국한의약진흥원의 다빈도 한약재 목록은 {name}의 기원을 {origin}로 기재한다. 원료 동정에 관한 정보이며 효능·용량을 안내하지 않는다.",
            "source_url": ORIGIN_URL, "publisher": "한국한의약진흥원",
            "evidence_level": "2025년 공고 첨부 공정서 기원 목록의 자체 요약",
            "limitations": "품목 기원 정보는 복용 안전성이나 개인별 적합성의 근거가 아니다. 최신 공정서와 구별되며 자가 복용·증상별 약재 선택에 사용할 수 없다.",
            "retrieved_at": "2026-10-09"})
    for slug, title, category, tags, body in FACTS:
        url = "https://www.nccih.nih.gov/health/" + slug
        downloads.append(download(url, "nccih-" + slug + ".html"))
        records.append({"id": "nccih-" + slug, "title": title, "category": category, "tags": tags,
            "body": body, "source_url": url, "publisher": "미국 NIH 국립보완통합건강센터 (NCCIH)",
            "evidence_level": "공공기관 일반 근거·안전성 안내의 자체 한국어 요약",
            "limitations": "한국의 허가사항이나 개인별 치료 지침이 아니다. 일반 정보이며 복용·중단·용량 추천에 사용할 수 없다.",
            "retrieved_at": "2026-10-09"})
    (ROOT / "data" / "knowledge.seed.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = ROOT / "data" / "sources.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["knowledge_record_count"] = len(records)
    manifest.pop("record_count", None)
    manifest["expanded_downloads"] = downloads
    manifest["curation"] = "30 additional herbal origin summaries reviewed against pinned 2025 NIKOM PDF; 5 NCCIH pages downloaded and summarized. No personal prescriptions."
    manifest["records"] = [{k: r[k] for k in ("id", "title", "source_url", "publisher", "evidence_level", "retrieved_at")} for r in records]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Downloaded {len(downloads)} public references; knowledge records: {len(records)}")


if __name__ == "__main__":
    main()
