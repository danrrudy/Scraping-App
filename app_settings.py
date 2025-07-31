# app_settings.py
import json
import os

#######################################
# WARNING: NO LOGGING IN THIS FILE    #
# LOGGER CANNOT BE CALLED HERE DUE TO #
# CIRCULAR DEPENDENCIES! WARNINGS AND #
# ERRORS IN THIS FILE ARE WRITTEN TO  #
# CONSOLE ONLY!                       #
#######################################

# Default application settings
# Options defined in settings_window.py
default_settings = {
    "fontSize": "12", # Font size for display
    "MIDLocation": "", # File location of the MID
    "MIDSheetName": "", # Sheet name within the MID to use
    "loggingLevel": "INFO", # Minimum severity of messages to log
    # NOTE: logs will be saved to ./logs if this variable can't be found by the logger!
    "logFileDirectory": os.path.join(os.path.dirname(__file__), "logs"), # Default: ./logs
    "logRetention": 10, # Maximum number of log files to keep
    "consoleOutput": "Both", # Writes log to console as well
    "scrapingToolDirectory": os.path.join(os.path.dirname(__file__), "scrapers"), # Default: ./scrapers
    "scrapingTools": {},
    "dataDirectory": os.path.join(os.path.dirname(__file__), "data"), # Default: ./data
    "defaultScraper": "" # Name of the scraper to use as a fallback
}

# Default location for settings file
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "user_settings.json")

def load_settings(path=SETTINGS_PATH):
    """Load settings from file or return defaults if file not found or invalid."""
    if not os.path.exists(path):
        save_settings(default_settings, path)
        return default_settings.copy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_settings = json.load(f)

            filtered_settings = {
                key: value for key, value in user_settings.items()
                if key in default_settings
            }

            unexpected_keys = set(user_settings) - set(default_settings)
            if unexpected_keys:
                print(f"[Warning] Ignored unknown setting(s): {unexpected_keys}")
            
            # Merge defaults with user settings (preserve fallback values)
            merged = default_settings.copy()
            merged.update(filtered_settings)

            # Confirm that Logging directory exists or create 
            log_dir = merged.get("logFileDirectory")
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            return merged
    except Exception as e:
        print(f"[Warning] Failed to load settings: {e}")
        return default_settings.copy()

def save_settings(settings, path=SETTINGS_PATH):
    """Save settings to file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save settings: {e}")
