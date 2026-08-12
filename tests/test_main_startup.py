import ast
from pathlib import Path


def test_main_does_not_arm_or_connect_a_server_on_startup():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = [ast.unparse(node.func) for node in ast.walk(main) if isinstance(node, ast.Call)]

    assert "history_store.set_armed_server" not in calls
    assert "app.start_process" not in calls
