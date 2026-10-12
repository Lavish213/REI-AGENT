import ast
import csv
import hashlib
import json
import subprocess
from pathlib import Path


def inventory():
    root = Path(__file__).resolve().parents[2]
    output = root / "REI-AGENT/docs/system-audit"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("REI-AGENT", "Bob-Intelligence", "Sophia-Agent", "The-Dashboard"):
        repo = root / name
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
        for filename in filter(None, files):
            path = repo / filename
            if not path.is_file():
                continue
            data = path.read_bytes()
            row = {"repository": name, "file": filename, "bytes": len(data),
                   "lines": len(data.splitlines()), "sha256": hashlib.sha256(data).hexdigest(),
                   "imports": [], "route_declarations": []}
            if path.suffix == ".py":
                try:
                    tree = ast.parse(data.decode())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            row["imports"].extend(item.name for item in node.names)
                        elif isinstance(node, ast.ImportFrom):
                            row["imports"].append(node.module or "")
                        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                              and isinstance(node.func.value, ast.Name) and node.func.value.id in {"app", "router"}):
                            if node.func.attr in {"get", "post", "put", "patch", "delete", "websocket"}:
                                if node.args and isinstance(node.args[0], ast.Constant):
                                    row["route_declarations"].append([node.func.attr, node.args[0].value])
                except (SyntaxError, UnicodeDecodeError):
                    pass
            rows.append(row)
    (output / "file-map.json").write_text(json.dumps(rows, indent=2) + "\n")
    with (output / "file-map.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=["repository", "file", "bytes", "lines", "sha256"])
        writer.writeheader()
        writer.writerows({key: row[key] for key in writer.fieldnames} for row in rows)
    lines = ["# Tracked file map", "", "Static inventory, imports and route declarations; not runtime coverage.", ""]
    for name in ("REI-AGENT", "Bob-Intelligence", "Sophia-Agent", "The-Dashboard"):
        lines.append(f"- {name}: {sum(row['repository'] == name for row in rows)} tracked files")
    (output / "FILE-MAP.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    inventory()
