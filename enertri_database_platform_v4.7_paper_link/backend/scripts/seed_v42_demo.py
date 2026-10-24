#!/usr/bin/env python
from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.database import SessionLocal
from app.models import Publication, PublicationSource
from app.publication_service import normalize_title

DEMO_PUBLICATIONS = [
    {
        "doi": "10.1016/j.jmatprotec.2026.118999",
        "title": "Laser Welding Parameter Optimization and Porosity Control in Q355 Steel",
        "authors": ["Li Ming", "Anna Petrova", "Chen Wei"],
        "institutions": ["EnerTri Joint Laboratory"],
        "abstract": "A cross-source demo record for evidence-first literature and paper knowledge workflows.",
        "keywords": ["laser welding", "porosity", "Q355 steel"],
        "journal": "Journal of Materials Processing Technology",
        "year": 2026,
        "citation_count": 18,
        "open_access": True,
        "primary_source": "OpenAlex",
        "sources": [("OpenAlex", "W-DEMO-V42-001"), ("Crossref", "10.1016/j.jmatprotec.2026.118999")],
    },
    {
        "doi": "10.1007/s00170-026-14242-1",
        "title": "Keyhole Stability and Pore Formation During High-Power Laser Welding",
        "authors": ["Wang Hao", "Elena Smirnova"],
        "institutions": ["Advanced Joining Research Center"],
        "abstract": "A second demo record retained as a unique publication after deduplication.",
        "keywords": ["keyhole", "pore formation", "laser welding"],
        "journal": "The International Journal of Advanced Manufacturing Technology",
        "year": 2026,
        "citation_count": 7,
        "open_access": False,
        "primary_source": "Crossref",
        "sources": [("Crossref", "10.1007/s00170-026-14242-1")],
    },
]


def main() -> None:
    with SessionLocal() as db:
        for item in DEMO_PUBLICATIONS:
            pub = db.scalar(select(Publication).where(Publication.doi == item["doi"]))
            if not pub:
                pub = Publication(
                    doi=item["doi"], title=item["title"], normalized_title=normalize_title(item["title"]),
                    authors_json=json.dumps(item["authors"], ensure_ascii=False), institutions_json=json.dumps(item["institutions"], ensure_ascii=False),
                    abstract=item["abstract"], keywords_json=json.dumps(item["keywords"], ensure_ascii=False), journal=item["journal"], year=item["year"],
                    citation_count=item["citation_count"], open_access=item["open_access"], primary_source=item["primary_source"],
                    metadata_json=json.dumps({"demo": True, "dedup_reasons": ["DOI 完全一致"] if len(item["sources"]) > 1 else []}, ensure_ascii=False),
                )
                db.add(pub); db.flush()
            for source_name, source_record_id in item["sources"]:
                exists = db.scalar(select(PublicationSource).where(PublicationSource.source_name == source_name, PublicationSource.source_record_id == source_record_id))
                if not exists:
                    db.add(PublicationSource(publication_id=pub.id, source_name=source_name, source_record_id=source_record_id, raw_json=json.dumps({"demo": True}, ensure_ascii=False)))
        db.commit()
    print({"ok": True, "demo_publications": len(DEMO_PUBLICATIONS), "cross_source_merged": 1})


if __name__ == "__main__":
    main()
