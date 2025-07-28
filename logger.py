import logging
import os
import glob
from datetime import datetime
from app_settings import load_settings


def get_logging_level(level_name):
	return {
		"CRITICAL": logging.CRITICAL,
		"ERROR":	logging.ERROR,
		"WARNING":	logging.WARNING,
		"INFO":		logging.INFO,
		"DEBUG":	logging.DEBUG
	}.get(level_name.upper(), logging.INFO)

# Sets log retention policy based on User settings
def enforce_log_retention(log_dir, max_logs):
	log_files = sorted(
		glob.glob(os.path.join(log_dir, "app_*.log")),
		key = os.path.getmtime,
		reverse = True
	)

	for old_log in log_files[max_logs:]:
		try:
			os.remove(old_log)
		except Exception as e:
			print(f"[Warning] Failed to delete old log file: {old_log} - {e}")


def setup_logger():
	settings = load_settings()
	level_name = settings.get("loggingLevel", "INFO")
	log_dir = settings.get("logFileDirectory", os.path.join(os.path.dirname(__file__), "logs")) # will default to ./logs if the setting can't be loaded
	max_logs = int(settings.get("logRetention", 10))
	console_output = settings.get("consoleOutput", False)

	os.makedirs(log_dir, exist_ok=True)

	timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
	log_file = os.path.join(log_dir, f"app_{timestamp}.log")
	log_level = get_logging_level(level_name)

	logger = logging.getLogger("scraper")
	logger.setLevel(log_level)

	if not logger.handlers:
		handler = logging.FileHandler(log_file, mode = 'a', encoding = 'utf-8')
		formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
		handler.setFormatter(formatter)
		logger.addHandler(handler)

		# Enable Console Output for realtime log monitoring:
		if console_output != "File":
			console = logging.StreamHandler()
			console.setFormatter(formatter)
			logger.addHandler(console)

		# Enforce log retention policy
		enforce_log_retention(log_dir, max_logs)

	return logger