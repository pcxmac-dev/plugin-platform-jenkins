"""The plugin conforms to the class contract (plugin API 2.2: liminal_libs.sources.conformance, read from the plugin
alone, nothing run): a machine plugin of the platform named jenkins, drawn under the Continuous Integration plugins,
its icon Jenkins' mark; its hooks the machine kind's and its own two; its version and floor as pyproject says them; one
run state across the registry's copies; what it says of the interface it shares sound by the Internal API tab's rules;
and its settings declared as the login reads them, the token a secret."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import liminal_libs
import plugin_platform_jenkins as module
from liminal_libs import internal
from liminal_libs.sources.conformance import assert_module_conforms
from liminal_libs.sources.keys import refusal
from liminal_libs.ui import STATIC

PYPROJECT = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert found and all(p.api == "2.2" and not p.is_record for p in found)
    assert {p.SYSTEM for p in found} == {"platform"} and {p.KIND for p in found} == {"machine"}
    assert {p.name for p in found} == {"jenkins"} and {p.ICON for p in found} == {"jenkins"}
    assert [p.title for p in found] == ["Jenkins"]
    assert module.MACHINE.interface()["apis"] == [a.name for a in module.MACHINE.apis]


def test_it_is_drawn_under_the_platforms_continuous_integration_plugins():
    """Its section of the platform's list (the user, 2026-11-22: a "Continuous Integration" class of plugins): "ci"; a
    platform that does not draw it yet keeps it under Machine plugins."""
    assert {p.SECTION for p in assert_module_conforms(module)} == {"ci"}


def test_its_icon_is_jenkins_mark_once_the_library_draws_it():
    """The tray draws the icon by its name in the library's icons.js: a name it does not have draws nothing, so the
    plugin's page stands without it until the library adds Jenkins' mark."""
    drawn = set(re.findall(r"^\s*([a-z]+):\s*'", (STATIC / "icons.js").read_text(encoding="utf-8"), re.M))
    assert module.MACHINE.ICON == "jenkins"
    if "jenkins" not in drawn:
        pytest.skip("liminal-libs' icons.js draws no jenkins mark yet: the tray shows none for it until it does")
    assert module.MACHINE.ICON in drawn


def test_its_hooks_are_the_machine_kinds_and_its_own():
    p = module.MACHINE
    assert set(p.interface()["hooks"]) == {"present", "status", "refresh", "build"}
    assert p.HOOKS[-2:] == ("refresh", "build") and p.READ_HOOKS == ("refresh",)
    assert not any(h in p.interface()["hooks"] for h in ("setup", "run", "instances", "scan", "settings"))


def test_what_it_says_of_its_interface_is_sound():
    """The Internal API tab's own rules (liminal-libs 1.63.0's internal.problems): its declarations name its own hooks,
    a read is no job and takes no accept_ argument, every hook it answers says what it is in its docstring."""
    assert internal.problems(module.MACHINE) == []
    assert all(isinstance(n, str) and len(n) <= 400 for n in module.MACHINE.INTERNAL_NOTES)


def test_its_version_and_floor_are_pyprojects():
    assert re.search(r'^version = "([^"]+)"', PYPROJECT, re.M).group(1) == module.__version__ == "0.1.0"
    floor = re.search(r'"liminal-libs>=([0-9.]+)"', PYPROJECT).group(1)
    assert floor == "1.63.0"
    have = tuple(int(x) for x in liminal_libs.__version__.split(".")[:3])
    assert have >= tuple(int(x) for x in floor.split("."))  # this library is new enough
    assert re.search(r'^jenkins = "plugin_platform_jenkins"$', PYPROJECT, re.M)  # its entry point


def test_a_copy_the_registry_hands_out_shares_what_the_plugin_keeps():
    p = module.JenkinsPlugin()
    copy = p.with_(origin="the plugin directory's checkout")
    assert copy is not p and copy._rt is p._rt and copy.name == "jenkins"


def test_its_settings_are_declared_as_the_login_reads_them():
    keys = {k.name: k for k in module.MACHINE.keys}
    assert list(keys) == ["JENKINS_URL", "JENKINS_USER", "JENKINS_TOKEN"]
    assert keys["JENKINS_TOKEN"].secret and not keys["JENKINS_URL"].secret and not keys["JENKINS_USER"].secret
    assert [k.pair for k in keys.values()] == ["jenkins-url", "jenkins-user", "jenkins-token"]
    assert all(refusal(n) is None for n in keys)  # none Windows', Python's or the app's own
    assert all(k.hint for k in keys.values())
