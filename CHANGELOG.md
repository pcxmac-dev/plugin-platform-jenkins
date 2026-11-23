# Changelog

## 0.1.0 (2026-11-22)

The first release: Jenkins for the platform, the first plugin of its Continuous Integration section (the user,
2026-11-22: a "Continuous Integration" class of plugins, with Jenkins, GoCD and Buildbot). Needs liminal-libs>=1.66.0
(1.62.0's machines/endpoint.py sends its requests; 1.63.0 reads what it says of its interface; 1.66.0 holds an ask to
its PAGE_ONLY_HOOKS).

- **Present** when Jenkins is installed here or answers at its address; **valid** while it answers (its `X-Jenkins`
  header, or its own refusal of the token: 401 with `Basic realm="Jenkins"`). Installed here (here.py): on Windows its
  service `jenkins` and its state, asked of the service control manager (no process, no administrator's rights), and
  its war file in `%ProgramFiles%\Jenkins`; on Linux its unit `jenkins.service`, its file and its state (`systemctl
  show`), and its war file where the jenkins.io packages put it. Every look is a finder a test stands in for; what a
  look got is put in words apart (`unit_state_of`, `service_state_of`), tested on what systemd and Windows answer.
- **The page**: the address and Jenkins' version (the `X-Jenkins` header of its top page and its `.../api/` pages),
  whether you are signed in and why not, and once Jenkins answers to you three tables, each one GET of its JSON API
  asking with a tree for only what is shown (200 rows at most): its jobs (kind, state, last build, when, Build…; none
  for a multibranch project or an organization folder, whose build would be a scan), its build queue (a job in a
  folder by its full name) and its nodes. Jenkins starting or restarting (503) is said as that; what to do when it is
  installed and does not answer follows its service's or unit's state. A failure is said in words, never raised; what
  was read is kept 30 s, Read again (`refresh`) reads now, and an ask waits 60 s at most for another's read under way.
- **A build** (`build`), asked from the platform's page alone (`PAGE_ONLY_HOOKS`) and confirmed there first, held to
  the address and user the page named (`at`): the job looked at (there, buildable, its parameters), then `POST
  /job/NAME/build` or `/buildWithParameters` (its parameters as typed, `NAME=value&...`, their defaults otherwise),
  with the crumb and its session cookie when Jenkins' CSRF protection issues one; refused in words before anything
  changes for a job not there, disabled, a folder, a multibranch project or an organization folder, for a parameter it
  does not have, and where what answers is not Jenkins. Jenkins' answer is said: queued, the same build already
  waiting (303), or none queued (302 back to the job).
- **Settings** through the login alone: `JENKINS_URL` (`http://127.0.0.1:8080` unless set), `JENKINS_USER`,
  `JENKINS_TOKEN` (an API token, a secret; Jenkins CLI's `JENKINS_USER_ID` and `JENKINS_API_TOKEN` read too). The
  token goes to `JENKINS_URL` alone, over https or to this machine, and there only once an unsigned first ask was
  answered with `X-Jenkins`, while every answer since has been; no redirect is followed; the token, its header, a crumb
  and a session cookie are taken out of every word said before any is cut, and never printed, logged or returned. A
  Jenkins started by hand from an environment that holds the token hands it to its builds: the page says to start one
  without it.
- **How to install Jenkins**, said when it is not here (from jenkins.io, read 2026-11-22: Java 21 or 25; Jenkins'
  Windows installer and the JENKINS_HOME it chooses; the apt and rpm LTS repositories): this release installs, starts
  and stops nothing.
- **Its API** (plugin API 2.2, apis.py): Jenkins' remote access API (14 parts, 21 calls, 7 of them made, the two
  builds writes), Windows' service control manager and systemd's systemctl, every address read on 2026-11-22;
  `api_facts()` asks nothing.
- `python -m plugin_platform_jenkins status | jobs | build JOB [NAME=value&...]`.
- Tests: nothing runs, connects or looks at this machine for real (a guard fails any test that does); Jenkins and the
  install are stand-ins, answering as Jenkins does (a refused token's 401 without `X-Jenkins`, a multibranch project's
  scan, a repeated build's 303, a vetoed build's 302, the loading page's 503); the contract, the Internal API tab's
  rules and the cards' own checks hold.
