from base_scraper import BaseScraper

class TextScraper(BaseScraper):
    def scrape(self):
        all_text = []
        for page in self.pages:
            text = page.get_text("text")  # fitz.Page method
            all_text.append(text)
        return {
            "text": "\n\n".join(all_text),
            "page": [p.number + 1 for p in self.pages],  # fitz is zero-indexed, return 1-indexed
            "method": "TextScraper"
        }
