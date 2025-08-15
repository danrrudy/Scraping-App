from base_scraper import BaseScraper
from image_utils import pdf_page_to_pil
from transformers import AutoImageProcessor, TableTransformerForObjectDetection, AutoProcessor
import torch
import fitz  # PyMuPDF
from PIL import ImageDraw, ImageFont
import os


from transformers import DetrFeatureExtractor

feature_extractor = DetrFeatureExtractor()

detection_processor = AutoProcessor.from_pretrained("microsoft/table-transformer-detection")
detection_model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-detection")
detection_model.eval()

# Load model + processor once at module level
# processor = AutoImageProcessor.from_pretrained("microsoft/table-transformer-detection", local_files_only=True)
# model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-detection", local_files_only=True)
# model.eval()


# encoding.keys()
model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-structure-recognition")


class TableScraper(BaseScraper):
    def scrape(self):
        TABLE_PADDING = 50
        extracted_tables = []
        cropped_tables = []
        all_texts = []
        images = []

        # Outer loop over all pages in the passed range
        for page in self.pages:

            # First stage: locate table on the page
            tables_on_page = []
            # Convert the PDF page to an image
            image = pdf_page_to_pil(page, scale=2.0) # Upscale by 2x, may need to adjust this to acommodate some docs that fail to load
            inputs = detection_processor(images=image, return_tensors="pt")
            with torch.no_grad():
                detection_outputs = detection_model(**inputs)

            # Flip width & height dimensions    
            target_size = torch.tensor([image.size[::-1]])
            detection_result = detection_processor.post_process_object_detection(detection_outputs, target_sizes=target_size, threshold=0.8)[0]
            
            # # Filter to 'table' boxes with a confidence of >=90% only
            # table_boxes = [
            #     box.tolist()
            #     for score, label, box in zip(
            #         detection_result["scores"],
            #         detection_result["labels"],
            #         detection_result["boxes"]
            #     )
            #     if detection_model.config.id2label[label.item()] == "table" and score.item() > 0.9
            # ]

            for score, label, box in zip(detection_result["scores"], detection_result["labels"], detection_result["boxes"]):
                if detection_model.config.id2label[label.item()] == "table" and score.item() > .9:
                    xmin, ymin, xmax, ymax = box.tolist()
                    # Apply a constant pad to the bbox edges to aid structure recognition (per dev suggestions in GH)
                    xmin -= TABLE_PADDING
                    ymin -= TABLE_PADDING
                    xmax += TABLE_PADDING
                    ymax += TABLE_PADDING
                    cropped = image.crop((xmin, ymin, xmax, ymax))
                    cropped_tables.append(cropped)
                    table_rect = fitz.Rect(
                                xmin,
                                ymin,
                                xmax,
                                ymax,
                            )

                    # Roughly Extract text within table region
                    # First, see if it can be pulled directly form the PDF
                    table_text = page.get_text("text", clip=table_rect)
                    if table_text.strip():
                        tables_on_page.append(table_text.strip())
                    else: # This can probably be left blank
                        #print(f"Empty object detected: Score: {score}, Label: {label_str}")
                        continue


            extracted_tables.extend(tables_on_page)
            all_texts.append("\n\n".join(tables_on_page) if tables_on_page else "")

            # Second stage: parse the rows, columns, and other features from the table


            for table in cropped_tables:
                struct_input = feature_extractor(table, return_tensors = "pt")

                with torch.no_grad():
                    outputs = model(**struct_input)


                target_sizes = [table.size[::-1]]
                results = feature_extractor.post_process_object_detection(outputs, threshold=0.8, target_sizes=target_sizes)[0]



                # Draw image
                drawn_image = table.copy()
                draw = ImageDraw.Draw(drawn_image)

                # Optional: specify a default font if available (platform dependent)
                try:
                    font = ImageFont.truetype("arial.ttf", 14)
                except:
                    font = ImageFont.load_default()

                COLOR_PALETTE = [
                    "red", "green", "blue", "orange", "purple",
                    "cyan", "magenta", "yellow", "lime", "pink"
                ]

                # Loop over detected boxes and draw them
                for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
                    if score < .9:
                        continue
                    label_str = model.config.id2label[label.item()]
                    score_val = round(score.item(), 2)
                    # do not need to pad within-table features AFAIK
                    xmin, ymin, xmax, ymax = box.tolist()
                    if label_str == "table column":
                        xmin -= 0 
                        xmax += 0
                    else:
                        xmin -= 10
                        xmax += 10
                    # Columns seem to be drawing more narrow than they actually are, add some padding manually to account for this

                    # Define a basic color palette for up to 10 unique labels (extendable)


                    # Compute color by label index (wrap around if more labels than colors)
                    color = COLOR_PALETTE[label.item() % len(COLOR_PALETTE)]

                    # Draw rectangle
                    draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=2)

                    # Label text
                    label_text = f"{label_str} ({score_val})"
                    draw.text((xmin + 5, ymin + 5), label_text, fill=color, font=font)

                images.append(drawn_image)


                # Create bounding coordinates 
                # target_size = torch.tensor([image.size[::-1]])
                # # Identify objects with a confidence threshold of .9
                # results = processor.post_process_object_detection(outputs, target_sizes=target_size, threshold=0.9)[0]
                # I don't know why I set this up as two separate loops, this logic can and should be integrated into the loop above


                # Store tables on each page as an array in case multiple are detected
                regions_in_table = []
                # Loop over all of the detected objects
                for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):

                    # Pull the name of the current object
                    label_str = model.config.id2label[label.item()]

                    # Not interested in the outer bounding box of the table
                    # if label_str != "table":
                    #     continue

                    # Convert object location box to PDF coords for OCR
                    # Confirm that this is corrct, it seems like it may be drawing the boxes too big
                    xmin, ymin, xmax, ymax = box.tolist()
                    img_w, img_h = table.size
                    pdf_rect = fitz.Rect(
                        xmin,
                        ymin,
                        xmax,
                        ymax,
                    )

                    # THIS IS A PROBLEM - VESTIGIAL FROM SINGLE-PHASE DEV
                    # This section needs to be replaced with the logic to parse structure from the extracted elements
                    # and put the content into the correct cells.

                    # Extract text within table region
                    # First, see if it can be pulled directly form the PDF
                    region_text = page.get_text("text", clip=pdf_rect)
                    if region_text.strip():
                        regions_in_table.append(region_text.strip())
                        #print(f"Score: {score}, Label: {label_str}, Content: {region_text.strip()}")
                    else: # Perform OCR on the region
                        print(f"Empty object detected: Score: {score}, Label: {label_str}")
                        continue


                extracted_tables.extend(tables_on_page)
                all_texts.append("\n\n".join(tables_on_page) if tables_on_page else "")

        self._output = {
            "status": f"{len(extracted_tables)} tables found across {len(self.pages)} page(s)",
            "text": all_texts,
            "tables": extracted_tables,
            "page": [p.number + 1 for p in self.pages],
            "images": images,
            "method": self.__class__.__name__,
        }
