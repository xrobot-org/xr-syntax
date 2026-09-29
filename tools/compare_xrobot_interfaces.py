"""比较当前 XRobot manifest 配置与 xr-syntax 构造函数视图。
Compare current XRobot manifest configuration with xr-syntax constructor views.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path

from xrobot.ModuleParser import parse_constructor_args, parse_manifest_from_header

from xr_syntax.cpp import CppDocument, CppParameterView


def _normalized_type(value: str | None) -> str:
    """压缩类型文本中的空白，供固定前置参数识别。
    Normalize whitespace in type text for fixed-prefix parameter detection.
    """
    return "" if value is None else re.sub(r"\s+", "", value)


def _primary_headers(root: Path) -> Iterable[Path]:
    """枚举 module/module.hpp 形式的主头文件。
    Enumerate primary module headers using the module/module.hpp convention.
    """
    for header in sorted(root.rglob("*.hpp")):
        if header.stem == header.parent.name:
            yield header


def _is_application_prefix(parameters: tuple[CppParameterView, ...]) -> bool:
    """判断构造函数是否以 XRobot 固定 hw/app 参数开头。
    Return whether a constructor starts with XRobot's fixed hardware/app parameters.
    """
    if len(parameters) < 2:
        return False
    first = _normalized_type(parameters[0].type)
    second = _normalized_type(parameters[1].type)
    return "HardwareContainer" in first and "ApplicationManager" in second


def compare_header(header: Path) -> dict[str, object]:
    """比较一个模块主头文件，并返回可序列化结果。
    Compare one primary module header and return a serializable result row.
    """
    module_name = header.parent.name
    result: dict[str, object] = {
        "module": module_name,
        "header": str(header),
    }

    manifest = parse_manifest_from_header(header)
    if manifest is None:
        result["status"] = "skipped-no-manifest"
        return result

    constructor_args = parse_constructor_args(manifest.constructor_args)
    template_args = parse_constructor_args(manifest.template_args)
    result["manifest_constructor_args"] = list(constructor_args)
    result["manifest_template_args"] = list(template_args)

    document = CppDocument.parse(header.read_bytes(), source_name=str(header))
    result["diagnostics"] = [item.message for item in document.diagnostics]

    classes = document.class_views(module_name)
    result["class_count"] = len(classes)
    if len(classes) != 1:
        result["status"] = "mismatch"
        result["reason"] = "class-count"
        return result

    class_view = classes[0]
    result["cpp_template_parameters"] = [
        {
            "name": parameter.name,
            "type": parameter.type,
            "default": parameter.default,
        }
        for parameter in class_view.template_parameters
    ]

    constructors = class_view.constructors(public_only=True, callable_only=True)
    result["constructors"] = [
        [
            {
                "name": parameter.name,
                "type": parameter.type,
                "default": parameter.default,
            }
            for parameter in constructor.parameters
        ]
        for constructor in constructors
    ]

    candidates = [
        (index, len(constructor.parameters) - 2)
        for index, constructor in enumerate(constructors)
        if _is_application_prefix(constructor.parameters)
    ]
    result["application_constructor_candidates"] = candidates

    constructor_match = any(extra_count == len(constructor_args) for _, extra_count in candidates)
    template_match = len(class_view.template_parameters) == len(template_args)
    result["constructor_count_match"] = constructor_match
    result["template_count_match"] = template_match

    if constructor_match and template_match:
        result["status"] = "match"
    else:
        result["status"] = "mismatch"
        result["reason"] = "constructor-count" if not constructor_match else "template-count"
    return result


def compare_modules(root: Path) -> dict[str, object]:
    """比较目录中的全部主模块头文件并汇总结果。
    Compare every primary module header below a directory and summarize the results.
    """
    rows: list[dict[str, object]] = [compare_header(header) for header in _primary_headers(root)]
    mismatches = [row for row in rows if row["status"] == "mismatch"]
    skipped = [row for row in rows if str(row["status"]).startswith("skipped-")]
    matches = [row for row in rows if row["status"] == "match"]
    return {
        "primary_headers": len(rows),
        "eligible": len(matches) + len(mismatches),
        "matches": len(matches),
        "mismatches": len(mismatches),
        "skipped": len(skipped),
        "rows": rows,
        "mismatch_rows": mismatches,
        "skipped_rows": skipped,
    }


def main() -> None:
    """运行 XRobot manifest/constructor golden parity。
    Run XRobot manifest/constructor golden parity.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("modules", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="report mismatches without returning a failing exit code",
    )
    args = parser.parse_args()

    result = compare_modules(args.modules)
    print(
        f"primary_headers={result['primary_headers']} "
        f"eligible={result['eligible']} matches={result['matches']} "
        f"mismatches={result['mismatches']} skipped={result['skipped']}"
    )
    for row in result["mismatch_rows"]:
        print("MISMATCH", row["module"], row.get("reason"))
    for row in result["skipped_rows"]:
        print("SKIP", row["module"], row["status"])

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if result["mismatches"] and not args.allow_mismatch:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
