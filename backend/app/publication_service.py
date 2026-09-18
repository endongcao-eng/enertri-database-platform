from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .literature import CONTACT_EMAIL, CROSSREF_URL, OPENALEX_API_KEY, OPENALEX_URL, TIMEOUT, normalize_openalex_work, search_crossref, search_openalex
from .models import Publication, PublicationSource


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value.strip().rstrip(".") or None


def normalize_title(value: str | None) -> str:
    value = (value or "").casefold()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_person(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").casefold())


def normalize_publication(item: dict[str, Any], source: str) -> dict[str, Any]:
    authors = item.get("authors") or []
    if authors and isinstance(authors[0], dict):
        authors = [a.get("name") or a.get("display_name") or "" for a in authors]
    authors = [str(a).strip() for a in authors if str(a).strip()]
    institutions = [str(v).strip() for v in item.get("institutions") or [] if str(v).strip()]
    keywords = [str(v).strip() for v in item.get("keywords") or [] if str(v).strip()]
    title = str(item.get("title") or "Untitled").strip()
    return {
        "source": source,
        "source_record_id": str(item.get("id") or item.get("source_record_id") or normalize_doi(item.get("doi")) or title),
        "doi": normalize_doi(item.get("doi")),
        "title": title,
        "normalized_title": normalize_title(title),
        "authors": authors,
        "first_author": authors[0] if authors else None,
        "institutions": institutions,
        "abstract": item.get("abstract"),
        "keywords": keywords,
        "journal": item.get("journal") or item.get("source") or item.get("container_title"),
        "year": int(item["year"]) if item.get("year") else None,
        "citation_count": int(item.get("citation_count", item.get("cited_by_count", 0)) or 0),
        "open_access": item.get("open_access"),
        "landing_page_url": item.get("landing_page_url") or item.get("url"),
        "fulltext_url": item.get("fulltext_url") or item.get("pdf_url"),
        "raw": item,
    }


def duplicate_reason(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str | None, float]:
    if a.get("doi") and a.get("doi") == b.get("doi"):
        return True, "doi_exact", 1.0
    ta, tb = a.get("normalized_title") or "", b.get("normalized_title") or ""
    if ta and ta == tb:
        return True, "title_normalized_exact", 1.0
    title_score = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0
    author_match = bool(normalize_person(a.get("first_author")) and normalize_person(a.get("first_author")) == normalize_person(b.get("first_author")))
    year_a, year_b = a.get("year"), b.get("year")
    year_close = not year_a or not year_b or abs(int(year_a) - int(year_b)) <= 1
    journal_a, journal_b = normalize_title(a.get("journal")), normalize_title(b.get("journal"))
    journal_match = bool(journal_a and journal_b and SequenceMatcher(None, journal_a, journal_b).ratio() >= 0.85)
    if title_score >= 0.94 and author_match and year_close:
        return True, "title_author_similarity", title_score
    if title_score >= 0.90 and author_match and year_close and journal_match:
        return True, "title_author_year_journal", title_score
    return False, None, title_score


def deduplicate_publications(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[dict[str, Any]] = []
    merges: list[dict[str, Any]] = []
    for item in items:
        matched = None
        for group in groups:
            is_dup, reason, score = duplicate_reason(group["canonical"], item)
            if is_dup:
                matched = (group, reason, score)
                break
        if not matched:
            groups.append({"canonical": item, "records": [item], "sources": [item["source"]], "dedup_reasons": []})
            continue
        group, reason, score = matched
        group["records"].append(item)
        if item["source"] not in group["sources"]:
            group["sources"].append(item["source"])
        group["dedup_reasons"].append({"source": item["source"], "reason": reason, "score": round(score, 4)})
        canonical = group["canonical"]
        for field in ["doi", "abstract", "journal", "landing_page_url", "fulltext_url"]:
            if not canonical.get(field) and item.get(field):
                canonical[field] = item[field]
        canonical["citation_count"] = max(int(canonical.get("citation_count") or 0), int(item.get("citation_count") or 0))
        canonical["open_access"] = bool(canonical.get("open_access") or item.get("open_access"))
        canonical["authors"] = canonical.get("authors") or item.get("authors") or []
        canonical["institutions"] = sorted(set((canonical.get("institutions") or []) + (item.get("institutions") or [])))
        canonical["keywords"] = sorted(set((canonical.get("keywords") or []) + (item.get("keywords") or [])))
        merges.append({"into_title": canonical.get("title"), "merged_source": item["source"], "reason": reason, "score": round(score, 4)})
    output = []
    for group in groups:
        row = dict(group["canonical"])
        row["sources"] = group["sources"]
        row["source_records"] = [{"source": r["source"], "source_record_id": r["source_record_id"]} for r in group["records"]]
        row["dedup_reasons"] = group["dedup_reasons"]
        output.append(row)
    return output, merges


class PublicationAdapter(Protocol):
    name: str
    def search_publications(self, query: str, *, limit: int = 20, **filters: Any) -> list[dict[str, Any]]: ...
    def get_publication(self, identifier: str) -> dict[str, Any] | None: ...
    def get_citations(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]: ...
    def get_references(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]: ...
    def get_author(self, identifier: str) -> dict[str, Any] | None: ...
    def get_fulltext_link(self, identifier: str) -> str | None: ...


@dataclass
class OpenAlexAdapter:
    name: str = "OpenAlex"

    def _client(self):
        return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": f"EnerTri/4.2 (mailto:{CONTACT_EMAIL})"})

    def _params(self, value: dict[str, Any]) -> dict[str, Any]:
        if not OPENALEX_API_KEY:
            raise RuntimeError("未配置 OpenAlex API Key")
        return {**value, "api_key": OPENALEX_API_KEY}

    def search_publications(self, query: str, *, limit: int = 20, **filters: Any) -> list[dict[str, Any]]:
        result = search_openalex(query, year_from=filters.get("year_from"), year_to=filters.get("year_to"), open_access=filters.get("open_access"), language=filters.get("language"), limit=limit)
        if result.get("source") != "OpenAlex":
            raise RuntimeError(result.get("warning") or "OpenAlex 未返回结果")
        return [normalize_publication(item, self.name) for item in result.get("items") or []]

    def _work(self, identifier: str) -> dict[str, Any] | None:
        endpoint = identifier
        doi = normalize_doi(identifier)
        if doi and not identifier.startswith("W") and "openalex.org/" not in identifier:
            endpoint = f"https://doi.org/{doi}"
        with self._client() as client:
            response = client.get(f"{OPENALEX_URL}/works/{quote(endpoint, safe=':/')}", params=self._params({}))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    def get_publication(self, identifier: str) -> dict[str, Any] | None:
        work = self._work(identifier)
        return normalize_publication(normalize_openalex_work(work), self.name) if work else None

    def get_citations(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]:
        work = self._work(identifier)
        if not work:
            return []
        openalex_id = str(work.get("id") or "").rsplit("/", 1)[-1]
        with self._client() as client:
            r = client.get(f"{OPENALEX_URL}/works", params=self._params({"filter": f"cites:{openalex_id}", "per_page": min(limit, 100)})); r.raise_for_status()
        return [normalize_publication(normalize_openalex_work(item), self.name) for item in r.json().get("results") or []]

    def get_references(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]:
        work = self._work(identifier)
        ids = (work or {}).get("referenced_works") or []
        rows: list[dict[str, Any]] = []
        for work_id in ids[:limit]:
            item = self.get_publication(str(work_id))
            if item: rows.append(item)
        return rows

    def get_author(self, identifier: str) -> dict[str, Any] | None:
        with self._client() as client:
            r = client.get(f"{OPENALEX_URL}/authors/{quote(identifier, safe=':/')}", params=self._params({}))
            if r.status_code == 404: return None
            r.raise_for_status(); data = r.json()
        return {"id": data.get("id"), "name": data.get("display_name"), "works_count": data.get("works_count"), "cited_by_count": data.get("cited_by_count"), "institutions": [i.get("display_name") for i in data.get("last_known_institutions") or []]}

    def get_fulltext_link(self, identifier: str) -> str | None:
        item = self.get_publication(identifier)
        return (item or {}).get("fulltext_url") or (item or {}).get("landing_page_url")


@dataclass
class CrossrefAdapter:
    name: str = "Crossref"

    def _client(self):
        return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": f"EnerTri/4.2 (mailto:{CONTACT_EMAIL})"})

    def _normalize_crossref(self, work: dict[str, Any]) -> dict[str, Any]:
        issued = ((work.get("issued") or {}).get("date-parts") or [[None]])[0]
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")])).strip() for a in work.get("author") or []]
        links = work.get("link") or []
        pdf = next((x.get("URL") for x in links if x.get("content-type") == "application/pdf"), None)
        item = {
            "id": work.get("DOI"), "doi": work.get("DOI"), "title": " ".join(work.get("title") or []) or "Untitled",
            "authors": authors, "year": issued[0] if issued else None, "journal": (work.get("container-title") or [None])[0],
            "citation_count": work.get("is-referenced-by-count") or 0, "abstract": work.get("abstract"),
            "landing_page_url": work.get("URL"), "fulltext_url": pdf, "open_access": bool(pdf),
        }
        return normalize_publication(item, self.name)

    def search_publications(self, query: str, *, limit: int = 20, **filters: Any) -> list[dict[str, Any]]:
        result = search_crossref(query, year_from=filters.get("year_from"), year_to=filters.get("year_to"), limit=limit)
        return [normalize_publication(item, self.name) for item in result.get("items") or []]

    def get_publication(self, identifier: str) -> dict[str, Any] | None:
        doi = normalize_doi(identifier)
        if not doi: return None
        with self._client() as client:
            r = client.get(f"{CROSSREF_URL}/works/{quote(doi, safe='')}", params={"mailto": CONTACT_EMAIL})
            if r.status_code == 404: return None
            r.raise_for_status(); work = (r.json().get("message") or {})
        return self._normalize_crossref(work)

    def get_citations(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]:
        # Crossref does not provide a direct cited-by works list in this API; query bibliographic DOI as a conservative fallback.
        doi = normalize_doi(identifier)
        if not doi: return []
        result = search_crossref(doi, limit=limit)
        return [normalize_publication(item, self.name) for item in result.get("items") or [] if normalize_doi(item.get("doi")) != doi]

    def get_references(self, identifier: str, *, limit: int = 20) -> list[dict[str, Any]]:
        doi = normalize_doi(identifier)
        if not doi: return []
        with self._client() as client:
            r = client.get(f"{CROSSREF_URL}/works/{quote(doi, safe='')}", params={"mailto": CONTACT_EMAIL}); r.raise_for_status()
        refs = (r.json().get("message") or {}).get("reference") or []
        return [normalize_publication({"id": x.get("DOI") or x.get("key"), "doi": x.get("DOI"), "title": x.get("article-title") or x.get("volume-title") or "Reference", "authors": [x.get("author")] if x.get("author") else [], "year": x.get("year")}, self.name) for x in refs[:limit]]

    def get_author(self, identifier: str) -> dict[str, Any] | None:
        return {"id": identifier, "name": identifier, "source": self.name, "note": "Crossref 公共 API 不提供稳定的作者实体接口。"}

    def get_fulltext_link(self, identifier: str) -> str | None:
        item = self.get_publication(identifier)
        return (item or {}).get("fulltext_url") or (item or {}).get("landing_page_url")


ADAPTERS: dict[str, PublicationAdapter] = {"openalex": OpenAlexAdapter(), "crossref": CrossrefAdapter()}


def search_publications(query: str, *, sources: list[str] | None = None, limit: int = 20, **filters: Any) -> dict[str, Any]:
    selected = [s.lower() for s in (sources or ["openalex", "crossref"]) if s.lower() in ADAPTERS]
    if not selected:
        raise ValueError("至少选择一个有效文献来源")
    all_items: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    for key in selected:
        adapter = ADAPTERS[key]
        try:
            rows = adapter.search_publications(query, limit=limit, **filters)
            all_items.extend(rows)
            source_status.append({"source": adapter.name, "ok": True, "count": len(rows)})
        except Exception as exc:
            source_status.append({"source": adapter.name, "ok": False, "count": 0, "error": str(exc)})
    if not all_items and source_status and all(not s["ok"] for s in source_status):
        raise RuntimeError("所有文献来源均不可用：" + "; ".join(f"{s['source']}: {s.get('error')}" for s in source_status))
    deduped, merges = deduplicate_publications(all_items)
    return {"query": query, "raw_count": len(all_items), "deduplicated_count": len(deduped), "duplicate_count": len(all_items) - len(deduped), "source_status": source_status, "dedup_merges": merges, "items": deduped}


def upsert_search_results(db: Session, result: dict[str, Any]) -> list[Publication]:
    saved: list[Publication] = []
    for item in result.get("items") or []:
        existing = None
        if item.get("doi"):
            existing = db.scalar(select(Publication).where(Publication.doi == item["doi"]))
        if not existing:
            candidates = db.scalars(select(Publication).where(Publication.normalized_title == item["normalized_title"]).limit(5)).all()
            probe = item
            for candidate in candidates:
                candidate_item = {"doi": candidate.doi, "normalized_title": candidate.normalized_title, "first_author": (json.loads(candidate.authors_json or "[]") or [None])[0], "year": candidate.year, "journal": candidate.journal}
                if duplicate_reason(candidate_item, probe)[0]:
                    existing = candidate; break
        if not existing:
            existing = Publication(title=item["title"], normalized_title=item["normalized_title"], doi=item.get("doi"), primary_source=(item.get("sources") or [item.get("source") or "unknown"])[0])
            db.add(existing); db.flush()
        existing.title = existing.title or item["title"]
        existing.doi = existing.doi or item.get("doi")
        existing.authors_json = json.dumps(item.get("authors") or [], ensure_ascii=False)
        existing.institutions_json = json.dumps(item.get("institutions") or [], ensure_ascii=False)
        existing.abstract = existing.abstract or item.get("abstract")
        existing.keywords_json = json.dumps(item.get("keywords") or [], ensure_ascii=False)
        existing.journal = existing.journal or item.get("journal")
        existing.year = existing.year or item.get("year")
        existing.citation_count = max(int(existing.citation_count or 0), int(item.get("citation_count") or 0))
        existing.open_access = bool(existing.open_access or item.get("open_access"))
        existing.landing_page_url = existing.landing_page_url or item.get("landing_page_url")
        existing.fulltext_url = existing.fulltext_url or item.get("fulltext_url")
        existing.metadata_json = json.dumps({"dedup_reasons": item.get("dedup_reasons") or []}, ensure_ascii=False)
        for source_record in item.get("source_records") or []:
            source_name, source_record_id = source_record["source"], str(source_record["source_record_id"])
            link = db.scalar(select(PublicationSource).where(PublicationSource.source_name == source_name, PublicationSource.source_record_id == source_record_id))
            if not link:
                db.add(PublicationSource(publication_id=existing.id, source_name=source_name, source_record_id=source_record_id, raw_json=None))
        saved.append(existing)
    db.commit()
    return saved


def publication_to_dict(db: Session, row: Publication) -> dict[str, Any]:
    sources = db.scalars(select(PublicationSource).where(PublicationSource.publication_id == row.id)).all()
    doi_url = f"https://doi.org/{row.doi}" if row.doi else None
    landing_url = row.landing_page_url or doi_url
    fulltext_url = row.fulltext_url or landing_url
    return {
        "id": row.id, "doi": row.doi, "title": row.title, "authors": json.loads(row.authors_json or "[]"),
        "institutions": json.loads(row.institutions_json or "[]"), "abstract": row.abstract, "keywords": json.loads(row.keywords_json or "[]"),
        "journal": row.journal, "year": row.year, "citation_count": row.citation_count, "open_access": row.open_access,
        "primary_source": row.primary_source, "sources": [s.source_name for s in sources], "landing_page_url": landing_url,
        "fulltext_url": fulltext_url, "doi_url": doi_url, "open_url": fulltext_url or landing_url or doi_url,
        "updated_at": row.updated_at,
    }
