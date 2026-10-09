"""Rebuild the pinned, public-domain classical-text demo corpus.

Run ``python refresh_classics.py`` from any directory. The script downloads only
the exact Wikisource revisions listed below, verifies each raw wikitext SHA-256,
then writes data/classics.seed.json and data/classics.manifest.json. It never
touches the modern knowledge seed or uses an AI/API service.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
API = "https://zh.wikisource.org/w/api.php"
SNAPSHOT_DATE = "2026-10-09"
LICENSE = "Public domain original; Wikisource transcription CC BY-SA 4.0 (also GFDL)"
LIMITATIONS = (
    "고대 의서의 역사적 기록입니다. 현대 임상 효능, 진단 또는 치료를 입증하지 않으며, "
    "개인별 약재 선택이나 복용 지침으로 사용할 수 없습니다."
)

# The Dongui root revision is kept as the table-of-contents/source anchor. The
# other entries are the exact transcribed pages used in the corpus.
PAGES = [
    {"key": "dongui-root", "title": "東醫寶鑒", "pageid": 505382, "revid": 2245890,
     "timestamp": "2022-12-21T17:41:44Z", "sha256": "a94fb88e9f5f4ee212d1ff007919fae6323cc66937dafc2fd074d7a70e7134fa",
     "include": False},
    {"key": "dongui-preface", "title": "東醫寶鑒/序", "pageid": 1116135, "revid": 2346994,
     "timestamp": "2023-12-21T13:44:22Z", "sha256": "12182b9a458f70b562b8ed2da832a275cf5c6d06749ef937e43ff0d94b775b96",
     "include": True},
    {"key": "dongui-giprye", "title": "東醫寶鑒/集例", "pageid": 1116138, "revid": 2199215,
     "timestamp": "2022-12-02T04:57:05Z", "sha256": "c22f97d6ce64521008507a8b808611f146688b9dd34ed3bc707e8b3b73bcfa70",
     "include": True},
    {"key": "dongui-inner-1", "title": "東醫寶鑒/內景篇一", "pageid": 1116137, "revid": 2308308,
     "timestamp": "2023-08-23T02:46:07Z", "sha256": "47417743666da052d4c3e11c19686860ea0dc0ce8ec6f7df90b0d5999be9d48e",
     "include": True},
    {"key": "huangdi-suwen-1", "title": "黃帝內經/素問第一卷", "pageid": 16902, "revid": 2083230,
     "timestamp": "2021-10-17T14:30:13Z", "sha256": "f1bb91f185adfaf2c3f9d06d76bc7b1cf6ac152d85c1d6ac377376733d176c4c",
     "include": True},
    {"key": "shennong", "title": "神農本草經", "pageid": 56728, "revid": 2490492,
     "timestamp": "2024-11-13T01:20:36Z", "sha256": "a7ef706e8b3255c20582620a882adbc8b3ef1d3fbb5d9c00ba0b8b8ceb5c18d1",
     "include": True},
]

BY_KEY = {page["key"]: page for page in PAGES}

# Hangul search tags for source headings where a stable, familiar Korean name
# is available. These are name mappings, not efficacy claims or prescriptions.
HERB_KO = {
    "人參": "인삼", "甘草": "감초", "黃耆": "황기", "黃芪": "황기",
    "大黃": "대황", "當歸": "당귀", "芍藥": "작약", "白芍": "백작약",
    "赤芍": "적작약", "柴胡": "시호", "麥門冬": "맥문동", "天門冬": "천문동",
    "五味子": "오미자", "防風": "방풍", "黃連": "황련", "黃芩": "황금",
    "茯苓": "복령", "桂枝": "계지", "麻黃": "마황", "附子": "부자",
    "半夏": "반하", "生薑": "생강", "乾薑": "건강", "枳實": "지실",
    "厚朴": "후박", "白朮": "백출", "朮": "출", "牛膝": "우슬",
    "車前子": "차전자", "木香": "목향", "薯蕷": "서여·산약", "山藥": "산약",
    "薏苡仁": "의이인·율무", "澤瀉": "택사", "遠志": "원지", "石斛": "석곡",
    "黃精": "황정", "牡丹": "모란피", "牡丹皮": "목단피", "豬苓": "저령",
    "白芷": "백지", "五加皮": "오가피", "丹參": "단삼", "決明子": "결명자",
    "蛇床子": "사상자", "地榆": "지유", "續斷": "속단", "狗脊": "구척",
    "防己": "방기", "羌活": "강활", "獨活": "독활", "細辛": "세신",
    "木通": "목통", "通草": "통초", "連翹": "연교", "桔梗": "길경",
    "石膏": "석고", "知母": "지모", "苦參": "고삼", "龍膽": "용담",
    "地黃": "지황", "乾地黃": "건지황", "熟地黃": "숙지황", "菊花": "국화",
    "菖蒲": "창포", "蘆根": "노근", "枸杞": "구기자", "枸杞子": "구기자",
    "大棗": "대추", "棗": "대추", "龍眼": "용안", "桂": "계피",
    "橘皮": "진피", "陳皮": "진피", "桑白皮": "상백피", "桑根白皮": "상백피",
    "葶藶": "정력자", "白頭翁": "백두옹", "紫草": "자초", "敗醬": "패장",
    "白英": "백영", "營實": "영실", "水萍": "부평초", "蒲黃": "포황",
    "香蒲": "향포", "漏蘆": "누로", "飛廉": "비렴", "旋花": "선화",
    "蘭草": "난초", "地膚子": "지부자", "海藻": "해조", "澤蘭": "택란",
    "天名精": "천명정", "白蒿": "백호", "赤箭": "적전", "茜根": "천초근",
    "茜草": "천초", "黃精": "황정", "玉泉": "옥천", "雲母": "운모",
    "石鍾乳": "종유석", "滑石": "활석", "石膽": "석담", "空青": "공청",
    "曾青": "증청", "禹餘糧": "우여량", "白石英": "백석영", "紫石英": "자석영",
    "赤石脂": "적석지", "白青": "백청", "扁青": "편청", "豬苓": "저령",
}

DONGUI_HEADING_KO = {
    "身形": "몸의 형체", "形氣之始": "형체와 기의 시작", "胎孕之始": "태아의 형성",
    "四大成形": "사대와 몸의 형성", "人氣盛衰": "사람의 기가 성하고 쇠함",
    "形體之始": "형체의 기원", "形氣定壽夭": "형기와 수명에 대한 고전 설명",
    "保養精氣神": "정·기·신을 보양한다는 고전 논의", "養性延年藥餌": "양생 약물에 대한 고전 기록",
    "導引法": "도인법에 관한 기록", "修養法": "수양법에 관한 기록", "按摩法": "안마법에 관한 기록",
    "養生禁忌": "양생 금기에 관한 기록", "精": "정에 관한 고전 설명", "氣": "기에 관한 고전 설명",
    "神": "신에 관한 고전 설명", "補精藥餌": "정(精) 보양 약물·음식 기록",
    "單方": "단방 기록", "人參固本丸": "인삼고본환",
    "濕痰滲爲遺精": "습담과 유정에 관한 고전 기록", "導引法": "도인법 기록", "鍼灸法": "침구법 기록",
}

HUANGDI_TITLES = {
    "上古天真論篇第一": ("상고천진론", "고대인의 장수와 생활, 생애 단계에 관한 황제·기백의 문답을 기록한다."),
    "四氣調神大論篇第二": ("사기조신대론", "봄·여름·가을·겨울의 계절 변화와 생활 원칙을 연결하는 고전의 계절론을 서술한다."),
    "生氣通天論篇第三": ("생기통천론", "천지·음양과 몸의 기운이 서로 통한다는 고전 이론을 설명한다."),
    "金匱真言論篇第四": ("금궤진언론", "방위·계절·색·장부의 상응 관계를 다루는 고전 분류를 서술한다."),
}


def fetch_revisions() -> dict[str, dict]:
    ids = "|".join(str(page["revid"]) for page in PAGES)
    url = f"{API}?action=query&format=json&prop=revisions&rvprop=ids%7Ctimestamp%7Ccontent&rvslots=main&revids={ids}"
    request = Request(url, headers={"User-Agent": "HanuiRelayClassics/1.0 (pinned public-source corpus)"})
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    by_revision = {}
    for page in payload.get("query", {}).get("pages", {}).values():
        revision = page.get("revisions", [{}])[0]
        if not revision:
            continue
        by_revision[str(revision.get("revid"))] = {
            "title": page.get("title", ""),
            "pageid": page.get("pageid"),
            "revision": revision,
            "wikitext": revision.get("slots", {}).get("main", {}).get("*"),
        }
    found = {}
    for spec in PAGES:
        item = by_revision.get(str(spec["revid"]))
        if not item or item["wikitext"] is None:
            raise ValueError(f"Pinned Wikisource revision {spec['revid']} is unavailable")
        raw = item["wikitext"]
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if item["pageid"] != spec["pageid"] or item["title"] != spec["title"]:
            raise ValueError(f"Pinned revision identity changed for {spec['key']}")
        if digest != spec["sha256"]:
            raise ValueError(f"Pinned wikitext hash mismatch for {spec['key']}: {digest}")
        found[spec["key"]] = {**spec, "wikitext": raw, "sha256_verified": digest}
    return found


def source_url(page: dict) -> str:
    title = quote(page["title"].replace(" ", "_"), safe="()_/-")
    return f"https://zh.wikisource.org/wiki/{title}?oldid={page['revid']}"


def strip_templates(value: str) -> str:
    out = []
    depth = 0
    i = 0
    while i < len(value):
        if value.startswith("{{", i):
            depth += 1
            i += 2
        elif value.startswith("}}", i) and depth:
            depth -= 1
            i += 2
        else:
            if depth == 0:
                out.append(value[i])
            i += 1
    return "".join(out)


def source_content(raw: str, onlyinclude: bool = True) -> str:
    value = re.sub(r"(?s)<!--.*?-->", "", raw)
    if onlyinclude:
        match = re.search(r"(?is)<onlyinclude>(.*?)</onlyinclude>", value)
        if match:
            value = match.group(1)
    value = re.sub(r"(?is)<ref\b[^>]*/\s*>", "", value)
    value = re.sub(r"(?is)<ref\b[^>]*>.*?</ref\s*>", "", value)
    value = strip_templates(value)
    value = re.sub(r"(?is)</?(?:onlyinclude|noinclude|includeonly|poem)\b[^>]*>", "", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    return value


def plain_line(value: str) -> str:
    value = re.sub(r"-\{([^{}]*?)\}-", r"\1", value)
    value = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[(?:https?://\S+)\s+([^\]]+)\]", r"\1", value)
    value = re.sub(r"'{2,3}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"[ \t\u3000]+", " ", value).strip()


def split_headed_text(raw: str, onlyinclude: bool = True) -> list[tuple[list[str], str]]:
    value = source_content(raw, onlyinclude=onlyinclude)
    blocks: list[tuple[list[str], list[str]]] = []
    path: list[str] = []
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(line for line in lines if line).strip()
        if text:
            blocks.append((path.copy(), text))
        lines.clear()

    for raw_line in value.splitlines():
        heading = re.match(r"^\s*(={2,6})\s*(.*?)\s*\1\s*$", raw_line)
        if heading:
            flush()
            depth = len(heading.group(1)) - 2
            title = plain_line(heading.group(2))
            path = path[:depth] + [title]
            continue
        text = plain_line(raw_line)
        if text:
            lines.append(text)
    flush()
    return blocks


def split_long_text(text: str, maximum: int = 950) -> list[str]:
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    atoms: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= maximum:
            atoms.append(paragraph)
            continue
        parts = re.split(r"(?<=[。！？；])", paragraph)
        buffer = ""
        for part in parts:
            if not part:
                continue
            if buffer and len(buffer) + len(part) > maximum:
                atoms.append(buffer)
                buffer = ""
            buffer += part
        if buffer:
            atoms.append(buffer)

    packed: list[str] = []
    buffer = ""
    for atom in atoms:
        candidate = f"{buffer}\n{atom}" if buffer else atom
        if buffer and len(candidate) > maximum:
            packed.append(buffer)
            buffer = atom
        else:
            buffer = candidate
    if buffer:
        packed.append(buffer)
    return packed


def base_record(record_id: str, title: str, category_tags: list[str], body: str,
                summary: str, book: str, section: str, location: str,
                page: dict, evidence: str) -> dict:
    return {
        "id": record_id,
        "title": title,
        "category": "classical",
        "tags": list(dict.fromkeys(["고문헌", "원문", *category_tags])),
        "body": body,
        "summary": summary,
        "book": book,
        "section": section,
        "location": location,
        "source_url": source_url(page),
        "source_revision": str(page["revid"]),
        "license": LICENSE,
        "source_id": f"zh-wikisource:{page['pageid']}@{page['revid']}",
        "publisher": "중국 위키문고(Wikisource) 기여자 전사",
        "evidence_level": evidence,
        "limitations": LIMITATIONS,
        "retrieved_at": SNAPSHOT_DATE,
    }


def simple_page_records(page: dict, book: str, section: str, record_id: str,
                        title: str, tags: list[str], summary: str) -> list[dict]:
    text = "\n".join(body for _, body in split_headed_text(page["wikitext"]))
    chunks = split_long_text(text)
    result = []
    for index, chunk in enumerate(chunks, 1):
        location = section if len(chunks) == 1 else f"{section} · 원문 구간 {index}/{len(chunks)}"
        result.append(base_record(
            f"{record_id}-{index:03d}", title if len(chunks) == 1 else f"{title} · {index}",
            tags, chunk, summary, book, section, location, page,
            "역사적 고전 원문 전사 및 한국어 독해 요약",
        ))
    return result


def dongui_records(pages: dict[str, dict]) -> list[dict]:
    result: list[dict] = []
    result.extend(simple_page_records(
        pages["dongui-preface"], "동의보감 (東醫寶鑒)", "序 · 이정구 서문", "dongui-preface",
        "동의보감 서문 (이정구) 원문", ["동의보감", "편찬서문", "이정구"],
        "허준의 동의보감 편찬을 알리는 서문으로, 의서를 모아 백성을 돕고 의학 지식을 정리하려는 취지를 서술한다.",
    ))
    result.extend(simple_page_records(
        pages["dongui-giprye"], "동의보감 (東醫寶鑒)", "集例 · 편찬 예례", "dongui-giprye",
        "동의보감 집례 원문", ["동의보감", "편찬원칙", "자료구성"],
        "집례는 책의 편제와 자료를 모은 원칙, 처방 기록에 관한 편찬 기준을 설명한다.",
    ))
    page = pages["dongui-inner-1"]
    blocks = split_headed_text(page["wikitext"])
    grouped: list[dict] = []
    current_parts: list[str] = []
    current_locations: list[str] = []
    current_subjects: list[str] = []
    current_size = 0
    current_root = ""

    def flush_inner() -> None:
        nonlocal current_parts, current_locations, current_subjects, current_size, current_root
        if current_parts:
            grouped.append({
                "body": "\n\n".join(current_parts),
                "locations": list(dict.fromkeys(current_locations)),
                "subjects": list(dict.fromkeys(current_subjects)),
                "root": current_root,
            })
        current_parts, current_locations, current_subjects = [], [], []
        current_size, current_root = 0, ""

    for path, text in blocks:
        source_heading = path[-1] if path else "內景篇一"
        root_heading = path[0] if path else "內景篇一"
        subject = DONGUI_HEADING_KO.get(source_heading, "내경편의 관련 주제")
        if current_parts and current_root != root_heading:
            flush_inner()
        for chunk in split_long_text(text):
            part = f"{source_heading}\n{chunk}"
            if current_parts and current_size + len(part) + 2 > 950:
                flush_inner()
            if not current_root:
                current_root = root_heading
            current_parts.append(part)
            current_locations.append(" > ".join(path) if path else "內景篇一")
            current_subjects.append(subject)
            current_size += len(part) + 2
    flush_inner()

    for index, group in enumerate(grouped, 1):
        locations = group["locations"]
        location = f"{locations[0]} — {locations[-1]} · 원문 구간 {index}/{len(grouped)}"
        subjects = group["subjects"]
        subject_list = ", ".join(subjects[:3])
        if len(subjects) > 3:
            subject_list += " 등"
        section = f"內景篇一 > {group['root']}"
        if group["root"] == "精":
            summary = "내경편 정(精) 절의 고전 설명과 약물·단방·도인·침구에 관한 기록을 수록한다. 역사적 의서의 서술이다."
        elif group["root"] == "身形":
            summary = "내경편 신형 절에서 몸의 형성, 기의 성쇠, 생애 단계와 양생에 관한 고전 설명을 다룬다. 역사적 의서의 서술이다."
        else:
            summary = f"동의보감 내경편 ‘{subject_list}’의 원문과 인용을 수록한다. 역사적 의학 문헌의 서술이다."
        result.append(base_record(
            f"dongui-inner1-{index:03d}", f"동의보감 내경편 원문: {subject_list}",
            ["동의보감", "내경편", "신체", *subjects], group["body"],
            summary,
            "동의보감 (東醫寶鑒)", section, location, page,
            "역사적 고전 원문 전사 및 한국어 독해 요약",
        ))
    return result


def huangdi_records(page: dict) -> list[dict]:
    result = []
    for path, text in split_headed_text(page["wikitext"]):
        if not path:
            continue
        heading = path[-1]
        title_ko, summary = HUANGDI_TITLES.get(
            heading, ("소문 원문", "황제내경 소문의 고전 내용을 원문 전사로 수록한다."))
        section = f"素問第一卷 > {heading}"
        chunks = split_long_text(text)
        for index, chunk in enumerate(chunks, 1):
            location = heading if len(chunks) == 1 else f"{heading} · 원문 구간 {index}/{len(chunks)}"
            result.append(base_record(
                f"huangdi-suwen1-{len(result) + 1:03d}", f"황제내경 {title_ko} 원문",
                ["황제내경", "소문", "음양", "계절", title_ko], chunk, summary,
                "황제내경 (黃帝內經)", section, location, page,
                "역사적 의학 이론의 고전 원문 전사; 현대 임상 근거가 아님",
            ))
    return result


def extract_shennong_entries(raw: str) -> tuple[list[dict], str]:
    value = source_content(raw, onlyinclude=False)
    entries = []
    current_section = ""
    current_name = None
    current_lines: list[str] = []
    prelude: list[str] = []

    def finish_entry() -> None:
        nonlocal current_name, current_lines
        if current_name:
            content = "\n".join(line for line in current_lines if line).strip()
            if content:
                entries.append({"section": current_section, "name": current_name, "text": content})
        current_name = None
        current_lines = []

    for raw_line in value.splitlines():
        heading = re.match(r"^\s*={2,4}\s*(.*?)\s*={2,4}\s*$", raw_line)
        if heading:
            finish_entry()
            heading_text = plain_line(heading.group(1))
            if heading_text in {"上經", "中經", "下經"}:
                current_section = heading_text
            continue
        bold = re.match(r"^\s*'{3}([^']+?)'{3}(.*)$", raw_line)
        if bold:
            finish_entry()
            current_name = plain_line(bold.group(1))
            rest = plain_line(bold.group(2))
            if rest:
                current_lines.append(rest)
            continue
        line = plain_line(raw_line)
        if current_name:
            if line:
                current_lines.append(line)
        elif line:
            prelude.append(line)
    finish_entry()
    return entries, "\n".join(prelude).strip()


def shennong_records(page: dict) -> list[dict]:
    entries, prelude = extract_shennong_entries(page["wikitext"])
    result: list[dict] = []
    if prelude:
        for index, chunk in enumerate(split_long_text(prelude), 1):
            result.append(base_record(
                f"shennong-preface-{index:03d}", "신농본초경 서문 원문",
                ["신농본초경", "본초", "편찬서문"], chunk,
                "신농본초경의 서문과 분류 취지를 담은 원문이다. 역사적 본초 문헌으로 읽는다.",
                "신농본초경 (神農本草經)", "序 및 상경 서문", f"서문 · {index}", page,
                "역사적 본초 문헌 원문 전사 및 한국어 독해 요약",
            ))

    # Group complete herb entries, without truncation, into searchable chunks.
    group: list[dict] = []
    group_chars = 0

    def flush_group() -> None:
        nonlocal group, group_chars
        if not group:
            return
        section = group[0]["section"] or "本草"
        names = [entry["name"] for entry in group]
        korean_names = [HERB_KO[name] for name in names if name in HERB_KO]
        body = "\n\n".join(f"{entry['name']} {entry['text']}" for entry in group)
        start, end = names[0], names[-1]
        tags = ["신농본초경", "본초", section, "약재"] + korean_names
        labels = "·".join(korean_names[:3]) if korean_names else f"{start} 등"
        result.append(base_record(
            f"shennong-herbs-{len(result) + 1:03d}",
            f"신농본초경 {section} 원문: {labels}", tags, body,
            f"{section} 분류의 본초 항목을 원문으로 묶었다. 고전의 분류·성미·주치 기록이며 현대 임상 효능이나 복용 권고를 뜻하지 않는다.",
            "신농본초경 (神農本草經)", section,
            f"{section} · {start}" if start == end else f"{section} · {start}—{end}",
            page, "역사적 본초 문헌 원문 전사 및 한국어 독해 요약",
        ))
        group = []
        group_chars = 0

    for entry in entries:
        entry_chars = len(entry["name"]) + len(entry["text"])
        if group and (entry["section"] != group[0]["section"] or group_chars + entry_chars + 2 > 950):
            flush_group()
        group.append(entry)
        group_chars += entry_chars + 2
        if entry_chars > 950:
            flush_group()
    flush_group()
    if not entries:
        raise ValueError("Pinned Shennong page contained no recognizable original-text entries")
    return result


def build_manifest(pages: dict[str, dict], records: list[dict]) -> dict:
    downloads = []
    for page in PAGES:
        item = pages[page["key"]]
        downloads.append({
            "source_id": f"zh-wikisource:{page['pageid']}@{page['revid']}",
            "title": page["title"],
            "pageid": page["pageid"],
            "revision": page["revid"],
            "revision_timestamp": page["timestamp"],
            "source_url": source_url(page),
            "raw_wikitext_chars": len(item["wikitext"]),
            "raw_wikitext_sha256": item["sha256_verified"],
            "used_in_records": page["include"],
            "license": LICENSE,
        })
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "generated_by": "refresh_classics.py",
        "source_system": "zh.wikisource.org MediaWiki API; exact old revisions only",
        "license": LICENSE,
        "attribution": "Wikisource contributors, page title and permanent oldid link per record; original works marked public domain. Extraction strips wiki formatting, then chunks the transcription and adds Korean summaries.",
        "record_count": len(records),
        "source_revision_count": sum(1 for page in PAGES if page["include"]),
        "coverage": {
            "dongui": "東醫寶鑒 root revision 2245890; pinned 序, 集例, and the available 身形 and 精 sections on 內景篇一. Its 氣 and 神 transclusions point to missing pages; the API lists no 內景篇一 subpages. Missing text is not fabricated.",
            "huangdi": "黃帝內經/素問第一卷, including the four chapters present in the pinned transcription.",
            "shennong": "All readable content present in the pinned 神農本草經 page revision. Wikisource marks its transcription Textquality 50%; this does not establish a complete or critical edition.",
        },
        "historical_scope": "Classical statements are historical source text, not current clinical evidence, diagnoses, treatment advice, or proof of efficacy.",
        "downloads": downloads,
        "records": [{key: record[key] for key in (
            "id", "title", "book", "section", "location", "source_url",
            "source_revision", "source_id", "license",
        )} for record in records],
    }


def main() -> None:
    pages = fetch_revisions()
    records = []
    records.extend(dongui_records(pages))
    records.extend(huangdi_records(pages["huangdi-suwen-1"]))
    records.extend(shennong_records(pages["shennong"]))
    if not records or len(records) > 1000:
        raise ValueError(f"Unexpected classical corpus size: {len(records)}")
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate classical record IDs")
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    outputs = {
        data_dir / "classics.seed.json": json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        data_dir / "classics.manifest.json": json.dumps(build_manifest(pages, records), ensure_ascii=False, indent=2) + "\n",
    }
    temporary_paths = []
    try:
        for target, content in outputs.items():
            temporary = target.with_name(target.name + ".tmp")
            temporary_paths.append((temporary, target))
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        for temporary, target in temporary_paths:
            temporary.replace(target)
    finally:
        for temporary, _ in temporary_paths:
            if temporary.exists():
                temporary.unlink()
    print(f"Pinned revisions verified: {len(PAGES)}; corpus records: {len(records)}")
    print(f"Wrote {data_dir / 'classics.seed.json'} and {data_dir / 'classics.manifest.json'}")


if __name__ == "__main__":
    main()
