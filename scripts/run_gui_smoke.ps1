$ErrorActionPreference = 'Stop'
# Explicit visual check; never launches Steam/Rust or reads the real Player.log.
py -3 tests\gui_smoke.py
