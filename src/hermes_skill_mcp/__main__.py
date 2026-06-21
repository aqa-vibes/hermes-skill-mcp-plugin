"""CLI entry point: hermes-skill-mcp install."""

import shutil
import sys
from pathlib import Path


def main() -> None:  # noqa: WPS213
    """Install the plugin into ~/.hermes/plugins/skill-mcp/."""
    if len(sys.argv) < 2 or sys.argv[1] != "install":
        print(  # noqa: WPS421
            "Usage: hermes-skill-mcp install",
        )
        print(  # noqa: WPS421
            "       python -m hermes_skill_mcp install",
        )
        sys.exit(1)

    plugin_dir = Path.home() / ".hermes" / "plugins" / "skill-mcp"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    source_dir = Path(__file__).parent
    plugin_yaml = source_dir / "plugin.yaml"
    if plugin_yaml.exists():
        shutil.copy2(plugin_yaml, plugin_dir / "plugin.yaml")
        print(f"Plugin registered at {plugin_dir}")  # noqa: WPS421
    else:
        print(  # noqa: WPS421
            f"plugin.yaml not found at {plugin_yaml}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
