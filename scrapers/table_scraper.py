# scrapers/table_scraper.py

from base_scraper import BaseScraper
from image_utils import pdf_page_to_pil
from transformers import TableTransformerForObjectDetection, AutoProcessor
import torch

# Use cached version of the processor and model headers to avoid pinging HF with every page that's scraped
# Model loading is resource-expensive, so it is loaded upon first call and cached for future calls
processor = AutoProcessor.from_pretrained("microsoft/table-transformer-detection", local_files_only = True)
model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-detection", local_files_only = True)
model.eval()


# TableScraper is only implemented for single pages at this point
class TableScraper(BaseScraper):
    def scrape(self):
        all_text = []
        for page in self.pages:
            image = pdf_page_to_pil(page, scale=2.0)                # From image_utils
            inputs = processor(images=image, return_tensors="pt")

            with torch.no_grad():
                outputs = model(**inputs)

            target_size = torch.tensor([image.size[::-1]])
            results = processor.post_process_object_detection(outputs, target_sizes=target_size, threshold=0.8)[0]

            # Grab all object the model labeled as a table. In the future, attach diagnostic statistics to this such as confidence.
            tables_found = sum(
                1 for label in results["labels"]
                if model.config.id2label[label.item()] == "table"
            )
            all_text.append(f"{tables_found} table(s) detected")

        return {
            "tables_found": tables_found,
            "text": all_text,
            "pages": [p.number + 1 for p in self.pages],
            "method": "TableScraper"
        }
