"""Jenkins' client and the settings it is made from: the address as typed, the token sent only where it may be (https,
or this machine) and never in a word said, every request under the address with nothing followed off it, an answer
read under its bounds, the crumb and its session cookie, a job's path quoted. Jenkins is a stand-in (stand_ins.py)."""
from __future__ import annotations

import base64

import pytest

from liminal_libs.apps import EnvironmentLogin
from plugin_platform_jenkins import client, settings
from plugin_platform_jenkins.client import MOST, Jenkins, JenkinsError, job_path, queued
from stand_ins import BASE, COOKIE, CRUMB, SESSION, TOKEN, USER, Clock, FakeJenkins, basic, reply


def target(url=None, user=USER, token=TOKEN):
    values = {"JENKINS_USER": user, "JENKINS_TOKEN": token}
    if url is not None:
        values["JENKINS_URL"] = url
    return settings.parse(values)


# -- the settings ----------------------------------------------------------------------------------------------------
def test_the_address_is_the_default_unless_set_and_is_read_as_typed():
    assert settings.parse({}).base == BASE and settings.parse({}).problems == ()
    assert target("localhost").base == "http://localhost:8080"  # no scheme, no port: Jenkins' own port
    tls = target("https://ci.example.com")
    assert (tls.base, tls.port, tls.tls) == ("https://ci.example.com", 443, True)
    t = target("http://127.0.0.1:8080/jenkins/")
    assert (t.base, t.host, t.port, t.tls) == ("http://127.0.0.1:8080/jenkins", "127.0.0.1", 8080, False)
    assert target("http://[::1]:9090").at == "[::1]:9090"


def test_a_bad_address_is_said_and_never_asked():
    for url in ("ftp://ci.example.com", "http://alice:secret@ci.example.com", "http://ci.example.com/?a=1"):
        t = target(url)
        assert t.base == "" and t.problems[0].startswith("JENKINS_URL is not an address Jenkins is asked at")
        assert "secret" not in " ".join(t.problems)
        with pytest.raises(ValueError):
            Jenkins(t, transport=FakeJenkins())


def test_a_setting_typed_wrong_is_said_without_the_token():
    t = settings.parse({"JENKINS_USER": "al:ice", "JENKINS_TOKEN": TOKEN})
    assert t.user == "" and any("colon" in p for p in t.problems) and not t.keyed
    t = settings.parse({"JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN + "\n" + TOKEN})
    assert t.token == "" and any("line break" in p for p in t.problems)
    t = settings.parse({"JENKINS_TOKEN": TOKEN})
    assert any("without JENKINS_USER" in p for p in t.problems) and not t.sends
    assert all(TOKEN not in p for p in t.problems) and TOKEN not in repr(t)


def test_the_settings_are_read_through_the_login_alone():
    login = EnvironmentLogin(env={"JENKINS_URL": "https://ci.example.com", "JENKINS_USER": USER,
                                  "JENKINS_TOKEN": TOKEN})
    t = settings.read(login)
    assert (t.base, t.user, t.token, t.sends) == ("https://ci.example.com", USER, TOKEN, True)

    class Broken(EnvironmentLogin):
        def variables(self, wanted):
            raise RuntimeError("the login app is down")

    t = settings.read(Broken())
    assert t.base == BASE and t.user == "" and "could not be read from the login (RuntimeError)" in t.problems[0]


def test_the_token_goes_over_https_or_to_this_machine_only():
    assert target().sends and target("http://localhost:8080").sends and target("http://[::1]:8080").sends
    assert target("https://ci.example.com").sends
    lan = target("http://ci.lan:8080")
    assert lan.keyed and not lan.sends and lan.withheld
    fake = FakeJenkins(anonymous=True)
    Jenkins(lan, transport=fake).get("/api/json")
    assert "Authorization" not in fake.asked[0][2]  # plain http to another machine: never sent
    fake = FakeJenkins()
    Jenkins(target(), transport=fake).get("/api/json")
    assert fake.asked[0][2]["Authorization"] == basic(USER, TOKEN)  # with the first request (403 answers one without)


# -- requests ------------------------------------------------------------------------------------------------------
def test_every_request_goes_under_the_address_and_says_who_asks():
    fake = FakeJenkins()
    j = Jenkins(target(), transport=fake)
    got = j.get("/api/json", tree="jobs[name]{0,200}")
    method, url, headers, body = fake.asked[0]
    assert (method, body) == ("GET", None) and url.startswith(BASE + "/api/json?tree=")
    assert headers["Accept"] == "application/json" and headers["User-Agent"] == client.AGENT
    assert headers["Accept-Encoding"] == "identity" and got.status == 200 and isinstance(got.data, dict)
    assert j.version == "2.580.2"  # the X-Jenkins header
    for path in ("api/json", "//evil.example/x", "https://evil.example/", "/a b", "/x?y=1", "/x#y", "/a\nb", "/a\\b"):
        with pytest.raises(ValueError):
            j.url(path)


def test_a_redirect_is_never_followed():
    fake = FakeJenkins(redirect="https://sso.example.com/login?from=%2Fapi%2Fjson&secret=" + TOKEN)
    j = Jenkins(target(), transport=fake)
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    assert e.value.status == 302 and e.value.version == "2.580.2"
    said = str(e.value)
    assert "sending it on to https://sso.example.com/login: not followed" in said
    assert "from=" not in said and TOKEN not in said  # its query never said
    assert len(fake.asked) == 1 and all(u.startswith(BASE + "/") for _, u, _, _ in fake.asked)


def test_no_answer_is_said_in_words_without_the_token():
    j = Jenkins(target(), transport=FakeJenkins(down=True))
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    assert e.value.status == 0 and "nothing listens at 127.0.0.1:8080" in str(e.value)

    def leaky(method, url, headers, body, timeout, stream):
        raise OSError(f"proxy said: bad header {headers['Authorization']}")

    j = Jenkins(target(), transport=leaky)
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    words = str(e.value)
    assert TOKEN not in words and basic(USER, TOKEN)[6:] not in words and "•••" in words


def test_refusals_are_said_by_their_status():
    j = Jenkins(target(token="0" * 34), transport=FakeJenkins())
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    assert e.value.status == 401 and "refused the user name or the API token" in str(e.value)
    j = Jenkins(target(user="", token=""), transport=FakeJenkins())
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    assert e.value.status == 403 and "asks who you are" in str(e.value)
    got = j.get("/api/json", ok=(200, 403))
    assert got.status == 403 and j.version == "2.580.2"  # the version comes with a refusal too
    j = Jenkins(target(), transport=FakeJenkins(fail={"/queue/api/json": 500}))
    with pytest.raises(JenkinsError) as e:
        j.get("/queue/api/json")
    assert "HTTP 500: Jenkins failed" in str(e.value) and "Oops" not in str(e.value)  # its HTML page never shown


def test_an_answer_is_read_under_its_bounds():
    def big(method, url, headers, body, timeout, stream):
        return reply(200, {"X-Jenkins": "2.591", "Content-Length": str(MOST + 1)}, b"{}")

    with pytest.raises(JenkinsError, match="more than the"):
        Jenkins(target(), transport=big).get("/api/json")

    def endless(method, url, headers, body, timeout, stream):
        from liminal_libs.machines.endpoint import Reply
        return Reply(200, {"X-Jenkins": "2.591"}, iter([b"x" * (1 << 20)] * 5), lambda: None)

    with pytest.raises(JenkinsError, match="longer than"):
        Jenkins(target(), transport=endless).get("/api/json")
    clock = Clock()

    def slow(method, url, headers, body, timeout, stream):
        def pieces():
            for _ in range(3):
                clock.now += 6.0
                yield b"{"
        from liminal_libs.machines.endpoint import Reply
        return Reply(200, {"X-Jenkins": "2.591"}, pieces(), lambda: None)

    with pytest.raises(JenkinsError, match="not whole after 10 s"):
        Jenkins(target(), transport=slow, clock=clock).get("/api/json")

    def packed(method, url, headers, body, timeout, stream):
        return reply(200, {"X-Jenkins": "2.591", "Content-Encoding": "gzip"}, b"\x1f\x8b")

    with pytest.raises(JenkinsError, match="gzip-encoded"):
        Jenkins(target(), transport=packed).get("/api/json")


def test_every_reply_is_let_go():
    closed = []

    def once(method, url, headers, body, timeout, stream):
        from liminal_libs.machines.endpoint import Reply
        return Reply(404, {"X-Jenkins": "2.591"}, [b"<html/>"], lambda: closed.append(url))

    with pytest.raises(JenkinsError):
        Jenkins(target(), transport=once).get("/job/x/api/json")
    assert len(closed) == 1


# -- a change ------------------------------------------------------------------------------------------------------
def test_a_post_carries_the_crumb_and_its_session_cookie():
    fake = FakeJenkins()
    j = Jenkins(target(), transport=fake)
    done, said = j.post("/job/app/build")
    assert done.status == 201 and said == "its crumb sent in Jenkins-Crumb" and queued(done) == 101
    (m1, u1, _, _), (m2, u2, h2, b2) = fake.asked
    assert (m1, u1) == ("GET", BASE + "/crumbIssuer/api/json") and (m2, u2) == ("POST", BASE + "/job/app/build")
    assert h2["Jenkins-Crumb"] == CRUMB and h2["Cookie"] == COOKIE and b2 == b""
    assert j.words(f"{CRUMB} {SESSION} {TOKEN}") == "••• ••• •••"  # each taken out of what is said from then on


def test_no_crumb_is_sent_where_jenkins_issues_none():
    fake = FakeJenkins(csrf=False)
    j = Jenkins(target(), transport=fake)
    done, said = j.post("/job/app/buildWithParameters", form=[("BRANCH", "main & more")])
    assert done.status == 201 and said.startswith("no crumb")
    method, url, headers, body = fake.asked[-1]
    assert "Jenkins-Crumb" not in headers and "Cookie" not in headers
    assert headers["Content-Type"] == "application/x-www-form-urlencoded" and body == b"BRANCH=main+%26+more"


def test_a_crumb_not_as_jenkins_gives_one_is_refused():
    def odd(method, url, headers, body, timeout, stream):
        return reply(200, {"X-Jenkins": "2.591", "Content-Type": "application/json"},
                     b'{"crumb": "bad crumb\\n", "crumbRequestField": "Jenkins Crumb"}')

    with pytest.raises(JenkinsError, match="holds no crumb"):
        Jenkins(target(), transport=odd).crumb()


def test_a_jobs_path_is_quoted_and_never_leaves_the_address():
    assert job_path("app") == "/job/app" and job_path("team/app") == "/job/team/job/app"
    assert job_path(" my job ") == "/job/my%20job" and job_path("a?b#c") == "/job/a%3Fb%23c"
    assert job_path("/team/app/") == "/job/team/job/app"
    for name in ("", None, "..", "team/../x", "a//b", "a\nb", "x" * 256):
        with pytest.raises(ValueError):
            job_path(name)


def test_what_is_noted_of_each_request():
    seen = []
    j = Jenkins(target(), transport=FakeJenkins(down=True), note=lambda *a: seen.append(a))
    with pytest.raises(JenkinsError):
        j.get("/api/json")
    j = Jenkins(target(), transport=FakeJenkins(), note=lambda *a: seen.append(a))
    j.get("/api/json")
    assert [s[0] for s in seen] == [0, 200] and seen[0][2] and not seen[1][2]
    assert all(TOKEN not in s[2] for s in seen)


def test_the_basic_header_is_the_user_and_the_token():
    j = Jenkins(target(), transport=FakeJenkins())
    assert j.signed and base64.b64decode(j._auth[6:]).decode() == f"{USER}:{TOKEN}"
    assert not Jenkins(target(), transport=FakeJenkins(), anonymous=True).signed
