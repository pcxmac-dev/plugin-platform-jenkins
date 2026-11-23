"""Jenkins asked over its remote access API, its JSON flavour (jenkins.io/doc/book/using/remote-access-api): one
address, as one user, nothing followed off it.

    j = Jenkins(target)                                       # sends nothing yet
    got = j.get("/api/json", tree="jobs[name,color]{0,200}")  # an Answer: its status, headers, body and JSON
    j.version                                                 # the X-Jenkins header of the last answer that said it
    got, crumb = j.post("/job/app/build")                     # the crumb asked first, sent when Jenkins gives one

The address is the user's (settings.py: JENKINS_URL), and every request goes to it and to nothing else: a path is asked
under it, never as an address of its own, and a redirect is never followed but said in words (where it pointed, without
its query). The token goes in an HTTP basic authorization header with the first request (Jenkins answers 403, not 401,
to a request without one: its "Authenticating scripted clients"), and only where the address allows it (`Target.sends`:
https, or this machine); it is taken out of every word said, with the header's encoding of it, a crumb and the session
cookie that came with the crumb. Each request waits TIMEOUT_S for each socket operation and reads MOST bytes at most,
whole within twice that wait; none is sent a second time. Sending is the library's (endpoint.requests_transport:
nothing taken from the environment, no proxy, no redirect followed); a test hands its own transport.
"""
from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode, urlsplit

from liminal_libs.instances import is_local
from liminal_libs.machines.endpoint import requests_transport, trouble
from liminal_libs.machines.rest import scrub

DEFAULT_URL = "http://127.0.0.1:8080"  # where Jenkins' installer and its packages have it answer
DEFAULT_PORT = 8080  # an address typed without a scheme and without a port is asked at Jenkins' own
TIMEOUT_S = 5.0  # seconds a request waits for each socket operation (the connection, each read)
MOST = 4 << 20  # bytes read of one answer at most (two hundred jobs are some 60 kB)
AGENT = "Liminal platform plugin (Jenkins)"  # a fixed name: nothing of the user's, nothing of the machine's
OK = (200, 201, 202, 204)
REDIRECTS = frozenset({301, 302, 303, 307, 308})
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_-]{0,63}$")  # X-Jenkins: 2.580.2, 2.591, 2.592-SNAPSHOT
FIELD = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # the crumb's request field: Jenkins-Crumb
CRUMB = re.compile(r"^[A-Za-z0-9+/=._:-]{1,512}$")  # a crumb: a hash, in hexadecimal
SESSION = re.compile(r"(?:^|[\s,;])(JSESSIONID[A-Za-z0-9._-]{0,64})=([A-Za-z0-9._~+/=-]{1,512})")  # Set-Cookie's
QUEUED = re.compile(r"/queue/item/(\d{1,18})/?$")  # a build's answer names its queue item in Location
NAME_MOST = 255  # characters of one part of a job's name


def _control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


@dataclass(frozen=True)
class Target:
    """Where Jenkins is asked and as whom (settings.parse makes one): its address (`base`: the scheme, the host, the
    port unless it is the scheme's own, and the path Jenkins runs under), its host and port, whether it is https, the
    user and the API token (never shown: repr leaves it out), and what was wrong with the settings, in words that never
    hold the token. An empty `base`: no address to ask (why, in `problems`)."""

    base: str = ""
    host: str = ""
    port: int = 0
    tls: bool = False
    user: str = ""
    token: str = field(default="", repr=False)
    problems: tuple[str, ...] = ()

    @property
    def local(self) -> bool:
        """Whether Jenkins is asked on this machine (127.0.0.1, localhost, ::1)."""
        return is_local(self.host)

    @property
    def keyed(self) -> bool:
        """Whether a user and a token are both set."""
        return bool(self.user and self.token)

    @property
    def sends(self) -> bool:
        """Whether the token is sent: both set, and the address https or this machine's (plain http to another machine
        would carry it readable on the way)."""
        return self.keyed and (self.tls or self.local)

    @property
    def withheld(self) -> bool:
        """A user and a token set, and not sent: plain http to another machine."""
        return self.keyed and not self.sends

    @property
    def at(self) -> str:
        """Its host and port, as words name them: 127.0.0.1:8080, [::1]:8080."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


class JenkinsError(Exception):
    """A request that failed, in words that hold no secret: its HTTP status (0: no answer came) and Jenkins' version
    when that answer said it (X-Jenkins: Jenkins answered, though not as asked)."""

    def __init__(self, message: str, status: int = 0, version: str = ""):
        super().__init__(message)
        self.status = status
        self.version = version


@dataclass
class Answer:
    """An answer: its status, its headers (by lowercased name), its body, how long it took, its JSON (None: none)."""

    status: int
    headers: dict[str, str]
    body: bytes = b""
    seconds: float = 0.0
    data: object = None

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


def job_path(name) -> str:
    """A job's path under Jenkins' address, from its name (a folder's job as folder/job): /job/app, /job/team/job/app,
    each part quoted. ValueError in words for a name that is none (empty, a part . or .., a control character)."""
    text = str(name if name is not None else "").strip().strip("/")
    parts = [p.strip() for p in text.split("/")] if text else []
    if not parts or any(not p or p in (".", "..") or len(p) > NAME_MOST or _control(p) for p in parts):
        raise ValueError(f"not a job's name: {text[:80]!r} (a job in a folder is folder/job)")
    return "".join(f"/job/{quote(p, safe='')}" for p in parts)


def queued(answer: Answer) -> int | None:
    """The queue item a build's answer names (Location: .../queue/item/42/), None when it names none."""
    try:
        path = urlsplit(answer.header("location").strip()).path
    except ValueError:
        return None
    found = QUEUED.search(path)
    return int(found.group(1)) if found else None


class Jenkins:
    """Jenkins at one address, as one user (the module's docstring). `transport(method, url, headers, body, timeout,
    stream)` -> endpoint.Reply is a test's stand-in, else the library's requests_transport; `note(status, seconds,
    error)` is told of every request as it ends (what api_facts says); `anonymous`: the token is not sent, even where it
    may be. Making one sends nothing."""

    def __init__(self, target: Target, *, transport: Callable | None = None, timeout: float = TIMEOUT_S,
                 clock: Callable[[], float] = time.monotonic, note: Callable | None = None, anonymous: bool = False):
        if not target.base:
            raise ValueError(target.problems[0] if target.problems else "no address to ask Jenkins at")
        self.target = target
        self._transport = transport or requests_transport
        self._timeout = float(timeout)
        self._clock = clock
        self._note = note
        self._auth = ""
        if target.sends and not anonymous:
            pair = f"{target.user}:{target.token}".encode("utf-8")
            self._auth = "Basic " + base64.b64encode(pair).decode("ascii")
        self._secrets = [s for s in (target.token, self._auth, self._auth[6:]) if s]
        self.version = ""  # the X-Jenkins header of the last answer that said it

    @property
    def signed(self) -> bool:
        """Whether its requests carry the token."""
        return bool(self._auth)

    def hide(self, *values: str) -> None:
        """Values taken out of every word said from now on (a crumb, a session cookie), as the token is."""
        self._secrets += [str(v) for v in values if v]

    def words(self, text) -> str:
        """`text` with every secret taken out (rest.scrub: each as given, and each of its lines)."""
        return scrub(str(text), self._secrets)

    def url(self, path: str, params: Mapping | None = None) -> str:
        """`path` under Jenkins' address, with `params` (their None ones left out). A path is never an address of its
        own: whatever it holds, it is asked of this address."""
        text = str(path or "")
        if (not text.startswith("/") or text.startswith("//") or "://" in text or _control(text)
                or any(c in text for c in " #?\\")):
            raise ValueError(f"not a path under Jenkins' address: {text[:80]!r}")
        query = {k: v for k, v in (params or {}).items() if v is not None}
        return self.target.base + text + ("?" + urlencode(query) if query else "")

    def get(self, path: str, tree: str | None = None, ok: Iterable[int] = OK) -> Answer:
        """A GET of one of Jenkins' .../api/json pages, `tree` naming what of it to give (only what is shown)."""
        return self.ask("GET", path, params={"tree": tree} if tree else None, ok=ok)

    def crumb(self) -> tuple[dict[str, str], str]:
        """The headers a change goes with when Jenkins' CSRF protection asks for a crumb, and in words which it was:
        GET /crumbIssuer/api/json, whose 404 says it issues none (nothing to send). A crumb is tied to the web session
        it was issued in, so the session cookie that came with it goes too (Jenkins' CSRF page: "Note the Set-Cookie
        response header"). A request authenticated with an API token is exempt from the protection, and a crumb does it
        no harm."""
        got = self.ask("GET", "/crumbIssuer/api/json", ok=(200, 404))
        if got.status == 404:
            return {}, "no crumb: Jenkins' CSRF protection issues none"
        data = got.data if isinstance(got.data, Mapping) else {}
        name, value = str(data.get("crumbRequestField") or ""), str(data.get("crumb") or "")
        if not FIELD.match(name) or not CRUMB.match(value):
            raise JenkinsError("GET /crumbIssuer/api/json: its answer holds no crumb as Jenkins gives one "
                               "(crumbRequestField and crumb)", got.status, self.version)
        self.hide(value)
        headers = {name: value}
        cookie = SESSION.search(got.header("set-cookie"))
        if cookie:
            self.hide(cookie.group(2))
            headers["Cookie"] = f"{cookie.group(1)}={cookie.group(2)}"
        return headers, f"its crumb sent in {name}"

    def post(self, path: str, form=None) -> tuple[Answer, str]:
        """A change: the crumb asked first (crumb), then the POST with it; its answer, and the crumb in words."""
        extra, said = self.crumb()
        return self.ask("POST", path, form=form, headers=extra), said

    def ask(self, method: str, path: str, *, params: Mapping | None = None, form=None,
            headers: Mapping[str, str] | None = None, ok: Iterable[int] = OK) -> Answer:
        """One request and its whole answer when its status is one of `ok`; else a JenkinsError in words. `form`: a
        POST's fields, sent form-encoded as Jenkins' own pages send them (pairs, or a mapping); a POST without one sends
        an empty body. A redirect is never followed (the module's docstring)."""
        method = str(method).upper()
        url = self.url(path, params)
        lead = f"{method} {self._where(path)}"
        sent = {"Accept": "application/json", "User-Agent": AGENT, "Accept-Encoding": "identity"}
        if self._auth:
            sent["Authorization"] = self._auth
        body = None
        if form is not None:
            pairs = list(form.items()) if isinstance(form, Mapping) else list(form)
            body = urlencode(pairs).encode("utf-8")
            sent["Content-Type"] = "application/x-www-form-urlencoded"
        elif method == "POST":
            body = b""
        sent.update(headers or {})
        started = self._clock()
        try:
            answer = self._send(method, url, sent, body, started, lead)
            said = answer.header("x-jenkins").strip()
            version = said if VERSION.match(said) else ""
            if version:
                self.version = version
            if answer.status in REDIRECTS:
                raise JenkinsError(self._redirected(lead, answer), answer.status, version)
            if answer.status not in set(ok):
                raise JenkinsError(self.words(f"{lead}: {self._refusal(answer)}"), answer.status, version)
        except JenkinsError as e:
            self._told(e.status, started, str(e))
            raise
        self._told(answer.status, started, "")
        return answer

    # -- how ----------------------------------------------------------------------------------------------------------
    def _send(self, method: str, url: str, headers: dict, body: bytes | None, started: float, lead: str) -> Answer:
        reply = None
        try:
            try:
                reply = self._transport(method, url, headers, body, self._timeout, False)
            except Exception as e:  # noqa: BLE001 - the connection's trouble, in words
                raise JenkinsError(self.words(f"{lead}: {trouble(e, self.target.at, self._timeout, self._secrets)}")) \
                    from None
            return self._whole(reply, started, lead)
        finally:
            if reply is not None:
                try:
                    reply.close()
                except Exception:  # noqa: BLE001 - a connection that will not close is let go
                    pass

    def _whole(self, reply, started: float, lead: str) -> Answer:
        """A reply read under the bounds: refused past MOST bytes (by what it says its length is, before a byte is read;
        else as it comes), and when it is not whole within twice the wait; a redirect's body is not read at all."""
        status = int(reply.status)
        headers = _lower(reply.headers)
        if status in REDIRECTS:
            return Answer(status, headers, b"", self._clock() - started)
        coding = headers.get("content-encoding", "").strip().lower()
        if coding not in ("", "identity"):
            raise JenkinsError(f"{lead}: its answer came {coding[:20]}-encoded, which was not asked for: not read",
                               status)
        length = headers.get("content-length", "").strip()
        if length.isdigit() and int(length) > MOST:
            raise JenkinsError(f"{lead}: its answer is {int(length):,} bytes, more than the {MOST:,} read of one: "
                               "not read", status)
        ends = started + 2 * self._timeout
        got, pieces = 0, []
        try:
            for piece in reply.chunks:
                got += len(piece)
                if got > MOST:
                    raise JenkinsError(f"{lead}: its answer is longer than {MOST:,} bytes: not read", status)
                if self._clock() > ends:
                    raise JenkinsError(f"{lead}: its answer was not whole after {2 * self._timeout:g} s: not read",
                                       status)
                pieces.append(bytes(piece))
        except JenkinsError:
            raise
        except Exception as e:  # noqa: BLE001 - its body broke off
            words = trouble(e, self.target.at, self._timeout, self._secrets)
            raise JenkinsError(self.words(f"{lead}: its answer broke off: {words}"), status) from None
        body = b"".join(pieces)
        return Answer(status, headers, body, self._clock() - started, _json(body, headers))

    def _refusal(self, answer: Answer) -> str:
        """Why an answer is not the one asked for, in words (Jenkins' error pages are HTML: only a phrase of theirs that
        says why is looked for in them, never shown)."""
        status = answer.status
        text = answer.body[:4000].decode("utf-8", "replace")
        if status == 401:
            return ("HTTP 401: Jenkins refused the user name or the API token (wrong, or revoked)" if self._auth
                    else "HTTP 401: Jenkins asks who you are")
        if status == 403:
            if "No valid crumb" in text:
                return "HTTP 403: no valid crumb was included (Jenkins' CSRF protection refused it)"
            return ("HTTP 403: Jenkins does not let this user do it (its permissions)" if self._auth
                    else "HTTP 403: Jenkins asks who you are (JENKINS_USER and JENKINS_TOKEN)")
        if status == 404:
            return "HTTP 404: not there"
        if status >= 500:
            return f"HTTP {status}: Jenkins failed (its log says why)"
        return f"HTTP {status}"

    def _redirected(self, lead: str, answer: Answer) -> str:
        """A redirect in words: where it pointed (its scheme, host, port and path; never a user, a password or a query),
        not followed."""
        location = answer.header("location").strip()
        where = "another address"
        if location:
            try:
                parts = urlsplit(location)
                host = parts.hostname or ""
                port = f":{parts.port}" if parts.port else ""
                start = f"{parts.scheme}://{host}{port}" if host else self.target.base
                where = "".join(c for c in start + (parts.path or "/") if ord(c) >= 32 and ord(c) != 127)[:160]
            except ValueError:
                where = "an address that is none"
        return self.words(f"{lead}: Jenkins answered HTTP {answer.status}, sending it on to {where}: not followed "
                          f"(every request goes to {self.target.base} alone; JENKINS_URL may want https, or the path "
                          "Jenkins runs under)")

    def _where(self, path: str) -> str:
        """A path as an error names it: without its query, secrets taken out, 120 characters at most."""
        return self.words(str(path or "/").split("?", 1)[0])[:120]

    def _told(self, status: int, started: float, error: str) -> None:
        if self._note is None:
            return
        try:
            self._note(int(status), max(0.0, self._clock() - started), error)
        except Exception:  # noqa: BLE001 - what is noted is extra: the request is answered all the same
            pass


def _lower(headers) -> dict[str, str]:
    try:
        return {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    except (TypeError, ValueError):
        return {}


def _json(body: bytes, headers: Mapping[str, str]):
    """An answer's JSON (None when it holds none): read when its type says JSON or it begins as JSON does."""
    if not body or ("json" not in headers.get("content-type", "") and body.lstrip()[:1] not in (b"{", b"[")):
        return None
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        return None
