"""Jenkins for Liminal: a platform plugin of its Continuous Integration section (the user, 2026-11-22: a new class of
plugins, "Continuous Integration", with Jenkins, GoCD and Buildbot).

It says whether Jenkins is here, installed on this machine (its Windows service or systemd unit, its war file: here.py)
or answering at its address; its version (the X-Jenkins header of its top page and of its .../api/ pages); and, once
Jenkins answers to you, its jobs (each one's state, last build and when), its build queue and its nodes (online or not,
their executors), read through Jenkins' remote access API (client.py: the JSON flavour, one GET each, a tree asking only
what is shown). A job's build is asked from the platform's page alone (PAGE_ONLY_HOOKS), once you have confirmed it
there, with Jenkins' crumb when its CSRF protection issues one. When Jenkins is not here, the page says how to install
it, from Jenkins' own pages: this release installs, starts and stops nothing.

Its settings (settings.py) are read through the plugin's login alone: JENKINS_URL (http://127.0.0.1:8080 unless set),
JENKINS_USER and JENKINS_TOKEN (an API token). The plugin sends the token to JENKINS_URL and nowhere else, over https or
to this machine, and there only once an unsigned first ask was answered as Jenkins answers it (its X-Jenkins header),
and while every answer since has been; it never prints, logs or returns it. (Where the platform's login keeps it today,
as one of your user environment variables, every program you start inherits it: a Jenkins started by hand from such an
environment hands it to its builds, so the page says to start one without it.) Nothing runs on its own: the plugin
reads when the platform asks, keeps what it read READ_S (the page asks every few seconds; a build, Read again and new
settings read anew), holds no thread and no process between asks, and forgets what it read when detached.

    python -m plugin_platform_jenkins status | jobs | build JOB [NAME=value&...]
"""
from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from liminal_libs.machines.plugin import MachinePlugin

from . import apis as cards
from . import here, listing, settings
from .client import (OK, QUEUED, Answer, Jenkins, JenkinsError, Target, challenged, job_path, queued, same_page,
                     version_of)
from .listing import ROWS, ago, clock, took

__version__ = "0.1.0"
READ_S = 30.0  # what was read is kept this long: the platform's page asks every few seconds
READ_WAIT_S = 60.0  # an ask waits this long for another's read under way: more than a read takes at its GETs' bounds
PARAMETERS_MOST = 50  # parameters of one build at most
PARAMETERS_CHARS = 4000  # characters of what is typed for them at most
WITHHELD = ("the API token goes to another machine over https only, and JENKINS_URL is plain http: it was not sent "
            "(an https address signs you in, as Jenkins on this machine does)")
COMPUTED = ("it is a multibranch project or an organization folder, where a POST of its build asks Jenkins to scan its "
            "branches or repositories and builds nothing itself: a job in it is built by its full name, {name}/...")


def cell(text, sub=None):
    return {"text": text, "sub": sub} if sub else text


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def wall_clock(seconds: float) -> str:
    """A time in seconds since 1970 as this machine's local time, to the second."""
    return datetime.fromtimestamp(seconds, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class Reading:
    """One read of Jenkins: when (monotonic, for keeping it; the wall's, for the page), the settings it was read with,
    what was found installed here, whether Jenkins answered (its X-Jenkins header, or its own refusal of the token) and
    its version, the first GET's status (0: no answer came), why Jenkins was not read ("" when its jobs were), whether
    the token went with it, the jobs, the build queue and the nodes as read (None: not read), what of the last two could
    not be read, whether Jenkins is getting ready to shut down, and whether this ask was left waiting for another's read
    (`busy`: READ_WAIT_S)."""

    at: float
    when: float
    target: Target
    found: here.Found
    answered: bool = False
    version: str = ""
    status: int = 0
    why: str = ""
    signed: bool = False
    jobs: tuple | None = None
    queue: tuple | None = None
    nodes: listing.Nodes | None = None
    problems: tuple = ()
    quieting: bool = False
    busy: bool = False

    @property
    def read(self) -> bool:
        """Whether its jobs were read."""
        return self.jobs is not None


class _Runtime:
    """What the plugin keeps while it lives, shared by its copies (the registry hands out a shallow one): the last
    reading, what its requests came to (for api_facts), how the last build met Jenkins' CSRF protection, and the
    address Jenkins answered an unsigned ask at with the version it said (`jenkins`; ("", "") for none): the token goes
    there while every answer since has carried X-Jenkins."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reading_lock = threading.Lock()  # one read at a time: a second asker waits (READ_WAIT_S), then takes it
        self.reading: Reading | None = None
        self.seen = {"requests": 0, "failed": 0, "status": 0, "at": 0.0, "seconds": 0.0, "error": ""}
        self.crumb = ""
        self.jenkins = ("", "")


def parameters_of(text) -> list[tuple[str, str]]:
    """A build's parameters as typed: NAME=value pairs joined by &, as an address's query has them (a value's own & is
    %26, its + %2B), each name once. ValueError in words for what is none."""
    raw = "" if text is None else str(text).strip()
    if not raw:
        return []
    if len(raw) > PARAMETERS_CHARS:
        raise ValueError(f"the parameters are {len(raw):,} characters: {PARAMETERS_CHARS:,} at most")
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("the parameters hold a line break or a control character: type them on one line")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ValueError("parameters are NAME=value pairs joined by & (BRANCH=main&DRY_RUN=true), a value's own & "
                         "typed as %26") from None
    names = [k for k, _ in pairs]
    twice = sorted({k for k in names if names.count(k) > 1})
    if twice:
        raise ValueError(f"a parameter given twice: {', '.join(twice)}")
    if len(pairs) > PARAMETERS_MOST:
        raise ValueError(f"{len(pairs)} parameters: {PARAMETERS_MOST} at most")
    if any(not k.strip() for k in names):
        raise ValueError("a parameter without a name: NAME=value")
    return pairs


class JenkinsPlugin(MachinePlugin):
    """Jenkins for the platform: present when it is installed here or answers at its address, valid while it answers."""

    name = "jenkins"
    title = "Jenkins"
    about = ("Jenkins here or at its address: whether it is installed and runs, its version, and once it answers to "
             "you its jobs, build queue and nodes; a job's build asked once confirmed. How to install it is said, not "
             "done.")
    api = "2.2"
    # what it attaches to (plugin API 2.2): Jenkins' remote access API, and Windows' service control manager or
    # systemd's systemctl for its install (apis.py: each one's pages, parts and calls)
    apis = cards.APIS
    order = 770  # the Continuous Integration plugins in the user's naming: Jenkins 770, GoCD 771, Buildbot 772
    ICON = "jenkins"  # Jenkins' mark, once the library's icons.js draws it (the plug until then)
    SECTION = "ci"  # drawn under the platform's Continuous Integration plugins (Machine's until a platform draws it)
    HOOKS = (*MachinePlugin.HOOKS, "refresh", "build")
    READ_HOOKS = ("refresh",)  # what it says of the interface it shares (the Internal API tab, liminal-libs 1.63.0)
    # a build runs whatever its job says, as JENKINS_USER: asked from the platform's page alone, where you confirm it,
    # never by another plugin (liminal-libs 1.66.0's apps/asking.py; the command line calls it itself)
    PAGE_ONLY_HOOKS = ("build",)
    INTERNAL_NOTES = (
        "A build is asked from its page alone (PAGE_ONLY_HOOKS), once you confirmed it there: another plugin's ask of "
        "it is refused, since a job runs whatever it says as JENKINS_USER.",
        "The API token goes to JENKINS_URL alone, over https or on this machine, and only once an unsigned ask there "
        "was answered as Jenkins answers (X-Jenkins); no answer, table or log holds it.",
        "Jenkins is read at most once every 30 s (Read again, a build and new settings read anew): three GETs of its "
        "JSON API, after one unsigned GET at an address not yet answered as Jenkins; 200 rows of a list at most.",
    )
    keys = settings.KEYS  # its settings, kept through the platform's login

    def __init__(self, finders=None, transport=None, clock=None, wall=None):
        self._finders = finders  # here.Finders: what is installed here (a test's stand-in); the real ones unless given
        self._transport = transport  # (method, url, headers, body, timeout, stream) -> endpoint.Reply: a test's
        self._clock = clock or time.monotonic
        self._wall = wall or time.time
        self._rt = _Runtime()

    # -- reading -------------------------------------------------------------------------------------------------------
    def _client(self, target: Target, anonymous: bool = False) -> Jenkins:
        return Jenkins(target, transport=self._transport, clock=self._clock, note=self._noted, anonymous=anonymous)

    def _noted(self, status: int, seconds: float, error: str) -> None:
        with self._rt.lock:
            s = self._rt.seen
            s["requests"] += 1
            s["failed"] += 1 if error else 0
            s["status"], s["at"], s["seconds"], s["error"] = status, self._wall(), seconds, error

    def _found(self) -> here.Found:
        try:
            return here.look(self._finders)
        except Exception as e:  # noqa: BLE001 - what cannot be looked at is said, never raised
            return here.Found(why=f"this machine could not be looked at: {type(e).__name__}")

    def _read(self, fresh: bool = False) -> Reading:
        """Jenkins as read, kept READ_S (`fresh`: read now). One read at a time: an ask that finds another's under way
        waits for it READ_WAIT_S at most (an answer's status line and headers have no bound of their own: client.py),
        then answers with what was read last (not when `fresh`), else that Jenkins is being read."""
        if not self._rt.reading_lock.acquire(timeout=READ_WAIT_S):
            with self._rt.lock:
                kept = self._rt.reading
            if kept is not None and not fresh:
                return kept
            target = settings.read(self.login)
            return self._reading(target, self._found(), None, busy=True,
                                 why=(f"another ask of Jenkins at {target.base or settings.URL} has waited more than "
                                      f"{READ_WAIT_S:g} s for its answer: what answers there answers too slowly"))
        try:
            with self._rt.lock:
                kept = self._rt.reading
            if kept is not None and not fresh and self._clock() - kept.at < READ_S:
                return kept
            reading = self._look(settings.read(self.login), self._found())
            with self._rt.lock:
                self._rt.reading = reading
            return reading
        finally:
            self._rt.reading_lock.release()

    def _forget(self) -> None:
        """What was read goes, and the hold on its address with it: the next ask reads anew, unsigned first."""
        with self._rt.lock:
            self._rt.reading = None
            self._rt.jenkins = ("", "")

    def _vouched(self, base: str) -> str:
        """The version Jenkins said at `base`, while it is held to answer there (_Runtime.jenkins); "" when it is not,
        and the next ask of `base` goes unsigned."""
        with self._rt.lock:
            at, version = self._rt.jenkins
        return version if base and at == base else ""

    def _doubt(self) -> None:
        """Jenkins is held to answer at no address any more: an answer came without X-Jenkins, or none came."""
        with self._rt.lock:
            self._rt.jenkins = ("", "")

    def _first(self, target: Target) -> tuple[Jenkins, Answer]:
        """An address's first ask, unsigned and as small as there is (listing.FIRST_TREE). Answered with X-Jenkins (a
        200, or Jenkins' 403 to anyone not signed in), Jenkins is held to answer there, and the asks that follow carry
        the token; an answer without it is not Jenkins', and gets no token. JenkinsError for no answer, or for one that
        answers nothing (a redirect, a failure)."""
        p = self._client(target, anonymous=True)
        try:
            got = p.get("/api/json", tree=listing.FIRST_TREE, ok=(200, 401, 403))
        except JenkinsError:
            self._doubt()
            raise
        with self._rt.lock:
            self._rt.jenkins = (target.base, p.version) if p.version else ("", "")
        return p, got

    def _reading(self, target: Target, found: here.Found, j: Jenkins | None, version: str = "", **said) -> Reading:
        return Reading(self._clock(), self._wall(), target, found, version=(j.version if j else "") or version,
                       signed=j.signed if j else False, **said)

    def _look(self, target: Target, found: here.Found) -> Reading:
        """One read: /api/json (the jobs, the version, whether you are let in), then, when the jobs came, the build
        queue and the nodes; each failure kept in words. Where the token is sent, an address Jenkins is not held to
        answer at is asked unsigned first (_first); an answer without X-Jenkins ends the hold (_doubt)."""
        if not target.base:
            return self._reading(target, found, None, why=target.problems[0])
        known = self._vouched(target.base) if target.sends else ""
        if target.sends and not known:
            try:
                p, first = self._first(target)
            except JenkinsError as e:
                return self._reading(target, found, None, e.version, answered=bool(e.version), status=e.status,
                                     why=str(e))
            if not p.version:
                return self._reading(target, found, p, status=first.status,
                                     why=self._not_jenkins(target, first.status, sent=False))
            known = p.version
        j = self._client(target)
        try:
            return self._jobs(target, found, j, known)
        finally:
            if j.unmarked:
                self._doubt()

    def _jobs(self, target: Target, found: here.Found, j: Jenkins, known: str) -> Reading:
        """The read past its first ask: its jobs, then its build queue and its nodes (`known`: the version Jenkins said
        at the address before, for its refusal of the token, which does not say it)."""
        try:
            got = j.get("/api/json", tree=listing.JOBS_TREE, ok=(200, 401, 403))
        except JenkinsError as e:
            return self._reading(target, found, j, answered=bool(e.version), status=e.status, why=str(e))
        if not j.version:
            if j.signed and challenged(got):  # Jenkins' own refusal of the token, which carries no X-Jenkins
                return self._reading(target, found, j, known, answered=True, status=401,
                                     why=self._kept_out(target, j, 401))
            return self._reading(target, found, j, status=got.status,
                                 why=self._not_jenkins(target, got.status, sent=j.signed))
        if got.status != 200:
            return self._reading(target, found, j, answered=True, status=got.status,
                                 why=self._kept_out(target, j, got.status))
        jobs = listing.jobs_of(got.data)
        if jobs is None:
            return self._reading(target, found, j, answered=True, status=200,
                                 why="its answer to GET /api/json holds no list of jobs as Jenkins gives one: not read")
        quieting = isinstance(got.data, Mapping) and got.data.get("quietingDown") is True
        problems, queue, nodes = [], None, None
        try:
            queue = listing.queue_of(j.get("/queue/api/json", tree=listing.QUEUE_TREE).data)
            if queue is None:
                problems.append(("build queue", "its answer holds no list of items as Jenkins gives one"))
        except JenkinsError as e:
            problems.append(("build queue", str(e)))
        try:
            nodes = listing.nodes_of(j.get("/computer/api/json", tree=listing.NODES_TREE).data)
            if nodes is None:
                problems.append(("nodes", "its answer holds no list of computers as Jenkins gives one"))
        except JenkinsError as e:
            problems.append(("nodes", str(e)))
        return self._reading(target, found, j, answered=True, status=200, jobs=jobs, queue=queue, nodes=nodes,
                             problems=tuple(problems), quieting=quieting)

    @staticmethod
    def _not_jenkins(target: Target, status: int, sent: bool) -> str:
        """Why what answers at the address is not taken for Jenkins, in words (`sent`: the token went with the ask)."""
        held = "" if sent or not target.sends else ", and the token was not sent to it"
        return (f"something answers at {target.base} (HTTP {status}), but not as Jenkins does: its answer has no "
                f"X-Jenkins header{held}")

    @staticmethod
    def _kept_out(target: Target, j: Jenkins, status: int) -> str:
        """Why Jenkins answered but did not let you read it (401, 403), in words."""
        if status == 401:
            return (f"Jenkins refused {target.user}'s API token (HTTP 401): make a new one ({settings.TOKEN_PAGE}) and "
                    "set it as JENKINS_TOKEN" if j.signed else "Jenkins asks who you are (HTTP 401)")
        if j.signed:
            return f"{target.user} may not read Jenkins (HTTP 403): the user needs its Overall/Read permission"
        return "not signed in (Jenkins answers HTTP 403 to anyone else)"

    # -- the hooks -----------------------------------------------------------------------------------------------------
    def present(self) -> bool:
        """Whether Jenkins is here: installed on this machine (its service or unit, its war file) or answering at its
        address, as last read (kept READ_S)."""
        try:
            r = self._read()
        except Exception:  # noqa: BLE001 - one that cannot say is not there
            return False
        return r.found.installed or r.answered

    def status(self) -> dict:
        """What Jenkins is here and how it does, for the platform's page: installed here or not, its service's state,
        its address and version, whether you are signed in, and once it answers to you its jobs (each with Build…), its
        build queue and its nodes; how to install it when it is not here. A failure is said in words, never raised."""
        try:
            return self._page(self._read())
        except Exception as e:  # noqa: BLE001 - a page that cannot be made says why
            return {"present": False, "summary": "Jenkins could not be read", "valid": False,
                    "why": f"the plugin failed: {type(e).__name__}", "tables": [], "forms": []}

    def refresh(self) -> dict:
        """Jenkins read again now (what was read is kept READ_S otherwise)."""
        r = self._read(fresh=True)
        base = r.target.base or settings.URL
        if r.read:
            said = f"{self._named(r)} read at {base} now: {plural(len(r.jobs), 'job')}"
        elif r.answered:
            said = f"{self._named(r)} answers at {base}, but was not read: {self._short(r)[0]}"
        elif r.busy:
            said = f"Jenkins at {base} is being read by another ask, which still waits for its answer"
        elif r.status == 503:
            said = f"Jenkins at {base} is starting or restarting (HTTP 503)"
        else:
            said = f"Jenkins does not answer at {base}"
        lines = [r.why] if r.why else []
        lines += [f"its {what} could not be read: {why}" for what, why in r.problems]
        return {"said": said, "ok": r.answered, "lines": lines + [f"this machine: {r.found.words()}"]}

    def build(self, job, parameters=None, at=None) -> dict:
        """A job's build asked of Jenkins: POST /job/NAME/build, or /buildWithParameters for a job with parameters
        (their defaults unless given, as NAME=value pairs joined by &), with Jenkins' crumb when its CSRF protection
        issues one. The platform's page asks it once you have confirmed it, and it alone (PAGE_ONLY_HOOKS); `at` is
        where and as whom the page named (its form's), and the settings must still name it. Refused before anything
        changes for a job that is not there or cannot be built (a multibranch project's or an organization folder's
        build would be a scan), for a parameter the job does not have, and where what answers is not Jenkins. Jenkins'
        answer is said: the build queued, the same build already waiting (303), or none queued (302 back to the job)."""
        path = job_path(job)
        name = str(job).strip().strip("/")
        given = parameters_of(parameters)
        target = settings.read(self.login)
        if not target.base:
            raise ValueError(target.problems[0])
        if target.withheld:
            raise ValueError(f"{WITHHELD}: no build is asked as no one")
        if at is not None and str(at) != self._confirmed(target):
            raise ValueError(f"the settings changed since the page asked you (they name Jenkins at "
                             f"{self._confirmed(target)} now): no build was asked; read again, then ask it anew")
        try:
            if target.sends and not self._vouched(target.base):
                p, first = self._first(target)
                if not p.version:
                    raise ValueError(f"{self._not_jenkins(target, first.status, sent=False)}: no build was asked")
            j = self._client(target)
            try:
                done, crumb, known = self._asked(j, path, name, given)
            finally:
                if j.unmarked:
                    self._doubt()
        except JenkinsError:
            self._forget()
            raise
        with self._rt.lock:
            self._rt.crumb = crumb
            self._rt.reading = None  # the queue changed: read anew at the page's next ask
        lines = [f"at {target.base}" + (f", as {target.user}" if j.signed else ", as no one (no token set)")]
        if known:
            typed = [k for k, _ in given]
            lines.append(f"with {', '.join(typed)} as typed, the rest their defaults" if typed
                         else "with its parameters' defaults")
        lines.append(crumb)
        if done.status == 302:  # back to the job's own page (ask's `lands`): Jenkins put nothing in its queue
            return {"said": f"Jenkins did not queue a build of {name}: a queue decision of one of its plugins refused "
                            "it", "ok": False, "lines": lines}
        item = queued(done)
        number = f" (queue item {item})" if item is not None else ""
        if done.status == 303:  # the same build already waits: Jenkins folded this ask into it
            return {"said": f"the same build of {name} already waits in the queue{number}: Jenkins queued no second "
                            "one", "ok": True, "lines": lines}
        return {"said": f"a build of {name} is queued{number}", "ok": True, "lines": lines}

    def _asked(self, j: Jenkins, path: str, name: str, given: list) -> tuple[Answer, str, list]:
        """The job looked at, then its build asked: (Jenkins' answer, the crumb in words, the job's parameters'
        names). ValueError before anything changes for what is not built (build)."""
        got = j.get(path + "/api/json", tree=listing.JOB_TREE, ok=(200, 404))
        if got.status == 404:
            raise ValueError(f"Jenkins at {j.target.base} has no job {name}")
        if not version_of(got):  # what answered is not Jenkins: nothing more goes to it
            raise ValueError(f"{self._not_jenkins(j.target, got.status, sent=j.signed)}: no build was asked")
        row = got.data if isinstance(got.data, Mapping) else {}
        colour = row.get("color") if isinstance(row.get("color"), str) else ""
        if row.get("buildable") is not True or not colour:
            why = ("it is disabled" if colour.startswith("disabled")
                   else COMPUTED.format(name=name) if row.get("buildable") is True  # buildable, no colour: computed
                   else "it is not a job a build is asked of (a folder, say)" if "buildable" not in row
                   else "Jenkins says it cannot be built now")
            raise ValueError(f"{name} is not built: {why}")
        known = [p for p, _ in listing.parameters_of(row)]
        if given and not known:
            raise ValueError(f"{name} takes no parameters: it is built without them")
        unknown = [k for k, _ in given if k not in known]
        if unknown:
            raise ValueError(f"{name} has no parameter {', '.join(unknown)}: its parameters are {', '.join(known)}")
        page = j.url(path)  # the job's own page, where Jenkins sends a build it did not queue

        def lands(status: int, where: str) -> bool:
            """A build's redirect taken as its answer: a 303 to the queue item it joined, a 302 back to the job."""
            if status == 303:
                return QUEUED.search(urlsplit(where).path) is not None
            return status == 302 and same_page(where, page)

        done, crumb = j.post(path + ("/buildWithParameters" if known else "/build"), form=given if known else None,
                             ok=(*OK, 302, 303), lands=lands)
        return done, crumb, known

    def settings_changed(self) -> None:
        """Its settings were just entered (the platform's Settings…, kept through the login): read anew at once, the
        address asked unsigned first."""
        self._forget()

    def detach(self) -> None:
        """Detached (the platform ending, the plugin turned off): what it read and learned goes; nothing of its own was
        running."""
        with self._rt.lock:
            self._rt.reading = None
            self._rt.crumb = ""
            self._rt.jenkins = ("", "")
            self._rt.seen = {"requests": 0, "failed": 0, "status": 0, "at": 0.0, "seconds": 0.0, "error": ""}
        super().detach()

    def api_facts(self) -> dict:
        """What it learned of its APIs while it ran, asking nothing (plugin API 2.2): Jenkins' address, version and
        whether you were signed in, as last read; its requests and their last answer; whether its CSRF protection
        issued a crumb at the last build; and what the last read found installed here. Nothing read yet: {}."""
        with self._rt.lock:
            r, seen, crumb = self._rt.reading, dict(self._rt.seen), self._rt.crumb
        out: dict[str, dict[str, str]] = {}
        facts: dict[str, str] = {}
        if r is not None:
            facts["Address"] = r.target.base or "none: " + (r.target.problems[0] if r.target.problems else "")
            facts["Read"] = f"{wall_clock(r.when)} (kept {READ_S:g} s)"
            if r.version:
                facts["Version"] = f"{r.version} (its X-Jenkins header)"
            facts["Signed in"] = self._signed(r)
        if seen["requests"]:
            failed = f", {seen['failed']:,} failed" if seen["failed"] else ""
            facts["Requests"] = f"{seen['requests']:,} made{failed}"
            facts["Last answer"] = ((f"HTTP {seen['status']} in {seen['seconds'] * 1000:.0f} ms" if seen["status"]
                                     else "none (no connection)") + f", {wall_clock(seen['at'])}")
            if seen["error"]:
                facts["Last trouble"] = seen["error"][:200]
        if crumb:
            facts["CSRF protection"] = f"at the last build: {crumb}"
        if facts:
            out[cards.REMOTE] = facts
        if r is not None and r.found.looked:
            installed = {"Installed": r.found.words()}
            if r.found.why:
                installed["Not looked at"] = r.found.why
            out[cards.SCM if r.found.system == "windows" else cards.SYSTEMD] = installed
        return out

    # -- what the platform's page draws -------------------------------------------------------------------------------
    def _page(self, r: Reading) -> dict:
        summary, why, problem = self._said(r)
        out: dict = {"present": r.found.installed or r.answered, "summary": summary, "valid": r.answered,
                     "why": "" if r.answered else why}
        out.update(self._facts(r))
        out["tables"] = self._tables(r)
        buildable = [j for j in r.jobs or () if j.buildable]
        out["forms"] = [self._build_form(r, buildable)] if buildable else []
        out["actions"] = [{"hook": "refresh", "args": [], "title": "Read again",
                           "note": f"asks Jenkins again now (what was read is kept {READ_S:g} s)"}]
        if problem:
            out["problem"] = problem
        return out

    @staticmethod
    def _named(r: Reading) -> str:
        """Jenkins by its version when an answer said it: Jenkins 2.580.2, else Jenkins."""
        return f"Jenkins {r.version}" if r.version else "Jenkins"

    def _said(self, r: Reading) -> tuple[str, str, str]:
        """The page's summary, why it is not valid ("" when it is), and its trouble ("" for none)."""
        t, f = r.target, r.found
        noted = list(t.problems)
        if not t.base:
            return f"{settings.URL} is not an address Jenkins is asked at", t.problems[0], ""
        if r.busy:
            return f"Jenkins at {t.base} is being read", "; ".join([r.why] + noted), ""
        if not r.answered:
            if r.status == 503:  # Jenkins' own page while it loads, which carries no X-Jenkins: no other port to try
                return (f"Jenkins at {t.base} is starting or restarting (HTTP 503)",
                        "; ".join([r.why.rstrip(". ")] + noted), "")
            if f.installed:
                summary = f"Jenkins is installed here, but does not answer at {t.base}"
                why = f"Jenkins does not answer at {t.base}: {r.why}. {self._start_words(f)}"
            elif f.looked:
                summary = f"Jenkins is not installed here, and nothing answers at {t.base}"
                why = (f"Jenkins is not installed here, and does not answer at {t.base} ({r.why}): install it (the "
                       "table below says how), or set JENKINS_URL to where it runs")
            else:
                summary = f"Jenkins does not answer at {t.base}"
                why = f"{r.why}: set JENKINS_URL to where Jenkins runs"
            return summary, "; ".join([why.rstrip(". ")] + noted), ""
        head = f"{self._named(r)} at {t.base}"
        if not r.read:
            short, trouble = self._short(r)
            return f"{head} · {short}", "", "; ".join(([r.why] if trouble else []) + noted)
        parts = [head, self._jobs_words(r.jobs)]
        if r.queue is not None:
            parts.append(f"{len(r.queue)} waiting" if r.queue else "nothing waiting")
        if r.nodes is not None:
            online = sum(1 for n in r.nodes.nodes if not n.offline)
            parts.append(f"{online} of {plural(len(r.nodes.nodes), 'node')} online")
        if r.quieting:
            parts.append("getting ready to shut down: no new build starts")
        unread = [f"its {what} could not be read: {why}" for what, why in r.problems]
        return " · ".join(parts), "", "; ".join(unread + noted)

    @staticmethod
    def _short(r: Reading) -> tuple[str, bool]:
        """Why Jenkins was not read, in a few words, and whether that is trouble (not merely being signed out)."""
        if r.status == 401:
            return ("JENKINS_USER's API token was refused" if r.signed else "it asks who you are"), True
        if r.status == 403:
            return (f"{r.target.user} may not read it", True) if r.signed else ("not signed in", False)
        return "not read", True

    @staticmethod
    def _jobs_words(jobs) -> str:
        if not jobs:
            return "no job yet"
        running = sum(1 for j in jobs if j.running or j.building)
        failing = sum(1 for j in jobs if j.colour == "red")
        more = ", ".join(x for x in (f"{running} building" if running else "",
                                     f"{failing} failing" if failing else "") if x)
        return plural(len(jobs), "job") + (f" ({more})" if more else "")

    @staticmethod
    def _start_words(f: here.Found) -> str:
        """What to do when Jenkins is installed here and does not answer, in words, by its service's or its unit's
        state (this plugin starts nothing)."""
        state = f.state.split(" ", 1)[0]
        if f.system == "windows":
            if not f.service:
                return (f"Its war file is here, but not its service: run it with java -jar jenkins.war (Java 21 or "
                        f"later) {here.WAR_ALONE}, or install the service with Jenkins' Windows installer")
            if state == "running":
                return ("Its service runs: it may answer at another port (the --httpPort in jenkins.xml, in its "
                        "install folder); set JENKINS_URL to it")
            if f.state == "not known":
                return f"Its service's state is not known: {f.why}"
            if state in ("starting", "continuing"):
                return f"Its service is {f.state}: wait for it (Jenkins answers some seconds after its service starts)"
            if state in ("pausing", "paused"):
                return (f"Its service is {f.state}: resume it from the Services app, or with Resume-Service jenkins in "
                        "an administrator's PowerShell (this plugin starts nothing)")
            if state == "stopping":
                return ("Its service is stopping: once it has stopped, start it from the Services app, or with "
                        "Start-Service jenkins in an administrator's PowerShell (this plugin starts nothing)")
            return (f"Its service is {f.state}: start it from the Services app, or with Start-Service jenkins in an "
                    "administrator's PowerShell (this plugin starts nothing)")
        if f.system == "linux":
            if not f.state:
                return (f"Its unit's state is not known ({f.why}); in a WSL distribution, systemd runs once "
                        "/etc/wsl.conf says [boot] systemd=true" if f.service else
                        f"Its war file is here, but no unit: run it with java -jar jenkins.war (Java 21 or later) "
                        f"{here.WAR_ALONE}")
            if state == "running":
                return ("Its unit runs: it may answer at another port (JENKINS_PORT, which systemctl cat jenkins "
                        "shows); set JENKINS_URL to it")
            if f.state == here.MASKED:
                return ("Its unit is masked, so systemctl will not start it: sudo systemctl unmask jenkins first, then "
                        "sudo systemctl start jenkins (this plugin starts nothing)")
            if f.state == here.RESTARTING:
                return ("Its unit is restarting after a failure, and systemd starts it again: journalctl -u jenkins "
                        "says why it fails")
            if state == "failed":
                return ("Its unit failed: journalctl -u jenkins says why; once that is put right, sudo systemctl start "
                        "jenkins starts it (this plugin starts nothing)")
            if state in ("starting", "reloading"):
                return f"Its unit is {f.state}: wait for it (Jenkins answers some seconds after its unit starts)"
            if state == "stopping":
                return ("Its unit is stopping: once it has stopped, start it with sudo systemctl start jenkins (this "
                        "plugin starts nothing)")
            return f"Its unit is {f.state}: start it with sudo systemctl start jenkins (this plugin starts nothing)"
        return ""

    def _signed(self, r: Reading) -> str:
        """Whether you were signed in, in words."""
        t = r.target
        if r.signed:
            if r.status == 401:
                return f"no: Jenkins refused {t.user}'s API token"
            if r.status == 403:
                return f"as {t.user}, who may not read Jenkins"
            return f"as {t.user}" if r.answered else f"as {t.user}, once Jenkins answers"
        if t.sends:  # set, and held back: nothing answered an unsigned ask at the address as Jenkins does
            return (f"not yet: {t.user}'s API token goes to {t.base} once Jenkins has answered an unsigned ask there "
                    "(its X-Jenkins header)")
        return "no: " + self._sign_in(t) + (" (Jenkins lets anyone read it)" if r.read else "")

    @staticmethod
    def _sign_in(t: Target) -> str:
        """How you sign in, given the settings as they are."""
        if t.withheld:
            return WITHHELD
        if t.user and not t.token:
            return f"JENKINS_TOKEN is not set: an API token of {t.user} ({settings.TOKEN_PAGE})"
        if t.token and not t.user:
            return "JENKINS_USER is not set: the user ID the API token belongs to"
        return "JENKINS_USER and JENKINS_TOKEN are not set (Settings, above): your user ID and an API token of it"

    @staticmethod
    def _confirmed(t: Target) -> str:
        """Where a build is asked and as whom, as the page's confirmation names it (the form's `at`): build holds the
        settings to it."""
        return f"{t.base}, as {t.user if t.sends else 'no one'}"

    def _facts(self, r: Reading) -> dict:
        out: dict = {"address": r.target.base or "not set", "installed": r.found.words()}
        if r.answered:
            out["version"] = r.version or "not said yet"
        out["signedIn"] = self._signed(r)
        if r.jobs is not None:
            out["jobs"] = self._jobs_words(r.jobs)
        if r.queue is not None:
            out["queue"] = f"{len(r.queue)} waiting"
        if r.nodes is not None:
            n = r.nodes
            online = sum(1 for x in n.nodes if not x.offline)
            out["nodes"] = f"{online} of {len(n.nodes)} online" + (
                f" · {n.busy} of {n.total} executors busy" if n.busy is not None and n.total is not None else "")
        out["readAt"] = f"{wall_clock(r.when)} (kept {READ_S:g} s; Read again asks now)"
        return out

    def _tables(self, r: Reading) -> list[dict]:
        if not r.answered:
            if r.target.base and not r.found.installed and not r.busy and r.status != 503:
                return [{"title": "How to install Jenkins", "rows": here.install_rows(r.found.system),
                         "columns": [{"title": "Step"}, {"title": "How"}],
                         "note": ("Jenkins' own steps, from jenkins.io (read 2026-11-22): this plugin installs, starts "
                                  "and stops nothing. Once Jenkins answers at its address, this page reads it."),
                         "empty": ""}]
            return []
        on = f"at {r.target.base}"
        if not r.read:
            signed_out = self._short(r) == ("not signed in", False)
            empty = f"Not read: not signed in. {self._sign_in(r.target)}." if signed_out else f"Not read: {r.why}"
            return [{"title": "Jobs", "note": on, "columns": [{"title": "Job"}], "rows": [], "empty": empty}]
        out = [self._jobs_table(r, on)]
        problems = dict(r.problems)
        out.append(self._queue_table(r, on, problems.get("build queue")))
        out.append(self._nodes_table(r, on, problems.get("nodes")))
        return out

    def _jobs_table(self, r: Reading, on: str) -> dict:
        now = self._wall()
        rows = []
        for j in r.jobs:
            last = cell(f"#{j.number}", j.last or None) if j.number is not None else "–"
            length = took(j.took) if j.took and not j.building else ""
            since = " · ".join(x for x in (length, ago(j.started, now)) if x)
            when = cell(clock(j.started), since) if j.started else "–"
            if j.buildable:
                button = {"form": "build", "title": "Build…", "values": {"job": j.name}, "label": f"Build {j.name}"}
            else:
                button = cell("–", "disabled" if j.colour == "disabled" else "scanned by Jenkins, not built"
                              if j.computed else "not a job to build" if not j.colour else "cannot be built now")
            state_sub = "building now" if j.running else "in the queue" if j.queued else None
            rows.append([cell(j.name, j.kind or None), cell(j.state, state_sub), last, when, button])
        note = on + (f" · the first {ROWS}" if len(r.jobs) >= ROWS else "") + " · a folder's jobs are not listed yet"
        table = {"title": "Jobs", "note": note, "rows": rows,
                 "columns": [{"title": "Job"}, {"title": "State"}, {"title": "Last build", "num": True},
                             {"title": "When"}, {"title": "Build"}],
                 "empty": "No job in Jenkins yet: make one on its page (New Item)."}
        if any(j.buildable for j in r.jobs):
            table["actions"] = [{"form": "build", "title": "Build a job…"}]
        return table

    def _queue_table(self, r: Reading, on: str, problem: str | None) -> dict:
        now = self._wall()
        rows = [[cell(w.job, f"item {w.id}" if w.id is not None else None),
                 cell(clock(w.since), ago(w.since, now)) if w.since else "–", w.why or "–", w.state]
                for w in r.queue or ()]
        return {"title": "Build queue", "note": on, "rows": rows,
                "columns": [{"title": "Job"}, {"title": "Waiting since"}, {"title": "Why"}, {"title": "State"}],
                "empty": f"Not read: {problem}" if problem else "Nothing waits: every build asked has started."}

    def _nodes_table(self, r: Reading, on: str, problem: str | None) -> dict:
        n = r.nodes
        rows = [[cell(x.name, ", ".join(x.labels[:6]) or None), cell(x.state, x.reason or None),
                 cell(f"{x.busy} of {x.executors} busy" if x.executors else "none")]
                for x in (n.nodes if n is not None else ())]
        note = on + (f" · {n.busy} of {n.total} executors busy" if n is not None and n.busy is not None
                     and n.total is not None else "")
        return {"title": "Nodes", "note": note, "rows": rows,
                "columns": [{"title": "Node"}, {"title": "State"}, {"title": "Executors", "num": True}],
                "empty": f"Not read: {problem}" if problem else "No node: Jenkins lists none."}

    def _build_form(self, r: Reading, jobs: list) -> dict:
        """The build's form (liminal-platform's status.forms): the job picked, its parameters typed for one that has
        some, and where and as whom it is asked (`at`, fixed: build holds the settings to it); asked once confirmed.
        The fields are build's arguments in order, so the parameters' field is always there, shown only for a job
        that has some."""
        takes = [j.name for j in jobs if j.parameters]
        fields: list[dict] = [{
            "name": "job", "label": "Job", "type": "choice", "value": jobs[0].name,
            "choices": [{"value": j.name, "title": j.name,
                         "note": " · ".join(x for x in (j.kind, j.state, "parameters: " + ", ".join(p for p, _ in
                                                                                                 j.parameters)
                                                        if j.parameters else "") if x)} for j in jobs]}]
        fields.append({"name": "parameters", "label": "Parameters", "type": "text", "when": {"job": takes},
                       "placeholder": "BRANCH=main&DRY_RUN=true",
                       "note": ("its parameters' defaults unless typed here: NAME=value pairs joined by &, as an "
                                "address's query has them (a value's own & as %26); what is typed shows on the "
                                "next step, so a password parameter is best left to its default")})
        fields.append({"name": "at", "label": "Jenkins", "type": "fixed", "value": self._confirmed(r.target)})
        who = f" as {r.target.user}" if r.signed else ""
        return {"id": "build", "hook": "build", "title": "Build a job", "submit": "Review", "fields": fields,
                "note": f"Jenkins at {r.target.base} queues the build, and starts it on the first free executor.",
                "confirm": {"title": "Build {job}?",
                            "words": (f"Jenkins at {r.target.base} queues a build of {{job}}{who}. It runs what the "
                                      "job says (its steps, and whatever they change), on the first free executor."),
                            "yes": "Build"}}


MACHINE = JenkinsPlugin()
