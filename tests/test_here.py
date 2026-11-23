"""What of Jenkins is installed here, on each system, as the finders (stood in for) say it: Windows' service and war
file, Linux's unit, its file and the war file, nothing looked for elsewhere; and how to install it, said for each system
from Jenkins' own pages. The real looks are refused by conftest's guard: only their words are read here."""
from __future__ import annotations

import ast
import inspect

from plugin_platform_jenkins import here
from stand_ins import WAR, FakeFinders


def test_windows_its_service_and_its_war_file():
    f = FakeFinders(system="windows", service="running", files=(WAR,))
    found = here.look(f)
    assert (found.system, found.service, found.state) == ("windows", "the Windows service jenkins", "running")
    assert found.war == WAR
    assert found.installed and found.words() == f"the Windows service jenkins (running) · its war file {WAR}"
    assert ("service", "jenkins") in f.asked


def test_windows_an_older_installs_folder_and_none_at_all():
    old = "C:\\Program Files (x86)\\Jenkins\\jenkins.war"
    found = here.look(FakeFinders(system="windows", files=(old,)))
    assert found.installed and found.war == old and found.service == ""
    found = here.look(FakeFinders(system="windows"))
    assert not found.installed and found.words() == "not installed here"
    why = "the service jenkins could not be asked (error 5)"
    found = here.look(FakeFinders(system="windows", service="not known", why=why))
    assert found.installed and found.words() == "the Windows service jenkins (not known)" and "error 5" in found.why


def test_linux_its_unit_its_file_and_its_war_file():
    f = FakeFinders(system="linux", unit="running", files=("/lib/systemd/system/jenkins.service",
                                                            "/usr/share/java/jenkins.war"))
    found = here.look(f)
    assert (found.service, found.state) == ("the systemd unit jenkins.service", "running")
    assert (found.unit_file, found.war) == ("/lib/systemd/system/jenkins.service", "/usr/share/java/jenkins.war")
    assert ("unit", "jenkins.service") in f.asked
    found = here.look(FakeFinders(system="linux", files=("/usr/share/jenkins/jenkins.war",)))
    assert found.installed and found.service == "" and found.war == "/usr/share/jenkins/jenkins.war"


def test_linux_without_systemd_its_unit_file_says_it_is_installed():
    why = "systemctl could not say: System has not been booted with systemd as init system (PID 1). Can't operate."
    found = here.look(FakeFinders(system="linux", files=("/usr/lib/systemd/system/jenkins.service",), why=why))
    assert found.installed and found.state == "" and found.service == "the systemd unit jenkins.service"
    assert found.words() == "the systemd unit jenkins.service (its state not known)" and found.why == why


def test_another_system_looks_for_nothing():
    f = FakeFinders(system="darwin")
    found = here.look(f)
    assert not found.installed and not found.looked and f.asked == []
    assert found.words() == "not looked for on darwin"


def source_of(name: str) -> str:
    """A function of here.py as written (the guard stands in for the real looks: their code is read from the file)."""
    text = inspect.getsource(here)
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node)


def test_the_real_looks_ask_only_what_they_say():
    """Never run here (the guard refuses them): their code asks the service control manager for a status alone, and
    systemctl to show three properties."""
    win = source_of("_service_state")
    for call in ("OpenSCManagerW", "OpenServiceW", "QueryServiceStatus", "CloseServiceHandle"):
        assert f"adv.{call}(" in win
    assert "SC_MANAGER_CONNECT" in win and "SERVICE_QUERY_STATUS" in win and "StartService" not in win
    unit = source_of("_unit_state")
    assert '"systemctl", "show"' in unit and "LoadState" in unit and "no_window()" in unit
    assert all(word not in unit for word in ('"start"', '"stop"', '"enable"'))


def test_how_to_install_is_said_for_each_system():
    win = {step: how for step, how in here.install_rows("windows")}
    assert "https://www.jenkins.io/download/" in win["Jenkins"] and "Windows service" in win["Jenkins"]
    assert "initialAdminPassword" in win["Unlock it"] and "Java 21 or 25" in win["Java"]
    assert win["Sign in here"].endswith("set JENKINS_USER and JENKINS_TOKEN in this plugin's Settings")
    linux = {step: how for step, how in here.install_rows("linux")}
    assert "https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key" in linux["Debian, Ubuntu: its repository"]
    assert "https://pkg.jenkins.io/rpm-stable/jenkins.repo" in linux["Fedora, Red Hat: its repository"]
    assert "openjdk-21-jre" in linux["Debian, Ubuntu: Java"]
    assert "java-21-openjdk" in linux["Fedora, Red Hat: Java and Jenkins"]
    assert "systemctl start jenkins" in linux["Start it"]
    other = {step: how for step, how in here.install_rows("darwin")}
    assert "https://www.jenkins.io/download/" in other["Jenkins"]
