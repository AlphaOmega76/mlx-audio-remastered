#!/bin/zsh
# Builds two tiny double-clickable apps (compiled AppleScript, via osacompile — a
# standard macOS tool, no extra dependency) that start and stop the MLX-Audio server.
#
# They are deliberately simple (start-and-return / stop-and-return) rather than a single
# "stays open while running, stops on quit" app: reliably detecting that a user quit a
# running app (as opposed to it still being busy) is not something that could be verified
# without testing on a real, different Mac, so this trades a second icon for something
# that is easy to reason about and test.
#
# Usage: make_launchers.sh <python-executable-in-venv> <port> <target-applications-dir> <server-log-dir>
set -e

VENV_PYTHON="$1"
PORT="$2"
TARGET_DIR="$3"
SERVER_LOG_DIR="$4"

if [ -z "$VENV_PYTHON" ] || [ -z "$PORT" ] || [ -z "$TARGET_DIR" ] || [ -z "$SERVER_LOG_DIR" ]; then
  echo "Usage: make_launchers.sh <venv-python> <port> <target-dir> <server-log-dir>" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR" "$SERVER_LOG_DIR"
LOG_FILE="${MLXA_LOG_FILE:-$HOME/Library/Logs/MLX-Audio.log}"
mkdir -p "$(dirname "$LOG_FILE")"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Start app -------------------------------------------------------------------
cat > "$TMP/start.applescript" <<'EOF'
on run
	try
		set isUp to true
		try
			do shell script "curl -s -o /dev/null http://localhost:__PORT__/v1/models"
		on error
			set isUp to false
		end try

		if isUp is false then
			display notification "Starting the MLX-Audio server. The very first launch can take several minutes while macOS checks the newly installed files (only happens once)." with title "MLX-Audio"
			-- `do shell script` runs with a working directory that isn't writable (it isn't
			-- the user's home folder), and the server creates a small "logs" folder relative
			-- to wherever it's run from unless told otherwise -- so --log-dir is required here,
			-- not optional (without it, the server crashes on startup with "Read-only file
			-- system: 'logs'").
			-- paths are single-quoted below: Application Support has a space in it, which
			-- broke nohup here during real testing (it treated "Application" as the
			-- command and the rest as arguments) until these were quoted.
			do shell script "cd " & quoted form of (POSIX path of (path to home folder)) & " && nohup '__VENV_PYTHON__' -m mlx_audio.server --port __PORT__ --log-dir '__SERVER_LOG_DIR__' > '__LOG_FILE__' 2>&1 &"

			-- The very first time the freshly installed Python and its compiled libraries
			-- (scipy, mlx, numpy, etc.) actually run, macOS checks each one, which measured
			-- about 8 minutes on a real, freshly provisioned Mac during testing -- every run
			-- after that was instant. 90 seconds (the original value here) was not nearly
			-- enough and produced a false "did not start" error on a perfectly good install.
			set isReady to false
			repeat with i from 1 to 600
				try
					do shell script "curl -s -o /dev/null http://localhost:__PORT__/v1/models"
					set isReady to true
					exit repeat
				on error
					delay 1
				end try
			end repeat

			if isReady is false then
				display dialog "MLX-Audio did not start within 10 minutes. This can happen on the very first launch after installing -- try double-clicking MLX-Audio again, since that first check only needs to happen once. If it still doesn't start, check the log at __LOG_FILE__ for details, or ask whoever set this up for help." buttons {"OK"} with icon caution
				return
			end if
		end if

		do shell script "open http://localhost:__PORT__"
	on error errMsg
		display dialog "MLX-Audio ran into a problem starting:" & return & errMsg buttons {"OK"} with icon stop
	end try
end run
EOF

# --- Stop app ----------------------------------------------------------------------
cat > "$TMP/stop.applescript" <<'EOF'
on run
	try
		-- "-sTCP:LISTEN" matters: plain `lsof -ti:PORT` also returns every process merely
		-- connected to the port (an open browser tab's network process, for example), and
		-- this would then kill those too. Only the server is listening.
		do shell script "kill $(lsof -ti tcp:__PORT__ -sTCP:LISTEN) 2>/dev/null; exit 0"
		display notification "MLX-Audio has been stopped." with title "MLX-Audio"
	on error errMsg
		display dialog "Could not stop MLX-Audio:" & return & errMsg buttons {"OK"} with icon caution
	end try
end run
EOF

# Substitute placeholders now (the scripts above are single-quoted heredocs, so none of
# this was touched by the shell yet — the `$(...)` in stop.applescript is meant to be
# evaluated later, when the compiled app actually runs it, not now).
# sed_escape: a path containing & | or \ would otherwise be misread by sed's replacement text.
sed_escape() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }
for f in "$TMP/start.applescript" "$TMP/stop.applescript"; do
  sed -i '' \
    -e "s|__PORT__|$(sed_escape "$PORT")|g" \
    -e "s|__VENV_PYTHON__|$(sed_escape "$VENV_PYTHON")|g" \
    -e "s|__LOG_FILE__|$(sed_escape "$LOG_FILE")|g" \
    -e "s|__SERVER_LOG_DIR__|$(sed_escape "$SERVER_LOG_DIR")|g" \
    "$f"
done

rm -rf "$TARGET_DIR/MLX-Audio.app"
osacompile -o "$TARGET_DIR/MLX-Audio.app" "$TMP/start.applescript"

rm -rf "$TARGET_DIR/Stop MLX-Audio.app"
osacompile -o "$TARGET_DIR/Stop MLX-Audio.app" "$TMP/stop.applescript"

echo "Installed 'MLX-Audio' and 'Stop MLX-Audio' to $TARGET_DIR"
