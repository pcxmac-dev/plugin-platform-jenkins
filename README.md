# plugin-platform-jenkins

Jenkins for Liminal: whether Jenkins is installed here or answers at its address, its version, and once it answers to
you its jobs, build queue and nodes; a job's build asked once the platform's page has confirmed it.

The user's words (2026-11-22): a new class of plugins, "Continuous Integration", with three of them: Jenkins, GoCD and
Buildbot. This is the first.

## What it does

A machine plugin of the platform (`liminal_libs.machines.MachinePlugin`, plugin API 2.2), drawn under the platform's
Continuous Integration plugins (`SECTION = "ci"`; a platform that does not draw that section yet keeps it under
Machine plugins), its icon Jenkins' mark (`ICON = "jenkins"`, once the library's icons.js draws it).

- **Installed here** (here.py), looked at without asking Jenkins: on Windows its service (`jenkins`, as Jenkins'
  installer makes it) and its state, asked of the service control manager (no process, no administrator's rights),
  and its war file in `%ProgramFiles%\Jenkins`; on Linux its systemd unit (`jenkins.service`), its file where the
  jenkins.io packages put it and its state (`systemctl show`, a read that ends: said as not known where systemd does
  not run), and its war file (`/usr/share/java/jenkins.war`, and `/usr/share/jenkins` and `/usr/lib/jenkins` for older
  packages). On any other system only its address says whether it is there.
- **Its address and version**: Jenkins at `JENKINS_URL` (`http://127.0.0.1:8080` unless set), its version from the
  `X-Jenkins` header every answer carries. Something answering there without that header is said not to be Jenkins.
- **Once it answers to you**, three tables, each one GET of Jenkins' JSON API with a tree naming only what is shown
  (200 rows at most): **Jobs** (each one's kind, state as its colour says it and whether it builds now, its last
  build's number and result, when it started and how long it took, and Build…), **Build queue** (each waiting build:
  since when, why in Jenkins' words, blocked, stuck or waiting for an executor) and **Nodes** (online, offline or taken
  offline and why, its executors and how many are busy, its labels). A folder is listed, its jobs not yet.
- **A build** (`build`), through a form the page confirms first: the job is looked at (there, buildable, its
  parameters), then `POST /job/NAME/build`, or `/buildWithParameters` for a job with parameters (their defaults
  unless typed, as `NAME=value` pairs joined by `&`, sent form-encoded), with Jenkins' crumb when its CSRF protection
  issues one (`/crumbIssuer/api/json`, sent in its request field with the session cookie it came with; a request
  authenticated with an API token is exempt, and the crumb does it no harm). Refused in words, before anything
  changes, for a job not there, disabled or no job at all (a folder), and for a parameter the job does not have. The
  queue item it became is said; a parameter's value never is.
- **When Jenkins is not here**: the page says how to install it, from Jenkins' own pages (read 2026-11-22), for
  Windows (a Java 21 or 25, Jenkins' Windows installer of the LTS line, its unlock password, an API token) and Linux
  (the jenkins.io apt or rpm LTS repository, OpenJDK 21, `systemctl enable` and `start`, in a WSL distribution systemd
  first). This release installs, starts and stops nothing; when Jenkins is installed but does not answer, the page says
  what to do (its service stopped, its port another).

It is valid while Jenkins answers at its address (signed in or not); not valid, the page shows why and, when Jenkins is
not installed here, how to install it. Nothing runs on its own: the plugin reads when the platform asks, keeps what it
read 30 s (a build, Read again and new settings read anew), holds no thread and no process between asks, and forgets
what it read when detached.

## Its settings

Read through the plugin's login alone (the platform's EnvironmentLogin today, the login app's pairs once it is bound;
no settings file):

- `JENKINS_URL`: where Jenkins answers, `http://127.0.0.1:8080` unless set, with the path it runs under if it has one
  (`http://127.0.0.1:8080/jenkins`).
- `JENKINS_USER`: your Jenkins user ID.
- `JENKINS_TOKEN` (a secret): an API token of that user (your name, top right › Security › API Token › Add new
  Token), never your password.

The token is sent in an HTTP basic authorization header with the first request (Jenkins answers 403, not 401, to one
without it), to `JENKINS_URL` alone, and only over https or to this machine (127.0.0.1, localhost, ::1): over plain
http to another machine it is not sent, Jenkins is read as no one, and the page says why. No redirect is followed:
one is said in words, where it pointed without its query. The token, its header's encoding, a crumb and a session
cookie are taken out of every word the plugin says; none is ever printed, logged or returned. Every request waits 5 s
for each socket operation and reads 4 MB of an answer at most.

## Its API

What it attaches to, as its page shows it (plugin API 2.2: `apis.py`, every address read on its maker's pages on
2026-11-22):

- **Jenkins remote access API** (the Jenkins project): the
  [remote access API](https://www.jenkins.io/doc/book/using/remote-access-api/),
  [authenticating scripted clients](https://www.jenkins.io/doc/book/system-administration/authenticating-scripted-clients/),
  [CSRF protection](https://www.jenkins.io/doc/book/security/csrf-protection/), the javadoc of the objects it reads
  ([Job](https://javadoc.jenkins.io/hudson/model/Job.html), [Run](https://javadoc.jenkins.io/hudson/model/Run.html),
  [BallColor](https://javadoc.jenkins.io/hudson/model/BallColor.html),
  [Queue.Item](https://javadoc.jenkins.io/hudson/model/Queue.Item.html),
  [ComputerSet](https://javadoc.jenkins.io/hudson/model/ComputerSet.html),
  [Computer](https://javadoc.jenkins.io/hudson/model/Computer.html),
  [CrumbIssuer](https://javadoc.jenkins.io/hudson/security/csrf/CrumbIssuer.html)), the installing guides for
  [Windows](https://www.jenkins.io/doc/book/installing/windows/) and
  [Linux](https://www.jenkins.io/doc/book/installing/linux/), the
  [Java support policy](https://www.jenkins.io/doc/book/platform-information/support-policy-java/), the
  [LTS changelog](https://www.jenkins.io/changelog-stable/). Fourteen parts, six used; twenty-one calls, the seven it
  makes each named with what it makes it for (two of them writes: the builds).
- **Windows service control manager** (Microsoft): OpenSCManagerW, OpenServiceW, QueryServiceStatus and
  CloseServiceHandle used; StartServiceW and ControlService not.
- **systemd's systemctl**: `systemctl show jenkins.service` used; start, stop and enable not.

`api_facts()` says what it learned while it ran, asking nothing: Jenkins' address, version and whether you were
signed in as last read, its requests and their last answer, whether its CSRF protection issued a crumb at the last
build, and what was found installed here. `LIMINAL_VENDOR_PAGES=1 pytest tests/test_apis.py` checks that every address
on the cards still answers.

## Its hooks

`present` (installed here or answering), `status` (the summary, the facts, `tables`, `forms`, `actions`), `refresh()`
(Jenkins read again now: a read, its READ_HOOKS) and `build(job, parameters)` (a change, confirmed by the page first).

## From the command line

```
python -m plugin_platform_jenkins status
python -m plugin_platform_jenkins jobs
python -m plugin_platform_jenkins build app
python -m plugin_platform_jenkins build deploy "BRANCH=main&DRY_RUN=true"
```

The settings are this shell's environment variables there; typing `build` is its confirmation.

## Not in this release

Jenkins installed, started or stopped from here; a folder's jobs listed; a build's log, its stop, a queue item's
cancel, a node taken offline; and Jenkins' mark in the library's icons.js (the tray shows none for it until then).
