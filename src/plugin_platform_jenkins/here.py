"""What of Jenkins is installed on this machine, looked at without asking Jenkins, and how it is installed.

- Windows: its service, `jenkins` as Jenkins' installer makes it, and its state, asked of the service control manager
  (OpenSCManagerW, OpenServiceW, QueryServiceStatus, CloseServiceHandle: no process, and no administrator's rights,
  since a signed-in user may query a service's status); its war file in its install folder (%ProgramFiles%\\Jenkins,
  and Program Files (x86) where an older 32-bit installer put it).
- Linux: its systemd unit, `jenkins.service` as the jenkins.io packages make it: the unit's file where they put it, and
  its state as `systemctl show` says it (a read that ends; where systemd does not run, as in a WSL distribution without
  it, the state is said as not known); its war file (/usr/share/java/jenkins.war, and where older packages kept it).
- Any other system: nothing is looked for here; only Jenkins' address says whether it is there.

`Finders` are the real looks, each a read that changes nothing (a test hands its own); `look` reads them into a
`Found`. What a look got is put in words apart from the look itself (`unit_state_of`: what `systemctl show` printed;
`service_state_of`: the service's dwCurrentState), so the words are tested on what systemd and Windows answer.
`install_rows` says how Jenkins is installed on each system, from Jenkins' own pages (read 2026-11-22: the jenkins.io
installing guides and the Java support policy; the Windows installer's own source for where it keeps JENKINS_HOME):
this plugin installs, starts and stops nothing."""
from __future__ import annotations

import ntpath
import os
import subprocess
import sys
from dataclasses import dataclass

from liminal_libs.proc import no_window

SERVICE = "jenkins"  # the Windows service, by the name Jenkins' installer gives it
UNIT = "jenkins.service"  # the systemd unit, by the name the jenkins.io packages give it
# %ProgramFiles%; the 64-bit Program Files as a 32-bit Python is told it; an older 32-bit installer's
FOLDERS = ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
WARS = ("/usr/share/java/jenkins.war", "/usr/share/jenkins/jenkins.war", "/usr/lib/jenkins/jenkins.war")
UNIT_FILES = ("/etc/systemd/system/jenkins.service", "/usr/lib/systemd/system/jenkins.service",
              "/lib/systemd/system/jenkins.service")
STATES = {1: "stopped", 2: "starting", 3: "stopping", 4: "running", 5: "continuing", 6: "pausing", 7: "paused"}
ACTIVE = {"active": "running", "inactive": "stopped", "failed": "failed", "activating": "starting",
          "deactivating": "stopping", "reloading": "reloading"}  # systemd's ActiveState, in words
MASKED = "masked: it cannot be started"  # a unit systemd is told never to start (systemctl mask)
RESTARTING = "restarting after a failure"  # activating, its SubState auto-restart: it failed, systemd starts it again
SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS = 0x0001, 0x0004
ERROR_SERVICE_DOES_NOT_EXIST = 1060
SYSTEMCTL_S = 5.0  # seconds `systemctl show` is given


@dataclass(frozen=True)
class Found:
    """What of Jenkins is installed here, as looked at: the system (windows, linux, or another's sys.platform), its
    service or unit ("" when there is none) and that one's state in words ("" when not known), its war file's path and
    its unit file's ("" when none was found), and what could not be looked at, in words."""

    system: str = ""
    service: str = ""
    state: str = ""
    war: str = ""
    unit_file: str = ""
    why: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.service or self.war or self.unit_file)

    @property
    def looked(self) -> bool:
        """Whether this system is one where Jenkins' install is looked for."""
        return self.system in ("windows", "linux")

    def words(self) -> str:
        """What was found, in one line."""
        parts = []
        if self.service:
            parts.append(f"{self.service} ({self.state or 'its state not known'})")
        if self.war:
            parts.append(f"its war file {self.war}")
        if parts:
            return " · ".join(parts)
        return "not installed here" if self.looked else f"not looked for on {self.system or 'this system'}"


class Finders:
    """The real looks at this machine, each a read that changes nothing: what a test stands in for."""

    def system(self) -> str:
        """This machine's system: windows, linux, or sys.platform's word for another (darwin)."""
        if os.name == "nt":
            return "windows"
        return "linux" if sys.platform.startswith("linux") else sys.platform

    def env(self, name: str) -> str:
        """One of this process's environment variables, "" when it is not set (%ProgramFiles% and its siblings)."""
        return os.environ.get(name, "")

    def file(self, path: str) -> bool:
        """Whether a file is there."""
        try:
            return os.path.isfile(path)
        except (OSError, ValueError):
            return False

    def windows_service(self, name: str) -> tuple[str, str]:
        """(a Windows service's state in words, "" when there is no such service; why it could not be asked, "" when
        it could)."""
        return _service_state(name)

    def systemd_unit(self, name: str) -> tuple[str, str]:
        """(a systemd unit's state in words, "" when systemd has no such unit; why it could not be asked, "" when it
        could)."""
        return _unit_state(name)


def look(finders: Finders | None = None) -> Found:
    """What of Jenkins is installed here, by `finders` (the real ones unless given)."""
    f = finders if finders is not None else Finders()
    system = f.system()
    if system == "windows":
        state, why = f.windows_service(SERVICE)
        wars = dict.fromkeys(ntpath.join(f.env(v), "Jenkins", "jenkins.war") for v in FOLDERS if f.env(v))
        war = next((p for p in wars if f.file(p)), "")
        return Found(system, f"the Windows service {SERVICE}" if state else "", state, war, "", why)
    if system == "linux":
        unit_file = next((p for p in UNIT_FILES if f.file(p)), "")
        state, why = f.systemd_unit(UNIT)
        war = next((p for p in WARS if f.file(p)), "")
        return Found(system, f"the systemd unit {UNIT}" if state or unit_file else "", state, war, unit_file, why)
    return Found(system, why="on this system only Jenkins' address is looked at")


# -- the real looks ------------------------------------------------------------------------------------------------
def _service_state(name: str) -> tuple[str, str]:
    """A Windows service's state, asked of the service control manager with the rights any signed-in user holds
    (SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS): OpenSCManagerW, OpenServiceW, QueryServiceStatus, CloseServiceHandle."""
    import ctypes
    from ctypes import wintypes

    class ServiceStatus(ctypes.Structure):  # SERVICE_STATUS, as winsvc.h lays it out
        _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD), ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
    except (OSError, AttributeError) as e:
        return "", f"the service control manager could not be reached ({type(e).__name__})"
    adv.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    adv.OpenSCManagerW.restype = wintypes.HANDLE
    adv.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    adv.OpenServiceW.restype = wintypes.HANDLE
    adv.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    adv.QueryServiceStatus.restype = wintypes.BOOL
    adv.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    adv.CloseServiceHandle.restype = wintypes.BOOL
    manager = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not manager:
        return "", f"the service control manager could not be asked (error {ctypes.get_last_error()})"
    try:
        service = adv.OpenServiceW(manager, name, SERVICE_QUERY_STATUS)
        if not service:
            error = ctypes.get_last_error()
            if error == ERROR_SERVICE_DOES_NOT_EXIST:
                return "", ""
            return "not known", f"the service {name} could not be asked (error {error})"
        try:
            status = ServiceStatus()
            if not adv.QueryServiceStatus(service, ctypes.byref(status)):
                return "not known", f"the service {name}'s state could not be read (error {ctypes.get_last_error()})"
            return service_state_of(status.dwCurrentState), ""
        finally:
            adv.CloseServiceHandle(service)
    finally:
        adv.CloseServiceHandle(manager)


def service_state_of(current) -> str:
    """A Windows service's state in words, from its SERVICE_STATUS's dwCurrentState (SERVICE_STOPPED 1 to
    SERVICE_PAUSED 7)."""
    try:
        state = int(current)
    except (TypeError, ValueError):
        return "not known"
    return STATES.get(state, f"in state {state}")


def _unit_state(name: str) -> tuple[str, str]:
    """A systemd unit's state as `systemctl show` says it (its LoadState, ActiveState and SubState): a read that ends,
    run without a window and without this process's standard input."""
    command = ["systemctl", "show", name, "--no-pager", "-p", "LoadState", "-p", "ActiveState", "-p", "SubState"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=SYSTEMCTL_S, stdin=subprocess.DEVNULL, check=False, **no_window())
    except FileNotFoundError:
        return "", "systemctl is not here: this system does not run systemd"
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"systemctl could not be asked ({type(e).__name__})"
    return unit_state_of(done.returncode, done.stdout, done.stderr)


def unit_state_of(code, out, err) -> tuple[str, str]:
    """(a systemd unit's state in words, "" when systemd has no such unit; why systemctl could not say, "" when it
    could), from what `systemctl show -p LoadState -p ActiveState -p SubState` ended with and printed: masked (systemd
    is told never to start it), restarting after a failure (activating, its SubState auto-restart), else its
    ActiveState in words with its SubState when that says more."""
    if code != 0:
        said = " ".join(str(err or out or "").split())[:200]
        return "", f"systemctl could not say: {said or f'it ended with {code}'}"
    props = dict(line.split("=", 1) for line in str(out or "").splitlines() if "=" in line)
    load, active, sub = (props.get(k, "").strip() for k in ("LoadState", "ActiveState", "SubState"))
    if load in ("", "not-found"):
        return "", ""
    if load == "masked":
        return MASKED, ""
    if active == "activating" and sub.startswith("auto-restart"):
        return RESTARTING, ""
    words = ACTIVE.get(active, active or "not known")
    return (f"{words} ({sub})" if sub and sub not in ("running", "dead", "start", "stop", active) else words), ""


# -- how Jenkins is installed: its own steps, said, never done -------------------------------------------------------
JAVA = ("Java 21 or 25 (today's Jenkins runs on no older Java: the last releases for Java 17 were the LTS 2.541.3 and "
        "the weekly 2.544)")
TOKEN_STEP = ("Sign in here", "make an API token (your name, top right › Security › API Token › Add new Token), then "
                              "set JENKINS_USER and JENKINS_TOKEN in this plugin's Settings")
# a war file run by hand: Jenkins' builds on its built-in node inherit the environment it was started in, so one started
# where the plugin's settings are environment variables (the platform's login keeps them so today) hands the token on
WAR_ALONE = ("in a shell where JENKINS_USER and JENKINS_TOKEN are not set (the builds on its built-in node inherit the "
             "environment it starts in, the token too)")


def install_rows(system: str) -> list[list[str]]:
    """How Jenkins is installed on `system`, a step a row (its LTS line, as jenkins.io says it on 2026-11-22)."""
    if system == "windows":
        return [
            ["Java", f"{JAVA}: a JDK or JRE of its own, Eclipse Temurin's (adoptium.net) say"],
            ["Jenkins", "the Windows installer of the LTS line, from https://www.jenkins.io/download/: it installs "
                        "Jenkins as a Windows service listening at port 8080, in C:\\Program Files\\Jenkins unless you "
                        "choose another folder"],
            ["Unlock it", "open http://localhost:8080 and type the password from the file the Unlock Jenkins page "
                          "names, JENKINS_HOME\\secrets\\initialAdminPassword (JENKINS_HOME: C:\\ProgramData\\Jenkins\\"
                          ".jenkins for a service run as LocalSystem, the service user's %LocalAppData%\\Jenkins\\"
                          ".jenkins otherwise; the password is in jenkins.err.log too), then make your user"],
            list(TOKEN_STEP),
            ["Its guide", "https://www.jenkins.io/doc/book/installing/windows/"],
        ]
    if system == "linux":
        return [
            ["Debian, Ubuntu: Java", "sudo apt update && sudo apt install fontconfig openjdk-21-jre"],
            ["Debian, Ubuntu: its repository",
             "sudo wget -O /etc/apt/keyrings/jenkins-keyring.asc "
             "https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key, then the line deb "
             "[signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/ in "
             "/etc/apt/sources.list.d/jenkins.list"],
            ["Debian, Ubuntu: Jenkins", "sudo apt update && sudo apt install jenkins"],
            ["Fedora, Red Hat: its repository",
             "sudo wget -O /etc/yum.repos.d/jenkins.repo https://pkg.jenkins.io/rpm-stable/jenkins.repo"],
            ["Fedora, Red Hat: Java and Jenkins",
             "sudo dnf install fontconfig java-21-openjdk jenkins (yum on Red Hat), then sudo systemctl daemon-reload"],
            ["Start it", "sudo systemctl enable jenkins && sudo systemctl start jenkins: the unit jenkins.service, "
                         "listening at port 8080 (in a WSL distribution, systemd runs once /etc/wsl.conf says "
                         "[boot] systemd=true)"],
            ["Unlock it", "open http://localhost:8080 and type the password in "
                          "/var/lib/jenkins/secrets/initialAdminPassword, then make your user"],
            list(TOKEN_STEP),
            ["Its guide", "https://www.jenkins.io/doc/book/installing/linux/"],
        ]
    return [
        ["Java", JAVA],
        ["Jenkins", "https://www.jenkins.io/download/ lists its packages for every system (some are third parties'), "
                    f"and its war file, run with java -jar jenkins.war --httpPort=8080 {WAR_ALONE}"],
        list(TOKEN_STEP),
    ]
