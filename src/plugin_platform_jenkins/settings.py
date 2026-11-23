"""The plugin's settings, read through the Login interface of the app it is attached to and nothing else (the user,
2026-11-08: "all the settings are stored on a login-app db"): the platform's EnvironmentLogin today, the login app's
pairs once the platform binds it, and, not attached (the command line), an EnvironmentLogin of its own. Each setting is
a pair named by its variable (JENKINS_TOKEN is the pair `jenkins-token`). There is no settings file: a value is never
written anywhere, and the token is never shown, logged or returned; only whether it is set is said."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from liminal_libs.apps import EnvironmentLogin
from liminal_libs.machines.endpoint import base_url, parse_address
from liminal_libs.machines.rest import scrub
from liminal_libs.sources.keys import KeyVar

from .client import DEFAULT_PORT, DEFAULT_URL, Target

URL = "JENKINS_URL"
USER = "JENKINS_USER"
TOKEN = "JENKINS_TOKEN"
NAMES = (URL, USER, TOKEN)
TOKEN_PAGE = "your name, top right › Security › API Token › Add new Token (JENKINS_URL/me/security)"
KEYS = (
    KeyVar(URL, label="Jenkins URL", secret=False,
           hint=(f"optional: where Jenkins answers, {DEFAULT_URL} unless set, with the path it runs under if it has "
                 "one (http://127.0.0.1:8080/jenkins); plain http to this machine only, https to another")),
    KeyVar(USER, label="User", secret=False, hint="your Jenkins user ID, whose API token is below"),
    KeyVar(TOKEN, label="API token", hint=f"an API token of that user ({TOKEN_PAGE}), never your password"),
)


def _control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def parse(values: Mapping[str, str], problems: Iterable[str] = ()) -> Target:
    """The settings from their values by variable (one not set: left out, or empty): where Jenkins is asked
    (JENKINS_URL, the default unless set) and as whom, and what was wrong with them, in words that never hold the
    token."""
    said = list(problems)
    url = str(values.get(URL) or "").strip() or DEFAULT_URL
    user = str(values.get(USER) or "").strip()
    token = str(values.get(TOKEN) or "").strip()
    if user and (":" in user or _control(user)):
        said.append(f"{USER} holds a colon or a line break, which no user name holds: enter it again")
        user = ""
    if token and _control(token):
        said.append(f"{TOKEN} holds a line break: enter it again, alone (nothing was sent with it)")
        token = ""
    if token and not user:
        said.append(f"{TOKEN} is set without {USER}: the token goes with its user's name, so no one is signed in")
    try:
        host, port, tls, prefix = parse_address(url, DEFAULT_PORT)
        base = base_url(host, port, tls, prefix)
    except ValueError as e:
        words = scrub(str(e), (token,) if token else ())
        return Target(user=user, token=token, problems=(f"{URL} is not an address Jenkins is asked at: {words}", *said))
    return Target(base, host, port, tls, user, token, tuple(said))


def read(login=None) -> Target:
    """The settings as `login` furnishes them (the login of the app the plugin is attached to), else an
    EnvironmentLogin's; a login that cannot be asked furnishes none, and says so (Jenkins is then asked at its default
    address, as no one)."""
    asked = login if login is not None else EnvironmentLogin()
    try:
        values = asked.variables(NAMES)
    except Exception as e:  # noqa: BLE001 - a login that cannot be asked: nothing set, and why
        return parse({}, (f"the settings could not be read from the login ({type(e).__name__}): {DEFAULT_URL} is "
                          "asked, as no one",))
    return parse(values or {})
