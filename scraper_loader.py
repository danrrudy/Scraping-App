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
			logger.debug("Scraper loaded from file, returning")
			return obj
	logger.error(f"No subclass of BaseScraper found in {filepath}, ensure the scraper is defined properly")
	raise ImportError(f"No subclass of BaseScraper found in {filepath}")

## TODO: select_scraper: simple dictionary mapping user's settings, then pull the filepath from settings before passing to load_scraper_class
def select_scraper_class(settings, format_type):
	logger = setup_logger()
	logger.debug(f"Selecting scraping tool for format type {format_type}")
	tools = settings.get("scrapingTools", {})
	default_scraper = settings.get("defaultScraper", "")
	for tool_name, tool_data in tools.items():
		if format_type in tool_data.get("format_types", []):
			path = tool_data["path"]
			logger.debug(f"Scraping tool \"{tool_name}\" selected for format code {format_type}")
			return load_scraper_class(path)
	# Use the user-defined default scraper if one can't be identified for this format_type
	if default_scraper in tools:
		logger.info(f"No scraper matched for format type {format_type}, returning default scraper ({default_scraper})")
		return(load_scraper_class(tools[default_scraper]["path"]))
	else:
		logger.warning("default scraper could not be loaded")
	# Throw an error if a scraper can't be identified and loading the default fails		
	raise ValueError(f"No scraper found for format type {format_type}")