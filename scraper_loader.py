import importlib.util
import os
import inspect
from base_scraper import BaseScraper
from logger import setup_logger

def load_scraper_class(filepath):
	logger = setup_logger()

	# Set up a 'container' for the scraper to be loaded into
	module_name = os.path.splitext(os.path.basename(filepath))[0]
	spec = importlib.util.spec_from_file_location(module_name, filepath)
	if not spec or not spec.loader:
		logger.critical(f"failed to load scraper specification from {filepath}")
		raise ImportError(f"Could not load scraping module specification from {filepath}")

	# Load the scraper
	module = importlib.util.module_from_spec(spec)
	# Run the loaded scraper
	spec.loader.exec_module(module)

	# Return the scraper implementation defined in the loaded file
	# This only accepts the first subclass found, generalize in case multi-page scrapers or other similar tools are useful
	for _, obj in inspect.getmembers(module, inspect.isclass):
		if issubclass(obj, BaseScraper) and obj is not BaseScraper:
			logger.debug("Scraper identified, returning its Class")
			return obj
	logger.error(f"No subclass of BaseScraper found in {filepath}, ensure the scraper is defined properly")
	raise ImportError(f"No subclass of BaseScraper found in {filepath}")

## TODO: select_scraper: simple dictionary mapping user's settings, then pull the filepath from settings before passing to load_scraper_class
