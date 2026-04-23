from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_WRITE_SCAN_ROOTS = ("src", "ai_sdlc", "scripts")
RUNTIME_WRITE_ALLOWED_SURFACES = {
    "src/watchdog/validation/ai_sdlc_runtime_io.py",
}

_RUNTIME_LITERAL = "runtime.yaml"
_DIRECT_WRITE_METHODS = {"write_text", "write_bytes"}
_DIRECT_OPEN_NAMES = {"open"}
_DIRECT_WRITE_MODES = {"w", "a", "x"}
_LITERAL_ORIGIN = "<literal>"
_CallableTarget = tuple[str, bool]
_FUNCTOOLS_PARTIAL_WRAPPERS = {
    "partial": False,
    "partialmethod": True,
}


def validate_runtime_write_entrypoints(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for path in _iter_scan_files(root):
        relative_path = path.relative_to(root).as_posix()
        if relative_path in RUNTIME_WRITE_ALLOWED_SURFACES:
            continue

        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(
                f"runtime write entrypoint ({relative_path}): "
                f"unable to parse file for runtime write scan ({exc.msg})"
            )
            continue

        if _contains_unapproved_runtime_write(module):
            violations.append(
                f"runtime write entrypoint ({relative_path}): "
                "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
            )

    return violations


def _iter_scan_files(repo_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for base_name in RUNTIME_WRITE_SCAN_ROOTS:
        base_dir = repo_root / base_name
        if not base_dir.exists():
            continue
        files.extend(sorted(base_dir.rglob("*.py")))
    return tuple(files)


def _contains_unapproved_runtime_write(module: ast.Module) -> bool:
    partial_wrapper_names = _collect_partial_wrapper_names(module)
    functions = _collect_function_defs(module)
    signatures = {name: _parameter_names(node) for name, node in functions.items()}
    sink_parameters = _collect_sink_parameters(functions, signatures, partial_wrapper_names)
    callable_factories = _collect_callable_factories(
        functions,
        sink_parameters,
        signatures,
        partial_wrapper_names,
    )

    _, _, _, module_sinks = _scan_block(
        module.body,
        {},
        {},
        {},
        sink_parameters,
        callable_factories,
        signatures,
        partial_wrapper_names,
    )
    if _LITERAL_ORIGIN in module_sinks:
        return True

    for function in functions.values():
        _, _, _, function_sinks = _scan_block(
            function.body,
            {},
            {},
            {},
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        if _LITERAL_ORIGIN in function_sinks:
            return True

    for class_node in (node for node in ast.walk(module) if isinstance(node, ast.ClassDef)):
        _, _, class_wrapper_aliases, _ = _scan_block(
            class_node.body,
            {},
            {},
            {},
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        if not class_wrapper_aliases:
            continue
        for statement in class_node.body:
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _, _, _, method_sinks = _scan_block(
                statement.body,
                {},
                {},
                class_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            if _LITERAL_ORIGIN in method_sinks:
                return True

    return False


def _collect_partial_wrapper_names(module: ast.Module) -> dict[str, bool]:
    wrapper_names = dict(_FUNCTOOLS_PARTIAL_WRAPPERS)
    for node in ast.walk(module):
        if not isinstance(node, ast.ImportFrom) or node.module != "functools":
            continue
        for alias in node.names:
            if alias.name in _FUNCTOOLS_PARTIAL_WRAPPERS:
                wrapper_names[alias.asname or alias.name] = _FUNCTOOLS_PARTIAL_WRAPPERS[alias.name]
    return wrapper_names


def _collect_function_defs(module: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
    return functions


def _parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    return tuple(
        arg.arg
        for arg in function.args.posonlyargs + function.args.args + function.args.kwonlyargs
    )


def _collect_sink_parameters(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> dict[str, frozenset[str]]:
    sinks = {name: frozenset() for name in functions}

    changed = True
    while changed:
        changed = False
        for name, function in functions.items():
            env = {param_name: {param_name} for param_name in signatures[name]}
            _, _, _, sink_origins = _scan_block(
                function.body,
                env,
                {},
                {},
                sinks,
                {},
                signatures,
                partial_wrapper_names,
            )
            next_sinks = frozenset(origin for origin in sink_origins if origin in env)
            if next_sinks != sinks[name]:
                sinks[name] = next_sinks
                changed = True

    return sinks


def _collect_callable_factories(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    sink_parameters: dict[str, frozenset[str]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> dict[str, frozenset[_CallableTarget]]:
    factories = {name: frozenset() for name in functions}

    changed = True
    while changed:
        changed = False
        for name, function in functions.items():
            _, returned_targets = _scan_callable_returns(
                function.body,
                {},
                sink_parameters,
                factories,
                signatures,
                partial_wrapper_names,
            )
            next_targets = frozenset(target for target in returned_targets if target[0] != "write_yaml_atomic")
            if next_targets != factories[name]:
                factories[name] = next_targets
                changed = True

    return factories


def _scan_block(
    statements: list[ast.stmt],
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> tuple[dict[str, set[str]], dict[str, set[_CallableTarget]], dict[str, bool], set[str]]:
    active_env = _copy_env(env)
    active_callable_aliases = _copy_callable_aliases(callable_aliases)
    active_wrapper_aliases = _copy_wrapper_aliases(wrapper_aliases)
    sink_origins: set[str] = set()
    deferred_scopes: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    violation = False

    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            deferred_scopes.append(statement)
        (
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            statement_sinks,
            statement_violation,
        ) = _scan_statement(
            statement,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(statement_sinks)
        violation = violation or statement_violation

    if deferred_scopes and (active_env or active_callable_aliases or active_wrapper_aliases):
        for deferred_statement in deferred_scopes:
            _, _, _, rescanned_sinks, rescanned_violation = _scan_statement(
                deferred_statement,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(rescanned_sinks)
            violation = violation or rescanned_violation

    if violation:
        sink_origins.add(_LITERAL_ORIGIN)
    return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins


def _scan_statement(
    statement: ast.stmt,
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> tuple[dict[str, set[str]], dict[str, set[_CallableTarget]], dict[str, bool], set[str], bool]:
    active_env = _copy_env(env)
    active_callable_aliases = _copy_callable_aliases(callable_aliases)
    active_wrapper_aliases = _copy_wrapper_aliases(wrapper_aliases)
    sink_origins: set[str] = set()
    violation = False

    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        sink_origins, violation = _scan_expressions(
            _function_definition_expressions(statement),
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        if active_env or active_callable_aliases or active_wrapper_aliases:
            _, _, _, function_sinks = _scan_block(
                statement.body,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(function_sinks)
            violation = violation or _LITERAL_ORIGIN in function_sinks
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, violation

    if isinstance(statement, ast.ClassDef):
        header_sinks, header_violation = _scan_expressions(
            _class_definition_expressions(statement),
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(header_sinks)
        _, _, _, class_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(class_sinks)
        return (
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_origins,
            header_violation or _LITERAL_ORIGIN in class_sinks,
        )

    if isinstance(statement, ast.Assign):
        expr_sinks, expr_violation = _scan_expression(
            statement.value,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        violation = violation or expr_violation
        assigned_origins = _runtime_origins(statement.value, active_env)
        callable_targets = _callable_targets(
            statement.value,
            sink_parameters,
            active_callable_aliases,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        for target in statement.targets:
            _apply_assignment(target, assigned_origins, active_env)
            _apply_callable_assignment(target, callable_targets, active_callable_aliases)
            _apply_wrapper_assignment(
                target,
                _wrapper_binding(statement.value, active_wrapper_aliases, partial_wrapper_names),
                active_wrapper_aliases,
            )
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, violation

    if isinstance(statement, ast.AnnAssign):
        annotation_sinks, annotation_violation = _scan_expressions(
            [statement.annotation],
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(annotation_sinks)
        violation = violation or annotation_violation
        if statement.value is not None:
            expr_sinks, expr_violation = _scan_expression(
                statement.value,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(expr_sinks)
            violation = violation or expr_violation
            _apply_assignment(statement.target, _runtime_origins(statement.value, active_env), active_env)
            _apply_callable_assignment(
                statement.target,
                _callable_targets(
                    statement.value,
                    sink_parameters,
                    active_callable_aliases,
                    callable_factories,
                    signatures,
                    partial_wrapper_names,
                ),
                active_callable_aliases,
            )
            _apply_wrapper_assignment(
                statement.target,
                _wrapper_binding(statement.value, active_wrapper_aliases, partial_wrapper_names),
                active_wrapper_aliases,
            )
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, violation

    if isinstance(statement, ast.AugAssign):
        expr_sinks, expr_violation = _scan_expression(
            statement.value,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        violation = violation or expr_violation
        _apply_assignment(statement.target, set(), active_env)
        _apply_callable_assignment(statement.target, set(), active_callable_aliases)
        _apply_wrapper_assignment(statement.target, None, active_wrapper_aliases)
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, violation

    if isinstance(statement, ast.If):
        test_sinks, test_violation = _scan_expression(
            statement.test,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(test_sinks)
        violation = violation or test_violation

        guard_name = _runtime_exclusion_guard(statement)
        body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(body_sinks)
        body_violation = _LITERAL_ORIGIN in body_sinks

        orelse_env = _copy_env(active_env)
        orelse_aliases = _copy_callable_aliases(active_callable_aliases)
        orelse_wrapper_aliases = _copy_wrapper_aliases(active_wrapper_aliases)
        orelse_sinks: set[str] = set()
        orelse_violation = False
        if statement.orelse:
            orelse_env, orelse_aliases, orelse_wrapper_aliases, orelse_sinks = _scan_block(
                statement.orelse,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(orelse_sinks)
            orelse_violation = _LITERAL_ORIGIN in orelse_sinks

        fallthrough_envs: list[dict[str, set[str]]] = []
        fallthrough_aliases: list[dict[str, set[_CallableTarget]]] = []
        fallthrough_wrapper_aliases: list[dict[str, bool]] = []
        if _block_falls_through(statement.body):
            fallthrough_envs.append(body_env)
            fallthrough_aliases.append(body_aliases)
            fallthrough_wrapper_aliases.append(body_wrapper_aliases)
        if statement.orelse:
            if _block_falls_through(statement.orelse):
                fallthrough_envs.append(orelse_env)
                fallthrough_aliases.append(orelse_aliases)
                fallthrough_wrapper_aliases.append(orelse_wrapper_aliases)
        else:
            next_env = _copy_env(active_env)
            next_aliases = _copy_callable_aliases(active_callable_aliases)
            next_wrapper_aliases = _copy_wrapper_aliases(active_wrapper_aliases)
            if guard_name is not None:
                next_env.pop(guard_name, None)
            fallthrough_envs.append(next_env)
            fallthrough_aliases.append(next_aliases)
            fallthrough_wrapper_aliases.append(next_wrapper_aliases)

        merged_env = _merge_envs(fallthrough_envs)
        merged_aliases = _merge_callable_aliases(fallthrough_aliases)
        merged_wrapper_aliases = _merge_wrapper_aliases(fallthrough_wrapper_aliases)
        violation = violation or body_violation or orelse_violation
        return merged_env, merged_aliases, merged_wrapper_aliases, sink_origins, violation

    if isinstance(statement, (ast.For, ast.AsyncFor)):
        iter_sinks, iter_violation = _scan_expression(
            statement.iter,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(iter_sinks)
        violation = violation or iter_violation
        body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(body_sinks)
        orelse_env, orelse_aliases, orelse_wrapper_aliases, orelse_sinks = _scan_block(
            statement.orelse,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(orelse_sinks)
        return (
            _merge_envs((active_env, body_env, orelse_env)),
            _merge_callable_aliases((active_callable_aliases, body_aliases, orelse_aliases)),
            _merge_wrapper_aliases((active_wrapper_aliases, body_wrapper_aliases, orelse_wrapper_aliases)),
            sink_origins,
            violation or _LITERAL_ORIGIN in body_sinks or _LITERAL_ORIGIN in orelse_sinks,
        )

    if isinstance(statement, ast.While):
        test_sinks, test_violation = _scan_expression(
            statement.test,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(test_sinks)
        violation = violation or test_violation
        body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(body_sinks)
        orelse_env, orelse_aliases, orelse_wrapper_aliases, orelse_sinks = _scan_block(
            statement.orelse,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(orelse_sinks)
        return (
            _merge_envs((active_env, body_env, orelse_env)),
            _merge_callable_aliases((active_callable_aliases, body_aliases, orelse_aliases)),
            _merge_wrapper_aliases((active_wrapper_aliases, body_wrapper_aliases, orelse_wrapper_aliases)),
            sink_origins,
            violation or _LITERAL_ORIGIN in body_sinks or _LITERAL_ORIGIN in orelse_sinks,
        )

    if isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            item_sinks, item_violation = _scan_expression(
                item.context_expr,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(item_sinks)
            violation = violation or item_violation
        body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(body_sinks)
        return (
            _merge_envs((active_env, body_env)),
            _merge_callable_aliases((active_callable_aliases, body_aliases)),
            _merge_wrapper_aliases((active_wrapper_aliases, body_wrapper_aliases)),
            sink_origins,
            violation or _LITERAL_ORIGIN in body_sinks,
        )

    if isinstance(statement, (ast.Try, ast.TryStar)):
        body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
            statement.body,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(body_sinks)
        final_envs = [body_env]
        final_aliases = [body_aliases]
        final_wrapper_aliases = [body_wrapper_aliases]
        for handler in statement.handlers:
            handler_type_sinks, _ = _scan_expressions(
                [handler.type],
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(handler_type_sinks)
            handler_env, handler_aliases, handler_wrapper_aliases, handler_sinks = _scan_block(
                handler.body,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(handler_sinks)
            final_envs.append(handler_env)
            final_aliases.append(handler_aliases)
            final_wrapper_aliases.append(handler_wrapper_aliases)
        if statement.orelse:
            orelse_env, orelse_aliases, orelse_wrapper_aliases, orelse_sinks = _scan_block(
                statement.orelse,
                body_env,
                body_aliases,
                body_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(orelse_sinks)
            final_envs.append(orelse_env)
            final_aliases.append(orelse_aliases)
            final_wrapper_aliases.append(orelse_wrapper_aliases)
        if statement.finalbody:
            final_env, final_callable_aliases, final_wrapper_aliases_merged, final_sinks = _scan_block(
                statement.finalbody,
                _merge_envs(final_envs),
                _merge_callable_aliases(final_aliases),
                _merge_wrapper_aliases(final_wrapper_aliases),
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(final_sinks)
            final_envs = [final_env]
            final_aliases = [final_callable_aliases]
            final_wrapper_aliases = [final_wrapper_aliases_merged]
        return (
            _merge_envs(final_envs),
            _merge_callable_aliases(final_aliases),
            _merge_wrapper_aliases(final_wrapper_aliases),
            sink_origins,
            _LITERAL_ORIGIN in sink_origins,
        )

    if isinstance(statement, ast.Assert):
        expr_sinks, expr_violation = _scan_expression(
            statement.test,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        violation = violation or expr_violation
        if statement.msg is not None:
            msg_sinks, msg_violation = _scan_expression(
                statement.msg,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(msg_sinks)
            violation = violation or msg_violation
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, violation

    if isinstance(statement, ast.Match):
        subject_sinks, subject_violation = _scan_expression(
            statement.subject,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(subject_sinks)
        violation = violation or subject_violation

        case_envs = [active_env]
        case_aliases = [active_callable_aliases]
        case_wrapper_aliases = [active_wrapper_aliases]
        for case in statement.cases:
            pattern_sinks, pattern_violation = _scan_expressions(
                _match_case_expressions(case),
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(pattern_sinks)
            violation = violation or pattern_violation

            body_env, body_aliases, body_wrapper_aliases, body_sinks = _scan_block(
                case.body,
                active_env,
                active_callable_aliases,
                active_wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            sink_origins.update(body_sinks)
            violation = violation or _LITERAL_ORIGIN in body_sinks

            if _block_falls_through(case.body):
                case_envs.append(body_env)
                case_aliases.append(body_aliases)
                case_wrapper_aliases.append(body_wrapper_aliases)

        return (
            _merge_envs(case_envs),
            _merge_callable_aliases(case_aliases),
            _merge_wrapper_aliases(case_wrapper_aliases),
            sink_origins,
            violation,
        )

    if isinstance(statement, ast.Return):
        if statement.value is None:
            return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, False
        expr_sinks, expr_violation = _scan_expression(
            statement.value,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, expr_violation

    if isinstance(statement, ast.Expr):
        expr_sinks, expr_violation = _scan_expression(
            statement.value,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, expr_violation

    if isinstance(statement, ast.Raise):
        if statement.exc is None:
            return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, False
        expr_sinks, expr_violation = _scan_expression(
            statement.exc,
            active_env,
            active_callable_aliases,
            active_wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, expr_violation

    return active_env, active_callable_aliases, active_wrapper_aliases, sink_origins, False


def _scan_expression(
    expression: ast.AST,
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> tuple[set[str], bool]:
    sink_origins: set[str] = set()
    for node in ast.walk(expression):
        if not isinstance(node, ast.Call):
            continue
        sink_origins.update(
            _call_sink_origins(
                node,
                env,
                callable_aliases,
                wrapper_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
        )

    return sink_origins, any(origin == _LITERAL_ORIGIN for origin in sink_origins)


def _scan_expressions(
    expressions: list[ast.AST | None] | tuple[ast.AST | None, ...],
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> tuple[set[str], bool]:
    sink_origins: set[str] = set()
    violation = False
    for expression in expressions:
        if expression is None:
            continue
        expr_sinks, expr_violation = _scan_expression(
            expression,
            env,
            callable_aliases,
            wrapper_aliases,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_origins.update(expr_sinks)
        violation = violation or expr_violation
    return sink_origins, violation


def _call_sink_origins(
    call: ast.Call,
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> set[str]:
    partial_origins = _partial_wrapper_origins(
        call,
        env,
        callable_aliases,
        wrapper_aliases,
        sink_parameters,
        callable_factories,
        signatures,
        partial_wrapper_names,
    )
    if partial_origins:
        return partial_origins

    direct_origins = _direct_write_call_origins(call, env)
    if direct_origins:
        return direct_origins

    callable_targets = _callable_targets(
        call.func,
        sink_parameters,
        callable_aliases,
        callable_factories,
        signatures,
        partial_wrapper_names,
    )

    if not callable_targets:
        return set()

    call_origins: set[str] = set()
    positional_args = list(call.args)
    keyword_args = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }
    for function_name, bound_method_call in callable_targets:
        if function_name == "write_yaml_atomic" or function_name not in sink_parameters:
            continue
        parameter_names = signatures.get(function_name, ())
        resolved_parameter_names = parameter_names
        if bound_method_call and parameter_names[:1] and parameter_names[0] in {"self", "cls"}:
            resolved_parameter_names = parameter_names[1:]
        for parameter_name in sink_parameters[function_name]:
            if parameter_name not in resolved_parameter_names:
                continue
            parameter_index = resolved_parameter_names.index(parameter_name)
            if parameter_index < len(positional_args):
                call_origins.update(_runtime_origins(positional_args[parameter_index], env))
                continue
            if parameter_name in keyword_args:
                call_origins.update(_runtime_origins(keyword_args[parameter_name], env))

    return call_origins


def _partial_wrapper_origins(
    call: ast.Call,
    env: dict[str, set[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    wrapper_aliases: dict[str, bool],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> set[str]:
    binds_method_receiver = _wrapper_binding(call.func, wrapper_aliases, partial_wrapper_names)
    if binds_method_receiver is None or not call.args:
        return set()

    callable_targets = _callable_targets(
        call.args[0],
        sink_parameters,
        callable_aliases,
        callable_factories,
        signatures,
        partial_wrapper_names,
    )
    if not callable_targets:
        return set()

    bound_args = list(call.args[1:])
    bound_keywords = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }
    partial_origins: set[str] = set()
    for target_name, bound_method_call in callable_targets:
        if target_name not in sink_parameters:
            continue
        parameter_names = signatures.get(target_name, ())
        resolved_parameter_names = parameter_names
        if (bound_method_call or binds_method_receiver) and parameter_names[:1] and parameter_names[0] in {"self", "cls"}:
            resolved_parameter_names = parameter_names[1:]
        for parameter_name in sink_parameters[target_name]:
            if parameter_name not in resolved_parameter_names:
                continue
            parameter_index = resolved_parameter_names.index(parameter_name)
            if parameter_index < len(bound_args):
                partial_origins.update(_runtime_origins(bound_args[parameter_index], env))
                continue
            if parameter_name in bound_keywords:
                partial_origins.update(_runtime_origins(bound_keywords[parameter_name], env))

    return partial_origins


def _direct_write_call_origins(call: ast.Call, env: dict[str, set[str]]) -> set[str]:
    if isinstance(call.func, ast.Attribute):
        if call.func.attr in _DIRECT_WRITE_METHODS:
            return _runtime_origins(call.func.value, env)
        if call.func.attr == "open" and _has_write_mode(call.args, call.keywords, mode_index=0):
            return _runtime_origins(call.func.value, env)

    if isinstance(call.func, ast.Name) and call.func.id in _DIRECT_OPEN_NAMES:
        if not _has_write_mode(call.args, call.keywords, mode_index=1):
            return set()
        if not call.args:
            return set()
        return _runtime_origins(call.args[0], env)

    return set()


def _function_definition_expressions(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST | None]:
    expressions: list[ast.AST | None] = []
    expressions.extend(statement.decorator_list)
    expressions.append(statement.returns)
    expressions.extend(statement.args.defaults)
    expressions.extend(statement.args.kw_defaults)
    for argument in (
        statement.args.posonlyargs
        + statement.args.args
        + statement.args.kwonlyargs
    ):
        expressions.append(argument.annotation)
    if statement.args.vararg is not None:
        expressions.append(statement.args.vararg.annotation)
    if statement.args.kwarg is not None:
        expressions.append(statement.args.kwarg.annotation)
    return expressions


def _class_definition_expressions(statement: ast.ClassDef) -> list[ast.AST | None]:
    expressions: list[ast.AST | None] = []
    expressions.extend(statement.decorator_list)
    expressions.extend(statement.bases)
    expressions.extend(keyword.value for keyword in statement.keywords)
    return expressions


def _match_case_expressions(case: ast.match_case) -> list[ast.AST | None]:
    expressions: list[ast.AST | None] = []
    expressions.append(case.guard)
    for node in ast.walk(case.pattern):
        if isinstance(node, ast.expr):
            expressions.append(node)
    return expressions


def _self_or_cls_attribute_name(expression: ast.AST | None) -> str | None:
    if not isinstance(expression, ast.Attribute):
        return None
    if not isinstance(expression.value, ast.Name):
        return None
    if expression.value.id not in {"self", "cls"}:
        return None
    return expression.attr


def _has_write_mode(args: list[ast.expr], keywords: list[ast.keyword], mode_index: int) -> bool:
    mode_expr: ast.expr | None = None
    if len(args) > mode_index:
        mode_expr = args[mode_index]
    else:
        for keyword in keywords:
            if keyword.arg == "mode":
                mode_expr = keyword.value
                break
    if mode_expr is None or not isinstance(mode_expr, ast.Constant) or not isinstance(mode_expr.value, str):
        return False
    return any(mode in mode_expr.value for mode in _DIRECT_WRITE_MODES)


def _runtime_origins(expression: ast.AST | None, env: dict[str, set[str]]) -> set[str]:
    if expression is None:
        return set()

    if isinstance(expression, ast.Name):
        return set(env.get(expression.id, set()))

    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return {_LITERAL_ORIGIN} if _RUNTIME_LITERAL in expression.value else set()

    if isinstance(expression, ast.JoinedStr):
        origins: set[str] = set()
        for value in expression.values:
            origins.update(_runtime_origins(value, env))
        return origins

    if isinstance(expression, ast.FormattedValue):
        return _runtime_origins(expression.value, env)

    if isinstance(expression, ast.BinOp):
        return _runtime_origins(expression.left, env) | _runtime_origins(expression.right, env)

    if isinstance(expression, ast.Call):
        origins: set[str] = set()
        origins.update(_runtime_origins(expression.func, env))
        for argument in expression.args:
            origins.update(_runtime_origins(argument, env))
        for keyword in expression.keywords:
            origins.update(_runtime_origins(keyword.value, env))
        return origins

    if isinstance(expression, ast.Attribute):
        return _runtime_origins(expression.value, env)

    if isinstance(expression, ast.Subscript):
        return _runtime_origins(expression.value, env) | _runtime_origins(expression.slice, env)

    if isinstance(expression, (ast.List, ast.Tuple, ast.Set)):
        origins: set[str] = set()
        for element in expression.elts:
            origins.update(_runtime_origins(element, env))
        return origins

    if isinstance(expression, ast.Dict):
        origins: set[str] = set()
        for key in expression.keys:
            origins.update(_runtime_origins(key, env))
        for value in expression.values:
            origins.update(_runtime_origins(value, env))
        return origins

    return set()


def _apply_assignment(target: ast.expr, origins: set[str], env: dict[str, set[str]]) -> None:
    if isinstance(target, ast.Name):
        if origins:
            env[target.id] = set(origins)
        else:
            env.pop(target.id, None)
        return

    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _apply_assignment(element, origins, env)


def _apply_callable_assignment(
    target: ast.expr,
    callable_targets: set[_CallableTarget],
    callable_aliases: dict[str, set[_CallableTarget]],
) -> None:
    if isinstance(target, ast.Name):
        if callable_targets:
            callable_aliases[target.id] = set(callable_targets)
        else:
            callable_aliases.pop(target.id, None)
        return

    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _apply_callable_assignment(element, callable_targets, callable_aliases)


def _wrapper_binding(
    expression: ast.AST | None,
    wrapper_aliases: dict[str, bool],
    partial_wrapper_names: dict[str, bool],
) -> bool | None:
    if expression is None:
        return None

    if isinstance(expression, ast.Name):
        if expression.id in wrapper_aliases:
            return wrapper_aliases[expression.id]
        return partial_wrapper_names.get(expression.id)

    if isinstance(expression, ast.Attribute):
        attribute_name = _self_or_cls_attribute_name(expression)
        if attribute_name is not None and attribute_name in wrapper_aliases:
            return wrapper_aliases[attribute_name]
        return partial_wrapper_names.get(expression.attr)

    return None


def _apply_wrapper_assignment(
    target: ast.expr,
    wrapper_binding: bool | None,
    wrapper_aliases: dict[str, bool],
) -> None:
    if isinstance(target, ast.Name):
        if wrapper_binding is None:
            wrapper_aliases.pop(target.id, None)
        else:
            wrapper_aliases[target.id] = wrapper_binding
        return

    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _apply_wrapper_assignment(element, wrapper_binding, wrapper_aliases)


def _callable_targets(
    expression: ast.AST | None,
    sink_parameters: dict[str, frozenset[str]],
    callable_aliases: dict[str, set[_CallableTarget]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> set[_CallableTarget]:
    if expression is None:
        return set()

    if isinstance(expression, ast.Name):
        targets = set(callable_aliases.get(expression.id, set()))
        if expression.id in sink_parameters:
            targets.add((expression.id, False))
        targets.update(callable_factories.get(expression.id, ()))
        return targets

    if isinstance(expression, ast.Attribute):
        if expression.attr in sink_parameters:
            return {(expression.attr, True)}
        return set(callable_factories.get(expression.attr, ()))

    if isinstance(expression, ast.Call):
        return _callable_targets(
            expression.func,
            sink_parameters,
            callable_aliases,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )

    if isinstance(expression, ast.Lambda):
        return _lambda_callable_targets(
            expression,
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )

    return set()


def _scan_callable_returns(
    statements: list[ast.stmt],
    callable_aliases: dict[str, set[_CallableTarget]],
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> tuple[dict[str, set[_CallableTarget]], set[_CallableTarget]]:
    active_aliases = _copy_callable_aliases(callable_aliases)
    returned_targets: set[_CallableTarget] = set()

    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        if isinstance(statement, ast.Assign):
            targets = _callable_targets(
                statement.value,
                sink_parameters,
                active_aliases,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            for target in statement.targets:
                _apply_callable_assignment(target, targets, active_aliases)
            continue

        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                _apply_callable_assignment(
                    statement.target,
                    _callable_targets(
                        statement.value,
                        sink_parameters,
                        active_aliases,
                        callable_factories,
                        signatures,
                        partial_wrapper_names,
                    ),
                    active_aliases,
                )
            continue

        if isinstance(statement, ast.AugAssign):
            _apply_callable_assignment(statement.target, set(), active_aliases)
            continue

        if isinstance(statement, ast.If):
            body_aliases, body_returns = _scan_callable_returns(
                statement.body,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            orelse_aliases, orelse_returns = _scan_callable_returns(
                statement.orelse,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            active_aliases = _merge_callable_aliases((active_aliases, body_aliases, orelse_aliases))
            returned_targets.update(body_returns)
            returned_targets.update(orelse_returns)
            continue

        if isinstance(statement, (ast.For, ast.AsyncFor)):
            body_aliases, body_returns = _scan_callable_returns(
                statement.body,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            orelse_aliases, orelse_returns = _scan_callable_returns(
                statement.orelse,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            active_aliases = _merge_callable_aliases((active_aliases, body_aliases, orelse_aliases))
            returned_targets.update(body_returns)
            returned_targets.update(orelse_returns)
            continue

        if isinstance(statement, ast.With):
            body_aliases, body_returns = _scan_callable_returns(
                statement.body,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            active_aliases = _merge_callable_aliases((active_aliases, body_aliases))
            returned_targets.update(body_returns)
            continue

        if isinstance(statement, ast.Try):
            body_aliases, body_returns = _scan_callable_returns(
                statement.body,
                active_aliases,
                sink_parameters,
                callable_factories,
                signatures,
                partial_wrapper_names,
            )
            returned_targets.update(body_returns)
            branch_aliases = [body_aliases]
            for handler in statement.handlers:
                handler_aliases, handler_returns = _scan_callable_returns(
                    handler.body,
                    active_aliases,
                    sink_parameters,
                    callable_factories,
                    signatures,
                    partial_wrapper_names,
                )
                branch_aliases.append(handler_aliases)
                returned_targets.update(handler_returns)
            if statement.orelse:
                orelse_aliases, orelse_returns = _scan_callable_returns(
                    statement.orelse,
                    body_aliases,
                    sink_parameters,
                    callable_factories,
                    signatures,
                    partial_wrapper_names,
                )
                branch_aliases.append(orelse_aliases)
                returned_targets.update(orelse_returns)
            active_aliases = _merge_callable_aliases([active_aliases, *branch_aliases])
            if statement.finalbody:
                final_aliases, final_returns = _scan_callable_returns(
                    statement.finalbody,
                    active_aliases,
                    sink_parameters,
                    callable_factories,
                    signatures,
                    partial_wrapper_names,
                )
                active_aliases = final_aliases
                returned_targets.update(final_returns)
            continue

        if isinstance(statement, ast.Return) and statement.value is not None:
            returned_targets.update(
                _callable_targets(
                    statement.value,
                    sink_parameters,
                    active_aliases,
                    callable_factories,
                    signatures,
                    partial_wrapper_names,
                )
            )

    return active_aliases, returned_targets


def _lambda_callable_targets(
    expression: ast.Lambda,
    sink_parameters: dict[str, frozenset[str]],
    callable_factories: dict[str, frozenset[_CallableTarget]],
    signatures: dict[str, tuple[str, ...]],
    partial_wrapper_names: dict[str, bool],
) -> set[_CallableTarget]:
    lambda_name = f"<lambda:{expression.lineno}:{expression.col_offset}>"
    if lambda_name not in signatures:
        signatures[lambda_name] = tuple(
            arg.arg
            for arg in expression.args.posonlyargs
            + expression.args.args
            + expression.args.kwonlyargs
        )

    if lambda_name not in sink_parameters:
        lambda_env = {param_name: {param_name} for param_name in signatures[lambda_name]}
        lambda_sinks, _ = _scan_expression(
            expression.body,
            lambda_env,
            {},
            {},
            sink_parameters,
            callable_factories,
            signatures,
            partial_wrapper_names,
        )
        sink_parameters[lambda_name] = frozenset(
            origin for origin in lambda_sinks if origin in lambda_env
        )

    if not sink_parameters[lambda_name]:
        return set()

    return {(lambda_name, False)}


def _runtime_exclusion_guard(statement: ast.If) -> str | None:
    if not _block_definitely_exits(statement.body):
        return None

    comparisons = (statement.test,) if isinstance(statement.test, ast.Compare) else ()
    for comparison in comparisons:
        if len(comparison.ops) != 1 or len(comparison.comparators) != 1:
            continue
        if not isinstance(comparison.ops[0], ast.Eq):
            continue
        left_name = _runtime_name_attr(comparison.left)
        right_name = _runtime_name_attr(comparison.comparators[0])
        if left_name is not None and _is_runtime_name_literal(comparison.comparators[0]):
            return left_name
        if right_name is not None and _is_runtime_name_literal(comparison.left):
            return right_name

    return None


def _runtime_name_attr(expression: ast.AST) -> str | None:
    if not isinstance(expression, ast.Attribute):
        return None
    if expression.attr != "name":
        return None
    if not isinstance(expression.value, ast.Name):
        return None
    return expression.value.id


def _is_runtime_name_literal(expression: ast.AST) -> bool:
    return isinstance(expression, ast.Constant) and expression.value == _RUNTIME_LITERAL


def _block_definitely_exits(statements: list[ast.stmt]) -> bool:
    if not statements:
        return False

    last = statements[-1]
    if isinstance(last, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(last, ast.If):
        return _block_definitely_exits(last.body) and _block_definitely_exits(last.orelse)
    if isinstance(last, ast.Try):
        branches = [last.body, *(handler.body for handler in last.handlers)]
        if last.orelse:
            branches.append(last.orelse)
        return all(_block_definitely_exits(branch) for branch in branches if branch)
    return False


def _block_falls_through(statements: list[ast.stmt]) -> bool:
    return not _block_definitely_exits(statements)


def _copy_env(env: dict[str, set[str]]) -> dict[str, set[str]]:
    return {name: set(origins) for name, origins in env.items()}


def _copy_callable_aliases(
    callable_aliases: dict[str, set[_CallableTarget]],
) -> dict[str, set[_CallableTarget]]:
    return {name: set(targets) for name, targets in callable_aliases.items()}


def _copy_wrapper_aliases(wrapper_aliases: dict[str, bool]) -> dict[str, bool]:
    return dict(wrapper_aliases)


def _merge_envs(envs: tuple[dict[str, set[str]], ...] | list[dict[str, set[str]]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for env in envs:
        for name, origins in env.items():
            merged.setdefault(name, set()).update(origins)
    return merged


def _merge_callable_aliases(
    aliases_list: tuple[dict[str, set[_CallableTarget]], ...]
    | list[dict[str, set[_CallableTarget]]]
) -> dict[str, set[_CallableTarget]]:
    merged: dict[str, set[_CallableTarget]] = {}
    for callable_aliases in aliases_list:
        for name, targets in callable_aliases.items():
            merged.setdefault(name, set()).update(targets)
    return merged


def _merge_wrapper_aliases(
    aliases_list: tuple[dict[str, bool], ...] | list[dict[str, bool]]
) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for wrapper_aliases in aliases_list:
        for name, binds_method_receiver in wrapper_aliases.items():
            merged[name] = merged.get(name, False) or binds_method_receiver
    return merged
