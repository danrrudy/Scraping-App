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
        self._output = None

    @abstractmethod
    def scrape(self):
        """populates the output dictionary (self._output)"""
        pass

    @property
    def result(self):
        """returns validated output dict after running scrape()"""
        if self._output is None:
            raise ValueError("Scrape has not been run yet")
        return self._enforce_output_format(self._output)

    def _enforce_output_format(self, output_dict):
        """
        Ensures scraper output adheres to the required schema:
        """
        if not isinstance(output_dict, dict):
            raise ValueError("Scraper output must be a dictionary.")

        if "page" not in output_dict or not isinstance(output_dict["page"], list):
            raise ValueError("Scraper output must include 'page' as a list.")

        if "text" not in output_dict or not isinstance(output_dict["text"], (str, list)):
            raise ValueError("Scraper output must include 'text' as a string.")

        if output_dict.get("method") != self.__class__.__name__:
            raise ValueError(f"'method' must be set to '{self.__class__.__name__}'")

        if "status" not in output_dict:
            output_dict["status"] = "OK"

        return output_dict