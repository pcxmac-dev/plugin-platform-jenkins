"""What the plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its
attached to, and present links that provide documentation"): its cards are sound; Jenkins' card names every request
the plugin sends (read from the stand-in as it was sent) and claims none it does not send, and the install's cards
every call its looks make; its changes are marked as writes and none costs; its facts ask nothing; and, with
LIMINAL_VENDOR_PAGES=1 alone, every address on them answers (the only test here that reaches the network)."""
from __future__ import annotations

import ast
import inspect
import os
import re

import pytest

import plugin_platform_jenkins as jk
from liminal_libs.sources import apis as A
from liminal_libs.sources.conformance import problems
from plugin_platform_jenkins import apis as cards
from plugin_platform_jenkins import here
from stand_ins import FakeFinders, FakeJenkins, make


def card(name: str) -> A.Api:
    return next(a for a in jk.MACHINE.apis if a.name == name)


def pattern(call: A.Call) -> tuple[str, re.Pattern]:
    method, _, path = call.name.partition(" ")
    return method, re.compile(re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(path)) + r"\Z")


def named(api: A.Api, method: str, path: str) -> A.Call | None:
    """The card's call a request is, by its method and its path."""
    for c in api.calls:
        m, rx = pattern(c)
        if m == method and rx.match(path):
            return c
    return None


def flows() -> FakeJenkins:
    """The plugin doing everything it does, against a stand-in: Jenkins read, a job built, a job with parameters built,
    Read again. Every request, as sent."""
    p, j, _ = make()
    p.status()
    p.build("app")
    p.build("deploy", "BRANCH=main")
    p.refresh()
    return j


def test_its_cards_are_sound_and_written_for_plugin_api_2_2():
    p = jk.MACHINE
    assert p.api == "2.2" and problems(p) == [] and A.problems(p.apis) == []
    assert [a.name for a in p.apis] == [cards.REMOTE, cards.SCM, cards.SYSTEMD]
    for a in p.apis:
        assert a.verified == "2026-11-22" and a.docs.startswith("https://") and a.used and a.covered
        assert all(c.area in {x.name for x in a.areas} for c in a.calls), a.name  # every call in one of its parts
        assert len(a.areas) > len(a.covered) and len(a.calls) > len(a.used)  # more of the API than the plugin uses
    assert p.interface()["apis"] == [a.name for a in p.apis]
    remote = card(cards.REMOTE)
    assert "API token" in remote.auth and "crumb" in remote.auth and remote.docs == cards._REMOTE
    assert {x.kind for x in remote.links} >= {"docs", "reference", "auth", "guide", "changelog", "source"}


def test_jenkins_card_names_every_request_the_plugin_sends_and_no_other():
    j = flows()
    api = card(cards.REMOTE)
    made = set()
    for method, path in j.paths():
        c = named(api, method, path)
        assert c is not None and c.used, f"{method} {path}: not on the card as a call the plugin makes"
        made.add(c.name)
    assert made == {c.name for c in api.used}, made ^ {c.name for c in api.used}


def source_of(name: str) -> str:
    text = inspect.getsource(here)
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node)


def test_the_install_cards_name_every_call_its_looks_make():
    scm = {c.name for c in card(cards.SCM).used}
    assert scm == {"OpenSCManagerW", "OpenServiceW", "QueryServiceStatus", "CloseServiceHandle"}
    win = source_of("_service_state")
    assert all(f"adv.{name}(" in win for name in scm)
    assert set(re.findall(r"adv\.([A-Za-z]+)\(", win)) == scm  # and no other
    unit = card(cards.SYSTEMD).used
    assert [c.name for c in unit] == ["systemctl show jenkins.service"]
    assert '"systemctl", "show"' in source_of("_unit_state") and here.UNIT == "jenkins.service"


def test_the_changes_are_marked_as_writes_and_none_costs():
    writes = {c.name for c in card(cards.REMOTE).used if c.writes}
    assert writes == {"POST /job/{name}/build", "POST /job/{name}/buildWithParameters"}
    assert all(c.name.startswith("POST ") for c in card(cards.REMOTE).calls if c.writes)
    assert not any(c.costs for a in jk.MACHINE.apis for c in a.calls)
    assert not any(c.writes for a in jk.MACHINE.apis if a.name != cards.REMOTE for c in a.used)  # the looks: reads


def test_its_facts_say_what_it_learned_and_ask_nothing():
    assert jk.JenkinsPlugin().api_facts() == {}  # nothing read yet, nothing asked
    p, j, _ = make(finders=FakeFinders(system="linux", unit="running", files=("/usr/share/java/jenkins.war",)))
    p.status()
    before = len(j.asked)
    facts = A.facts_of(p)
    assert len(j.asked) == before
    assert set(facts) == {cards.REMOTE, cards.SYSTEMD}
    assert facts[cards.REMOTE]["Address"] == "http://127.0.0.1:8080" and facts[cards.REMOTE]["Requests"] == "3 made"
    assert facts[cards.SYSTEMD]["Installed"] == ("the systemd unit jenkins.service (running) · its war file "
                                                 "/usr/share/java/jenkins.war")


@pytest.mark.skipif(os.environ.get("LIMINAL_VENDOR_PAGES") != "1",
                    reason="reaches the makers' pages: LIMINAL_VENDOR_PAGES=1")
def test_every_address_on_its_cards_answers(monkeypatch):
    monkeypatch.undo()  # this test alone reaches the network (conftest refuses it to every other)
    assert A.dead_links(jk.MACHINE.apis) == []
