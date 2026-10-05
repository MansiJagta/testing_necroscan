from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java",
    ".yaml", ".yml", ".json"
}

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", "dist", "build",
    ".next", "target"
}


def _run_git_clone(repo_url: str, destination: str) -> None:
    if not re.match(r"^https://github\.com/[^/\s]+/[^/\s]+(?:\.git)?/?$", repo_url.strip()):
        raise ValueError(
            "Only public GitHub HTTPS repository URLs are supported, "
            "for example: https://github.com/owner/repository"
        )

    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, destination],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git clone failed")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _normalize_path(path: str) -> str:
    path = re.sub(r"\s+", "", path)
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/+", "/", path)
    return path


def _add_api(results: list[dict[str, Any]], method: str, path: str,
             framework: str, source_file: str, line_number: int,
             evidence: str) -> None:
    path = _normalize_path(path)
    if path in {"//", "/"} and path != "/":
        return

    results.append({
        "method": method.upper(),
        "path": path,
        "framework": framework,
        "source_file": source_file,
        "line_number": line_number,
        "evidence": evidence,
    })


def _scan_python(text: str, rel: str, results: list[dict[str, Any]]) -> None:
    lines = text.splitlines()

    # FastAPI decorators:
    # @app.get("/users"), @router.post("/users/{id}")
    fastapi = re.compile(
        r'@\s*(?:app|router|api|[A-Za-z_]\w*)\s*\.\s*'
        r'(get|post|put|patch|delete|options|head)\s*\(\s*["\']([^"\']+)["\']'
    )

    # Flask:
    # @app.route("/users", methods=["GET", "POST"])
    flask_route = re.compile(
        r'@\s*(?:app|blueprint|bp|[A-Za-z_]\w*)\s*\.\s*route'
        r'\s*\(\s*["\']([^"\']+)["\']([^)]*)\)'
    )

    # Django path()/re_path():
    django_path = re.compile(
        r'\b(?:path|re_path)\s*\(\s*["\']([^"\']+)["\']'
    )

    for i, line in enumerate(lines, 1):
        m = fastapi.search(line)
        if m:
            _add_api(results, m.group(1), m.group(2), "FastAPI",
                     rel, i, "Python decorator")

        m = flask_route.search(line)
        if m:
            path, options = m.group(1), m.group(2)
            methods = re.findall(
                r'["\'](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)["\']',
                options, re.I
            )
            methods = [m.upper() for m in methods] or ["GET"]
            for method in methods:
                _add_api(results, method, path, "Flask",
                         rel, i, "Flask route decorator")

        m = django_path.search(line)
        if m:
            # Django URL patterns don't necessarily expose the HTTP method.
            _add_api(results, "ANY", "/" + m.group(1).lstrip("/"),
                     "Django", rel, i, "Django URL pattern")


def _scan_javascript(text: str, rel: str, results: list[dict[str, Any]]) -> None:
    lines = text.splitlines()

    # Express: app.get("/users"), router.post("/users")
    express = re.compile(
        r'\b(?:app|router|route|server)\s*\.\s*'
        r'(get|post|put|patch|delete|options|head|all)\s*'
        r'\(\s*[`"\']([^`"\']+)[`"\']'
    )

    # Express app.use("/prefix", ...)
    use_prefix = re.compile(
        r'\b(?:app|router)\s*\.\s*use\s*\(\s*[`"\']([^`"\']+)[`"\']'
    )

    for i, line in enumerate(lines, 1):
        m = express.search(line)
        if m:
            method = m.group(1).upper()
            if method == "ALL":
                method = "ANY"
            _add_api(results, method, m.group(2), "Express.js",
                     rel, i, "Express route")

        m = use_prefix.search(line)
        if m:
            _add_api(results, "ANY", m.group(1), "Express.js",
                     rel, i, "Express middleware prefix")


def _scan_java(text: str, rel: str, results: list[dict[str, Any]]) -> None:
    lines = text.splitlines()

    mappings = [
        ("GET", re.compile(r'@GetMapping\s*\(\s*["\']([^"\']+)["\']')),
        ("POST", re.compile(r'@PostMapping\s*\(\s*["\']([^"\']+)["\']')),
        ("PUT", re.compile(r'@PutMapping\s*\(\s*["\']([^"\']+)["\']')),
        ("PATCH", re.compile(r'@PatchMapping\s*\(\s*["\']([^"\']+)["\']')),
        ("DELETE", re.compile(r'@DeleteMapping\s*\(\s*["\']([^"\']+)["\']')),
        ("ANY", re.compile(r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']')),
    ]

    for i, line in enumerate(lines, 1):
        for method, pattern in mappings:
            m = pattern.search(line)
            if m:
                _add_api(results, method, m.group(1), "Spring Boot",
                         rel, i, "Spring mapping annotation")


def _extract_openapi_file(path: Path, rel: str) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(_read_text(path))
        else:
            # Avoid requiring PyYAML unless the user wants YAML parsing.
            try:
                import yaml
                data = yaml.safe_load(_read_text(path))
            except ImportError:
                return []
    except Exception:
        return []

    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        return []

    results = []
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

    for api_path, item in data["paths"].items():
        if not isinstance(item, dict):
            continue
        for method in methods:
            if method in item:
                results.append({
                    "method": method.upper(),
                    "path": _normalize_path(str(api_path)),
                    "framework": "OpenAPI",
                    "source_file": rel,
                    "line_number": None,
                    "evidence": "OpenAPI/Swagger document",
                })
    return results


def _detect_framework(root: Path) -> list[str]:
    found = set()

    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue

        name = path.name.lower()
        text = _read_text(path)

        if name in {"requirements.txt", "pyproject.toml", "poetry.lock"}:
            if re.search(r"\bfastapi\b", text, re.I):
                found.add("FastAPI")
            if re.search(r"\bflask\b", text, re.I):
                found.add("Flask")
            if re.search(r"\bdjango\b", text, re.I):
                found.add("Django")

        if name == "package.json":
            if re.search(r'"express"\s*:', text, re.I):
                found.add("Express.js")

        if name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            if re.search(r"spring-boot|spring-web", text, re.I):
                found.add("Spring Boot")

    return sorted(found)


def scan_repository(repo_url: str) -> dict[str, Any]:
    temp_root = tempfile.mkdtemp(prefix="necroscan_")
    repo_dir = os.path.join(temp_root, "repo")

    try:
        _run_git_clone(repo_url, repo_dir)

        root = Path(repo_dir)
        frameworks = _detect_framework(root)
        source_apis: list[dict[str, Any]] = []
        documented_apis: list[dict[str, Any]] = []

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            rel = str(path.relative_to(root)).replace("\\", "/")
            text = _read_text(path)

            if path.suffix.lower() == ".py":
                _scan_python(text, rel, source_apis)
            elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
                _scan_javascript(text, rel, source_apis)
            elif path.suffix.lower() == ".java":
                _scan_java(text, rel, source_apis)

            if path.name.lower() in {
                "openapi.json", "swagger.json",
                "openapi.yaml", "openapi.yml",
                "swagger.yaml", "swagger.yml"
            }:
                documented_apis.extend(_extract_openapi_file(path, rel))

        def unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen = set()
            output = []
            for item in items:
                key = (
                    item["method"],
                    item["path"],
                    item.get("source_file")
                )
                if key not in seen:
                    seen.add(key)
                    output.append(item)
            return output

        source_apis = unique(source_apis)
        documented_apis = unique(documented_apis)

        # Reconcile source-code APIs with documentation.
        documented_keys = {
            (a["method"], a["path"])
            for a in documented_apis
        }

        inventory = []
        for api in source_apis:
            key = (api["method"], api["path"])
            inventory.append({
                **api,
                "documented": key in documented_keys,
                "runtime_data_available": False,
                "usage_status": "UNKNOWN",
                "classification": "UNCLASSIFIED",
            })

        # Include documented APIs that weren't found in source code.
        source_keys = {
            (a["method"], a["path"])
            for a in source_apis
        }
        for api in documented_apis:
            key = (api["method"], api["path"])
            if key not in source_keys:
                inventory.append({
                    **api,
                    "documented": True,
                    "runtime_data_available": False,
                    "usage_status": "UNKNOWN",
                    "classification": "DOCUMENTED_ONLY",
                })

        return {
            "repository_url": repo_url,
            "frameworks": frameworks,
            "source_api_count": len(source_apis),
            "documented_api_count": len(documented_apis),
            "total_inventory": len(inventory),
            "runtime_data_available": False,
            "apis": inventory,
        }

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
