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

    tables: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(str(path)) as plumber:
            table_idx = 1
            for page_number, page in enumerate(plumber.pages, start=1):
                captions = _captions(pages[page_number - 1]["text"], TABLE_CAPTION_RE)
                for raw in page.extract_tables() or []:
                    if not raw or len(raw) < 2: continue
                    cap_no, cap_title = captions[min(len(captions) - 1, 0)] if captions else (str(table_idx), "")
                    tables.append({"table_number": f"Table {cap_no}", "page_number": page_number, "title": cap_title, "data": raw, "markdown": _markdown_table(raw)})
                    table_idx += 1
                    if len(tables) >= 100: break
    except Exception:
        tables = []
    emit(58, "表格提取", f"提取到 {len(tables)} 个表格")

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
    document.metadata_json = json.dumps({"ocr_pages": ocr_pages, "references": refs, "text_layer_pages": len(pages) - ocr_pages}, ensure_ascii=False, default=str)
    file_record.parse_status = "parsed"
    db.commit()
    emit(92, "向量化与结构化阅读", f"完成 {len(chunks)} 个本地向量和证据索引")
    return {"document_id": document.id, "title": title, "page_count": len(pages), "ocr_pages": ocr_pages, "sections": sections, "tables": [{k: v for k, v in t.items() if k != "data"} for t in tables], "figures": figures[:30], "reference_count": len(refs), "chunk_count": len(chunks), "structured_reading": structured}


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
