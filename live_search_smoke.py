"""Explicit live OpenAI search checks; consumes the current account's model quota."""
import json
import tempfile
from pathlib import Path

from server import App, ROOT


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = App(Path(directory), ROOT / "data" / "knowledge.seed.json")
        if not app.codex_enabled:
            raise RuntimeError("ChatGPT login unavailable")
        session = app.store.create_session()["id"]
        report = {"model": "gpt-6-luna", "effort": "high", "auth": "existing ChatGPT login", "checks": []}
        for kind, query in [
            ("hospitals", "서울 강남역 한의원 공식 위치 전화번호와 공개 후기"),
            ("web", "한국한의약진흥원 국가한의임상정보포털 공식 안내"),
        ]:
            care = app.web_search(session, {"query": query}, kind)
            result = next(s for s in care["searches"] if s["kind"] == kind)["data"]
            rows = result["hospitals"] if kind == "hospitals" else result["results"]
            assert rows, f"No accessible results for {kind}"
            report["checks"].append({"kind": kind, "count": len(rows), "data": result})
        report["booking_submitted"] = False
        (ROOT / ".runtime" / "search-live-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"model": report["model"], "effort": report["effort"],
                          "results": [{"kind": row["kind"], "count": row["count"]} for row in report["checks"]],
                          "booking_submitted": False}))


if __name__ == "__main__":
    main()
