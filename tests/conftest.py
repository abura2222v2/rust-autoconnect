import logging
import pytest
from src.core.config import AppConfig
from src.core.logger import app_logger


@pytest.fixture(autouse=True, scope="session")
def _never_touch_real_appdata(tmp_path_factory):
    """Some tests spawn background threads (WebBridge, AppController) that can
    outlive their own function-scoped monkeypatch of AppConfig.data_file and
    later call history_store.save() using the real path once that patch has
    been undone. Redirect it globally for the whole session so nothing in the
    suite can ever write to the user's real saved-server history, regardless
    of which individual test's cleanup missed a thread."""
    shared_dir = tmp_path_factory.mktemp("shared_appdata")
    mp = pytest.MonkeyPatch()
    mp.setattr(AppConfig, "appdata_dir", property(lambda self: shared_dir))
    mp.setattr(AppConfig, "data_file", property(lambda self: shared_dir / "data.json"))
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def cleanup_logging_handlers():
    yield
    for handler in app_logger.logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            try:
                handler.close()
                app_logger.logger.removeHandler(handler)
            except Exception:
                pass
