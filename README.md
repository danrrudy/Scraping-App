# Scraping-App
The Scraping App is a configurable document review and data extraction application designed to assist in structured evaluation workflows. The system allows users to load a Master Input Document (MID), navigate entries, scrape data from associated documents, extract structured content, and classify results using customizable evaluation classes.

The application is designed to be modular and extensible. Scraping tools, extraction tools, and classification schemes can be added or modified without changing the core application code.

This README provides a high-level overview of the project, installation instructions, configuration guidance, and general usage notes. For detailed operational instructions, refer to the User Guide. For implementation details, refer to the Technical Documentation.

## File Structure:

### Files and Folders outside of Code Directory
The following sections refer to files specifically related to the Scraping Application in the "Python Content ..." Folder. This section addresses all other files related to the project as of April 2026. 

**/Documentation** - Contains detailed descriptions of various project components:
*Codebook* - Describes variables in the program's output

*User Guide* - Provides instructions on installation and operation of the program as a non-developer user

*Codebase Documentation* - Discusses the technical components of the program and advice for making modifications to the code.

*Case Review* - Contains a chronological account of edge cases considered while developing the database and how they were resolved. This file may be useful if attempting to recreate the data, especially in ambiguous cases.

**/PAR-GAO Completed (06-14-2025)** - Contains the following directories:

**/Final Output** - Contains the output spreadsheet

**/Highlighted Agency-Year GAO-PARs PDFs** - Contains the original set of PDF documents used as input. Reports are contained within agency folders, in addition to the "Revised Uniform Filename Format" directory, where they are standardized to the format the program expects as input. 

**/Intermediate Output** - Contains the spreadsheet and user_settings.json files as of Feb 16, 2026 as a backup and reference if needed.

**/Table Detection Results** - Proof of concept for the Microsoft Table Transformer as a table scraping engine. Contains images of all tables that were successfully extracted from documents, overlayed with the structural components MTT was able to identify. The contents of this folder may be useful if you are seeking to finish implementing the table scraping code, but has no other use at this time.

All other files in the "PAR-GAO Completed" directory are the original project documentation from its inception. Briefly:

*Comparative_Agency_Performance* - Paper related to the project's purpose

*CUP Elements Draft* - Resh & Cho paper on PAR report performance information

*PAR Data Dictionary* - Original Description of key data fields, contains more detail on input fields than the final data dictionary, but does not contain any of the newly-added fields.

*PAR Data Format Overview* - Descriptions of how PARs report performance information as initially enumerated to inform the Format_Type variable.

*PAR Database.READ ME* - README document corresponding to the input spreadsheet (MID) describing fields and scope of the project. Three versions provided with sequential updates.

*Resh & Cho PARs database* - Initial MID used as program input at setup.




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

*table_scraper* - Performs simple table detection using Microsoft table Transformer. *Current form does not extract text as MTT returns structured data that requires not-yet-implemented post-processing steps to recreate the scraped table(s)*. Returns the following dictionary:
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
Please note that this is a summary of installation steps; for detailed instructions and troubleshooting, see the user guide.

1. Clone this repository to your machine or otherwise download the files
2. Before running for the first time, open a terminal in the top-level folder (/Scraping-App/), and run "pip install -r requirements.txt" - This will install all of the necessary python packages. Please note that this includes several large files and may take up to 30 minutes on slower internet connections.
3. In the terminal, run "python scraping_helper.py" - This will launch the main application, which will generate the file structure it needs. You may encounter errors upon the first launch, please try to re-lauch up to 3 times to ensure all necessary files are created before running. 
4. Open the settings menu and minimally configure the following settings:
* Master Input Document - The Master Input Document (MID) should point to an excel spreadsheet containing information on your document corpus. The requirements for this file are defined later in this document. 

You should save your settings to Scraping-App/user_settings.json now so they are loaded automatically in the future.


### Running
The Application contains three modes for runtime: user mode, reviewer mode, and developer mode. Developer mode can be enabled in settings, and is described later in this document. The following information pertains only to user & reviewer mode. 

1. Set up Scraping Tools
There are several scraping tools included in this repository by default, and you may add your own as needed. The requirements for user-defined scrapers are described later in this document.

To set up scraping tools, open the settings menu and click "Set Up Scraping Tools". This will open a new dialog window. Ensure that the scraping tool directory is set to a subfolder of /Scaping-App/. The default is ./scrapers. For each tool you wish to add, click "Add Scraping Tool", enter a plain-english name for the tool, select the python file for the tool, then enter the format codes to map that tool to. Format codes must be positive integers, and the list should be comma-separated (whitespace is ignored).

Click OK on both the Scraping Tool and Main Settings dialogs (save main settings if desired).

2. Load Documents

Once the MID is loaded, the application will attempt to load the first document listed, and scrape its contents. If your tools are correctly configured and the MID was defined properly, you should see the scraped page contents in the right sidebar. If no text appears, or an error message displays, check the logs to identify the issue. 

3. Fill in performance information 

The Application will automatically load the correct page(s) defined for each document. You can use the "Next Page" and "Previous Page" buttons to navigate within this range. These buttons will not respond if you try to navigate beyond the page range defined in the MID, and an info message will be written to the log (and/or console, depending on your settings).

The main workflow consists of transferring information from the right pane (scraped text) to text fields on the left pane (control panel). Hotkeys and function buttons are implemented to greatly simplify and speed up this process, which are described in full in the user guide.

4. Save output

The program maintains a copy of the spreadsheet in memory, which is updated each time the user moves to a different MID entry or saves the MID. The spreadsheet in memory is *only* saved to a file when the user saves the MID, either through File->Save or Ctrl+S. Closing the program without saving will erase all unsaved changes.

5. Review Output

Changing to reviewer mode and setting the MID to the output spreadsheet allows for a simple process to review the results. Reviewer mode enables additional controls to identify any entries that appear to be incorrect. Advancing through all of the entries in reviewer mode and saving the spreadsheet again (this can be done in stages if the spreadsheet is saved and reloaded between sessions) produces a list of "ACCEPT" or "REJECT" tags for each entry to guide any manual corrections that are necessary.


## More Information
Detailed information on using the program is provided in the User Guide. Details on code functionality are described at a high level in the codebase documentation, and more granularly within the code. Variable descriptions are detailed in the codebooks (See the final codebook for new variables and how they were coded in practice, and the original codebook for more detail on the initial set of varaibles.) Updated versions of the code may be available [on github](https://github.com/danrrudy/Scraping-App), but may have different functionality than this version. Update at your own risk!

---
