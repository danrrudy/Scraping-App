from base_scraper import BaseScraper

class TextScraper(BaseScraper):
    def scrape(self):
        text = self.page.get_text("text")  # fitz.Page method
        return {
            "text": text,
            "page": self.page.number + 1,  # fitz is zero-indexed
            "method": "TextScraper"
        }
