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
                            for _ in 1 2 3 4 5; do
                                python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/v1/models', timeout=2)" 2>/dev/null && break
                                sleep 1
                            done
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
                    // `agent none` at stage level + explicit `node('mac-arm64')`
                    // INSIDE the timeout is the ONLY combo where a missing-agent
                    // wait counts toward the timeout AND the
                    // FlowInterruptedException is catchable. With `agent { label
                    // 'mac-arm64' }` at stage level, the agent allocation happens
                    // before the steps block runs, so a missing agent makes the
                    // build pend forever (timeout step ticks on exec time only).
                    agent none
                    steps {
                        catchError(
                            buildResult: 'UNSTABLE',
                            stageResult: 'FAILURE',
                            message: 'mac-arm64 agent unavailable or stage failed — Release stage (tag builds) will block on missing binary.'
                        ) {
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
                        }
                    }
                }

                stage('Windows x64') {
                    // The windows-docker-agent only has Python 2.7 in PATH
                    // (despite README claiming 3.13). Pull a portable CPython
                    // 3.11 standalone build into the workspace, mirroring the
                    // Linux stage. Self-contained, no admin rights needed.
                    agent { label 'windows-amd64' }
                    steps {
                        checkout scm
                        powershell '''
                            $ErrorActionPreference = "Stop"
                            $PyVer = "3.11.10"
                            $PyRelease = "20241016"
                            $PyTar = "cpython-$PyVer+$PyRelease-x86_64-pc-windows-msvc-install_only.tar.gz"
                            $Url = "https://github.com/astral-sh/python-build-standalone/releases/download/$PyRelease/$PyTar"

                            Write-Host "Downloading portable CPython $PyVer ..."
                            New-Item -ItemType Directory -Force -Path .python | Out-Null
                            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile python.tar.gz
                            tar -xzf python.tar.gz -C .python
                            Remove-Item python.tar.gz
                            $env:Path = "$PWD\\.python\\python;$env:Path"
                            python --version

                            python -m venv .venv
                            & ".venv\\Scripts\\Activate.ps1"
                            python -m pip install --upgrade pip
                            python -m pip install -r requirements-build.txt
                            python -m PyInstaller --clean --noconfirm persoia.spec
                            Move-Item dist\\persoia.exe dist\\persoia-windows-x64.exe
                            $Bin = "dist\\persoia-windows-x64.exe"

                            if (-not ((& $Bin version) -match "^persoia \\d+\\.\\d+\\.\\d+$")) {
                                throw "version output did not match"
                            }
                            if (-not ((& $Bin help) -match "Assistant code souverain")) {
                                throw "help text missing marker"
                            }
                            "" | Set-Content $env:TEMP\\empty.env
                            $env:PERSOIA_CONFIG = "$env:TEMP\\empty.env"
                            if (-not ((& $Bin config) -match "Non connect")) {
                                throw "config did not report not-connected state"
                            }
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
