from base_scraper import BaseScraper
from image_utils import pdf_page_to_pil
from transformers import AutoImageProcessor, TableTransformerForObjectDetection
from logger import setup_logger
import torch
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import pytesseract

# ------------------------
# Models
# ------------------------
DETECTION_MODEL_ID = "microsoft/table-transformer-detection"
STRUCTURE_MODEL_ID = "microsoft/table-transformer-structure-recognition"

detection_processor  = AutoImageProcessor.from_pretrained(DETECTION_MODEL_ID)
detection_model      = TableTransformerForObjectDetection.from_pretrained(DETECTION_MODEL_ID).eval()
structure_processor  = AutoImageProcessor.from_pretrained(STRUCTURE_MODEL_ID)
structure_model      = TableTransformerForObjectDetection.from_pretrained(STRUCTURE_MODEL_ID).eval()

# ------------------------
# Tunable constants
# ------------------------
TABLE_PADDING_PX        = 50
DETECTION_THRESHOLD     = 0.8
STRUCTURE_THRESHOLD     = 0.8
DRAW_OVERLAY_THRESHOLD  = 0.9
SNAP_MARGIN_PX          = 8     # Minimum absolute pixel tolerance for row width snapping
SNAP_MARGIN_FRAC        = 0.015 # Percentage-based margin for snapping rows to table width

# Todlerance for snapping intersections into spanning cells
SPAN_GUARD_FRAC         = 0.06  # 6% of band size



# ------------------------
# Program Constants
# ------------------------
OCR_CONFIG_CELL = r"--oem 3 --psm 6"

# Color palette for table labeling
COLOR_PALETTE = [
    "red", "green", "blue", "orange", "purple",
    "cyan", "magenta", "yellow", "lime", "pink"
]

ROW_TYPES = {"table row", "column header"} # Constant for row-type objects, used in label-conditional logic
COL_TYPES = {"table column"} # Constnat for column-type objects, used in label-conditional logic
SPAN_TYPES = {"table spanning cell"}

# ------------------------
# Data Structures
# ------------------------

BBox = Tuple[float, float, float, float]

@dataclass
class Cell:
    r: int 
    c: int 
    rowspan: int 
    colspan: int
    text: str 
    bbox_crop: Optional[BBox] = None

@dataclass
class TableGrid:
    page_number: int
    table_index_on_page: int 
    n_rows: int 
    n_cols: int 
    row_bounds: List[float] # len = n_rows+1
    col_bounds: List[float] # len = n_cols+1
    header: List[str]
    cells: List[Cell]


def _snap_to_table_width(sx1, sy1, sx2, sy2, crop_w, crop_h, label):
    """
    Table rows tend to push in a few pixels from the table boundary
    If any side is within a small margin of the table crop boundary, extend the region to that bound
    for rows and header row: snap to full width
    for columns: snap to full height
    for other labels: ignore for now
    """

    margin = max(SNAP_MARGIN_PX, SNAP_MARGIN_FRAC*min(crop_w, crop_h))

    # Generic snaps: if a side is already close to a boundary, pull it to that boundary
    if sx1 <= margin:           sx1 = 0.0
    if sy1 <= margin:           sy1 = 0.0
    if (crop_w - sx2) <= margin: sx2 = float(crop_w)
    if (crop_h - sy2) <= margin: sy2 = float(crop_h)

    # Removed conditional logic in favor of a generic logic (above)
    # label_name can be removed as an argument if this is sufficient
    return sx1, sy1, sx2, sy2

# Ensures that padded boundaries do not extend past legal limits
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _bounds_from_structs(structs, crop_w, crop_h):
    rows = []
    cols = []
    spans = []
    for s in structs:
        label = (s.get("label") or "").lower()
        bb = s.get("bbox_crop") or {}
        try:
            x0, y0, x1, y1 = float(bb["x1"]), float(bb["y1"]), float(bb["x2"]), float(bb["y2"])
        except Exception:
            continue
        if label in ROW_TYPES:
            rows.append((y0, y1))
        elif label in COL_TYPES:
            cols.append((x0, x1))
        elif label in SPAN_TYPES:
            spans.append((x0, y0, x1, y1))


# Converts image to grayscle, ups the contrast, then removes features that are unlikely to be distinguished
def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    return g


# Pytesseract implementation of OCR
def _ocr(img: Image.Image, config: str) -> str:
    return (pytesseract.image_to_string(_preprocess_for_ocr(img), config=config) or "").strip()

# Cleans row and column boundaries to remove overlap and tighten
# Necessary for constructing individual cells to ensure the correct text is captured

def _to_bounds(ivals, lo=0.0, hi=1.0):
    if not ivals:
        return []
    ivals = sorted(ivals, key=lambda t: (t[0], t[1]))
    # centers between consecutive intervals define internal boundaries
    mids = []
    for i in range(len(ivals)-1):
        mids.append( (ivals[i][1] + ivals[i+1][0]) / 2.0 )
    # pad bounds outward by a half median height/width
    sizes = [b-a for a,b in ivals]
    pad = (sum(sizes)/len(sizes))/2.0 if sizes else 1.0
    return [max(lo, ivals[0][0]-pad)] + mids + [min(hi, ivals[-1][1]+pad)]

    row_bounds = _to_bounds(rows, 0.0, crop_h)
    col_bounds = _to_bounds(cols, 0.0, crop_w)

    return row_bounds, col_bounds, spans


# Identifies which bands are covered by an object, used to detect spanning cell dimensions
def _band_index(bounds, a0, a1, min_frac=0.5):
    """Return inclusive band index [j0,j1] covered by [a0,a1]. If none passes, snap to nearest."""
    covered = []
    for j in range(len(bounds)-1):
        b0, b1 = bounds[j], bounds[j+1]
        inter = max(0.0, min(a1,b1) - max(a0,b0))
        length = max(1e-6, a1-a0)
        if inter/length >= min_frac:
            covered.append(j)
    if not covered and len(bounds) > 1:
        centers = [(bounds[j]+bounds[j+1])/2.0 for j in range(len(bounds)-1)]
        ctr = (a0+a1)/2.0
        j = min(range(len(centers)), key=lambda k: abs(centers[k]-ctr))
        covered = [j]
    return (min(covered), max(covered)) if covered else (0,0)


def _rects_intersect(a, b, guard=0.0):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (ax0 <= bx1+guard and ax1+guard >= bx0 and ay0 <= by1+guard and ay1+guard >= by0)

class TableScraper(BaseScraper):
    def scrape(self):
        logger = setup_logger()

        page_texts = []     # concatenated embedded text per page (from table regions)
        debug_images = []   # overlay images for each table crop
        tables_payload = [] # rich per-table data

        # Outer loop scans the pages to identify table locations
        for page_idx, pdf_page in enumerate(self.pages):
            page_image = pdf_page_to_pil(pdf_page, scale=2.0)

            # ----- Stage 1: detect table regions on the full page -----
            with torch.no_grad():
                det_inputs  = detection_processor(images=page_image, return_tensors="pt")
                det_outputs = detection_model(**det_inputs)
            det_result = detection_processor.post_process_object_detection(
                det_outputs,
                target_sizes=[page_image.size[::-1]],  # (H, W)
                threshold=DETECTION_THRESHOLD
            )[0]

            table_crops = []  # list of (crop_image, (offset_x, offset_y), page_bbox_xyxy)
            for score, label_id, box in zip(det_result["scores"], det_result["labels"], det_result["boxes"]):
                if detection_model.config.id2label[label_id.item()] != "table" or score.item() <= 0.9:
                    continue

                x1, y1, x2, y2 = box.tolist()
                # Add padding to the coordinates as long as this does not extend past the page
                x1 = _clamp(x1 - TABLE_PADDING_PX, 0, page_image.width)
                y1 = _clamp(y1 - TABLE_PADDING_PX, 0, page_image.height)
                x2 = _clamp(x2 + TABLE_PADDING_PX, 0, page_image.width)
                y2 = _clamp(y2 + TABLE_PADDING_PX, 0, page_image.height)

                # Store the cropped and padded image
                crop_image = page_image.crop((x1, y1, x2, y2))
                table_crops.append((crop_image, (x1, y1), (x1, y1, x2, y2)))

            # Page-level text: pull embedded text for each table region (NOT OCR)
            # The page-embedded text will be correct in terms of spelling, but not formatting
            # OCR will be correct in terms of formatting, but may struggle with spelling
            page_tables_embedded = []
            for _, _, (tx1, ty1, tx2, ty2) in table_crops:
                clip_rect = fitz.Rect(tx1, ty1, tx2, ty2)
                table_text = (pdf_page.get_text("text", clip=clip_rect) or "").strip()
                if table_text:
                    page_tables_embedded.append(table_text)
            page_texts.append("\n\n".join(page_tables_embedded) if page_tables_embedded else "")


            # ----- Stage 2: detect within-table structure; OCR each structure -----
            for table_idx, (crop_image, (offset_x, offset_y), table_bbox_page) in enumerate(table_crops):
                with torch.no_grad():
                    struct_inputs  = structure_processor(images=crop_image, return_tensors="pt")
                    struct_outputs = structure_model(**struct_inputs)
                struct_result = structure_processor.post_process_object_detection(
                    struct_outputs,
                    target_sizes=[crop_image.size[::-1]],  # (H, W)
                    threshold=STRUCTURE_THRESHOLD
                )[0]

                # Overlay canvas
                drawn = crop_image.copy()
                draw  = ImageDraw.Draw(drawn)
                try:
                    font = ImageFont.truetype("arial.ttf", 14)
                except Exception:
                    font = ImageFont.load_default()

                # Build table payload
                # Contains the page index and number, the table index on the page, and its bounding coordinates
                # Also initializes an empty array for the structures to be saved into in the next loop
                table_record = {
                    "page_index": page_idx,
                    "page_number": pdf_page.number + 1,
                    "table_index_on_page": table_idx,
                    "table_box_page": {
                        "x1": float(table_bbox_page[0]),
                        "y1": float(table_bbox_page[1]),
                        "x2": float(table_bbox_page[2]),
                        "y2": float(table_bbox_page[3]),
                    },
                    "structures": []
                }

                # Stable ID counter within this table
                struct_counter = 0
                table_width = float(table_bbox_page[2])-float(table_bbox_page[0])
                table_height = float(table_bbox_page[3])-float(table_bbox_page[1])

                for score, label_id, box in zip(struct_result["scores"], struct_result["labels"], struct_result["boxes"]):
                    label_name = structure_model.config.id2label[label_id.item()]
                    conf = float(score.item())

                    sx1, sy1, sx2, sy2 = box.tolist()
                    # small padding for non-columns (columns tend to be tight already)
                    # This may be unneccessary with the new snap to width function
                    if label_name != "table column":
                        sx1 -= 10; sx2 += 10

                    sx1 = _clamp(sx1, 0, crop_image.width)
                    sy1 = _clamp(sy1, 0, crop_image.height)
                    sx2 = _clamp(sx2, 0, crop_image.width)
                    sy2 = _clamp(sy2, 0, crop_image.height)

                    sx1, sy1, sx2, sy2 = _snap_to_table_width(
                        sx1, sy1, sx2, sy2,
                        crop_w = table_width,
                        crop_h = table_height,
                        label = label_name
                    )

                    # OCR only the structure crop
                    struct_crop = crop_image.crop((sx1, sy1, sx2, sy2))
                    ocr_text = _ocr(struct_crop, OCR_CONFIG_CELL)

                    # Assign a human-readable ID
                    struct_id = f"p{pdf_page.number + 1}-t{table_idx}-s{struct_counter}"
                    struct_counter += 1

                    # Draw overlays for high-confidence only, include the ID
                    if conf >= DRAW_OVERLAY_THRESHOLD:
                        color = COLOR_PALETTE[label_id.item() % len(COLOR_PALETTE)]
                        draw.rectangle([sx1, sy1, sx2, sy2], outline=color, width=2)
                        draw.text((sx1 + 5, sy1 + 5), f"[{struct_id}] {label_name} ({conf:.2f})", fill=color, font=font)

                    # Absolute page coords for downstream mapping
                    px1 = float(sx1 + offset_x); py1 = float(sy1 + offset_y)
                    px2 = float(sx2 + offset_x); py2 = float(sy2 + offset_y)

                    structure_record = {
                        "id": struct_id,
                        "label": label_name,
                        "confidence": conf,
                        "bbox_crop": {"x1": float(sx1), "y1": float(sy1), "x2": float(sx2), "y2": float(sy2)},
                        "bbox_page": {"x1": px1, "y1": py1, "x2": px2, "y2": py2},
                        "ocr_text": ocr_text,
                    }
                    table_record["structures"].append(structure_record)

                    # DEBUG console line with ID for quick cross-ref
                    # if logger:
                    #     preview = (ocr_text[:200] + "…") if len(ocr_text) > 200 else ocr_text
                    #     logger.debug(
                    #         f"[{struct_id}] {label_name} ({conf:.2f}) OCR -> '{preview}'"
                    #     )

            # ---- Build a span-aware grid from structure boxes ----
            row_bounds, col_bounds, span_boxes = _bounds_from_structs(table_record["structures"], table_width, table_height)
            n_rows = max(0, len(row_bounds)-1)
            n_cols = max(0, len(col_bounds)-1)

            cells: List[Cell] = []
            header_texts = [""] * n_cols

            if n_rows >= 1 and n_cols >= 1:
                # Guard based on typical band size
                avg_row_h = (row_bounds[-1] - row_bounds[0]) / max(1, n_rows)
                avg_col_w = (col_bounds[-1] - col_bounds[0]) / max(1, n_cols)
                guard = SPAN_GUARD_FRAC * min(avg_row_h, avg_col_w)

                # Precompute rectangles for each intersection
                # (r,c) -> bbox in crop coordinates
                inter_rects: Dict[Tuple[int,int], BBox] = {}
                for r in range(n_rows):
                    y0, y1 = row_bounds[r], row_bounds[r+1]
                    for c in range(n_cols):
                        x0, x1 = col_bounds[c], col_bounds[c+1]
                        inter_rects[(r,c)] = (x0, y0, x1, y1)

                # Remove intersections that live inside a spanning cell (with tolerance)
                to_skip = set()
                for (sx0, sy0, sx1, sy1) in span_boxes:
                    # Which row/col bands does this span cover?
                    r0, r1 = _band_index(row_bounds, sy0, sy1, 0.4)
                    c0, c1 = _band_index(col_bounds, sx0, sx1, 0.4)
                    for rr in range(r0, r1+1):
                        for cc in range(c0, c1+1):
                            if _rects_intersect(inter_rects[(rr,cc)], (sx0,sy0,sx1,sy1), guard):
                                to_skip.add((rr,cc))

                # Build cells: OCR per cell; header row = r==0
                for r in range(n_rows):
                    for c in range(n_cols):
                        if (r,c) in to_skip:
                            continue
                        x0, y0, x1, y1 = inter_rects[(r,c)]
                        crop = crop_image.crop((x0, y0, x1, y1))
                        txt = _ocr(crop, OCR_CONFIG_CELL)

                        # Find potential row/col span by checking overlap against spans again
                        rr0, rr1 = r, r
                        cc0, cc1 = c, c
                        for (sx0, sy0, sx1, sy1) in span_boxes:
                            if _rects_intersect((x0,y0,x1,y1), (sx0,sy0,sx1,sy1), guard):
                                # expand to full coverage of that spanning rect's bands
                                pr0, pr1 = _band_index(row_bounds, sy0, sy1, 0.4)
                                pc0, pc1 = _band_index(col_bounds, sx0, sx1, 0.4)
                                rr0, rr1 = min(rr0, pr0), max(rr1, pr1)
                                cc0, cc1 = min(cc0, pc0), max(cc1, pc1)

                        rowspan = rr1 - rr0 + 1
                        colspan = cc1 - cc0 + 1

                        # only emit the anchor cell (top-left of span)
                        if rr0 == r and cc0 == c:
                            cells.append(Cell(r=r, c=c, rowspan=rowspan, colspan=colspan, text=txt, bbox_crop=(x0,y0,x1,y1)))
                            if r == 0:
                                header_texts[c] = txt

            # Save a header even if empty bands (keeps schema stable)
            grid = TableGrid(
                page_number=table_record["page_number"],
                table_index_on_page=table_record["table_index_on_page"],
                n_rows=n_rows,
                n_cols=n_cols,
                row_bounds=[float(v) for v in row_bounds] if row_bounds else [],
                col_bounds=[float(v) for v in col_bounds] if col_bounds else [],
                header=header_texts if n_rows >= 1 else [],
                cells=cells
            )

            # Attach to the table payload
            table_record["grid"] = asdict(grid)



            tables_payload.append(table_record)
            debug_images.append(drawn)

        self._output = {
            "status": f"{len(tables_payload)} tables found across {len(self.pages)} page(s)",
            "text": page_texts,                                  # embedded page text from table regions
            "tables": tables_payload,                            # rich per-table data with per-structure IDs
            "page": [p.number + 1 for p in self.pages],          # 1-based page numbers
            "images": debug_images,                              # PIL.Image overlays with IDs drawn
            "method": self.__class__.__name__,
        }
        return None
