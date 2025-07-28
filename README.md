# Scraping-App
This is a Python-based modular application to aid in scraping text from PDF documents.

## File Structure:

### Directories - all generated at runtime if not already present
/data - location for input PDFs
/logs - output location for logfiles and audit reports
/scrapers - location for user-defined scraping tools built on base_scraper.py

### Project Files
*scraping_helper* - This is the main application shell, which handles UI setup and the main workflow

*mid_manager* - Handles excel input, spreadsheet navigation, and other related data functions

*base_scraper* - This is the abstract that individual scraping tools must inherit to interface with the app

*app_settings* - Defines default settings, as well as settings R/W to JSON

*logger* - Implements the logging structure for the entire application

*scraper_loader* - The engine that selects the correct scraping tool, sanitizes inputs & outputs, etc.

*settings_window* - UI and parsing for user settings

*scraping_tool_dialog* - Called by settings_window for interactive setup of scraping tools

*audit_runner* - Contains unit tests for checking data consistency and reliability

*flatten_directory* - Separate from the main application, standalone utility for removing files from folders. Helpful in setting up ./data.