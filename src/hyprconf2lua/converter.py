from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from hyprconf2lua.lexer import tokenize, LexerError
from hyprconf2lua.parser import parse_config, ParserError
from hyprconf2lua.codegen import Codegen
from hyprconf2lua.ast import ConfigFile, SourceDirective


class ConversionError(Exception):
    pass


class ConversionResult:
    def __init__(self, lua: str, report: dict, errors: list, warnings: list):
        self.lua = lua
        self.report = report
        self.errors = errors
        self.warnings = warnings

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    @property
    def coverage(self) -> float:
        total = self.report.get("translated", 0) + self.report.get("passthrough", 0) + self.report.get("flagged", 0)
        if total == 0:
            return 100.0
        return round(self.report.get("translated", 0) / total * 100, 1)


def _load_sources(config: ConfigFile, base_dir: str, seen: Optional[set[str]] = None) -> ConfigFile:
    """Load source= files so their variables/directives are available to codegen."""
    if seen is None:
        seen = set()

    merged = []

    for stmt in config.body:
        if not isinstance(stmt, SourceDirective):
            merged.append(stmt)
            continue

        path = stmt.path.strip()

        # Glob sources are intentionally left alone for now.
        if "*" in path or "?" in path or "[" in path:
            merged.append(stmt)
            continue

        if path.startswith("~"):
            path = os.path.expanduser(path)
        elif not os.path.isabs(path):
            path = os.path.join(base_dir, path)

        path = os.path.realpath(path)

        if path in seen:
            continue

        if not os.path.isfile(path):
            merged.append(stmt)
            continue

        seen.add(path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            sourced = parse_config(source)
            sourced = _load_sources(sourced, os.path.dirname(path), seen)
            merged.extend(sourced.body)
        except (OSError, ParserError):
            merged.append(stmt)

    return ConfigFile(merged)


def convert(source: str) -> ConversionResult:
    errors: list = []
    warnings: list = []

    try:
        tokens = tokenize(source)
    except LexerError as e:
        errors.append(str(e))
        return ConversionResult("", {"translated": 0, "passthrough": 0, "flagged": 0}, errors, warnings)

    try:
        config = parse_config(source)
        config = _load_sources(config, os.getcwd())
    except ParserError as e:
        errors.append(str(e))
        return ConversionResult("", {"translated": 0, "passthrough": 0, "flagged": 0}, errors, warnings)

    gen = Codegen()
    try:
        lua = gen.generate(config)
    except Exception as e:
        errors.append(f"Code generation error: {e}")
        return ConversionResult("", {"translated": 0, "passthrough": 0, "flagged": 0}, errors, warnings)

    report = gen.get_report()

    if report["flagged"] > 0:
        warnings.append(f"{report['flagged']} directive(s) flagged for manual review")

    return ConversionResult(lua, report, errors, warnings)
