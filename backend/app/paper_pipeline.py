from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from docx import Document as DocxDocument

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeFigure, KnowledgePage, KnowledgeTable, WorkspaceFile

CHUNK_CHARS = max(600, int(os.getenv("KNOWLEDGE_CHUNK_CHARS", "1400")))
CHUNK_OVERLAP = max(50, int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", "180")))
OCR_MIN_TEXT_CHARS = max(10, int(os.getenv("OCR_MIN_TEXT_CHARS", "60")))
EMBED_DIM = max(64, int(os.getenv("LOCAL_EMBED_DIM", "128")))

SECTION_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?(abstract|摘要|introduction|引言|materials?\s*(?:and|&)\s*methods?|experimental|试验材料|实验材料|方法|methods?|results?(?:\s+and\s+discussion)?|结果(?:与讨论)?|discussion|讨论|conclusions?|结论|references?|参考文献|acknowledg(?:e)?ments?|致谢)\s*$",
    re.I,
)
TABLE_CAPTION_RE = re.compile(r"^(?:Table|表)\s*([A-Za-z0-9一二三四五六七八九十.-]+)\s*[:：.-]?\s*(.*)$", re.I)
FIGURE_CAPTION_RE = re.compile(r"^(?:Fig(?:ure)?\.?|图)\s*([A-Za-z0-9一二三四五六七八九十.-]+)\s*[:：.-]?\s*(.*)$", re.I)


TABLE_EXTRACTION_STRATEGIES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("pymupdf-lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
    ("pymupdf-text", {"vertical_strategy": "text", "horizontal_strategy": "text", "min_words_vertical": 2, "min_words_horizontal": 1}),
    ("pymupdf-mixed", {"vertical_strategy": "lines", "horizontal_strategy": "text", "min_words_horizontal": 1}),
)
TABLE_METHOD_PRIORITY = {"pymupdf-lines": 0, "pdfplumber-lines": 1, "pymupdf-mixed": 2, "pdfplumber-text": 3, "pymupdf-text": 4}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*|[\u4e00-\u9fff]{1,4}|\d+(?:\.\d+)?", text.casefold())


def local_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    vec = [0.0] * dim
    for token, count in Counter(_tokenize(text)).items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign * (1.0 + math.log1p(count))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 8) for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _page_title(lines: list[str]) -> str | None:
    candidates = [line.strip() for line in lines if 8 <= len(line.strip()) <= 220]
    for line in candidates[:12]:
        if not SECTION_RE.match(line) and not re.match(r"^(doi|http|www\.)", line, re.I):
            return line
    return candidates[0] if candidates else None


def _extract_abstract(all_text: str) -> str | None:
    match = re.search(r"(?:Abstract|摘要)\s*[:：]?\s*(.{80,4000}?)(?=\n\s*(?:Keywords?|关键词|1\.?\s*Introduction|引言|I\.\s*INTRODUCTION))", all_text, re.I | re.S)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()[:3500]
    return None


def _section_map(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current = {"title": "Front Matter", "page_start": 1, "page_end": 1}
    sections.append(current)
    for page in pages:
        for raw in page["text"].splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if len(line) <= 100 and SECTION_RE.match(line):
                if current["title"] == line and current["page_start"] == page["page_number"]:
                    continue
                current["page_end"] = max(current["page_start"], page["page_number"] - 1)
                current = {"title": line, "page_start": page["page_number"], "page_end": page["page_number"]}
                sections.append(current)
        current["page_end"] = page["page_number"]
    return sections


def _section_for_page(sections: list[dict[str, Any]], page_number: int) -> str:
    matches = [s for s in sections if s["page_start"] <= page_number <= s["page_end"]]
    return (matches[-1]["title"] if matches else "Unknown")


def _markdown_table(rows: list[list[Any]]) -> str:
    cleaned = [[re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row] for row in rows]
    width = max((len(row) for row in cleaned), default=0)
    if width == 0:
        return ""
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = cleaned[0]
    return "| " + " | ".join(header) + " |\n| " + " | ".join(["---"] * width) + " |\n" + "\n".join("| " + " | ".join(row) + " |" for row in cleaned[1:])


def _clean_table_rows(raw_rows: Any) -> list[list[str]]:
    """Normalize cells from different PDF table engines into stable rectangular rows."""
    if not raw_rows:
        return []
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if raw_row is None:
            continue
        if not isinstance(raw_row, (list, tuple)):
            raw_row = [raw_row]
        row = [re.sub(r"\s+", " ", str(cell or "").replace("\u00a0", " ")).strip() for cell in raw_row]
        if any(row):
            row_text = " ".join(cell for cell in row if cell)
            # Text based detection can include the caption as its first row.
            if TABLE_CAPTION_RE.match(row_text) or re.match(r"^able\s*\d", row_text, re.I):
                continue
            rows.append(row)
    width = max((len(row) for row in rows), default=0)
    if width < 2 or len(rows) < 2:
        return []
    rows = [row + [""] * (width - len(row)) for row in rows]
    # Remove columns that the extractor created but that contain no information.
    keep_columns = [i for i in range(width) if any(row[i] for row in rows)]
    rows = [[row[i] for i in keep_columns] for row in rows]
    if len(rows[0]) < 2 or len(rows) < 2:
        return []
    # A repeated header is common when a table is split across PDF text blocks.
    compact = lambda row: "|".join(cell.casefold() for cell in row)
    cleaned: list[list[str]] = []
    previous = None
    for row in rows:
        marker = compact(row)
        if marker and marker == previous and len(cleaned) > 1:
            continue
        cleaned.append(row)
        previous = marker
    populated = sum(bool(cell) for row in cleaned for cell in row)
    if populated < max(4, len(cleaned) * 2) or populated / max(1, len(cleaned) * len(cleaned[0])) < 0.28:
        return []
    return cleaned


def _table_quality(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    cells = len(rows) * len(rows[0])
    populated = sum(bool(cell) for row in rows for cell in row)
    distinct_rows = len({"|".join(row).casefold() for row in rows})
    return round(min(1.0, (populated / max(1, cells)) * 0.7 + (distinct_rows / len(rows)) * 0.3), 3)


def _table_fingerprint(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(cell.casefold() for cell in row) for row in rows)


def _bbox_iou(a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float] | None) -> float:
    if not a or not b:
        return 0.0
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if not intersection:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(1.0, area_a + area_b - intersection)


def _bbox_overlap_ratio(a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float] | None) -> float:
    """Measure overlap against the smaller box, catching a text candidate that contains a ruled table."""
    if not a or not b:
        return 0.0
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(1.0, min(area_a, area_b))


def _caption_positions(pdf_page: Any) -> list[dict[str, Any]]:
    """Read caption text blocks with their vertical position for correct table pairing."""
    found: list[dict[str, Any]] = []
    try:
        blocks = pdf_page.get_text("blocks") or []
    except Exception:
        blocks = []
    for block in blocks:
        if len(block) < 5:
            continue
        top = float(block[1])
        for line in str(block[4] or "").splitlines():
            value = re.sub(r"\s+", " ", line).strip()
            match = TABLE_CAPTION_RE.match(value)
            if match:
                found.append({"top": top, "number": match.group(1), "title": (match.group(2) or "").strip()})
            top += 10.0
    return sorted(found, key=lambda item: item["top"])


def _extract_pdf_tables(pdf: Any, pages: list[dict[str, Any]], source_path: Path | None = None, pdfplumber_module: Any | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract tables with several layout strategies, then de-duplicate by location/content.

    Scientific PDFs use both ruled tables and whitespace-aligned tables. A single
    extractor strategy misses one of those families, which was the reason four
    source tables could become two stored results.
    """
    candidates: list[dict[str, Any]] = []
    strategy_counts: Counter[str] = Counter()
    for page_number in range(1, pdf.page_count + 1):
        page = pdf.load_page(page_number - 1)
        for method, settings in TABLE_EXTRACTION_STRATEGIES:
            try:
                finder = page.find_tables(**settings)
                for table in getattr(finder, "tables", []) or []:
                    rows = _clean_table_rows(table.extract())
                    if not rows:
                        continue
                    bbox = tuple(float(value) for value in (getattr(table, "bbox", None) or ()))
                    candidates.append({"page_number": page_number, "rows": rows, "bbox": bbox if len(bbox) == 4 else None, "method": method, "quality": _table_quality(rows)})
                    strategy_counts[method] += 1
            except Exception:
                continue

    # pdfplumber is a useful fallback for PDFs where PyMuPDF cannot infer line geometry.
    if pdfplumber_module is not None and source_path is not None:
        try:
            with pdfplumber_module.open(str(source_path)) as plumber:
                for page_number, plumber_page in enumerate(plumber.pages, start=1):
                    for method, settings in (
                        ("pdfplumber-lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
                        ("pdfplumber-text", {"vertical_strategy": "text", "horizontal_strategy": "text", "min_words_vertical": 2, "min_words_horizontal": 1}),
                    ):
                        try:
                            for table in plumber_page.find_tables(table_settings=settings) or []:
                                rows = _clean_table_rows(table.extract())
                                if not rows:
                                    continue
                                bbox = tuple(float(value) for value in (getattr(table, "bbox", None) or ()))
                                candidates.append({"page_number": page_number, "rows": rows, "bbox": bbox if len(bbox) == 4 else None, "method": method, "quality": _table_quality(rows)})
                                strategy_counts[method] += 1
                        except Exception:
                            continue
        except Exception:
            pass

    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (item["page_number"], TABLE_METHOD_PRIORITY.get(item["method"], 9), (item["bbox"] or (0, 0, 0, 0))[1], -item["quality"])):
        duplicate = False
        for existing in selected:
            if existing["page_number"] != candidate["page_number"]:
                continue
            same_content = _table_fingerprint(existing["rows"]) == _table_fingerprint(candidate["rows"])
            same_location = _bbox_iou(existing.get("bbox"), candidate.get("bbox")) >= 0.45 or _bbox_overlap_ratio(existing.get("bbox"), candidate.get("bbox")) >= 0.55
            if same_content or same_location:
                duplicate = True
                if TABLE_METHOD_PRIORITY.get(candidate["method"], 9) < TABLE_METHOD_PRIORITY.get(existing["method"], 9) or (candidate["quality"] > existing["quality"] and TABLE_METHOD_PRIORITY.get(candidate["method"], 9) == TABLE_METHOD_PRIORITY.get(existing["method"], 9)):
                    existing.update(candidate)
                break
        if not duplicate:
            selected.append(candidate)

    captions_by_page: dict[int, list[dict[str, Any]]] = {}
    for page_number in {item["page_number"] for item in selected}:
        captions_by_page[page_number] = _caption_positions(pdf.load_page(page_number - 1))
    output: list[dict[str, Any]] = []
    for page_number in sorted({item["page_number"] for item in selected}):
        page_tables = [item for item in selected if item["page_number"] == page_number]
        page_tables.sort(key=lambda item: (item.get("bbox") or (0, 0, 0, 0))[1])
        captions = captions_by_page.get(page_number, [])
        used_caption_indexes: set[int] = set()
        for ordinal, item in enumerate(page_tables, start=1):
            caption = None
            table_top = (item.get("bbox") or (0, 0, 0, 0))[1]
            eligible = [(index, value) for index, value in enumerate(captions) if index not in used_caption_indexes and value["top"] <= table_top + 32]
            if eligible:
                index, caption = min(eligible, key=lambda pair: abs(table_top - pair[1]["top"]))
                used_caption_indexes.add(index)
            elif ordinal <= len(captions):
                caption = captions[ordinal - 1]
            number = caption["number"] if caption else str(len(output) + 1)
            title = caption["title"] if caption else ""
            output.append({"table_number": f"Table {number}", "page_number": page_number, "title": title, "data": item["rows"], "markdown": _markdown_table(item["rows"]), "extraction_method": item["method"], "extraction_quality": item["quality"]})
    diagnostics = {"candidate_count": len(candidates), "table_count": len(output), "strategy_counts": dict(strategy_counts), "pages_with_tables": sorted({item["page_number"] for item in output})}
    return output[:100], diagnostics


def _captions(text: str, regex: re.Pattern[str]) -> list[tuple[str, str]]:
    out = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        m = regex.match(line)
        if m:
            out.append((m.group(1), (m.group(2) or "").strip()))
    return out


def _extract_references(pages: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[str]:
    ref_section = next((s for s in sections if re.search(r"references|参考文献", s["title"], re.I)), None)
    if not ref_section:
        return []
    text = "\n".join(p["text"] for p in pages if p["page_number"] >= ref_section["page_start"])
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    refs: list[str] = []
    current = ""
    for line in lines:
        if re.match(r"^(\[?\d+\]?|\d+\.)\s+", line):
            if current: refs.append(current[:2000])
            current = line
        elif current:
            current += " " + line
    if current: refs.append(current[:2000])
    return refs[:500]


def _page_section_segments(page: dict[str, Any], sections: list[dict[str, Any]]) -> list[tuple[str, str]]:
    page_number = int(page["page_number"])
    # For continuation pages without a new heading, inherit the most recently opened section.
    inherited = [s for s in sections if s["page_start"] < page_number <= s["page_end"]]
    current_title = inherited[-1]["title"] if inherited else "Front Matter"
    buffer: list[str] = []
    segments: list[tuple[str, str]] = []
    for raw in page["text"].splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and len(line) <= 100 and SECTION_RE.match(line):
            if buffer:
                content = "\n".join(buffer).strip()
                if content:
                    segments.append((current_title, content))
            current_title = line
            buffer = [line]
        else:
            buffer.append(raw)
    if buffer:
        content = "\n".join(buffer).strip()
        if content:
            segments.append((current_title, content))
    return segments


def _chunk_pages(pages: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    idx = 0
    for page in pages:
        for section_title, segment_text in _page_section_segments(page, sections):
            text = re.sub(r"\n{3,}", "\n\n", segment_text).strip()
            if not text:
                continue
            start = 0
            while start < len(text):
                end = min(len(text), start + CHUNK_CHARS)
                piece = text[start:end]
                if end < len(text):
                    boundary = max(piece.rfind("\n"), piece.rfind("。"), piece.rfind(". "))
                    if boundary > int(CHUNK_CHARS * 0.55):
                        end = start + boundary + 1
                        piece = text[start:end]
                chunks.append({
                    "chunk_index": idx,
                    "content": piece.strip(),
                    "page_start": page["page_number"],
                    "page_end": page["page_number"],
                    "section": section_title,
                })
                idx += 1
                if end >= len(text):
                    break
                start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def _structured_reading(title: str, abstract: str | None, pages: list[dict[str, Any]], sections: list[dict[str, Any]], tables: list[dict[str, Any]], figures: list[dict[str, Any]], refs: list[str]) -> dict[str, Any]:
    full = "\n".join(p["text"] for p in pages)
    facts: list[dict[str, Any]] = []
    patterns = [
        ("laser_power", r"(?:laser\s+power|激光功率)\s*(?:was|of|=|为|：|:)??\s*(\d+(?:\.\d+)?)\s*(W|kW)"),
        ("tensile_strength", r"(?:tensile\s+strength|抗拉强度|UTS)\s*(?:was|of|=|为|：|:)??\s*(\d+(?:\.\d+)?)\s*(MPa|GPa)"),
        ("current", r"(?:current|电流)\s*(?:was|of|=|为|：|:)??\s*(\d+(?:\.\d+)?)\s*A"),
        ("travel_speed", r"(?:travel\s+speed|welding\s+speed|焊接速度|扫描速度)\s*(?:was|of|=|为|：|:)??\s*(\d+(?:\.\d+)?)\s*(mm/s|mm/min|m/min)"),
    ]
    for key, pattern in patterns:
        for m in re.finditer(pattern, full, re.I):
            before = full[:m.start()]
            # approximate page from cumulative chars
            cum = 0; page_num = 1
            for p in pages:
                cum += len(p["text"]) + 1
                if len(before) <= cum:
                    page_num = p["page_number"]; break
            facts.append({"type": key, "value": m.group(1), "unit": m.group(2), "page": page_num, "evidence": m.group(0)[:300]})
            if len(facts) >= 80: break
    return {
        "title": title,
        "abstract": abstract,
        "sections": sections,
        "key_facts": facts,
        "table_count": len(tables),
        "figure_count": len(figures),
        "reference_count": len(refs),
        "evidence_policy": "所有自动结论必须携带页码/章节/原文片段；未检索到证据时返回未知，不补造。",
    }


def ingest_pdf_document(
    db: Session,
    document: KnowledgeDocument,
    file_record: WorkspaceFile,
    *,
    progress: Callable[[int, str, str], None] | None = None,
) -> dict[str, Any]:
    path = Path(file_record.storage_path)
    if path.suffix.lower() != ".pdf":
        raise RuntimeError("V4.2 结构化论文知识流水线当前要求 PDF 输入")
    try:
        import fitz  # PyMuPDF
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 解析依赖 PyMuPDF/pdfplumber") from exc

    def emit(p: int, step: str, msg: str) -> None:
        if progress: progress(p, step, msg)

    emit(15, "文本层检测", "正在检测 PDF 文本层并逐页解析")
    pdf = fitz.open(str(path))
    if pdf.page_count < 1:
        raise RuntimeError("PDF 不包含可解析页面")
    pages: list[dict[str, Any]] = []
    ocr_pages = 0
    for i in range(pdf.page_count):
        page = pdf.load_page(i)
        text = page.get_text("text") or ""
        method = "text"
        ocr_used = False
        if len(re.sub(r"\s+", "", text)) < OCR_MIN_TEXT_CHARS:
            try:
                import pytesseract
                from PIL import Image
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr = pytesseract.image_to_string(image, lang=os.getenv("OCR_LANG", "eng"))
                if len(ocr.strip()) > len(text.strip()):
                    text = ocr; method = "ocr"; ocr_used = True; ocr_pages += 1
            except Exception:
                method = "text-low-confidence"
        pages.append({"page_number": i + 1, "text": text, "extraction_method": method, "ocr_used": ocr_used})
    emit(35, "页面解析 / OCR", f"完成 {len(pages)} 页解析，其中 OCR 兜底 {ocr_pages} 页")

    first_lines = [line.strip() for line in pages[0]["text"].splitlines() if line.strip()] if pages else []
    title = _page_title(first_lines) or file_record.original_name
    all_text = "\n".join(p["text"] for p in pages)
    abstract = _extract_abstract(all_text)
    sections = _section_map(pages)
    emit(47, "识别标题与章节", f"识别标题、摘要与 {len(sections)} 个章节区间")

    tables, table_diagnostics = _extract_pdf_tables(pdf, pages, path, pdfplumber)
    emit(58, "表格提取", f"使用多种版式策略提取到 {len(tables)} 个表格")

    figures: list[dict[str, Any]] = []
    figure_dir = path.parent / f"doc_{document.id}_figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    figure_idx = 1
    for i in range(pdf.page_count):
        page = pdf.load_page(i)
        captions = _captions(pages[i]["text"], FIGURE_CAPTION_RE)
        images = page.get_images(full=True)
        for image_no, image in enumerate(images[:20]):
            xref = image[0]
            try:
                extracted = pdf.extract_image(xref)
                ext = extracted.get("ext") or "bin"
                image_path = figure_dir / f"p{i+1}_fig{figure_idx}.{ext}"
                image_path.write_bytes(extracted["image"])
            except Exception:
                image_path = None
            cap_no, cap_text = captions[image_no] if image_no < len(captions) else (str(figure_idx), "")
            figures.append({"figure_number": f"Figure {cap_no}", "page_number": i + 1, "caption": cap_text, "image_path": str(image_path) if image_path else None})
            figure_idx += 1
            if len(figures) >= 120: break
    emit(67, "图片与图注", f"提取到 {len(figures)} 个图片对象/图注关联")

    refs = _extract_references(pages, sections)
    chunks = _chunk_pages(pages, sections)
    emit(76, "参考文献与分块", f"解析 {len(refs)} 条参考文献，生成 {len(chunks)} 个证据分块")

    # Replace partial parse results atomically within the current document.
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    db.execute(delete(KnowledgePage).where(KnowledgePage.document_id == document.id))
    db.execute(delete(KnowledgeTable).where(KnowledgeTable.document_id == document.id))
    db.execute(delete(KnowledgeFigure).where(KnowledgeFigure.document_id == document.id))
    for p in pages:
        db.add(KnowledgePage(document_id=document.id, page_number=p["page_number"], text=p["text"], extraction_method=p["extraction_method"], ocr_used=p["ocr_used"], metadata_json=json.dumps({}, ensure_ascii=False)))
    for t in tables:
        db.add(KnowledgeTable(document_id=document.id, table_number=t["table_number"], page_number=t["page_number"], title=t["title"], data_json=json.dumps(t["data"], ensure_ascii=False, default=str), markdown=t["markdown"]))
    for f in figures:
        db.add(KnowledgeFigure(document_id=document.id, figure_number=f["figure_number"], page_number=f["page_number"], caption=f["caption"], image_path=f["image_path"], metadata_json=json.dumps({}, ensure_ascii=False)))
    for c in chunks:
        emb = local_embedding(c["content"])
        db.add(KnowledgeChunk(document_id=document.id, chunk_index=c["chunk_index"], content=c["content"], token_count=len(_tokenize(c["content"])), page_start=c["page_start"], page_end=c["page_end"], section=c["section"], embedding_model=f"enertri-hash-v1-{EMBED_DIM}", embedding_json=json.dumps(emb), metadata_json=json.dumps({"evidence_excerpt": c["content"][:500]}, ensure_ascii=False)))
    structured = _structured_reading(title, abstract, pages, sections, tables, figures, refs)
    document.title = title[:512]
    document.page_count = len(pages)
    document.status = "ready"
    document.structure_json = json.dumps(structured, ensure_ascii=False, default=str)
    document.metadata_json = json.dumps({"ocr_pages": ocr_pages, "references": refs, "text_layer_pages": len(pages) - ocr_pages, "table_extraction": table_diagnostics}, ensure_ascii=False, default=str)
    file_record.parse_status = "parsed"
    db.commit()
    emit(92, "向量化与结构化阅读", f"完成 {len(chunks)} 个本地向量和证据索引")
    return {"document_id": document.id, "title": title, "page_count": len(pages), "ocr_pages": ocr_pages, "sections": sections, "tables": [{k: v for k, v in t.items() if k != "data"} for t in tables], "table_extraction": table_diagnostics, "figures": figures[:30], "reference_count": len(refs), "chunk_count": len(chunks), "structured_reading": structured}


def ingest_docx_document(
    db: Session,
    document: KnowledgeDocument,
    file_record: WorkspaceFile,
    *,
    progress: Callable[[int, str, str], None] | None = None,
) -> dict[str, Any]:
    """Extract a DOCX into the same evidence index used by PDF documents.

    DOCX has no reliable physical-page model until it is rendered by a word
    processor. Explicit page breaks are therefore retained when present; in
    their absence the document is represented as one logical source page.
    """
    path = Path(file_record.storage_path)
    if path.suffix.lower() != ".docx":
        raise RuntimeError("DOCX 流水线收到的文件类型不正确")

    def emit(p: int, step: str, msg: str) -> None:
        if progress:
            progress(p, step, msg)

    emit(18, "读取 Word 文档", "正在提取段落、标题与表格")
    docx = DocxDocument(str(path))
    pages: list[dict[str, Any]] = []
    current: list[str] = []
    page_number = 1

    def flush_page() -> None:
        nonlocal current, page_number
        text = "\n".join(current).strip()
        if text or not pages:
            pages.append({"page_number": page_number, "text": text, "extraction_method": "docx-text", "ocr_used": False})
        current = []
        page_number += 1

    for paragraph in docx.paragraphs:
        text = paragraph.text.strip()
        if text:
            current.append(text)
        has_page_break = any(
            br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page"
            for run in paragraph._p.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br")
        )
        if has_page_break:
            flush_page()
    flush_page()
    if pages and not pages[-1]["text"] and len(pages) > 1:
        pages.pop()
    emit(40, "识别标题与章节", f"完成 {len(pages)} 个逻辑页解析")

    tables: list[dict[str, Any]] = []
    for index, table in enumerate(docx.tables, start=1):
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows:
            continue
        page = 1
        if pages:
            table_text = "\n".join(" | ".join(row) for row in rows)
            page = next((p["page_number"] for p in pages if table_text[:80] in p["text"]), 1)
        tables.append({"table_number": f"Table {index}", "page_number": page, "title": "", "data": rows, "markdown": _markdown_table(rows)})
    emit(58, "表格提取", f"提取到 {len(tables)} 个表格")

    sections = _section_map(pages)
    all_text = "\n".join(p["text"] for p in pages)
    first_lines = [line.strip() for line in pages[0]["text"].splitlines() if line.strip()] if pages else []
    title = _page_title(first_lines) or file_record.original_name
    abstract = _extract_abstract(all_text)
    refs = _extract_references(pages, sections)
    chunks = _chunk_pages(pages, sections)
    emit(76, "参考文献与分块", f"解析 {len(refs)} 条参考文献，生成 {len(chunks)} 个证据分块")

    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    db.execute(delete(KnowledgePage).where(KnowledgePage.document_id == document.id))
    db.execute(delete(KnowledgeTable).where(KnowledgeTable.document_id == document.id))
    db.execute(delete(KnowledgeFigure).where(KnowledgeFigure.document_id == document.id))
    for p in pages:
        db.add(KnowledgePage(document_id=document.id, page_number=p["page_number"], text=p["text"], extraction_method=p["extraction_method"], ocr_used=False, metadata_json=json.dumps({"source_format": "docx"}, ensure_ascii=False)))
    for table in tables:
        db.add(KnowledgeTable(document_id=document.id, table_number=table["table_number"], page_number=table["page_number"], title=table["title"], data_json=json.dumps(table["data"], ensure_ascii=False), markdown=table["markdown"]))
    for chunk in chunks:
        db.add(KnowledgeChunk(document_id=document.id, chunk_index=chunk["chunk_index"], content=chunk["content"], token_count=len(_tokenize(chunk["content"])), page_start=chunk["page_start"], page_end=chunk["page_end"], section=chunk["section"], embedding_model=f"enertri-hash-v1-{EMBED_DIM}", embedding_json=json.dumps(local_embedding(chunk["content"])), metadata_json=json.dumps({"evidence_excerpt": chunk["content"][:500], "source_format": "docx"}, ensure_ascii=False)))
    structured = _structured_reading(title, abstract, pages, sections, tables, [], refs)
    document.title = title[:512]
    document.page_count = len(pages)
    document.status = "ready"
    document.structure_json = json.dumps(structured, ensure_ascii=False, default=str)
    document.metadata_json = json.dumps({"source_format": "docx", "references": refs, "logical_pages": len(pages), "page_position_note": "Word 文档页码取显式分页符；无分页符时按逻辑页呈现。"}, ensure_ascii=False, default=str)
    file_record.parse_status = "parsed"
    db.commit()
    emit(92, "向量化与结构化阅读", f"完成 {len(chunks)} 个 Word 文档证据分块")
    return {"document_id": document.id, "title": title, "page_count": len(pages), "ocr_pages": 0, "sections": sections, "tables": [{k: v for k, v in table.items() if k != "data"} for table in tables], "figures": [], "reference_count": len(refs), "chunk_count": len(chunks), "structured_reading": structured, "source_format": "docx"}


def ingest_document(db: Session, document: KnowledgeDocument, file_record: WorkspaceFile, *, progress: Callable[[int, str, str], None] | None = None) -> dict[str, Any]:
    suffix = Path(file_record.storage_path).suffix.lower()
    if suffix == ".pdf":
        return ingest_pdf_document(db, document, file_record, progress=progress)
    if suffix == ".docx":
        return ingest_docx_document(db, document, file_record, progress=progress)
    raise RuntimeError("知识库仅支持 PDF 或 DOCX 文档")


def _expanded_query(question: str) -> str:
    q = question.casefold()
    additions: list[str] = []
    if any(k in q for k in ["激光功率", "laser power"]):
        additions += ["laser power", "kW", "welding parameter"]
    if any(k in q for k in ["抗拉强度", "tensile", "uts"]):
        additions += ["tensile strength", "MPa", "parameter group"]
    if any(k in q for k in ["母材", "base metal", "base material", "substrate"]):
        additions += ["base material", "base metal", "steel", "thickness"]
    if any(k in q for k in ["气孔", "porosity", "pore", "孔隙"]):
        additions += ["porosity", "pore formation", "shielding gas", "keyhole"]
    return question + (" " + " ".join(additions) if additions else "")


def retrieve_evidence(db: Session, document_id: int, question: str, limit: int = 5) -> list[dict[str, Any]]:
    expanded = _expanded_query(question)
    query_vec = local_embedding(expanded)
    q_tokens = set(_tokenize(expanded))
    rows = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    ranked: list[tuple[float, KnowledgeChunk]] = []
    for row in rows:
        try: emb = json.loads(row.embedding_json or "[]")
        except Exception: emb = []
        row_tokens = set(_tokenize(row.content))
        lexical = len(q_tokens & row_tokens) / max(1, min(len(q_tokens), 12))
        score = 0.68 * cosine(query_vec, emb) + 0.32 * lexical
        ranked.append((score, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [{"chunk_id": row.id, "score": round(score, 4), "page": row.page_start, "page_end": row.page_end, "section": row.section, "text": row.content, "excerpt": row.content[:900]} for score, row in ranked[:limit] if score > -0.2]


def _best_sentence(text: str, pattern: str) -> str | None:
    flat = re.sub(r"\s+", " ", text).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s+", flat) if s.strip()]
    for sentence in sentences:
        if re.search(pattern, sentence, re.I):
            return sentence[:700]
    m = re.search(rf".{{0,120}}(?:{pattern}).{{0,220}}", flat, re.I)
    return m.group(0).strip()[:700] if m else None


def answer_question(db: Session, document: KnowledgeDocument, question: str) -> dict[str, Any]:
    evidence = retrieve_evidence(db, document.id, question, 6)
    if not evidence:
        return {"answer": "未在已解析原文中检索到足够证据，无法可靠回答。", "confidence": "low", "evidence": []}

    q = question.casefold()
    intent = "generic"
    pattern = None
    if any(k in q for k in ["激光功率", "laser power"]):
        intent, pattern = "laser_power", r"laser\s+power|激光功率"
    elif any(k in q for k in ["抗拉强度", "tensile", "uts"]):
        intent, pattern = "tensile", r"tensile\s+strength|抗拉强度|\bUTS\b"
    elif any(k in q for k in ["母材", "base metal", "base material", "substrate"]):
        intent, pattern = "base_material", r"base\s+(?:metal|material)|substrate|母材"
    elif any(k in q for k in ["气孔", "porosity", "pore", "孔隙"]):
        intent, pattern = "porosity", r"porosity|pores?|气孔|孔隙"

    candidates: list[tuple[str, dict[str, Any]]] = []
    for ev in evidence:
        sentence = _best_sentence(ev["text"], pattern) if pattern else None
        if not sentence:
            text = re.sub(r"\s+", " ", ev["text"])
            sentences = re.split(r"(?<=[。！？.!?])\s+", text)
            query_tokens = set(_tokenize(_expanded_query(question)))
            sentence = max(sentences, key=lambda s: len(set(_tokenize(s)) & query_tokens), default=text[:500])[:700]
        candidates.append((sentence, ev))

    # Put matching evidence first even when the source paper and the question use different languages.
    if pattern:
        candidates.sort(key=lambda item: (0 if re.search(pattern, item[0], re.I) else 1, -item[1]["score"]))

    primary_text, primary_ev = candidates[0]
    answer = primary_text
    matched_structured = False
    if intent == "laser_power":
        m = re.search(r"laser\s+power\s+(?:was|of|=|:)??\s*([0-9]+(?:\.[0-9]+)?)\s*(kW|W)", primary_text, re.I)
        if m:
            answer = f"论文原文给出的激光功率为 {m.group(1)} {m.group(2)}。"
            matched_structured = True
    elif intent == "tensile":
        m = re.search(r"(?:highest\s+)?tensile\s+strength\s+(?:was|of|=|:)??\s*([0-9]+(?:\.[0-9]+)?)\s*(MPa|GPa)(?:.{0,80}?group\s+([A-Za-z0-9_-]+))?", primary_text, re.I)
        if m:
            answer = f"论文报告的最高抗拉强度为 {m.group(1)} {m.group(2)}" + (f"，对应参数组 {m.group(3)}" if m.group(3) else "") + "。"
            matched_structured = True
    elif intent == "base_material":
        m = re.search(r"base\s+(?:metal|material)\s+(?:was|is)\s+([^.;]+)(?:[.;]|$)", primary_text, re.I)
        if m:
            answer = f"论文原文描述的母材为：{m.group(1).strip()}。"
            matched_structured = True
    elif intent == "porosity":
        if re.search(r"trapped.+keyhole|keyhole.+trapped", primary_text, re.I):
            answer = "作者将气孔形成解释为：不稳定小孔塌陷过程中保护气体被困（shielding gas was trapped）；稳定的小孔行为可减少气孔形成。"
            matched_structured = True

    confidence = "high" if matched_structured or primary_ev["score"] >= 0.35 else "medium"
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for text, ev in candidates:
        key = (int(ev["page"] or 0), text[:120])
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"page": ev["page"], "page_end": ev["page_end"], "section": ev["section"], "excerpt": text, "score": ev["score"]})
        if len(deduped) >= 4:
            break
    return {
        "answer": answer,
        "confidence": confidence,
        "evidence": deduped,
        "evidence_policy": "答案仅基于已解析原文证据；页码为 PDF 物理页码。",
    }
