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
    def __init__(self, pages, metadata=None):
        """
        Parameters:
            pages: A single or list of fitz.Page objects or image representations.
            metadata: Optional dictionary of context (e.g., agency name, year, Format_Type).
        """
        self.pages = pages if isinstance(pages, list) else [pages]
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
