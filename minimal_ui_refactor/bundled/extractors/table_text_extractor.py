# table_text_extractor.py
from base_extractor import BaseExtractor
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from collections import defaultdict
import statistics

BBox = Tuple[float, float, float, float]

@dataclass
class Cell:
    r: int
    c: int
    rowspan: int
    colspan: int
    text: str


# -------------------------
# Geometry/grid helpers
# -------------------------
def _median_dim(elems, axis: str = "y") -> float:
    vals = []
    for e in elems:
        x0, y0, x1, y1 = e["bbox"]
        vals.append((y1 - y0) if axis == "y" else (x1 - x0))
    return statistics.median(vals) if vals else 0.0


def _indices_covered(bounds: List[float], a0: float, a1: float, min_frac: float = 0.5) -> Tuple[int, int]:
    """
    Given axis bounds [b0,b1,b2,...], return inclusive index range (j0,j1) of bands
    that cover at least min_frac of [a0,a1]. If none meet threshold, snap to nearest band.
    """
    covered = []
    for j in range(len(bounds) - 1):
        b0, b1 = bounds[j], bounds[j + 1]
        inter = max(0.0, min(a1, b1) - max(a0, b0))
        length = max(1e-6, a1 - a0)
        if inter / length >= min_frac:
            covered.append(j)
    if not covered and (len(bounds) > 1):
        centers = [(bounds[j] + bounds[j + 1]) / 2.0 for j in range(len(bounds) - 1)]
        ctr = (a0 + a1) / 2.0
        j = min(range(len(centers)), key=lambda k: abs(centers[k] - ctr))
        covered = [j]
    return (min(covered), max(covered)) if covered else (0, 0)


def _cluster_intervals(elems, axis: str = "y", k: float = 0.75) -> List[List[int]]:
    """
    Lightweight single-linkage on 1D intervals, tolerance scaled by median element size.
    Returns list of clusters of element indices.
    """
    ivals = []
    for i, e in enumerate(elems):
        x0, y0, x1, y1 = e["bbox"]
        a0, a1 = (y0, y1) if axis == "y" else (x0, x1)
        ivals.append((a0, a1, i))
    ivals.sort(key=lambda t: t[0])

    med = _median_dim(elems, axis=axis)
    tau = (k * med) if med > 0 else 2.0

    clusters: List[List[int]] = []
    cur: List[int] = []
    cur_end = float("-inf")
    for a0, a1, i in ivals:
        if not cur:
            cur = [i]
            cur_end = a1
        elif a0 <= cur_end + tau:
            cur.append(i)
            cur_end = max(cur_end, a1)
        else:
            clusters.append(cur)
            cur = [i]
            cur_end = a1
    if cur:
        clusters.append(cur)
    return clusters


def _band_centers_and_bounds(elems, clusters: List[List[int]], axis: str = "y") -> Tuple[List[float], List[float]]:
    """
    From clustered intervals, produce sorted band centers and expanded bounds.
    """
    stats = []
    for idxs in clusters:
        coords = []
        for i in idxs:
            x0, y0, x1, y1 = elems[i]["bbox"]
            a0, a1 = (y0, y1) if axis == "y" else (x0, x1)
            coords.append((a0, a1))
        lo = min(a0 for a0, _ in coords)
        hi = max(a1 for _, a1 in coords)
        c = (lo + hi) / 2.0
        stats.append((lo, hi, c))

    stats.sort(key=lambda t: t[2])
    centers = [c for _, _, c in stats]

    bounds: List[float] = []
    if stats:
        # midpoints between cluster ends/starts
        mids = [(stats[i][1] + stats[i + 1][0]) / 2 for i in range(len(stats) - 1)]
        default_pad = statistics.median([(hi - lo) for lo, hi, _ in stats]) if len(stats) > 1 else (stats[-1][1] - stats[0][0])
        bounds = [stats[0][0] - default_pad / 2] + mids + [stats[-1][1] + default_pad / 2]
    return centers, bounds


def build_table(elements, y_k=0.75, x_k=0.75, min_axis_frac=0.5, span_guard=0.2):
    """
    Legacy builder that both derives bounds and anchors text groups. Still used in fallback.
    """
    if not elements:
        return [], 0, 0, [], []

    row_clusters = _cluster_intervals(elements, "y", y_k)
    col_clusters = _cluster_intervals(elements, "x", x_k)
    _, row_bounds = _band_centers_and_bounds(elements, row_clusters, "y")
    _, col_bounds = _band_centers_and_bounds(elements, col_clusters, "x")
    n_rows = max(0, len(row_bounds) - 1)
    n_cols = max(0, len(col_bounds) - 1)

    med_h = _median_dim(elements, "y") or 1.0
    med_w = _median_dim(elements, "x") or 1.0

    def crosses(bounds, i0, i1, a0, a1, guard):
        if i1 == i0:
            return i0, i1
        while i0 < i1 and (a1 - bounds[i0 + 1]) < guard:
            i0 += 1
        while i1 > i0 and (bounds[i1] - a0) < guard:
            i1 -= 1
        return i0, i1

    anchor_map = {}
    for e in elements:
        x0, y0, x1, y1 = e["bbox"]
        r0, r1 = _indices_covered(row_bounds, y0, y1, min_axis_frac)
        c0, c1 = _indices_covered(col_bounds, x0, x1, min_axis_frac)
        r0, r1 = crosses(row_bounds, r0, r1, y0, y1, span_guard * med_h)
        c0, c1 = crosses(col_bounds, c0, c1, x0, y1, span_guard * med_w)  # x-axis; using y1 is harmless here
        anchor_map.setdefault((r0, c0), []).append({**e, "r1": r1, "c1": c1})

    cells = []
    for (r, c), group in anchor_map.items():
        r1 = max(g["r1"] for g in group)
        c1 = max(g["c1"] for g in group)
        group.sort(key=lambda g: (g["bbox"][1], g["bbox"][0]))
        text = "\n".join(t.strip() for t in [g["text"] for g in group] if t and t.strip())
        cells.append(Cell(r=r, c=c, rowspan=r1 - r + 1, colspan=c1 - c + 1, text=text))

    return cells, n_rows, n_cols, row_bounds, col_bounds


def cells_to_html(cells: List[Cell], n_rows: int, n_cols: int) -> str:
    skip = [[False] * n_cols for _ in range(n_rows)]
    by_pos = {(c.r, c.c): c for c in cells}
    rows = []
    for r in range(n_rows):
        tds = []
        c = 0
        while c < n_cols:
            if skip[r][c]:
                c += 1
                continue
            cell = by_pos.get((r, c))
            if cell:
                for rr in range(r, r + cell.rowspan):
                    for cc in range(c, c + cell.colspan):
                        if rr == r and cc == c:
                            continue
                        skip[rr][cc] = True
                attrs = []
                if cell.rowspan > 1:
                    attrs.append(f'rowspan="{cell.rowspan}"')
                if cell.colspan > 1:
                    attrs.append(f'colspan="{cell.colspan}"')
                safe = (cell.text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                tds.append(f"<td {' '.join(attrs)}>{safe}</td>")
                c += cell.colspan
            else:
                tds.append("<td></td>")
                c += 1
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        + "".join(rows)
        + "</table>"
    )


# -------------------------
# New helpers for split responsibilities
# -------------------------
def _bounds_from_structs(structs: List[Dict[str, Any]]) -> Tuple[List[float], List[float]]:
    """
    Build row/column bounds strictly from structure boxes:
      - rows: 'table row' and 'table column header'
      - cols: 'table column'
    """
    rows_like = []
    cols_like = []

    for s in structs:
        label = (s.get("label") or "").lower()
        bb = s.get("bbox_crop") or s.get("bbox") or {}
        try:
            x0 = float(bb["x1"])
            y0 = float(bb["y1"])
            x1 = float(bb["x2"])
            y1 = float(bb["y2"])
        except Exception:
            continue

        if label in {"table row", "table column header"}:
            rows_like.append({"bbox": (x0, y0, x1, y1)})
        elif label in {"table column"}:
            cols_like.append({"bbox": (x0, y0, x1, y1)})

    r_clusters = _cluster_intervals(rows_like, "y", 0.75) if rows_like else []
    c_clusters = _cluster_intervals(cols_like, "x", 0.75) if cols_like else []
    _, row_bounds = _band_centers_and_bounds(rows_like, r_clusters, "y") if rows_like else ([], [])
    _, col_bounds = _band_centers_and_bounds(cols_like, c_clusters, "x") if cols_like else ([], [])
    return row_bounds, col_bounds


def _collect_token_elements(structs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Gather token/word/line-level text elements with bboxes from any structure.
    Tries common keys: 'ocr_tokens', 'tokens', 'words', 'lines'.
    Each returned element is {'text': str, 'bbox': (x0,y0,x1,y1)}.
    """
    elements: List[Dict[str, Any]] = []
    for s in structs:
        for key in ("ocr_tokens", "tokens", "words", "lines"):
            arr = s.get(key, [])
            if not isinstance(arr, list):
                continue
            for t in arr:
                tb = t.get("bbox") or t.get("bbox_crop") or {}
                # Support dict {'x1','y1','x2','y2'} or list/tuple (x0,y0,x1,y1)
                if isinstance(tb, dict):
                    try:
                        x0 = float(tb["x1"])
                        y0 = float(tb["y1"])
                        x1 = float(tb["x2"])
                        y1 = float(tb["y2"])
                    except Exception:
                        continue
                else:
                    try:
                        x0, y0, x1, y1 = map(float, tb)
                    except Exception:
                        continue
                txt = (t.get("text") or t.get("ocr_text") or "").strip()
                if txt:
                    elements.append({"text": txt, "bbox": (x0, y0, x1, y1)})
    return elements


# -------------------------
# Extractor
# -------------------------
class TableTextExtractor(BaseExtractor):
    """
    Consumes TableScraper output:
      - scrape['tables'] -> list of {
            'page_number': int (1-based),
            'structures': [
                {
                  'label': str,
                  'bbox_crop' or 'bbox': {x1,y1,x2,y2},
                  # optional token arrays with bboxes:
                  'ocr_tokens' | 'tokens' | 'words' | 'lines': [{text, bbox{...}}, ...],
                  'ocr_text': str (fallback)
                }, ...
            ]
        }

    Produces per-page HTML concatenating all detected tables (span-aware).
    """

    # Kept for fallback use if token bboxes are missing
    TABLE_LABELS = {"table row", "table column", "table column header", "table spanning cell"}

    def extract(self):
        scrape = self.scrape_output or {}
        tables = scrape.get("tables", [])
        page_html: Dict[int, List[str]] = {}

        for tbl in tables:
            page_num = int(tbl.get("page_number", 0))  # assumed 1-based
            structs = tbl.get("structures", []) or []

            # 1) Derive row/column bounds from structure boxes
            row_bounds, col_bounds = _bounds_from_structs(structs)

            # If we lack either dimension, or degenerate bands, fallback to legacy grouping
            if not row_bounds or not col_bounds or len(row_bounds) < 2 or len(col_bounds) < 2:
                elements = []
                for s in structs:
                    label = (s.get("label") or "").lower()
                    if label not in self.TABLE_LABELS:
                        continue
                    bb = s.get("bbox_crop") or s.get("bbox") or {}
                    try:
                        x0 = float(bb["x1"])
                        y0 = float(bb["y1"])
                        x1 = float(bb["x2"])
                        y1 = float(bb["y2"])
                    except Exception:
                        continue
                    text = (s.get("ocr_text") or "").strip()
                    if text:
                        elements.append({"text": text, "bbox": (x0, y0, x1, y1)})

                if not elements:
                    continue

                cells, nr, nc, _, _ = build_table(elements)
                html_tbl = cells_to_html(cells, nr, nc)
                page_html.setdefault(page_num, []).append(html_tbl)
                continue

            # 2) Collect token-level text elements to place into the grid
            token_elems = _collect_token_elements(structs)

            # If tokens unavailable, fallback to structure-level text (coarser placement)
            if not token_elems:
                for s in structs:
                    bb = s.get("bbox_crop") or s.get("bbox") or {}
                    try:
                        x0 = float(bb["x1"])
                        y0 = float(bb["y1"])
                        x1 = float(bb["x2"])
                        y1 = float(bb["y2"])
                    except Exception:
                        continue
                    text = (s.get("ocr_text") or "").strip()
                    if text:
                        token_elems.append({"text": text, "bbox": (x0, y0, x1, y1)})

            if not token_elems:
                # nothing to place
                continue

            # 3) Place tokens into cells using the precomputed bounds
            n_rows = max(0, len(row_bounds) - 1)
            n_cols = max(0, len(col_bounds) - 1)

            med_h = _median_dim(token_elems, "y") or 1.0
            med_w = _median_dim(token_elems, "x") or 1.0
            guard_h = 0.2 * med_h
            guard_w = 0.2 * med_w

            def _cross_fix(bounds, i0, i1, a0, a1, guard):
                if i1 == i0:
                    return i0, i1
                while i0 < i1 and (a1 - bounds[i0 + 1]) < guard:
                    i0 += 1
                while i1 > i0 and (bounds[i1] - a0) < guard:
                    i1 -= 1
                return i0, i1

            buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
            for e in token_elems:
                x0, y0, x1, y1 = e["bbox"]
                r0, r1 = _indices_covered(row_bounds, y0, y1, 0.5)
                c0, c1 = _indices_covered(col_bounds, x0, x1, 0.5)
                r0, r1 = _cross_fix(row_bounds, r0, r1, y0, y1, guard_h)
                c0, c1 = _cross_fix(col_bounds, c0, c1, x0, y1, guard_w)  # x-axis; using y1 is okay for guard symmetry
                buckets[(r0, c0)].append({"text": e["text"], "bbox": (x0, y0, x1, y1), "r1": r1, "c1": c1})

            # 4) Build cells (with spans) from buckets
            cells: List[Cell] = []
            for (r, c), group in buckets.items():
                max_r1 = max(g["r1"] for g in group) if group else r
                max_c1 = max(g["c1"] for g in group) if group else c
                group.sort(key=lambda g: (g["bbox"][1], g["bbox"][0]))
                text = "\n".join(g["text"].strip() for g in group if g.get("text"))
                cells.append(Cell(r=r, c=c, rowspan=max_r1 - r + 1, colspan=max_c1 - c + 1, text=text))

            html_tbl = cells_to_html(cells, n_rows, n_cols)
            page_html.setdefault(page_num, []).append(html_tbl)

        # Emit per-page html aligned to scrape['page'] (1-based indices)
        pages = scrape.get("page", [])
        html_by_page: List[str] = []
        for p in pages:
            joined = "<br/>".join(page_html.get(int(p), [])) if p is not None else ""
            html_by_page.append(joined or "")

        self._output = {
            "text": html_by_page,   # list[str], one per scraped page
            "format": "html",
            "method": self.__class__.__name__,
        }
        return None
