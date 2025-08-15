from base_scraper import BaseScraper

class TextScraper(BaseScraper):
    def scrape(self):
        try:
            all_text = [page.get_text("text") for page in self.pages]
            status = f"OK: {len(all_text)} pages scraped"
            if not any((t or "").strip() for t in all_text):
                status = "No Text Found"
        except Exception as e:
            status = "FATAL ERROR"
            all_text = ["" for _ in self.pages]

        self._output = {
            "text": all_text,
            "page": [p.number + 1 for p in self.pages],  # fitz is zero-indexed, return 1-indexed
            "status": status,
            "method": "TextScraper"
        }
