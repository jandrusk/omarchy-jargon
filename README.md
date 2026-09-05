# Jargon

A small Omarchy popup that draws a random entry from the
[Jargon File glossary](https://andrusk.com/jargon/html/go01.html) and shows
the definition in a floating window on the current workspace.

## Install

This plugin already lives at `~/.config/omarchy/plugins/jra.jargon/` on this
machine. Enable it and bind a key:

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable jra.jargon

A Hyprland window rule in `~/.config/hypr/hyprland.lua` floats the popup
on the current workspace (not pinned across all of them).
```

```lua
-- ~/.config/hypr/bindings.lua
o.bind("SUPER + SHIFT + J", "Jargon", "omarchy-shell shell toggle jra.jargon")
```

From a git checkout elsewhere:

```bash
omarchy plugin add <git-url> --enable
```

## Use

- `Super + Shift + J` — open or close the popup
- Drag the title (or Super + left mouse) — move it on the current workspace
- `Super + Shift + 1`…`0` — send it to another workspace
- `Space` / `n` / `r` — another random entry
- Click a link in the definition — open it in the default browser
- `Enter` — open the source page in the default browser
- `Escape` — close
- Arrow keys — scroll a long definition

It is a normal floating Hyprland window (not pinned), so it stays on the
workspace you leave it on.

## Remove

```bash
omarchy plugin disable jra.jargon
omarchy plugin remove jra.jargon
```

The second command only applies if the plugin was installed with
`omarchy plugin add`. A hand-dropped folder can be deleted from
`~/.config/omarchy/plugins/jra.jargon/`.
