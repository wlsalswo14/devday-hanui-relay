# Classical source corpus

`data/classics.seed.json` is a small, searchable corpus of original Chinese transcription text from three historical medical works. Every row has an exact Wikisource page revision, a short Korean reading, a section/location, a source ID, and an attribution/license field. The corpus distinguishes historical theory from modern clinical evidence; these passages do not establish present-day efficacy or provide personal diagnosis or treatment advice.

## Pinned source revisions

`data/classics.manifest.json` records the page IDs, revision IDs, revision timestamps, SHA-256 hashes of the raw wikitext, permanent links, and the rows derived from each source. The root Dongui page is included as a table-of-contents anchor; its cited excerpt rows use the pinned subpage revisions below.

| Work / page | Pinned revision | SHA-256 of raw wikitext |
| --- | ---: | --- |
| [東醫寶鑒 root](https://zh.wikisource.org/w/index.php?title=%E6%9D%B1%E9%86%AB%E5%AF%B6%E9%91%92&oldid=2245890) | 2245890 | `a94fb88e9f5f4ee212d1ff007919fae6323cc66937dafc2fd074d7a70e7134fa` |
| [東醫寶鑒/序](https://zh.wikisource.org/w/index.php?title=%E6%9D%B1%E9%86%AB%E5%AF%B6%E9%91%92%2F%E5%BA%8F&oldid=2346994) | 2346994 | `12182b9a458f70b562b8ed2da832a275cf5c6d06749ef937e43ff0d94b775b96` |
| [東醫寶鑒/集例](https://zh.wikisource.org/w/index.php?title=%E6%9D%B1%E9%86%AB%E5%AF%B6%E9%91%92%2F%E9%9B%86%E4%BE%8B&oldid=2199215) | 2199215 | `c22f97d6ce64521008507a8b808611f146688b9dd34ed3bc707e8b3b73bcfa70` |
| [東醫寶鑒/內景篇一](https://zh.wikisource.org/w/index.php?title=%E6%9D%B1%E9%86%AB%E5%AF%B6%E9%91%92%2F%E5%85%A7%E6%99%AF%E7%AF%87%E4%B8%80&oldid=2308308) | 2308308 | `47417743666da052d4c3e11c19686860ea0dc0ce8ec6f7df90b0d5999be9d48e` |
| [黃帝內經/素問第一卷](https://zh.wikisource.org/w/index.php?title=%E9%BB%83%E5%B8%9D%E5%85%A7%E7%B6%93%2F%E7%B4%A0%E5%95%8F%E7%AC%AC%E4%B8%80%E5%8D%B7&oldid=2083230) | 2083230 | `f1bb91f185adfaf2c3f9d06d76bc7b1cf6ac152d85c1d6ac377376733d176c4c` |
| [神農本草經](https://zh.wikisource.org/w/index.php?title=%E7%A5%9E%E8%BE%B2%E6%9C%AC%E8%8D%89%E7%B6%93&oldid=2490492) | 2490492 | `a7ef706e8b3255c20582620a882adbc8b3ef1d3fbb5d9c00ba0b8b8ceb5c18d1` |

The Dongui `序` page names 李廷龜 (이정구) as its author. The corpus identifies him in the section and title metadata. The `黃帝內經/素問第一卷` page contains four chapters: 上古天真論篇第一, 四氣調神大論篇第二, 生氣通天論篇第三, and 金匱真言論篇第四.

## Coverage limits

The pinned Dongui root points to `內景篇一`, whose available transcription contains the `身形` and `精` sections. Its `氣` and `神` transclusions point to missing pages: a Wikisource API prefix lookup returned no `內景篇一/…` subpages. Only text that is present in the pinned page is included; missing sections are not reconstructed.

The pinned `神農本草經` page marks its transcription as Textquality 50%. The seed contains the readable text present in that exact revision; this label does not establish that the transcription is complete or that it represents a critical edition. The page's `序` heading labels its introductory passage; herb rows are grouped under the original `上經`, `中經`, or `下經` class and located by the original bold item names. Those source headings remain distinct in the row's `section` and `location`. The seed retains historical Chinese herb names, with familiar Korean name tags added where a mapping is available. Those tags support search and are not contemporary drug identifications or use recommendations.

## Attribution and license

The ancient underlying works are public domain. Wikisource's [Chinese copyright information page](https://zh.wikisource.org/wiki/Wikisource%3A%E7%89%88%E6%9D%83%E4%BF%A1%E6%81%AF) says that contributions are released under CC BY-SA 4.0 and GFDL; see also the [CC BY-SA 4.0 terms](https://creativecommons.org/licenses/by-sa/4.0/). Each seed row links to its permanent page revision and carries the source title, revision, source ID, and license. Attribution is to the relevant Wikisource contributors and page; the script removes wiki formatting, divides the transcription into searchable sections, and adds Korean summaries.

The `body` field contains the transcribed source text in traditional Chinese, with wiki templates/markup and footnote markup removed for search. The `summary` field is a concise Korean reading. The historical statements remain separate from the app's modern safety and evidence material.

## Rebuilding

Run `python refresh_classics.py`. It requests only the fixed MediaWiki revision IDs in the script, verifies every raw wikitext SHA-256 before rebuilding, and then writes the seed and manifest. A network failure, unavailable revision, identity mismatch, or hash mismatch stops the run before either output is replaced. The script does not fetch or modify `data/knowledge.seed.json` and does not access `info.mediclassics.kr`.
