"""One actual Luna High turn: exact classical quotations plus Korean readings."""
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from server import App,ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8");start=time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        app=App(Path(directory),ROOT/"data"/"knowledge.seed.json")
        sid=app.store.create_session()["id"]
        session=app.chat(sid,{"message":"동의보감에서 음식과 일상의 규칙에 관한 고문헌 원문을 찾아줘. 한자 인용에 짧은 한국어 해석을 달아줘.","mode":"codex"})
        reply=session["messages"][-1]
        classics=[s for s in reply["sources"] if s["category"]=="classical" and s.get("citations")]
        assert classics,"No classical citations"
        for source in classics:
            for c in source["citations"]:
                assert source["body"][c["offset_start"]:c["offset_end"]]==c["quote"]
                assert 0<len(c["reading"])<=400 and re.search(r"[가-힣]",c["reading"])
                assert c["reading_origin"]=="luna"
        assert app.store.get_session(sid)["messages"][-1]["sources"]==reply["sources"]
        result={"model":"gpt-6-luna","effort":"high","provider":"openai","elapsed_seconds":round(time.monotonic()-start,1),"reply":reply["content"],"sources":reply["sources"]}
    (ROOT/".runtime"/"reading-live-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"sources"}}|{"classical_sources":len(classics)},ensure_ascii=False))


if __name__=="__main__":main()
