from __future__ import annotations

import html
import os
import re
from collections import Counter
from datetime import date
from typing import Any

import httpx

OPENALEX_URL = os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/")
CROSSREF_URL = os.getenv("CROSSREF_BASE_URL", "https://api.crossref.org").rstrip("/")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()
CONTACT_EMAIL = os.getenv("LITERATURE_CONTACT_EMAIL", "enertri@example.org").strip()
TIMEOUT = float(os.getenv("LITERATURE_TIMEOUT_SECONDS", "30"))


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions: dict[int, str] = {}
    for word, indexes in index.items():
        for position in indexes:
            positions[int(position)] = word
    return " ".join(positions[i] for i in sorted(positions)) or None


def _openalex_params(extra: dict[str, Any]) -> dict[str, Any]:
    params = dict(extra)
    if not OPENALEX_API_KEY:
        raise RuntimeError("未配置 OPENALEX_API_KEY")
    params["api_key"] = OPENALEX_API_KEY
    return params


def _headers() -> dict[str, str]:
    return {"User-Agent": f"EnerTri/4.0 (mailto:{CONTACT_EMAIL})"}


def _clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("https://doi.org/", "").replace("http://doi.org/", "")


def _clean_abstract(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip() or None


def normalize_openalex_work(work: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for item in work.get("authorships") or []:
        name = ((item.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    topic = work.get("primary_topic") or {}
    return {
        "id": work.get("id"),
        "title": work.get("display_name") or work.get("title") or "Untitled",
        "authors": authors,
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "source": source.get("display_name"),
        "doi": _clean_doi(work.get("doi")),
        "cited_by_count": work.get("cited_by_count") or 0,
        "type": work.get("type"),
        "language": work.get("language"),
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "topic": topic.get("display_name"),
        "topic_id": topic.get("id"),
        "open_access": bool((work.get("open_access") or {}).get("is_oa")),
        "landing_page_url": primary_location.get("landing_page_url") or best_oa.get("landing_page_url"),
        "pdf_url": best_oa.get("pdf_url") or primary_location.get("pdf_url"),
        "license": best_oa.get("license") or primary_location.get("license"),
    }


def search_openalex(
    query: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    open_access: bool | None = None,
    language: str | None = None,
    sort: str = "relevance_score:desc",
    limit: int = 20,
) -> dict[str, Any]:
    filters: list[str] = []
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{year_to}-12-31")
    if open_access is not None:
        filters.append(f"open_access.is_oa:{str(open_access).lower()}")
    if language:
        filters.append(f"language:{language.strip().lower()}")
    params: dict[str, Any] = {
        "search": query,
        "per_page": max(1, min(limit, 100)),
        "sort": sort,
        "select": "id,display_name,authorships,publication_year,publication_date,primary_location,best_oa_location,doi,cited_by_count,type,language,abstract_inverted_index,primary_topic,open_access",
    }
    if filters:
        params["filter"] = ",".join(filters)
    if not OPENALEX_API_KEY:
        return search_crossref(
            query, year_from=year_from, year_to=year_to, limit=limit,
            warning="未配置 OpenAlex API Key，已使用 Crossref 元数据回退；配置免费 Key 后可获得更完整的主题与开放获取字段。",
        )
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_headers()) as client:
            response = client.get(f"{OPENALEX_URL}/works", params=_openalex_params(params))
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        return search_crossref(query, year_from=year_from, year_to=year_to, limit=limit, warning=f"OpenAlex 暂不可用，已使用 Crossref 回退：{exc}")
    return {
        "source": "OpenAlex",
        "total": (data.get("meta") or {}).get("count", len(data.get("results") or [])),
        "items": [normalize_openalex_work(item) for item in data.get("results") or []],
        "warning": None,
    }


def search_crossref(
    query: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    warning: str | None = None,
) -> dict[str, Any]:
    filters: list[str] = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{year_to}-12-31")
    params: dict[str, Any] = {"query.bibliographic": query, "rows": max(1, min(limit, 100)), "mailto": CONTACT_EMAIL}
    if filters:
        params["filter"] = ",".join(filters)
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_headers()) as client:
            response = client.get(f"{CROSSREF_URL}/works", params=params)
            response.raise_for_status()
            message = response.json().get("message") or {}
    except httpx.HTTPError as exc:
        raise RuntimeError(f"文献检索服务不可用：{exc}") from exc
    items = []
    for work in message.get("items") or []:
        title = " ".join(work.get("title") or []) or "Untitled"
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in work.get("author") or []]
        issued = ((work.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = issued[0] if issued else None
        links = work.get("link") or []
        pdf_url = next((item.get("URL") for item in links if item.get("content-type") == "application/pdf"), None)
        items.append({
            "id": work.get("DOI"),
            "title": title,
            "authors": [a for a in authors if a],
            "year": year,
            "publication_date": None,
            "source": (work.get("container-title") or [None])[0],
            "doi": work.get("DOI"),
            "cited_by_count": work.get("is-referenced-by-count") or 0,
            "type": work.get("type"),
            "language": work.get("language"),
            "abstract": _clean_abstract(work.get("abstract")),
            "topic": None,
            "topic_id": None,
            "open_access": None,
            "landing_page_url": work.get("URL"),
            "pdf_url": pdf_url,
            "license": ((work.get("license") or [{}])[0]).get("URL"),
        })
    return {"source": "Crossref", "total": message.get("total-results", len(items)), "items": items, "warning": warning}


def _topic_groups(query: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": query,
        "filter": f"from_publication_date:{start_year}-01-01,to_publication_date:{end_year}-12-31",
        "group_by": "primary_topic.id",
        "per_page": 1,
    }
    with httpx.Client(timeout=TIMEOUT, headers=_headers()) as client:
        response = client.get(f"{OPENALEX_URL}/works", params=_openalex_params(params))
        response.raise_for_status()
        return response.json().get("group_by") or []


def _crossref_hotspot_terms(query: str, start_year: int, end_year: int, rows: int = 300) -> tuple[Counter[str], int]:
    """Build a transparent sample-based topic proxy from Crossref subjects/titles."""
    params: dict[str, Any] = {
        "query.bibliographic": query,
        "rows": max(20, min(rows, 1000)),
        "filter": f"from-pub-date:{start_year}-01-01,until-pub-date:{end_year}-12-31",
        "mailto": CONTACT_EMAIL,
    }
    with httpx.Client(timeout=TIMEOUT, headers=_headers()) as client:
        response = client.get(f"{CROSSREF_URL}/works", params=params)
        response.raise_for_status()
        items = (response.json().get("message") or {}).get("items") or []
    counts: Counter[str] = Counter()
    stopwords = {
        "study", "analysis", "effect", "effects", "using", "based", "research", "method", "methods",
        "welding", "weld", "material", "materials", "process", "processes", "performance", "properties",
        "the", "and", "for", "with", "from", "into", "under", "a", "an", "of", "in", "on", "to",
    }
    for work in items:
        subjects = [str(value).strip() for value in work.get("subject") or [] if str(value).strip()]
        if subjects:
            counts.update(subjects)
            continue
        title = " ".join(work.get("title") or [])
        words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}|[\u4e00-\u9fff]{2,8}", title)]
        counts.update(word for word in words if word not in stopwords and word.lower() not in query.lower().split())
    return counts, len(items)


def _crossref_hotspots(query: str, recent_start: int, current_year: int, previous_start: int, previous_end: int, limit: int, warning: str) -> dict[str, Any]:
    try:
        recent, recent_sample = _crossref_hotspot_terms(query, recent_start, current_year)
        previous, previous_sample = _crossref_hotspot_terms(query, previous_start, previous_end)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"热点统计服务不可用：{exc}") from exc
    rows = []
    for topic, recent_count in recent.items():
        previous_count = previous.get(topic, 0)
        growth = None if previous_count == 0 else round((recent_count - previous_count) / previous_count * 100, 1)
        momentum = recent_count if previous_count == 0 else round(recent_count / max(previous_count, 1), 3)
        rows.append({
            "topic_id": None,
            "topic": topic,
            "recent_count": recent_count,
            "previous_count": previous_count,
            "growth_percent": growth,
            "momentum": momentum,
        })
    rows.sort(key=lambda x: (x["momentum"], x["recent_count"]), reverse=True)
    return {
        "source": "Crossref sample-based fallback",
        "query": query,
        "recent_window": f"{recent_start}-{current_year}",
        "comparison_window": f"{previous_start}-{previous_end}",
        "items": rows[: max(1, min(limit, 50))],
        "sample_size": {"recent": recent_sample, "comparison": previous_sample},
        "warning": warning,
        "note": "回退结果基于 Crossref 返回样本中的学科标签或题名高频词，不是全库精确聚合；配置 OpenAlex API Key 后使用主题聚合。",
    }


def research_hotspots(query: str, *, recent_years: int = 2, comparison_years: int = 2, limit: int = 20) -> dict[str, Any]:
    current_year = date.today().year
    recent_start = current_year - recent_years + 1
    previous_end = recent_start - 1
    previous_start = previous_end - comparison_years + 1
    if not OPENALEX_API_KEY:
        return _crossref_hotspots(
            query, recent_start, current_year, previous_start, previous_end, limit,
            "未配置 OpenAlex API Key，热点采用 Crossref 样本回退。",
        )
    try:
        recent_groups = _topic_groups(query, recent_start, current_year)
        previous_groups = _topic_groups(query, previous_start, previous_end)
    except (httpx.HTTPError, RuntimeError) as exc:
        return _crossref_hotspots(
            query, recent_start, current_year, previous_start, previous_end, limit,
            f"OpenAlex 暂不可用，热点采用 Crossref 样本回退：{exc}",
        )
    previous_map = {item.get("key"): int(item.get("count") or 0) for item in previous_groups}
    rows = []
    for item in recent_groups:
        recent_count = int(item.get("count") or 0)
        previous_count = previous_map.get(item.get("key"), 0)
        growth = None if previous_count == 0 else round((recent_count - previous_count) / previous_count * 100, 1)
        momentum = recent_count if previous_count == 0 else round(recent_count / max(previous_count, 1), 3)
        rows.append({
            "topic_id": item.get("key"),
            "topic": item.get("key_display_name") or item.get("key") or "未知主题",
            "recent_count": recent_count,
            "previous_count": previous_count,
            "growth_percent": growth,
            "momentum": momentum,
        })
    rows.sort(key=lambda x: (x["momentum"], x["recent_count"]), reverse=True)
    return {
        "source": "OpenAlex",
        "query": query,
        "recent_window": f"{recent_start}-{current_year}",
        "comparison_window": f"{previous_start}-{previous_end}",
        "items": rows[: max(1, min(limit, 50))],
        "note": "热点基于 OpenAlex 主题聚合和两个时间窗口的发文量变化，适合作为选题线索，不等同于同行评议结论。",
    }

