$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUST_E2E = '0'
py -3 -m pytest tests -q --ignore=tests/stress_test.py --ignore=tests/simulate_reconnect_loop.py --basetemp .pytest_tmp\safe_ci
py -3 -m compileall -q src tests
git diff --check
