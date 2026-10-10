import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, closing
from pathlib import Path

from classical_db import ClassicalDB
from codex_bridge import validate_result, ModelError
from store import Store


@contextmanager
def writable(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class ClassicalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/v2").mkdir(parents=True)
        source = {"source_id": "book", "title": "東醫寶鑑", "source_url": "https://mediclassics.kr/books/8",
                  "author_body": "KIOM", "edition": "test edition", "license": "KOGL Type 1"}
        with writable(self.root / "data/kmm.sqlite3") as db:
            db.execute("CREATE TABLE sources(source_id,title,source_url,author_body,edition,license)")
            db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)", tuple(source.values()))
            db.execute("CREATE TABLE lines(line_id,source_id,text_hanmun,text_ko)")
            db.execute("INSERT INTO lines VALUES ('book.line1','book','起居有常','생활에 일정한 규칙이 있다')")
        with writable(self.root / "data/v2/search.sqlite3") as db:
            db.executescript("""
                CREATE TABLE meta(key,value);
                INSERT INTO meta VALUES ('version','kmm-index-v2.1');
                CREATE TABLE sources(source_id,metadata);
                CREATE TABLE documents(id INTEGER PRIMARY KEY,passage_id,source_id,section_id,section_path,title,
                    line_ids_json,text_hanmun,text_ko,content_hash);
                CREATE TABLE views(id INTEGER PRIMARY KEY,doc_id);
                CREATE VIRTUAL TABLE views_fts USING fts5(title_tokens,korean_tokens,hanmun_tokens,alias_tokens);
                INSERT INTO views VALUES (1,1);
                INSERT INTO views_fts VALUES ('양생','생활 규칙 수면','起居 有常','동의보감');
                """)
            db.execute("INSERT INTO sources VALUES (?,?)", ("book", json.dumps(source)))
            db.execute("INSERT INTO documents VALUES (1,'v2:1','book','section1','양생','양생',?,'起居有常','생활에 일정한 규칙이 있다','hash')", (json.dumps(["book.line1"]),))
        self.adapter = ClassicalDB(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_search_and_citation_use_exact_original(self):
        records = self.adapter.search(["양생"], 4)
        self.assertEqual(records[0]["body"], "起居有常")
        self.assertIn("book.line1", records[0]["location"])
        result = {"reply": "규칙적인 생활에 관한 원문이에요.", "source_ids": [], "citations": [
            {"source_id": records[0]["id"], "quote": "起居有常", "reading": "생활에 규칙이 있다"}]}
        self.assertEqual(validate_result(result, "", records, require_classical=True)["citations"][0]["offset_end"], 4)
        result["citations"][0]["quote"] = "허구 원문"
        with self.assertRaises(ModelError):
            validate_result(result, "", records, require_classical=True)

    def test_index_mismatch_fails_closed(self):
        with writable(self.root / "data/kmm.sqlite3") as db:
            db.execute("UPDATE lines SET text_hanmun='different'")
        with self.assertRaisesRegex(ValueError, "원본과 달라"):
            self.adapter.search(["양생"])

    def test_missing_line_fails_closed(self):
        with writable(self.root / "data/kmm.sqlite3") as db:
            db.execute("DELETE FROM lines")
        with self.assertRaises(ValueError):
            self.adapter.search(["양생"])

    def test_read_only_and_fts_input_is_not_sql(self):
        with self.adapter.open(self.adapter.corpus) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM lines")
        self.assertEqual(self.adapter.search(['" OR * ; DROP TABLE lines; --']), [])
        self.assertEqual(self.adapter.status()["lines"], 1)

    def test_store_connection_preserves_personal_data(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "knowledge-db.json").write_text(json.dumps({"root": str(self.root)}), encoding="utf-8")
        seed = Path(__file__).resolve().parents[1] / "data/knowledge.seed.json"
        store = Store(runtime / "patient.sqlite3", seed)
        session = store.create_session()
        self.assertEqual(store.search_fulltext(["양생"], 1)[0]["corpus"], "kmm")
        self.assertEqual(store.get_session(session["id"])["id"], session["id"])
        self.assertTrue(any(r.get("corpus") == "kmm" for r in store.library(category="classical")))
        baseline = Store(self.root / "separate/patient.sqlite3", seed)
        self.assertEqual([r["id"] for r in store.library("수면", "lifestyle")],
                         [r["id"] for r in baseline.library("수면", "lifestyle")])


if __name__ == "__main__":
    unittest.main()
