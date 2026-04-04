from __future__ import annotations


def render_labeled_counter(name: str, help_text: str, labels_values: dict[str, float]) -> str:
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} counter",
    ]
    for label, val in sorted(labels_values.items()):
        safe = label.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{name}{{action="{safe}"}} {val}')
    return "\n".join(lines) + "\n"


def render_gauge(name: str, help_text: str, value: float) -> str:
    return (
        f"# HELP {name} {help_text}\n"
        f"# TYPE {name} gauge\n"
        f"{name} {value}\n"
    )
