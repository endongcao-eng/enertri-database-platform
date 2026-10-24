from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from .models import SpaceEnergyLiterature


DEFAULT_SPACE_ENERGY_API_BASE_URL = "https://114514191981061285174648.dpdns.org"
SPACE_ENERGY_TIMEOUT = float(os.getenv("SPACE_ENERGY_TIMEOUT_SECONDS", "8"))


class SpaceEnergyCatalogError(RuntimeError):
    pass


class SpaceEnergyLiteratureNotFound(SpaceEnergyCatalogError):
    pass


def api_base_url() -> str:
    return os.getenv("SPACE_ENERGY_API_BASE_URL", DEFAULT_SPACE_ENERGY_API_BASE_URL).strip().rstrip("/")


def _request_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{api_base_url()}{path}"
    headers = {"Accept": "application/json", "User-Agent": "EnerTri/4.7 paper-catalog"}
    token = os.getenv("SPACE_ENERGY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=SPACE_ENERGY_TIMEOUT, follow_redirects=True)
        if response.status_code == 404:
            raise SpaceEnergyLiteratureNotFound("论文主库中未找到该论文")
        response.raise_for_status()
        data = response.json()
    except SpaceEnergyLiteratureNotFound:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise SpaceEnergyCatalogError(f"空间能源平台论文主库暂不可用：{exc}") from exc
    if not isinstance(data, dict):
        raise SpaceEnergyCatalogError("空间能源平台返回了无法识别的数据格式")
    return data


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def map_literature(item: dict[str, Any]) -> dict[str, Any]:
    """Map the upstream `literatures` row to EnerTri's compatible response."""
    authors = _as_list(item.get("authors"))
    tags = _as_list(item.get("tags"))
    doi = item.get("doi") or None
    url = item.get("url") or None
    doi_url = f"https://doi.org/{doi}" if doi else None
    landing_url = url or doi_url
    source = item.get("source") or None
    return {
        "id": str(item.get("id") or ""),
        "title": item.get("title") or "",
        "authors": authors,
        "year": item.get("year"),
        "source": source,
        "journal": source,
        "abstract": item.get("abstract") or None,
        "doi": doi,
        "url": url,
        "full_text": item.get("full_text") or None,
        "source_file": item.get("source_file") or None,
        "tags": tags,
        "keywords": tags,
        "primary_source": "space_energy",
        "sources": ["空间能源平台论文库"],
        "citation_count": 0,
        "open_access": None,
        "landing_page_url": landing_url,
        "fulltext_url": url,
        "doi_url": doi_url,
        "open_url": landing_url,
    }


def _mirror_rows(db: Session, items: list[dict[str, Any]]) -> None:
    """Persist a schema-compatible read-through mirror after successful reads."""
    for item in items:
        literature_id = str(item.get("id") or "").strip()
        if not literature_id:
            continue
        row = db.get(SpaceEnergyLiterature, literature_id)
        if row is None:
            row = SpaceEnergyLiterature(id=literature_id)
            db.add(row)
        row.title = item.get("title")
        row.authors = ",".join(_as_list(item.get("authors")))
        row.year = item.get("year")
        row.source = item.get("source")
        row.abstract = item.get("abstract")
        row.doi = item.get("doi")
        row.url = item.get("url")
        row.full_text = item.get("full_text")
        row.source_file = item.get("source_file")
        row.tags = ",".join(_as_list(item.get("tags")))
    if items:
        db.commit()


def list_literatures(db: Session, *, q: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 200)), "offset": max(0, offset)}
    if q and q.strip():
        params["keyword"] = q.strip()
    data = _request_json("/api/literatures", params)
    items = data.get("items")
    if not isinstance(items, list):
        raise SpaceEnergyCatalogError("空间能源平台论文列表响应缺少 items")
    _mirror_rows(db, items)
    return {
        "items": [map_literature(item) for item in items if isinstance(item, dict)],
        "total": int(data.get("total") or len(items)),
        "offset": int(data.get("offset") or 0),
        "limit": int(data.get("limit") or params["limit"]),
        "source": "space_energy",
        "available": True,
    }


def get_literature(db: Session | None, literature_id: str) -> dict[str, Any] | None:
    try:
        data = _request_json(f"/api/literatures/{quote(literature_id, safe='')}")
    except SpaceEnergyLiteratureNotFound:
        return None
    item = data.get("data")
    if not isinstance(item, dict):
        return None
    if db is not None:
        _mirror_rows(db, [item])
    return map_literature(item)


def search_literatures(query: str, *, limit: int = 20, year_from: int | None = None, year_to: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "limit": max(1, min(limit, 100)), "sort": "relevance"}
    if year_from:
        params["year_from"] = year_from
    if year_to:
        params["year_to"] = year_to
    data = _request_json("/api/search", params)
    items = data.get("literatures")
    if not isinstance(items, list):
        raise SpaceEnergyCatalogError("空间能源平台搜索响应缺少 literatures")
    return {
        "source": "空间能源平台论文库",
        "total": int(data.get("total_literatures") or len(items)),
        "items": [map_literature(item) for item in items if isinstance(item, dict)],
        "warning": None,
    }


def sync_search_results(db: Session, items: list[dict[str, Any]]) -> None:
    rows = []
    for item in items:
        rows.append({
            "id": item.get("id") or item.get("source_record_id"), "title": item.get("title"), "authors": item.get("authors"),
            "year": item.get("year"), "source": item.get("journal") or item.get("source"),
            "abstract": item.get("abstract"), "doi": item.get("doi"), "url": item.get("url") or item.get("landing_page_url"),
            "full_text": item.get("full_text"), "source_file": item.get("source_file"), "tags": item.get("tags") or item.get("keywords"),
        })
    _mirror_rows(db, rows)


def connection_status() -> dict[str, Any]:
    try:
        data = _request_json("/api/literatures", {"limit": 1, "offset": 0})
        return {"ok": True, "available": True, "total": int(data.get("total") or 0), "message": "空间能源平台论文主库已连接"}
    except SpaceEnergyCatalogError as exc:
        return {"ok": False, "available": False, "total": None, "message": str(exc)}
