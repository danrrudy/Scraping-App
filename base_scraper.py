from abc import ABC, abstractmethod


#########################################################
#########################################################
#
#
#                      WAIT!
#   This file should not be modified under most
#   circumstances! To create a new scraping tool,
#   you should extend this class as:
#   class YourScraper(BaseScraper)
#   Modifying this file will break existing tools!
#
#########################################################
#########################################################
class BaseScraper(ABC):
    def __init__(self, page, metadata=None):
        """
        Parameters:
            page: A fitz.Page object or image representation.
            metadata: Optional dictionary of context (e.g., agency name, year, Format_Type).
        """
        self.page = page
        self.metadata = metadata or {}

    @abstractmethod
    def scrape(self):
        """
        Extracts structured output from a page.
        Must be implemented by subclasses.
        
        Returns:
            A dictionary like:
            {
                "text": "Extracted content",
                "page": 3,
                "method": "TextScraper"
            }
        """
        pass
