"""Jenkins' recipe for a container (0.2.0; service-containers-design §5.2, with the user's answers of 2026-11-25:
"Containers only", an agent container beside each server, its setup wizard with the unlock password shown once,
reporting to its makers off, images pinned by digest).

Two parts on the service's one network: `controller` (Jenkins itself, its pages and API on 8080, its home in a volume:
jobs, users, credentials, plugins and build history) and, once you made its node in Jenkins and set its secret, `agent`
(Jenkins' inbound agent, connecting to the controller over WebSocket on the same network: no port of its own). Jenkins'
usage statistics are never sent (hudson.model.UsageStatistics.disabled). No admin is seeded: Jenkins' setup wizard
makes yours, and Unlock… shows the password that opens it, once.

The pins: each image by its tag and its digest. A digest still UNREAD (all zeros) is refused before any plan, so
nothing is installed until a release reads the digests from Docker Hub (jenkins/jenkins, jenkins/inbound-agent)."""
from __future__ import annotations

from collections.abc import Mapping

from liminal_libs.instances import Refusal
from liminal_libs.machines.containedservice import UNREAD
from liminal_libs.machines.containers import ServiceSpec

OWNER = "jenkins"
AGENT_NAME = "liminal-agent"  # the node you make in Jenkins (Manage Jenkins › Nodes › New node, an inbound agent)
AGENT_SECRET = "JENKINS_AGENT_SECRET"  # its secret, as Jenkins shows it on that node's page: a pair through the login
WEB_PORT = 8080
MEMORY_MB = 2048
AGENT_MEMORY_MB = 1024
USAGE_OFF = "-Dhudson.model.UsageStatistics.disabled=true"  # its usage statistics never sent (decision 19 a)
HUB = "https://hub.docker.com/r/"

# the pins, by system: (part, reference, digest, its size in bytes when known); read when this release was made
PINS = {
    "linux": {
        "controller": dict(ref="docker.io/jenkins/jenkins:2.580.2-lts-jdk21", digest="sha256:74401de6a6f92e1afe1b02d1c8e3d0c33f263bfb5275dd8813f9150355f2367b", size=243724062, system="linux",
                           platforms=["linux/amd64", "linux/arm64"], version="2.580.2", licence="MIT",
                           page=HUB + "jenkins/jenkins", tar=True),
        "agent": dict(ref="docker.io/jenkins/inbound-agent:latest-jdk21", digest="sha256:38be636e3564556ded40bf0a1bcac52fd5c10e18e45997094cb4819e7bef6234", size=151876550, system="linux",
                      platforms=["linux/amd64", "linux/arm64"], licence="MIT", page=HUB + "jenkins/inbound-agent",
                      tar=True),
    },
    "windows": {
        "controller": dict(ref="docker.io/jenkins/jenkins:2.580.2-windowsservercore-ltsc2022", digest="sha256:442ba44321d1400dad55f514881f67967277b64e04ee36cc7dae94abcb8a1378", size=2544552783,
                           system="windows", platforms=["windows/amd64"], os_build=20348, version="2.580.2",
                           licence="MIT", page=HUB + "jenkins/jenkins", tar=False),
        "agent": dict(ref="docker.io/jenkins/inbound-agent:windowsservercore-ltsc2022", digest="sha256:78dfd65993ce5d8084663551c2ab53e3db941f74e13e22c5bd63e647c9507333", size=2436601105,
                      system="windows", platforms=["windows/amd64"], os_build=20348, licence="MIT",
                      page=HUB + "jenkins/inbound-agent", tar=False),
    },
}
HOME = {"linux": "/var/jenkins_home", "windows": "C:/ProgramData/Jenkins/.jenkins"}
AGENT_WORK = {"linux": "/home/jenkins/agent", "windows": "C:/Users/jenkins/Work"}


def spec(system: str, name: str, options: Mapping, agent: bool, pins: Mapping | None = None) -> ServiceSpec:
    """Jenkins' spec for a system: the controller, and its agent when `agent` (its secret is set). Options: `lan`,
    `memory_mb` (0: 2 GB), `ports` (the web port's host port first)."""
    pins = pins if pins is not None else PINS
    if system not in pins:
        raise Refusal(f"Jenkins has no {system} image")
    ports = list(options.get("ports") or [])
    host = int(ports[0]) if ports else WEB_PORT
    memory = int(options.get("memory_mb") or 0) or MEMORY_MB
    controller = {
        "name": "controller", "image": dict(pins[system]["controller"]),
        "ports": [{"name": "web", "container": WEB_PORT, "host": host, "lan": bool(options.get("lan")),
                   "about": "Jenkins' pages and its API"}],
        "volumes": [{"name": "home", "path": HOME[system],
                     "holds": "its jobs, users, credentials, plugins and build history",
                     "owner": 1000 if system == "linux" else None}],
        "env": {"JAVA_OPTS": USAGE_OFF},
        "readable": [{"name": "unlock", "volume": "home", "path": "secrets/initialAdminPassword",
                      "about": "the password that unlocks its setup"}],
        "memory": memory << 20, "health": {"port": "web", "path": "/login", "ready_s": 300}, "stop_s": 30}
    parts = [controller]
    if agent:
        parts.append({
            "name": "agent", "image": dict(pins[system]["agent"]),
            "env": {"JENKINS_URL": f"http://liminal-{OWNER}-{name}-controller:{WEB_PORT}/",
                    "JENKINS_AGENT_NAME": AGENT_NAME, "JENKINS_WEB_SOCKET": "true",
                    "JENKINS_AGENT_WORKDIR": AGENT_WORK[system]},
            "secrets": [{"variable": AGENT_SECRET, "env": "JENKINS_SECRET",
                         "about": "the secret Jenkins shows on the node's page"}],
            "memory": AGENT_MEMORY_MB << 20, "stop_s": 30})
    return ServiceSpec.of({"owner": OWNER, "name": name, "title": "Jenkins", "system": system, "parts": parts})
