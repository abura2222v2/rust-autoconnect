import pytest

from src.core.benchmark_model import BENCHMARK_VERSION, build_run, configuration_key, median


def test_configuration_key_is_stable_for_display_spacing():
    left = configuration_key("AMD  Ryzen  7", "Samsung 990 Pro")
    right = configuration_key("AMD Ryzen 7", "Samsung 990 Pro")
    assert left == right


def test_configuration_key_changes_when_rust_storage_changes():
    first = configuration_key("AMD Ryzen 7", "Samsung 990 Pro")
    moved = configuration_key("AMD Ryzen 7", "External SSD")
    assert first != moved


def test_build_run_has_two_phases_and_no_serial_number_field():
    run = build_run("local-install", "AMD Ryzen 7", "Samsung 990 Pro", "NVMe", 35.5, 44.25)
    assert run["benchmark_version"] == BENCHMARK_VERSION
    assert run["total_time"] == 79.75
    assert "serial" not in run
    assert "path" not in run


@pytest.mark.parametrize("menu,demo", [(1.9, 20), (20, 601)])
def test_build_run_rejects_invalid_phases(menu, demo):
    with pytest.raises(ValueError):
        build_run("local-install", "CPU", "Disk", "NVMe", menu, demo)


def test_median_is_not_distorted_by_single_fast_run():
    assert median([20, 21, 150]) == 21.0
