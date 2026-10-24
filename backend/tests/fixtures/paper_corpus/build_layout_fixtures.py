"""Generate small, copyright-free layout fixtures for parser regression.

The fixture geometry mirrors common energy-paper layouts; real public-paper
anchors stay in manifest.json and can be mounted by an external evaluation
job without committing their binary contents to the repository.
"""
from __future__ import annotations

from pathlib import Path


def _table(page, x: float, y: float, number: int, width: float = 230, height: float = 100) -> None:
    page.insert_text((x, y - 8), f"Table {number} Energy conversion parameters", fontsize=8)
    cols, rows = 3, 3
    for row in range(rows + 1):
        page.draw_line((x, y + row * height / rows), (x + width, y + row * height / rows))
    for col in range(cols + 1):
        page.draw_line((x + col * width / cols, y), (x + col * width / cols, y + height))
    values = [["Case", "Power", "Efficiency"], [f"{number}A", "2.4 kW", "78%"], [f"{number}B", "2.8 kW", "81%"]]
    for row, values_row in enumerate(values):
        for col, value in enumerate(values_row):
            page.insert_text((x + col * width / cols + 5, y + row * height / rows + 20), value, fontsize=8)


def build_four_tables(path: str | Path) -> Path:
    import fitz
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((44, 42), "Space energy conversion system experimental results", fontsize=14)
    page.insert_text((44, 64), "Results and Discussion", fontsize=10)
    for index, (x, y) in enumerate(((44, 100), (320, 100), (44, 330), (320, 330)), start=1):
        _table(page, x, y, index, width=230 if x < 100 else 230, height=150)
    path.write_bytes(doc.tobytes(garbage=4, deflate=True))
    doc.close()
    return path


def build_two_column(path: str | Path) -> Path:
    import fitz
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((44, 42), "Thermal management for orbital power systems", fontsize=14)
    left = "Introduction\nOrbital energy systems require thermal control.\n\nMethods\nHeat transfer and radiator performance were measured."
    right = "Results\nThe radiator rejected 12 kW at the design point.\n\nConclusion\nThe design remains stable across the test envelope."
    page.insert_textbox(fitz.Rect(44, 80, 280, 780), left, fontsize=9)
    page.insert_textbox(fitz.Rect(315, 80, 550, 780), right, fontsize=9)
    path.write_bytes(doc.tobytes(garbage=4, deflate=True))
    doc.close()
    return path


def build_scanned(path: str | Path, *, chinese: bool = False) -> Path:
    import fitz
    path = Path(path)
    source = fitz.open()
    page = source.new_page(width=595, height=842)
    text = "摘要 这是中文扫描论文的能源动力研究结果与结论。" if chinese else "Abstract This scanned paper reports an energy conversion experiment."
    page.insert_text((52, 110), text, fontsize=13, fontname="china-s" if chinese else "helv")
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = pix.tobytes("png")
    source.close()
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=image)
    path.write_bytes(scanned.tobytes(garbage=4, deflate=True))
    scanned.close()
    return path
