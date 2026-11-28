# Atom for Antigravity CLI

Atom can live in [Antigravity CLI](https://antigravity.google/docs/cli/statusline/) (`agy`) as a
custom status line: a small pixel Atom under the CLI's own status line that reacts to
what the agent is doing. Run `python3 atom_status.py --demo` to see every state.

## Stays within Antigravity's terms

The CLI version only uses features Antigravity documents for this:

| Piece | Documented feature |
|---|---|
| `atom_hook.py` via `hooks.json` | [Plugin lifecycle hooks](https://antigravity.google/docs/plugins/) |
| `atom_status.py` | [CLI custom status line](https://antigravity.google/docs/cli/statusline/) |

It never wraps, launches, patches or injects into `agy`, never talks to the network, and
never stores the status line's `email`, title, paths or prompts. (The desktop overlay,
`atom_launch.py`, works differently and isn't used here.)

## Install

1. Install Atom's plugin, which supplies the hooks (skip this if the desktop installer already did):

   ```bash
   agy plugin install /path/to/atom
   ```

2. Make Atom the status line:

   ```bash
   python3 /path/to/atom/atom_cli_setup.py
   ```

   This adds one block to `~/.gemini/antigravity-cli/settings.json` and backs the file up
   first. If you already have a custom status line it stops and asks for `--force`. The
   old line is saved, and `--uninstall` puts it back.

   ```json
   "statusLine": {
     "type": "command",
     "command": "python3 -S -I /path/to/atom/atom_status.py",
     "stack_with_default": true
   }
   ```

3. Restart `agy`.

Turn it off with `python3 atom_cli_setup.py --uninstall`, or in the CLI with
`/statusline disable`.

## Options

| Option | |
|---|---|
| `--skin v2` | Atom V2: round blob with a rainbow beanie and pom-pom (default) |
| `--skin atom` / `--skin chibi` / `--skin base-qt` | the classic box Atom / Cozy Chibi / base qt. (`ATOM_SKIN` works too) |
| `--style auto` | pixel Atom at 50+ columns, one line below that (default) |
| `--style sprite` / `--style line` | always the pixel Atom / always one line |
| `--color 256` | for terminals without truecolor (`ATOM_COLOR=256` works too) |
| `--color none` | no colour (one line); `NO_COLOR` is honoured |

Pass them to `atom_cli_setup.py` and it writes them into the command.

To see every state without running `agy`: `python3 atom_status.py --demo`
(add `--skin chibi` etc. for another skin, or `--skin all` to see every skin).

The skins are small hand-drawn terminal versions of the desktop skins in `assets/`, using the
same ids. Moods only recolour the blue body and leave the beanie stripes alone, as on the desktop.

## What Atom shows

| When | Atom |
|---|---|
| Waiting for you to approve a tool (`tool_confirmation_pending`) | wide eyes, yellow crown: *needs your OK* |
| Thinking / writing code / running a command / reading & searching | eyes up / down / right / left |
| Subagents running | *delegating…*, with how many |
| Turn finished | *done!* (or *hit an error*, *stopped*, *hit the step limit*) until the next turn |
| You were rude / kind in your prompt | angry or sad look for that turn / blush |
| Every enabled quota bucket used up, or the model hit its limit | asleep, *back at 14:30* |
| Background tasks | *keeping watch…* |

## How it works

- The CLI runs `atom_status.py` whenever the agent state changes. It throttles runs
  to one every 300 ms and stops any run after 5 s. It sends the session state as JSON on
  stdin. Atom reads `agent_state`, `tool_confirmation_pending`, `subagents`, `task_count`,
  `quota`, `terminal_width` and `conversation_id`.
- For detail the payload doesn't carry (which tool is running, reactions to your prompt,
  how the turn ended), it reads the files Atom's hooks already write in
  `~/.antigravity-atom` (`convs/<conversation>.json`, `emotion.json`, `limits.json`).
- Its only write is `~/.antigravity-atom/cli/<conversation>.json`: whether the last redraw
  was busy, plus the current reaction, so *done!* survives redraws.
- The status line only redraws on state changes, so Atom changes pose but doesn't
  animate between them.
- It always exits 0 and prints a plain `Atom` if anything goes wrong, because the CLI
  turns off a status line after 30 failures in a row.

## Windows

The CLI runs the command with `cmd /c`. The setup script quotes the path with double
quotes. Use `--python py` if `python3` isn't on your `PATH`.
