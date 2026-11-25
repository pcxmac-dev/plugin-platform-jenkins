"""Jenkins on the platform's page, over stand-ins (stand_ins.py): present on each system, the status when Jenkins is
not here, installed but not answering, starting, answering to no one, refusing the token, and read (its jobs, build
queue and nodes as tables, its version from X-Jenkins); a redirect refused; the token sent only once Jenkins answered
an unsigned ask at its address, and never in any answer, table or fact; a build confirmed by the page and asked with
the crumb, its parameters checked first, held to the address and user the page named, never a multibranch project's
scan, and Jenkins' answer said (queued, already waiting, not queued); what is kept and when it is read anew; the
command line."""
from __future__ import annotations

import json
import threading

import pytest

import plugin_platform_jenkins as jk
import plugin_platform_jenkins.__main__ as cli
from plugin_platform_jenkins import READ_S, JenkinsPlugin
from plugin_platform_jenkins.client import JenkinsError
from stand_ins import (BASE, CRUMB, NOW, SESSION, TOKEN, USER, WAR, Clock, FakeFinders, FakeJenkins, basic, make,
                       reply)

SECRETS = (TOKEN, basic(USER, TOKEN), basic(USER, TOKEN)[6:], CRUMB, SESSION)
REMOTE = {"JENKINS_URL": "https://ci.example.com", "JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN}


def no_secret(*things) -> None:
    """None of the secrets in anything said: a status, an answer, the facts, an error's words."""
    text = json.dumps(things, default=str)
    for s in SECRETS:
        assert s not in text


def table(status: dict, title: str) -> dict:
    return next(t for t in status["tables"] if t["title"] == title)


def texts(row) -> list[str]:
    return [c.get("text", c.get("title", "")) if isinstance(c, dict) else c for c in row]


def signed(j: FakeJenkins) -> list[bool]:
    """Which of the requests Jenkins (or what stands at its address) got carried the token."""
    return [h.get("Authorization") == basic(USER, TOKEN) for _, _, h, _ in j.asked]


# -- present, on each system ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("finders, installed", [
    (FakeFinders(system="windows", service="stopped"), True),
    (FakeFinders(system="windows", files=(WAR,)), True),
    (FakeFinders(system="windows"), False),
    (FakeFinders(system="linux", unit="failed"), True),
    (FakeFinders(system="linux", files=("/usr/share/java/jenkins.war",)), True),
    (FakeFinders(system="linux", why="systemctl is not here: this system does not run systemd"), False),
    (FakeFinders(system="darwin"), False),
])
def test_present_is_installed_here_or_answering(finders, installed):
    p, _, _ = make(FakeJenkins(down=True), finders)
    assert p.present() is installed
    p, _, _ = make(FakeJenkins(), finders)
    assert p.present() is True  # answering at its address, wherever it is installed


# -- the status ----------------------------------------------------------------------------------------------------
def test_not_here_says_how_to_install_it():
    p, j, _ = make(FakeJenkins(down=True), FakeFinders(system="windows"))
    s = p.status()
    assert s["present"] is False and s["valid"] is True and s["why"] == ""  # 0.2.0: it can be placed in a container
    assert s["summary"] == f"Jenkins is not installed here, and nothing answers at {BASE}"
    assert "nothing listens at 127.0.0.1:8080" in s["note"] and "Install… it in a container (below)" in s["note"]
    assert "install it yourself (jenkins.io/download)" in s["note"] and s["tables"] == []  # no native install table
    assert s["forms"] == [] and s["installed"] == "not installed here" and len(j.asked) == 1
    no_secret(s)


def test_installed_but_not_answering_says_what_to_do():
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="windows", service="stopped", files=(WAR,)))
    s = p.status()
    assert s["present"] is True and s["valid"] is True and s["tables"] == []
    assert s["summary"] == f"Jenkins is installed here, but does not answer at {BASE}"
    assert "Its service is stopped: start it from the Services app" in s["note"] and "starts nothing" in s["note"]
    assert s["installed"] == f"the Windows service jenkins (stopped) · its war file {WAR}"
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="windows", service="running"))
    assert "it may answer at another port" in p.status()["note"]
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="linux", unit="failed"))
    assert "Its unit failed: journalctl -u jenkins says why" in p.status()["note"]


def test_a_war_file_alone_is_run_without_the_plugins_settings():
    """A Jenkins started by hand from an environment that holds the token hands it to every build on its built-in node:
    where the page says to run the war file, it says to run it where JENKINS_USER and JENKINS_TOKEN are not set."""
    for finders in (FakeFinders(system="windows", files=(WAR,)),
                    FakeFinders(system="linux", files=("/usr/share/java/jenkins.war",))):
        p, _, _ = make(FakeJenkins(down=True), finders)
        why = p.status()["note"]
        assert "java -jar jenkins.war" in why and "in a shell where JENKINS_USER and JENKINS_TOKEN are not set" in why


def test_while_jenkins_starts_it_is_said_so():
    """Jenkins' loading page answers 503 to everything, without X-Jenkins: said as starting or restarting, never as a
    failure, and with no advice of another port, nor how to install it."""
    p, j, _ = make(FakeJenkins(starting=True), FakeFinders(system="windows", service="running", files=(WAR,)))
    s = p.status()
    assert s["valid"] is True and s["summary"] == f"Jenkins at {BASE} is starting or restarting (HTTP 503)"
    assert "HTTP 503: Jenkins is starting or restarting, and answers once it is ready" in s["note"]
    assert "failed" not in s["why"] and "another port" not in s["why"] and s["tables"] == []
    assert p.refresh()["said"] == f"Jenkins at {BASE} is starting or restarting (HTTP 503)"
    assert not any(signed(j))  # its page is no Jenkins' answer: the token waits
    p, _, _ = make(FakeJenkins(starting=True), FakeFinders(system="windows"), env=dict(REMOTE))
    s = p.status()
    assert s["summary"] == "Jenkins at https://ci.example.com is starting or restarting (HTTP 503)"
    assert s["tables"] == []  # no table of how to install it: something answers there


def test_something_else_answering_is_not_jenkins():
    p, _, _ = make(FakeJenkins(jenkins=False, anonymous=True))
    s = p.status()
    assert s["valid"] is True and "not as Jenkins does: its answer has no X-Jenkins header" in s["note"]
    assert "the token was not sent to it" in s["note"]
    assert s["signedIn"].startswith("not yet: alice's API token goes to")


def test_the_token_goes_only_where_jenkins_answered_an_unsigned_ask():
    """A first ask of an address goes unsigned; the token goes with the asks after it once that answer carried
    X-Jenkins, and never to what answers without it: before, after Read again, after READ_S, nor with a build."""
    clock = Clock()
    p, j, _ = make(FakeJenkins(jenkins=False, anonymous=True), FakeFinders(system="windows", service="stopped"),
                   clock=clock)
    p.status()
    p.present()
    p.refresh()
    clock.now += READ_S + 1
    p.status()
    with pytest.raises(ValueError, match="not as Jenkins does.*no build was asked"):
        p.build("app")
    assert len(j.asked) == 4 and not any(signed(j)) and not any(m == "POST" for m, _ in j.paths())
    # Jenkins: unsigned once, then signed
    p, j, _ = make()
    p.status()
    assert signed(j) == [False, True, True, True] and j.paths()[0] == ("GET", "/api/json")
    assert "tree=quietingDown" in j.asked[0][1]


def test_the_hold_on_an_address_ends_with_an_answer_without_x_jenkins():
    """Jenkins answered at its address, then something else holds it: its first answer without X-Jenkins ends the
    hold, and every ask after it goes unsigned again until Jenkins answers there."""
    clock = Clock()
    fake = FakeJenkins()
    p, j, _ = make(fake, clock=clock)
    p.status()
    assert signed(j) == [False, True, True, True]
    fake.jenkins, fake.anonymous = False, True  # Jenkins stopped; something else answers at its port
    p.refresh()
    assert signed(j)[4:] == [True]  # held until then: one GET, and no more, reaches what is not Jenkins
    assert p.status()["valid"] is True
    p.refresh()
    clock.now += READ_S + 1
    p.status()
    assert len(j.asked) == 7 and not any(signed(j)[5:])  # unsigned from then on
    fake.jenkins, fake.anonymous = True, False  # Jenkins answers there again
    p.refresh()
    assert signed(j)[-4:] == [False, True, True, True]


def test_no_answer_ends_the_hold_too():
    clock = Clock()
    fake = FakeJenkins()
    p, j, _ = make(fake, clock=clock)
    p.status()
    fake.down = True  # Jenkins stopped: nothing listens
    p.refresh()
    fake.down, fake.jenkins, fake.anonymous = False, False, True  # then something else listens at its port
    p.refresh()
    assert signed(j)[-1] is False and p.status()["valid"] is True


def test_reachable_without_a_token_it_says_how_to_sign_in():
    p, j, _ = make(env={})
    s = p.status()
    assert s["valid"] is True and s["present"] is True and s["version"] == "2.580.2"
    assert s["summary"] == f"Jenkins 2.580.2 at {BASE} · not signed in" and "problem" not in s
    assert s["signedIn"].startswith("no: JENKINS_USER and JENKINS_TOKEN are not set")
    jobs = table(s, "Jobs")
    assert jobs["rows"] == [] and jobs["empty"].startswith("Not read: not signed in. JENKINS_USER and JENKINS_TOKEN")
    assert [t["title"] for t in s["tables"]] == ["Jobs"] and s["forms"] == []
    assert "Authorization" not in j.asked[0][2] and len(j.asked) == 1  # one GET: nothing more is read signed out


def test_a_user_without_a_token_and_a_token_kept_from_plain_http():
    p, _, _ = make(env={"JENKINS_USER": USER})
    assert p.status()["signedIn"].startswith("no: JENKINS_TOKEN is not set: an API token of alice")
    p, j, _ = make(env={"JENKINS_URL": "http://ci.lan:8080", "JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN})
    s = p.status()
    assert s["valid"] is True and "goes to another machine over https only" in s["signedIn"]
    assert all("Authorization" not in h for _, _, h, _ in j.asked) and j.asked[0][1].startswith("http://ci.lan:8080/")
    with pytest.raises(ValueError, match="no build is asked as no one"):
        p.build("app")
    assert len(j.asked) == 1  # refused before anything was sent


def test_a_refused_token_is_trouble_in_words():
    """Jenkins refuses a token with 401 and its Basic realm "Jenkins", without X-Jenkins: Jenkins answered, and the
    page says the token was refused, on this machine or another, never that Jenkins is not there."""
    p, _, _ = make(FakeJenkins(token="another"))
    s = p.status()
    assert s["valid"] is True and s["present"] is True
    assert s["summary"] == f"Jenkins 2.580.2 at {BASE} · JENKINS_USER's API token was refused"
    assert "Jenkins refused alice's API token (HTTP 401)" in s["problem"]
    assert s["signedIn"].startswith("no: Jenkins refused") and s["version"] == "2.580.2"
    no_secret(s)
    p, j, _ = make(FakeJenkins(token="another"), FakeFinders(system="windows"), env=dict(REMOTE))
    assert p.present() is True
    s = p.status()
    assert s["valid"] is True and s["summary"].startswith("Jenkins 2.580.2 at https://ci.example.com · JENKINS_USER")
    assert [t["title"] for t in s["tables"]] == ["Jobs"] and "Jenkins refused alice's API token" in s["problem"]
    assert p.refresh()["said"] == ("Jenkins 2.580.2 answers at https://ci.example.com, but was not read: "
                                   "JENKINS_USER's API token was refused")
    no_secret(s, p.api_facts())


def test_a_refusal_whose_version_no_answer_said_reads_without_one():
    """Jenkins' refusal of the token says no version: with none known before, the words say Jenkins without one."""
    p, j, _ = make(FakeJenkins(token="another"))
    target = jk.settings.read(p.login)
    r = p._jobs(target, p._found(), p._client(target), "")  # the read past its first ask, no version known
    assert r.answered and r.version == "" and r.status == 401 and signed(j) == [True]
    assert p._said(r)[0] == f"Jenkins at {BASE} · JENKINS_USER's API token was refused"
    assert p._facts(r)["version"] == "not said yet" and p._named(r) == "Jenkins"


def test_signed_in_the_jobs_queue_and_nodes_are_tables():
    p, j, _ = make()
    s = p.status()
    assert s["valid"] is True and s["version"] == "2.580.2" and s["signedIn"] == "as alice"
    assert s["summary"] == (f"Jenkins 2.580.2 at {BASE} · 5 jobs (1 building, 1 failing) · 1 waiting · "
                            "1 of 2 nodes online")
    assert [t["title"] for t in s["tables"]] == ["Jobs", "Build queue", "Nodes"]
    jobs = table(s, "Jobs")
    assert [c["title"] for c in jobs["columns"]] == ["Job", "State", "Last build", "When", "Build"]
    rows = {texts(r)[0]: r for r in jobs["rows"]}
    assert list(rows) == ["app", "deploy", "old", "team", "shop"]
    assert rows["app"][0] == {"text": "app", "sub": "Freestyle project"} and rows["app"][1] == "succeeded"
    assert rows["app"][2] == {"text": "#42", "sub": "succeeded"} and rows["app"][3]["sub"] == "1 min 35 s · 3 h ago"
    assert rows["app"][4] == {"form": "build", "title": "Build…", "values": {"job": "app"}, "label": "Build app"}
    assert rows["deploy"][1] == {"text": "failed", "sub": "building now"} and rows["deploy"][2]["sub"] == "building"
    assert rows["deploy"][3]["sub"] == "2 min ago"
    assert rows["old"][1] == "disabled" and rows["old"][2] == "–" and rows["old"][4] == {"text": "–", "sub": "disabled"}
    assert rows["team"][:2] == [{"text": "team", "sub": "Folder"}, "–"]
    assert rows["team"][4] == {"text": "–", "sub": "not a job to build"}
    assert rows["shop"][0] == {"text": "shop", "sub": "Multibranch Pipeline"}
    assert rows["shop"][4] == {"text": "–", "sub": "scanned by Jenkins, not built"}
    (waiting,) = table(s, "Build queue")["rows"]
    assert waiting[0] == {"text": "deploy", "sub": "item 12"} and waiting[1]["sub"] == "1 min ago"
    assert waiting[2:] == ["Waiting for next available executor", "waiting for an executor"]
    nodes = table(s, "Nodes")
    assert texts(nodes["rows"][0]) == ["Built-In Node", "online", "1 of 2 busy"]
    assert nodes["rows"][0][0]["sub"] == "built-in"  # its own name's label left out
    assert nodes["rows"][1][1] == {"text": "taken offline", "sub": "disk full"}
    assert nodes["note"].endswith("1 of 2 executors busy") and s["nodes"] == "1 of 2 online · 1 of 2 executors busy"
    assert [(m, path) for m, path in j.paths()] == [("GET", "/api/json"), ("GET", "/api/json"),
                                                   ("GET", "/queue/api/json"), ("GET", "/computer/api/json")]
    assert signed(j) == [False, True, True, True]  # the address's first ask unsigned, the rest as alice
    no_secret(s, p.api_facts(), p.interface())


def test_queued_builds_of_jobs_in_folders_are_named_in_full():
    queue = {"_class": "hudson.model.Queue", "items": [
        {"_class": "hudson.model.Queue$WaitingItem", "id": 31, "why": "In the quiet period.", "inQueueSince": 0,
         "task": {"name": "main", "fullName": "shop/main"}},
        {"_class": "hudson.model.Queue$WaitingItem", "id": 32, "why": "In the quiet period.", "inQueueSince": 0,
         "task": {"name": "main", "fullName": "billing/main"}},
        {"_class": "hudson.model.Queue$BuildableItem", "id": 33, "task": {"name": "app", "fullName": "app"}}]}
    p, _, _ = make(FakeJenkins(queue=queue))
    rows = table(p.status(), "Build queue")["rows"]
    assert [texts(r)[0] for r in rows] == ["shop/main", "billing/main", "app"]


def test_the_trees_ask_only_what_is_shown():
    from urllib.parse import parse_qs, urlsplit
    p, j, _ = make()
    p.status()
    trees = [(urlsplit(u).path, parse_qs(urlsplit(u).query)["tree"][0]) for _, u, _, _ in j.asked]
    assert trees[0] == ("/api/json", "quietingDown")  # the address's first ask: as little as Jenkins answers
    asked = dict(trees[1:])
    assert asked["/api/json"].startswith("jobs[name,color,buildable,inQueue,lastBuild[")
    assert "{0,200}" in asked["/api/json"] and asked["/api/json"].endswith(",quietingDown")
    assert asked["/queue/api/json"].startswith("items[") and "task[name,fullName]" in asked["/queue/api/json"]
    assert asked["/computer/api/json"].startswith("busyExecutors,")


def test_a_part_that_fails_is_said_and_the_rest_shown():
    p, _, _ = make(FakeJenkins(fail={"/computer/api/json": 500}))
    s = p.status()
    assert s["valid"] is True and "its nodes could not be read: GET /computer/api/json: HTTP 500" in s["problem"]
    assert table(s, "Nodes")["empty"].startswith("Not read: GET /computer/api/json: HTTP 500")
    assert len(table(s, "Jobs")["rows"]) == 5


def test_a_redirect_is_refused_and_said():
    p, j, _ = make(FakeJenkins(redirect="https://sso.example.com/login?next=/api/json"))
    s = p.status()
    assert s["valid"] is True and s["summary"].endswith("· not read")
    assert "sending it on to https://sso.example.com/login: not followed" in s["problem"]
    assert len(j.asked) == 1 and j.asked[0][1].startswith(BASE + "/api/json")
    p, j, _ = make(FakeJenkins(redirect="https://sso.example.com/login", jenkins=False))
    assert p.status()["valid"] is True and len(j.asked) == 1  # a proxy's redirect, no Jenkins behind it said
    assert not any(signed(j))


def test_a_bad_address_is_said_and_nothing_asked():
    p, j, _ = make(env={"JENKINS_URL": "ftp://ci.example.com"})
    s = p.status()
    assert s["valid"] is True and s["summary"] == "JENKINS_URL is not an address Jenkins is asked at" and j.asked == []
    assert s["note"].startswith("JENKINS_URL is not an address Jenkins is asked at: an instance is asked over http")


# -- what is kept --------------------------------------------------------------------------------------------------
def test_what_was_read_is_kept_and_read_anew_when_asked():
    clock = Clock()
    p, j, _ = make(clock=clock)
    p.status()
    p.status()
    p.present()
    assert len(j.asked) == 4  # one read: its first ask unsigned, then three
    clock.now += READ_S + 1
    p.status()
    assert len(j.asked) == 7  # Jenkins still held to answer there: three, signed
    said = p.refresh()
    assert said["ok"] and said["said"] == f"Jenkins 2.580.2 read at {BASE} now: 5 jobs" and len(j.asked) == 10
    p.settings_changed()
    p.status()
    assert len(j.asked) == 14 and signed(j)[10] is False  # new settings: the address asked unsigned first again
    p.detach()
    assert p.api_facts() == {} and p.login is None and p._rt.jenkins == ("", "")


def test_an_ask_waits_a_while_for_a_read_under_way_then_answers_without_it(monkeypatch):
    """One read at a time; an ask finding another's read under way waits READ_WAIT_S for it, then answers with what
    was read last, else that Jenkins is being read, never parked for as long as what answers there takes."""
    monkeypatch.setattr(jk, "READ_WAIT_S", 0.01)
    clock = Clock()
    p, j, _ = make(clock=clock)
    before = p.status()
    clock.now += READ_S + 1
    said = []
    worker = threading.Thread(target=lambda: said.append(p.status()))
    assert p._rt.reading_lock.acquire(blocking=False)  # a read under way that does not end (held here)
    try:
        worker.start()  # an ask of the page's own, in its own thread
        worker.join(timeout=10)
        assert not worker.is_alive(), "an ask waited for the read under way past READ_WAIT_S"
        assert said == [before] and len(j.asked) == 4  # what was read last, nothing asked
        assert p.status() == before and p.present() is True and len(j.asked) == 4  # here too, bounded the same
        said = p.refresh()
        assert said["ok"] is False and said["said"].startswith(f"Jenkins at {BASE} is being read by another ask")
        p._forget()
        s = p.status()
        assert s["summary"] == f"Jenkins at {BASE} is being read" and s["valid"] is True and s["tables"] == []
        assert "has waited more than 0.01 s for its answer" in s["note"] and len(j.asked) == 4
    finally:
        p._rt.reading_lock.release()
        worker.join(timeout=10)
    assert p.status()["valid"] is True and len(j.asked) == 8  # once it ends, read as ever


def test_its_facts_ask_nothing():
    p, j, _ = make()
    assert p.api_facts() == {}
    p.status()
    p.build("app")
    p.status()  # the platform's page reads again after a change
    before = len(j.asked)
    facts = p.api_facts()
    assert len(j.asked) == before == 10
    jenkins = facts[jk.cards.REMOTE]
    assert jenkins["Version"] == "2.580.2 (its X-Jenkins header)" and jenkins["Requests"] == "10 made"
    assert jenkins["CSRF protection"] == "at the last build: its crumb sent in Jenkins-Crumb"
    assert jenkins["Last answer"].startswith("HTTP 200 in ") and jenkins["Signed in"] == "as alice"
    assert facts[jk.cards.SCM] == {"Installed": f"the Windows service jenkins (running) · its war file {WAR}"}
    no_secret(facts)


# -- a build -------------------------------------------------------------------------------------------------------
def test_the_build_is_confirmed_by_the_page():
    p, _, _ = make()
    s = p.status()
    (form,) = s["forms"]
    assert form["id"] == "build" and form["hook"] == "build" and form["submit"] == "Review"
    assert form["confirm"]["title"] == "Build {job}?" and form["confirm"]["yes"] == "Build"
    assert "{job}" in form["confirm"]["words"] and "as alice" in form["confirm"]["words"]
    job, params, at = form["fields"]  # build's arguments, in order
    assert job["type"] == "choice" and [c["value"] for c in job["choices"]] == ["app", "deploy"]
    assert params["name"] == "parameters" and params["when"] == {"job": ["deploy"]}
    assert at == {"name": "at", "label": "Jenkins", "type": "fixed", "value": f"{BASE}, as alice"}
    assert table(s, "Jobs")["actions"] == [{"form": "build", "title": "Build a job…"}]
    assert {a["hook"] for a in s["actions"]} == {"refresh"}
    listed = [j for j in FakeJenkins().listed if j["name"] != "deploy"]  # no job takes parameters
    p, _, _ = make(FakeJenkins(listed=listed))
    job, params, at = p.status()["forms"][0]["fields"]
    assert params["when"] == {"job": []} and at["name"] == "at"  # never shown, and `at` stays the third argument


def test_a_build_is_posted_with_the_crumb():
    p, j, _ = make()
    s = p.status()
    answer = p.build("app", None, s["forms"][0]["fields"][2]["value"])  # as the page asks it
    assert answer == {"said": "a build of app is queued (queue item 101)", "ok": True,
                      "lines": [f"at {BASE}, as alice", "its crumb sent in Jenkins-Crumb"]}
    assert j.paths()[-3:] == [("GET", "/job/app/api/json"), ("GET", "/crumbIssuer/api/json"),
                              ("POST", "/job/app/build")]
    method, url, headers, body = j.asked[-1]
    assert headers["Jenkins-Crumb"] == CRUMB and SESSION in headers["Cookie"] and body == b""
    assert headers["Authorization"] == basic(USER, TOKEN) and j.built == [("/job/app/build", [])]
    p.status()
    assert j.paths()[-1] == ("GET", "/computer/api/json")  # the page's next ask read anew
    no_secret(answer, p.status(), p.api_facts())


def test_a_build_holds_the_settings_to_what_the_page_confirmed():
    """The page confirmed Jenkins at one address as one user; when the settings name another by the time the build is
    asked, nothing is asked of either."""
    env = {"JENKINS_URL": "https://staging.example.com", "JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN}
    p, j, _ = make(env=env)
    at = p.status()["forms"][0]["fields"][2]["value"]
    assert at == "https://staging.example.com, as alice"
    env["JENKINS_URL"] = "https://prod.example.com"  # changed in another tab, or by another session
    asked = len(j.asked)
    with pytest.raises(ValueError, match="the settings changed since the page asked you"):
        p.build("app", None, at)
    env["JENKINS_URL"], env["JENKINS_USER"] = "https://staging.example.com", "bob"
    with pytest.raises(ValueError, match=r"they name Jenkins at https://staging\.example\.com, as bob now"):
        p.build("app", None, at)
    assert len(j.asked) == asked and j.built == []  # nothing was sent
    env["JENKINS_USER"] = USER
    assert p.build("app", None, at)["ok"] is True and j.built == [("/job/app/build", [])]


def test_a_build_without_csrf_protection_sends_no_crumb():
    p, j, _ = make(FakeJenkins(csrf=False))
    answer = p.build("app")
    assert answer["lines"][-1] == "no crumb: Jenkins' CSRF protection issues none"
    assert "Jenkins-Crumb" not in j.asked[-1][2] and j.built == [("/job/app/build", [])]


def test_a_job_with_parameters_is_built_with_them():
    p, j, _ = make()
    answer = p.build("deploy", "BRANCH=release/1.2&DRY_RUN=true")
    assert answer["said"] == "a build of deploy is queued (queue item 101)"
    assert "with BRANCH, DRY_RUN as typed, the rest their defaults" in answer["lines"]
    assert j.built == [("/job/deploy/buildWithParameters", [("BRANCH", "release/1.2"), ("DRY_RUN", "true")])]
    assert "release/1.2" not in json.dumps(answer)  # a parameter's value is never said back
    answer = p.build("deploy", "")
    assert "with its parameters' defaults" in answer["lines"] and j.built[-1] == ("/job/deploy/buildWithParameters", [])


def test_the_same_build_asked_while_it_waits_is_said_not_failed():
    """Jenkins folds a build asked again while the same one waits into it: 303 to its queue item, which is said."""
    p, j, _ = make()
    first = p.build("deploy", "BRANCH=main")
    again = p.build("deploy", "BRANCH=main")
    assert first["said"] == "a build of deploy is queued (queue item 101)"
    assert again == {"said": "the same build of deploy already waits in the queue (queue item 101): Jenkins queued no "
                             "second one", "ok": True, "lines": first["lines"]}
    assert j.built == [("/job/deploy/buildWithParameters", [("BRANCH", "main")])]
    assert p.build("deploy", "BRANCH=dev")["said"] == "a build of deploy is queued (queue item 102)"
    code, said = cli_said(p, ["build", "deploy", "BRANCH=main"])
    assert code == 0 and said.startswith("the same build of deploy already waits in the queue (queue item 101)")


def test_a_build_jenkins_does_not_queue_is_said_so():
    """A queue decision of one of Jenkins' plugins refuses the build: Jenkins answers 302 back to the job's own page,
    which is said as that, not as an address to correct; a 302 anywhere else is still refused as a redirect."""
    p, j, _ = make(FakeJenkins(vetoed={"app"}))
    answer = p.build("app")
    assert answer["ok"] is False and answer["said"] == ("Jenkins did not queue a build of app: a queue decision of one "
                                                        "of its plugins refused it")
    assert j.built == [] and j.paths()[-1] == ("POST", "/job/app/build")
    code, said = cli_said(p, ["build", "app"])
    assert code == 1 and said.startswith("Jenkins did not queue a build of app")

    class Elsewhere(FakeJenkins):
        def __call__(self, method, url, headers, body, timeout, stream):
            if method == "POST":
                self.asked.append((method, url, dict(headers), body))
                return reply(302, {"Location": "https://sso.example.com/login?from=%2Fjob%2Fapp%2Fbuild"})
            return super().__call__(method, url, headers, body, timeout, stream)

    p, _, _ = make(Elsewhere())
    with pytest.raises(JenkinsError, match="sending it on to https://sso.example.com/login: not followed"):
        p.build("app")
    assert p._rt.seen["failed"] == 1 and "not followed" in p._rt.seen["error"]  # noted as the request that failed


def test_a_multibranch_project_is_scanned_not_built():
    """A multibranch project or an organization folder is buildable as Jenkins says it, with no colour: its build
    would be a scan of its branches or repositories. No Build… for it, none in the form, and build refuses it before
    anything is sent."""
    p, j, _ = make()
    s = p.status()
    row = next(r for r in table(s, "Jobs")["rows"] if texts(r)[0] == "shop")
    assert row[4] == {"text": "–", "sub": "scanned by Jenkins, not built"}
    assert "shop" not in [c["value"] for c in s["forms"][0]["fields"][0]["choices"]]
    with pytest.raises(ValueError, match=r"shop is not built: it is a multibranch project or an organization folder.*"
                                         r"a job in it is built by its full name, shop/\.\.\."):
        p.build("shop")
    assert not any(m == "POST" for m, _ in j.paths()) and j.scans == [] and j.built == []


@pytest.mark.parametrize("job, parameters, words", [
    ("nope", None, "has no job nope"),
    ("old", None, "old is not built: it is disabled"),
    ("team", None, "team is not built: it is not a job a build is asked of"),
    ("shop", None, "shop is not built: it is a multibranch project or an organization folder"),
    ("app", "X=1", "app takes no parameters"),
    ("deploy", "BRANCH=main&COLOUR=red", "deploy has no parameter COLOUR: its parameters are BRANCH, DRY_RUN"),
    ("deploy", "BRANCH=main&BRANCH=dev", "a parameter given twice: BRANCH"),
    ("deploy", "BRANCH", "parameters are NAME=value pairs joined by &"),
    ("../x", None, "not a job's name"),
])
def test_a_build_is_refused_before_anything_changes(job, parameters, words):
    p, j, _ = make()
    with pytest.raises(ValueError, match=words.replace("(", r"\(")):
        p.build(job, parameters)
    assert not any(m == "POST" for m, _ in j.paths()) and j.built == []


def test_a_build_jenkins_refuses_fails_in_words():
    p, j, _ = make(FakeJenkins(fail={"/job/app/build": 403}))
    with pytest.raises(JenkinsError, match="HTTP 403"):
        p.build("app")
    p, j, _ = make(FakeJenkins(down=True))
    with pytest.raises(JenkinsError, match="nothing listens at 127.0.0.1:8080"):
        p.build("app")


def test_the_token_is_never_in_any_answer_table_or_fact():
    p, j, _ = make()
    said = [p.status(), p.refresh(), p.build("app"), p.build("deploy", "BRANCH=x"), p.build("deploy", "BRANCH=x"),
            p.api_facts(), p.interface(), p.status()]
    for bad in (FakeJenkins(token="another"), FakeJenkins(down=True), FakeJenkins(redirect=f"{BASE}/login?t={TOKEN}"),
                FakeJenkins(fail={"/job/app/build": 500}), FakeJenkins(starting=True), FakeJenkins(vetoed={"app"}),
                FakeJenkins(jenkins=False, anonymous=True)):
        q, _, _ = make(bad)
        said += [q.status(), q.refresh(), q.api_facts()]
        try:
            said.append(q.build("app"))
        except (ValueError, JenkinsError) as e:
            said.append(str(e))
    no_secret(*said)
    assert any(basic(USER, TOKEN) == h.get("Authorization") for _, _, h, _ in j.asked)  # it was sent, all the same


def test_a_plugin_with_no_login_lent_reads_the_environment(monkeypatch):
    monkeypatch.setenv("JENKINS_USER", USER)
    monkeypatch.setenv("JENKINS_TOKEN", TOKEN)
    j = FakeJenkins()
    p = JenkinsPlugin(finders=FakeFinders(), transport=j, wall=lambda: NOW)
    assert p.status()["signedIn"] == "as alice"


def test_jenkins_clis_own_names_are_read_too():
    """jenkins-cli.jar's JENKINS_USER_ID and JENKINS_API_TOKEN, for a user who has them set already."""
    p, j, _ = make(env={"JENKINS_USER_ID": USER, "JENKINS_API_TOKEN": TOKEN})
    assert p.status()["signedIn"] == "as alice" and signed(j) == [False, True, True, True]


def test_a_failure_of_its_own_is_said_not_raised():
    p, _, _ = make()
    p._page = lambda r: 1 / 0  # a bug of the page's
    s = p.status()
    assert s["valid"] is False and s["why"] == "the plugin failed: ZeroDivisionError" and s["tables"] == []


# -- the command line ----------------------------------------------------------------------------------------------
def cli_said(p, argv) -> tuple[int, str]:
    """The command line run over `p`: its exit code, and what it printed (its output, then its errors)."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    real = cli.MACHINE
    cli.MACHINE = p
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
    finally:
        cli.MACHINE = real
    return code, out.getvalue() + err.getvalue()


def test_the_command_line(monkeypatch, capsys):
    p, j, _ = make()
    monkeypatch.setattr(cli, "MACHINE", p)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["version"] == "2.580.2" and TOKEN not in out
    assert cli.main(["jobs"]) == 0
    out = capsys.readouterr().out
    assert "  app (Freestyle project)  succeeded  #42 (succeeded)" in out
    assert cli.main(["build", "app"]) == 0 and "a build of app is queued" in capsys.readouterr().out
    assert cli.main(["build", "nope"]) == 1 and "refused: Jenkins at" in capsys.readouterr().err
    assert cli.main(["what"]) == 2 and "python -m plugin_platform_jenkins" in capsys.readouterr().err
