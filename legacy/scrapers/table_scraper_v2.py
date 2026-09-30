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
# Tunables
# ------------------------
TABLE_PADDING_PX        = 50
DETECTION_THRESHOLD     = 0.8
STRUCTURE_THRESHOLD     = 0.8
DRAW_OVERLAY_THRESHOLD  = 0.9

OCR_CONFIG_CELL = r"--oem 3 --psm 6"

COLOR_PALETTE = [
    "red", "green", "blue", "orange", "purple",
    "cyan", "magenta", "yellow", "lime", "pink"
]

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    return g

def _ocr(img: Image.Image, config: str) -> str:
    return (pytesseract.image_to_string(_preprocess_for_ocr(img), config=config) or "").strip()


class TableScraper(BaseScraper):
    def scrape(self):
        logger = setup_logger()

        page_texts = []     # concatenated embedded text per page (from table regions)
        debug_images = []   # overlay images for each table crop
        tables_payload = [] # rich per-table data

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
                x1 = _clamp(x1 - TABLE_PADDING_PX, 0, page_image.width)
                y1 = _clamp(y1 - TABLE_PADDING_PX, 0, page_image.height)
                x2 = _clamp(x2 + TABLE_PADDING_PX, 0, page_image.width)
                y2 = _clamp(y2 + TABLE_PADDING_PX, 0, page_image.height)

                crop_image = page_image.crop((x1, y1, x2, y2))
                table_crops.append((crop_image, (x1, y1), (x1, y1, x2, y2)))

            # Page-level text: pull embedded text for each table region (NOT OCR)
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

                for score, label_id, box in zip(struct_result["scores"], struct_result["labels"], struct_result["boxes"]):
                    label_name = structure_model.config.id2label[label_id.item()]
                    conf = float(score.item())

                    sx1, sy1, sx2, sy2 = box.tolist()
                    # small padding for non-columns (columns tend to be tight already)
                    if label_name != "table column":
                        sx1 -= 10; sx2 += 10

                    sx1 = _clamp(sx1, 0, crop_image.width)
                    sy1 = _clamp(sy1, 0, crop_image.height)
                    sx2 = _clamp(sx2, 0, crop_image.width)
                    sy2 = _clamp(sy2, 0, crop_image.height)

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
                        "id": struct_id,  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< added ID
                        "label": label_name,
                        "confidence": conf,
                        "bbox_crop": {"x1": float(sx1), "y1": float(sy1), "x2": float(sx2), "y2": float(sy2)},
                        "bbox_page": {"x1": px1, "y1": py1, "x2": px2, "y2": py2},
                        "ocr_text": ocr_text,
                    }
                    table_record["structures"].append(structure_record)

                    # DEBUG console line with ID for quick cross-ref
                    if logger:
                        preview = (ocr_text[:200] + "…") if len(ocr_text) > 200 else ocr_text
                        logger.debug(
                            f"[{struct_id}] {label_name} ({conf:.2f}) OCR -> '{preview}'"
                        )

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
