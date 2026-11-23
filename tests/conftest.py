"""Nothing in these tests asks Jenkins, starts a process or reaches the network: Jenkins is a stand-in's (stand_ins.py:
a transport answering as Jenkins' JSON API does), and so is what is installed here (its finders). The guard is the
Docker plugin's, made so no broad `except` of the plugin's can swallow it: a process started (subprocess's run and
Popen), a connection made or a name looked up (socket's create_connection, getaddrinfo and connect), the library's real
transport or one of the real finders (the service control manager, systemctl) reached raises `Reached`, a BaseException,
and fails the test at its end as well; no program is found on PATH (shutil.which), and Jenkins' variables and Liminal's
are taken out of this process's environment."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading

import pytest

try:
    import requests  # noqa: F401 - imported before the guard, as the plugins' tests do: urllib3 binds a socket then
except ImportError:  # (not every test run has it)
    pass

from plugin_platform_jenkins import client, here

STOOD_IN = [
    (subprocess, "subprocess", ("run", "Popen")),
    (socket, "socket", ("create_connection", "getaddrinfo")),
    (socket.socket, "socket.socket", ("connect", "connect_ex")),
    (client, "the library's transport", ("requests_transport",)),
    (here, "the real finders", ("_service_state", "_unit_state")),
]


class Reached(BaseException):
    """A test reached for real what it must stand in for."""


@pytest.fixture(autouse=True)
def nothing_runs(monkeypatch):
    reached: list[str] = []

    def refuse(what):
        def stand_in(*args, **kwargs):
            __tracebackhide__ = True  # its arguments (a request's headers, with the token's) never printed
            reached.append(what)
            raise Reached(f"the test reached {what} for real: give the plugin a stand-in")
        return stand_in

    for owner, said, names in STOOD_IN:
        for name in names:
            monkeypatch.setattr(owner, name, refuse(f"{said}: {name}"))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    for name in list(os.environ):
        if name.upper().startswith(("JENKINS_", "LIMINAL_")):
            monkeypatch.delenv(name, raising=False)
    yield reached
    assert not reached, f"the test reached the outside for real: {reached}"


@pytest.fixture(autouse=True)
def no_thread_left():
    """A test leaves no thread of its own behind: the plugin holds none between asks."""
    before = set(threading.enumerate())
    yield
    left = [t.name for t in threading.enumerate() if t not in before and t.is_alive()]
    assert not left, f"threads left running: {left}"
