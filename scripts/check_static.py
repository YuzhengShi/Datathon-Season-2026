"""Static checks that need no third-party packages.

They exist because part of this code base (FastAPI/SQLAlchemy/Typer layers) was written in an
environment where those libraries could not be installed. They catch the mistakes a human or an
agent makes most often there: syntax newer than Python 3.11, unused/missing imports, internal imports
that point at names that do not exist, and ORM models drifting away from the hand-written migration.
Run: ``python scripts/check_static.py`` (exit 1 on any finding).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE_FILES = sorted(SRC.rglob("*.py"))
ALL_FILES = sorted(
    [
        *PACKAGE_FILES,
        *ROOT.joinpath("migrations").rglob("*.py"),
        *ROOT.joinpath("scripts").glob("*.py"),
        *ROOT.joinpath("tests").rglob("*.py"),
    ]
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def check_py311_fstrings(files: list[Path]) -> list[str]:
    """Python 3.11 forbids a backslash or the outer quote character inside an f-string expression."""
    findings = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.FormattedValue):
                        segment = ast.get_source_segment(source, part.value) or ""
                        if "\\" in segment:
                            findings.append(
                                f"{path.relative_to(ROOT)}:{part.lineno}: backslash inside f-string expression (needs 3.12)"
                            )
    return findings


def _imported_names(tree: ast.Module) -> list[tuple[str, int]]:
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [((a.asname or a.name).split(".")[0], node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            names += [(a.asname or a.name, node.lineno) for a in node.names if a.name != "*"]
    return names


def check_unused_imports(files: list[Path]) -> list[str]:
    findings = []
    for path in files:
        if path.name == "__init__.py":
            continue  # re-export modules
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        }
        text_names = set()
        for node in ast.walk(tree):  # names used only inside string annotations
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text_names.update(
                    w
                    for w in node.value.replace("[", " ").replace("]", " ").replace("|", " ").replace(",", " ").split()
                    if w.isidentifier()
                )
        exported = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                exported = {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
        lines = source.splitlines()
        for name, lineno in _imported_names(tree):
            if name in used or name in text_names or name in exported or "noqa" in lines[lineno - 1]:
                continue
            findings.append(f"{path.relative_to(ROOT)}:{lineno}: unused import {name!r}")
    return findings


def _module_names(path: Path) -> set[str]:
    names = set()
    for node in _tree(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.If):  # e.g. conditional definitions
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
    return names


def check_internal_imports(files: list[Path]) -> list[str]:
    """Every ``from navigator.x import y`` must resolve to an existing module and a name defined in it."""
    findings = []
    for path in files:
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] == "navigator"
                and node.level == 0
            ):
                base = SRC.joinpath(*node.module.split("."))
                module_file = base.with_suffix(".py") if base.with_suffix(".py").exists() else base / "__init__.py"
                if not module_file.exists():
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: module {node.module} does not exist")
                    continue
                defined = _module_names(module_file)
                for alias in node.names:
                    is_submodule = (base / f"{alias.name}.py").exists() or (base / alias.name / "__init__.py").exists()
                    if alias.name not in defined and not is_submodule:
                        findings.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: {node.module} defines no {alias.name!r}"
                        )
    return findings


def check_undefined_names(files: list[Path]) -> list[str]:
    """Names that are read in a function/class but never defined, imported or built in (F821-like)."""
    import builtins
    import symtable

    findings = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        top = symtable.symtable(source, str(path), "exec")
        defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
        defined |= {"__file__", "__name__", "__doc__", "__package__", "__spec__"}
        stack = list(top.get_children())
        while stack:
            table = stack.pop()
            stack.extend(table.get_children())
            for sym in table.get_symbols():
                name = sym.get_name()
                if sym.is_global() and sym.is_referenced() and name not in defined and not hasattr(builtins, name):
                    findings.append(f"{path.relative_to(ROOT)}: undefined name {name!r} (in {table.get_name()})")
    return findings


# ----------------------------------------------------------------- ORM models vs migration


def _call_name(node: ast.AST) -> str:
    func = node.func if isinstance(node, ast.Call) else node
    return ast.unparse(func).split(".")[-1]


def _type_of(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    name = _call_name(node)
    if name in {"String", "Text", "Integer", "Boolean", "JSON"}:
        args = [ast.unparse(a) for a in node.args] if isinstance(node, ast.Call) else []
        return f"{name}({','.join(args)})" if args else name
    return None


def _kw(call: ast.Call, key: str):
    return next((k.value for k in call.keywords if k.arg == key), None)


def _lit(node: ast.AST | None):
    return ast.literal_eval(node) if node is not None else None


def _empty_table() -> dict:
    return {"columns": {}, "pk": set(), "unique": {}, "checks": set(), "indexes": {}, "fkc": set()}


def _constraint(table: dict, item: ast.Call) -> None:
    kind = _call_name(item)
    if kind == "UniqueConstraint":
        table["unique"][_lit(_kw(item, "name"))] = tuple(_lit(a) for a in item.args)
    elif kind == "CheckConstraint":
        table["checks"].add(_lit(_kw(item, "name")))
    elif kind == "Index":
        table["indexes"][_lit(item.args[0])] = tuple(_lit(a) for a in item.args[1:])
    elif kind == "PrimaryKeyConstraint":
        table["pk"].update(_lit(a) for a in item.args)
    elif kind == "ForeignKeyConstraint":
        table["fkc"].add((tuple(_lit(item.args[0])), tuple(_lit(item.args[1])), _lit(_kw(item, "ondelete"))))


def models_schema() -> dict[str, dict]:
    tables: dict[str, dict] = {}
    for cls in [n for n in _tree(SRC / "navigator/models/tables.py").body if isinstance(n, ast.ClassDef)]:
        name = next(
            (_lit(s.value) for s in cls.body if isinstance(s, ast.Assign) and s.targets[0].id == "__tablename__"), None
        )
        if name is None:
            continue
        table = tables[name] = _empty_table()
        for stmt in cls.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.value, ast.Call)
                and _call_name(stmt.value) == "mapped_column"
            ):
                call, annotation = stmt.value, ast.unparse(stmt.annotation)
                fk = next((a for a in call.args if isinstance(a, ast.Call) and _call_name(a) == "ForeignKey"), None)
                is_pk = bool(_lit(_kw(call, "primary_key")))
                nullable = _lit(_kw(call, "nullable")) if _kw(call, "nullable") is not None else ("None" in annotation)
                table["columns"][stmt.target.id] = {
                    "nullable": False if is_pk else bool(nullable),
                    "type": next((ty for ty in (_type_of(a) for a in call.args) if ty), None),
                    "fk": (_lit(fk.args[0]), _lit(_kw(fk, "ondelete"))) if fk else None,
                }
                if is_pk:
                    table["pk"].add(stmt.target.id)
            elif isinstance(stmt, ast.Assign) and stmt.targets[0].id == "__table_args__":
                for item in stmt.value.elts:
                    _constraint(table, item)
    return tables


def migration_schema() -> dict[str, dict]:
    tables: dict[str, dict] = {}
    source = _tree(ROOT / "migrations/versions/0001_initial.py")
    upgrade = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    for call in [n.value for n in upgrade.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]:
        op = _call_name(call)
        if op == "create_table":
            table = tables[_lit(call.args[0])] = _empty_table()
            for item in call.args[1:]:
                if _call_name(item) == "Column":
                    fk = next((a for a in item.args if isinstance(a, ast.Call) and _call_name(a) == "ForeignKey"), None)
                    is_pk = bool(_lit(_kw(item, "primary_key")))
                    nullable = _lit(_kw(item, "nullable")) if _kw(item, "nullable") is not None else True
                    table["columns"][_lit(item.args[0])] = {
                        "nullable": False if is_pk else bool(nullable),
                        "type": _type_of(item.args[1]),
                        "fk": (_lit(fk.args[0]), _lit(_kw(fk, "ondelete"))) if fk else None,
                    }
                    if is_pk:
                        table["pk"].add(_lit(item.args[0]))
                else:
                    _constraint(table, item)
        elif op == "create_index":
            tables[_lit(call.args[1])]["indexes"][_lit(call.args[0])] = tuple(_lit(call.args[2]))
    return tables


def check_schema_sync() -> list[str]:
    models, migration = models_schema(), migration_schema()
    findings = []
    if set(models) != set(migration):
        findings.append(
            f"tables differ: models-only {sorted(set(models) - set(migration))}, migration-only {sorted(set(migration) - set(models))}"
        )
    for name in sorted(set(models) & set(migration)):
        m, g = models[name], migration[name]
        if set(m["columns"]) != set(g["columns"]):
            findings.append(f"{name}: columns differ {sorted(set(m['columns']) ^ set(g['columns']))}")
        for col in set(m["columns"]) & set(g["columns"]):
            a, b = m["columns"][col], g["columns"][col]
            if a["nullable"] != b["nullable"]:
                findings.append(f"{name}.{col}: nullable {a['nullable']} (model) vs {b['nullable']} (migration)")
            if a["type"] and b["type"] and a["type"] != b["type"]:
                findings.append(f"{name}.{col}: type {a['type']} vs {b['type']}")
            if a["fk"] != b["fk"]:
                findings.append(f"{name}.{col}: foreign key {a['fk']} vs {b['fk']}")
        for key in ("pk", "unique", "checks", "indexes", "fkc"):
            if m[key] != g[key]:
                findings.append(f"{name}: {key} differ: model {m[key]} vs migration {g[key]}")
    revision = next(
        _lit(n.value)
        for n in _tree(ROOT / "migrations/versions/0001_initial.py").body
        if isinstance(n, ast.Assign) and n.targets[0].id == "revision"
    )
    expected = next(
        _lit(n.value)
        for n in _tree(SRC / "navigator/db.py").body
        if isinstance(n, ast.Assign) and n.targets[0].id == "EXPECTED_REVISION"
    )
    if revision != expected:
        findings.append(f"db.EXPECTED_REVISION={expected!r} but the migration revision is {revision!r}")
    return findings


def check_fstring_quotes(files: list[Path]) -> list[str]:
    """Python 3.11 cannot reuse the f-string's own (single-character) quote inside a replacement field."""
    findings = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.JoinedStr):
                continue
            segment = ast.get_source_segment(source, node) or ""
            body = segment.lstrip("fFrRbB")
            delimiter = body[:3] if body[:3] in {'"""', "'''"} else body[:1]
            if len(delimiter) != 1:
                continue
            for part in node.values:
                if isinstance(part, ast.FormattedValue) and delimiter in (
                    ast.get_source_segment(source, part.value) or ""
                ):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{part.lineno}: f-string reuses its own quote {delimiter} inside {{...}} (needs 3.12)"
                    )
    return findings


def check_ruff_defaults(files: list[Path]) -> list[str]:
    """The ruff rules this project selects (E4/E7/E9/F) that can be checked with the AST alone."""
    findings = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        rel = path.relative_to(ROOT)

        def noqa(lineno: int) -> bool:
            return "noqa" in lines[lineno - 1]

        # a format spec such as the :<5 in f"{x:<5}" is itself a JoinedStr without placeholders: not a finding
        format_specs = {
            id(n.format_spec) for n in ast.walk(tree) if isinstance(n, ast.FormattedValue) and n.format_spec is not None
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.JoinedStr)
                and id(node) not in format_specs
                and not any(isinstance(v, ast.FormattedValue) for v in node.values)
            ):
                if not noqa(node.lineno):
                    findings.append(f"{rel}:{node.lineno}: F541 f-string without placeholders")
            elif isinstance(node, ast.ExceptHandler) and node.type is None and not noqa(node.lineno):
                findings.append(f"{rel}:{node.lineno}: E722 bare except")
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda) and not noqa(node.lineno):
                findings.append(f"{rel}:{node.lineno}: E731 lambda assigned to a name")
            elif isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators, strict=True):
                    if (
                        isinstance(op, (ast.Eq, ast.NotEq))
                        and isinstance(right, ast.Constant)
                        and (right.value is None or right.value is True or right.value is False)
                        and not noqa(node.lineno)
                    ):
                        findings.append(f"{rel}:{node.lineno}: E711/E712 comparison to {right.value!r} with ==/!=")
            elif isinstance(node, (ast.Name, ast.arg)):
                name = node.id if isinstance(node, ast.Name) else node.arg
                stored = isinstance(node, ast.arg) or isinstance(node.ctx, ast.Store)
                if name in {"l", "O", "I"} and stored and not noqa(node.lineno):
                    findings.append(f"{rel}:{node.lineno}: E741 ambiguous variable name {name!r}")
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            declared = {n for g in ast.walk(fn) if isinstance(g, (ast.Global, ast.Nonlocal)) for n in g.names}
            loaded = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            class_attributes = {id(stmt) for c in ast.walk(fn) if isinstance(c, ast.ClassDef) for stmt in c.body}
            for stmt in ast.walk(fn):
                if id(stmt) in class_attributes:  # attributes of a class defined inside the function are not locals
                    continue
                targets = []
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    targets = [(stmt.targets[0].id, stmt.lineno)]
                elif isinstance(stmt, ast.ExceptHandler) and stmt.name:
                    targets = [(stmt.name, stmt.lineno)]
                for name, lineno in targets:
                    if name not in loaded and name not in declared and not name.startswith("_") and not noqa(lineno):
                        findings.append(f"{rel}:{lineno}: F841 local variable {name!r} is assigned but never used")
    return findings


def main() -> int:
    findings = (
        check_py311_fstrings(ALL_FILES)
        + check_unused_imports(ALL_FILES)
        + check_internal_imports(ALL_FILES)
        + check_undefined_names(ALL_FILES)
        + check_fstring_quotes(ALL_FILES)
        + check_ruff_defaults(ALL_FILES)
        + check_schema_sync()
    )
    for line in findings:
        print(line)
    print(f"{len(findings)} finding(s) in {len(ALL_FILES)} files")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
