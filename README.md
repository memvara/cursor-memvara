# cursor-memvara

Give Cursor a memory it can prove — hosted MCP and the skill that says
how to use it.

Add this repository as a Cursor marketplace and install `memvara`.

The first connection opens a browser so you can click Allow. That grant
lasts 90 days, and no API key ships in the plugin files.

## Making memory automatic, and what Cursor cannot do

Installing the plugin gives you the endpoint and the skill. To have memory
arrive without asking, run:

```
python3 bin/install.py          # writes ~/.cursor/hooks.json
python3 bin/install.py --remove # takes it back out
```

Cursor reads hooks from that file rather than from a plugin manifest — a
manifest `hooks` key was measured on cursor-agent 2026.08.25 and did not
fire, while the config file did. The installer only ever adds or removes
its own entries and leaves everything else in the file alone.

**There is no per-prompt recall on Cursor.** This is the part to read before
you install. `beforeSubmitPrompt` is the event that would carry it, and it
never fires on this client — not on the first message, not on a `--continue`
follow-up, and not from user or project scope. So what you get is:

| | |
|---|---|
| `sessionStart` | your standing memories, once, at the start of a session |
| `preToolUse` | read-only memory tools auto-approved |
| `sessionEnd` | the last exchange mined for anything worth keeping |

Recall during a session is what the model asks for through the MCP tools,
not something injected on every turn as it is on Claude Code. `stop` is
declared by Cursor and never fired in any probe, which is why capture runs
once at the end rather than once a turn.

Capture mines the turn with **your own model** — `cursor-agent --mode ask`,
read-only, with whatever you have configured. It is slower than the
alternative: measured at 32 seconds for one extraction and once over the
90-second budget, so expect it to fail sometimes and say so in the log.
`claude -p` is the fallback if you have Claude Code; with neither,
extraction logs that it could not run rather than storing nothing in
silence.

Nothing this plugin prints reaches your screen — a hook's reply has no
operator channel on this host, measured. Its account of itself is
`~/.memvara/.hooks/`.

## When the browser sign-in will not finish

The skill carries `scripts/memvara_auth.py` — inside the skill directory,
so it is `scripts/memvara_auth.py` under wherever this skill is installed.
In this repository that is `plugin/skills/memvara/scripts/memvara_auth.py`.
It is the device-code flow, standard library only, no `pip install`, and
nothing left running when it returns. It also does `logout` and `stats`.

Ask Cursor to authenticate memvara and it runs the script. If it cannot
find it, give it the absolute path — the install location is not written
out here because it has not been checked on this host, and a path nobody
verified is worse than none.

## No `/memvara authenticate` yet, and why

Cursor is the one host in this family that **could** carry it. A Cursor
plugin discovers a `commands/` directory. Codex and Copilot cannot: their
plugin manifests have no command field, and Codex's own validator rejects
one the same way it rejects a field that does not exist. OpenCode does read
slash commands, from `~/.config/opencode/commands/`, but those are the
user's directories and a plugin has no route into them.

It is not shipped because the piece that fails silently was not measured.
A command body names the plugin's own directory through a placeholder, and
on Grok the equivalent (`${CLAUDE_PLUGIN_ROOT}`) expanded to nothing and
handed the shell an absolute path to a file that has never existed on any
machine — with the plugin sitting correctly on disk beside it. Verifying
`${CURSOR_PLUGIN_ROOT}` needs a signed-in `cursor-agent`, and on the
machine this was written `cursor-agent status` said `Not logged in`.

So the skill route ships, which needs no placeholder, and the commands
wait for someone who can run that check.

URL: `https://app.memvara.dev/mcp`

You can also paste that URL into `.cursor/mcp.json` without the plugin;
the plugin is the path that also loads the skill.

Claude Code: [memvara/claude-memvara](https://github.com/memvara/claude-memvara).
A loop you wrote is `pip install memvara`.

## License

Apache-2.0.

## Teach it your vocabulary

The built-in predicates are a personal-assistant vocabulary. A store of engineering facts
matches none of them, and an unknown predicate takes the safe default twice over:
multi-valued, so nothing supersedes it, and slow-decaying, so this morning's deploy still
ranks as fresh in two years. The first half shows up on the write receipt. The second is
silent.

Server-side configuration, so it is set where the server is launched:

```bash
MEMVARA_PREDICATES=engineering        # or: engineering,./ours.toml
```

A declaration outranks a guess, so a pack corrects a store that already classified
something wrongly rather than only shaping a fresh one.

## Coming from another memory product

```python
from memvara.compat import import_mem0, import_supermemory
```

mem0 records what changed and when, so that import rebuilds supersession. Supermemory
records current state, so its documents arrive as episodes on their original timestamps
and nothing invents a history it was never told — which means plain recall answers from
claims and looks empty until you ask for `include_episodes`. The skill says this at the
point of use.
