
"""Gates for the Cursor plugin.

Every file the client will read is asserted here.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"
SKILL = PLUGIN / "skills" / "memvara"
HOSTED = "https://app.memvara.dev/mcp"
REPO_NAME = "memvara/cursor-memvara"


def _json(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class LibraryUnreachable(Exception):
    """Neither a local checkout nor GitHub could answer. Raised, never swallowed.

    A drift check that quietly passes when it cannot look is the same as no drift check.
    This repository has already been caught by exactly that shape: `skill-sync.yml` failed
    on every scheduled run for days while nothing here went red, because the vendored copy
    and `skill.lock` stayed consistent with each other and the only thing that would have
    noticed was a scheduled job nobody read.
    """


def _trust() -> "ssl.SSLContext":
    """A context that trusts the same roots `curl` does.

    python.org's macOS build ignores the system trust store, so an unqualified `urlopen`
    raises CERTIFICATE_VERIFY_FAILED against a certificate `curl` accepts. Without this the
    drift check below does not fail on a Mac -- it *skips*, reporting the library as
    unreachable when the library is fine, which is the quiet half of the failure it was
    written to catch.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "memvara-tests"})
    with urllib.request.urlopen(request, timeout=30, context=_trust()) as resp:
        return bytes(resp.read())


def _library_bytes(sha: str, path: str) -> bytes:
    root = os.environ.get("MEMVARA_LIBRARY")
    if root:
        try:
            return subprocess.check_output(
                ["git", "-C", root, "show", f"{sha}:{path}"],
                stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            # The checkout has the sha `skill.lock` names and nothing else: CI clones the
            # library AT that sha, shallow, so the library's current HEAD is simply not an
            # object here. Falling back to the network rather than failing is what lets the
            # drift check below run on CI at all -- and it only matters when the lock is
            # stale, which is precisely when the check has something to say.
            pass
    return _fetch(f"https://raw.githubusercontent.com/memvara/memvara/{sha}/{path}")


def _library_head() -> str:
    """The library default branch's current sha, or raise `LibraryUnreachable`."""
    root = os.environ.get("MEMVARA_LIBRARY")
    if root:
        for ref in ("origin/main", "main"):
            try:
                return subprocess.check_output(
                    ["git", "-C", root, "rev-parse", ref],
                    stderr=subprocess.DEVNULL).decode().strip()
            except subprocess.CalledProcessError:
                continue
    try:
        body = _fetch("https://api.github.com/repos/memvara/memvara/commits/main")
        return str(json.loads(body)["sha"])
    except Exception as exc:
        raise LibraryUnreachable(str(exc)) from exc


def _library_skill_files(sha: str) -> "set[str]":
    """Every path under the packaged skill at `sha`, relative to it."""
    root = os.environ.get("MEMVARA_LIBRARY")
    prefix = "memvara/skills/memvara/"
    if root:
        try:
            out = subprocess.check_output(
                ["git", "-C", root, "ls-tree", "-r", "--name-only", sha,
                 "memvara/skills/memvara"], stderr=subprocess.DEVNULL).decode()
        except subprocess.CalledProcessError:
            # Not an object in this checkout -- see `_library_bytes`. Ask GitHub instead
            # of reporting the library unreachable, which would SKIP the check on the one
            # run that needed it.
            out = None
        if out is not None:
            return {line[len(prefix):] for line in out.splitlines()
                    if line.startswith(prefix)}
    try:
        tree = json.loads(_fetch(
            f"https://api.github.com/repos/memvara/memvara/git/trees/{sha}?recursive=1"))
    except Exception as exc:
        raise LibraryUnreachable(str(exc)) from exc
    return {entry["path"][len(prefix):] for entry in tree.get("tree", [])
            if entry.get("type") == "blob" and entry["path"].startswith(prefix)}


def _lock(name: str = "skill.lock") -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _library_files(sha: str, path: str) -> "set[str]":
    """Every path under `path` at `sha`, relative to `path`."""
    root = os.environ.get("MEMVARA_LIBRARY")
    prefix = f"{path}/"
    if root:
        try:
            out = subprocess.check_output(
                ["git", "-C", root, "ls-tree", "-r", "--name-only", sha, path],
                stderr=subprocess.DEVNULL).decode()
        except subprocess.CalledProcessError:
            out = None
        if out is not None:
            return {line[len(prefix):] for line in out.splitlines()
                    if line.startswith(prefix)}
    try:
        tree = json.loads(_fetch(
            f"https://api.github.com/repos/memvara/memvara/git/trees/{sha}?recursive=1"))
    except Exception as exc:
        raise LibraryUnreachable(str(exc)) from exc
    return {entry["path"][len(prefix):] for entry in tree.get("tree", [])
            if entry.get("type") == "blob" and entry["path"].startswith(prefix)}


HOOKS = PLUGIN / "hooks"
LIBRARY_HOOKS_PATH = "plugin/hooks"

#: Hook scripts are executable content Cursor runs, so the allowlist names them one by
#: one. There is no `hooks.json` here: Cursor reads its hook config from the user's own
#: file, which `bin/install.py` writes, so nothing is generated into this tree.
ALLOWED_HOOK_FILES = {
    "run.py", "recall.py", "capture.py", "session_start.py", "approve.py", "daemon.py",
    "core/__init__.py", "core/host.py", "core/envelope.py",
    "hosts/__init__.py", "hosts/claude.py", "hosts/codex.py", "hosts/cursor.py",
    "hosts/opencode.py",
    "js/shim.mjs", "js/opencode.mjs",
    "lib/__init__.py", "lib/extract.py", "lib/fast.py", "lib/hosted.py", "lib/ipc.py",
    "lib/open.py", "lib/standing.py", "lib/transcript.py", "lib/usage.py", "lib/write.py",
    "tools/__init__.py", "tools/generate.py",
}


class SkillTree(unittest.TestCase):
    def test_skill_has_front_matter_and_references(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.splitlines()[0] == "---")
        named = set(re.findall(r"references/([a-z0-9-]+\.md)", text))
        self.assertTrue(named)
        for name in named:
            self.assertTrue((SKILL / "references" / name).is_file(), name)

    def test_matches_library_at_lock_sha(self) -> None:
        lock = _lock()
        self.assertEqual(lock["repo"], "memvara/memvara")
        sha = lock["sha"]
        self.assertEqual(len(sha), 40)
        for rel in ("SKILL.md", "references/hosted-mcp.md"):
            expected = _library_bytes(sha, f"memvara/skills/memvara/{rel}")
            self.assertEqual((SKILL / rel).read_bytes(), expected, rel)

    def test_the_vendored_skill_is_not_behind_the_library(self) -> None:
        """The whole tree, against the library's CURRENT default branch.

        `test_matches_library_at_lock_sha` cannot catch a stale sync and is not supposed
        to: it compares the copy against the sha the copy itself names, so a lock and a
        tree frozen together agree with each other forever. That is exactly how this repo
        shipped a skill five commits behind -- `skill-sync.yml` dying every night on a
        permission the organization pins, nothing here going red, and the agreement
        between the two stale files being the thing that hid it.

        Two deliberate choices about noise. It compares BYTES rather than shas, so the
        library moving does not fail this repository -- only the library's *skill* moving
        does, which is rare. And it compares the file SET as well, because a new reference
        file upstream is drift that a per-file comparison of the files we already have
        would never see.

        When the library cannot be reached this SKIPS rather than passes. A skip is
        visible in the run output; a pass is not, and a check that silently succeeds when
        it could not look is the failure it exists to prevent, one level up.
        """
        try:
            head = _library_head()
            upstream = _library_skill_files(head)
        except LibraryUnreachable as exc:
            raise unittest.SkipTest(
                f"library unreachable, drift NOT checked: {exc}") from exc

        self.assertTrue(upstream, "the library reported an empty skill tree")
        ours = {str(path.relative_to(SKILL))
                for path in SKILL.rglob("*") if path.is_file()}
        self.assertEqual(
            ours, upstream,
            f"the vendored skill's file set differs from the library at {head[:7]} — "
            "run scripts/sync_plugin_repos.py from the library and update skill.lock")

        drifted = []
        for rel in sorted(upstream):
            expected = _library_bytes(head, f"memvara/skills/memvara/{rel}")
            if (SKILL / rel).read_bytes() != expected:
                drifted.append(rel)
        self.assertEqual(
            drifted, [],
            f"vendored skill is behind memvara/memvara@{head[:7]}: {drifted} — "
            "sync it")


class Hooks(unittest.TestCase):
    """The tree Cursor runs, vendored byte for byte with ZERO transforms."""

    def _ours(self) -> "set[str]":
        return {path.relative_to(HOOKS).as_posix() for path in HOOKS.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts}

    def test_the_vendored_hook_bytes_match_the_library_at_the_pinned_sha(self) -> None:
        lock = _lock("hooks.lock")
        self.assertEqual(lock["repo"], "memvara/memvara")
        self.assertEqual(lock["path"], LIBRARY_HOOKS_PATH)
        self.assertEqual(lock["host"], "cursor")
        sha = lock["sha"]
        self.assertEqual(len(sha), 40, f"hooks.lock sha is not a full sha: {sha!r}")
        ours = self._ours()
        self.assertTrue(ours, "no vendored hook files found — this guard would pass on "
                              "an empty tree, which is the shape it exists to stop")
        try:
            upstream = _library_files(sha, LIBRARY_HOOKS_PATH)
        except LibraryUnreachable as exc:
            raise unittest.SkipTest(
                f"library unreachable, vendored bytes NOT checked: {exc}") from exc
        self.assertEqual(ours, upstream,
                         f"the vendored hook file set differs from the library@{sha[:7]}")
        drifted = [rel for rel in sorted(ours)
                   if (HOOKS / rel).read_bytes()
                   != _library_bytes(sha, f"{LIBRARY_HOOKS_PATH}/{rel}")]
        self.assertEqual(drifted, [], f"vendored hooks drifted from {sha[:7]}: {drifted}")

    def test_the_vendored_hooks_are_not_behind_the_library(self) -> None:
        try:
            head = _library_head()
            upstream = _library_files(head, LIBRARY_HOOKS_PATH)
        except LibraryUnreachable as exc:
            raise unittest.SkipTest(
                f"library unreachable, hook drift NOT checked: {exc}") from exc
        self.assertTrue(upstream, "the library reported an empty hook tree")
        self.assertEqual(self._ours(), upstream,
                         f"the vendored hook file set differs from the library at "
                         f"{head[:7]} — re-vendor and update hooks.lock")

    def test_the_hook_file_set_is_named_here_one_by_one(self) -> None:
        extra = self._ours() - ALLOWED_HOOK_FILES
        self.assertFalse(extra, f"unlisted hook files: {sorted(extra)}")

    def test_the_allowlist_names_nothing_that_is_no_longer_in_the_tree(self) -> None:
        missing = ALLOWED_HOOK_FILES - self._ours()
        self.assertFalse(missing, f"allowlist names files that are gone: {sorted(missing)}")

    def test_the_sync_workflow_rewrites_the_lock_it_already_has(self) -> None:
        """`hooks-sync.yml` must write back exactly the lock that is committed here.

        The workflow replaces `hooks.lock` wholesale on every run. One stray character
        between the heredoc there and the file here and the diff is never empty, so the
        nightly job opens a pull request that changes nothing, every night, forever --
        and the honest daily PR is what everybody then stops reading.

        `host` is the half that must NOT come from the workflow. Seven repositories vendor
        one tree and each registers a different client, so a literal host in the heredoc
        would flatten six install surfaces into a copy of this one on the first sync. It
        is read out of the file being replaced, and this asserts the heredoc interpolates
        it rather than naming it.
        """
        source = (ROOT / ".github" / "workflows" / "hooks-sync.yml").read_text(
            encoding="utf-8")
        opener = "cat > hooks.lock <<LOCK\n"
        self.assertIn(opener, source, "hooks-sync.yml no longer writes hooks.lock")
        indent = " " * (source.index(opener) - source.rindex("\n", 0, source.index(opener))
                        - 1)
        body, _, rest = source.split(opener, 1)[1].partition(f"{indent}LOCK\n")
        self.assertTrue(rest, "the hooks.lock heredoc is not terminated")

        lines = []
        for line in body.splitlines(True):
            self.assertTrue(line.startswith(indent), f"ragged heredoc line: {line!r}")
            lines.append(line[len(indent):])
        written = "".join(lines)

        self.assertIn("host=$host\n", written,
                      "the heredoc must interpolate this repository's own host, not "
                      "name one -- a literal there flattens every sibling repo into this "
                      "one on the first sync")
        self.assertIn('host=$(awk -F= \'/^host=/{print $2}\' hooks.lock)', source,
                      "the host must be read back out of the lock being replaced")

        lock = _lock("hooks.lock")
        written = written.replace("$sha", lock["sha"]).replace("$host", lock["host"])
        self.assertEqual(
            written, (ROOT / "hooks.lock").read_text(encoding="utf-8"),
            "hooks-sync.yml would rewrite hooks.lock differently from how it is "
            "committed, so every scheduled run would open a PR that changes nothing")

    def test_the_sync_workflow_copies_the_tree_this_repository_actually_vendors(self) -> None:
        """The destination path is the half the heredoc cannot check.

        A workflow that rewrites the lock perfectly and copies into the wrong directory
        leaves the old tree in place and the lock claiming a sha it does not hold -- a
        pair agreeing with each other while both are wrong, which is this project's
        commonest defect shape. `DEST` is where the tree is on disk here, so this compares
        the workflow against the repository rather than against a copy of itself.
        """
        source = (ROOT / ".github" / "workflows" / "hooks-sync.yml").read_text(
            encoding="utf-8")
        dest = HOOKS.relative_to(ROOT).as_posix()
        self.assertIn(f"rm -rf {dest}\n", source,
                      f"hooks-sync.yml does not clear {dest} before copying")
        self.assertIn(f'cp -R "$src" {dest}\n', source,
                      f"hooks-sync.yml does not copy the library tree into {dest}")
        self.assertIn(f'if [ -z "$(git status --porcelain -- {dest})" ]; then', source,
                      f"hooks-sync.yml decides on a different path than {dest}")
        self.assertNotIn("git diff --quiet", source,
                         "`git diff` cannot see a file the library ADDED -- it lands "
                         "untracked -- so the addition is dropped and re-copied nightly "
                         "in silence. `git status --porcelain` lists untracked entries")

    def _record(self):
        sys.path.insert(0, str(HOOKS))
        try:
            import hosts.cursor as record  # noqa: PLC0415
            return record.HOST
        finally:
            sys.path.remove(str(HOOKS))

    def test_this_host_ships_no_per_prompt_recall_and_says_so(self) -> None:
        """The reduction, asserted in the record AND on the page.

        `beforeSubmitPrompt` never fires on this client -- not on a first message, not on
        a `--continue` follow-up, not from user or project scope -- so `recall` is absent
        from `events` and `run.py` skips it with a logged reason. Absence alone is not the
        guard: a record that quietly regained the mapping would ship a hook that installs,
        registers and never runs, and a README that quietly stopped disclosing the gap
        would leave a user believing memory arrives every turn when it does not. Both
        halves are required here, which is what makes either one failing loud.
        """
        host = self._record()
        self.assertNotIn(
            "recall", host.events,
            "the record maps `recall` to an event; beforeSubmitPrompt does not fire on "
            "this client, so that hook would install, register and never run")
        for name in ("session_start", "capture", "approve"):
            self.assertIn(name, host.events, f"{name} is no longer mapped")
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("no per-prompt recall on Cursor", text,
                      "the README does not disclose that memory is not injected per turn")
        self.assertIn("beforeSubmitPrompt", text,
                      "the README does not name the event that was measured, so a reader "
                      "cannot check the finding themselves")

    def test_capture_mines_with_this_host_s_own_model(self) -> None:
        """And read-only, which is what makes the `--trust` beside it defensible.

        `-p` alone has access to write and shell, and what this command is handed is a
        mined turn -- arbitrary text, including whatever the user pasted. `--trust` is
        required because an extraction runs wherever the turn happened and Cursor refuses
        an untrusted directory outright, so the read-only mode is not decoration.
        """
        argv = self._record().extractor.argv
        self.assertEqual(argv[0], "cursor-agent",
                         f"the first rung is {argv[0]!r}, not this host's own CLI")
        self.assertIn("--mode", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "ask",
                         "the extractor is not read-only, and it is passed --trust")
        self.assertNotIn("--model", argv,
                         "the extractor pins a model, overriding the one this user "
                         "configured and possibly naming one they cannot reach")

    def test_a_hook_never_fails_a_turn_whatever_the_environment(self) -> None:
        env = dict(os.environ, HOME="/nonexistent", MEMVARA_HOME="/nonexistent",
                   # Without this, `capture` forks and returns before the body is
                   # imported, so the subtest would check the wrapper and not the code
                   # that opens a store and reads a transcript.
                   MEMVARA_HOOK_DETACHED="1")
        for hook in ("session_start", "recall", "capture", "approve"):
            with self.subTest(hook=hook):
                proc = subprocess.run(
                    [sys.executable, str(HOOKS / "run.py"), hook, "--host", "cursor"],
                    input="{}", capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(proc.returncode, 0,
                                 f"{hook} exited {proc.returncode}: {proc.stderr[:300]}")
                if proc.stdout.strip():
                    json.loads(proc.stdout)


class Installer(unittest.TestCase):
    """It writes the user's own hook config, so it must never take anything else."""

    def _run(self, cfg: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "bin" / "install.py"), "--config", str(cfg),
             *args], capture_output=True, text=True)

    def test_it_writes_the_three_events_this_host_supports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "hooks.json"
            self.assertEqual(self._run(cfg).returncode, 0)
            hooks = _json(cfg)["hooks"]
            self.assertEqual(sorted(hooks), ["preToolUse", "sessionEnd", "sessionStart"],
                             "the installer wrote a different event set than the record "
                             "declares, so the two can disagree about what runs")
            self.assertNotIn("beforeSubmitPrompt", hooks,
                             "it registered the event that does not fire on this client")

    def test_it_leaves_everything_that_is_not_ours_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "hooks.json"
            cfg.write_text(json.dumps({"version": 1, "hooks": {
                "sessionStart": [{"command": "echo theirs"}],
                "beforeShellExecution": [{"command": "echo also theirs"}]}}),
                encoding="utf-8")
            self.assertEqual(self._run(cfg).returncode, 0)
            hooks = _json(cfg)["hooks"]
            self.assertIn("beforeShellExecution", hooks, "it dropped an unrelated event")
            self.assertTrue(any("echo theirs" in e["command"]
                                for e in hooks["sessionStart"]),
                            "it dropped a foreign hook on an event it also writes")
            self.assertEqual(len(hooks["sessionStart"]), 2)

            # And running it again must replace rather than append.
            self.assertEqual(self._run(cfg).returncode, 0)
            self.assertEqual(len(_json(cfg)["hooks"]["sessionStart"]), 2)

            # --remove takes ONLY ours.
            self.assertEqual(self._run(cfg, "--remove").returncode, 0)
            hooks = _json(cfg)["hooks"]
            self.assertEqual(hooks["sessionStart"], [{"command": "echo theirs"}])
            self.assertIn("beforeShellExecution", hooks)

    def test_it_refuses_a_hook_value_it_cannot_read_rather_than_replacing_it(self) -> None:
        """The docstring promises anything else in the file is left exactly as it was.

        An earlier version reset a non-list to `[]`, which silently DELETED it: a
        hand-written `"sessionStart": {"command": ...}` came back as our entry alone while
        the output still said "wrote". The identical defect was found in
        `opencode-memvara`'s installer and fixed there as an instance; this is the guard
        that stops it being reproduced a third time.
        """
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "hooks.json"
            cfg.write_text(json.dumps({"version": 1, "hooks": {
                "sessionStart": {"command": "echo theirs"}}}), encoding="utf-8")
            proc = self._run(cfg)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("refusing to write", proc.stderr + proc.stdout)
            self.assertIn("theirs", cfg.read_text(encoding="utf-8"),
                          "it refused and destroyed the value anyway")

    def test_it_does_not_touch_an_event_it_never_writes(self) -> None:
        """An empty list under someone else's event is a placeholder, not litter.

        The merge loop walked every event in the file so it could tidy up, and tidying
        somebody else's config is not this script's business: `"beforeShellExecution": []`
        — left while a hook was disabled — was deleted because the key happened to be
        empty, by a `pop` meant only for an event we had just emptied ourselves.
        """
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "hooks.json"
            cfg.write_text(json.dumps({"version": 1, "hooks": {
                "beforeShellExecution": [], "afterFileEdit": [{"command": "echo x"}]}}),
                encoding="utf-8")
            self.assertEqual(self._run(cfg).returncode, 0)
            hooks = _json(cfg)["hooks"]
            self.assertIn("beforeShellExecution", hooks,
                          "it deleted an empty event this plugin never writes")
            self.assertEqual(hooks["afterFileEdit"], [{"command": "echo x"}])

    def test_it_refuses_a_config_it_cannot_parse(self) -> None:
        """The user's file, with Cursor's own features in it. A parse failure is a reason
        to stop, not to start again from an empty object."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "hooks.json"
            cfg.write_text("{not json", encoding="utf-8")
            proc = self._run(cfg)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("refusing to write", proc.stderr + proc.stdout)
            self.assertEqual(cfg.read_text(encoding="utf-8"), "{not json",
                             "it refused and overwrote the file anyway")


class License(unittest.TestCase):
    def test_apache(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", text)
        self.assertIn("Version 2.0", text)


class SharedInstructions(unittest.TestCase):
    """CLAUDE.md is shared across every plugin repo, and nothing used to carry it.

    It was hand-copied and it drifted: eleven of fourteen sections were byte-identical
    across all seven repositories while a section written in one of them reached none of
    the others. The canonical is `plugin-claude.md` in the library; `skill-sync.yml`
    composes this file from it and preserves the `local:` block, because two sections
    legitimately differ per repo — a repository's own runtime facts, and hook rules that
    only one plugin needs.

    Without this guard the sync would be a tidier way to drift rather than an end to it,
    which is the objection the section it carries makes about hand-maintained copies.
    """

    BEGIN = "<!-- local: begin"
    END = "<!-- local: end -->"

    def _text(self) -> str:
        return (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_the_local_block_is_delimited_exactly_once(self) -> None:
        """Two of either marker and the splice takes the wrong span; none and the composer
        refuses rather than replacing this repository's sections with a placeholder.
        """
        text = self._text()
        self.assertEqual(text.count(self.BEGIN), 1)
        self.assertEqual(text.count(self.END), 1)
        self.assertLess(text.index(self.BEGIN), text.index(self.END))

    def test_the_shared_half_matches_the_library(self) -> None:
        """Compared against the LIBRARY, never against this file's own halves.

        A check that read both halves of one file would prove it internally consistent and
        nothing else — exactly how a vendored skill sat five commits behind while its own
        drift test passed.
        """
        lock = _lock()
        try:
            canonical = _library_bytes(lock["sha"], "plugin-claude.md").decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(
                f"library has no plugin-claude.md at {lock['sha'][:7]}: {exc}") from exc
        text = self._text()
        head, rest = text.split(self.BEGIN, 1)
        _, tail = rest.split(self.END, 1)
        want_head, want_tail = canonical.split("@@LOCAL@@\n", 1)
        self.assertEqual(head, want_head,
                         "text above the local block drifted — edit plugin-claude.md in "
                         "memvara/memvara, not the copy here")
        self.assertEqual(tail.lstrip("\n"), want_tail.lstrip("\n"),
                         "text below the local block drifted from plugin-claude.md")

    def test_the_local_block_holds_what_only_this_repo_knows(self) -> None:
        """Not decorative: it carries the two sections that differ per repo. A sync that
        flattened it would lose them silently — the file would still read as a complete
        CLAUDE.md, just one belonging to a different repository.
        """
        local = self._text().split(self.BEGIN, 1)[1].split(self.END, 1)[0]
        self.assertIn("Runtime facts that cost hours to find", local)
        self.assertIn("If this repo ships hooks", local)


class Hygiene(unittest.TestCase):
    def test_no_npx_in_json(self) -> None:
        """No JSON *this repo ships* may reach for npx.

        `_library` is skipped because it is not ours: CI checks the library out there, at
        `skill.lock`'s sha, so the drift test can run offline. The moment that lock moves
        to a sha where the library has an npm package, an unfiltered scan reads
        `_library/npm/memvara/package.json` -- whose description legitimately begins "npx
        memvara" -- and fails a sync PR for a string in another repository. That is not
        hypothetical: it happened in claude-memvara on 2026-08-25, and this lock bump is
        the one that would have done it here.

        The scan stays repo-wide rather than narrowing to `plugin/`: the rule is about
        anything shipped from here, and an allowlist of directories stops covering the
        next one added.
        """
        for path in ROOT.rglob("*.json"):
            if {"node_modules", "_library"} & set(path.parts):
                continue
            self.assertNotIn("npx", path.read_text(encoding="utf-8"), path)

    def test_no_app_manifest_and_no_commands(self) -> None:
        """`hooks/` was asserted absent here and is not any more: this plugin ships it.
        What replaced that assertion is the `Hooks` class, which is strictly stronger --
        every file named one by one and every byte compared against the library."""
        self.assertFalse((PLUGIN / ".app.json").exists())
        self.assertFalse((PLUGIN / "commands").exists())

    def test_github_org(self) -> None:
        env = os.environ.get("GITHUB_REPOSITORY")
        if env:
            self.assertEqual(env, REPO_NAME)

class CursorManifest(unittest.TestCase):
    def test_manifest(self) -> None:
        body = _json(PLUGIN / ".cursor-plugin" / "plugin.json")
        assert isinstance(body, dict)
        self.assertEqual(body["name"], "memvara")
        self.assertEqual(body["repository"], f"https://github.com/{REPO_NAME}")

    def test_marketplace(self) -> None:
        body = _json(ROOT / ".cursor-plugin" / "marketplace.json")
        self.assertEqual(body["plugins"][0]["source"], "./plugin")

    def test_mcp_json_is_cursor_shape(self) -> None:
        body = _json(PLUGIN / "mcp.json")
        server = body["mcpServers"]["memvara"]
        self.assertEqual(server["url"], HOSTED)
        self.assertNotIn("servers", body)
        self.assertNotIn("command", server)
        raw = (PLUGIN / "mcp.json").read_text(encoding="utf-8")
        self.assertNotIn("python3", raw)

    def test_readme(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("cursor", text.lower())
        self.assertIn(HOSTED, text)
        self.assertNotIn("npx ", text)
        self.assertNotIn("chatgpt", text.lower())

    def test_plugin_tree(self) -> None:
        allowed = {
            pathlib.Path(".cursor-plugin") / "plugin.json",
            pathlib.Path("mcp.json"),
        }
        for path in SKILL.rglob("*"):
            if path.is_file():
                allowed.add(path.relative_to(PLUGIN))
        for rel in ALLOWED_HOOK_FILES:
            allowed.add(pathlib.Path("hooks", *rel.split("/")))
        found = {p.relative_to(PLUGIN) for p in PLUGIN.rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts}
        self.assertFalse(found - allowed, found - allowed)


class Version(unittest.TestCase):
    """Every version this repository states must be the same one, and none may hide.

    Five skill syncs shipped under 0.1.0. The vendored skill is the whole of what a client
    receives here, it changed five times, and the string a client compares never moved.
    `claude-memvara` was caught by the identical shape at larger scale -- twenty-one
    commits on main behind an unchanged version, `/plugin update` answering "already at
    the latest version" for every one of them.

    Three deliberate choices, each of them paid for by a sabotage run.

    Files are found by walking the tree, not by reading a list, so a manifest nobody
    remembered cannot go unchecked. `DECLARED` is then the completeness half -- it names
    the manifests that MUST carry a version, and it is compared against the walk in both
    directions, which is what keeps a hand-written list from quietly narrowing coverage.

    The file set comes from `git ls-files`, not from the filesystem. Two sweeps of the
    tree were tried first and both were wrong in a way a passing run could not show: one
    ignored directories by absolute path, which excluded the entire repository whenever the
    checkout was a worktree (those live under `.claude/worktrees/`, so `.claude` was in the
    parts of every path); the next was caught by CI dragging in six manifests from the
    library checkout under `_library/`. Git already knows which files this repository owns.

    And the assertions demand presence rather than absence of the wrong value. The
    coverage check was first written as a bare set comparison and passed on that broken
    walk because both sides were empty; the value check alone still passes when one
    manifest of several drops its version entirely. A guard an absence satisfies has
    stopped guarding.
    """

    VERSION = "0.2.3"
    DECLARED = {
        'plugin/.cursor-plugin/plugin.json',
    }

    @classmethod
    def _walk(cls, node: object, where: str = ""):
        """Every `version` string at any depth, with the pointer that reached it."""
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "version" and isinstance(value, str):
                    yield f"{where}.{key}", value
                else:
                    yield from cls._walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from cls._walk(value, f"{where}[{index}]")

    @classmethod
    def _candidates(cls) -> list:
        """Every JSON file this repository TRACKS -- asked of git, not of the filesystem.

        The filesystem is the wrong referent. CI checks the library out into `_library/`,
        which carries the sibling plugins' own manifests, and an `rglob` swept all six into
        the walk; a denylist would then have to grow a name for every scratch directory
        anyone ever creates, and the first one nobody thought of is a false failure. What
        the question actually means is "files this repository owns", and git is the thing
        that knows. Untracked checkouts and nested worktrees fall out for free.

        No fallback when git cannot answer. A fallback here would silently cover less than
        the caller believes, which is the failure this whole class exists to prevent.
        """
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", "*.json"],
            check=True, capture_output=True, text=True).stdout
        return [
            ROOT / name for name in listed.split("\0")
            if name and pathlib.PurePath(name).name != "package-lock.json"
        ]

    def _stated(self) -> list:
        found = []
        for path in self._candidates():
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            found.extend((path, where, value) for where, value in self._walk(body))
        return found

    def test_every_version_this_repo_states_is_the_released_one(self) -> None:
        stated = self._stated()
        self.assertTrue(
            stated, "no file states a version at all -- this guard has stopped guarding")
        for path, where, value in stated:
            self.assertEqual(
                value, self.VERSION,
                f"{path.relative_to(ROOT)}{where} says {value!r}; a partial bump is how a "
                "client gets told it is current while the contents moved underneath it")

    def test_exactly_the_manifests_that_must_declare_a_version_do(self) -> None:
        """Both directions, because each catches a mistake the other cannot see.

        A file the walk misses is a version nobody checks. A file that has stopped
        declaring one is a manifest shipping unversioned -- invisible to the value check
        above, which goes green as soon as any other file still says the right thing.
        Confirmed by sabotage: deleting the key from one of three manifests left it green.
        """
        reached = {str(path.relative_to(ROOT)) for path, _where, _value in self._stated()}
        by_text = {
            str(path.relative_to(ROOT)) for path in self._candidates()
            if '"version"' in path.read_text(encoding="utf-8")
        }
        self.assertEqual(by_text, self.DECLARED, "a manifest gained or lost its version")
        self.assertEqual(reached, self.DECLARED, "the JSON walk missed a stated version")

    def test_the_release_number_is_written_down_exactly_once_in_this_suite(self) -> None:
        """`VERSION` above is the only place the tests name it.

        Ported from claude-memvara, which learned it the same way this repository just
        did: another test asserted the release literally, so a bump had to be applied in
        two places and one of them was missed. Every extra place is the mechanism a
        partial bump needs, and a partial bump is what tells a client it is current while
        the contents moved underneath it.

        The duplicates that prompted this now read `Version.VERSION` instead, which is
        why they no longer count.
        """
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(
            source.count(f'"{self.VERSION}"'), 1,
            f"{self.VERSION} appears more than once in this file; VERSION is meant to be "
            "the single place the suite states the release")


def _readme_prose(root: pathlib.Path) -> str:
    """The README with every run of whitespace collapsed to one space.

    Where prose wraps is not a fact about what it says: matching raw text pins a line
    break, so a reflow reddens a guard whose sentence is present and correct, and a
    rewrapped reintroduction slips past `assertNotIn`.
    """
    return " ".join(root.joinpath("README.md").read_text(encoding="utf-8").split())


class ModuleShape(unittest.TestCase):
    """Nothing may be defined below `unittest.main()`.

    Measured in the sibling repos: a class appended after the `__main__` block is
    collected by `unittest discover` and NOT by `python3 test/test_plugin.py`, and both
    print OK -- 26 tests one way and 21 the other, with nothing saying so.
    """

    def test_nothing_is_defined_after_the_main_block(self) -> None:
        import ast

        body = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8")).body
        guards = [i for i, node in enumerate(body)
                  if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)]
        self.assertEqual(len(guards), 1, "expected exactly one __main__ block")
        after = [type(node).__name__ for node in body[guards[0] + 1:]]
        self.assertEqual(
            after, [],
            f"{after} is defined after `unittest.main()`, so "
            "`python3 test/test_plugin.py` runs without it and still prints OK")


class AuthScript(unittest.TestCase):
    """The skill carries the device-code flow. On this host that is a CHOICE, not a limit.

    Codex, Copilot and OpenCode cannot ship a command at all -- their plugin formats have
    no command component. Cursor does: a plugin discovers a `commands/` directory. What
    stopped the commands shipping here is the piece that fails silently. A command body
    names its plugin's directory through a placeholder, and the equivalent on Grok
    (`${CLAUDE_PLUGIN_ROOT}`) expanded to nothing and handed the shell an absolute path to
    a file that has never existed on any machine, with the plugin correctly on disk beside
    it. Checking `${CURSOR_PLUGIN_ROOT}` needs a signed-in `cursor-agent`, and
    `cursor-agent status` said `Not logged in`.

    So the skill route ships -- it needs no placeholder -- and the README says why the
    commands are absent, so their absence reads as a decision rather than an oversight.
    """

    SCRIPT = SKILL / "scripts" / "memvara_auth.py"
    COMMANDS = ("authenticate", "login", "logout", "stats")

    def test_the_skill_ships_the_auth_script(self) -> None:
        """Positive, because the failure to catch is a deletion."""
        self.assertTrue(
            self.SCRIPT.is_file(),
            f"{self.SCRIPT.relative_to(ROOT)} is missing; the README tells the user it "
            "is there")

    def test_the_script_runs_here_and_names_every_command(self) -> None:
        """Executed rather than read, on the interpreter running this suite. A byte diff
        against the library cannot see a broken script: a library that shipped one hands
        every repo two copies that are equally broken and agree."""
        done = subprocess.run(
            [sys.executable, str(self.SCRIPT), "not-a-command"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        for command in self.COMMANDS:
            self.assertIn(command, done.stdout,
                          f"the usage this prints omits {command}")

    def test_the_readme_names_the_in_repo_path_and_it_resolves(self) -> None:
        """Only the path this checkout can actually verify.

        The sibling repo learned this the expensive way: an install path was written out
        from memory, string-matched by its own guard, and pointed at the wrong directory
        -- and it was the fallback offered because resolution was unverified. So this
        README states the in-repo path, which is checkable, and tells the reader to supply
        an absolute one rather than naming a location nobody here has confirmed.
        """
        text = _readme_prose(ROOT)
        quoted = "plugin/skills/memvara/scripts/memvara_auth.py"
        self.assertIn(quoted, text, "the README never names the auth script")
        self.assertTrue((ROOT / quoted).is_file(),
                        f"the README says {quoted}, and nothing is there")
        self.assertIn("no `pip install`", text)

    def test_the_readme_does_not_invent_an_install_path(self) -> None:
        """The other half of the test above, and the actual lesson from the sibling repo.

        A path nobody checked is worse than no path: it looks authoritative, it is what a
        stuck reader reaches for, and it fails with `No such file or directory` on a
        machine where the file is sitting correctly on disk. Until someone verifies where
        a Cursor plugin's skill lands, this README must not name one.
        """
        text = _readme_prose(ROOT)
        # The hazard is a runnable command pointing somewhere nobody checked, not one
        # particular spelling of it. Forbidding `~/.cursor/plugins` caught the prefix
        # already thought of and would have passed `$HOME/...`, `/Users/...` or
        # `~/Library/Application Support/Cursor/...` -- each of which sends a stuck reader
        # to a path that does not exist on their machine, which is the defect
        # openclaw-memvara shipped and had to fix. This README's whole position is that it
        # offers no runnable absolute invocation, so that is what gets asserted.
        for absolute in ("python3 ~/", "python3 /", "python3 $HOME"):
            self.assertNotIn(absolute, text,
                             f"the README runs the script from {absolute!r}, an install "
                             "location nothing here has verified; check it on a "
                             "signed-in host before naming one")
        self.assertIn("not written out here because it has not been checked", text,
                      "the README should say WHY it gives no install path, or the "
                      "omission reads as forgetfulness")

    def test_the_readme_says_why_no_command_ships(self) -> None:
        """This host CAN carry one, so silence would read as an oversight.

        Positive, and it must name the placeholder: "no commands here" without the reason
        is indistinguishable from nobody having tried.
        """
        text = _readme_prose(ROOT)
        self.assertIn("No `/memvara authenticate` yet, and why", text)
        self.assertIn("${CURSOR_PLUGIN_ROOT}", text,
                      "the section does not name the thing that was not verified")
        self.assertIn("Not logged in", text,
                      "the section does not say what blocked the check, so a reader "
                      "cannot tell a blocked measurement from a negative result")

    def test_the_readme_no_longer_promises_no_python(self) -> None:
        """It said "there is no local Python process", and now one ships. Both
        directions, against normalised prose so a rewrapped reintroduction is caught."""
        text = _readme_prose(ROOT)
        self.assertNotIn("no local Python process", text,
                         "the README still claims no Python ships, and a Python script "
                         "is sitting in plugin/skills/memvara/scripts/")
        # This required "Nothing runs in the background", true while the only Python
        # here was a command the user typed. The plugin now runs python3 at session start,
        # on tool use and at session end. Requiring the positive disclosure instead means
        # a README that quietly stops mentioning it fails as loudly as one that denies it.
        self.assertNotIn("Nothing runs in the background", text)
        self.assertIn("Making memory automatic", text,
                      "the README has no section saying what this plugin runs locally")
        self.assertIn("~/.memvara/.hooks/", text,
                      "the README does not name where the hooks account for themselves, "
                      "and on this host that log is the only account there is")


if __name__ == "__main__":
    unittest.main()
