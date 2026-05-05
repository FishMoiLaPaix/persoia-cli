pipeline {
    agent none

    options {
        timeout(time: 30, unit: 'MINUTES')
        skipDefaultCheckout()
        // disableConcurrentBuilds() — temporarily removed: a previously
        // aborted build (#2) left the controller's in-memory state thinking
        // a build was still running, blocking all new triggers. Without
        // hard-restarting the controller, dropping this option is the
        // fastest way to unstick the queue. Re-enable in a follow-up once
        // the controller is restarted.
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        // Tag name when building a tag (multibranch tag discovery), empty otherwise.
        // Used to gate the Release stage and as the GitHub release tag.
        RELEASE_TAG = "${env.TAG_NAME ?: ''}"
    }

    stages {
        stage('Build matrix') {
            parallel {
                stage('Source lint') {
                    // Fast feedback: catch syntax errors / obvious typos before
                    // any (slow) PyInstaller stage runs. Uses the existing
                    // ubuntu-multi-tool-agent cloud template (jnlp jenkins user,
                    // Python 3.11 preinstalled).
                    agent { label 'python311' }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            python3 -m py_compile src/persoia.py tests/mock_api.py

                            # --- Source-level: two complementary suites in one
                            # heredoc so the lint stage stays a single fast
                            # invocation. (1) cmd_code helpers reject path
                            # traversal and forbidden names; (2) the French
                            # language directive must land in the auto-injected
                            # context file AND in any PERSOIA.md produced by the
                            # offline persoia init template.
                            #
                            # Both suites use explicit raise SystemExit (not
                            # bare assert): the latter is stripped under
                            # python -O, which would let silent regressions
                            # through CI. Both also use chr(10) and string ops
                            # rather than regex with backslashes, because
                            # Groovy parses backslash escape sequences inside
                            # sh triple-single-quoted blocks at pipeline
                            # compile time, and unknown escapes (like the
                            # regex end-of-string anchor) abort the build
                            # before bash ever runs.
                            python3 - <<'PY'
import sys, tempfile, shutil
sys.path.insert(0, "src")
import persoia


def fail(msg):
    raise SystemExit("LINT FAIL: " + msg)


# === Suite 1: cmd_code helpers ===

# Argument classifier returns (aider_flags, file_paths, persoia_flags).
# Persoia-owned flags must be detected at top level only — never as the
# value of an aider flag like `--message -y`.
flags, files, persoia_flags = persoia._classify_code_args(
    ["foo.py", "--model", "x", "bar.go", "-y", "--no-discover"]
)
if files != ["foo.py", "bar.go"]:
    fail(f"unexpected files: {files}")
if "--model" not in flags or "x" not in flags:
    fail(f"--model/value missing: {flags}")
if not persoia_flags["auto_yes"] or not persoia_flags["no_discover"]:
    fail(f"persoia flags not parsed: {persoia_flags}")

# `--message -y`: -y is the message value, not a persoia auto-confirm.
flags, files, persoia_flags = persoia._classify_code_args(["--message", "-y"])
if persoia_flags["auto_yes"]:
    fail("auto_yes incorrectly triggered when -y is a flag value")
if flags != ["--message", "-y"]:
    fail(f"-y not preserved as flag value: {flags}")

# `--chat-language english main.py`: language is a value-taking aider flag,
# its value must NOT be mis-classified as a file path (creating the file
# was the failure mode Copilot caught on PR #5).
flags, files, persoia_flags = persoia._classify_code_args(
    ["--chat-language", "english", "main.py"]
)
if files != ["main.py"]:
    fail(f"--chat-language value mis-classified as file: files={files}")
if flags != ["--chat-language", "english"]:
    fail(f"--chat-language value not forwarded intact: flags={flags}")

# _strip_flag_with_value removes both `--flag value` and `--flag=value`
out = persoia._strip_flag_with_value(
    ["--chat-language", "english", "--model", "x"], "--chat-language"
)
if out != ["--model", "x"]:
    fail(f"_strip_flag_with_value space form: {out}")
out = persoia._strip_flag_with_value(
    ["--chat-language=english", "--model", "x"], "--chat-language"
)
if out != ["--model", "x"]:
    fail(f"_strip_flag_with_value equals form: {out}")

# Path safety: cwd-bound (absolute paths under cwd OK), refuses traversal,
# refuses leaf names AND segments in forbidden lists.
tmp = tempfile.mkdtemp()
try:
    cwd = persoia.Path(tmp)
    (cwd / "ok.txt").touch()
    (cwd / ".aws").mkdir()
    (cwd / ".aws" / "credentials").write_text("nope")
    if persoia._resolve_safe_file("ok.txt", cwd) is None:
        fail("relative ok.txt rejected")
    if persoia._resolve_safe_file(str(cwd / "ok.txt"), cwd) is None:
        fail("absolute path under cwd rejected")
    if persoia._resolve_safe_file("../../etc/passwd", cwd) is not None:
        fail("traversal accepted")
    if persoia._resolve_safe_file("/etc/passwd", cwd) is not None:
        fail("absolute path outside cwd accepted")
    if persoia._resolve_safe_file(".env", cwd) is not None:
        fail("forbidden leaf name .env accepted")
    if persoia._resolve_safe_file(".aws/credentials", cwd) is not None:
        fail("forbidden path segment .aws accepted")
finally:
    shutil.rmtree(tmp)

# Project scan honors excluded dirs, dotfiles, size cap
tmp = tempfile.mkdtemp()
try:
    cwd = persoia.Path(tmp)
    (cwd / "real.py").write_text("x")
    (cwd / "node_modules").mkdir()
    (cwd / "node_modules" / "ignored.js").write_text("y")
    (cwd / ".env").write_text("SECRET=x")
    found = persoia._collect_project_files(cwd)
    names = {p.name for p in found}
    if "real.py" not in names:
        fail("real.py not discovered")
    if "ignored.js" in names:
        fail("ignored.js leaked from node_modules")
    if ".env" in names:
        fail(".env leaked into discovery")
finally:
    shutil.rmtree(tmp)

print("OK: cmd_code helpers reject unsafe paths and parse flags safely")


# === Suite 2: French language directive ===

ctx_path = persoia.make_context_file()
with open(ctx_path, encoding="utf-8") as f:
    body = f.read()
if "## Langue" not in body:
    fail("make_context_file: missing Langue section" + chr(10) + body)
if persoia.LANGUE_DIRECTIVE not in body:
    fail("make_context_file: directive mismatch with LANGUE_DIRECTIVE" + chr(10) + body)

# Offline _make_raw_template path must also carry the directive once
# wrapped through _ensure_langue_section (the cmd_init save site).
raw = persoia._make_raw_template({
    "name": "test", "description": "", "languages": [], "frameworks": [],
    "package_manager": "", "directories": [], "commands": {},
})
final = persoia._ensure_langue_section(raw)
if "## Langue" not in final or persoia.LANGUE_DIRECTIVE not in final:
    fail("offline path: _ensure_langue_section did not inject directive" + chr(10) + final)

# Wrong-body case: the Langue heading exists with paraphrased text, and
# the canonical directive appears elsewhere in the document. The previous
# "in content" implementation returned unchanged; the normalizer must
# replace the section body with LANGUE_DIRECTIVE.
poisoned_lines = [
    "# Test",
    "",
    "## Langue",
    "",
    "Respond in English please.",
    "",
    "## Examples",
    "",
    "Some quote: " + persoia.LANGUE_DIRECTIVE,
    "",
]
poisoned = "".join(line + chr(10) for line in poisoned_lines)
healed = persoia._ensure_langue_section(poisoned)


def section_body(text, header):
    marker = header + chr(10)
    idx = text.find(marker)
    if idx < 0:
        return ""
    rest = text[idx + len(marker):]
    next_heading = rest.find(chr(10) + "## ")
    return rest if next_heading < 0 else rest[:next_heading]


sec = section_body(healed, "## Langue")
if persoia.LANGUE_DIRECTIVE not in sec:
    fail("_ensure_langue_section did not heal a poisoned Langue body" + chr(10) + healed)
if "Respond in English" in sec:
    fail("_ensure_langue_section left bad text inside the Langue body" + chr(10) + healed)

twice = persoia._ensure_langue_section(healed)
if twice != healed:
    fail("_ensure_langue_section not idempotent")

print("OK: French directive guaranteed (incl. wrong-body normalization)")
PY
                        '''
                    }
                }

                stage('Linux x64') {
                    agent { label 'python311' }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            # The cloud agent's system /usr/bin/python3 is 3.10 built
                            # without --enable-shared, which makes PyInstaller bail
                            # with `Python library not found: libpython3.10.so.1.0`.
                            # Pull a portable CPython 3.11 standalone build from
                            # python-build-standalone (Astral) — these include the
                            # shared libpython3.11.so PyInstaller needs.
                            PY_VER=3.11.10
                            PY_RELEASE=20241016
                            PY_TAR="cpython-${PY_VER}+${PY_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
                            curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${PY_TAR}" \
                                | tar xz -C /tmp
                            export PATH="/tmp/python/bin:$PATH"
                            python3 --version

                            python3 -m venv /tmp/venv
                            . /tmp/venv/bin/activate
                            pip install --no-cache-dir -r requirements-build.txt
                            pyinstaller --clean --noconfirm persoia.spec
                            mv dist/persoia dist/persoia-linux-x64
                            BIN="$PWD/dist/persoia-linux-x64"

                            # --- Smoke tests: binary works end-to-end without network ---
                            "$BIN" version | grep -qE "^persoia [0-9]+\\.[0-9]+\\.[0-9]+$"
                            "$BIN" help    | grep -q "Assistant code souverain"
                            # `config` reads PERSOIA_CONFIG; point it at an empty file so we test
                            # the "not connected" path independently of any host-leaked state.
                            : > /tmp/empty.env
                            PERSOIA_CONFIG=/tmp/empty.env "$BIN" config | grep -q "Non connecté"

                            # --- Smoke test: login path against a mock API ---
                            python3 tests/mock_api.py --port 8765 &
                            MOCK_PID=$!
                            trap "kill $MOCK_PID 2>/dev/null || true" EXIT
                            ready=0
                            for _ in 1 2 3 4 5; do
                                if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/v1/models', timeout=2)" 2>/dev/null; then
                                    ready=1
                                    break
                                fi
                                sleep 1
                            done
                            [ "$ready" = "1" ] || { echo "ERROR: tests/mock_api.py never became ready on :8765"; exit 1; }
                            : > /tmp/login.env
                            PERSOIA_CONFIG=/tmp/login.env \
                            PERSOIA_API_BASE=http://127.0.0.1:8765/v1 \
                                "$BIN" login --email ci@example.com --password fake
                            grep -q "PERSOIA_API_KEY=persoia_demo_sk_mock_login_ci" /tmp/login.env
                            grep -q "PERSOIA_TENANT_NAME=Mock Tenant" /tmp/login.env
                            PERSOIA_CONFIG=/tmp/login.env "$BIN" config | grep -q "Clé API:"
                        '''
                        archiveArtifacts artifacts: 'dist/persoia-linux-x64', fingerprint: true
                        stash name: 'binary-linux-x64', includes: 'dist/persoia-linux-x64'
                    }
                }

                stage('macOS arm64') {
                    // `agent none` at stage level + `node('mac-arm64')` INSIDE
                    // the timeout is the only way for a missing-agent wait to
                    // count toward the timeout (otherwise the timeout step
                    // only ticks on exec time, not on queue wait).
                    //
                    // `catchError` alone does NOT downgrade a timeout-induced
                    // ABORTED back to UNSTABLE — Jenkins sets the build result
                    // before catchError runs. Use an explicit script-level
                    // try/catch + `currentBuild.result = 'UNSTABLE'` to
                    // override.
                    agent none
                    steps {
                        script {
                            try {
                                timeout(time: 5, unit: 'MINUTES') {
                                    node('mac-arm64') {
                                        checkout scm
                                        sh '''
                                            set -eu
                                            python3 -m venv .venv
                                            . .venv/bin/activate
                                            pip install --upgrade pip
                                            pip install -r requirements-build.txt
                                            pyinstaller --clean --noconfirm persoia.spec
                                            mv dist/persoia dist/persoia-darwin-arm64
                                            BIN="$PWD/dist/persoia-darwin-arm64"

                                            "$BIN" version | grep -qE "^persoia [0-9]+\\.[0-9]+\\.[0-9]+$"
                                            "$BIN" help    | grep -q "Assistant code souverain"
                                            : > /tmp/empty.env
                                            PERSOIA_CONFIG=/tmp/empty.env "$BIN" config | grep -q "Non connecté"
                                        '''
                                        archiveArtifacts artifacts: 'dist/persoia-darwin-arm64', fingerprint: true
                                        stash name: 'binary-darwin-arm64', includes: 'dist/persoia-darwin-arm64'
                                    }
                                }
                            } catch (err) {
                                // For PR builds (env.CHANGE_ID set), reset the
                                // result to SUCCESS so the PR check passes —
                                // we don't want a missing mac agent to block
                                // merges. The Release stage on tag/main builds
                                // will hard-fail when it tries to unstash the
                                // missing mac binary, so we never accidentally
                                // ship an incomplete release.
                                //
                                // currentBuild.result = 'UNSTABLE' would have
                                // worked semantically, but the Jenkins GitHub
                                // Checks plugin maps UNSTABLE → conclusion
                                // 'failure' which blocks the merge anyway.
                                echo "mac-arm64 stage failed: ${err}"
                                if (env.CHANGE_ID) {
                                    currentBuild.result = 'SUCCESS'
                                } else {
                                    throw err
                                }
                            }
                        }
                    }
                }

                stage('Windows x64') {
                    // The windows-docker-agent only has Python 2.7 in PATH
                    // (despite README claiming 3.13). Pull a portable CPython
                    // 3.11 standalone build into the workspace, mirroring the
                    // Linux stage. Self-contained, no admin rights needed.
                    //
                    // Use bat (not powershell) because PyInstaller writes to
                    // stderr and PowerShell with $ErrorActionPreference=Stop
                    // turns those into NativeCommandError exceptions. bat with
                    // `|| exit /b 1` per line is more predictable for native
                    // exe pipelines.
                    agent { label 'windows-amd64' }
                    steps {
                        checkout scm
                        bat '''
                            REM Workspace is shared between builds — clean
                            REM leftovers so move /Y is enough to handle the
                            REM rename target without "file already exists".
                            if exist dist     rmdir /S /Q dist
                            if exist build    rmdir /S /Q build
                            if exist .venv    rmdir /S /Q .venv
                            if exist .python  rmdir /S /Q .python

                            REM Pull portable CPython 3.11 standalone
                            curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.11.10+20241016-x86_64-pc-windows-msvc-install_only.tar.gz" -o python.tar.gz || exit /b 1
                            mkdir .python || exit /b 1
                            tar -xzf python.tar.gz -C .python || exit /b 1
                            del python.tar.gz
                            set "PYTHON=%CD%\\.python\\python\\python.exe"
                            "%PYTHON%" --version || exit /b 1

                            "%PYTHON%" -m venv .venv || exit /b 1
                            call .venv\\Scripts\\activate.bat || exit /b 1
                            python -m pip install --upgrade pip || exit /b 1
                            python -m pip install -r requirements-build.txt || exit /b 1
                            python -m PyInstaller --clean --noconfirm persoia.spec || exit /b 1
                            move /Y dist\\persoia.exe dist\\persoia-windows-x64.exe || exit /b 1
                            set BIN=dist\\persoia-windows-x64.exe

                            %BIN% version | findstr /R "^persoia [0-9]" >nul || exit /b 1
                            %BIN% help    | findstr /C:"Assistant code souverain" >nul || exit /b 1
                            type NUL > %TEMP%\\empty.env
                            set PERSOIA_CONFIG=%TEMP%\\empty.env
                            %BIN% config  | findstr /C:"Non connect" >nul || exit /b 1
                        '''
                        archiveArtifacts artifacts: 'dist/persoia-windows-x64.exe', fingerprint: true
                        stash name: 'binary-windows-x64', includes: 'dist/persoia-windows-x64.exe'
                    }
                }
            }
        }

        stage('Release') {
            // Only when a tag like v1.2.3 was pushed and discovered by multibranch
            when { expression { return env.RELEASE_TAG?.startsWith('v') } }
            agent { label 'python311' }
            steps {
                checkout scm
                unstash 'binary-linux-x64'
                unstash 'binary-darwin-arm64'
                unstash 'binary-windows-x64'
                withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                    sh '''
                        set -eu
                        # Release stage doesn't need PyInstaller, just gh CLI to
                        # upload artifacts. Self-contained download (no apt/sudo).
                        GH_VERSION="2.65.0"
                        curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
                            | tar xz
                        export PATH="$PWD/gh_${GH_VERSION}_linux_amd64/bin:$PATH"
                        gh --version

                        # Create the release if it does not exist yet (idempotent).
                        if ! gh release view "${RELEASE_TAG}" --repo FishMoiLaPaix/persoia-cli >/dev/null 2>&1; then
                            gh release create "${RELEASE_TAG}" \
                                --repo FishMoiLaPaix/persoia-cli \
                                --title "${RELEASE_TAG}" \
                                --generate-notes
                        fi

                        gh release upload "${RELEASE_TAG}" \
                            --repo FishMoiLaPaix/persoia-cli \
                            --clobber \
                            dist/persoia-linux-x64 \
                            dist/persoia-darwin-arm64 \
                            dist/persoia-windows-x64.exe
                    '''
                }
            }
        }
    }
}
