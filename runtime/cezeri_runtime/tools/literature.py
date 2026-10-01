"""Literature search tools for the Cezeri research-team app.

Registers into the shared tool registry (see CONTRACT.md "Tool registry"):

- search_pubmed            -- NCBI E-utilities (esearch -> esummary -> efetch)
- search_semantic_scholar  -- api.semanticscholar.org paper search
- search_europe_pmc        -- EBI Europe PMC REST search

All search tools take ``(query: str, max_results: int = 8)`` and return a
``list[dict]`` of papers shaped as::

    {"title": str, "authors": list[str], "year": str, "journal": str,
     "doi": str, "pmid": str, "url": str, "abstract": str}

Every key is always present (empty string / empty list when unknown).

Hard guarantees (per contract):
- NEVER raise on network failure, rate limiting, or bad responses:
  log a warning and return [] so agents degrade gracefully offline.
- Every HTTP request carries a 10s timeout.
- No API keys required by any of these sources.

A ``format_citations(papers)`` helper renders numbered citation lines.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 10
_TOOL = "cezeri"
_EMAIL = "cezeri@localhost"

_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_SEMANTIC_SCHOLAR_SEARCH = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)

_EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _empty_paper() -> dict:
    return {
        "title": "",
        "authors": [],
        "year": "",
        "journal": "",
        "doi": "",
        "pmid": "",
        "url": "",
        "abstract": "",
    }


def _clean(value) -> str:
    """Return a stripped string; never raise on weird input."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _get_json(url: str, params: dict | None = None) -> dict | list | None:
    """GET and parse JSON; return None (with a warning) on any failure."""
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code == 429:
            log.warning("rate limited (429) by %s", url)
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.warning("request failed for %s: %s", url, exc)
        return None
    except ValueError as exc:  # bad JSON
        log.warning("bad JSON response from %s: %s", url, exc)
        return None


def _get_text(url: str, params: dict | None = None) -> str | None:
    """GET and return text; return None (with a warning) on any failure."""
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code == 429:
            log.warning("rate limited (429) by %s", url)
            return None
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        log.warning("request failed for %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------
# PubMed (NCBI E-utilities)
# --------------------------------------------------------------------------
def search_pubmed(query: str, max_results: int = 8) -> list[dict]:
    """Search PubMed via NCBI E-utilities.

    Flow: esearch (PMIDs) -> esummary (title/authors/journal/doi) ->
    efetch XML (abstracts). Sleeps ~0.34s between calls to stay under the
    3 req/s NCBI limit. Returns [] on any failure.
    """
    try:
        return _search_pubmed(query, max_results)
    except Exception as exc:  # contract: never raise
        log.warning("search_pubmed failed: %s", exc)
        return []


def _search_pubmed(query: str, max_results: int) -> list[dict]:
    query = _clean(query)
    if not query:
        return []
    max_results = max(1, min(int(max_results), 50))
    base = {"tool": _TOOL, "email": _EMAIL}

    # 1) esearch -> PMID list
    data = _get_json(
        _PUBMED_ESEARCH,
        {**base, "db": "pubmed", "term": query, "retmax": max_results,
         "retmode": "json", "sort": "relevance"},
    )
    if not data:
        return []
    try:
        idlist = data["esearchresult"]["idlist"]
    except (KeyError, TypeError):
        log.warning("pubmed esearch returned unexpected shape")
        return []
    if not idlist:
        return []
    time.sleep(0.34)  # NCBI: <= 3 requests/second

    # 2) esummary -> metadata for all IDs in one call
    summary = _get_json(
        _PUBMED_ESUMMARY,
        {**base, "db": "pubmed", "id": ",".join(idlist), "retmode": "json"},
    )
    time.sleep(0.34)
    docs: dict[str, dict] = {}
    if isinstance(summary, dict):
        result = summary.get("result", {}) or {}
        for pmid in idlist:
            doc = result.get(pmid)
            if isinstance(doc, dict):
                docs[pmid] = doc

    # 3) efetch XML -> abstracts (one batched call)
    abstracts: dict[str, str] = {}
    xml = _get_text(
        _PUBMED_EFETCH,
        {**base, "db": "pubmed", "id": ",".join(idlist),
         "retmode": "xml", "rettype": "abstract"},
    )
    if xml:
        abstracts = _parse_pubmed_abstracts(xml)

    papers: list[dict] = []
    for pmid in idlist:
        doc = docs.get(pmid, {})
        paper = _empty_paper()
        paper["pmid"] = pmid
        paper["title"] = _clean(doc.get("title"))
        authors = doc.get("authors") or []
        paper["authors"] = [
            _clean(a.get("name")) for a in authors
            if isinstance(a, dict) and a.get("name")
        ]
        pubdate = _clean(doc.get("pubdate"))
        paper["year"] = pubdate[:4] if len(pubdate) >= 4 and pubdate[:4].isdigit() else ""
        paper["journal"] = _clean(doc.get("source"))
        for aid in doc.get("articleids") or []:
            if not isinstance(aid, dict):
                continue
            if aid.get("idtype") == "doi" and aid.get("idvalue"):
                paper["doi"] = _clean(aid["idvalue"])
        if paper["doi"]:
            paper["url"] = f"https://doi.org/{paper['doi']}"
        else:
            paper["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        paper["abstract"] = abstracts.get(pmid, "")
        papers.append(paper)
    return papers


def _parse_pubmed_abstracts(xml_text: str) -> dict[str, str]:
    """Map PMID -> abstract text from efetch XML. Never raises."""
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("pubmed efetch XML parse failed: %s", exc)
        return out
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find("./MedlineCitation/PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
        if not pmid:
            continue
        parts = []
        for node in article.findall("./MedlineCitation/Article/Abstract/AbstractText"):
            text = "".join(node.itertext()).strip()
            label = node.get("Label")
            if label:
                text = f"{label.strip()}: {text}"
            if text:
                parts.append(text)
        if parts:
            out[pmid] = " ".join(parts)
    return out


# --------------------------------------------------------------------------
# Semantic Scholar
# --------------------------------------------------------------------------
def search_semantic_scholar(query: str, max_results: int = 8) -> list[dict]:
    """Search Semantic Scholar's paper graph. Returns [] on any failure."""
    try:
        return _search_semantic_scholar(query, max_results)
    except Exception as exc:  # contract: never raise
        log.warning("search_semantic_scholar failed: %s", exc)
        return []


def _search_semantic_scholar(query: str, max_results: int) -> list[dict]:
    query = _clean(query)
    if not query:
        return []
    max_results = max(1, min(int(max_results), 50))
    data = _get_json(
        _SEMANTIC_SCHOLAR_SEARCH,
        {
            "query": query,
            "limit": max_results,
            "fields": "title,authors,year,venue,doi,url,abstract,openAccessPdf",
        },
    )
    if not isinstance(data, dict):
        return []
    papers: list[dict] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        paper = _empty_paper()
        paper["title"] = _clean(item.get("title"))
        paper["authors"] = [
            _clean(a.get("name")) for a in (item.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        paper["year"] = _clean(item.get("year"))
        paper["journal"] = _clean(item.get("venue"))
        paper["doi"] = _clean(item.get("doi"))
        paper["abstract"] = _clean(item.get("abstract"))
        url = _clean(item.get("url"))
        if not url:
            pdf = item.get("openAccessPdf") or {}
            url = _clean(pdf.get("url")) if isinstance(pdf, dict) else ""
        if not url and paper["doi"]:
            url = f"https://doi.org/{paper['doi']}"
        paper["url"] = url
        papers.append(paper)
    return papers


# --------------------------------------------------------------------------
# Europe PMC
# --------------------------------------------------------------------------
def search_europe_pmc(query: str, max_results: int = 8) -> list[dict]:
    """Search the Europe PMC REST API. Returns [] on any failure."""
    try:
        return _search_europe_pmc(query, max_results)
    except Exception as exc:  # contract: never raise
        log.warning("search_europe_pmc failed: %s", exc)
        return []


def _search_europe_pmc(query: str, max_results: int) -> list[dict]:
    query = _clean(query)
    if not query:
        return []
    max_results = max(1, min(int(max_results), 50))
    data = _get_json(
        _EUROPE_PMC_SEARCH,
        {
            "query": query,
            "format": "json",
            "pageSize": max_results,
            "resultType": "core",  # includes abstractText
        },
    )
    if not isinstance(data, dict):
        return []
    papers: list[dict] = []
    for item in (data.get("resultList") or {}).get("result") or []:
        if not isinstance(item, dict):
            continue
        paper = _empty_paper()
        paper["title"] = _clean(item.get("title"))
        author_string = _clean(item.get("authorString"))
        paper["authors"] = [a.strip() for a in author_string.split(", ") if a.strip()]
        paper["year"] = _clean(item.get("pubYear"))
        journal_info = item.get("journalInfo") or {}
        paper["journal"] = _clean(
            journal_info.get("journal", {}).get("title")
            if isinstance(journal_info.get("journal"), dict)
            else journal_info.get("title")
        )
        paper["doi"] = _clean(item.get("doi"))
        paper["pmid"] = _clean(item.get("pmid"))
        paper["abstract"] = _clean(item.get("abstractText"))
        pmcid = _clean(item.get("pmcid"))
        if pmcid:
            paper["url"] = f"https://europepmc.org/articles/{pmcid}"
        elif paper["pmid"]:
            paper["url"] = f"https://europepmc.org/article/MED/{paper['pmid']}"
        elif paper["doi"]:
            paper["url"] = f"https://doi.org/{paper['doi']}"
        papers.append(paper)
    return papers


# --------------------------------------------------------------------------
# Citation formatting
# --------------------------------------------------------------------------
def format_citations(papers: list[dict]) -> str:
    """Render papers as numbered citation lines.

    ``[1] Author A, Author B, Author C, et al. (2021). Title. Journal.
    doi:10.x/… PMID:12345 https://…``

    Never raises; missing fields are omitted gracefully.
    """
    lines: list[str] = []
    for i, paper in enumerate(papers or [], start=1):
        try:
            lines.append(f"[{i}] {_format_one(paper)}")
        except Exception as exc:  # never break the batch on one bad record
            log.warning("format_citations skipped paper %d: %s", i, exc)
    return "\n".join(lines)


def _format_one(paper: dict) -> str:
    paper = paper or {}
    authors = [a for a in (paper.get("authors") or []) if _clean(a)]
    if not authors:
        author_part = "Unknown"
    elif len(authors) <= 3:
        author_part = ", ".join(authors)
    else:
        author_part = ", ".join(authors[:3]) + ", et al."
    year = _clean(paper.get("year")) or "n.d."
    title = _clean(paper.get("title")) or "(untitled)"
    parts = [f"{author_part} ({year}). {title}."]
    journal = _clean(paper.get("journal"))
    if journal:
        parts.append(f"{journal}.")
    doi = _clean(paper.get("doi"))
    if doi:
        parts.append(f"doi:{doi}")
    pmid = _clean(paper.get("pmid"))
    if pmid:
        parts.append(f"PMID:{pmid}")
    url = _clean(paper.get("url"))
    if url:
        parts.append(url)
    return " ".join(parts)


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    query = "influenza vaccine hemagglutinin antibody"
    for name, fn in (
        ("pubmed", search_pubmed),
        ("semantic_scholar", search_semantic_scholar),
        ("europe_pmc", search_europe_pmc),
    ):
        try:
            results = fn(query, max_results=3)
            count = len(results) if isinstance(results, list) else -1
        except Exception as exc:  # must never crash the self-test
            count = f"ERROR ({exc})"
            results = []
        print(f"[{name}] query -> {count} papers")
        if isinstance(results, list) and results:
            first = results[0] or {}
            title = _clean(first.get("title"))[:100]
            print(f"  first: {title}")
    # exercise the formatter too (works fully offline)
    demo = [_empty_paper()]
    demo[0].update(
        title="Demo paper", authors=["Smith J", "Doe A", "Roe B", "Public Q"],
        year="2024", journal="J Demo", doi="10.1000/demo", pmid="12345",
        url="https://doi.org/10.1000/demo",
    )
    print("format_citations demo:")
    print(format_citations(demo))
    print("self-test done (exit 0)")
