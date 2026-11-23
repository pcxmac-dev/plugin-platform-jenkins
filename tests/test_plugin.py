"""Jenkins on the platform's page, over stand-ins (stand_ins.py): present on each system, the status when Jenkins is
not here, installed but not answering, answering to no one, refusing the token, and read (its jobs, build queue and
nodes as tables, its version from X-Jenkins); a redirect refused; the token never in any answer, table or fact; a build
confirmed by the page and asked with the crumb, its parameters checked first; what is kept and when it is read anew;
the command line."""
from __future__ import annotations

import json

import pytest

import plugin_platform_jenkins as jk
import plugin_platform_jenkins.__main__ as cli
from plugin_platform_jenkins import READ_S, JenkinsPlugin
from plugin_platform_jenkins.client import JenkinsError
from stand_ins import (BASE, CRUMB, NOW, SESSION, TOKEN, USER, WAR, Clock, FakeFinders, FakeJenkins, basic, make)

SECRETS = (TOKEN, basic(USER, TOKEN), basic(USER, TOKEN)[6:], CRUMB, SESSION)


def no_secret(*things) -> None:
    """None of the secrets in anything said: a status, an answer, the facts, an error's words."""
    text = json.dumps(things, default=str)
    for s in SECRETS:
        assert s not in text


def table(status: dict, title: str) -> dict:
    return next(t for t in status["tables"] if t["title"] == title)


def texts(row) -> list[str]:
    return [c.get("text", c.get("title", "")) if isinstance(c, dict) else c for c in row]


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
    assert s["present"] is False and s["valid"] is False
    assert s["summary"] == f"Jenkins is not installed here, and nothing answers at {BASE}"
    assert "nothing listens at 127.0.0.1:8080" in s["why"] and "install it (the table below says how)" in s["why"]
    t = table(s, "How to install Jenkins")
    assert [r[0] for r in t["rows"]][:3] == ["Java", "Jenkins", "Unlock it"] and "installs, starts" in t["note"]
    assert s["forms"] == [] and s["installed"] == "not installed here" and len(j.asked) == 1
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="linux"))
    assert [r[0] for r in table(p.status(), "How to install Jenkins")["rows"]][0] == "Debian, Ubuntu: Java"
    no_secret(s)


def test_installed_but_not_answering_says_what_to_do():
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="windows", service="stopped", files=(WAR,)))
    s = p.status()
    assert s["present"] is True and s["valid"] is False and s["tables"] == []
    assert s["summary"] == f"Jenkins is installed here, but does not answer at {BASE}"
    assert "Its service is stopped: start it from the Services app" in s["why"] and "starts nothing" in s["why"]
    assert s["installed"] == f"the Windows service jenkins (stopped) · its war file {WAR}"
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="windows", service="running"))
    assert "it may answer at another port" in p.status()["why"]
    p, _, _ = make(FakeJenkins(down=True), FakeFinders(system="linux", unit="failed"))
    assert "Its unit is failed: start it with sudo systemctl start jenkins" in p.status()["why"]


def test_something_else_answering_is_not_jenkins():
    p, _, _ = make(FakeJenkins(jenkins=False, anonymous=True))
    s = p.status()
    assert s["valid"] is False and "not as Jenkins does: its answer has no X-Jenkins header" in s["why"]


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
    p, _, _ = make(FakeJenkins(token="another"))
    s = p.status()
    assert s["valid"] is True and s["summary"].endswith("· JENKINS_USER's API token was refused")
    assert "Jenkins refused alice's API token (HTTP 401)" in s["problem"]
    assert s["signedIn"].startswith("no: Jenkins refused")
    no_secret(s)


def test_signed_in_the_jobs_queue_and_nodes_are_tables():
    p, j, _ = make()
    s = p.status()
    assert s["valid"] is True and s["version"] == "2.580.2" and s["signedIn"] == "as alice"
    assert s["summary"] == (f"Jenkins 2.580.2 at {BASE} · 4 jobs (1 building, 1 failing) · 1 waiting · "
                            "1 of 2 nodes online")
    assert [t["title"] for t in s["tables"]] == ["Jobs", "Build queue", "Nodes"]
    jobs = table(s, "Jobs")
    assert [c["title"] for c in jobs["columns"]] == ["Job", "State", "Last build", "When", "Build"]
    rows = {texts(r)[0]: r for r in jobs["rows"]}
    assert list(rows) == ["app", "deploy", "old", "team"]
    assert rows["app"][0] == {"text": "app", "sub": "Freestyle project"} and rows["app"][1] == "succeeded"
    assert rows["app"][2] == {"text": "#42", "sub": "succeeded"} and rows["app"][3]["sub"] == "1 min 35 s · 3 h ago"
    assert rows["app"][4] == {"form": "build", "title": "Build…", "values": {"job": "app"}, "label": "Build app"}
    assert rows["deploy"][1] == {"text": "failed", "sub": "building now"} and rows["deploy"][2]["sub"] == "building"
    assert rows["deploy"][3]["sub"] == "2 min ago"
    assert rows["old"][1] == "disabled" and rows["old"][2] == "–" and rows["old"][4] == {"text": "–", "sub": "disabled"}
    assert rows["team"][:2] == [{"text": "team", "sub": "Folder"}, "–"]
    assert rows["team"][4] == {"text": "–", "sub": "not a job to build"}
    (waiting,) = table(s, "Build queue")["rows"]
    assert waiting[0] == {"text": "deploy", "sub": "item 12"} and waiting[1]["sub"] == "1 min ago"
    assert waiting[2:] == ["Waiting for next available executor", "waiting for an executor"]
    nodes = table(s, "Nodes")
    assert texts(nodes["rows"][0]) == ["Built-In Node", "online", "1 of 2 busy"]
    assert nodes["rows"][0][0]["sub"] == "built-in"  # its own name's label left out
    assert nodes["rows"][1][1] == {"text": "taken offline", "sub": "disk full"}
    assert nodes["note"].endswith("1 of 2 executors busy") and s["nodes"] == "1 of 2 online · 1 of 2 executors busy"
    assert [(m, path) for m, path in j.paths()] == [("GET", "/api/json"), ("GET", "/queue/api/json"),
                                                   ("GET", "/computer/api/json")]
    assert all(h["Authorization"] == basic(USER, TOKEN) for _, _, h, _ in j.asked)
    no_secret(s, p.api_facts(), p.interface())


def test_the_trees_ask_only_what_is_shown():
    from urllib.parse import parse_qs, urlsplit
    p, j, _ = make()
    p.status()
    trees = {urlsplit(u).path: parse_qs(urlsplit(u).query)["tree"][0] for _, u, _, _ in j.asked}
    assert trees["/api/json"].startswith("jobs[name,color,buildable,inQueue,lastBuild[")
    assert "{0,200}" in trees["/api/json"] and trees["/api/json"].endswith(",quietingDown")
    assert trees["/queue/api/json"].startswith("items[") and trees["/computer/api/json"].startswith("busyExecutors,")


def test_a_part_that_fails_is_said_and_the_rest_shown():
    p, _, _ = make(FakeJenkins(fail={"/computer/api/json": 500}))
    s = p.status()
    assert s["valid"] is True and "its nodes could not be read: GET /computer/api/json: HTTP 500" in s["problem"]
    assert table(s, "Nodes")["empty"].startswith("Not read: GET /computer/api/json: HTTP 500")
    assert len(table(s, "Jobs")["rows"]) == 4


def test_a_redirect_is_refused_and_said():
    p, j, _ = make(FakeJenkins(redirect="https://sso.example.com/login?next=/api/json"))
    s = p.status()
    assert s["valid"] is True and s["summary"].endswith("· not read")
    assert "sending it on to https://sso.example.com/login: not followed" in s["problem"]
    assert len(j.asked) == 1 and j.asked[0][1].startswith(BASE + "/api/json")
    p, j, _ = make(FakeJenkins(redirect="https://sso.example.com/login", jenkins=False))
    assert p.status()["valid"] is False and len(j.asked) == 1  # a proxy's redirect, no Jenkins behind it said


def test_a_bad_address_is_said_and_nothing_asked():
    p, j, _ = make(env={"JENKINS_URL": "ftp://ci.example.com"})
    s = p.status()
    assert s["valid"] is False and s["summary"] == "JENKINS_URL is not an address Jenkins is asked at" and j.asked == []
    assert s["why"].startswith("JENKINS_URL is not an address Jenkins is asked at: an instance is asked over http")


# -- what is kept --------------------------------------------------------------------------------------------------
def test_what_was_read_is_kept_and_read_anew_when_asked():
    clock = Clock()
    p, j, _ = make(clock=clock)
    p.status()
    p.status()
    p.present()
    assert len(j.asked) == 3  # one read
    clock.now += READ_S + 1
    p.status()
    assert len(j.asked) == 6
    said = p.refresh()
    assert said["ok"] and said["said"] == f"Jenkins 2.580.2 read at {BASE} now: 4 jobs" and len(j.asked) == 9
    p.settings_changed()
    p.status()
    assert len(j.asked) == 12
    p.detach()
    assert p.api_facts() == {} and p.login is None


def test_its_facts_ask_nothing():
    p, j, _ = make()
    assert p.api_facts() == {}
    p.status()
    p.build("app")
    p.status()  # the platform's page reads again after a change
    before = len(j.asked)
    facts = p.api_facts()
    assert len(j.asked) == before == 9
    jenkins = facts[jk.cards.REMOTE]
    assert jenkins["Version"] == "2.580.2 (its X-Jenkins header)" and jenkins["Requests"] == "9 made"
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
    job, params = form["fields"]
    assert job["type"] == "choice" and [c["value"] for c in job["choices"]] == ["app", "deploy"]
    assert params["name"] == "parameters" and params["when"] == {"job": ["deploy"]}
    assert table(s, "Jobs")["actions"] == [{"form": "build", "title": "Build a job…"}]
    assert {a["hook"] for a in s["actions"]} == {"refresh"}


def test_a_build_is_posted_with_the_crumb():
    p, j, _ = make()
    p.status()
    answer = p.build("app")
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


@pytest.mark.parametrize("job, parameters, words", [
    ("nope", None, "has no job nope"),
    ("old", None, "old is not built: it is disabled"),
    ("team", None, "team is not built: it is not a job a build is asked of"),
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
    said = [p.status(), p.refresh(), p.build("app"), p.build("deploy", "BRANCH=x"), p.api_facts(), p.interface(),
            p.status()]
    for bad in (FakeJenkins(token="another"), FakeJenkins(down=True), FakeJenkins(redirect=f"{BASE}/login?t={TOKEN}"),
                FakeJenkins(fail={"/job/app/build": 500})):
        q, _, _ = make(bad)
        said += [q.status(), q.refresh(), q.api_facts()]
        try:
            q.build("app")
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


def test_a_failure_of_its_own_is_said_not_raised():
    p, _, _ = make()
    p._page = lambda r: 1 / 0  # a bug of the page's
    s = p.status()
    assert s["valid"] is False and s["why"] == "the plugin failed: ZeroDivisionError" and s["tables"] == []


# -- the command line ----------------------------------------------------------------------------------------------
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
