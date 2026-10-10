"""Read-only adapter for the KMM canonical corpus and its existing v2 FTS index.

No external project imports, model weights, inference, downloads or credentials.
Only retrieved passages are read and checked against canonical source lines.
"""
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path


class ClassicalDB:
    def __init__(self, root):
        root = Path(root).resolve()
        self.corpus = root / "data/kmm.sqlite3"
        self.index = root / "data/v2/search.sqlite3"
        if not self.corpus.is_file() or not self.index.is_file():
            raise ValueError("고문헌 원본 DB와 v2 검색 인덱스를 찾지 못했어요.")
        with self.open(self.index) as db:
            self.meta = dict(db.execute("SELECT key,value FROM meta"))
            if self.meta.get("version") != "kmm-index-v2.1":
                raise ValueError("지원하지 않는 고문헌 검색 인덱스예요.")
            self.count = db.execute("SELECT count(*) FROM documents").fetchone()[0]
            self.sources = {r[0]: json.loads(r[1]) for r in db.execute("SELECT source_id,metadata FROM sources")}
        with self.open(self.corpus) as db:
            self.line_count = db.execute("SELECT count(*) FROM lines").fetchone()[0]
            canonical_sources = {r["source_id"]: dict(r) for r in db.execute("SELECT * FROM sources")}
            if set(canonical_sources) != set(self.sources):
                raise ValueError("고문헌 원본과 검색 인덱스의 문헌 목록이 달라요.")
            self.sources = canonical_sources
        self.terms = {}
        term_map = root / "data/term_map.json"
        if term_map.is_file():
            data = json.loads(term_map.read_text(encoding="utf-8"))
            for word, candidates in data.get("ko2han", {}).items():
                ranked = sorted(candidates.items(), key=lambda x: (bool(x[1].get("in_title")), x[1].get("n", 0)), reverse=True)
                self.terms[word] = [han for han, info in ranked[:2] if info.get("in_title") or info.get("n", 0) >= 2]

    @staticmethod
    def open(path):
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return closing(db)

    def status(self):
        return {"connected": True, "books": len(self.sources), "passages": self.count,
                "lines": self.line_count, "index_version": self.meta["version"],
                "index_bytes": self.index.stat().st_size, "corpus_bytes": self.corpus.stat().st_size}

    def expression(self, term):
        words = re.findall(r"[a-z0-9가-힣\u3400-\u9fff]+", unicodedata.normalize("NFKC", term).lower())[:8]
        alternatives = []
        for word in words:
            # Prefixes match inflections in the existing morphological index.
            forms = [word, *self.terms.get(word, [])]
            alternatives.append("(" + " OR ".join('"' + f + '"*' for f in forms) + ")")
        return " AND ".join(alternatives)

    def search(self, keywords, limit=8):
        limit = min(100, max(1, limit))
        terms = list(dict.fromkeys(k.strip() for k in keywords if isinstance(k, str) and 1 < len(k.strip()) <= 300))[:12]
        scores, rows = {}, {}
        with self.open(self.index) as db:
            # Bound each result list before reading any full passage.
            for term in terms:
                expression = self.expression(term)
                if not expression:
                    continue
                hits = db.execute("""SELECT v.doc_id,d.title,substr(d.text_ko,1,100) AS reading FROM views_fts
                    JOIN views v ON v.id=views_fts.rowid JOIN documents d ON d.id=v.doc_id
                    WHERE views_fts MATCH ? ORDER BY bm25(views_fts,5,2,2,4) LIMIT 80""", (expression,)).fetchall()
                seen = set()
                for position, hit in enumerate(hits):
                    doc_id = hit[0]
                    if doc_id in seen:
                        continue
                    seen.add(doc_id)
                    heading = hit["title"] + " " + hit["reading"].split("\n", 1)[0]
                    heading_match = term.lower() in heading.lower()
                    scores[doc_id] = scores.get(doc_id, 0) + 1 / (60 + position) + (0.05 if heading_match else 0)
            ids = sorted(scores, key=lambda i: (-scores[i], i))[:limit]
            for doc_id in ids:
                rows[doc_id] = dict(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
        return self.records([rows[i] for i in ids])

    def browse(self, limit=40):
        with self.open(self.index) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY id LIMIT ?", (min(100, limit),))]
        return self.records(rows)

    def records(self, rows):
        records = []
        with self.open(self.corpus) as db:
            for row in rows:
                line_ids = json.loads(row["line_ids_json"])
                if not line_ids:
                    raise ValueError("고문헌 원문 행 위치가 없어요.")
                original = {r["line_id"]: dict(r) for r in db.execute(
                    "SELECT line_id,source_id,text_hanmun,text_ko FROM lines WHERE line_id IN (" + ",".join("?" for _ in line_ids) + ")", line_ids)}
                if any(i not in original or original[i]["source_id"] != row["source_id"] for i in line_ids):
                    raise ValueError("고문헌 인덱스와 원문 위치가 일치하지 않아요.")
                body = "\n".join(original[i]["text_hanmun"] for i in line_ids if original[i]["text_hanmun"])
                reading = "\n".join(original[i]["text_ko"] for i in line_ids if original[i]["text_ko"])
                if body != row["text_hanmun"] or reading != row["text_ko"]:
                    raise ValueError("고문헌 검색 인덱스가 원본과 달라 답변을 보류했어요.")
                if not body.strip():
                    continue
                source = self.sources[row["source_id"]]
                records.append({"id": "kmm:" + row["passage_id"], "title": source["title"] + " · " + row["title"],
                    "category": "classical", "tags": [row["title"]], "body": body, "summary": reading,
                    "book": source["title"], "section": row["section_path"],
                    "location": row["section_id"] + " · " + ", ".join(line_ids),
                    "source_url": source["source_url"], "publisher": source["author_body"],
                    "source_revision": source["edition"], "license": source["license"],
                    "evidence_level": "고문헌 원문", "limitations": "역사적 문헌이며 개인 진단·처방의 근거를 대신하지 않아요.",
                    "retrieved_at": self.meta.get("built_at", ""), "line_ids": line_ids,
                    "content_hash": row["content_hash"], "corpus": "kmm"})
        return records
