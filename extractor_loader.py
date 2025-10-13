import importlib.util
import os
import inspect
from base_extractor import BaseExtractor
from logger import setup_logger

def load_extractor_class(filepath):
	logger = setup_logger()

	# Set up a 'container' for the scraper to be loaded into
	module_name = os.path.splitext(os.path.basename(filepath))[0]
	spec = importlib.util.spec_from_file_location(module_name, filepath)
	if not spec or not spec.loader:
		logger.critical(f"failed to load scraper specification from {filepath}")
		raise ImportError(f"Could not load scraping module specification from {filepath}")

	# Load the extractor
	module = importlib.util.module_from_spec(spec)
	
	# Run the loaded extractor
	spec.loader.exec_module(module)

	# Return the extractor implementation defined in the loaded file
	# This only accepts the first subclass found
	for _, obj in inspect.getmembers(module, inspect.isclass):
		if issubclass(obj, BaseExtractor) and obj is not BaseExtractor:
			logger.debug("Extractor loaded from file, returning")
			return obj
	logger.error(f"No subclass of BaseExtractor found in {filepath}, ensure the extractor is defined properly")
	raise ImportError(f"No subclass of BaseExtractor found in {filepath}")

def select_extractor_class(settings, format_type):
	logger = setup_logger()
	logger.debug(f"Selecting extraction tool for format type {format_type}")
	tools = settings.get("extractionTools", {})
	default_extractor = settings.get("defaultExtractor", "")
	for tool_name, tool_data in tools.items():
		if format_type in tool_data.get("format_types", []):
			path = tool_data["path"]
			logger.debug(f"Extraction tool \"{tool_name}\" selected for format code {format_type}")
			return load_extractor_class(path)
	# Use the user-defined default scraper if one can't be identified for this format_type
	if default_extractor in tools:
		logger.info(f"No extractor matched for format type {format_type}, returning default extractor ({default_extractor})")
		return(load_extractor_class(tools[default_extractor]["path"]))
	else:
		logger.warning("default extractor could not be loaded")
	# Throw an error if a extractor can't be identified and loading the default fails		
	raise ValueError(f"No extractor found for format type {format_type}")