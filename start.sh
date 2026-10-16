#!/bin/sh
# Start Open Health Archive on macOS or Linux: import the newest Health Connect
# export from the chosen folder, then open the viewer. Run with --choose to pick
# the folders again, or --xiaomi <export folder> to import a Mi Fitness export
# instead. Everything except the folder dialogs runs in Docker.
# HEALTHVIZ_CONFIG_DIR and HEALTHVIZ_CACHE_DIR override the private folders.
set -eu
cd "$(dirname "$0")"

CONFIG_DIR=${HEALTHVIZ_CONFIG_DIR:-$HOME/.config/healthviz}
PREFS=$CONFIG_DIR/launcher.conf
URL=http://127.0.0.1:8501
NEWLINE='
'
die() {
    printf '%s\n' "$*" >&2
    exit 1
}

# Read one saved preference; the file is parsed, never sourced.
pref() {
    [ -f "$PREFS" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in "$1="*) printf '%s\n' "${line#*=}" ;; esac
    done < "$PREFS"
}

pick_folder() {
    if [ "$(uname -s)" = Darwin ]; then
        osascript -e "POSIX path of (choose folder with prompt \"$1\")" 2>/dev/null | sed 's#/$##'
    elif command -v zenity >/dev/null 2>&1; then
        zenity --file-selection --directory --title="$1" 2>/dev/null
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --getexistingdirectory "$HOME" --title "$1" 2>/dev/null
    else
        printf '%s: ' "$1" >&2
        IFS= read -r answer || true
        printf '%s\n' "$answer"
    fi
}

folder() {
    value=$(pref "$1")
    if [ "$choose" = 1 ] || [ -z "$value" ] || [ ! -d "$value" ]; then
        value=$(pick_folder "$2") || true
    fi
    case $value in *"$NEWLINE"*) die "Folder names with line breaks are not supported." ;; esac
    [ -n "$value" ] && [ -d "$value" ] || die "No folder chosen; nothing was started."
    printf '%s\n' "$value"
}

cache_dir() {
    if [ "$(uname -s)" = Darwin ]; then
        printf '%s\n' "$HOME/Library/Caches/OpenHealthArchive/viewer"
    else
        printf '%s\n' "${XDG_CACHE_HOME:-$HOME/.cache}/open-health-archive/viewer"
    fi
}

compose() {
    docker compose -f compose.yaml -f compose.launcher.yaml "$@"
}

choose=0
xiaomi=
while [ $# -gt 0 ]; do
    case $1 in
        --choose)
            choose=1
            shift
            ;;
        --xiaomi)
            xiaomi=${2:-}
            [ -n "$xiaomi" ] && [ -d "$xiaomi" ] || die "--xiaomi needs an existing export folder."
            shift 2
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

command -v docker >/dev/null 2>&1 || die "Docker is required: install and start Docker Desktop or Docker Engine."
archive=$(folder archive_dir "Choose the archive folder")
# A Xiaomi import reads the export given on the command line; the Health Connect
# folder stays as it was saved.
if [ -n "$xiaomi" ]; then
    imports=$(pref import_dir)
else
    imports=$(folder import_dir "Choose the folder where you download Health Connect exports")
fi
mkdir -p "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR"
printf 'archive_dir=%s\nimport_dir=%s\n' "$archive" "$imports" > "$PREFS"
chmod 600 "$PREFS"
cache=${HEALTHVIZ_CACHE_DIR:-$(cache_dir)}
cache_parent=$(dirname "$cache")
# Only a parent this script creates is made private; an existing one is left as it is.
if [ ! -d "$cache_parent" ]; then
    mkdir -p "$cache_parent" && chmod 700 "$cache_parent"
fi

# The import container reads one folder: Health Connect's, or the Xiaomi export.
source_dir=${xiaomi:-$imports}
label=$source_dir
case $source_dir in "$HOME"/*) label="~/${source_dir#"$HOME"/}" ;; esac
export HEALTHVIZ_ARCHIVE_DIR="$archive" HEALTHVIZ_IMPORT_DIR="$source_dir" \
    HEALTHVIZ_IMPORT_LABEL="$label" HEALTHVIZ_CONFIG_DIR="$CONFIG_DIR" HEALTHVIZ_CACHE_DIR="$cache"

# Rebuild so an updated checkout is what runs; without network keep the existing image.
if ! compose build viewer; then
    docker image inspect open-health-archive-viewer >/dev/null 2>&1 ||
        die "Could not build the viewer image; connect to the internet once and retry."
    printf '%s\n' "Could not rebuild; using the existing image." >&2
fi
# The viewer's own identity creates the cache: a host-created directory can appear
# owned by another user inside the container, and the read model refuses it.
if [ ! -d "$cache" ]; then
    docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true \
        --mount "type=bind,src=$cache_parent,dst=/cache-parent" open-health-archive-viewer \
        python -c 'import os, sys; os.mkdir("/cache-parent/" + sys.argv[1], 0o700)' "$(basename "$cache")" ||
        die "Could not create the private cache folder."
fi
compose stop viewer >/dev/null 2>&1 || true
# On Linux bind mounts keep host ownership, so the import writes as the current user.
if [ "$(uname -s)" = Linux ]; then
    set -- --user "$(id -u):$(id -g)"
else
    set --
fi
if [ -n "$xiaomi" ]; then
    compose run --rm "$@" import-xiaomi || printf '%s\n' "Xiaomi import failed; see the lines above." >&2
else
    compose run --rm "$@" import || printf '%s\n' "Import failed; the viewer shows the reason." >&2
fi
compose up -d viewer

if command -v curl >/dev/null 2>&1; then
    tries=0
    until curl -fsS "$URL/_stcore/health" >/dev/null 2>&1 || [ "$tries" -ge 60 ]; do
        tries=$((tries + 1))
        sleep 1
    done
fi
if [ "$(uname -s)" = Darwin ]; then
    open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
fi
printf 'Open Health Archive: %s\n' "$URL"
