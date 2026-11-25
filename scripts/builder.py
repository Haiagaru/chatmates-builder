#!/usr/bin/env python3
"""Reproducible Haiagaru APK builds using only the Python standard library."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "chatmates.json").read_text(encoding="utf-8"))
REPO = os.environ.get("GITHUB_REPOSITORY", "Haiagaru/chatmates-builder")
API = "https://api.github.com"
WORK = ROOT / ".work"
OUT = ROOT / "out"
LOGS = ROOT / "logs"
ISSUE_WATCH = json.loads((ROOT / "issue-watch.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request(url: str):
    headers = {"User-Agent": "ChatMates-Builder", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    # Credentials are sent only to the GitHub API, never to asset redirects.
    if token and url.startswith(API + "/"):
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("Download retry limit reached")


def api(path: str):
    with request(API + path) as response:
        return json.load(response)


def releases(repository: str):
    page = 1
    while True:
        items = api(f"/repos/{repository}/releases?per_page=100&page={page}")
        yield from items
        if len(items) < 100:
            return
        page += 1


def api_pages(path: str):
    separator = "&" if "?" in path else "?"
    page = 1
    while True:
        items = api(f"{path}{separator}per_page=100&page={page}")
        yield from items
        if len(items) < 100:
            return
        page += 1


def issue_requests() -> list[dict]:
    """Accept only a literal command, never instructions/code from issue content."""
    repository = ISSUE_WATCH["repository"]
    since = ISSUE_WATCH["since"]
    query = urllib.parse.urlencode({"since": since, "sort": "updated", "direction": "asc"})
    command = ISSUE_WATCH["command"]
    issues = {}
    requests = []

    def add(kind: str, item: dict, url: str):
        key = hashlib.sha256(f"{repository}:{kind}:{item['id']}".encode()).hexdigest()[:16]
        requests.append({"key": key, "url": url, "updated_at": item["updated_at"]})

    for issue in api_pages(f"/repos/{repository}/issues?state=all&{query}"):
        issues[issue["number"]] = issue
        if issue.get("pull_request") or issue["updated_at"] < since:
            continue
        if any((issue.get(field) or "").strip() == command for field in ("title", "body")):
            add("issue", issue, f"https://github.com/{repository}/issues/{issue['number']}")
    for comment in api_pages(f"/repos/{repository}/issues/comments?{query}"):
        if comment["updated_at"] < since or (comment.get("body") or "").strip() != command:
            continue
        issue_number = int(comment["issue_url"].rsplit("/", 1)[1])
        issue = issues.get(issue_number)
        if issue is None:
            issue = api(f"/repos/{repository}/issues/{issue_number}")
            issues[issue_number] = issue
        if issue.get("pull_request"):
            continue
        add("comment", comment,
            f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{comment['id']}")
    return sorted(requests, key=lambda item: (item["updated_at"], item["key"]))


def download(url: str, path: Path, expected: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or (expected and sha256(path) != expected):
        temporary = path.with_suffix(path.suffix + ".part")
        with request(url) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        if expected and sha256(temporary) != expected:
            temporary.unlink()
            raise RuntimeError(f"SHA-256 mismatch: {path.name}")
        temporary.replace(path)
    return path


def asset_digest(asset: dict) -> str | None:
    digest = asset.get("digest") or ""
    return digest.removeprefix("sha256:") if digest.startswith("sha256:") else None


def bundle_asset(release: dict) -> dict:
    assets = [asset for asset in release["assets"] if asset["name"].endswith(".mpp")]
    if len(assets) != 1:
        raise RuntimeError(f"Expected one Android MPP in {release['tag_name']}, found {len(assets)}")
    return assets[0]


def release_plan(release: dict, force_suffix: str = "") -> dict:
    asset = {key: bundle_asset(release).get(key) for key in
             ("id", "name", "size", "updated_at", "digest", "browser_download_url")}
    channel = "prerelease" if release["prerelease"] else "stable"
    identity = {"config": CONFIG, "id": release["id"], "channel": channel,
                "asset": {key: asset.get(key) for key in ("id", "size", "updated_at", "digest")}}
    libraries = select_library_assets(release)
    if libraries:
        identity["library_policy"] = 2
        identity["libraries"] = libraries
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12]
    tag = re.sub(r"[^A-Za-z0-9._-]", "-", release["tag_name"])
    return {"key": f"{release['id']}-{channel}-{key}{force_suffix}",
            "tag": f"haiagaru-{tag}-{channel}-{key}{force_suffix}",
            "upstream_tag": release["tag_name"], "upstream_id": release["id"],
            "upstream_url": release["html_url"], "channel": channel,
            "published_at": release["published_at"], "asset": asset, "libraries": libraries}


def select_library_assets(release: dict) -> dict:
    assets = {item["name"]: item for item in release["assets"]}
    combined = "haiagaru-image-moderation-vpn.zip"
    moderation = "haiagaru-image-moderation.zip"
    model = "haiagaru-image-moderation-model.zip"
    runtime = "haiagaru-image-moderation-runtime.zip"
    vpn = "haiagaru-image-vpn-v2.zip"
    if combined in assets:
        selected = {"imageModerationFile": combined, "imageVpnLibraryFile": combined}
    elif moderation in assets or model in assets or runtime in assets:
        # Do not silently ship a reduced build while release assets are uploading.
        selected = ({"imageModerationFile": moderation} if moderation in assets else
                    {"imageModerationModelFile": model, "imageModerationRuntimeFile": runtime})
        selected["imageVpnLibraryFile"] = vpn
        missing = set(selected.values()) - assets.keys()
        if missing:
            raise RuntimeError(f"{release['tag_name']}: library assets are incomplete: {sorted(missing)}")
    else:
        raise RuntimeError(f"{release['tag_name']}: required library assets are unavailable")
    if "imageNgLibraryFile" not in selected:
        selected["imageNgLibraryFile"] = "haiagaru-image-ng.zip"
    missing = set(selected.values()) - assets.keys()
    if missing:
        raise RuntimeError(f"{release['tag_name']}: library assets are incomplete: {sorted(missing)}")
    return {option: {key: assets[name].get(key) for key in
                    ("name", "id", "size", "updated_at", "digest", "browser_download_url")}
            for option, name in selected.items()}


LIBRARY_PATCHES = {
    "moderation": "成人向け・グロ画像の自動検出",
    "vpn": "画像取得専用VPN（追加用・有効切替）",
}


def build_variants(plan: dict) -> list[dict]:
    if not plan.get("libraries"):
        raise RuntimeError("All-library variants require matching upstream assets")
    return [{"id": "all-enabled", "shizuku": True, "mega": True,
             "image_detection": True, "image_vpn": True, "video_viewer": True}]


def variant_table(plan: dict) -> str:
    table = "| Variant | Shizuku | MEGA | Image detection | Image VPN | Dedicated video viewer | Crash logs |\n|---|---|---|---|---|---|---|\n"
    for variant in build_variants(plan):
        values = ["ON" if variant[key] else "OFF" for key in ("shizuku", "mega", "image_detection", "image_vpn", "video_viewer")]
        table += f"| {variant['id']} | {' | '.join(values)} | ON |\n"
    return table + "\n"


def prepare_libraries(apk_id: str):
    plan = get_plan()
    options = {}
    manifest = []
    seen = {}
    for option, asset in plan.get("libraries", {}).items():
        if option == "imageNgLibraryFile" and apk_id != "191":
            continue
        expected = asset_digest(asset)
        if not expected:
            raise RuntimeError(f"Library asset has no SHA-256 digest: {asset['name']}")
        path = download(asset["browser_download_url"], WORK / "libraries" / plan["key"] / asset["name"], expected)
        options[option] = str(path)
        if asset["name"] not in seen:
            manifest.append({"name": asset["name"], "sha256": sha256(path),
                             "url": asset["browser_download_url"]})
            seen[asset["name"]] = path
    state = {"release_key": plan["key"], "options": options, "assets": manifest}
    WORK.mkdir(exist_ok=True)
    (WORK / f"libraries-{apk_id}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"Prepared {len(manifest)} verified library ZIP(s) for ChMate {apk_id}")


def output(name: str, value):
    rendered = json.dumps(value, separators=(",", ":")) if not isinstance(value, str) else value
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as target:
            target.write(f"{name}={rendered}\n")
    else:
        print(f"{name}={rendered}")


def discover(channel: str):
    upstream = []
    # Always seed the latest official bundle. Afterwards include every release
    # published since setup, including multiple releases between scheduled runs.
    stable = None
    for release in releases(CONFIG["upstream"]):
        if release["draft"]:
            continue
        if not release["prerelease"] and (stable is None or release["published_at"] > stable["published_at"]):
            stable = release
        if release["published_at"] >= CONFIG["monitor_since"]:
            upstream.append(release)
        elif stable is not None:
            # GitHub orders releases by creation, not strictly publication time.
            # Do not break early: old drafts can be published later.
            continue
    if stable and stable["id"] not in {item["id"] for item in upstream}:
        upstream.append(stable)
    published = {release["tag_name"] for release in releases(REPO) if not release["draft"]}
    # An issue-request rebuild also satisfies the normal release build.
    completed_bundles = {re.sub(r"-issue-[0-9a-f]{16}$", "", tag) for tag in published}
    force = os.environ.get("FORCE", "false").lower() == "true"
    suffix = "-run" + os.environ.get("GITHUB_RUN_ID", str(int(time.time()))) if force else ""
    plans = []
    newest = max((item["published_at"] for item in upstream), default="")
    for release in sorted(upstream, key=lambda item: item["published_at"]):
        kind = "prerelease" if release["prerelease"] else "stable"
        if channel not in ("all", kind):
            continue
        if not any(asset["name"].endswith(".mpp") for asset in release["assets"]):
            continue  # A release may be visible before its bundle upload completes.
        plan = release_plan(release, suffix)
        # Configuration upgrades rebuild the newest bundle. Preserve historical
        # releases instead of recreating every old version under the new policy.
        version_prefix = f"haiagaru-{re.sub(r'[^A-Za-z0-9._-]', '-', release['tag_name'])}-{kind}-"
        if (not force and release["published_at"] < newest
                and any(tag.startswith(version_prefix) for tag in published)):
            continue
        if force or plan["tag"] not in completed_bundles:
            plans.append(plan)
    candidates = [release for release in upstream
                  if channel in ("all", "prerelease" if release["prerelease"] else "stable")
                  and any(asset["name"].endswith(".mpp") for asset in release["assets"])]
    if candidates:
        latest = max(candidates, key=lambda item: item["published_at"])
        for request in issue_requests():
            suffix = "-issue-" + request["key"]
            if any(tag.endswith(suffix) for tag in published):
                continue
            plan = release_plan(latest, suffix)
            plan["issue_request"] = request
            # Avoid building the identical bundle twice on first detection.
            base_tag = release_plan(latest)["tag"]
            plans = [item for item in plans if item["tag"] != base_tag]
            plans.append(plan)
            print(f"Accepted update request: {request['url']} -> Haiagaru {latest['tag_name']}")
    builds = [{"release": plan, "apk_id": apk["id"]} for plan in plans for apk in CONFIG["apks"]]
    if len(builds) > 256:
        raise RuntimeError("Too many pending releases for one Actions matrix; run smaller channels first")
    output("has_updates", "true" if plans else "false")
    output("build_matrix", {"include": builds})
    output("release_matrix", {"include": [{"release": plan} for plan in plans]})
    print(f"Pending releases: {len(plans)}; ChMate build jobs: {len(builds)}")


def selected_patches(variant: dict, libraries: dict | None = None) -> list[str]:
    patches = list(CONFIG["patches"]["base"])
    for name in ("shizuku", "mega", "video_viewer"):
        if variant[name]:
            patches.append(CONFIG["patches"][name])
    if libraries:
        patches.extend(LIBRARY_PATCHES.values())
    return patches


def bundle_patch_names(cli: Path, bundle: Path) -> set[str]:
    result = subprocess.check_output([
        "java", "-Dfile.encoding=UTF-8", "-jar", str(cli), "list-patches",
        "--patches", str(bundle)
    ], text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    return {line.removeprefix("Name: ").strip() for line in result.splitlines()
            if line.startswith("Name: ")}


def version_at_least(tag: str, minimum: str) -> bool:
    def version(value: str) -> tuple[int, ...]:
        match = re.match(r"^v?(\d+(?:\.\d+){0,2})", value)
        if not match:
            raise RuntimeError(f"Cannot parse upstream version: {value}")
        return tuple(int(part) for part in match.group(1).split("."))
    return version(tag) >= version(minimum)


def patch_command(cli: Path, bundle: Path, source: Path, target: Path,
                  key: Path, variant: dict, password: str, libraries: dict | None = None,
                  crash_log_patch: bool = False) -> list[str]:
    command = ["java", "-Xmx4g", "-jar", str(cli), "patch", str(source),
               "-p", str(bundle), "--exclusive", "-e", "Haiagaru"]
    if libraries and "imageNgLibraryFile" in libraries:
        command += [f"-OimageNgLibraryFile={libraries['imageNgLibraryFile']}", "-OimageNgTfliteFix=true"]
    command += ["-e", "Change ChMate package name",
               f"-OpackageName={CONFIG['package_name']}", f"-OappName={CONFIG['app_name']}",
               f"-OversionCode={CONFIG['version_code']}"]
    if crash_log_patch:
        command += ["-e", "Save ChMate crash logs"]
    for name in ("shizuku", "mega", "video_viewer"):
        command += ["-e" if variant[name] else "-d", CONFIG["patches"][name]]
    if libraries:
        command += ["-e", LIBRARY_PATCHES["moderation"]]
        command += [f"-O{option}={path}" for option, path in libraries.items() if option.startswith("imageModeration")]
        command += ["-e", LIBRARY_PATCHES["vpn"],
                    f"-OimageVpnLibraryFile={libraries['imageVpnLibraryFile']}"]
    command += ["-o", str(target), "--keystore", str(key),
                "--keystore-entry-alias", "chatmates", "--keystore-password", password,
                "--keystore-entry-password", password,
                "--signer", "ChatMates", "--result-file", str(LOGS / (target.stem + ".result.json")),
                "-t", str(WORK / "scratch" / target.stem)]
    return command


def run_patch(command: list[str], log: Path):
    with log.open("w", encoding="utf-8") as target:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        assert process.stdout is not None
        for line in process.stdout:
            target.write(line)
            print(line, end="", flush=True)
        if process.wait() != 0:
            raise RuntimeError(f"Patching failed. See {log}")


def get_plan() -> dict:
    return json.loads(os.environ["RELEASE_JSON"])


def build(apk_id: str):
    plan = get_plan()
    state_path = WORK / f"libraries-{apk_id}.json"
    if not state_path.exists():
        prepare_libraries(apk_id)
    library_state = json.loads(state_path.read_text(encoding="utf-8"))
    if library_state["release_key"] != plan["key"]:
        raise RuntimeError("Prepared libraries belong to a different release")
    library_options = library_state["options"]
    for asset in library_state["assets"]:
        path = WORK / "libraries" / plan["key"] / asset["name"]
        if sha256(path) != asset["sha256"]:
            raise RuntimeError("Prepared library checksum mismatch")
    apk = next(item for item in CONFIG["apks"] if item["id"] == apk_id)
    OUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    LOGS.mkdir(exist_ok=True)
    password = os.environ.get("CHATMATES_KEYSTORE_PASSWORD", "")
    if not password:
        raise RuntimeError("Set CHATMATES_KEYSTORE_PASSWORD and CHATMATES_KEYSTORE_BASE64 in Actions secrets")
    key = ROOT / ".signing" / "chatmates.p12"
    if encoded := os.environ.get("CHATMATES_KEYSTORE_BASE64"):
        key.parent.mkdir(exist_ok=True)
        key.write_bytes(base64.b64decode(encoded, validate=True))
    if not key.exists():
        raise RuntimeError("ChatMates signing keystore is missing")
    certificate = subprocess.check_output(["keytool", "-exportcert", "-alias", "chatmates",
        "-keystore", str(key), "-storepass:env", "CHATMATES_KEYSTORE_PASSWORD"])
    signer_sha256 = hashlib.sha256(certificate).hexdigest()
    if signer_sha256 != CONFIG["signer_sha256"]:
        raise RuntimeError("Signing certificate does not match chatmates.json")
    cli_config = CONFIG["cli"]
    cli = download(f"https://github.com/{cli_config['repository']}/releases/download/"
                   f"{cli_config['tag']}/{cli_config['asset']}", WORK / cli_config["asset"], cli_config["sha256"])
    bundle = download(plan["asset"]["browser_download_url"], WORK / (plan["key"] + ".mpp"),
                      asset_digest(plan["asset"]))
    available_patches = bundle_patch_names(cli, bundle)
    crash_log_patch = "Save ChMate crash logs" in available_patches
    if (not crash_log_patch and not version_at_least(
            plan["upstream_tag"], CONFIG["crash_logs_integrated_since"])):
        raise RuntimeError("Crash log patch is missing before its documented integration version")
    # Local original APKs can be used without publishing them first.
    source = ROOT / "inputs" / apk["asset"]
    if source.exists():
        if sha256(source) != apk["sha256"]:
            raise RuntimeError(f"Original APK checksum mismatch: {source.name}")
    else:
        source = download(f"https://github.com/{REPO}/releases/download/"
                          f"{CONFIG['source_release']}/{apk['asset']}", WORK / apk["asset"], apk["sha256"])
    artifacts = []
    file_version = re.sub(r"[^A-Za-z0-9._-]", "-", plan["upstream_tag"])
    for variant in build_variants(plan):
        active_libraries = library_options
        filename = f"ChatMates-{apk_id}-Haiagaru-{file_version}-{variant['id']}.apk"
        target = OUT / filename
        expected_patches = selected_patches(variant, active_libraries)
        if crash_log_patch:
            expected_patches.append("Save ChMate crash logs")
        print(f"Building {filename}: {', '.join(expected_patches)}", flush=True)
        run_patch(patch_command(cli, bundle, source, target, key, variant, password,
                                active_libraries, crash_log_patch), LOGS / (target.stem + ".log"))
        result = json.loads((LOGS / (target.stem + ".result.json")).read_text(encoding="utf-8"))
        applied = set(result.get("appliedPatches", []))
        desired = set(expected_patches)
        disabled = {CONFIG["patches"][name] for name in ("shizuku", "mega", "video_viewer") if not variant[name]}
        if (not result.get("success") or result.get("failedPatches")
                or not desired.issubset(applied) or disabled.intersection(applied)):
            raise RuntimeError(f"Patch result does not match the requested variant: {filename}")
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"Expected APK was not produced: {target}")
        with zipfile.ZipFile(target) as archive:
            if active_libraries:
                required = ["assets/haiagaru/image-moderation/model.onnx"]
                required += [f"lib/{abi}/{name}" for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
                             for name in ("libonnxruntime.so", "libonnxruntime4j_jni.so")]
                required += [f"lib/{abi}/libgojni.so" for abi in
                             ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")]
                if apk_id == "191":
                    required.append("assets/haiagaru/image-ng-runtime-fixed")
                for name in required:
                    if name not in archive.namelist():
                        raise RuntimeError(f"Required library/model marker missing: {name}")
        artifacts.append({"file": filename, "sha256": sha256(target), "variant": variant,
                          "patches": expected_patches,
                          "libraries": library_state["assets"] if active_libraries else [],
                          "image_detection_min_sdk": 24 if active_libraries else None})
    manifest = {"release": plan, "source": apk, "app_name": CONFIG["app_name"],
                "package_name": CONFIG["package_name"], "version_code": CONFIG["version_code"],
                "signer_sha256": signer_sha256, "cli": cli_config,
                "bundle_sha256": sha256(bundle), "artifacts": artifacts,
                "libraries": library_state["assets"],
                "builder_commit": os.environ.get("GITHUB_SHA", "local")}
    (OUT / f"build-{apk_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish():
    plan = get_plan()
    expected = set()
    for apk in CONFIG["apks"]:
        manifest = json.loads((OUT / f"build-{apk['id']}.json").read_text(encoding="utf-8"))
        if manifest["release"]["key"] != plan["key"] or manifest["signer_sha256"] != CONFIG["signer_sha256"]:
            raise RuntimeError("Build manifest release or signing certificate mismatch")
        if {entry["variant"]["id"] for entry in manifest["artifacts"]} != {v["id"] for v in build_variants(plan)}:
            raise RuntimeError("Missing build variants")
        for entry in manifest["artifacts"]:
            path = OUT / entry["file"]
            if sha256(path) != entry["sha256"]:
                raise RuntimeError(f"Built APK checksum mismatch: {path.name}")
            expected.add(path)
    if len(expected) != len(CONFIG["apks"]) * len(build_variants(plan)):
        raise RuntimeError("Incomplete APK build set")
    checksums = OUT / "SHA256SUMS"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(expected)), encoding="utf-8")
    notes = OUT / "release-notes.md"
    trigger_note = (f"Update requested: {plan['issue_request']['url']}\n\n"
                    if "issue_request" in plan else "")
    library_note = ("Every APK includes enabled image detection and image VPN patches with matching model/runtime libraries. "
                    "ChMate 191 also includes the Image NG runtime fix. "
                    "These features require Android 7.0 (API 24) or newer.\n\n")
    notes.write_text(f"# ChatMate's · Haiagaru {plan['upstream_tag']}\n\n"
        f"Upstream: {plan['upstream_url']}\n\nChannel: **{plan['channel']}**\n\n"
        f"{trigger_note}"
        f"{library_note}"
        "Crash log saving is included in every APK (Download/Haiagaru); crash/ANR log sending follows the in-app consent setting. "
        "Shizuku, MEGA, and the dedicated video viewer are enabled in every APK. "
        f"This release contains {len(CONFIG['apks']) * len(build_variants(plan))} APKs.\n\n"
        "ChMate: 0.8.10.191 dev / 0.8.10.226 dev / 0.8.10.242 dev.\n\n"
        f"{variant_table(plan)}"
        f"App name: **{CONFIG['app_name']}**  \nPackage: `{CONFIG['package_name']}`  \n"
        f"versionCode: `{CONFIG['version_code']}`  \nSigner SHA-256: `{CONFIG['signer_sha256']}`\n\n"
        "All variants share the package ID and signing certificate. Install one variant at a time. "
        "Shizuku/MEGA variants require Android 7.0 or newer. "
        "Plain builds retain the source APK's minimum Android version.\n\n"
        "APK signatures and SHA-256 checksums are generated during the build; build-*.json records "
        "the exact original APK, patch bundle, CLI, selected patches and source commit.\n\n"
        "Credits: [Haiagaru](https://github.com/areteruhiro/Haiagaru-Morphe), "
        "[Morphe](https://github.com/MorpheApp), "
        "[VVispy/morphe-builder](https://github.com/VVispy/morphe-builder).\n", encoding="utf-8")
    files = sorted(expected) + sorted(OUT.glob("build-*.json")) + [checksums]
    existing = subprocess.run(["gh", "release", "view", plan["tag"], "--repo", REPO,
                               "--json", "isDraft"], capture_output=True, text=True)
    if existing.returncode == 0:
        if not json.loads(existing.stdout)["isDraft"]:
            raise RuntimeError("This build release is already published")
    else:
        subprocess.run(["gh", "release", "create", plan["tag"], "--repo", REPO, "--draft",
            "--target", os.environ.get("GITHUB_SHA", "main"),
            "--title", f"ChatMate's · Haiagaru {plan['upstream_tag']} ({plan['channel']})",
            "--notes-file", str(notes)], check=True)
    # Keep incomplete uploads as drafts. A subsequent run resumes the same draft.
    subprocess.run(["gh", "release", "upload", plan["tag"], *map(str, files),
                    "--repo", REPO, "--clobber"], check=True)
    flags = ["--prerelease", "--latest=false"] if plan["channel"] == "prerelease" else ["--prerelease=false", "--latest"]
    subprocess.run(["gh", "release", "edit", plan["tag"], "--repo", REPO,
                    "--draft=false", "--notes-file", str(notes), *flags], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "prepare-libraries", "build", "publish"))
    parser.add_argument("--channel", choices=("all", "stable", "prerelease"), default="all")
    parser.add_argument("--apk-id", choices=[apk["id"] for apk in CONFIG["apks"]])
    args = parser.parse_args()
    if args.command == "discover":
        discover(args.channel)
    elif args.command in ("build", "prepare-libraries"):
        if not args.apk_id:
            parser.error("build requires --apk-id")
        (build if args.command == "build" else prepare_libraries)(args.apk_id)
    else:
        publish()


if __name__ == "__main__":
    main()
