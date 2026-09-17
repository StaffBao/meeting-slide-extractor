"""User-level ASR setup for Meeting Slide Extractor.

Preferences never live inside the shared Skill folder. API keys are read from
environment variables first. On Windows the interactive wizard stores them in
the current user's Environment registry key; on other platforms it uses a
permission-restricted user credential file.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys


PROVIDERS = {
    "qwen": {
        "env": "DASHSCOPE_API_KEY",
        "model": "qwen-audio-3.0-asr-flash",
        "label": "Qwen / 千问 Token Plan",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini-transcribe",
        "label": "OpenAI API",
    },
}


def config_dir() -> Path:
    override = os.getenv("MEETING_SLIDE_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        root = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "MeetingSlideExtractor"
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "meeting-slide-extractor"


def config_path() -> Path:
    return config_dir() / "config.json"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_json(path: Path, data: dict, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private and os.name != "nt":
        path.chmod(0o600)


def read_windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip() or None
    except (FileNotFoundError, OSError):
        return None


def write_windows_user_env(name: str, value: str | None) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def load_api_key(provider: str) -> str | None:
    info = PROVIDERS[provider]
    value = os.getenv(info["env"])
    if value:
        return value.strip()
    value = read_windows_user_env(info["env"])
    if value:
        return value
    if os.name != "nt":
        value = read_json(credentials_path()).get(provider)
        if value:
            return str(value).strip()
    return None


def save_api_key(provider: str, value: str) -> None:
    value = value.strip()
    if not value:
        raise ValueError("API key cannot be empty")
    env_name = PROVIDERS[provider]["env"]
    if os.name == "nt":
        write_windows_user_env(env_name, value)
    else:
        credentials = read_json(credentials_path())
        credentials[provider] = value
        write_json(credentials_path(), credentials, private=True)


def clear_api_key(provider: str) -> None:
    env_name = PROVIDERS[provider]["env"]
    if os.name == "nt":
        write_windows_user_env(env_name, None)
    else:
        credentials = read_json(credentials_path())
        credentials.pop(provider, None)
        write_json(credentials_path(), credentials, private=True)


def save_choice(mode: str, provider: str | None = None) -> None:
    data = {"mode": mode}
    if provider:
        data["provider"] = provider
        data["model"] = PROVIDERS[provider]["model"]
    write_json(config_path(), data)


def status() -> dict:
    choice = read_json(config_path())
    mode = choice.get("mode", "unconfigured")
    provider = choice.get("provider")
    ready = mode == "offline" or (
        mode == "cloud" and provider in PROVIDERS and bool(load_api_key(provider))
    )
    return {
        "mode": mode,
        "provider": provider,
        "model": choice.get("model"),
        "ready": ready,
        "qwen_key_configured": bool(load_api_key("qwen")),
        "openai_key_configured": bool(load_api_key("openai")),
        "config_path": str(config_path()),
    }


def ask_choice(prompt: str, options: dict[str, str]) -> str:
    while True:
        print(prompt)
        for number, label in options.items():
            print(f"  {number}. {label}")
        answer = input("> ").strip()
        if answer in options:
            return answer
        print("Please enter one of: " + ", ".join(options))


def wizard() -> None:
    mode = ask_choice(
        "Choose transcription mode / 请选择转写方式：",
        {
            "1": "Cloud ASR (recommended; may incur a small fee) / 云端 ASR（推荐；可能产生少量费用）",
            "2": "Offline ASR (downloads ~1.53 GB on first use; slower) / 离线 ASR（首次需下载约 1.53 GB 模型；耗时较长）",
        },
    )
    if mode == "2":
        save_choice("offline")
        print("Saved: offline faster-whisper medium / 已保存：离线 faster-whisper medium")
        return

    selected = ask_choice(
        "Choose cloud provider / 请选择云端服务：",
        {"1": PROVIDERS["qwen"]["label"], "2": PROVIDERS["openai"]["label"]},
    )
    provider = "qwen" if selected == "1" else "openai"
    if not load_api_key(provider):
        env_name = PROVIDERS[provider]["env"]
        value = getpass.getpass(f"Enter {env_name} (hidden input / 输入不可见): ")
        save_api_key(provider, value)
    save_choice("cloud", provider)
    print(f"Saved: {PROVIDERS[provider]['label']} / 配置已保存。")
    print("The key value was not printed and is not stored in the Skill folder.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure ASR without placing secrets in the Skill folder")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("wizard")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    mode_parser = sub.add_parser("set-mode")
    mode_parser.add_argument("mode", choices=["cloud", "offline"])
    mode_parser.add_argument("--provider", choices=sorted(PROVIDERS))
    clear_parser = sub.add_parser("clear-key")
    clear_parser.add_argument("provider", choices=sorted(PROVIDERS))
    args = parser.parse_args()

    if args.command == "wizard":
        wizard()
    elif args.command == "status":
        data = status()
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else data)
    elif args.command == "set-mode":
        if args.mode == "cloud" and not args.provider:
            parser.error("--provider is required for cloud mode")
        save_choice(args.mode, args.provider)
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.command == "clear-key":
        clear_api_key(args.provider)
        print(f"Cleared {PROVIDERS[args.provider]['env']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled / 已取消")
