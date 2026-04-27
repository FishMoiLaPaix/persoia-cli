pipeline {
    agent none

    options {
        timeout(time: 30, unit: 'MINUTES')
        skipDefaultCheckout()
        disableConcurrentBuilds()
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
                    agent { label 'mac-arm64' }
                    // Fail fast if no mac-arm64 agent is available (the
                    // MacBook Pro might be offline or not yet provisioned).
                    // Tag builds will still hard-fail at the Release stage
                    // because the binary stash will be missing, so we don't
                    // accidentally publish an incomplete release.
                    options { timeout(time: 5, unit: 'MINUTES') }
                    steps {
                        // PR builds tolerate a missing mac binary (UNSTABLE
                        // instead of FAILURE) so the rest of the matrix can
                        // still gate the merge. The Release stage downstream
                        // will hard-fail on `unstash` when no Mac binary is
                        // available, which is the desired behaviour for
                        // tag builds.
                        catchError(
                            buildResult: 'UNSTABLE',
                            stageResult: 'FAILURE',
                            message: 'mac-arm64 agent unavailable or stage failed — Release stage (tag builds) will block on missing binary.'
                        ) {
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

                stage('Windows x64') {
                    // Reuse the existing permanent node `windows-docker-agent`
                    // (declared in k3d-cluster JCasC, provisioned by
                    // jenkins-agents-ansible/playbooks/windows-agent.yml).
                    // It already ships Python 3.13, so we just create a venv.
                    agent { label 'windows-amd64' }
                    steps {
                        checkout scm
                        bat '''
                            python -m venv .venv
                            call .venv\\Scripts\\activate.bat
                            python -m pip install --upgrade pip
                            pip install -r requirements-build.txt
                            pyinstaller --clean --noconfirm persoia.spec
                            move dist\\persoia.exe dist\\persoia-windows-x64.exe
                            set BIN=dist\\persoia-windows-x64.exe

                            %BIN% version | findstr /R "^persoia [0-9]" || exit /b 1
                            %BIN% help    | findstr /C:"Assistant code souverain" || exit /b 1
                            type NUL > %TEMP%\\empty.env
                            set PERSOIA_CONFIG=%TEMP%\\empty.env
                            %BIN% config  | findstr /C:"Non connect" || exit /b 1
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
                        # Self-contained gh CLI install — the Jenkins agent runs as
                        # an unprivileged jnlp user, so we can't apt-get. Download
                        # the standalone tarball into the workspace instead.
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
