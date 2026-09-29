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

LABEL="com.mlxaudio.server.$PORT"

# A tiny runner script lives beside the server's log folder, so the launch command below
# only has to quote one path and works even when paths contain spaces ("Application Support").
RUNNER="$(dirname "$SERVER_LOG_DIR")/run-server.sh"
cat > "$RUNNER" <<RUNNER_EOF
#!/bin/sh
cd "\$HOME"
exec '$VENV_PYTHON' -m mlx_audio.server --port $PORT --log-dir '$SERVER_LOG_DIR'
RUNNER_EOF
chmod +x "$RUNNER"

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
			-- The server is started through launchd (`launchctl submit`), not as a child of
			-- this app. Measured in a fresh macOS VM: a server started as a child (nohup ... &)
			-- made this app keep running forever, even after `quit` or SIGTERM, and a
			-- still-running app just re-activates when double-clicked again instead of running
			-- this script, so "Stop, then MLX-Audio again" silently did nothing. Started through
			-- launchd, this app exits on its own and every double-click runs the script.
			-- launchd restarts a killed server, so Stop uses `launchctl remove`, not just kill.
			-- (run-server.sh does the `cd` to the home folder and passes --log-dir: the server
			-- crashes with "Read-only file system: 'logs'" if started from a read-only cwd. It
			-- is a script so the paths, which contain a space, need quoting only once here.)
			do shell script "launchctl remove __LABEL__ >/dev/null 2>&1; launchctl submit -l __LABEL__ -o '__LOG_FILE__' -e '__LOG_FILE__' -- '__RUNNER__'"

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
				-- don't leave a crashing server restarting forever in the background
				do shell script "launchctl remove __LABEL__ >/dev/null 2>&1; exit 0"
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
		-- remove the launchd job first (launchd would otherwise restart a killed server)
		do shell script "launchctl remove __LABEL__ >/dev/null 2>&1; kill $(lsof -ti tcp:__PORT__ -sTCP:LISTEN) 2>/dev/null; exit 0"
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
    -e "s|__LABEL__|$(sed_escape "$LABEL")|g" \
    -e "s|__RUNNER__|$(sed_escape "$RUNNER")|g" \
    "$f"
done

rm -rf "$TARGET_DIR/MLX-Audio.app"
osacompile -o "$TARGET_DIR/MLX-Audio.app" "$TMP/start.applescript"

rm -rf "$TARGET_DIR/Stop MLX-Audio.app"
osacompile -o "$TARGET_DIR/Stop MLX-Audio.app" "$TMP/stop.applescript"

echo "Installed 'MLX-Audio' and 'Stop MLX-Audio' to $TARGET_DIR"
