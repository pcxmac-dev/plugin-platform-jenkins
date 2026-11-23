"""What Jenkins' JSON API answers, read into what the page shows: its jobs (each one's kind, colour, last build and
parameters), its build queue and its nodes, each asked with a tree naming only that (and ROWS rows at most: the
tree's {0,ROWS}). Every field is taken for what Jenkins' javadoc says it is (hudson.model.Job, Run, BallColor,
Queue.Item, Computer, ComputerSet), and one that is not what it should be is left out, never guessed at."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

ROWS = 200  # a list's rows asked of Jenkins at most, and shown
WORDS = 240  # characters kept of a text Jenkins writes (why a build waits, why a node is offline)
JOBS_TREE = ("jobs[name,color,buildable,inQueue,lastBuild[number,result,timestamp,duration,building],"
             f"property[parameterDefinitions[name,type]]]{{0,{ROWS}}},quietingDown")
JOB_TREE = "name,color,buildable,inQueue,property[parameterDefinitions[name,type]]"
QUEUE_TREE = f"items[id,why,inQueueSince,blocked,buildable,stuck,task[name]]{{0,{ROWS}}}"
NODES_TREE = ("busyExecutors,totalExecutors,computer[displayName,offline,temporarilyOffline,offlineCauseReason,"
              f"numExecutors,assignedLabels[name],executors[idle]]{{0,{ROWS}}}")
# a job's colour (hudson.model.BallColor, as the API names it); "_anime" after it: a build of it runs now
COLOURS = {"blue": "succeeded", "red": "failed", "yellow": "unstable", "grey": "pending", "disabled": "disabled",
           "aborted": "aborted", "notbuilt": "not built yet"}
RESULTS = {"SUCCESS": "succeeded", "FAILURE": "failed", "UNSTABLE": "unstable", "ABORTED": "aborted",
           "NOT_BUILT": "not built"}
KINDS = {  # a job's class (its _class), in words
    "hudson.model.FreeStyleProject": "Freestyle project",
    "org.jenkinsci.plugins.workflow.job.WorkflowJob": "Pipeline",
    "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject": "Multibranch Pipeline",
    "com.cloudbees.hudson.plugins.folder.Folder": "Folder",
    "jenkins.branch.OrganizationFolder": "Organization folder",
    "hudson.matrix.MatrixProject": "Multi-configuration project",
    "hudson.maven.MavenModuleSet": "Maven project",
}
WAITING = {"WaitingItem": "in its quiet period", "BlockedItem": "blocked", "BuildableItem": "waiting for an executor",
           "LeftItem": "leaving the queue"}  # a queue item's class (hudson.model.Queue$...), in words


def _text(value, most: int = WORDS) -> str:
    """A text Jenkins wrote, on one line, its control characters left out, cut at `most`."""
    if not isinstance(value, str):
        return ""
    words = " ".join("".join(c if ord(c) >= 32 and ord(c) != 127 else " " for c in value).split())
    return words if len(words) <= most else words[:most - 1].rstrip() + "…"


def _count(value) -> int | None:
    """A whole number that is none below 0, as Jenkins gives one; else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


@dataclass(frozen=True)
class Job:
    """A job as listed: its name, kind, colour (its BallColor without _anime: "" for a folder), whether a build of it
    runs now, can be asked, waits in the queue; its last build's number, result, start and length (milliseconds); and
    its parameters, (name, type) each."""

    name: str
    kind: str = ""
    colour: str = ""
    running: bool = False
    buildable: bool = False
    queued: bool = False
    number: int | None = None
    result: str = ""
    started: int | None = None
    took: int | None = None
    building: bool = False
    parameters: tuple[tuple[str, str], ...] = ()

    @property
    def state(self) -> str:
        """Its colour in words: succeeded, failed, unstable, ...; "–" for a folder, which has none."""
        return COLOURS.get(self.colour, self.colour) if self.colour else "–"

    @property
    def last(self) -> str:
        """Its last build's result in words ("building" while it runs, "" when it has had none)."""
        if self.number is None:
            return ""
        return "building" if self.building else RESULTS.get(self.result, self.result.lower() or "no result")


def parameters_of(row: Mapping) -> tuple[tuple[str, str], ...]:
    """A job's parameters as its ParametersDefinitionProperty lists them: (name, type) each, in order, each once."""
    out: dict[str, str] = {}
    for prop in row.get("property") or ():
        if not isinstance(prop, Mapping):
            continue
        for p in prop.get("parameterDefinitions") or ():
            if isinstance(p, Mapping) and isinstance(p.get("name"), str) and p["name"] and p["name"] not in out:
                out[p["name"]] = str(p.get("type") or "")
    return tuple(out.items())


def job_of(row) -> Job | None:
    """One job of a listing (None: no job's, a row without a name)."""
    if not isinstance(row, Mapping) or not isinstance(row.get("name"), str) or not row["name"].strip():
        return None
    colour = str(row.get("color") or "") if isinstance(row.get("color"), str) else ""
    running = colour.endswith("_anime")
    last = row.get("lastBuild") if isinstance(row.get("lastBuild"), Mapping) else {}
    return Job(name=row["name"].strip(), kind=KINDS.get(str(row.get("_class") or ""), ""),
               colour=colour[:-len("_anime")] if running else colour, running=running,
               buildable=row.get("buildable") is True, queued=row.get("inQueue") is True,
               number=_count(last.get("number")), result=str(last.get("result") or ""),
               started=_count(last.get("timestamp")), took=_count(last.get("duration")),
               building=last.get("building") is True, parameters=parameters_of(row))


def jobs_of(data) -> tuple[Job, ...] | None:
    """The jobs of /api/json, as Jenkins lists them (None: its answer holds no list of jobs)."""
    rows = data.get("jobs") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        return None
    return tuple(j for j in (job_of(r) for r in rows[:ROWS]) if j is not None)


@dataclass(frozen=True)
class Waiting:
    """A build waiting in the queue: its item's id, its job, why it waits (Jenkins' words), since when (milliseconds),
    and its kind of wait in words."""

    id: int | None
    job: str
    why: str = ""
    since: int | None = None
    state: str = ""


def queue_of(data) -> tuple[Waiting, ...] | None:
    """The build queue of /queue/api/json (None: its answer holds no list of items)."""
    rows = data.get("items") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows[:ROWS]:
        if not isinstance(row, Mapping):
            continue
        task = row.get("task") if isinstance(row.get("task"), Mapping) else {}
        kind = str(row.get("_class") or "").rsplit("$", 1)[-1]
        if row.get("stuck") is True:
            state = "stuck: no executor for too long"
        else:
            state = WAITING.get(kind) or ("blocked" if row.get("blocked") is True
                                          else "waiting for an executor" if row.get("buildable") is True else "waiting")
        out.append(Waiting(_count(row.get("id")), _text(task.get("name"), 200) or "(a task)", _text(row.get("why")),
                           _count(row.get("inQueueSince")), state))
    return tuple(out)


@dataclass(frozen=True)
class Node:
    """A node (the built-in one, or an agent): its name, whether it is offline, and taken offline by someone; why
    (Jenkins' words), its executors and how many are busy, its labels but its own name."""

    name: str
    offline: bool = False
    taken: bool = False
    reason: str = ""
    executors: int = 0
    busy: int = 0
    labels: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        return "online" if not self.offline else "taken offline" if self.taken else "offline"


@dataclass(frozen=True)
class Nodes:
    """The nodes of /computer/api/json, and the executors busy and working across them (None: not said)."""

    nodes: tuple[Node, ...]
    busy: int | None = None
    total: int | None = None


def nodes_of(data) -> Nodes | None:
    """The nodes as /computer/api/json lists them (None: its answer holds no list of computers)."""
    rows = data.get("computer") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows[:ROWS]:
        if not isinstance(row, Mapping) or not isinstance(row.get("displayName"), str):
            continue
        name = _text(row["displayName"], 200)
        executors = [e for e in row.get("executors") or () if isinstance(e, Mapping)]
        labels = tuple(dict.fromkeys(_text(x.get("name"), 80) for x in row.get("assignedLabels") or ()
                                     if isinstance(x, Mapping) and isinstance(x.get("name"), str)))
        out.append(Node(name, offline=row.get("offline") is True, taken=row.get("temporarilyOffline") is True,
                        reason=_text(row.get("offlineCauseReason")), executors=_count(row.get("numExecutors")) or 0,
                        busy=sum(1 for e in executors if e.get("idle") is False),
                        labels=tuple(x for x in labels if x and x != name)))
    return Nodes(tuple(out), _count(data.get("busyExecutors")), _count(data.get("totalExecutors")))


# -- times, in words -----------------------------------------------------------------------------------------------
def clock(ms) -> str:
    """A time in milliseconds since 1970 as this machine's local time: 2026-11-22 21:04 ("–" for none)."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "–"


def ago(ms, now: float) -> str:
    """How long before `now` (seconds since 1970) a time in milliseconds was: just now, 5 min ago, 3 h ago, 2 days
    ago."""
    try:
        seconds = float(now) - int(ms) / 1000
    except (TypeError, ValueError, OverflowError):
        return ""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


def took(ms) -> str:
    """A length in milliseconds in words: 42 s, 3 min 5 s, 1 h 2 min."""
    try:
        seconds = int(ms) // 1000
    except (TypeError, ValueError, OverflowError):
        return ""
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s" if seconds else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"
