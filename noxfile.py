from __future__ import annotations

import sys

import nox

nox.options.default_venv_backend = "none"


def _run_quality(session: nox.Session, command: str) -> None:
    session.run(
        sys.executable,
        "tools/quality.py",
        command,
        *session.posargs,
        external=True,
    )


@nox.session(name="quality-fast")
def quality_fast(session: nox.Session) -> None:
    _run_quality(session, "quality-fast")


@nox.session(name="quality-pr")
def quality_pr(session: nox.Session) -> None:
    _run_quality(session, "quality-pr")


@nox.session(name="quality-nightly")
def quality_nightly(session: nox.Session) -> None:
    _run_quality(session, "quality-nightly")


@nox.session(name="quality-baseline")
def quality_baseline(session: nox.Session) -> None:
    _run_quality(session, "quality-baseline")
