"""The outside, stood in for: Jenkins as a transport answering as its JSON API does (FakeJenkins), and this machine's
install as finders (FakeFinders). Every request is kept as it was sent, so a test reads what the plugin asked, of
where, with which headers and body."""
from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit

from liminal_libs.apps import EnvironmentLogin
from liminal_libs.machines.endpoint import Reply

from plugin_platform_jenkins import JenkinsPlugin

TOKEN = "11f0c3a9d2b84e67a5c1d0e9f8b7a6c5d4"  # an API token's form (a test's, never a real one)
USER = "alice"
BASE = "http://127.0.0.1:8080"
CRUMB = "5d41402abc4b2a76b9719d911017c592ae2b1e2f9e0c1d2b3a4f5e6d7c8b9a01"
SESSION = "node01x9k2m3n4p5q6.node0"
COOKIE = f"JSESSIONID.4f3e2d1c={SESSION}"
NOW = 1_795_000_000.0  # the wall clock's "now" in these tests (seconds since 1970)
T = int(NOW * 1000)  # the same, in milliseconds


def basic(user: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def jobs() -> list[dict]:
    """The top-level items as /api/json lists them with the plugin's tree."""
    return [
        {"_class": "hudson.model.FreeStyleProject", "name": "app", "color": "blue", "buildable": True, "inQueue": False,
         "lastBuild": {"_class": "hudson.model.FreeStyleBuild", "number": 42, "result": "SUCCESS",
                       "timestamp": T - 3 * 3600_000, "duration": 95_000, "building": False},
         "property": [{"_class": "jenkins.model.BuildDiscarderProperty"}]},
        {"_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob", "name": "deploy", "color": "red_anime",
         "buildable": True, "inQueue": True,
         "lastBuild": {"_class": "org.jenkinsci.plugins.workflow.job.WorkflowRun", "number": 7, "result": None,
                       "timestamp": T - 120_000, "duration": 0, "building": True},
         "property": [{"_class": "hudson.model.ParametersDefinitionProperty", "parameterDefinitions": [
             {"_class": "hudson.model.StringParameterDefinition", "name": "BRANCH",
              "type": "StringParameterDefinition"},
             {"_class": "hudson.model.BooleanParameterDefinition", "name": "DRY_RUN",
              "type": "BooleanParameterDefinition"}]}]},
        {"_class": "hudson.model.FreeStyleProject", "name": "old", "color": "disabled", "buildable": False,
         "inQueue": False, "lastBuild": None, "property": []},
        {"_class": "com.cloudbees.hudson.plugins.folder.Folder", "name": "team"},
        # a Multibranch Pipeline as ComputedFolder exports it: buildable, no colour, no last build (its POST /build
        # schedules a scan of its branches, then answers 302 to its own page)
        {"_class": "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject", "name": "shop",
         "buildable": True},
    ]


QUEUE = {"_class": "hudson.model.Queue", "items": [
    {"_class": "hudson.model.Queue$BuildableItem", "id": 12, "why": "Waiting for next available executor",
     "inQueueSince": T - 60_000, "blocked": False, "buildable": True, "stuck": False,
     "task": {"_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob", "name": "deploy", "fullName": "deploy"}}]}
LOADING = (b"<!DOCTYPE html><html><head><title>Starting Jenkins</title></head><body><h1>Please wait while Jenkins is "
           b"getting ready to work...</h1></body></html>")  # hudson.util.HudsonIsLoading's page: 503, no X-Jenkins
NODES = {"_class": "hudson.model.ComputerSet", "busyExecutors": 1, "totalExecutors": 2, "computer": [
    {"_class": "hudson.model.Hudson$MasterComputer", "displayName": "Built-In Node", "offline": False,
     "temporarilyOffline": False, "offlineCauseReason": "", "numExecutors": 2,
     "assignedLabels": [{"name": "built-in"}, {"name": "Built-In Node"}],
     "executors": [{"idle": False}, {"idle": True}]},
    {"_class": "hudson.slaves.SlaveComputer", "displayName": "linux-agent", "offline": True, "temporarilyOffline": True,
     "offlineCauseReason": "disk full", "numExecutors": 1,
     "assignedLabels": [{"name": "linux"}, {"name": "linux-agent"}], "executors": [{"idle": True}]}]}


def reply(status: int, headers: dict | None = None, body: bytes = b"") -> Reply:
    return Reply(status, headers or {}, [body] if body else [], lambda: None)


class FakeJenkins:
    """Jenkins as a stand-in transport (the library's requests_transport's shape): its version in X-Jenkins on its
    answers (none with `jenkins` False: something else answering), who it lets in (`user` with `token`; anyone with
    `anonymous`), its CSRF protection (`csrf`: a crumb issued, and required of every POST with its session cookie), no
    answer at all (`down`), its loading page while it starts (`starting`: 503 to everything, without X-Jenkins), a
    redirect for everything (`redirect`: its Location), the builds a queue decision of one of its plugins refuses
    (`vetoed`: job names, answered 302 back to the job's own page, as Jenkins' "." is), and every request as sent.

    As Jenkins does: a token it refuses gets 401 with WWW-Authenticate: Basic realm="Jenkins" and no X-Jenkins
    (BasicHeaderProcessor, through Spring's BasicAuthenticationEntryPoint); a request without one, where anonymous reads
    are not let in, 403 with X-Jenkins (HudsonAuthenticationEntryPoint); a build asked again while the same one waits
    in the queue (`waiting`), 303 to its queue item from /buildWithParameters and 201 to it from /build; a multibranch
    project's POST /build a scan (`scans`), then 302 to its own page."""

    def __init__(self, version="2.580.2", user=USER, token=TOKEN, anonymous=False, csrf=True, down=False,
                 redirect=None, jenkins=True, listed=None, queue=None, nodes=None, fail=None, starting=False,
                 vetoed=()):
        self.version, self.user, self.token = version, user, token
        self.anonymous, self.csrf, self.down, self.redirect, self.jenkins = anonymous, csrf, down, redirect, jenkins
        self.starting, self.vetoed = starting, set(vetoed)
        self.listed = jobs() if listed is None else listed
        self.queue = QUEUE if queue is None else queue
        self.nodes = NODES if nodes is None else nodes
        self.fail = dict(fail or {})  # a path -> the status it answers (a failing part)
        self.asked: list[tuple[str, str, dict, bytes | None]] = []
        self.built: list[tuple[str, list]] = []  # (the job's path, its form's pairs), as Jenkins queued them
        self.waiting: dict[tuple, int] = {}  # (the job's path, its form's pairs) -> the queue item it waits as
        self.scans: list[str] = []  # the computed folders a POST /build had scanned

    def paths(self) -> list[tuple[str, str]]:
        return [(m, urlsplit(u).path) for m, u, _, _ in self.asked]

    def __call__(self, method, url, headers, body, timeout, stream):
        self.asked.append((method, url, dict(headers), body))
        if self.down:
            raise ConnectionRefusedError(10061, "No connection could be made: the target machine actively refused it")
        if self.starting:
            return reply(503, {"Content-Type": "text/html;charset=UTF-8", "Cache-Control": "no-cache,no-store"},
                         LOADING)
        h = {"X-Jenkins": self.version, "X-Hudson": "1.395"} if self.jenkins else {"Server": "something-else"}
        if self.redirect:
            return reply(302, {**h, "Location": self.redirect})
        parts = urlsplit(url)
        path = parts.path
        if path in self.fail:
            return reply(self.fail[path], {**h, "Content-Type": "text/html"}, b"<html><body>Oops</body></html>")
        auth = headers.get("Authorization")
        if auth is not None and auth != basic(self.user, self.token):
            challenge = {"WWW-Authenticate": 'Basic realm="Jenkins"'} if self.jenkins else {**h}
            return reply(401, {**challenge, "Content-Type": "text/html;charset=iso-8859-1"},
                         b"<html><body><h2>HTTP ERROR 401 Unauthorized</h2></body></html>")
        if auth is None and not self.anonymous:
            return reply(403, {**h, "Content-Type": "text/html"}, b"<html>Authentication required</html>")
        js = {**h, "Content-Type": "application/json;charset=utf-8"}
        if method == "GET":
            if path == "/api/json":
                return reply(200, js, json.dumps({"_class": "hudson.model.Hudson", "jobs": self.listed,
                                                  "quietingDown": False}).encode())
            if path == "/queue/api/json":
                return reply(200, js, json.dumps(self.queue).encode())
            if path == "/computer/api/json":
                return reply(200, js, json.dumps(self.nodes).encode())
            if path == "/crumbIssuer/api/json":
                if not self.csrf:
                    return reply(404, {**h, "Content-Type": "text/html"}, b"<html>Not Found</html>")
                return reply(200, {**js, "Set-Cookie": f"{COOKIE}; Path=/; HttpOnly"}, json.dumps(
                    {"_class": "hudson.security.csrf.DefaultCrumbIssuer", "crumb": CRUMB,
                     "crumbRequestField": "Jenkins-Crumb"}).encode())
            if path.startswith("/job/") and path.endswith("/api/json"):
                job = self._job(path[:-len("/api/json")])
                if job is None:
                    return reply(404, {**h, "Content-Type": "text/html"}, b"<html>Not Found</html>")
                return reply(200, js, json.dumps({k: v for k, v in job.items() if k != "lastBuild"}).encode())
        if method == "POST":
            if self.csrf and (headers.get("Jenkins-Crumb") != CRUMB or COOKIE not in headers.get("Cookie", "")):
                return reply(403, {**h, "Content-Type": "text/html"},
                             b"<html>Error 403 No valid crumb was included in the request</html>")
            for end in ("/buildWithParameters", "/build"):
                job = self._job(path[:-len(end)]) if path.endswith(end) else None
                if job is None:
                    continue
                page = f"{BASE}{path[:-len(end)]}/"  # Jenkins' "." after the POST: the job's own page
                if not job.get("color"):  # a computed folder: ComputedFolder.doBuild schedules a scan
                    self.scans.append(job["name"])
                    return reply(302, {"Location": page})
                if job["name"] in self.vetoed:  # Queue.schedule2 refused: no item, sendRedirect(".")
                    return reply(302, {"Location": page})
                form = parse_qs((body or b"").decode(), keep_blank_values=True)
                key = (path, tuple(sorted((k, v[0]) for k, v in form.items())))
                if key in self.waiting:  # the same build waits: folded into it (ScheduleResult not created)
                    item = f"/queue/item/{self.waiting[key]}/"
                    return reply(303 if end == "/buildWithParameters" else 201, {"Location": item})
                self.built.append((path, list(key[1])))
                self.waiting[key] = 100 + len(self.built)
                return reply(201, {"Location": f"/queue/item/{100 + len(self.built)}/"})
        return reply(404, {**h, "Content-Type": "text/html"}, b"<html>Not Found</html>")

    def _job(self, path: str) -> dict | None:
        names = [unquote(p) for p in path.split("/job/")[1:]]
        return next((j for j in self.listed if [j["name"]] == names), None)


class FakeFinders:
    """This machine's install, stood in for: its system, its environment variables, the files there, the Windows
    service's or the systemd unit's state and why it could not be asked; every look kept."""

    def __init__(self, system="windows", service="", unit="", files=(), env=None, why=""):
        self._system, self._service, self._unit, self._why = system, service, unit, why
        self._files = set(files)
        self._env = {"ProgramFiles": "C:\\Program Files", "ProgramFiles(x86)": "C:\\Program Files (x86)"} \
            if env is None else env
        self.asked: list[tuple[str, str]] = []

    def system(self):
        return self._system

    def env(self, name):
        return self._env.get(name, "")

    def file(self, path):
        self.asked.append(("file", path))
        return path in self._files

    def windows_service(self, name):
        self.asked.append(("service", name))
        return self._service, self._why

    def systemd_unit(self, name):
        self.asked.append(("unit", name))
        return self._unit, self._why


class Clock:
    """A monotonic clock a test moves on."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


WAR = "C:\\Program Files\\Jenkins\\jenkins.war"


def make(jenkins: FakeJenkins | None = None, finders: FakeFinders | None = None, env: dict | None = None,
         clock: Clock | None = None):
    """A plugin over stand-ins, as the platform lends it a login (an EnvironmentLogin over `env`: alice and her token
    unless given); returns (plugin, jenkins, finders)."""
    j = jenkins if jenkins is not None else FakeJenkins()
    f = finders if finders is not None else FakeFinders(service="running", files=(WAR,))
    p = JenkinsPlugin(finders=f, transport=j, clock=clock or Clock(), wall=lambda: NOW)
    p.login = EnvironmentLogin(env={"JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN} if env is None else env)
    return p, j, f
