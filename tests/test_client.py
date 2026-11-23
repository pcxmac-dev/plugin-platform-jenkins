"""Jenkins' client and the settings it is made from: the address as typed, the token sent only where it may be (https,
or this machine) and never in a word said, every request under the address with nothing followed off it (a redirect
the answer only where its asker takes it), an answer read under its bounds, the crumb and its session cookie, a job's
path quoted. Jenkins is a stand-in (stand_ins.py)."""
from __future__ import annotations

import base64
import json

import pytest

from liminal_libs.apps import EnvironmentLogin
from plugin_platform_jenkins import client, settings
from plugin_platform_jenkins.client import (MOST, Answer, Jenkins, JenkinsError, challenged, job_path, landing, queued,
                                            same_page)
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


def test_jenkins_clis_names_are_read_after_the_plugins_own():
    """jenkins-cli.jar's own JENKINS_USER_ID and JENKINS_API_TOKEN are read too, the plugin's names first."""
    keys = {k.name: k for k in settings.KEYS}
    assert keys["JENKINS_USER"].aliases == ("JENKINS_USER_ID",)
    assert keys["JENKINS_TOKEN"].aliases == ("JENKINS_API_TOKEN",) and keys["JENKINS_URL"].aliases == ()
    t = settings.read(EnvironmentLogin(env={"JENKINS_USER_ID": "bob", "JENKINS_API_TOKEN": "b" * 34}))
    assert (t.user, t.token, t.sends) == ("bob", "b" * 34, True)
    t = settings.read(EnvironmentLogin(env={"JENKINS_USER": USER, "JENKINS_TOKEN": TOKEN, "JENKINS_USER_ID": "bob",
                                            "JENKINS_API_TOKEN": "b" * 34}))
    assert (t.user, t.token) == (USER, TOKEN)


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


def test_a_redirect_is_the_answer_only_where_its_asker_takes_it():
    """A build's 303 to the queue item it joined, its 302 back to the job's own page: the answer when its status is
    among `ok` and `lands` takes where it points; never followed, and any other still refused in words."""
    def answers(status, location):
        def transport(method, url, headers, body, timeout, stream):
            transport.asked.append(url)
            return reply(status, {"Location": location})
        transport.asked = []
        return transport

    def back(status, where):
        return same_page(where, BASE + "/job/app")

    t = answers(303, "/queue/item/7/")
    got = Jenkins(target(), transport=t).ask("POST", "/job/app/buildWithParameters", ok=(201, 303))
    assert got.status == 303 and queued(got) == 7 and t.asked == [BASE + "/job/app/buildWithParameters"]
    for location in (".", "/job/app/.", BASE + "/job/app/", BASE + "/job/app/."):  # Jenkins' "." however it is said
        assert Jenkins(target(), transport=answers(302, location)).ask("POST", "/job/app/build", ok=(201, 302),
                                                                        lands=back).status == 302
    with pytest.raises(JenkinsError, match="sending it on to https://sso.example.com/login: not followed"):
        Jenkins(target(), transport=answers(302, "https://sso.example.com/login")).ask(
            "POST", "/job/app/build", ok=(201, 302), lands=back)
    with pytest.raises(JenkinsError, match="not followed"):
        Jenkins(target(), transport=answers(303, "/queue/item/7/")).ask("POST", "/job/app/build")  # not among ok
    asked = BASE + "/jenkins/job/my%20job/build"
    assert landing(asked, Answer(302, {"location": "."})) == BASE + "/jenkins/job/my%20job/"
    assert landing(asked, Answer(302, {"location": "../../../x"})) == BASE + "/x"
    assert landing(asked, Answer(302, {})) == "" and landing(asked, Answer(302, {"location": "http://x:99999/"})) == ""
    assert same_page(BASE + "/jenkins/job/my%20job/", BASE + "/jenkins/job/my job")
    assert not same_page("", BASE + "/job/app") and not same_page(BASE + "/job/app/x", BASE + "/job/app")


def test_the_secrets_are_taken_out_before_any_word_is_cut():
    """An answer that echoes the token where its words are cut (a long Location's path, a Content-Encoding header)
    leaves no piece of it in what is said."""
    long = "https://sso.example.com/" + "a" * 120 + TOKEN
    with pytest.raises(JenkinsError) as e:
        Jenkins(target(), transport=FakeJenkins(redirect=long)).get("/api/json")
    said = str(e.value)
    assert TOKEN[:16] not in said and "a" * 120 + "•••" in said
    for echoed in (TOKEN, basic(USER, TOKEN)[6:]):
        def packed(method, url, headers, body, timeout, stream, echoed=echoed):
            return reply(200, {"X-Jenkins": "2.591", "Content-Encoding": echoed}, b"{}")

        with pytest.raises(JenkinsError) as e:
            Jenkins(target(), transport=packed).get("/api/json")
        said = str(e.value)
        assert echoed[:20].lower() not in said.lower() and "•••-encoded" in said, said


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
    j = Jenkins(target(), transport=FakeJenkins(starting=True))  # its loading page, while it starts or restarts
    with pytest.raises(JenkinsError) as e:
        j.get("/api/json")
    said = str(e.value)
    assert e.value.status == 503 and e.value.version == "" and "failed" not in said
    assert said == "GET /api/json: HTTP 503: Jenkins is starting or restarting, and answers once it is ready"


def test_jenkins_own_refusal_of_a_token_is_known_by_its_challenge():
    """A refused token: 401 with WWW-Authenticate: Basic realm="Jenkins", and no X-Jenkins on it."""
    def answer(status, challenge):
        return Answer(status, {"www-authenticate": challenge} if challenge is not None else {})

    assert challenged(answer(401, 'Basic realm="Jenkins"')) and challenged(answer(401, ' basic Realm = "Jenkins" '))
    for status, challenge in ((401, 'Basic realm="Restricted"'), (401, 'Basic realm="Jenkins"\nX: y'), (401, None),
                              (403, 'Basic realm="Jenkins"'), (401, 'Negotiate')):
        assert not challenged(answer(status, challenge)), (status, challenge)
    j = Jenkins(target(token="0" * 34), transport=FakeJenkins())
    got = j.get("/api/json", ok=(200, 401, 403))
    assert got.status == 401 and challenged(got) and j.version == "" and j.unmarked == 1


def test_what_answers_without_x_jenkins_is_counted():
    """The GETs that no answer with X-Jenkins came to: one without it, or none at all; a POST's answer is never
    counted (Jenkins marks none)."""
    j = Jenkins(target(), transport=FakeJenkins(jenkins=False, anonymous=True))
    j.get("/api/json")
    assert (j.unmarked, j.version) == (1, "")
    j = Jenkins(target(), transport=FakeJenkins())
    j.get("/api/json")
    assert (j.unmarked, j.version) == (0, "2.580.2")
    j = Jenkins(target(), transport=FakeJenkins(down=True))
    with pytest.raises(JenkinsError):
        j.get("/api/json")
    assert j.unmarked == 1
    j = Jenkins(target(), transport=FakeJenkins())
    done, _ = j.post("/job/app/build")
    assert done.status == 201 and "x-jenkins" not in done.headers and j.unmarked == 0


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


@pytest.mark.parametrize("field, crumb", [("Jenkins-Crumb\n", CRUMB), ("Jenkins-Crumb", CRUMB + "\n")])
def test_a_crumb_with_a_line_break_after_it_is_refused(field, crumb):
    """A field or a crumb with a line break after it matches no pattern whole: refused in words, before a POST is
    made with it (which the transport would refuse, sounding like a write that may have been done)."""
    def odd(method, url, headers, body, timeout, stream):
        return reply(200, {"X-Jenkins": "2.591", "Content-Type": "application/json"},
                     json.dumps({"crumb": crumb, "crumbRequestField": field}).encode())

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
