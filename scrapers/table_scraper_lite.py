from base_scraper import BaseScraper
from image_utils import pdf_page_to_pil
from transformers import AutoImageProcessor, TableTransformerForObjectDetection
from logger import setup_logger
import torch
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import pytesseract
from typing import List, Dict, Tuple, Any, Optional
from io import BytesIO


# ------------------------
# Models
# ------------------------
DETECTION_MODEL_ID = "microsoft/table-transformer-detection"
STRUCTURE_MODEL_ID = "microsoft/table-transformer-structure-recognition"


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

BBox = Tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points




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




class TableScraperLite(BaseScraper):
    def __init__(self, pages):
        super().__init__(pages)
        self.detection_processor  = AutoImageProcessor.from_pretrained(DETECTION_MODEL_ID)
        self.detection_model      = TableTransformerForObjectDetection.from_pretrained(DETECTION_MODEL_ID).eval()
        self.structure_processor  = AutoImageProcessor.from_pretrained(STRUCTURE_MODEL_ID)
        self.structure_model      = TableTransformerForObjectDetection.from_pretrained(STRUCTURE_MODEL_ID).eval()


    """
    Structure-only 'lite' table scraper.

    - Accepts a list of fitz.Document at instantiation.
    - scrape() has no arguments (aligns with your app's scraper lifecycle).
    - Returns cell coordinates (PDF-pt space) and per-page overlay PNGs.
    - Does NOT perform OCR/text extraction; you can add click-to-cell later using coords.
    """
    def detect_tables_on_page(self, page_image):
        with torch.no_grad():
            det_inputs  = self.detection_processor(images=page_image, return_tensors="pt")
            det_outputs = self.detection_model(**det_inputs)
        det_result = self.detection_processor.post_process_object_detection(
            det_outputs,
            target_sizes=[page_image.size[::-1]],  # (H, W)
            threshold=DETECTION_THRESHOLD
        )[0]

        table_crops = []  # list of (crop_image, (offset_x, offset_y), page_bbox_xyxy)
        for score, label_id, box in zip(det_result["scores"], det_result["labels"], det_result["boxes"]):
            if self.detection_model.config.id2label[label_id.item()] != "table" or score.item() <= 0.9:
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
        return table_crops

    def detect_structures_within_table(self, table_crops, page_idx, pdf_page):
        page_tables = [] # store the results per page as an array 
        for table_idx, (crop_image, (offset_x, offset_y), table_bbox_page) in enumerate(table_crops):
            with torch.no_grad():
                struct_inputs  = self.structure_processor(images=crop_image, return_tensors="pt")
                struct_outputs = self.structure_model(**struct_inputs)
            struct_result = self.structure_processor.post_process_object_detection(
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
                "structures": [],
                "table_image": None
            }

            # Stable ID counter within this table
            struct_counter = 0
            table_width = float(table_bbox_page[2])-float(table_bbox_page[0])
            table_height = float(table_bbox_page[3])-float(table_bbox_page[1])

            for score, label_id, box in zip(struct_result["scores"], struct_result["labels"], struct_result["boxes"]):
                label_name = self.structure_model.config.id2label[label_id.item()]
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

                # Assign a human-readable ID
                struct_id = f"p{pdf_page.number + 1}-t{table_idx}-s{struct_counter}"
                struct_counter += 1


                # Draw overlays for high-confidence only, include the ID
                if conf >= DRAW_OVERLAY_THRESHOLD:
                    color = COLOR_PALETTE[label_id.item() % len(COLOR_PALETTE)]
                    draw.rectangle([sx1, sy1, sx2, sy2], outline=color, width=2)
                    # draw.text((sx1 + 5, sy1 + 5), f"[{struct_id}] {label_name} ({conf:.2f})", fill=color, font=font)


                # Absolute page coords for downstream mapping
                px1 = float(sx1 + offset_x); py1 = float(sy1 + offset_y)
                px2 = float(sx2 + offset_x); py2 = float(sy2 + offset_y)

                structure_record = {
                    "id": struct_id,
                    "label": label_name,
                    "confidence": conf,
                    "bbox_crop": {"x1": float(sx1), "y1": float(sy1), "x2": float(sx2), "y2": float(sy2)},
                    "bbox_page": {"x1": px1, "y1": py1, "x2": px2, "y2": py2},
                }
                table_record["structures"].append(structure_record)
            table_record["table_image"] = drawn
            page_tables.append(table_record)
        return page_tables

    def scrape(self):
        logger = setup_logger()
        """
        Run structure detection only, draw overlays, and return a result dict.

        If one doc is provided:
            result["page_overlays"] = {page_idx: overlay_png_bytes}
            result["cells_by_page"] = {page_idx: [(x0,y0,x1,y1), ...]}  # PDF pts
            result["page_dims"]     = {page_idx: (w_pt, h_pt)}
        If multiple docs are provided:
            result["page_overlays_by_doc"] = {doc_i: {page_idx: png_bytes}}
            result["cells_by_page_by_doc"] = {doc_i: {page_idx: [bboxes...]}}
            result["page_dims_by_doc"]     = {doc_i: {page_idx: (w_pt, h_pt)}}
        In all cases:
            result["pages"] contains a compact list of entries with overlay bytes.
        """
        labeled_images = []
        tables_payload = []


        for page_idx, pdf_page in enumerate(self.pages):
            page_image = pdf_page_to_pil(pdf_page, scale=2.0)

            table_crops = self.detect_tables_on_page(page_image)
            table_record = self.detect_structures_within_table(table_crops, page_idx, pdf_page)
            tables_payload.append(table_record)


        self._output = {
            "status": "OK",
            "method": self.__class__.__name__,
            "format": "image",
            "page": [p.number + 1 for p in self.pages],
            "result": tables_payload,
            "text": ""
        }
        logger.info("done! returning table payload")
        return None
