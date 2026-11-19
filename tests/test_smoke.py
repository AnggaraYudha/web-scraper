import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "web_scraper",
        "web_scraper.models",
        "web_scraper.extractor",
        "web_scraper.discovery",
        "web_scraper.stealth",
        "web_scraper.cli",
    ],
)
def test_package_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module is not None
