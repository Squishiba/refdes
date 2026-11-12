"""`textio.replace_with_retry`: the Windows sharing-violation retry.

On Windows, Python's `open()` does not pass `FILE_SHARE_DELETE`, so
`os.replace` over a destination that ANY other handle has open (the
server's own poller, an editor, antivirus) fails with WinError 5
(ACCESS_DENIED), 32 (SHARING_VIOLATION) or 33 (LOCK_VIOLATION) for as
long as the handle lives -- a transient condition the rename survives a
few milliseconds later. main's push CI run 42648833899 (windows-latest,
2026-11-09) recorded exactly this as a user-visible save refusal:
`the write failed ([WinError 5] Access is denied: '...refdes-tmp-...'
-> 'items/log.yaml')`.

These tests force the platform by monkeypatching `os.name` AND the
helper's `_IS_WINDOWS` flag and inject the Windows-shaped exceptions
directly -- no real Windows behaviour is simulated beyond the
monkeypatched exceptions, so the suite runs identically on Linux CI and
Windows CI. No test sleeps in real time: `time.sleep` is monkeypatched
to a recorder.
"""

import os
import time

import pytest

from refdes import seal, textio
from refdes.schema import load_project
from refdes.serve import edit as edit_mod


def _win_error(code: int) -> PermissionError:
    exc = PermissionError(code, "Access is denied")
    exc.winerror = code
    return exc


def _harness(monkeypatch, failures: int, code: int = 5, windows: bool = True):
    """Fake `os.replace` that raises the WinError-shaped `PermissionError`
    for the first `failures` calls then delegates to the real replace;
    records calls and sleeps. Forces the platform both ways: the real
    `os.name` (so a helper that reads it directly is caught) and the
    helper's `_IS_WINDOWS` constant it actually consults."""
    real_replace = os.replace
    calls: list[tuple[str, str]] = []
    sleeps: list[float] = []

    def fake_replace(src, dst, *args, **kwargs):
        calls.append((str(src), str(dst)))
        if len(calls) <= failures:
            raise _win_error(code)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fake_replace)
    monkeypatch.setattr(os, "name", "nt" if windows else "posix")
    monkeypatch.setattr(textio, "_IS_WINDOWS", windows)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return calls, sleeps


def _pair(tmp_path):
    src = tmp_path / "src.yaml"
    dst = tmp_path / "dst.yaml"
    src.write_bytes(b"planned\n")
    dst.write_bytes(b"original\n")
    return str(src), str(dst)


def test_retries_transient_denials_then_succeeds(tmp_path, monkeypatch):
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=3)
    textio.replace_with_retry(src, dst)
    assert len(calls) == 4, "succeeded on the fourth call"
    with open(dst, "rb") as fh:
        assert fh.read() == b"planned\n"
    # bounded, and never in real time: the recorded sleeps sum to well
    # under the ~1 s worst case, and no call below sleeps in real time
    # because time.sleep is the recorder.
    assert len(sleeps) == 3
    assert sum(sleeps) <= 1.0


def test_exhausts_attempts_and_reraises_the_last_error(tmp_path, monkeypatch):
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=999)
    with pytest.raises(PermissionError) as excinfo:
        textio.replace_with_retry(src, dst)
    assert excinfo.value.winerror == 5
    assert len(calls) == 10, "attempts, no more"
    assert len(sleeps) == 9, "no sleep after the final failure"
    with open(dst, "rb") as fh:
        assert fh.read() == b"original\n"


def test_other_winerror_is_not_retried(tmp_path, monkeypatch):
    # WinError 2 (file not found) is not the sharing race -- it must
    # surface on the first attempt, exactly as os.replace raises it.
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=999, code=2)
    with pytest.raises(PermissionError) as excinfo:
        textio.replace_with_retry(src, dst)
    assert excinfo.value.winerror == 2
    assert len(calls) == 1
    assert sleeps == []


def test_oserror_without_winerror_is_not_retried(tmp_path, monkeypatch):
    # The fakes the existing suites inject (plain OSError, ENOSPC) carry
    # no winerror -- the helper must not absorb them.
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_replace(src, dst, *args, **kwargs):
        calls.append(str(src))
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", fake_replace)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(textio, "_IS_WINDOWS", True)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    src, dst = _pair(tmp_path)
    with pytest.raises(OSError) as excinfo:
        textio.replace_with_retry(src, dst)
    assert getattr(excinfo.value, "winerror", None) is None
    assert len(calls) == 1
    assert sleeps == []


def test_posix_is_exactly_one_call_even_on_denial(tmp_path, monkeypatch):
    # Forced to "posix", a PermissionError is NOT retried: on POSIX the
    # helper is exactly os.replace, no sleep, no extra attempt.
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=999, windows=False)
    with pytest.raises(PermissionError):
        textio.replace_with_retry(src, dst)
    assert len(calls) == 1
    assert sleeps == []


def test_posix_success_is_exactly_one_call(tmp_path, monkeypatch):
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=0, windows=False)
    textio.replace_with_retry(src, dst)
    assert len(calls) == 1
    assert sleeps == []
    with open(dst, "rb") as fh:
        assert fh.read() == b"planned\n"


def test_attempts_below_one_is_clamped_to_a_single_attempt(tmp_path, monkeypatch):
    """`attempts=0` on Windows must not skip the loop entirely: the
    original code fell through to `raise last` with `last` still `None`
    and raised TypeError (exceptions must derive from BaseException) --
    the denial vanished behind a crash. Clamp to one attempt: the
    WinError surfaces as the original PermissionError, one call, no
    sleep (no next attempt to delay for)."""
    src, dst = _pair(tmp_path)
    calls, sleeps = _harness(monkeypatch, failures=999)
    with pytest.raises(PermissionError) as excinfo:
        textio.replace_with_retry(src, dst, attempts=0)
    assert excinfo.value.winerror == 5
    assert len(calls) == 1
    assert sleeps == []


# ------------------------------------------------- _atomic_replace integration


def test_atomic_replace_survives_two_transient_denials(tmp_path, monkeypatch):
    """The shape of main's Windows failure: the first two renames of the
    save land on WinError 5, the third lands. Before the retry,
    `_atomic_replace` caught that first denial and returned the "the
    write failed" refusal -- the save refused while the bytes were fine
    a few ms later. After it, the save succeeds and lands its bytes."""
    path = tmp_path / "log.yaml"
    path.write_bytes(b"original\n")
    real_replace = os.replace
    calls: list[str] = []

    def flaky(src, dst, *args, **kwargs):
        calls.append(str(dst))
        if len(calls) <= 2:
            raise _win_error(5)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(textio, "_IS_WINDOWS", True)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    reason = edit_mod._atomic_replace(str(path), b"applied\n")
    assert reason is None, f"the save was refused: {reason}"
    with open(path, "rb") as fh:
        assert fh.read() == b"applied\n"


def test_atomic_replace_refuses_after_exhausting_retries(tmp_path, monkeypatch):
    """When the denials do not clear, the caller sees the SAME refusal it
    sees today (same type, same shape of message), the destination keeps
    its original bytes, and no temp is left behind."""
    path = tmp_path / "log.yaml"
    path.write_bytes(b"original\n")
    calls: list[str] = []

    def always_denied(src, dst, *args, **kwargs):
        calls.append(str(dst))
        raise _win_error(5)

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(textio, "_IS_WINDOWS", True)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    reason = edit_mod._atomic_replace(str(path), b"applied\n")
    assert reason is not None
    assert "the write failed" in reason
    assert "Access is denied" in reason
    with open(path, "rb") as fh:
        assert fh.read() == b"original\n"
    assert not [n for n in os.listdir(str(tmp_path)) if "refdes-tmp" in n]


# ------------------------------------------------- seal.save_seals integration


def test_save_seals_survives_transient_denials(sealed_flat_project, monkeypatch):
    """`seal.save_seals` replaces `.refdes/log-seal.yaml` -- a project
    file a concurrent reader can hold, so a transient WinError-5 denial
    that clears a few ms later must not fall into `_record_seal_write`'s
    "entries are NOT sealed" diagnostic: the rename retried lands."""
    real_replace = os.replace
    calls: list[str] = []

    def flaky(src, dst, *args, **kwargs):
        calls.append(str(dst))
        if len(calls) <= 2:
            raise _win_error(5)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(textio, "_IS_WINDOWS", True)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    project = load_project(config_path=str(sealed_flat_project / "refdes-project.yaml"))
    assert seal.save_seals(project, {"LOG-001": "0" * 16}) is True
    with open(seal.seal_path(project), encoding="utf-8") as fh:
        assert "LOG-001" in fh.read()


def test_save_seals_keeps_the_existing_refusal_after_exhausting_retries(
    sealed_flat_project, monkeypatch
):
    """When the denials never clear, `save_seals` keeps the refusal it
    performs today: returns False and records the blocked write (the
    build's exit-1 path), the seal file never lands, no temp is left."""
    calls: list[str] = []

    def always_denied(src, dst, *args, **kwargs):
        calls.append(str(dst))
        raise _win_error(5)

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(textio, "_IS_WINDOWS", True)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    project = load_project(config_path=str(sealed_flat_project / "refdes-project.yaml"))
    path = seal.seal_path(project)
    assert seal.save_seals(project, {"LOG-001": "0" * 16}) is False
    assert len(calls) == 10
    assert not os.path.exists(path)
    directory = os.path.dirname(path)
    assert not [n for n in os.listdir(directory) if n.endswith(".tmp")]
