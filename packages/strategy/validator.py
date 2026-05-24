"""
Strategy source validator.

Validates user-authored strategy Python source code against a strict
contract before it is allowed into the database. Performs two layers:

  1. Static AST analysis: rejects forbidden imports, dangerous builtin
     calls, dunder access, and structural violations (must define
     exactly one Strategy subclass with a PARAMS_MODEL).
  2. Restricted exec: compiles and executes the validated source in a
     namespace with minimal builtins and a controlled __import__,
     then locates the Strategy subclass and extracts its params
     schema as JSON Schema.

This is the gatekeeper for user code. Every byte stored in
user_strategies.source_code MUST pass through validate_strategy_source.

Threat model:
  * Single-user trust today; multi-user when Step 30 lands.
  * Defense against: own typos, LLM hallucinations, accidental
    foot-guns. Defense against deliberate sandbox escapes is added
    in Step 30 (subprocess isolation + resource limits).
  * In-process exec is acceptable for now; do not loosen the
    allowlists below without explicit review.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Allowlists
# ============================================================

# Modules that user strategies are permitted to import.
# Any `import X` or `from X import ...` where X is not in this set
# (or doesn't start with one of these prefixes) fails validation.
ALLOWED_IMPORT_PREFIXES: tuple[str, ...] = (
    "packages.strategy",        # Strategy base, BarContext
    "pydantic",                 # params models
    "typing",                   # type hints
    "__future__",               # `from __future__ import annotations`
    "dataclasses",              # @dataclass for helper types
    "math",                     # safe stdlib math
    "enum",                     # Enum for typed choices
    "decimal",                  # precise arithmetic for finance code
)

# Builtins that user code is explicitly NOT allowed to call.
# Note: __import__ is replaced by a controlled version in the exec
# namespace (see safe_import below); the validator also rejects
# direct __import__(...) calls at the AST level.
FORBIDDEN_BUILTIN_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "help",
    "exit",
    "quit",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "memoryview",
})

# Dunder attribute names that user code is allowed to reference.
# (Class definitions need __init__, etc.; we don't block those.)
ALLOWED_DUNDERS: frozenset[str] = frozenset({
    "__init__",
    "__name__",
    "__class__",     # used by isinstance, typing
    "__module__",    # set automatically on class def
    "__qualname__",
    "__doc__",
    "__annotations__",
    "__dict__",      # used by Pydantic internally — narrow risk
    "__post_init__", # dataclasses
})


# ============================================================
# Result types
# ============================================================

@dataclass
class ValidationError:
    """A single validation failure with location + reason."""
    code: str
    message: str
    line: int | None = None
    col: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "col": self.col,
        }


@dataclass
class StrategyValidationResult:
    """Result of validating a strategy source string."""
    ok: bool
    errors: list[ValidationError] = field(default_factory=list)
    class_name: str | None = None
    params_class_name: str | None = None
    params_schema: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [e.as_dict() for e in self.errors],
            "class_name": self.class_name,
            "params_class_name": self.params_class_name,
            "params_schema": self.params_schema,
        }


# ============================================================
# Public API
# ============================================================

def validate_strategy_source(source: str) -> StrategyValidationResult:
    """
    Validate user strategy source code.

    Returns a StrategyValidationResult. If ok is True, the source is
    safe to persist and execute under the same restricted exec
    environment. The result also includes extracted metadata
    (class_name, params_schema) used to populate the DB row.

    If ok is False, errors contains structured failure reasons. The
    source MUST NOT be persisted.
    """
    result = StrategyValidationResult(ok=False)

    # --- 1. Parse ---
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result.errors.append(ValidationError(
            code="syntax_error",
            message=f"Python syntax error: {e.msg}",
            line=e.lineno,
            col=e.offset,
        ))
        return result

    # --- 2. Static AST analysis ---
    static_errors = _walk_ast(tree)
    if static_errors:
        result.errors.extend(static_errors)
        return result

    # --- 3. Structural check (find Strategy subclass + PARAMS_MODEL) ---
    structural_errors, class_name, params_class_name = _find_strategy_class(tree)
    if structural_errors:
        result.errors.extend(structural_errors)
        return result
    result.class_name = class_name
    result.params_class_name = params_class_name

    # --- 4. Restricted exec for params schema extraction ---
    schema, exec_errors = _extract_params_schema(source, class_name)
    if exec_errors:
        result.errors.extend(exec_errors)
        return result
    result.params_schema = schema

    result.ok = True
    return result


# ============================================================
# Phase 2: AST walk
# ============================================================

class _Visitor(ast.NodeVisitor):
    """AST visitor that collects ValidationErrors."""

    def __init__(self) -> None:
        self.errors: list[ValidationError] = []

    # ---- imports ----
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not _is_import_allowed(alias.name):
                self.errors.append(ValidationError(
                    code="forbidden_import",
                    message=(
                        f"Import of '{alias.name}' is not allowed. "
                        f"Permitted prefixes: {', '.join(ALLOWED_IMPORT_PREFIXES)}."
                    ),
                    line=node.lineno,
                    col=node.col_offset,
                ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            # `from . import x` — relative import, always rejected
            self.errors.append(ValidationError(
                code="forbidden_import",
                message="Relative imports are not allowed.",
                line=node.lineno,
                col=node.col_offset,
            ))
        elif not _is_import_allowed(node.module):
            self.errors.append(ValidationError(
                code="forbidden_import",
                message=(
                    f"Import from '{node.module}' is not allowed. "
                    f"Permitted prefixes: {', '.join(ALLOWED_IMPORT_PREFIXES)}."
                ),
                line=node.lineno,
                col=node.col_offset,
            ))
        self.generic_visit(node)

    # ---- calls ----
    def visit_Call(self, node: ast.Call) -> None:
        # Direct calls like exec(...) or __import__(...)
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTIN_CALLS:
            self.errors.append(ValidationError(
                code="forbidden_call",
                message=f"Call to '{node.func.id}' is not allowed.",
                line=node.lineno,
                col=node.col_offset,
            ))
        self.generic_visit(node)

    # ---- dunder attribute access ----
    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__") and attr not in ALLOWED_DUNDERS:
            self.errors.append(ValidationError(
                code="forbidden_dunder",
                message=f"Access to dunder attribute '{attr}' is not allowed.",
                line=node.lineno,
                col=node.col_offset,
            ))
        self.generic_visit(node)

    # ---- explicitly-banned statements ----
    def visit_Global(self, node: ast.Global) -> None:
        self.errors.append(ValidationError(
            code="forbidden_statement",
            message="'global' statements are not allowed.",
            line=node.lineno,
            col=node.col_offset,
        ))
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.errors.append(ValidationError(
            code="forbidden_statement",
            message="'nonlocal' statements are not allowed.",
            line=node.lineno,
            col=node.col_offset,
        ))
        self.generic_visit(node)


def _walk_ast(tree: ast.AST) -> list[ValidationError]:
    """Static AST analysis. Returns list of errors (empty if clean)."""
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.errors


def _is_import_allowed(module_name: str) -> bool:
    """True if `import {module_name}` is permitted."""
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in ALLOWED_IMPORT_PREFIXES
    )


# ============================================================
# Phase 3: Find the Strategy subclass + PARAMS_MODEL
# ============================================================

def _find_strategy_class(
    tree: ast.AST,
) -> tuple[list[ValidationError], str | None, str | None]:
    """
    Locate the Strategy subclass and its PARAMS_MODEL assignment.

    Returns (errors, strategy_class_name, params_class_name).
    """
    errors: list[ValidationError] = []
    strategy_classes: list[ast.ClassDef] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Look for `class Foo(Strategy):` or `class Foo(strategy.Strategy):`
            for base in node.bases:
                base_name = _base_name(base)
                if base_name == "Strategy" or (base_name and base_name.endswith(".Strategy")):
                    strategy_classes.append(node)
                    break

    if len(strategy_classes) == 0:
        errors.append(ValidationError(
            code="no_strategy_class",
            message=(
                "No class inheriting from Strategy found. The source must "
                "define exactly one Strategy subclass."
            ),
        ))
        return errors, None, None

    if len(strategy_classes) > 1:
        errors.append(ValidationError(
            code="multiple_strategy_classes",
            message=(
                f"Found {len(strategy_classes)} Strategy subclasses; expected "
                f"exactly one. Classes: {[c.name for c in strategy_classes]}"
            ),
        ))
        return errors, None, None

    strategy_cls = strategy_classes[0]
    params_class_name = _find_params_model(strategy_cls)

    if params_class_name is None:
        errors.append(ValidationError(
            code="no_params_model",
            message=(
                f"Class '{strategy_cls.name}' has no PARAMS_MODEL assignment. "
                f"Add `PARAMS_MODEL = <PydanticClassName>` at class level."
            ),
            line=strategy_cls.lineno,
        ))
        return errors, strategy_cls.name, None

    return [], strategy_cls.name, params_class_name


def _base_name(base: ast.expr) -> str | None:
    """Render `Strategy`, `pkg.Strategy`, or `Strategy[T]` from an AST base expression."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        parent = _base_name(base.value)
        if parent is None:
            return None
        return f"{parent}.{base.attr}"
    if isinstance(base, ast.Subscript):
        # Handle generics like `Strategy[T]` — extract the base name
        return _base_name(base.value)
    return None


def _find_params_model(cls: ast.ClassDef) -> str | None:
    """Find `PARAMS_MODEL = SomeClass` in a class body. Returns SomeClass name."""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "PARAMS_MODEL":
                    if isinstance(stmt.value, ast.Name):
                        return stmt.value.id
    return None


# ============================================================
# Phase 4: Restricted exec to extract params JSON Schema
# ============================================================

def safe_import(
    name: str,
    globals_dict: dict[str, Any] | None = None,
    locals_dict: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """A restricted __import__ that only allows allowlisted modules."""
    if level != 0:
        raise ImportError("Relative imports are not allowed in user strategies.")
    if not _is_import_allowed(name):
        raise ImportError(
            f"Import of '{name}' is not allowed in user strategies. "
            f"Permitted prefixes: {', '.join(ALLOWED_IMPORT_PREFIXES)}."
        )
    return builtins.__import__(name, globals_dict, locals_dict, fromlist, level)


def build_safe_builtins() -> dict[str, Any]:
    """Construct a minimal __builtins__ dict for restricted exec."""
    allowed_names = {
        # constructors / coercion
        "bool", "int", "float", "str", "bytes", "bytearray",
        "list", "tuple", "set", "frozenset", "dict",
        "complex", "object", "type",
        # iteration / functional
        "iter", "next", "range", "enumerate", "zip",
        "map", "filter", "sorted", "reversed",
        "all", "any", "sum", "min", "max", "abs", "round",
        "len", "divmod", "pow",
        # introspection (limited)
        "isinstance", "issubclass", "callable",
        # I/O — print only
        "print", "repr",
        # class machinery
        "super", "property", "staticmethod", "classmethod",
        "__build_class__", "__name__",
        # exception types
        "Exception", "BaseException", "ValueError", "TypeError",
        "KeyError", "AttributeError", "IndexError", "RuntimeError",
        "ArithmeticError", "ZeroDivisionError", "StopIteration",
        "NotImplementedError", "AssertionError",
        # constants
        "True", "False", "None",
        # NotImplemented sentinel (used by __eq__ et al)
        "NotImplemented",
    }
    safe = {name: getattr(builtins, name) for name in allowed_names}
    safe["__import__"] = safe_import
    return safe


def _extract_params_schema(
    source: str,
    class_name: str,
) -> tuple[dict[str, Any] | None, list[ValidationError]]:
    """
    Compile and execute source in a restricted environment, then call
    `{class_name}.PARAMS_MODEL.model_json_schema()` to extract the
    JSON Schema for the params class.

    Returns (schema, errors). Schema is None if errors are non-empty.
    """
    try:
        code_obj = compile(source, "<user_strategy>", "exec")
    except SyntaxError as e:
        return None, [ValidationError(
            code="syntax_error",
            message=f"Python syntax error: {e.msg}",
            line=e.lineno,
            col=e.offset,
        )]

    safe_namespace: dict[str, Any] = {"__builtins__": build_safe_builtins()}

    try:
        # Pass a single namespace so class bodies can resolve names that
        # were imported at module level. Using separate globals+locals
        # would put imports in locals, where class-body free variables
        # can't see them.
        exec(code_obj, safe_namespace)  # noqa: S102
    except ImportError as e:
        return None, [ValidationError(
            code="forbidden_import",
            message=str(e),
        )]
    except Exception as e:
        return None, [ValidationError(
            code="exec_failed",
            message=f"Failed to load strategy source: {type(e).__name__}: {e}",
        )]

    strategy_cls = safe_namespace.get(class_name)
    if strategy_cls is None:
        return None, [ValidationError(
            code="class_not_found",
            message=f"Strategy class '{class_name}' was not defined by the source.",
        )]

    params_model = getattr(strategy_cls, "PARAMS_MODEL", None)
    if params_model is None:
        return None, [ValidationError(
            code="no_params_model",
            message=f"Class '{class_name}' has no PARAMS_MODEL attribute.",
        )]

    if not hasattr(params_model, "model_json_schema"):
        return None, [ValidationError(
            code="invalid_params_model",
            message=(
                f"PARAMS_MODEL on '{class_name}' is not a Pydantic BaseModel "
                f"(missing model_json_schema). Inherit from pydantic.BaseModel."
            ),
        )]

    try:
        schema = params_model.model_json_schema()
    except Exception as e:
        return None, [ValidationError(
            code="schema_extraction_failed",
            message=f"Could not extract JSON schema: {type(e).__name__}: {e}",
        )]

    return schema, []
