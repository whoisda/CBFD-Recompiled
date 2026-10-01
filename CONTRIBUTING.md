# Contributing

Thanks for helping with Conker's Bad Fur Day: Recompiled. This covers how changes
get in, where things live, and what a pull request needs. The [README](README.md)
covers building, and [recomp/README.md](recomp/README.md) explains how the
recompilation works.

**Never include anything from the game** in an issue or pull request: no ROMs,
no extracted assets or code, no recompiled output (`RecompiledFuncs/`). Everything
from the game is extracted from each person's own ROM during the build.

## Reporting a bug

Open an issue with:

- **The version:** shown in the launcher, or the release you downloaded. If
  you built it yourself, the commit.
- **Your system:** the OS, your GPU and its driver, and the graphics backend
  (Direct3D 12, Vulkan or Metal, in the graphics settings).
- **Your settings:** the aspect ratio and resolution, and any mods that are
  enabled.
- **Where it happens:** the level and what you were doing, and whether it
  happens every time. A save from just before it helps a lot.
- **For a crash:** `crash.log` from next to the executable (on Linux, the
  terminal output).
- **For a graphics problem:** a screenshot. Also say whether it happens with the
  aspect ratio set to Original (4:3); that tells widescreen bugs apart from
  everything else.

Check the open issues first, and add to an existing one rather than opening a
duplicate.

## Suggesting a change

For anything bigger than a small fix (a new setting, a change to how something
plays, a new patch to one of the tools), open an issue or a draft pull request
first. That way the approach can be agreed before you spend time on it.

You can also post a patch in an issue (a `git diff` against `main`). It gets
reviewed and applied with credit to you, as #37 and #47 were.

## Branches and pull requests

- **`main` is where work lands.** Open pull requests against `main`.
- **`master` is what's released.** The maintainer merges `main` into `master` and
  tags a release from it (e.g. `V0.1.4`). Don't open pull requests against
  `master`.
- **Keep a pull request to one topic.** Don't mix a fix with unrelated cleanups or
  another feature.
- **Say what you tested:** which system, backend and aspect ratios, and where in
  the game. A change to gameplay or graphics needs a test in game before it's
  merged.
- **CI builds every push to this repository's branches,** on Windows, Linux and
  macOS, and builds the included mods. It needs the ROM, which is kept in a
  secret, so it doesn't run for pull requests from forks. Build the change
  yourself on the systems you can, and say which ones.

## Where things live

| What | Where |
|---|---|
| Hooks into the game's code (a call to host code at a given instruction) | `conker.toml`, with the code in `host/src/` |
| The host: frontend, input, audio, settings, widescreen fixes | `host/src/` |
| Changes to RT64 (the renderer) | `recomp/rt64.patch` |
| Changes to RecompFrontend (menus, input binding) | `recomp/recompfrontend.patch` |
| Changes to N64Recomp / N64ModernRuntime | `recomp/n64recomp.patch`, `recomp/n64modernruntime.patch` |
| The game's symbols (names, addresses, sizes) | `recomp/conker.us.syms.toml`, `mods/syms/`, generated from the decompilation |
| The decompilation | `conker/` |
| The included mods | `mods/` |

### Hooks

A hook in `conker.toml` runs host code at an instruction of a game function
(`before_vram`). Its host function gets the game's registers in `ctx`.

- **Say what the hook relies on,** in a comment above it in `conker.toml` and above
  the host function: the function and address, what the registers you read or
  change hold at that point (e.g. "`$a0` is the camera"), and why the hook is
  there. Hooks depend on the exact instructions around them, so the next person
  needs to know what you relied on.
- **Check the type of what you change.** For example, whether a field is an `s32`
  or an `f32`, or a byte next to other data. Check it in the decompiled C or the
  disassembly; don't guess.
- **Add a setting for anything a player might not want,** and make the
  default match the original game where that makes sense.
- **Recompile after changing `conker.toml`:** `build.cmd` / `build.sh` does it. The
  host build stops with an error if `RecompiledFuncs/` was generated from a different
  `conker.toml`.

### Patches to the tools

The tools in `tools/` are submodules pinned to upstream commits. Our changes to
them are kept as patches in `recomp/`, and the build scripts apply them. To
change one:

1. Make the change in the submodule (for RT64, `tools/rt64`, with the current
   patch applied: `build.cmd` / `build.sh` leaves it applied).
2. Regenerate the patch from the submodule, **including new files**, which
   `git diff` leaves out unless they're added first:

   ```sh
   cd tools/rt64
   git add -N $(git ls-files --others --exclude-standard)
   git diff > ../../recomp/rt64.patch
   git reset -q
   ```

3. Check that it applies to a clean checkout of the pinned commit and builds.
4. Explain the change in `recomp/README.md` ("Local changes to the tools").
5. Keep licenses straight. Code taken or adapted from another project keeps its
   license and credits, in a file of its own with a header saying so (as
   `src/hle/rt64_rice_hash.cpp` in `rt64.patch` does for its GPL code), and the
   license section of `README.md` and `.github/release/LICENSES.txt` say what it
   means for builds. The GPL version 3 of the runtime (N64ModernRuntime) covers
   the program as a whole, so such code must be compatible with it: MIT, BSD,
   zlib, GPL version 2 *or later*, or GPL version 3 are; GPL version 2 *only* isn't.

Prefer small changes that are easy to carry forward when a submodule is updated.

### Mods

Mods live in `mods/<name>/`, with a `mod.toml` and `src/`, and are built with
`sh mods/build_mod.sh mods/<name>` (Linux, macOS or WSL, with `clang` and `lld`).
The release workflow builds every mod in `mods/`, so a new mod needs to build
there. Writing mods is covered in [recomp/README.md](recomp/README.md#mods).

## Code conventions

- **Match the surrounding code:** its naming, comment style and structure.
- **Comments explain what the game does and why the code is needed,** in plain
  language, with the functions, addresses and fields involved. Don't restate
  the code.
- **Function names:** `func_XXXXXXXX` names are placeholders. Once a function is
  understood, give it a descriptive name ending in its address (e.g.
  `resetSlotState_150104F0`), and document what it does. Keep a `func_` name
  that mods or hooks already refer to, or update them in the same change.
- **Decompiled C only goes in when it matches:** it has to compile to exactly the
  original instructions (`./build.sh --decomp` checks this). Names, types and
  comments aren't checked by that, so double-check them.

## Debugging code

Temporary logging and switches are welcome while you track something down, but
they don't get merged:

- **Mark them `TEMP-DEBUG`** in a comment, and put them behind an environment
  variable (e.g. `CONKER_...=1`) so they're off by default.
- **Remove them before the pull request is merged,** or turn them into a real
  setting if they're worth keeping.
- **Keep working notes out of the repository.** A handoff note belongs in an issue
  or the pull request description.

## Testing

Test in game, in the places your change affects. Depending on the change:

- **Graphics:** test at 4:3 (Original), 16:9 and an ultrawide ratio such as 32:9.
  `host/multi_aspect.ps1` runs several aspect ratios side by side on Windows. If
  the change is in the renderer, test both Direct3D 12 and Vulkan.
- **Input:** test keyboard and controller, and multiplayer if ports or bindings
  are involved.
- **Settings:** test that the default leaves the game as it was.
- **Mods:** if you changed something a mod hooks or reads, check the included
  mods still work.

## Commits

- **Summary line:** a short summary of the change (e.g. "Widescreen: don't zoom
  the motion blur's frame copy"), then a body explaining the cause and the fix.
  Reference the issue it fixes.
- **Credit co-authors** with a `Co-Authored-By:` line, including when a pull
  request applies someone's patch from an issue.

## AI-assisted contributions

Much of this project was written with an AI coding assistant (see the README), and
AI-assisted contributions are welcome under the same rules: the change must be
tested in game, the hooks and types checked against the game's code, and the
pull request must say what was verified and how. Say in the pull request that an
AI assistant was used.

## License

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
