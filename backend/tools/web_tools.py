from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from config import settings
from db.models import WebSearchCache
from tools.base import ToolContext, ToolExecutionError, ToolSpec, ensure_string
from tools.registry import ToolRegistry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _query_key(query: str, max_results: int) -> str:
    raw = f"{query.strip().lower()}::{max_results}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_CB_LOCK = threading.Lock()
_CB_STATE: dict[str, dict[str, float | int]] = {
    "duckduckgo": {"failures": 0, "open_until": 0.0},
    "wikipedia": {"failures": 0, "open_until": 0.0},
    "pubmed": {"failures": 0, "open_until": 0.0},
}


def _cb_should_allow(name: str) -> bool:
    now = time.monotonic()
    with _CB_LOCK:
        state = _CB_STATE.setdefault(name, {"failures": 0, "open_until": 0.0})
        return float(state.get("open_until", 0.0)) <= now


def _cb_record_success(name: str) -> None:
    with _CB_LOCK:
        state = _CB_STATE.setdefault(name, {"failures": 0, "open_until": 0.0})
        state["failures"] = 0
        state["open_until"] = 0.0


def _cb_record_failure(name: str) -> None:
    threshold = max(int(settings.WEB_SEARCH_CIRCUIT_FAIL_THRESHOLD), 1)
    open_seconds = max(int(settings.WEB_SEARCH_CIRCUIT_OPEN_SECONDS), 5)
    now = time.monotonic()
    with _CB_LOCK:
        state = _CB_STATE.setdefault(name, {"failures": 0, "open_until": 0.0})
        failures = int(state.get("failures", 0)) + 1
        state["failures"] = failures
        if failures >= threshold:
            state["open_until"] = now + open_seconds


def _run_with_circuit(name: str, fn, *args, **kwargs):
    if not _cb_should_allow(name):
        raise RuntimeError(f"{name} circuit_open")
    try:
        out = fn(*args, **kwargs)
        _cb_record_success(name)
        return out
    except Exception:
        _cb_record_failure(name)
        raise


def _read_cache(ctx: ToolContext, key: str) -> list[dict[str, Any]] | None:
    cutoff = _utc_now() - timedelta(hours=max(settings.WEB_SEARCH_CACHE_TTL_HOURS, 1))
    row = (
        ctx.db.query(WebSearchCache)
        .filter(WebSearchCache.query_key == key, WebSearchCache.fetched_at >= cutoff)
        .order_by(WebSearchCache.fetched_at.desc())
        .first()
    )
    if not row:
        return None
    try:
        parsed = json.loads(row.results_json)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _write_cache(ctx: ToolContext, key: str, query: str, provider: str, results: list[dict[str, Any]]) -> None:
    payload = json.dumps(results, ensure_ascii=True)
    row = ctx.db.query(WebSearchCache).filter(WebSearchCache.query_key == key).first()
    if not row:
        row = WebSearchCache(
            query_key=key,
            query=query,
            provider=provider,
            results_json=payload,
            fetched_at=_utc_now(),
        )
        ctx.db.add(row)
        return
    row.query = query
    row.provider = provider
    row.results_json = payload
    row.fetched_at = _utc_now()


def _ddg_instant_search(query: str, max_results: int, timeout_s: int) -> list[dict[str, str]]:
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers={"User-Agent": "LongevityCoach/1.0"})
        resp.raise_for_status()
        data = resp.json()

    results: list[dict[str, str]] = []
    abstract_text = str(data.get("AbstractText") or "").strip()
    abstract_url = str(data.get("AbstractURL") or "").strip()
    heading = str(data.get("Heading") or "").strip()
    if abstract_text and abstract_url:
        results.append(
            {
                "title": heading or "DuckDuckGo Instant Answer",
                "url": abstract_url,
                "snippet": abstract_text,
                "source": "duckduckgo",
            }
        )

    related = data.get("RelatedTopics", [])
    if isinstance(related, list):
        for topic in related:
            if len(results) >= max_results:
                break
            if isinstance(topic, dict) and isinstance(topic.get("Topics"), list):
                for child in topic.get("Topics", []):
                    if len(results) >= max_results:
                        break
                    if not isinstance(child, dict):
                        continue
                    text = str(child.get("Text") or "").strip()
                    url_item = str(child.get("FirstURL") or "").strip()
                    if text and url_item:
                        results.append(
                            {
                                "title": text.split(" - ")[0][:120],
                                "url": url_item,
                                "snippet": text[:320],
                                "source": "duckduckgo",
                            }
                        )
            elif isinstance(topic, dict):
                text = str(topic.get("Text") or "").strip()
                url_item = str(topic.get("FirstURL") or "").strip()
                if text and url_item:
                    results.append(
                        {
                            "title": text.split(" - ")[0][:120],
                            "url": url_item,
                            "snippet": text[:320],
                            "source": "duckduckgo",
                        }
                    )

    return results[:max_results]


def _wikipedia_open_search(query: str, max_results: int, timeout_s: int) -> list[dict[str, str]]:
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&search={quote_plus(query)}&limit={max_results}&namespace=0&format=json"
    )
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": "LongevityCoach/1.0"})
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list) or len(data) < 4:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    descs = data[2] if isinstance(data[2], list) else []
    urls = data[3] if isinstance(data[3], list) else []

    out: list[dict[str, str]] = []
    for i, title in enumerate(titles):
        if len(out) >= max_results:
            break
        t = str(title).strip()
        u = str(urls[i]).strip() if i < len(urls) else ""
        d = str(descs[i]).strip() if i < len(descs) else ""
        if not t or not u:
            continue
        out.append({"title": t, "url": u, "snippet": d[:320], "source": "wikipedia"})
    return out


def _pubmed_search(query: str, max_results: int, timeout_s: int) -> list[dict[str, str]]:
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": max_results,
        "sort": "relevance",
        "term": query,
    }
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        search_resp = client.get(
            search_url,
            params=search_params,
            headers={"User-Agent": "LongevityCoach/1.0"},
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()

        ids = (
            search_data.get("esearchresult", {}).get("idlist", [])
            if isinstance(search_data, dict)
            else []
        )
        if not isinstance(ids, list) or not ids:
            return []

        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        summary_resp = client.get(
            summary_url,
            params={
                "db": "pubmed",
                "retmode": "json",
                "id": ",".join(ids[:max_results]),
            },
            headers={"User-Agent": "LongevityCoach/1.0"},
        )
        summary_resp.raise_for_status()
        summary_data = summary_resp.json()

    if not isinstance(summary_data, dict):
        return []
    result_block = summary_data.get("result", {})
    if not isinstance(result_block, dict):
        return []

    out: list[dict[str, str]] = []
    for pmid in ids[:max_results]:
        item = result_block.get(str(pmid), {})
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        pubdate = str(item.get("pubdate", "")).strip()
        fulljournalname = str(item.get("fulljournalname", "")).strip()
        if not title:
            continue
        snippet_parts = []
        if fulljournalname:
            snippet_parts.append(fulljournalname)
        if pubdate:
            snippet_parts.append(pubdate)
        snippet = " | ".join(snippet_parts)
        out.append(
            {
                "title": title,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "snippet": snippet[:320],
                "source": "pubmed",
            }
        )
    return out


def _merge_results(primary: list[dict[str, str]], secondary: list[dict[str, str]], max_results: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in [*primary, *secondary]:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(item)
        if len(out) >= max_results:
            break
    return out


def _tool_web_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if not settings.ENABLE_WEB_SEARCH:
        raise ToolExecutionError("Web search is disabled")

    query = ensure_string(args, "query")
    max_results = args.get("max_results", settings.WEB_SEARCH_MAX_RESULTS)
    if not isinstance(max_results, int):
        raise ToolExecutionError("`max_results` must be an integer")
    max_results = max(1, min(max_results, 10))

    key = _query_key(query, max_results)
    cached = _read_cache(ctx, key)
    if cached is not None:
        return {"query": query, "results": cached[:max_results], "cached": True}

    timeout_s = max(2, int(settings.WEB_SEARCH_TIMEOUT_SECONDS))
    ddg_results: list[dict[str, str]] = []
    wiki_results: list[dict[str, str]] = []
    pubmed_results: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        ddg_results = _run_with_circuit(
            "duckduckgo",
            _ddg_instant_search,
            query,
            max_results=max_results,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        errors.append(f"duckduckgo:{exc.__class__.__name__}")
    try:
        wiki_results = _run_with_circuit(
            "wikipedia",
            _wikipedia_open_search,
            query,
            max_results=max_results,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        errors.append(f"wikipedia:{exc.__class__.__name__}")
    try:
        pubmed_results = _run_with_circuit(
            "pubmed",
            _pubmed_search,
            query,
            max_results=max_results,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        errors.append(f"pubmed:{exc.__class__.__name__}")

    results = _merge_results(ddg_results, _merge_results(pubmed_results, wiki_results, max_results), max_results)

    _write_cache(ctx, key=key, query=query, provider="duckduckgo+pubmed+wikipedia", results=results)
    return {"query": query, "results": results, "cached": False, "errors": errors}


def register_web_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="web_search",
            description="Search current web information for health-related user questions.",
            required_fields=("query",),
            read_only=True,
            allowed_specialists=frozenset(settings.WEB_SEARCH_ALLOWED_SPECIALISTS),
            tags=("search", "web"),
        ),
        _tool_web_search,
    )
