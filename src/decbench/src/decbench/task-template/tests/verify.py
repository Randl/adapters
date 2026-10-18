"""Evaluate submitted C through the pinned upstream metric implementation."""

import json
from pathlib import Path

from decbench.decompilers.llm_dec import _read_address_lines, _rename_func, _sanitize
from decbench.metrics import MetricRegistry
from decbench.models.decompilation import (
    DecompilationResult,
    DecompilerMetadata,
    FunctionDecompilation,
)
from decbench.pipeline.evaluate import evaluate_decompilation
from decbench.utils import binfmt
from decbench.utils.cfg import (
    best_source_by_name,
    extract_cfgs_from_source,
    resolved_source_for_binary,
)
from decbench.utils.dwarf_policy import dwarf_follow_abstract_origin

PERFECT = {"ged": 0.0, "type_match": 1.0, "byte_match": 1.0}


def score(
    problem: dict, code: str, original: Path, mappings: Path, sources: Path
) -> tuple[dict, dict]:
    code = _rename_func(_sanitize(code), problem["function"])
    function = FunctionDecompilation(
        name=problem["function"],
        address=problem["address"],
        decompiled_code=code,
        line_count=len(code.splitlines()),
        line_mappings=_read_address_lines(mappings, code, original),
    )
    result = DecompilationResult(
        binary_path=original,
        binary_name=problem["binary"],
        decompiler=DecompilerMetadata(decompiler_name="harbor"),
        functions={function.name: function},
    )
    source = {}
    if problem["measurable"]["ged"]:
        parsed = {
            p.stem: extract_cfgs_from_source(p, raise_on_error=True)
            for p in sorted(sources.glob("*.c"))
        }
        if not parsed:
            raise RuntimeError("Missing private source assets")
        owners = binfmt.source_function_owners(
            original, set(parsed), follow_abstract_origin=dwarf_follow_abstract_origin()
        )
        source = resolved_source_for_binary(
            problem["binary"],
            parsed,
            best_source_by_name(parsed),
            function_owners=owners,
        )
    # Parser/import failures are infrastructure failures, not zero scores.
    import rust_joern

    if not callable(rust_joern.parse_source):
        raise TypeError("CFG parser unavailable")
    for name in PERFECT:
        MetricRegistry.get(name)
    results = evaluate_decompilation(result, source, list(PERFECT))
    raw = {name: metric.model_dump(mode="json") for name, metric in results.items()}
    rewards = {}
    measured = []
    for name, target in PERFECT.items():
        metric = results.get(name)
        if metric is None:
            value = None
        else:
            if metric.errors:
                raise RuntimeError(f"{name} evaluator failed: {metric.errors}")
            value = metric.function_results.get(function.name)
        rewards[f"{name}_measured"] = int(problem["measurable"][name])
        rewards[f"{name}_perfect"] = int(
            problem["measurable"][name] and value is not None and value.value == target
        )
        measured.append(rewards[f"{name}_perfect"])
    rewards["union"] = int(any(measured))
    return raw, rewards


def main() -> None:
    problem = json.loads(Path("/tests/problem.json").read_text())
    path = Path("/workspace/decompiled.c")
    try:
        if path.is_symlink() or path.stat().st_size > 1_000_000:
            raise ValueError("Invalid C submission")
        code = path.read_text()
        if not code.strip():
            raise ValueError("Empty C submission")
    except (OSError, UnicodeError, ValueError):
        # Empty reconstruction goes through upstream evaluation so metric
        # availability is determined from the real target, including abstentions.
        code = ""
    raw, rewards = score(
        problem,
        code,
        Path("/tests/original.bin"),
        Path("/workspace/address_lines.json"),
        Path("/tests/sources"),
    )
    Path("/logs/verifier/evaluation.json").write_text(
        json.dumps({"task_id": problem["task_id"], "metrics": raw}, indent=2)
    )
    Path("/logs/verifier/reward.json").write_text(json.dumps(rewards))
    Path("/logs/verifier/reward.txt").write_text(str(rewards["union"]))


if __name__ == "__main__":
    main()
