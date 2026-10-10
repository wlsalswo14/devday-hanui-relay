"""Read public Naver search results without a visible browser or API credentials."""
import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse

from care import safe_url
from codex_bridge import ModelError
from request_lifecycle import CURRENT_REQUEST, check_cancelled


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchor = None
        self.rows = {}
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "a":
            self.finish_anchor()
            classes = attrs.get("class", "")
            eligible = any(marker in classes for marker in
                           ("fds-anchor-layout", "uD1F4", "news_tit", "title_link", "api_txt_lines", "link_tit", "total_tit"))
            url = safe_url(attrs.get("href", ""))
            host = urlparse(url).hostname or ""
            if host in {"search.naver.com", "ader.naver.com", "nid.naver.com", "keep.naver.com", "help.naver.com"}:
                eligible = False
            self.anchor = {"url": url, "eligible": eligible, "parts": []}

    def handle_data(self, data):
        if self.anchor and not self.skip:
            self.anchor["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag == "a":
            self.finish_anchor()

    def finish_anchor(self):
        anchor, self.anchor = self.anchor, None
        if not anchor or not anchor["eligible"] or not anchor["url"]:
            return
        text = " ".join(" ".join(anchor["parts"]).split()).replace("새 창 열림", "").strip()
        if len(text) < 4 or text in {"네이버", "홈페이지", "더보기", "공유하기"} or "Keep에" in text:
            return
        row = self.rows.setdefault(anchor["url"], {"url": anchor["url"], "texts": []})
        if text not in row["texts"]:
            row["texts"].append(text[:1000])

    def results(self, query):
        generic = {"공식", "자료", "안내", "홈페이지", "사이트", "검색", "최신", "정보", "인근", "주변", "목록", "리스트", "official", "website"}
        terms = [t.lower() for t in query.split() if len(t) > 1 and t.lower() not in generic]
        rows = []
        for row in self.rows.values():
            texts = row["texts"]
            titles = [t for t in texts if len(t) <= 180 and "›" not in t and not re.match(r"^(?:https?://|www\.)", t)]
            if not titles:
                continue
            title = titles[0]
            snippet = max(texts, key=len)
            if snippet == title:
                snippet = ""
            score = sum(term in " ".join(texts).lower() for term in terms)
            rows.append((score, {"title": title[:180], "url": row["url"], "summary": snippet[:800],
                                 "publisher": urlparse(row["url"]).hostname}))
        rows.sort(key=lambda row: row[0], reverse=True)
        return [row for _, row in rows[:8]]


def fetch(query):
    request = urllib.request.Request("https://search.naver.com/search.naver?" +
        urlencode({"where": "nexearch", "query": query}), headers={"User-Agent": "Hanui/1.0", "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200 or urlparse(response.url).hostname != "search.naver.com":
            raise ValueError("Search unavailable")
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("Search response too large")
    parser = ResultParser()
    parser.feed(content.decode("utf-8", "replace"))
    parser.finish_anchor()
    rows = parser.results(query)
    if not rows:
        raise ValueError("No verified search result links")
    return {"query": query, "provider": "네이버", "results": rows, "urls": [r["url"] for r in rows],
            "screen": json.dumps(rows, ensure_ascii=False)}


def search(query):
    check_cancelled()
    if not isinstance(query, str) or not query.strip() or len(query) > 250:
        raise ModelError("검색어를 확인해 주세요.")
    process = None
    try:
        if CURRENT_REQUEST.get() is None:
            result = fetch(query.strip())
        else:
            process = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            first = True
            while True:
                check_cancelled()
                try:
                    output, _ = process.communicate(json.dumps({"query": query.strip()}) if first else None, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            result = json.loads(output)
            if process.returncode or "error" in result:
                raise ValueError("Search unavailable")
        check_cancelled()
        return result
    except (OSError, ValueError):
        raise ModelError("웹검색 결과를 가져오지 못했어요. 잠시 후 다시 요청해 주세요.") from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == "__main__":
    try:
        print(json.dumps(fetch(json.load(sys.stdin)["query"]), ensure_ascii=False))
    except Exception:
        print(json.dumps({"error": "Search unavailable"}))
