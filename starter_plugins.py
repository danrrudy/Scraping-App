"""The scrapers and extractors a fresh installation starts with.

A packaged build cannot install anything, so the plugin folders beside a new
installation would otherwise be empty and the application would have nothing to
read a document with. These few plugins ship inside the program and are copied
out on first run, where the user can read them, edit them, and use them as the
template for their own.

Only plugins that depend on what the build already contains belong here. The
table-detection scrapers need PyTorch and Tesseract, which are not packaged;
they remain external plugins for people running from source.

Copying is one-way and never overwrites. A file the user has changed — or
deleted because they did not want it — stays changed or deleted.
"""

import shutil
from pathlib import Path

import paths

#: For each kind of plugin: the subdirectory it is seeded into, the setting
#: naming where that kind is looked for, the registry of configured tools, and
#: the setting naming which one to fall back on.
PLUGIN_KINDS = {
    "scrapers": {
        "directory_setting": "scrapingToolDirectory",
        "registry_setting": "scrapingTools",
        "default_setting": "defaultScraper",
    },
    "extractors": {
        "directory_setting": "extractionToolDirectory",
        "registry_setting": "extractionTools",
        "default_setting": "defaultExtractor",
    },
}


def seed(settings=None, logger=None):
    """Copy any starter plugin that is not already present.

    Returns ``{kind: [paths written]}``, so a caller can register what a first
    run installed.
    """
    settings = settings or {}
    written = {}

    for kind, config in PLUGIN_KINDS.items():
        source = paths.resource_dir() / "bundled" / kind
        if not source.is_dir():
            continue

        destination = Path(
            settings.get(config["directory_setting"]) or paths.in_app_dir(kind)
        )
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if logger:
                logger.warning(f"Could not create plugin folder {destination}: {exc}")
            continue

        # A folder that already holds plugins belongs to the user. Seeding into
        # it would restore files they deleted on purpose.
        if any(destination.glob("*.py")):
            continue

        for plugin in sorted(source.glob("*.py")):
            target = destination / plugin.name
            try:
                shutil.copyfile(plugin, target)
                written.setdefault(kind, []).append(target)
            except OSError as exc:
                if logger:
                    logger.warning(f"Could not install starter plugin {target}: {exc}")

    if written and logger:
        names = ", ".join(path.name for group in written.values() for path in group)
        logger.info(f"Installed starter plugins: {names}")

    return written


def register(settings, written, logger=None):
    """Make the freshly installed plugins usable without a trip to Settings.

    A copied file is inert on its own: the application picks a tool out of the
    ``scrapingTools`` registry, so an unregistered plugin means a new
    installation still cannot read a document.

    Only an installation that has configured *nothing* is touched. If the
    registry has any entry, or a default is already chosen, the user has been
    here before and their choices stand.

    Returns True if the settings were changed and should be saved.
    """
    changed = False

    for kind, config in PLUGIN_KINDS.items():
        installed = written.get(kind)
        if not installed:
            continue
        if settings.get(config["registry_setting"]) or settings.get(
            config["default_setting"]
        ):
            continue

        registry = {}
        for path in installed:
            # No format codes: these are fallbacks, chosen when nothing else
            # matches, rather than tools bound to a particular document layout.
            registry[path.stem] = {"path": str(path), "format_types": []}

        settings[config["registry_setting"]] = registry
        settings[config["default_setting"]] = installed[0].stem
        changed = True

        if logger:
            logger.info(
                f"Registered {installed[0].stem} as the default "
                f"{kind[:-1]} for this installation"
            )

    return changed
