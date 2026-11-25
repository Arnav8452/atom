#!/usr/bin/env bash
# Install or update Atom for the Antigravity app (Linux; macOS see README).
#
#   ./install.sh                 from a checkout
#   ./install.sh --uninstall
#   curl -fsSL https://raw.githubusercontent.com/Arnav8452/atom/main/install.sh | bash
#
# 1. Links this folder into ~/.gemini/config/plugins/atom, so the app runs
#    atom_hook.py on agent events (thinking / typing / idle / reactions).
# 2. Puts an "Antigravity" launcher entry in ~/.local/share/applications that
#    starts the app through atom_launch.py, which draws Atom on the prompt bar.
# Everything is stdlib Python; nothing else in your Antigravity setup changes.
set -euo pipefail

PLUGINS_DIR="${ANTIGRAVITY_PLUGINS_DIR:-$HOME/.gemini/config/plugins}"
LINK="$PLUGINS_DIR/atom"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP="$APPS_DIR/antigravity.desktop"
MARK="X-Atom-Mascot=true"

say() { printf '[atom] %s\n' "$*"; }
warn() {
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    printf '\033[33m[atom] %s\033[0m\n' "$*"
  else
    say "$*"
  fi
}
refresh_desktop_db() { command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" || true; }

if [ "${1:-}" = "--uninstall" ]; then
  if [ -L "$LINK" ]; then rm "$LINK"; say "removed $LINK"; fi
  if [ -f "$DESKTOP" ] && grep -q "$MARK" "$DESKTOP"; then rm "$DESKTOP"; refresh_desktop_db; say "removed $DESKTOP"; fi
  MAC_CMD="$HOME/Applications/Antigravity (Atom).command"
  if [ -f "$MAC_CMD" ] && grep -q "$MARK" "$MAC_CMD"; then rm "$MAC_CMD"; say "removed $MAC_CMD"; fi
  MAC_APP="$HOME/Applications/Antigravity (Atom).app"
  if [ -f "$MAC_APP/Contents/MacOS/antigravity-atom" ] && grep -q "$MARK" "$MAC_APP/Contents/MacOS/antigravity-atom"; then
    rm -rf "$MAC_APP"; say "removed $MAC_APP"
  fi
  say "restart Antigravity to finish. State in ~/.antigravity-atom can be deleted."
  exit 0
fi

command -v python3 >/dev/null || { say "python3 is required"; exit 1; }

# Locate the code: this checkout, or clone/update one when piped from curl.
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ ! -f "$SRC/plugin.json" ]; then
  ATOM_REPO="${ATOM_REPO:-https://github.com/Arnav8452/atom.git}"
  SRC="${ATOM_DIR:-$HOME/.local/share/antigravity-atom}"
  if [ -d "$SRC/.git" ]; then
    git -C "$SRC" pull --ff-only --quiet
  else
    git clone --depth 1 "$ATOM_REPO" "$SRC"
  fi
fi
say "code: $SRC"

# 1. Hooks plugin.
mkdir -p "$PLUGINS_DIR"
if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
  say "$LINK exists and is not a link; move it away and re-run"; exit 1
fi
ln -sfn "$SRC" "$LINK"
say "plugin: $LINK -> $SRC"

# 2. Launcher entry (Linux desktops). Same name as the system entry, so it
#    replaces it in app launchers and for antigravity:// links.
if [ "$(uname)" = "Linux" ]; then
  if [ -f "$DESKTOP" ] && ! grep -q "$MARK" "$DESKTOP"; then
    say "$DESKTOP exists and isn't ours; not touching it."
    say "point its Exec= at: python3 \"$SRC/atom_launch.py\" %U"
  else
    mkdir -p "$APPS_DIR"
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Name=Antigravity
Exec=python3 "$SRC/atom_launch.py" %U
Terminal=false
Type=Application
Icon=antigravity
StartupWMClass=Antigravity
Comment=Antigravity - Agentic Desktop Application (with Atom)
MimeType=x-scheme-handler/antigravity;
Categories=Development;
$MARK
EOF
    refresh_desktop_db
    say "launcher: $DESKTOP"
  fi
else
  MAC_APP="$HOME/Applications/Antigravity (Atom).app"
  MAC_BIN="$MAC_APP/Contents/MacOS/antigravity-atom"
  MAC_RES="$MAC_APP/Contents/Resources"
  mkdir -p "$MAC_APP/Contents/MacOS" "$MAC_RES"
  cat > "$MAC_BIN" <<EOF
#!/usr/bin/env bash
# $MARK
exec python3 "$SRC/atom_launch.py" "\$@"
EOF
  chmod +x "$MAC_BIN"

  ICON_KEY=""
  for res_dir in "/Applications/Antigravity.app/Contents/Resources" "$HOME/Applications/Antigravity.app/Contents/Resources"; do
    if [ -d "$res_dir" ]; then
      for icns in "$res_dir"/*.icns; do
        if [ -f "$icns" ]; then
          cp "$icns" "$MAC_RES/AppIcon.icns"
          ICON_KEY="  <key>CFBundleIconFile</key><string>AppIcon</string>"
          break 2
        fi
      done
    fi
  done

  cat > "$MAC_APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Antigravity (Atom)</string>
  <key>CFBundleDisplayName</key><string>Antigravity (Atom)</string>
  <key>CFBundleIdentifier</key><string>com.arnav8452.antigravity-atom</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>antigravity-atom</string>
$ICON_KEY
</dict>
</plist>
EOF
  say "macOS app bundle: $MAC_APP (Spotlight & Dock ready)"
  say "or start from Terminal: python3 \"$SRC/atom_launch.py\""
fi

if pgrep -i antigravity >/dev/null 2>&1; then
  warn "note: Antigravity is running. Fully quit it before launching."
fi
say "done. Open Antigravity from your launcher to meet Atom."
