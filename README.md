# Scraping-App
This is a Python-based modular application to aid in scraping text from PDF documents.

## File Structure:

### Directories - all generated at runtime if not already present
**/data** - location for input PDFs

**/logs** - output location for logfiles and audit reports

**/scrapers** - location for user-defined scraping tools built on base_scraper.py

**/utils** - Contains standalone python files that are helpful alongside this application

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

*image_utils* - Contains helper functions for image processing, including PDF to image conversion.

### Scrapers
*text_scraper* - Performs simple PDF -> plain text scraping via PyMuPDF (fitz). Returns the following dictionary:
* text: two newlines before all of the extracted text
* page: an array of page numbers scraped (1-indexed)
* method: "TextScraper"

*table_scraper* - Performs simple table detection using Microsoft table Transformer. Current form does not extract text as MTT returns structured data that requires not-yet-implemented post-processing steps to recreate the scraped table(s). CURRENTLY LIMITED TO A SINGLE PAGE AT A TIME. Returns the following dictionary:
* tables_found: an integer count of the number of tables detected
* text: "# table(s) detected" - NOT the contents of the table(s)!!!
* page: the single page number that was scraped (1-indexed)
* method: "TableScraper"


### Utility Files
*fileMGMTUtil* - Allows the user to perform several operations on batches of files in a command-line interface:
* cd <folder>                                              Change working directory
* rename <find_str> <replace_str> [--recursive]            Rename files in current directory
* duplicate <file_or_folder> <new_name_original> <copy>    Duplicate file or all files in a folder, and rename both old & new versions
* help                                                     Show program help message
* exit / quit                                              Exit the program
* expand <file>                                            Expand multi-year file into one per year by duplicating and renaming

*flatten_directory* - Extracts contents from all subfolders in the current directory and deletes those folders
* Operation runs immediately upon execution, and is not reversible!

*mtt_table_detector_POC* - Proof of Concept for Microsoft Table Transformer for automated table detection. Takes an image (of a page) as input, prints to console the confidence score of all detected tables.


## Usage

This application is designed as an all-in-one text scraping environment for processing many documents of mixed formats. It allows the user to define their own scraping tools as individual python files, and map those tools to different document formats interactively.

### Dependencies

Python 3.x (exact version requirements unknown)
Packages listed in "requirements.txt"
Windows 11 (not tested on any other OS)

### Installation

1. Clone this repository to your machine
2. Before running for the first time, open a terminal in the top-level folder (/Scraping-App/), and run "pip install -r requirements.txt" - This will install all of the necessary python packages. Please note that this includes several large files and may take up to 30 minutes on slower internet connections.
3. In the terminal, run "python scraping_helper.py" - This will launch the main application, which will generate the file structure it needs. You may encounter errors upon the first launch, please try to re-lauch up to 3 times to ensure all necessary files are created before running. 
4. Open the settings menu and minimally configure the following settings:
* Master Input Document - The Master Input Document (MID) should point to an excel spreadsheet containing information on your document corpus. The requirements for this file are defined later in this document. 

You should save your settings to Scraping-App/user_settings.json now so they are loaded automatically in the future.


### Running
The Application contains two modes for runtime: user mode and developer mode. Developer mode can be enabled in settings, and is described later in this document. The following information pertains only to user mode. 

1. Set up Scraping Tools
There are several scraping tools included in this repository by default, and you may add your own as needed. The requirements for user-defined scrapers are described later in this document.

To set up scraping tools, open the settings menu and click "Set Up Scraping Tools". This will open a new dialog window. Ensure that the scraping tool directory is set to a subfolder of /Scaping-App/. The default is ./scrapers. For each tool you wish to add, click "Add Scraping Tool", enter a plain-english name for the tool, select the python file for the tool, then enter the format codes to map that tool to. Format codes must be positive integers, and the list should be comma-separated (whitespace is ignored).

Click OK on both the Scraping Tool and Main Settings dialogs (save main settings if desired).

2. Load Documents

Once the MID is loaded, the application will attempt to load the first document listed, and scrape its contents. If your tools are correctly configured and the MID was defined properly, you should see the scraped page contents in the right sidebar. If no text appears, or an error message displays, check the logs to identify the issue. 

3. Review Scraping Accuracy

The Application will automatically load the correct page(s) defined for each document. You can use the "Next Page" and "Previous Page" buttons to navigate within this range. These buttons will not respond if you try to navigate beyond the page range defined in the MID, and an info message will be written to the log (and/or console, depending on your settings).

As each page is loaded, the application will attempt to scrape it and display its text. If the content is correct, click "Accept Scrape", if not, click "Reject Scrape". Both buttons will advance to the next MID entry. 


END OF IMPLEMENTED FUNCTIONALITY 

---


