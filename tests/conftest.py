"""Test fixtures and shared utilities."""
import importlib
import json
import os
import subprocess
from pathlib import Path
import pytest

_CI_PLUGIN_PATH = "/opt/hermes/plugins/hermes_skill_mcp"
_DEV_PLUGIN_PATH = str(Path(__file__).parent.parent / "src" / "hermes_skill_mcp")
PLUGIN_PATH = _CI_PLUGIN_PATH if Path(_CI_PLUGIN_PATH).exists() else _DEV_PLUGIN_PATH


def import_plugin_module(module_name: str):
    """Import a module from the skill-mcp plugin directory."""
    plugin_path = Path(PLUGIN_PATH)
    file_name = module_name.split(".")[-1]
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_path / "{}.py".format(file_name),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def plugin_dir():
    """Path to the installed skill-mcp plugin."""
    path = Path(PLUGIN_PATH)
    assert path.exists(), "Plugin not found at {}".format(path)
    return path


@pytest.fixture(scope="session")
def hermes_bin():
    """Ensure hermes CLI is available."""
    cmd_result = subprocess.run(
        ["which", "hermes"], capture_output=True, text=True,
    )
    assert cmd_result.returncode == 0, "hermes CLI not found"
    return cmd_result.stdout.strip()


@pytest.fixture(scope="module")
def e2e_config():
    """API credentials from environment."""
    return {
        "key": os.environ.get("HERMES_API_KEY", ""),
        "url": os.environ.get("HERMES_API_URL", ""),
        "model": os.environ.get("HERMES_API_MODEL", ""),
    }


@pytest.fixture
def temp_skills_dir(tmp_path):
    """Temporary skills directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def skill_with_mcp(tmp_path):
    """Fixture factory: create temp skill dir with mcp.yaml."""
    import yaml

    def _create(skill_name, mcp_config=None):
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# {}\n".format(skill_name))
        if mcp_config is not None:
            mcp_yaml = skill_dir / "mcp.yaml"
            mcp_yaml.write_text(yaml.dump(mcp_config))
        return skill_dir
    return _create


@pytest.fixture
def skill_without_mcp(tmp_path):
    """Fixture factory: create temp skill dir without mcp.yaml."""

    def _create(skill_name):
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "# {}\n".format(skill_name),
        )
        return skill_dir

    return _create


@pytest.fixture
def skill_with_mcp_json(tmp_path):
    """Fixture factory: create temp skill dir with mcp.json."""
    import json

    def _create(skill_name, mcp_config=None, format_type="wrapper"):
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# {}\n".format(skill_name))
        if mcp_config is not None:
            mcp_json_path = skill_dir / "mcp.json"
            if format_type == "wrapper":
                json_data = {"mcpServers": mcp_config}
            elif format_type == "flat":
                json_data = mcp_config
            else:
                raise ValueError("format_type must be 'wrapper' or 'flat'")
            mcp_json_path.write_text(json.dumps(json_data, indent=2))
        return skill_dir
    return _create


@pytest.fixture
def skill_with_frontmatter_mcp(tmp_path):
    """Fixture factory: create temp skill dir with mcp: in SKILL.md frontmatter."""
    def _create(skill_name, mcp_config=None, frontmatter_extra=None):
        skill_dir = tmp_path / skill_name
        skill_dir.mkdir(exist_ok=True)

        import yaml
        fm_data = {"name": skill_name, "description": "Test skill"}
        if frontmatter_extra:
            fm_data.update(frontmatter_extra)
        if mcp_config is not None:
            fm_data["mcp"] = mcp_config

        frontmatter = yaml.dump(fm_data, default_flow_style=False)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\n{}---\n# {}\n".format(frontmatter, skill_name))
        return skill_dir
    return _create
