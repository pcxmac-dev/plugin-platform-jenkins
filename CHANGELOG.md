# Changelog

## 0.1.0 (2026-11-23)

The first release: Jenkins for the platform, the first plugin of its Continuous Integration section (the user,
2026-11-22: a "Continuous Integration" class of plugins, with Jenkins, GoCD and Buildbot). Needs liminal-libs>=1.63.0
(1.62.0's machines/endpoint.py sends its requests; 1.63.0 reads what it says of its interface).

- **Present** when Jenkins is installed here or answers at its address; **valid** while it answers. Installed here
  (here.py): on Windows its service `jenkins` and its state, asked of the service control manager (no process, no
  administrator's rights), and its war file in `%ProgramFiles%\Jenkins`; on Linux its unit `jenkins.service`, its file
  and its state (`systemctl show`), and its war file where the jenkins.io packages put it. Every look is a finder a
  test stands in for.
- **The page**: the address and Jenkins' version (its `X-Jenkins` header), whether you are signed in and why not, and
  once Jenkins answers to you three tables, each one GET of its JSON API asking with a tree for only what is shown (200
  rows at most): its jobs (kind, state, last build, when, Build…), its build queue and its nodes. A failure is said in
  words, never raised; what was read is kept 30 s, Read again (`refresh`) reads now.
- **A build** (`build`), confirmed by the page first: the job looked at (there, buildable, its parameters), then `POST
  /job/NAME/build` or `/buildWithParameters` (its parameters as typed, `NAME=value&...`, their defaults otherwise),
  with the crumb and its session cookie when Jenkins' CSRF protection issues one; refused in words before anything
  changes for a job not there, disabled or a folder, and for a parameter it does not have.
- **Settings** through the login alone: `JENKINS_URL` (`http://127.0.0.1:8080` unless set), `JENKINS_USER`,
  `JENKINS_TOKEN` (an API token, a secret). The token goes to `JENKINS_URL` alone, over https or to this machine, with
  the first request; no redirect is followed; the token, its header, a crumb and a session cookie are taken out of
  every word said, and never printed, logged or returned.
- **How to install Jenkins**, said when it is not here (from jenkins.io, read 2026-11-22: Java 21 or 25; Jenkins'
  Windows installer; the apt and rpm LTS repositories): this release installs, starts and stops nothing.
- **Its API** (plugin API 2.2, apis.py): Jenkins' remote access API (14 parts, 21 calls, 7 of them made, the two
  builds writes), Windows' service control manager and systemd's systemctl, every address read on 2026-11-22;
  `api_facts()` asks nothing.
- `python -m plugin_platform_jenkins status | jobs | build JOB [NAME=value&...]`.
- Tests: nothing runs, connects or looks at this machine for real (a guard fails any test that does); Jenkins and the
  install are stand-ins; the contract, the Internal API tab's rules and the cards' own checks hold.
