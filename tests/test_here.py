"""What of Jenkins is installed here, on each system, as the finders (stood in for) say it: Windows' service and war
file, Linux's unit, its file and the war file, nothing looked for elsewhere; the state words of what the real looks
get (systemctl show's output as systemd prints it, each SERVICE_STATUS state) and what the page advises for each; and
how to install it, said for each system from Jenkins' own pages. The real looks are refused by conftest's guard: their
reads are stood in for, or their code read."""
from __future__ import annotations

import ast
import inspect
import subprocess

import pytest

from plugin_platform_jenkins import JenkinsPlugin, here
from plugin_platform_jenkins.here import _unit_state as REAL_UNIT_STATE  # taken before conftest's guard stands in
from stand_ins import WAR, FakeFinders

# what `systemctl show jenkins.service --no-pager -p LoadState -p ActiveState -p SubState` ends with and prints
SYSTEMCTL = {
    "running": (0, "LoadState=loaded\nActiveState=active\nSubState=running\n", ""),
    "stopped": (0, "LoadState=loaded\nActiveState=inactive\nSubState=dead\n", ""),
    "failed": (0, "LoadState=loaded\nActiveState=failed\nSubState=failed\n", ""),
    "restarting": (0, "LoadState=loaded\nActiveState=activating\nSubState=auto-restart\n", ""),
    "starting": (0, "LoadState=loaded\nActiveState=activating\nSubState=start\n", ""),
    "stopping": (0, "LoadState=loaded\nActiveState=deactivating\nSubState=stop-sigterm\n", ""),
    "masked": (0, "LoadState=masked\nActiveState=inactive\nSubState=dead\n", ""),
    "no unit": (0, "LoadState=not-found\nActiveState=inactive\nSubState=dead\n", ""),
    "no systemd": (1, "", "System has not been booted with systemd as init system (PID 1). Can't operate.\n"
                          "Failed to connect to bus: Host is down\n"),
}


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


@pytest.mark.parametrize("case, state, advice", [
    ("running", "running", "Its unit runs: it may answer at another port"),
    ("stopped", "stopped", "Its unit is stopped: start it with sudo systemctl start jenkins"),
    ("failed", "failed", "Its unit failed: journalctl -u jenkins says why"),
    ("restarting", "restarting after a failure", "systemd starts it again: journalctl -u jenkins says why it fails"),
    ("starting", "starting", "Its unit is starting: wait for it"),
    ("stopping", "stopping (stop-sigterm)", "Its unit is stopping: once it has stopped, start it"),
    ("masked", "masked: it cannot be started", "sudo systemctl unmask jenkins first, then sudo systemctl start"),
])
def test_a_units_state_in_words_and_what_to_do_with_it(case, state, advice):
    """systemctl show's output as systemd prints it, read into the unit's state, and the page's advice for it."""
    said, why = here.unit_state_of(*SYSTEMCTL[case])
    assert (said, why) == (state, "")
    found = here.Found("linux", "the systemd unit jenkins.service", said, "", "/usr/lib/systemd/system/jenkins.service")
    words = JenkinsPlugin._start_words(found)
    assert advice in words, words
    if case != "running":
        assert "another port" not in words
    if case in ("masked", "failed", "restarting", "starting", "stopping"):
        assert not words.startswith(f"Its unit is {state}: start it with")  # never advice its state contradicts


def test_no_unit_and_no_systemd_in_words():
    assert here.unit_state_of(*SYSTEMCTL["no unit"]) == ("", "")  # systemd knows no jenkins.service
    state, why = here.unit_state_of(*SYSTEMCTL["no systemd"])
    assert state == "" and why == ("systemctl could not say: System has not been booted with systemd as init system "
                                   "(PID 1). Can't operate. Failed to connect to bus: Host is down")
    assert here.unit_state_of(3, "", "") == ("", "systemctl could not say: it ended with 3")
    found = here.Found("linux", "the systemd unit jenkins.service", "", "", "/usr/lib/systemd/system/jenkins.service",
                       why)
    assert "in a WSL distribution, systemd runs once /etc/wsl.conf says [boot] systemd=true" in \
        JenkinsPlugin._start_words(found)


def test_the_real_unit_look_reads_what_systemctl_prints(monkeypatch):
    """_unit_state itself, over a stand-in for subprocess.run (no process is started): the command it runs, and its
    output read as unit_state_of reads it."""
    ran = []

    def run(command, **options):
        ran.append((command, options))
        return subprocess.CompletedProcess(command, *SYSTEMCTL["restarting"])

    monkeypatch.setattr(subprocess, "run", run)
    assert REAL_UNIT_STATE("jenkins.service") == ("restarting after a failure", "")
    ((command, options),) = ran
    assert command == ["systemctl", "show", "jenkins.service", "--no-pager", "-p", "LoadState", "-p", "ActiveState",
                       "-p", "SubState"]
    assert options["stdin"] is subprocess.DEVNULL and options["timeout"] == here.SYSTEMCTL_S

    def missing(command, **options):
        raise FileNotFoundError(2, "No such file or directory", "systemctl")

    monkeypatch.setattr(subprocess, "run", missing)
    assert REAL_UNIT_STATE("jenkins.service") == ("", "systemctl is not here: this system does not run systemd")


@pytest.mark.parametrize("current, state, advice", [
    (1, "stopped", "Its service is stopped: start it from the Services app, or with Start-Service jenkins"),
    (2, "starting", "Its service is starting: wait for it"),
    (3, "stopping", "Its service is stopping: once it has stopped, start it"),
    (4, "running", "Its service runs: it may answer at another port"),
    (5, "continuing", "Its service is continuing: wait for it"),
    (6, "pausing", "Its service is pausing: resume it from the Services app, or with Resume-Service jenkins"),
    (7, "paused", "Its service is paused: resume it from the Services app, or with Resume-Service jenkins"),
    (9, "in state 9", "Its service is in state 9: start it from the Services app"),
    (None, "not known", "Its service's state is not known"),
])
def test_a_services_state_in_words_and_what_to_do_with_it(current, state, advice):
    """Each SERVICE_STATUS dwCurrentState in words, and the page's advice for it."""
    assert here.service_state_of(current) == state
    found = here.Found("windows", "the Windows service jenkins", state, WAR, "", "")
    words = JenkinsPlugin._start_words(found)
    assert advice in words, words
    if current in (2, 3, 5, 6, 7):  # starting, stopping, pausing, paused: no start asked of it as it is
        assert not words.split(": ", 1)[1].startswith("start it"), words


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
    # where today's installer keeps JENKINS_HOME (its jenkins.wxs: %ProgramData% for LocalSystem, else the service
    # user's %LocalAppData%), not its install folder
    assert "C:\\ProgramData\\Jenkins\\.jenkins" in win["Unlock it"] and "%LocalAppData%\\Jenkins\\.jenkins" in \
        win["Unlock it"] and "jenkins.err.log" in win["Unlock it"]
    assert "Program Files\\Jenkins\\secrets" not in win["Unlock it"]
    assert win["Sign in here"].endswith("set JENKINS_USER and JENKINS_TOKEN in this plugin's Settings")
    linux = {step: how for step, how in here.install_rows("linux")}
    assert "https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key" in linux["Debian, Ubuntu: its repository"]
    assert "https://pkg.jenkins.io/rpm-stable/jenkins.repo" in linux["Fedora, Red Hat: its repository"]
    assert "openjdk-21-jre" in linux["Debian, Ubuntu: Java"]
    assert "java-21-openjdk" in linux["Fedora, Red Hat: Java and Jenkins"]
    assert "systemctl start jenkins" in linux["Start it"]
    other = {step: how for step, how in here.install_rows("darwin")}
    assert "https://www.jenkins.io/download/" in other["Jenkins"]
    assert "java -jar jenkins.war --httpPort=8080 in a shell where JENKINS_USER and JENKINS_TOKEN are not set" in \
        other["Jenkins"]  # a Jenkins started from an environment holding the token hands it to its builds
