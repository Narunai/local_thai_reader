"""Explicit online setup; normal server execution never downloads assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
from .settings import MODEL_DIR, prepare
from huggingface_hub import hf_hub_download
from .backends import F5_MODELS


def download(profile: str):
    prepare()
    revisions = json.loads((Path(__file__).parent / 'model_versions.json').read_text(encoding='utf-8'))
    tasks = [("k2-fsa/OmniVoice", "omnivoice", [
        "README.md", "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
        "audio_tokenizer/config.json", "audio_tokenizer/model.safetensors", "audio_tokenizer/preprocessor_config.json",
        "audio_tokenizer/LICENSE", "audio_tokenizer/README.md",
    ])] if profile == "omnivoice" else [("VIZINTZOR/VachanaTTS", "vachana", ["speaker_config.json", "voices/th_f_1.onnx", "voices/th_f_2.onnx"])] if profile == "vachana" else [
        (F5_MODELS[profile][0], profile, list(F5_MODELS[profile][1:])),
        ("charactr/vocos-mel-24khz", "vocos", ["config.yaml", "pytorch_model.bin"]),
    ]
    for repo, folder, filenames in tasks:
        revision = revisions[repo]
        target = MODEL_DIR / folder
        manifest = {"repository": repo, "revision": revision, "files": {}}
        previous_file = target / 'manifest.json'
        previous = json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.exists() else {}
        for filename in filenames:
            dest = target / (filename.removeprefix("voices/") if folder == "vachana" else filename)
            relative = str(dest.relative_to(target))
            if previous.get('revision') == revision and dest.is_file() and previous.get('files',{}).get(relative) == hashlib.sha256(dest.read_bytes()).hexdigest():
                manifest['files'][relative] = previous['files'][relative]
                print(f"Already verified: {dest.name}",flush=True)
                continue
            source = hf_hub_download(repo, filename, revision=revision, local_dir=target)
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            if Path(source).resolve() != dest.resolve():
                shutil.move(source, dest)
            manifest["files"][str(dest.relative_to(target))] = hashlib.sha256(dest.read_bytes()).hexdigest()
            print(f"Ready: {dest.name}", flush=True)
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=["vachana", "omnivoice", *F5_MODELS])
    try:
        download(parser.parse_args().profile)
    except __import__('huggingface_hub').errors.GatedRepoError:
        raise SystemExit("Model access is restricted. Request access on its Hugging Face page, then set HF_TOKEN locally and run setup again. Never paste the token into chat.")
