#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vet Lit Radar
PubMedの主要獣医誌を巡回し、犬・猫の内科トピックに該当する新着論文を集めて
index.html ダイジェストを生成する。

2つのモードに自動で切り替わります。
  - 無料モード（ANTHROPIC_API_KEY が無いとき）:
      該当論文をキーワードでトピック分類し、タイトル・抄録・リンクを一覧表示。
      AIによる要約・採点はしない。費用ゼロ。
  - AIモード（ANTHROPIC_API_KEY があるとき）:
      各論文をClaudeが採点・和文要約し、有用度で絞り込んで掲載。

使い方:
  python fetch_and_digest.py                  # 通常実行（config.RELDATE 日分）
  python fetch_and_digest.py --reldate 30     # 初回シード等、期間を上書き
  python fetch_and_digest.py --check-journals # 各誌略称が解決するか件数確認
"""
import os
import sys
import json
import time
import html
import datetime
import xml.etree.ElementTree as ET

import requests

import config

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

DATA_DIR = "data"
PAPERS_PATH = os.path.join(DATA_DIR, "papers.json")
SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
OUT_HTML = "index.html"


# --------------------------------------------------------------------------
# NCBI E-utilities
# --------------------------------------------------------------------------
def _ncbi_params(extra):
    p = dict(extra)
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    if NCBI_EMAIL:
        p["email"] = NCBI_EMAIL
    p["tool"] = "vet-lit-radar"
    return p


def build_term():
    journals = " OR ".join(f'"{j}"[Journal]' for j in config.JOURNALS)
    species = " OR ".join(f"{s}[tiab]" for s in config.SPECIES)
    kws = []
    for group in config.TOPIC_GROUPS.values():
        for kw in group:
            kws.append(f'"{kw}"[tiab]' if (" " in kw or "-" in kw) else f"{kw}[tiab]")
    topics = " OR ".join(kws)
    return f"(({journals}) AND ({species}) AND ({topics}))"


def esearch(term, reldate):
    params = _ncbi_params({
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": str(config.MAX_FETCH),
        "datetype": "edat",
        "reldate": str(reldate),
    })
    r = requests.get(f"{EUTILS}/esearch.fcgi", params=params, timeout=60)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def efetch(pmids):
    out = []
    for i in range(0, len(pmids), 100):
        batch = pmids[i:i + 100]
        params = _ncbi_params({
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        })
        r = requests.get(f"{EUTILS}/efetch.fcgi", params=params, timeout=120)
        r.raise_for_status()
        out.extend(parse_articles(r.text))
        time.sleep(0.4)
    return out


def parse_articles(xml_text):
    root = ET.fromstring(xml_text)
    arts = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID") or art.findtext(".//PMID") or ""
        title_el = art.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abs_parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            txt = "".join(ab.itertext()).strip()
            if not txt:
                continue
            abs_parts.append(f"{label}: {txt}" if label else txt)
        abstract = "\n".join(abs_parts)

        journal = (art.findtext(".//Journal/ISOAbbreviation")
                   or art.findtext(".//Journal/Title") or "")
        year = (art.findtext(".//JournalIssue/PubDate/Year")
                or art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")

        doi = ""
        for eid in art.findall(".//ELocationID"):
            if eid.get("EIdType") == "doi" and eid.text:
                doi = eid.text.strip()
                break
        if not doi:
            for aid in art.findall(".//ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text.strip()
                    break

        names = []
        for a in art.findall(".//AuthorList/Author"):
            ln = a.findtext("LastName")
            ini = a.findtext("Initials")
            if ln:
                names.append(f"{ln} {ini}" if ini else ln)
        if len(names) > 1:
            authors = f"{names[0]} et al."
        elif names:
            authors = names[0]
        else:
            authors = ""

        if pmid:
            arts.append({
                "pmid": pmid, "title": title, "abstract": abstract,
                "journal": journal, "year": str(year), "doi": doi, "authors": authors,
            })
    return arts


# --------------------------------------------------------------------------
# 無料モード: キーワードでトピックを割り当てる（AIなし）
# --------------------------------------------------------------------------
def match_topic(art):
    text = f"{art.get('title','')} {art.get('abstract','')}".lower()
    for name, kws in config.TOPIC_GROUPS.items():
        for kw in kws:
            if kw.lower() in text:
                return name
    return "その他"


# --------------------------------------------------------------------------
# AIモード: Claude による選別・要約（キーがあるときだけ使う）
# --------------------------------------------------------------------------
PROMPT = """あなたは小動物内科の臨床研究を専門とする獣医師です。次の論文（タイトルと抄録）を評価してください。

出力はJSONオブジェクトのみ。前後の説明・コードフェンス（```）は一切付けないこと。

{{
  "relevant": true または false,
  "topic": "次から最も近いもの1つ: {topics}, その他",
  "usefulness": 1から5の整数,
  "one_line_jp": "20〜40字の日本語見出し",
  "summary_jp": "2〜3文の日本語要約（試験デザイン・対象・主要結果）",
  "takeaway_jp": "1文の臨床的ポイント"
}}

判定基準:
- relevant=true は「犬または猫の内科臨床に有用」な場合のみ。基礎研究のみ・対象が他動物のみ・内科と無関係ならfalse。
- usefulness は臨床的有用性（5=実臨床を変えうる重要報告、3=参考になる、1=ほぼ影響なし）。

論文:
Journal: {journal} ({year})
Title: {title}
Abstract: {abstract}
"""


def _strip_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    return text.strip()


def classify(client, art):
    topics = "、".join(config.TOPIC_GROUPS.keys())
    prompt = PROMPT.format(
        topics=topics, journal=art["journal"], year=art["year"],
        title=art["title"], abstract=(art["abstract"][:6000] or "(抄録なし)"),
    )
    msg = client.messages.create(
        model=config.MODEL, max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return json.loads(_strip_json(text))


# --------------------------------------------------------------------------
# HTML ダイジェスト生成（両モード対応）
# --------------------------------------------------------------------------
def render_html(papers, ai_mode):
    e = html.escape
    papers = sorted(
        papers,
        key=lambda p: (p.get("date_added", ""), p.get("usefulness", 0), p.get("journal", "")),
        reverse=True,
    )
    topics = list(config.TOPIC_GROUPS.keys()) + ["その他"]
    updated = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    mode_label = "AI要約モード" if ai_mode else "一覧モード（無料）"

    cards = []
    for p in papers:
        topic = e(p.get("topic", "その他"))
        date = e(p.get("date_added", ""))
        pm = f"https://pubmed.ncbi.nlm.nih.gov/{e(p['pmid'])}/"
        doi_link = (f' · <a href="https://doi.org/{e(p["doi"])}" target="_blank" rel="noopener">DOI</a>'
                    if p.get("doi") else "")

        if "usefulness" in p:
            u = int(p.get("usefulness", 0))
            stars = f'<span class="stars" title="臨床的有用性">{"★" * u}{"☆" * (5 - u)}</span>'
        else:
            stars = ""

        heading = e(p.get("one_line_jp") or p.get("title", ""))
        orig = (f'<p class="orig">{e(p.get("title",""))}</p>'
                if p.get("one_line_jp") else "")

        if p.get("summary_jp"):
            body = (f'<p class="summary">{e(p["summary_jp"])}</p>'
                    f'<p class="takeaway">💡 {e(p.get("takeaway_jp",""))}</p>')
        elif p.get("abstract"):
            body = ('<details class="abs"><summary>抄録を表示</summary>'
                    f'<div class="abstract">{e(p["abstract"])}</div></details>')
        else:
            body = '<p class="orig">（抄録なし）</p>'

        cards.append(f"""
    <article class="card" data-topic="{topic}">
      <div class="meta"><span class="topic">{topic}</span>{stars}<span class="date">{date}</span></div>
      <h2>{heading}</h2>
      {orig}
      <p class="src">{e(p.get('authors',''))} — <em>{e(p.get('journal',''))}</em> {e(p.get('year',''))}</p>
      {body}
      <p class="links"><a href="{pm}" target="_blank" rel="noopener">PubMed (PMID:{e(p['pmid'])})</a>{doi_link}</p>
    </article>""")

    buttons = '<button class="filter active" data-f="all">すべて</button>' + "".join(
        f'<button class="filter" data-f="{e(t)}">{e(t)}</button>' for t in topics
    )

    empty = '<p class="empty">まだ論文がありません。初回は --reldate 30 でシードしてください。</p>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(config.SITE_TITLE)}</title>
<style>
  :root {{ --navy:#16294A; --teal:#0E7C86; --bg:#f5f7fa; --ink:#1f2733; --muted:#6b7280; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
          background:var(--bg); color:var(--ink); line-height:1.6; }}
  header {{ background:var(--navy); color:#fff; padding:20px 16px; }}
  header h1 {{ margin:0; font-size:1.2rem; }}
  header .sub {{ opacity:.8; font-size:.8rem; margin-top:4px; }}
  .filters {{ position:sticky; top:0; background:#fff; padding:10px 12px; border-bottom:1px solid #e5e7eb;
              display:flex; gap:6px; flex-wrap:wrap; z-index:10; }}
  .filter {{ border:1px solid var(--teal); background:#fff; color:var(--teal); border-radius:999px;
             padding:4px 12px; font-size:.8rem; cursor:pointer; }}
  .filter.active {{ background:var(--teal); color:#fff; }}
  main {{ max-width:760px; margin:0 auto; padding:14px; }}
  .card {{ background:#fff; border-left:4px solid var(--teal); border-radius:8px; padding:14px 16px;
           margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .meta {{ display:flex; gap:10px; align-items:center; font-size:.75rem; color:var(--muted); flex-wrap:wrap; }}
  .topic {{ background:var(--navy); color:#fff; border-radius:4px; padding:1px 8px; }}
  .stars {{ color:#e8a33d; letter-spacing:1px; }}
  .card h2 {{ font-size:1rem; margin:8px 0 4px; color:var(--navy); }}
  .orig {{ font-size:.82rem; color:var(--muted); margin:0 0 6px; }}
  .src {{ font-size:.8rem; color:var(--muted); margin:0 0 8px; }}
  .summary {{ margin:0 0 8px; }}
  .takeaway {{ background:#eef7f8; border-radius:6px; padding:8px 10px; margin:0 0 8px; font-size:.9rem; }}
  .abs summary {{ cursor:pointer; color:var(--teal); font-size:.85rem; }}
  .abstract {{ white-space:pre-line; font-size:.88rem; margin-top:8px; color:#333; }}
  .links a {{ color:var(--teal); text-decoration:none; font-size:.85rem; }}
  .empty {{ text-align:center; color:var(--muted); padding:40px; }}
  footer {{ text-align:center; color:var(--muted); font-size:.75rem; padding:24px; }}
</style>
</head>
<body>
<header>
  <h1>{e(config.SITE_TITLE)}</h1>
  <div class="sub">{mode_label} ／ 最終更新 {updated} ／ 収載 {len(papers)} 件</div>
</header>
<nav class="filters">{buttons}</nav>
<main id="list">
{''.join(cards) if cards else empty}
</main>
<footer>PubMed E-utilities（＋任意でClaude）で自動生成。内容は必ず原著（PubMedリンク）を確認してください。</footer>
<script>
  const btns = document.querySelectorAll('.filter');
  btns.forEach(b => b.addEventListener('click', () => {{
    btns.forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    const f = b.dataset.f;
    document.querySelectorAll('.card').forEach(c => {{
      c.style.display = (f === 'all' || c.dataset.topic === f) ? '' : 'none';
    }});
  }}));
</script>
</body>
</html>"""


# --------------------------------------------------------------------------
def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def check_journals():
    print(f"{'count':>10}  journal")
    for j in config.JOURNALS:
        params = _ncbi_params({"db": "pubmed", "term": f'"{j}"[Journal]', "retmode": "json"})
        r = requests.get(f"{EUTILS}/esearch.fcgi", params=params, timeout=60)
        c = r.json().get("esearchresult", {}).get("count", "?")
        flag = "  <-- 0件: 略称を確認" if c == "0" else ""
        print(f"{c:>10}  {j}{flag}")
        time.sleep(0.4)


def main(argv):
    reldate = config.RELDATE
    if "--check-journals" in argv:
        check_journals()
        return
    if "--reldate" in argv:
        reldate = int(argv[argv.index("--reldate") + 1])

    ai_mode = bool(ANTHROPIC_API_KEY)
    print(f"モード: {'AI要約' if ai_mode else '一覧（無料）'}")

    os.makedirs(DATA_DIR, exist_ok=True)
    papers = load(PAPERS_PATH, [])
    seen = set(load(SEEN_PATH, []))

    term = build_term()
    ids = esearch(term, reldate)
    print(f"esearch: {len(ids)} 件ヒット (reldate={reldate})")

    new_ids = [i for i in ids if i not in seen][:config.MAX_PAPERS_PER_RUN]
    print(f"新規: {len(new_ids)} 件")

    arts = efetch(new_ids) if new_ids else []
    today = datetime.date.today().isoformat()

    client = None
    if ai_mode:
        from anthropic import Anthropic  # キーがある時だけ読み込む
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

    added = 0
    for art in arts:
        seen.add(art["pmid"])

        if ai_mode:
            try:
                res = classify(client, art)
            except Exception as ex:  # noqa: BLE001
                print(f"  classify error PMID:{art['pmid']} {ex}")
                continue
            if not res.get("relevant"):
                continue
            if int(res.get("usefulness", 0)) < config.MIN_USEFULNESS:
                continue
            record = {
                "pmid": art["pmid"], "title": art["title"], "journal": art["journal"],
                "year": art["year"], "doi": art["doi"], "authors": art["authors"],
                "topic": res.get("topic", "その他"),
                "usefulness": int(res.get("usefulness", 0)),
                "one_line_jp": res.get("one_line_jp", ""),
                "summary_jp": res.get("summary_jp", ""),
                "takeaway_jp": res.get("takeaway_jp", ""),
                "date_added": today,
            }
            time.sleep(0.2)
        else:
            # 無料モード: 抄録も残してそのまま一覧化
            record = {**art, "topic": match_topic(art), "date_added": today}

        papers.append(record)
        added += 1

    print(f"掲載追加: {added} 件 / 総計 {len(papers)} 件")
    with open(PAPERS_PATH, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(render_html(papers, ai_mode))
    print(f"{OUT_HTML} を生成しました。")


if __name__ == "__main__":
    main(sys.argv[1:])
