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
                stage('Linux x64') {
                    agent {
                        docker {
                            image 'python:3.12-slim'
                            label 'docker'
                            args '-u root --entrypoint=""'
                        }
                    }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            apt-get update -qq && apt-get install -y -qq --no-install-recommends \
                                binutils upx-ucl
                            python -m venv /tmp/venv
                            . /tmp/venv/bin/activate
                            pip install --no-cache-dir -r requirements-build.txt
                            pyinstaller --clean --noconfirm persoia.spec
                            mv dist/persoia dist/persoia-linux-x64
                            ./dist/persoia-linux-x64 version
                        '''
                        archiveArtifacts artifacts: 'dist/persoia-linux-x64', fingerprint: true
                        stash name: 'binary-linux-x64', includes: 'dist/persoia-linux-x64'
                    }
                }

                stage('macOS arm64') {
                    agent { label 'mac-arm64' }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            python3 -m venv .venv
                            . .venv/bin/activate
                            pip install --upgrade pip
                            pip install -r requirements-build.txt
                            pyinstaller --clean --noconfirm persoia.spec
                            mv dist/persoia dist/persoia-darwin-arm64
                            ./dist/persoia-darwin-arm64 version
                        '''
                        archiveArtifacts artifacts: 'dist/persoia-darwin-arm64', fingerprint: true
                        stash name: 'binary-darwin-arm64', includes: 'dist/persoia-darwin-arm64'
                    }
                }

                stage('Windows x64') {
                    agent { label 'windows-x64' }
                    steps {
                        checkout scm
                        bat '''
                            python -m venv .venv
                            call .venv\\Scripts\\activate.bat
                            python -m pip install --upgrade pip
                            pip install -r requirements-build.txt
                            pyinstaller --clean --noconfirm persoia.spec
                            move dist\\persoia.exe dist\\persoia-windows-x64.exe
                            dist\\persoia-windows-x64.exe version
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
            agent { label 'docker' }
            steps {
                checkout scm
                unstash 'binary-linux-x64'
                unstash 'binary-darwin-arm64'
                unstash 'binary-windows-x64'
                withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
                    sh '''
                        set -eu
                        # gh CLI is expected on the agent; install if missing.
                        if ! command -v gh >/dev/null 2>&1; then
                            curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                                | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
                            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                                | sudo tee /etc/apt/sources.list.d/github-cli.list
                            sudo apt-get update -qq && sudo apt-get install -y -qq gh
                        fi

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
