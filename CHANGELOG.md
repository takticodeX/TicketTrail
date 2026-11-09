# Changelog

Each released version has a tag (`vX.Y.Z`), images on `ghcr.io/takticodex/tickettrail-*`
and a GitHub Release with an offline archive of the images. See README "Install from a
release".

## [0.3.0] - 2026-11-09

### Added
- **Dry-run review.** On a finished dry run, editors untick the commits not to post (they
  are never posted, by any run), pick the work item of a commit without one or with a
  wrong one from a searchable list of the board (closed items last; the link is kept for
  later runs), and **Post selected** posts exactly the reviewed rows without a rescan.
- **Organizations**: teams that own projects and connections; members are viewers, a share
  makes them editors; admins own every project.
- **Sharing** a project with users as viewer or editor.
- **Administrators** see and may do everything; **Admin → Activity** records what they do to
  other users' data. Tokens stay write-only for everyone.
- Releases: prebuilt images on ghcr.io and a release workflow (`TT_IMAGE_PREFIX`,
  `TT_VERSION`).

### Changed
- **Change owner** is the one way a project changes hands (it replaces the administrator's
  project Transfer and the users' Move); every owner change is in one history.

## [0.2.0] - 2026-10-21

First complete version (milestones 1-7 of SPEC.md): multi-user auth, Git and Azure DevOps
connections, projects with ticket pattern and comment template, dry runs, de-duplicated
posting with crash recovery, schedules, cancelling, hardening, CI and the end-to-end test.
