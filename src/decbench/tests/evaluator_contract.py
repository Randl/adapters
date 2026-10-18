"""Run with the upstream evaluator interpreter, isolated from the generator package."""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

from decbench.utils import binfmt

spec = importlib.util.spec_from_file_location("verifier", sys.argv[1])
assert spec is not None and spec.loader is not None
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    sources = root / "sources"
    sources.mkdir()
    correct = "int target(int x) { return x + 1; }"
    (sources / "target.c").write_text(
        correct + "\nint main(void) { return target(2); }\n"
    )
    binary = root / "target.bin"
    subprocess.run(
        ["gcc", "-g", "-O0", str(sources / "target.c"), "-o", str(binary)], check=True
    )
    owners = binfmt.source_function_owners(binary, {"target"})
    address = next(pc for pc, owner in owners.items() if owner[0] == "target")
    problem = {
        "function": "target",
        "address": address,
        "binary": "target",
        "measurable": {"ged": True, "type_match": True, "byte_match": True},
    }
    for code in (correct, "```c\n" + correct + "\n```"):
        _, reward = verifier.score(problem, code, binary, root / "absent.json", sources)
        assert all(reward[f"{name}_perfect"] == 1 for name in problem["measurable"])
    _, changed = verifier.score(
        problem, correct.replace("+", "-"), binary, root / "absent.json", sources
    )
    assert changed["byte_match_perfect"] == 0
    assert (
        changed["ged_perfect"] == changed["type_match_perfect"] == changed["union"] == 1
    )
    for code in ("", "not C"):
        _, reward = verifier.score(problem, code, binary, root / "absent.json", sources)
        assert reward["union"] == 0
        assert all(reward[f"{name}_measured"] == 1 for name in problem["measurable"])
print("Pinned evaluator contract passed: exact, fenced, changed, empty and malformed C")
