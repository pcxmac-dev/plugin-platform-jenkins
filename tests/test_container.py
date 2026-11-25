"""0.2.0: Jenkins in a container, through a container plugin's plans (the library's ContainedService, 1.94.0), on the
library's stand-ins alone (machines/servicestandins.py: a real apps.App, a stand-in container plugin over a FakeDocker,
a stand-in firewall and WSL plugin) and Jenkins as FakeJenkins: no docker, no process, no socket. Each of its own
gates has a test that fails when the gate is taken out."""
from __future__ import annotations

import re

import pytest

from liminal_libs.apps.asking import AskRefused
from liminal_libs.apps import asking
from liminal_libs.instances import Refusal
from liminal_libs.machines.containedservice import UNREAD, Pace
from liminal_libs.machines.servicestandins import JobLog, ServiceWorld

from plugin_platform_jenkins import JenkinsPlugin, recipe
from stand_ins import NOW, FakeFinders, FakeJenkins

DIG = "sha256:" + "a" * 64
UNLOCK = "3f1c0e9a2b7d4c58a6e1f0d9c8b7a6e5"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        import time

        self.now += s
        time.sleep(0.002)


def pins(digest=DIG):
    return {system: {part: {**pin, "digest": digest} for part, pin in parts.items()}
            for system, parts in recipe.PINS.items()}


def world(tmp_path, pairs=None, jenkins=None, digest=DIG):
    c = Clock()
    p = JenkinsPlugin(finders=FakeFinders(system="windows"), transport=jenkins or FakeJenkins(),
                      clock=c, wall=lambda: NOW, pace=Pace(clock=c, sleep=c.sleep), pins=pins(digest))
    return ServiceWorld(p, pairs=pairs, folder=tmp_path), p


def install(w, *args):
    end = w.install("ci", *args) if args else w.install("ci", "yes", "no", 2048, 8080)
    assert end["ok"], end
    return end


def test_its_shipped_pins_are_by_tag_and_digest_and_none_is_installed_before_its_digest_is_read(tmp_path):
    for system, parts in recipe.PINS.items():
        for part, pin in parts.items():
            assert pin["ref"].startswith("docker.io/jenkins/") and re.fullmatch(r"sha256:[0-9a-f]{64}", pin["digest"]) and pin["digest"] != UNREAD and pin["size"] > 0 and pin["system"] == system
    w, p = world(tmp_path, digest=UNREAD)
    w.grant()
    with pytest.raises(Refusal, match="not pinned by digest yet"):
        w.ask("service_install", w.HOST, w.TARGET)
    assert w.fake.changes() == []


def test_an_install_runs_jenkins_with_its_usage_statistics_off_and_waits_for_its_answer(tmp_path):
    j = FakeJenkins()
    w, p = world(tmp_path, jenkins=j)
    end = install(w)
    create = " ".join(w.fake.argv_of("create")[0])
    assert "--restart no" in create and "-p 8080:8080/tcp" in create and recipe.USAGE_OFF in create
    assert "liminal-jenkins-ci-home:/var/jenkins_home" in create and f"@{DIG}" in create
    assert len(w.fake.argv_of("create")) == 1  # no agent before its secret is set
    assert any(u.startswith("http://127.0.0.1:8080/api/json") for _, u, _, _ in j.asked)  # its readiness, asked
    assert any("Unlock… shows the password" in x for x in end["lines"])
    assert p.placement("ci")["state"] == "installed"


@pytest.mark.xfail(strict=True, raises=Refusal, reason=(
    "liminal-libs 1.93.0 ContainerHost._check_secrets takes a pair the asker itself declares (its keys) for another "
    "plugin's: until that is fixed, a secret set through its own Settings is refused (reported with 0.2.0)"))
def test_its_agent_comes_beside_it_once_its_secret_is_set_and_never_on_a_command_line(tmp_path):
    secret = "9f8e7d6c5b4a39281706f5e4d3c2b1a0aa"
    w, p = world(tmp_path, pairs={"JENKINS_AGENT_SECRET": secret})
    w.grant()
    a = w.ask("service_install", w.HOST, w.TARGET)
    words = w.page(w.HOST, "plan_words", a["plan"])
    assert "accept_kept_secret" in [x["name"] for x in words["accepts"]] and secret not in str(words)
    assert w.through(a)["ok"]
    made = w.fake.argv_of("create")
    assert len(made) == 2 and "--name liminal-jenkins-ci-agent" in " ".join(made[1])
    assert all(secret not in " ".join(argv) for argv in made)
    agent = w.fake.containers["liminal-jenkins-ci-agent"]
    assert agent["secret_values"] == {"JENKINS_SECRET": secret} and "JENKINS_WEB_SOCKET=true" in agent["argv"]


def test_its_address_is_its_containers_port_unless_jenkins_url_is_set(tmp_path):
    j = FakeJenkins()
    w, p = world(tmp_path, jenkins=j)
    install(w, "yes", "no", 2048, 8091)
    assert p._settings().base == "http://127.0.0.1:8091"
    w.login.env["JENKINS_URL"] = "http://127.0.0.1:8080"
    assert p._settings().base == "http://127.0.0.1:8080"


def test_something_else_at_its_port_is_not_taken_for_jenkins(tmp_path):
    w, p = world(tmp_path, jenkins=FakeJenkins(jenkins=False))
    end = install(w)
    assert "does not answer yet" in end["said"] and "not Jenkins" in end["said"]


def test_unlock_shows_the_password_once_from_its_page_alone(tmp_path):
    w, p = world(tmp_path)
    install(w)
    w.fake.volumes["liminal-jenkins-ci-home"]["files"]["secrets/initialAdminPassword"] = (UNLOCK + "\n").encode()
    said = w.ask("unlock")
    assert said["lines"] == [UNLOCK] and UNLOCK not in said["said"]
    with pytest.raises(AskRefused):
        w.host.ask_plugin("jenkins", "unlock")
    for who in ("standin-host", None):
        with asking.asking(who), pytest.raises(Refusal, match="from its page alone"):
            p.unlock()
    assert UNLOCK not in str(p.status()) and UNLOCK not in str(p.placements())


def test_unlock_before_an_install_is_refused(tmp_path):
    w, p = world(tmp_path)
    with pytest.raises(Refusal, match="not installed in a container"):
        w.ask("unlock")


def test_its_page_offers_its_container_where_it_is_attached(tmp_path):
    w, p = world(tmp_path)
    s = p.status()
    titles = [t["title"] for t in s["tables"]]
    assert "Run Jenkins in a container" in titles and s["valid"] is True
    assert {f["id"] for f in s["forms"]} >= {"install", "unlock", "stop", "carry"}
    assert p.SECTION == "ci" and p.LAN_FIRST is True and p.NEEDS_LOOPBACK is True
    install(w)
    assert p.present() is True and any(a.get("form") == "unlock" for a in p.status()["actions"])


def test_turned_off_its_containers_stop(tmp_path):
    w, p = world(tmp_path)
    install(w)
    w.app.off.add("jenkins")
    p.detach()
    assert w.host.hosted("jenkins/ci")["state"] == "stopped"


def test_a_carry_cancelled_is_said(tmp_path):
    w, p = world(tmp_path)
    w.grant()
    a = w.ask("service_install", w.HOST, w.TARGET)
    w.approve(a)
    log = JobLog()
    log.cancelled = True
    w.fake.fail["pull"] = "cancelled meanwhile"
    end = w.carry(a, log)
    assert end["ok"] is False and p.placement("ci") is None


def test_its_recipe_puts_the_agent_beside_the_controller_its_secret_by_environment_alone():
    s = recipe.spec("linux", "ci", {"lan": True}, agent=True, pins=pins())
    agent = s.part("agent")
    assert [p.name for p in s.parts] == ["controller", "agent"] and agent.ports == ()
    assert [(x.variable, x.env) for x in agent.secrets] == [("JENKINS_AGENT_SECRET", "JENKINS_SECRET")]
    assert agent.env["JENKINS_URL"] == "http://liminal-jenkins-ci-controller:8080/"
    assert agent.env["JENKINS_WEB_SOCKET"] == "true" and "JENKINS_SECRET" not in agent.env
    w = recipe.spec("windows", "ci", {}, agent=False, pins=pins())
    assert w.system == "windows" and w.part("controller").volumes[0].path == "C:/ProgramData/Jenkins/.jenkins"
    assert w.ports()[0].lan is False  # this PC alone unless asked
