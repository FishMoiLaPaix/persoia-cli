#!/usr/bin/env python3
"""PersoIA CLI — Cross-platform wrapper around aider for sovereign AI coding.

The model is determined by the tenant's subscription and fetched
from the API at startup. The user only needs an API key.

Usage:
    persoia login [--email EMAIL --password PASSWORD]
    persoia logout
    persoia init
    persoia code [aider args...]
    persoia chat "message"
    persoia config
    persoia version [--version, -V]
    persoia help
"""

import atexit
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from getpass import getpass
from pathlib import Path

__version__ = "0.5.0"


def collect_persoia_md_files() -> list[Path]:
    """Collect contiguous PERSOIA.md files from current dir upward.

    Walks up from cwd and stops at the first directory that does NOT
    contain a PERSOIA.md.  This prevents loading stale or unrelated
    files from distant parent directories (e.g. $HOME).

    Returns paths ordered from most generic (highest parent with a
    contiguous PERSOIA.md) to most specific (current directory).
    """
    found = []
    current = Path.cwd().resolve()
    while True:
        candidate = current / "PERSOIA.md"
        if candidate.is_file():
            found.append(candidate)
        else:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    found.reverse()
    return found


def get_config_dir() -> Path:
    """Return the config directory, respecting XDG on Linux/macOS and APPDATA on Windows."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "persoia"
    base = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(base) / "persoia"


def get_config_path() -> Path:
    """Return the path to the config file."""
    return Path(os.environ.get("PERSOIA_CONFIG", get_config_dir() / "config.env"))


def resolve_api_base(api_key: str, explicit_base: str) -> str:
    """Resolve the API base URL from the token prefix if the user hasn't set it explicitly.

    Demo tokens (persoia_demo_sk_) route to the demo environment.
    All other tokens (including persoia_sk_) route to the production API.
    If PERSOIA_API_BASE was explicitly set (env var or config file), it takes precedence.
    """
    if explicit_base.strip():
        return explicit_base.strip()
    if api_key.strip().startswith("persoia_demo_sk_"):
        return "https://demo.chat.persoia.com/v1"
    return "https://api.persoia.com/v1"


def load_config() -> dict:
    """Load configuration from the config file. Only PERSOIA_ prefixed keys are allowed."""
    config = {
        "PERSOIA_API_KEY": os.environ.get("PERSOIA_API_KEY", ""),
        "PERSOIA_API_BASE": os.environ.get("PERSOIA_API_BASE", ""),
        "PERSOIA_MODEL": os.environ.get("PERSOIA_MODEL", ""),
        "PERSOIA_TENANT_NAME": os.environ.get("PERSOIA_TENANT_NAME", ""),
    }

    config_path = get_config_path()
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("PERSOIA_"):
                config[key] = value.strip()

    # Auto-detect API base from token prefix when not explicitly configured
    config["PERSOIA_API_BASE"] = resolve_api_base(
        config["PERSOIA_API_KEY"], config["PERSOIA_API_BASE"]
    )

    return config


def save_config(values: dict) -> None:
    """Save configuration to the config file with restrictive permissions."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_config_path()

    lines = ["# PersoIA CLI configuration — généré par persoia login"]
    for key, value in sorted(values.items()):
        if key.startswith("PERSOIA_") and value:
            lines.append(f"{key}={value}")
    lines.append("")

    config_path.write_text("\n".join(lines), encoding="utf-8")

    # Restrictive permissions (Unix only)
    if platform.system() != "Windows":
        config_path.chmod(0o600)


def api_request(
    url: str,
    data: dict | None = None,
    api_key: str | None = None,
    *,
    fatal: bool = True,
    timeout: int = 15,
) -> tuple[int, dict | str] | tuple[None, None]:
    """Make an API request. Returns (status_code, response_body).

    Args:
        url: The endpoint URL.
        data: JSON body to POST (None for GET).
        api_key: Bearer token for Authorization header.
        fatal: If True, exit on network error. If False, return (None, None).
        timeout: Request timeout in seconds.

    Returns:
        (status_code, body) on success/HTTP error, or (None, None) when
        fatal=False and a network error occurs.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data else "GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(content)
            except json.JSONDecodeError:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(content)
        except json.JSONDecodeError:
            return e.code, content
    except urllib.error.URLError as e:
        if fatal:
            print("Erreur : impossible de contacter l'API PersoIA.", file=sys.stderr)
            print("Vérifiez votre connexion internet.", file=sys.stderr)
            print(f"Détail : {e.reason}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Avertissement : API injoignable ({e.reason}).", file=sys.stderr)
            return None, None


def fetch_model(config: dict) -> str:
    """Fetch the model from cache or API."""
    # Use cached model from login if available
    if config.get("PERSOIA_MODEL"):
        return config["PERSOIA_MODEL"]

    # Fallback: call GET /v1/models
    api_base = config["PERSOIA_API_BASE"]
    api_key = config["PERSOIA_API_KEY"]
    status, body = api_request(f"{api_base}/models", api_key=api_key)

    if status != 200:
        print("Erreur : impossible de récupérer le modèle depuis l'API.", file=sys.stderr)
        print("Vérifiez votre connexion et votre clé API.", file=sys.stderr)
        sys.exit(1)

    if isinstance(body, dict) and "data" in body and body["data"]:
        return body["data"][0].get("id", "unknown")

    print("Erreur : aucun modèle disponible pour votre abonnement.", file=sys.stderr)
    print("Votre instance GPU est peut-être éteinte (hors plage horaire).", file=sys.stderr)
    sys.exit(1)


def require_api_key(config: dict) -> None:
    """Exit if no API key is configured."""
    if not config.get("PERSOIA_API_KEY"):
        print("Erreur : vous n'êtes pas connecté.")
        print()
        print("Connectez-vous avec : persoia login")
        print(f"Ou configurez manuellement : {get_config_path()}")
        sys.exit(1)


def require_aider() -> None:
    """Exit if aider is not installed."""
    if not shutil.which("aider"):
        print("Erreur : aider est requis mais non installé.")
        print()
        if platform.system() == "Windows":
            print('Installer avec : powershell -c "irm https://aider.chat/install.ps1 | iex"')
        elif platform.system() == "Darwin":
            print("Installer avec : brew install aider")
        else:
            print("Installer avec : pip install aider-chat")
        sys.exit(1)


def make_context_file() -> str:
    """Create a temporary context file with current date/time.

    Injected as a read-only file so the model knows the current datetime.
    Returns the path (auto-deleted on process exit).
    """
    now = datetime.now()
    tz = now.astimezone().tzname()
    content = (
        f"# PersoIA Context\n"
        f"Date: {now.strftime('%Y-%m-%d')}\n"
        f"Heure: {now.strftime('%H:%M')}\n"
        f"Fuseau: {tz}\n"
        f"OS: {platform.system()} {platform.machine()}\n"
    )
    fd, path = tempfile.mkstemp(prefix="persoia-ctx-", suffix=".md", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    atexit.register(lambda: os.unlink(path) if os.path.exists(path) else None)
    return path


# --- Project scanning helpers ---

_EXCLUDED_DIRS = frozenset({
    "node_modules", ".git", "dist", "build", "__pycache__", "vendor",
    "target", ".venv", "venv", ".next", ".nuxt", ".quasar", ".astro",
    ".cache", ".output", "coverage",
})

GENERATION_PROMPT = """\
Tu es un assistant technique. Génère un fichier PERSOIA.md concis (100-150 lignes max) pour un projet de développement logiciel.

Ce fichier sera injecté comme contexte dans un assistant de codage IA avec une fenêtre de contexte limitée (8K tokens). Il doit être :
- Concis et factuel (pas de prose inutile)
- En markdown avec des tableaux quand c'est pertinent
- Axé sur ce qu'un développeur a besoin de savoir pour coder sur ce projet

Voici le scan automatique du projet :

{scan_text}

Génère le fichier PERSOIA.md avec ces sections :
1. # NomDuProjet — une ligne de description
2. ## Stack (tableau : composant | technologie | version si connue)
3. ## Structure (arbre des répertoires principaux, commentés)
4. ## Commandes (bloc code bash avec les commandes dev/build/test/lint)
5. ## Conventions (style de code détecté, format de commits si .git)
6. ## Architecture (notes brèves sur l'architecture si détectable)

Règles :
- Ne pas inventer d'information absente du scan
- Si une section manque de données, l'omettre plutôt que deviner
- Garder le fichier sous 150 lignes
- Langue : français pour les titres et descriptions
- Retourne UNIQUEMENT le contenu markdown, sans bloc code englobant"""

REFINEMENT_PROMPT = """\
Voici un fichier PERSOIA.md existant :

{content}

L'utilisateur demande la modification suivante :
"{feedback}"

Modifie le fichier en tenant compte de cette demande. Règles :
- Garde le fichier sous 200 lignes
- Conserve le format markdown existant
- Ne modifie que ce qui est demandé
- Retourne UNIQUEMENT le fichier complet modifié, sans bloc code englobant"""


def _parse_package_json(path: Path) -> dict:
    """Parse package.json and extract project metadata.

    Args:
        path: Path to package.json.

    Returns:
        Dict with name, scripts, dependencies, and devDependencies.
    """
    result: dict = {"name": "", "scripts": {}, "dependencies": [], "devDependencies": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        result["name"] = data.get("name", "")
        result["scripts"] = data.get("scripts", {})
        result["dependencies"] = list(data.get("dependencies", {}).keys())
        result["devDependencies"] = list(data.get("devDependencies", {}).keys())
    except (json.JSONDecodeError, OSError):
        pass
    return result


def _parse_go_mod(path: Path) -> dict:
    """Parse go.mod and extract module info and dependencies.

    Args:
        path: Path to go.mod.

    Returns:
        Dict with module name, go version, and dependency list.
    """
    result: dict = {"module": "", "go_version": "", "dependencies": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        in_require_block = False
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^module\s+(.+)$", line)
            if m:
                result["module"] = m.group(1)
                continue
            m = re.match(r"^go\s+(\S+)$", line)
            if m:
                result["go_version"] = m.group(1)
                continue
            if line == "require (":
                in_require_block = True
                continue
            if in_require_block:
                if line == ")":
                    in_require_block = False
                    continue
                parts = line.split()
                if parts and not parts[0].startswith("//"):
                    result["dependencies"].append(parts[0])
                continue
            m = re.match(r"^require\s+(\S+)", line)
            if m:
                result["dependencies"].append(m.group(1))
    except OSError:
        pass
    return result


def _parse_pyproject_toml(path: Path) -> dict:
    """Parse pyproject.toml with simple regex (no tomllib dependency).

    Args:
        path: Path to pyproject.toml.

    Returns:
        Dict with project name and dependencies list.
    """
    result: dict = {"name": "", "dependencies": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        current_section = ""
        in_deps = False
        for line in text.splitlines():
            stripped = line.strip()
            # Track section headers
            section_match = re.match(r"^\[(.+)\]$", stripped)
            if section_match:
                current_section = section_match.group(1)
                in_deps = False
                continue
            # Extract name from [project] section
            if current_section == "project":
                name_match = re.match(r'^name\s*=\s*"([^"]*)"', stripped)
                if name_match:
                    result["name"] = name_match.group(1)
                if stripped == "dependencies = [":
                    in_deps = True
                    continue
            if in_deps:
                if stripped == "]":
                    in_deps = False
                    continue
                dep_match = re.match(r'^"([^">=<!\[]+)', stripped)
                if dep_match:
                    result["dependencies"].append(dep_match.group(1).strip())
    except OSError:
        pass
    return result


def _parse_readme_description(path: Path) -> str:
    """Extract a short description from README.md.

    Args:
        path: Path to README.md.

    Returns:
        First non-empty, non-heading line (max 200 chars), or empty string.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines()[:20]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:200]
    except OSError:
        pass
    return ""


def _scan_directory_tree(root: Path, max_depth: int = 2) -> list[str]:
    """Return list of directory paths relative to root as indented tree.

    Args:
        root: Root directory to scan.
        max_depth: Maximum depth to recurse (default 2).

    Returns:
        List of indented directory strings, capped at 30 entries.
    """
    entries: list[str] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth or len(entries) >= 30:
            return
        try:
            children = sorted(
                [d for d in current.iterdir() if d.is_dir() and d.name not in _EXCLUDED_DIRS]
            )
        except OSError:
            return
        indent = "  " * depth
        for child in children:
            if len(entries) >= 30:
                return
            entries.append(f"{indent}{child.name}/")
            _walk(child, depth + 1)

    _walk(root, 0)
    return entries


def scan_project(root: Path) -> dict:
    """Scan a project directory and return structured metadata.

    Args:
        root: Path to the project root.

    Returns:
        Dict with project name, languages, frameworks, commands, etc.
    """
    scan: dict = {
        "name": root.name,
        "description": "",
        "languages": [],
        "frameworks": [],
        "package_manager": "",
        "commands": {},
        "directories": [],
        "docker": None,
        "ci": [],
        "code_style": [],
        "git": False,
    }

    # 1. package.json -> Node.js / TypeScript
    pkg_json = root / "package.json"
    if pkg_json.exists():
        pkg = _parse_package_json(pkg_json)
        scan["name"] = pkg["name"] or scan["name"]
        scan["languages"].append("JavaScript")
        scan["package_manager"] = "npm"

        if (root / "tsconfig.json").exists():
            scan["languages"].append("TypeScript")

        all_deps = pkg["dependencies"] + pkg["devDependencies"]
        framework_map = {
            "vue": "Vue", "react": "React", "angular": "Angular",
            "svelte": "Svelte", "astro": "Astro", "next": "Next.js",
            "nuxt": "Nuxt", "quasar": "Quasar", "@quasar/app-vite": "Quasar",
            "express": "Express", "fastify": "Fastify",
            "@nestjs/core": "NestJS", "pinia": "Pinia", "axios": "Axios",
            "tailwindcss": "Tailwind CSS", "vite": "Vite",
            "vitest": "Vitest", "@playwright/test": "Playwright",
        }
        for dep, fw in framework_map.items():
            if dep in all_deps and fw not in scan["frameworks"]:
                scan["frameworks"].append(fw)

        scan["commands"] = {k: v for k, v in pkg.get("scripts", {}).items()}

    # 2. go.mod -> Go
    go_mod = root / "go.mod"
    if go_mod.exists():
        gm = _parse_go_mod(go_mod)
        if "Go" not in scan["languages"]:
            scan["languages"].append("Go")
        scan["name"] = gm["module"].rsplit("/", 1)[-1] if gm["module"] else scan["name"]
        scan["package_manager"] = scan["package_manager"] or "go modules"
        go_fw_map = {
            "gin-gonic/gin": "Gin",
            "labstack/echo": "Echo",
            "gofiber/fiber": "Fiber",
            "go-chi/chi": "Chi",
        }
        for dep in gm["dependencies"]:
            for pattern, fw in go_fw_map.items():
                if pattern in dep and fw not in scan["frameworks"]:
                    scan["frameworks"].append(fw)
        scan["commands"].setdefault("build", "go build ./...")
        scan["commands"].setdefault("test", "go test ./...")
        scan["commands"].setdefault("lint", "golangci-lint run")

    # 3. pyproject.toml -> Python
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        pp = _parse_pyproject_toml(pyproject)
        if "Python" not in scan["languages"]:
            scan["languages"].append("Python")
        scan["name"] = pp["name"] or scan["name"]
        scan["package_manager"] = scan["package_manager"] or "pip"

    # 4. requirements*.txt -> Python
    req_files = list(root.glob("requirements*.txt"))
    if req_files:
        if "Python" not in scan["languages"]:
            scan["languages"].append("Python")
        scan["package_manager"] = scan["package_manager"] or "pip"
        py_fw_map = {
            "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
            "pytorch": "PyTorch", "tensorflow": "TensorFlow",
            "pandas": "Pandas", "numpy": "NumPy",
        }
        for rf in req_files:
            try:
                for line in rf.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip().lower()
                    if not line or line.startswith("#"):
                        continue
                    pkg_name = re.split(r"[>=<!\[;]", line)[0].strip()
                    for pattern, fw in py_fw_map.items():
                        if pattern in pkg_name and fw not in scan["frameworks"]:
                            scan["frameworks"].append(fw)
            except OSError:
                pass

    # 5. Cargo.toml -> Rust
    if (root / "Cargo.toml").exists():
        if "Rust" not in scan["languages"]:
            scan["languages"].append("Rust")
        scan["package_manager"] = scan["package_manager"] or "cargo"

    # 6. pom.xml / build.gradle -> Java
    if (root / "pom.xml").exists():
        if "Java" not in scan["languages"]:
            scan["languages"].append("Java")
        scan["package_manager"] = scan["package_manager"] or "Maven"
    if (root / "build.gradle").exists():
        if "Java" not in scan["languages"]:
            scan["languages"].append("Java")
        scan["package_manager"] = scan["package_manager"] or "Gradle"

    # 7. Gemfile / composer.json
    if (root / "Gemfile").exists():
        if "Ruby" not in scan["languages"]:
            scan["languages"].append("Ruby")
        scan["package_manager"] = scan["package_manager"] or "Bundler"
    if (root / "composer.json").exists():
        if "PHP" not in scan["languages"]:
            scan["languages"].append("PHP")
        scan["package_manager"] = scan["package_manager"] or "Composer"

    # 8. Makefile -> extract targets
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?![=:])", line)
                if m:
                    target = m.group(1)
                    if target.startswith(".") or "%" in target:
                        continue
                    if target not in scan["commands"]:
                        scan["commands"][target] = f"make {target}"
        except OSError:
            pass

    # 9. README.md -> description
    readme = root / "README.md"
    if readme.exists():
        scan["description"] = _parse_readme_description(readme)

    # 10. Directory tree
    scan["directories"] = _scan_directory_tree(root)

    # 11. Dockerfile -> FROM images
    dockerfile = root / "Dockerfile"
    if dockerfile.exists():
        try:
            text = dockerfile.read_text(encoding="utf-8", errors="replace")
            images = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)
            scan["docker"] = {"images": images}
        except OSError:
            pass

    # 12. docker-compose / compose files
    compose_patterns = ["docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml"]
    for pat in compose_patterns:
        if list(root.glob(pat)):
            if scan["docker"] is None:
                scan["docker"] = {}
            scan["docker"]["compose"] = True
            break

    # 13. CI detection
    if (root / "Jenkinsfile").exists():
        scan["ci"].append("Jenkins")
    gh_workflows = root / ".github" / "workflows"
    if gh_workflows.is_dir():
        try:
            yml_files = list(gh_workflows.glob("*.yml")) + list(gh_workflows.glob("*.yaml"))
            if yml_files:
                scan["ci"].append("GitHub Actions")
        except OSError:
            pass

    # 14. Code style
    if (root / "tsconfig.json").exists():
        try:
            ts_text = (root / "tsconfig.json").read_text(encoding="utf-8", errors="replace")
            ts_data = json.loads(ts_text)
            strict = ts_data.get("compilerOptions", {}).get("strict", False)
            scan["code_style"].append(f"TypeScript {'strict' if strict else 'standard'}")
        except (json.JSONDecodeError, OSError):
            scan["code_style"].append("TypeScript")

    for eslint_pat in [".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml"]:
        if (root / eslint_pat).exists():
            scan["code_style"].append("ESLint")
            break

    for prettier_pat in [".prettierrc", ".prettierrc.js", ".prettierrc.json", ".prettierrc.yml", ".prettierrc.yaml"]:
        if (root / prettier_pat).exists():
            scan["code_style"].append("Prettier")
            break

    if (root / ".editorconfig").exists():
        scan["code_style"].append("EditorConfig")

    # 15. Git
    scan["git"] = (root / ".git").exists()

    return scan


def format_scan_for_llm(scan: dict) -> str:
    """Convert scan dict to compact text for the LLM prompt.

    Args:
        scan: Project scan dictionary from scan_project().

    Returns:
        Compact text representation, targeting under 3K chars.
    """
    lines: list[str] = []
    lines.append(f"Projet: {scan['name']}")

    if scan["description"]:
        lines.append(f"Description: {scan['description']}")

    if scan["languages"]:
        lines.append(f"Langages: {', '.join(scan['languages'])}")

    if scan["frameworks"]:
        lines.append(f"Frameworks: {', '.join(scan['frameworks'])}")

    if scan["package_manager"]:
        lines.append(f"Gestionnaire: {scan['package_manager']}")

    if scan["commands"]:
        lines.append("Commandes:")
        for key, value in scan["commands"].items():
            lines.append(f"  {key}: {value}")

    if scan["directories"]:
        lines.append("Structure:")
        for d in scan["directories"]:
            lines.append(f"  {d}")

    if scan["docker"]:
        docker_parts: list[str] = []
        if "images" in scan["docker"]:
            docker_parts.append(f"images: {', '.join(scan['docker']['images'])}")
        if scan["docker"].get("compose"):
            docker_parts.append("docker-compose: oui")
        lines.append(f"Docker: {'; '.join(docker_parts)}" if docker_parts else "Docker: oui")

    if scan["ci"]:
        lines.append(f"CI: {', '.join(scan['ci'])}")

    if scan["code_style"]:
        lines.append(f"Style: {', '.join(scan['code_style'])}")

    lines.append(f"Git: {'oui' if scan['git'] else 'non'}")

    return "\n".join(lines)


def generate_persoia_md(config: dict, scan_text: str) -> str | None:
    """Call the LLM API to generate a PERSOIA.md file.

    Args:
        config: CLI configuration with API credentials.
        scan_text: Compact project scan text.

    Returns:
        Generated markdown content, or None on failure.
    """
    url = f"{config['PERSOIA_API_BASE']}/chat/completions"
    prompt = GENERATION_PROMPT.format(scan_text=scan_text)
    data = {
        "model": "persoia",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.3,
        "stream": False,
    }

    status, body = api_request(
        url, data=data, api_key=config.get("PERSOIA_API_KEY"), fatal=False, timeout=60,
    )

    if status is None:
        return None
    if not isinstance(body, dict):
        return None

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    # Strip surrounding code fences if present
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.index("\n") if "\n" in content else len(content)
        content = content[first_newline + 1:]
    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def refine_persoia_md(config: dict, content: str, feedback: str) -> str | None:
    """Call the LLM API to refine an existing PERSOIA.md.

    Args:
        config: CLI configuration with API credentials.
        content: Current PERSOIA.md content.
        feedback: User's modification request.

    Returns:
        Refined markdown content, or None on failure.
    """
    url = f"{config['PERSOIA_API_BASE']}/chat/completions"
    prompt = REFINEMENT_PROMPT.format(content=content, feedback=feedback)
    data = {
        "model": "persoia",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.3,
        "stream": False,
    }

    status, body = api_request(
        url, data=data, api_key=config.get("PERSOIA_API_KEY"), fatal=False, timeout=60,
    )

    if status is None:
        return None
    if not isinstance(body, dict):
        return None

    try:
        refined = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    # Strip surrounding code fences if present
    refined = refined.strip()
    if refined.startswith("```"):
        first_newline = refined.index("\n") if "\n" in refined else len(refined)
        refined = refined[first_newline + 1:]
    if refined.endswith("```"):
        refined = refined[:-3]

    return refined.strip()


def _make_raw_template(scan: dict) -> str:
    """Generate a basic PERSOIA.md when the LLM is unavailable.

    Args:
        scan: Project scan dictionary from scan_project().

    Returns:
        Markdown string with project metadata.
    """
    lines: list[str] = []
    lines.append(f"# {scan['name']}")
    lines.append("")

    if scan["description"]:
        lines.append(scan["description"])
        lines.append("")

    # Stack table
    if scan["languages"] or scan["frameworks"]:
        lines.append("## Stack")
        lines.append("")
        lines.append("| Composant | Technologie |")
        lines.append("|-----------|-------------|")
        for lang in scan["languages"]:
            lines.append(f"| Langage | {lang} |")
        for fw in scan["frameworks"]:
            lines.append(f"| Framework | {fw} |")
        if scan["package_manager"]:
            lines.append(f"| Gestionnaire | {scan['package_manager']} |")
        lines.append("")

    # Directory tree
    if scan["directories"]:
        lines.append("## Structure")
        lines.append("")
        lines.append("```")
        for d in scan["directories"]:
            lines.append(d)
        lines.append("```")
        lines.append("")

    # Commands
    if scan["commands"]:
        lines.append("## Commandes")
        lines.append("")
        lines.append("```bash")
        for key, value in scan["commands"].items():
            lines.append(f"{value}  # {key}")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


# --- Commands ---

def _open_cli_page(config: dict) -> None:
    """Open the CLI settings page in the browser as fallback."""
    api_base = config.get("PERSOIA_API_BASE", "https://api.persoia.com/v1")
    # Derive the portal URL from the API base
    portal_url = api_base.replace("/v1", "").replace("/api", "")
    cli_url = f"{portal_url}/cli"
    print()
    print(f"Ouverture de {cli_url} dans votre navigateur...")
    print("Créez une clé API depuis le portail, puis configurez-la avec :")
    print()
    print("  persoia config")
    print()
    webbrowser.open(cli_url)


def cmd_login(args: list[str]) -> None:
    """Authenticate via API, or open the browser as fallback."""
    email = ""
    password = ""

    # Parse flags
    i = 0
    while i < len(args):
        if args[i] == "--email" and i + 1 < len(args):
            email = args[i + 1]
            i += 2
        elif args[i] == "--password" and i + 1 < len(args):
            password = args[i + 1]
            i += 2
        else:
            print(f"Option inconnue pour login : {args[i]}", file=sys.stderr)
            sys.exit(1)

    config = load_config()

    # Interactive prompts
    if not email:
        try:
            email = input("Email : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _open_cli_page(config)
            return
    if not email:
        _open_cli_page(config)
        return

    if not password:
        try:
            password = getpass("Mot de passe : ")
        except (EOFError, KeyboardInterrupt):
            print()
            _open_cli_page(config)
            return
    if not password:
        _open_cli_page(config)
        return

    api_base = config["PERSOIA_API_BASE"]
    login_url = api_base.replace("/v1", "/api/v1/cli/api-keys/login")

    hostname = socket.gethostname()
    key_name = f"CLI - {hostname} - {datetime.now().strftime('%Y-%m-%d')}"

    # Try API login, fallback to browser on network error
    try:
        body = json.dumps({
            "email": email,
            "password": password,
            "key_name": key_name,
        }).encode("utf-8")
        req = urllib.request.Request(
            login_url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            status = resp.status
            body_json = json.loads(content)
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace")
        status = e.code
        try:
            body_json = json.loads(content)
        except json.JSONDecodeError:
            body_json = content
    except (urllib.error.URLError, OSError):
        print("L'API de login n'est pas disponible.", file=sys.stderr)
        _open_cli_page(config)
        return

    if status == 401:
        print("Erreur : identifiants incorrects.", file=sys.stderr)
        print("Vérifiez votre email et mot de passe.", file=sys.stderr)
        sys.exit(1)
    elif status == 403:
        print("Erreur : accès refusé.", file=sys.stderr)
        print("Votre compte n'a peut-être pas les droits CLI, ou il est désactivé.", file=sys.stderr)
        sys.exit(1)
    elif status not in (200, 201):
        print(f"Login API indisponible (code {status}).", file=sys.stderr)
        _open_cli_page(config)
        return

    if not isinstance(body_json, dict):
        print("Réponse inattendue, ouverture du portail...", file=sys.stderr)
        _open_cli_page(config)
        return

    # Unwrap {"success": true, "data": {...}} envelope if present
    if "data" in body_json and isinstance(body_json["data"], dict):
        body_json = body_json["data"]

    api_key = body_json.get("api_key", body_json.get("key", ""))
    if not api_key:
        print("Clé API absente de la réponse, ouverture du portail...", file=sys.stderr)
        _open_cli_page(config)
        return

    # Extract optional config
    tenant_name = body_json.get("tenant_name", body_json.get("tenant", ""))
    model = body_json.get("model", "")
    config_data = body_json.get("config", {})
    api_base_from_api = ""
    if isinstance(config_data, dict):
        model = model or config_data.get("model", "")
        tenant_name = tenant_name or config_data.get("tenant_name", "")
        raw_api_base = config_data.get("api_base", "").strip()
        # Validate URL before trusting the API response
        if raw_api_base.startswith("https://") and ".persoia.com" in raw_api_base:
            api_base_from_api = raw_api_base

    # Save config — prefer api_base from API response (knows the correct environment URL)
    save_values = {
        "PERSOIA_API_KEY": api_key,
        "PERSOIA_API_BASE": api_base_from_api or config["PERSOIA_API_BASE"],
    }
    if tenant_name:
        save_values["PERSOIA_TENANT_NAME"] = tenant_name
    if model:
        save_values["PERSOIA_MODEL"] = model

    save_config(save_values)

    print()
    print("Connexion réussie !")
    if tenant_name:
        print(f"  Entreprise : {tenant_name}")
    if model:
        print(f"  Modèle     : {model}")
    print()
    print(f"Configuration sauvegardée dans : {get_config_path()}")
    print("Lancez 'persoia code' pour commencer.")


def cmd_logout() -> None:
    """Delete local configuration."""
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
        print("Déconnexion effectuée.")
        print(f"Le fichier {config_path} a été supprimé.")
    else:
        print(f"Aucune session active (fichier {config_path} introuvable).")


def cmd_config(config: dict) -> None:
    """Display current configuration."""
    print("PersoIA CLI Configuration")
    print("=========================")
    print(f"Fichier config: {get_config_path()}")

    if not config.get("PERSOIA_API_KEY"):
        print("Statut:         Non connecté")
        print()
        print("Connectez-vous avec : persoia login")
        return

    print(f"API:            {config['PERSOIA_API_BASE']}")
    api_key = config["PERSOIA_API_KEY"]
    print(f"Clé API:        {api_key[:12]}...")

    if config.get("PERSOIA_TENANT_NAME"):
        print(f"Entreprise:     {config['PERSOIA_TENANT_NAME']}")

    # Show model
    if config.get("PERSOIA_MODEL"):
        print(f"Modèle:         {config['PERSOIA_MODEL']} (cache local)")
    else:
        try:
            model = fetch_model(config)
            print(f"Modèle:         {model} (via API)")
        except SystemExit:
            print("Modèle:         non disponible (vérifiez votre connexion)")

    print()
    md_files = collect_persoia_md_files()
    if md_files:
        print(f"PERSOIA.md:     {len(md_files)} fichier(s) chargé(s)")
        for f in md_files:
            try:
                line_count = len(f.read_text(encoding="utf-8").splitlines())
                print(f"  ↳ {f} ({line_count} lignes)")
            except OSError:
                print(f"  ↳ {f} (illisible)")
    else:
        print("PERSOIA.md:     Aucun fichier trouvé dans l'arborescence")


def cmd_init() -> None:
    """Generate a PERSOIA.md project context file."""
    config = load_config()
    root = Path.cwd()

    # Reset terminal — aider or other tools may leave CR/LF translation broken
    if sys.stdin.isatty() and platform.system() != "Windows":
        subprocess.run(["stty", "sane"], check=False, stderr=subprocess.DEVNULL)

    # Check if PERSOIA.md already exists
    persoia_md = root / "PERSOIA.md"
    if persoia_md.exists():
        line_count = len(persoia_md.read_text(encoding="utf-8").splitlines())
        print(f"PERSOIA.md existe déjà ({line_count} lignes).")
        try:
            sys.stdout.flush()
            answer = input("Voulez-vous le remplacer ? (O/N) : ")
            answer = answer.strip().strip("\r").lower()
        except (EOFError, KeyboardInterrupt):
            print("\nOpération annulée.")
            return
        if answer not in ("o", "oui", "y", "yes"):
            print("Opération annulée.")
            return

    # Phase 1: Local scan
    print("Analyse du projet...")
    scan = scan_project(root)
    scan_text = format_scan_for_llm(scan)

    print(f"Projet : {scan['name']}")
    if scan["languages"]:
        print(f"  Langages : {', '.join(scan['languages'])}")
    if scan["frameworks"]:
        print(f"  Frameworks : {', '.join(scan['frameworks'])}")
    print()

    # Phase 2: LLM generation
    content = None
    if config.get("PERSOIA_API_KEY"):
        print("Génération via l'IA...")
        content = generate_persoia_md(config, scan_text)

    if content is None:
        if not config.get("PERSOIA_API_KEY"):
            print("Pas de clé API. Utilisation du modèle hors-ligne.")
            print("Connectez-vous avec 'persoia login' pour la génération IA.")
        else:
            print("API indisponible. Utilisation du modèle hors-ligne.")
        content = _make_raw_template(scan)
        print()

    # Phase 3: Interactive refinement
    while True:
        print("=" * 60)
        print(content)
        print("=" * 60)
        print()

        try:
            sys.stdout.flush()
            answer = input("(S)auvegarder / (M)odifier / (A)nnuler : ")
            answer = answer.strip().strip("\r").lower()
        except (EOFError, KeyboardInterrupt):
            print("\nOpération annulée.")
            return

        if answer in ("a", "annuler", "q", "quit"):
            print("Aucun fichier créé.")
            return
        elif answer in ("s", "sauvegarder", "save", ""):
            break
        elif answer in ("m", "modifier", "edit"):
            if not config.get("PERSOIA_API_KEY"):
                print("La modification nécessite une connexion (persoia login).")
                continue
            try:
                sys.stdout.flush()
                feedback = input("Modification souhaitée : ")
                feedback = feedback.strip().strip("\r")
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            if not feedback:
                continue
            print("Modification en cours...")
            refined = refine_persoia_md(config, content, feedback)
            if refined:
                content = refined
            else:
                print("Erreur. Le contenu précédent est conservé.")

    # Save
    persoia_md.write_text(content + "\n", encoding="utf-8")
    line_count = len(content.splitlines())
    print()
    print(f"PERSOIA.md créé ({line_count} lignes).")
    print("Ce fichier sera automatiquement injecté dans 'persoia code'.")


def cmd_code(config: dict, extra_args: list[str]) -> None:
    """Launch aider with PersoIA infrastructure."""
    require_api_key(config)
    require_aider()

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = config["PERSOIA_API_KEY"]

    # Use "persoia" as model name — the API resolves the actual model
    # from the tenant's subscription. This avoids exposing internal
    # model paths and suppresses aider's "unknown model" warning.
    ctx_file = make_context_file()
    cmd = [
        "aider",
        "--model", "openai/persoia",
        "--openai-api-base", config["PERSOIA_API_BASE"],
        "--no-show-model-warnings",
        "--no-git",
        "--read", ctx_file,
    ]

    # Inject PERSOIA.md files from parent dirs to current (generic → specific)
    for md_file in collect_persoia_md_files():
        cmd.extend(["--read", str(md_file)])

    cmd.extend(extra_args)

    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def cmd_chat(config: dict, message: str) -> None:
    """One-shot chat question."""
    require_api_key(config)
    require_aider()

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = config["PERSOIA_API_KEY"]

    ctx_file = make_context_file()
    cmd = [
        "aider",
        "--model", "openai/persoia",
        "--openai-api-base", config["PERSOIA_API_BASE"],
        "--message", message,
        "--no-auto-commits",
        "--no-show-model-warnings",
        "--read", ctx_file,
    ]

    # Inject PERSOIA.md files from parent dirs to current (generic → specific)
    for md_file in collect_persoia_md_files():
        cmd.extend(["--read", str(md_file)])

    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def cmd_version() -> None:
    """Display version information."""
    print(f"persoia {__version__}")


def cmd_help() -> None:
    """Display help text."""
    print("""PersoIA CLI — Assistant code souverain

Usage:
  persoia login                    Connexion avec email et mot de passe
  persoia logout                   Déconnexion (supprime la clé API locale)
  persoia init                     Génère un fichier PERSOIA.md pour le projet
  persoia code [AIDER_ARGS...]     Lance aider avec l'infrastructure PersoIA
  persoia chat "message"           Mode chat rapide (une question)
  persoia config                   Affiche la configuration active
  persoia version (--version, -V)  Affiche la version du CLI
  persoia help (--help, -h)        Affiche cette aide

Le modèle IA est déterminé automatiquement par votre abonnement PersoIA.
Toutes les requêtes transitent par api.persoia.com (auth, audit, facturation).

Exemples:
  persoia login                           # Connexion interactive
  persoia login --email user@example.com  # Email en paramètre
  persoia init                            # Génère PERSOIA.md pour le projet
  persoia code                            # Lance aider
  persoia chat "Explique ce Dockerfile"   # Question rapide
  persoia config                          # Vérifie la configuration
  persoia logout                          # Déconnexion

Configuration:
  Fichier: """ + str(get_config_path()) + """
  Créé automatiquement par 'persoia login'.
""")


def main() -> None:
    """Entry point."""
    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]
    config = load_config()

    if command == "login":
        cmd_login(args)
    elif command == "logout":
        cmd_logout()
    elif command == "init":
        cmd_init()
    elif command == "code":
        cmd_code(config, args)
    elif command == "chat":
        if not args:
            print("Erreur : persoia chat nécessite un message")
            print('Usage : persoia chat "votre question"')
            sys.exit(1)
        cmd_chat(config, " ".join(args))
    elif command == "config":
        cmd_config(config)
    elif command in ("version", "--version", "-V"):
        cmd_version()
    elif command in ("help", "--help", "-h"):
        cmd_help()
    else:
        print(f"Commande inconnue : {command}")
        print("Lancez 'persoia help' pour l'aide")
        sys.exit(1)


if __name__ == "__main__":
    main()
