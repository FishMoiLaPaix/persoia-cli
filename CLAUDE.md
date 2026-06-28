# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Jenkins agents & labels

Builds run on jenkins.thefrenchies.com — pick the right agent label in Jenkinsfiles:

| Need | Label |
|---|---|
| Generic Linux build | `jnlp-linux-amd64` (ephemeral K8s pod, default) |
| Docker image build | `docker-enabled` |
| Infra self-deploy (helmfile/k3d) | `k8s-management` (never a K8s pod — killed mid-deploy) |
| macOS / iOS / Electron-mac | `mac-arm64` (aliases: macos, macos-arm64, darwin) |
| Android | `android` (NOT `android-sdk` — does not exist) |
| Windows / Electron-win | `windows` |
| Node / persoIA services | `nodejs` / `node` / `ia-workstation` |
| Go / Python / E2E | `golang` / `python` / `e2e` (or `playwright`) |
| Arduino firmware | `arduino` |

Full inventory (nodes, executors, all labels, usage): https://github.com/FishMoiLaPaix/k3d-cluster/blob/main/docs/jenkins-agents.md
