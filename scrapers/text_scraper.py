from base_scraper import BaseScraper

class TextScraper(BaseScraper):
    def scrape(self):
        all_text = [page.get_text("text") for page in self.pages]
        return {
            "text": all_text,
            "page": [p.number + 1 for p in self.pages],  # fitz is zero-indexed, return 1-indexed
            "method": "TextScraper"
        }
