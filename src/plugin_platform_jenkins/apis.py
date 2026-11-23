"""What the Jenkins plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API
its attached to, and present links that provide documentation ... it should also expose more of what the API is
about"): Jenkins' remote access API, and what it looks at on this machine for Jenkins' install, Windows' service control
manager or systemd's systemctl. Each part of each API is named with what the plugin does with it, each call it makes
with what it makes it for, and the notable calls it does not make; every address was read on its maker's pages on
2026-11-22 (liminal_libs.sources.apis.dead_links checks them, LIMINAL_VENDOR_PAGES=1)."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

VERIFIED = "2026-11-22"
REMOTE = "Jenkins remote access API"
SCM = "Windows service control manager"
SYSTEMD = "systemd's systemctl"

_DOC = "https://www.jenkins.io/doc/book/"
_JAVADOC = "https://javadoc.jenkins.io/"
_REMOTE = _DOC + "using/remote-access-api/"
_CSRF = _DOC + "security/csrf-protection/"
_SCRIPTED = _DOC + "system-administration/authenticating-scripted-clients/"
_NODES = _DOC + "managing/nodes/"
_ABORT = _DOC + "using/aborting-a-build/"
_PLUGINS = _DOC + "managing/plugins/"
_SCRIPT = _DOC + "managing/script-console/"
_CLI = _DOC + "managing/cli/"
_WIN32 = "https://learn.microsoft.com/en-us/windows/win32/"
_WINSVC = _WIN32 + "api/winsvc/"
_SYSTEMCTL = "https://www.freedesktop.org/software/systemd/man/latest/systemctl.html"


def _javadoc(page: str) -> str:
    """A class's page of Jenkins' javadoc: hudson/model/Job, hudson/model/Queue.Item."""
    return _JAVADOC + page + ".html"


JENKINS = Api(
    name=REMOTE, maker="The Jenkins project", kind="rest",
    about=("Jenkins' remote access API: every page of Jenkins answers under its .../api/ in XML, in JSON (with JSONP) "
           "and as a Python literal, and the actions behind its buttons (a build, a job's configuration, a node taken "
           "offline) answer a POST. The plugin reads the JSON flavour, asking with a tree for only what its page shows "
           "and at most 200 rows of a list; Jenkins' version comes in the X-Jenkins header of every answer. It asks a "
           "job's build once the platform's page has confirmed it, and makes no other change."),
    base=("JENKINS_URL (http://127.0.0.1:8080 unless set): /api/json, /queue/api/json, /computer/api/json, "
          "/job/NAME/..."),
    version=("Jenkins 2's remote access API, its JSON flavour; read against the LTS 2.580.2 and the weekly 2.591 "
             "(their pages, 2026-11-22)"),
    auth=("HTTP basic authentication with a user name and one of its API tokens, sent with the first request (Jenkins "
          "answers 403, not 401, to a request without it); only to JENKINS_URL, over https or on this machine. "
          "Requests authenticating with an API token are exempt from CSRF protection; any other POST sends the crumb "
          "/crumbIssuer/api/json gives, with the session cookie it came with, and the plugin sends it with a build "
          "whenever Jenkins issues one"),
    limits=("none published: Jenkins' own capacity. The plugin reads at most once every 30 s unless Read again asks "
            "now (three GETs a read, each waiting 5 s for each socket operation), and 4 MB of an answer at most"),
    costs="nothing: Jenkins is free and open source (the MIT licence)",
    links=(
        Link("Remote access API", _REMOTE, "docs"),
        Link("jenkins.io documentation", "https://www.jenkins.io/doc/", "docs"),
        Link("hudson.model.Api (every .../api/ page)", _javadoc("hudson/model/Api"), "reference"),
        Link("jenkins.model.Jenkins (/api/json)", _javadoc("jenkins/model/Jenkins"), "reference"),
        Link("hudson.model.Job", _javadoc("hudson/model/Job"), "reference"),
        Link("hudson.model.Run (a build)", _javadoc("hudson/model/Run"), "reference"),
        Link("hudson.model.BallColor (a job's colour)", _javadoc("hudson/model/BallColor"), "reference"),
        Link("hudson.model.Queue.Item", _javadoc("hudson/model/Queue.Item"), "reference"),
        Link("hudson.model.ComputerSet (/computer/api/json)", _javadoc("hudson/model/ComputerSet"), "reference"),
        Link("hudson.model.Computer (a node)", _javadoc("hudson/model/Computer"), "reference"),
        Link("hudson.security.csrf.CrumbIssuer", _javadoc("hudson/security/csrf/CrumbIssuer"), "reference"),
        Link("Authenticating scripted clients", _SCRIPTED, "auth"),
        Link("CSRF protection", _CSRF, "auth"),
        Link("Access control", _DOC + "security/access-control/", "auth"),
        Link("Managing nodes", _NODES, "guide"),
        Link("Aborting a build", _ABORT, "guide"),
        Link("Pipeline", _DOC + "pipeline/", "guide"),
        Link("Installing Jenkins on Windows", _DOC + "installing/windows/", "guide"),
        Link("Installing Jenkins on Linux", _DOC + "installing/linux/", "guide"),
        Link("The WAR file", _DOC + "installing/war-file/", "guide"),
        Link("Java support policy", _DOC + "platform-information/support-policy-java/", "guide"),
        Link("Downloads", "https://www.jenkins.io/download/", "tool"),
        Link("Debian and Ubuntu packages (LTS)", "https://pkg.jenkins.io/debian-stable/", "tool"),
        Link("Red Hat, Fedora and openSUSE packages (LTS)", "https://pkg.jenkins.io/rpm-stable/", "tool"),
        Link("Jenkins CLI", _CLI, "tool"),
        Link("LTS changelog", "https://www.jenkins.io/changelog-stable/", "changelog"),
        Link("Weekly changelog", "https://www.jenkins.io/changelog/", "changelog"),
        Link("Security advisories", "https://www.jenkins.io/security/advisories/", "changelog"),
        Link("jenkinsci/jenkins", "https://github.com/jenkinsci/jenkins", "source"),
    ),
    areas=(
        Area("Jenkins itself", "/api/json: the controller (its jobs, views, mode, whether it is getting ready to shut "
                               "down), and its version in the X-Jenkins header of every answer",
             _REMOTE, covered="its version, its jobs, and whether it is getting ready to shut down"),
        Area("Jobs", "/job/NAME/api/json: a job's colour, builds, health and parameters; a folder's jobs under it "
                     "(/job/FOLDER/job/NAME)", _javadoc("hudson/model/Job"),
             covered="listed with their state and last build (the Jobs table); a job looked at before its build"),
        Area("Builds", "/job/NAME/build and /buildWithParameters (a build asked), /job/NAME/NUMBER/api/json (one "
                       "build), its /stop, /term and /kill", _REMOTE, covered="a job's build asked, once confirmed"),
        Area("Build queue", "/queue/api/json: the builds waiting, why and since when; one item, and one taken off it",
             _javadoc("hudson/model/Queue.Item"), covered="the Build queue table"),
        Area("Nodes", "/computer/api/json: the built-in node and the agents, online or not, and their executors; a "
                      "node taken offline or back", _NODES, covered="the Nodes table"),
        Area("CSRF protection", "/crumbIssuer/api/json: the crumb a POST not authenticated by an API token sends",
             _CSRF, covered="a crumb asked before each build, and sent when Jenkins gives one"),
        Area("Views", "/view/NAME/api/json: the jobs a view lists"),
        Area("Console output", "/job/NAME/NUMBER/consoleText and its progressive log: what a build printed"),
        Area("Job configuration", "/job/NAME/config.xml read and replaced, /createItem (a job made), a job deleted"),
        Area("Users", "/whoAmI/api/json (who a request authenticates as), /user/NAME/api/json"),
        Area("Plugins", "/pluginManager/api/json: the plugins installed, their versions and updates", _PLUGINS),
        Area("Script console", "/script and /scriptText: Groovy run on the controller, an administrator's", _SCRIPT),
        Area("Restart and shutdown", "/quietDown, /cancelQuietDown, /safeRestart: the controller readied for a "
                                     "restart, or restarted"),
        Area("Jenkins CLI", "jenkins-cli.jar or SSH: Jenkins' tasks from a command line", _CLI),
    ),
    calls=(
        Call("GET /api/json", "the controller: its jobs, each one's name, colour, buildability, last build and "
                              "parameters (tree jobs[...]{0,200}), and whether it is getting ready to shut down",
             "Jenkins itself", used="the Jobs table, the version (X-Jenkins) and whether you are signed in",
             docs=_REMOTE),
        Call("GET /queue/api/json", "the build queue's items (tree items[...]{0,200})", "Build queue",
             used="the Build queue table", docs=_javadoc("hudson/model/Queue.Item")),
        Call("GET /computer/api/json", "the nodes and their executors (tree computer[...]{0,200})", "Nodes",
             used="the Nodes table", docs=_javadoc("hudson/model/ComputerSet")),
        Call("GET /job/{name}/api/json", "one job: whether it can be built, its parameters", "Jobs",
             used="Build…: the job looked at first, then refused in words if it is not there or cannot be built",
             docs=_javadoc("hudson/model/Job")),
        Call("GET /crumbIssuer/api/json", "a crumb and the request field it goes in (404: none issued)",
             "CSRF protection", used="Build…: asked first, and sent with the build when Jenkins gives one", docs=_CSRF),
        Call("POST /job/{name}/build", "a build of a job without parameters queued (its queue item in Location)",
             "Builds", used="Build… a job without parameters", docs=_REMOTE, writes=True),
        Call("POST /job/{name}/buildWithParameters", "a build of a job with parameters queued, their defaults unless "
                                                     "sent", "Builds",
             used="Build… a job with parameters (those typed, form-encoded)", docs=_REMOTE, writes=True),
        Call("GET /job/{name}/{number}/api/json", "one build: its result, its length, what started it", "Builds",
             docs=_javadoc("hudson/model/Run")),
        Call("POST /job/{name}/{number}/stop", "a running build aborted (/term and /kill, harder)", "Builds",
             docs=_ABORT, writes=True),
        Call("GET /queue/item/{id}/api/json", "one waiting build, and the build it became", "Build queue",
             docs=_javadoc("hudson/model/Queue.Item")),
        Call("POST /queue/cancelItem", "a waiting build taken off the queue", "Build queue", writes=True),
        Call("POST /computer/{name}/toggleOffline", "a node taken offline, or back online", "Nodes", docs=_NODES,
             writes=True),
        Call("GET /view/{name}/api/json", "a view's jobs", "Views"),
        Call("GET /job/{name}/{number}/consoleText", "a build's whole log, as text", "Console output"),
        Call("GET /job/{name}/config.xml", "a job's configuration", "Job configuration"),
        Call("POST /createItem", "a job made from a config.xml", "Job configuration", writes=True),
        Call("GET /whoAmI/api/json", "who a request authenticates as", "Users"),
        Call("GET /pluginManager/api/json", "the plugins installed", "Plugins", docs=_PLUGINS),
        Call("POST /scriptText", "a Groovy script run on the controller", "Script console", docs=_SCRIPT, writes=True),
        Call("POST /quietDown", "no new build started: ready for a restart", "Restart and shutdown", writes=True),
        Call("POST /safeRestart", "Jenkins restarted once its running builds end", "Restart and shutdown", writes=True),
    ),
    verified=VERIFIED)

WINDOWS_SCM = Api(
    name=SCM, maker="Microsoft", kind="system",
    about=("Windows' service control manager: the database of installed services, their states, their starts and "
           "stops. On Windows the plugin asks it whether Jenkins' service (jenkins, as Jenkins' installer makes it) is "
           "there and in what state, with no process and no administrator's rights, and looks for Jenkins' war file in "
           "its install folder (%ProgramFiles%\\Jenkins); it starts and stops nothing."),
    base="advapi32.dll: OpenSCManagerW, OpenServiceW, QueryServiceStatus, CloseServiceHandle",
    version="Win32 (winsvc.h), Windows XP and later",
    auth=("the signed-in user: SC_MANAGER_CONNECT to the manager and SERVICE_QUERY_STATUS to the service, which a "
          "local user holds by default"),
    limits="", costs="",
    links=(
        Link("Service control manager", _WIN32 + "services/service-control-manager", "docs"),
        Link("OpenSCManagerW", _WINSVC + "nf-winsvc-openscmanagerw", "reference"),
        Link("OpenServiceW", _WINSVC + "nf-winsvc-openservicew", "reference"),
        Link("QueryServiceStatus", _WINSVC + "nf-winsvc-queryservicestatus", "reference"),
        Link("SERVICE_STATUS", _WINSVC + "ns-winsvc-service_status", "reference"),
        Link("CloseServiceHandle", _WINSVC + "nf-winsvc-closeservicehandle", "reference"),
        Link("Service security and access rights", _WIN32 + "services/service-security-and-access-rights", "auth"),
    ),
    areas=(
        Area("Service status", "whether a service is there, and its state (stopped, starting, running ...)",
             _WINSVC + "nf-winsvc-queryservicestatus", covered="Jenkins' service and its state (Installed)"),
        Area("Service control", "a service started, stopped, paused or continued",
             _WINSVC + "nf-winsvc-controlservice"),
    ),
    calls=(
        Call("OpenSCManagerW", "the service control manager of this machine opened (SC_MANAGER_CONNECT)",
             "Service status", used="each read: to ask for Jenkins' service",
             docs=_WINSVC + "nf-winsvc-openscmanagerw"),
        Call("OpenServiceW", "one service opened by its name (SERVICE_QUERY_STATUS); ERROR_SERVICE_DOES_NOT_EXIST when "
                             "it is not there", "Service status", used="each read: the service jenkins",
             docs=_WINSVC + "nf-winsvc-openservicew"),
        Call("QueryServiceStatus", "a service's SERVICE_STATUS: its current state", "Service status",
             used="each read: the jenkins service's state", docs=_WINSVC + "nf-winsvc-queryservicestatus"),
        Call("CloseServiceHandle", "a handle of the manager or a service closed", "Service status",
             used="each read, after the state is read", docs=_WINSVC + "nf-winsvc-closeservicehandle"),
        Call("StartServiceW", "a service started (SERVICE_START)", "Service control",
             docs=_WINSVC + "nf-winsvc-startservicew", writes=True),
        Call("ControlService", "a control sent to a service: stop, pause, continue (SERVICE_STOP ...)",
             "Service control", docs=_WINSVC + "nf-winsvc-controlservice", writes=True),
    ),
    verified=VERIFIED)

SYSTEMD_CTL = Api(
    name=SYSTEMD, maker="The systemd project", kind="command",
    about=("systemctl, systemd's command: the units of a Linux system, their states, their starts, stops and starts at "
           "boot. On Linux the plugin asks it for the jenkins unit's state (systemctl show, a read that ends), and "
           "looks for the unit's file and Jenkins' war file where the jenkins.io packages put them; it starts, stops "
           "and enables nothing. Where systemd does not run (a WSL distribution without it), the state is said as not "
           "known."),
    base="systemctl show jenkins.service --no-pager -p LoadState -p ActiveState -p SubState",
    version="systemctl's show and --property, as every systemd since long ago has them",
    auth="none: any user reads a unit's state (its start and stop are root's)",
    limits="", costs="",
    links=(
        Link("systemctl", _SYSTEMCTL, "reference"),
        Link("Managing systemd services (Jenkins' unit)", _DOC + "system-administration/systemd-services/", "guide"),
    ),
    areas=(
        Area("Unit state", "a unit's properties and states (show, status, is-active)", _SYSTEMCTL,
             covered="the jenkins unit's load, active and sub states (Installed)"),
        Area("Unit control", "a unit started, stopped, restarted, enabled at boot", _SYSTEMCTL),
    ),
    calls=(
        Call("systemctl show jenkins.service", "the unit's properties named by -p: LoadState, ActiveState, SubState",
             "Unit state", used="each read: the jenkins unit's state", docs=_SYSTEMCTL),
        Call("systemctl start jenkins", "the unit started", "Unit control", docs=_SYSTEMCTL, writes=True),
        Call("systemctl stop jenkins", "the unit stopped", "Unit control", docs=_SYSTEMCTL, writes=True),
        Call("systemctl enable jenkins", "the unit started at every boot", "Unit control", docs=_SYSTEMCTL,
             writes=True),
    ),
    verified=VERIFIED)

APIS = (JENKINS, WINDOWS_SCM, SYSTEMD_CTL)
