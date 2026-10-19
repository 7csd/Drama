"""Version legacy pipeline workspaces without deleting earlier productions."""
import hashlib
import json
import shutil
import uuid
from pathlib import Path


def ensure_workspace_revision(working_dir, inputs):
    root = Path(working_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    manifest = root / "production_revision.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    known = ["characters.json", "storyboard.json", "camera_tree.json", "character_portraits_registry.json",
             "shots", "character_portraits", "image_candidates", "final_video.mp4"]
    if previous.get("fingerprint") != fingerprint:
        present = [root / name for name in known if (root / name).exists()]
        if present:
            archive = root / ".history" / uuid.uuid4().hex
            if not archive.resolve().is_relative_to(root):
                raise ValueError("Cache archive must stay within its workspace")
            archive.mkdir(parents=True)
            for source in present:
                if not source.resolve().is_relative_to(root):
                    raise ValueError("Cache source must stay within its workspace")
                shutil.move(str(source), str(archive / source.name))
            if manifest.exists():
                shutil.copyfile(manifest, archive / manifest.name)
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps({"fingerprint": fingerprint, "inputs": inputs}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(manifest)
    return fingerprint
