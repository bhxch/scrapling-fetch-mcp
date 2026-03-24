"""Dynamic tool factory for parameter visibility control.

Builds tool functions with only enabled parameters based on feature configuration,
allowing MCP clients to control which parameters appear in tool schemas.
"""

from logging import getLogger
from typing import Any, Callable

logger = getLogger("scrapling_fetch_mcp")

# Python 类型到签名字符串的映射
_TYPE_MAP = {
    str: "str",
    int: "int",
    bool: "bool",
    float: "float",
}


def build_tool_function(
    tool_name: str,
    param_configs: dict[str, dict],
    enabled_features: set[str],
    base_docstring: str,
    impl_func: Callable,
) -> Callable:
    """
    Dynamically build a tool function with only enabled parameters.

    Args:
        tool_name: Name of the tool (e.g., "s_fetch_page")
        param_configs: Parameter metadata from TOOL_PARAMS
        enabled_features: Set of enabled feature names
        base_docstring: Base description with IMPORTANT sections
        impl_func: The actual implementation function (accepts all params)

    Returns:
        Async function with the correct signature and docstring
    """
    # 1. Filter to enabled params
    enabled_params = []
    for name, cfg in param_configs.items():
        if cfg["feature"] is None or cfg["feature"] in enabled_features:
            enabled_params.append(name)

    # 2. Sort: required params first, then optional params
    #    (Python requires positional params before keyword params)
    enabled_params.sort(key=lambda n: not param_configs[n]["required"])

    # 3. Build signature with TYPE ANNOTATIONS
    sig_parts = []
    for name in enabled_params:
        cfg = param_configs[name]
        type_str = _TYPE_MAP.get(cfg["type"], "str")
        if not cfg["required"]:
            sig_parts.append(f"{name}: {type_str} = {repr(cfg['default'])}")
        else:
            sig_parts.append(f"{name}: {type_str}")

    sig_str = ", ".join(sig_parts)

    # 3. Build call kwargs (pass enabled params directly, use defaults for disabled)
    call_kwargs = {}
    for name in enabled_params:
        call_kwargs[name] = name
    for name, cfg in param_configs.items():
        if name not in call_kwargs:
            call_kwargs[name] = repr(cfg["default"])
    call_str = ", ".join(f"{k}={v}" for k, v in call_kwargs.items())

    # 4. Build dynamic docstring (only include enabled params in Args)
    docstring = _build_docstring(base_docstring, enabled_params, param_configs)

    # 5. Build function via dynamic code generation with type-annotated signature
    source = f'''async def {tool_name}({sig_str}) -> str:
    """{docstring}"""
    return await _impl({call_str})'''

    namespace: dict[str, Any] = {"_impl": impl_func}
    # Note: Using Python built-in exec() for dynamic function creation.
    # All inputs come from code constants (TOOL_PARAMS), not from user input.
    # This is safe from code injection.
    exec(source, namespace)
    return namespace[tool_name]


def _build_docstring(
    base_docstring: str,
    enabled_params: list[str],
    param_configs: dict[str, dict],
) -> str:
    """
    Build a docstring that includes base description and only enabled parameter descriptions.

    The base_docstring contains IMPORTANT sections and feature guidance.
    The Args section is generated dynamically, only listing enabled parameters.

    Args:
        base_docstring: Multi-line base description with IMPORTANT sections.
                        Does NOT include Args section - that is generated here.
        enabled_params: List of parameter names that are currently enabled.
        param_configs: Parameter metadata for description lookup.

    Returns:
        Complete docstring for the dynamic function.
    """
    lines = [base_docstring, "", "Args:"]
    for name in enabled_params:
        cfg = param_configs[name]
        desc = cfg.get("description", "")
        lines.append(f"    {name}: {desc}")
    return "\n".join(lines)
