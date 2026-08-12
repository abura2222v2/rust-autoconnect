from unittest.mock import MagicMock

from src.gui.main_window import MainWindow


class _Value:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_legacy_ranking_label_opens_the_ranking_panel_not_the_run_log():
    """Old saved/UI labels must never leave the Run log covering Ranking."""
    window = object.__new__(MainWindow)
    window.t = lambda key: {"tab_run_log": "Run log", "tab_online_ranking": "Online ranking"}[key]
    window.bench_view_var = _Value("Run log")
    window.bench_log = MagicMock()
    window.bench_online_ranking = MagicMock()
    window._load_online_benchmark_ranking = MagicMock()

    MainWindow.show_benchmark_view(window, "Ranking")

    assert window.bench_view_var.get() == "Online ranking"
    window.bench_log.grid_remove.assert_called_once_with()
    window.bench_online_ranking.grid_remove.assert_called_once_with()
    window.bench_online_ranking.grid.assert_called_once_with(row=0, column=0, sticky="nsew")
    window.bench_log.grid.assert_not_called()
    window._load_online_benchmark_ranking.assert_called_once_with()
