import importlib.util
import hashlib
import io
import json
import os
import subprocess
import signal
import socket
import sys
import tempfile
import tomllib
import unittest
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

from factory import config, pyrun

ROOT = Path(__file__).resolve().parents[1]


class LinuxRuntimeTests(unittest.TestCase):
    def test_mpt_directory_expands_home_and_relative_paths(self):
        with patch.object(config, "setting", return_value="~/MoneyPrinterTurbo"):
            self.assertEqual(config._mpt_dir(), Path.home() / "MoneyPrinterTurbo")
        with patch.object(config, "setting", return_value="custom/mpt"):
            self.assertEqual(config._mpt_dir(), ROOT / "custom/mpt")

    def test_posix_venv_runs_with_its_own_packages(self):
        with tempfile.TemporaryDirectory(prefix="vf linux '") as folder:
            venv = Path(folder) / "venv"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", venv], check=True)
            command = pyrun.venv_python(venv)
            self.assertEqual(command, (str(venv / "bin" / "python"),))
            result = subprocess.run([*command, "-c", "import sys; print(sys.prefix)"],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(venv))

    def test_browser_is_detected_from_linux_path(self):
        with patch.object(config, "setting", return_value=""), \
                patch("shutil.which", side_effect=lambda name: "/usr/bin/chromium" if name == "chromium" else None):
            self.assertEqual(config._chrome(), Path("/usr/bin/chromium"))

    def test_explicit_browser_takes_precedence(self):
        with patch.object(config, "setting", return_value="/opt/browser/chrome"):
            self.assertEqual(config._chrome(), Path("/opt/browser/chrome"))

    def test_engine_python_paths_are_linux_paths(self):
        from factory.engines import mpt, pixelle
        self.assertEqual(mpt.PYTHON, mpt.MPT_DIR / ".venv" / "bin" / "python")
        self.assertEqual(pixelle.PYTHON, pixelle.REPO / ".venv" / "bin" / "python")

    def test_aiauto_uses_native_npm(self):
        source = (ROOT / "factory/engines/aiauto.py").read_text()
        self.assertNotIn('["npm.cmd",', source)

    def test_remotion_sequence_uses_path_without_dotted_ancestors(self):
        from factory.engines import remotion
        from factory.spec import Spec
        spec = Spec.model_validate({"id": "smoke", "title": "Smoke", "images": False,
                                    "scenes": [{"type": "next", "title": "End", "say": "Xin chào."}]})
        commands = []
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            workdir = Path(folder) / ".cache" / "render"
            workdir.mkdir(parents=True)

            def fake_run(command, **kwargs):
                commands.append(command)
                if command[0] == "node":
                    output = str(command[5])
                    # The pinned Remotion CLI treats any dot in an output path as an extension.
                    self.assertNotIn(".", output)
                    frames = project / output
                    frames.mkdir(parents=True)
                    (frames / "frame0.jpeg").write_bytes(b"jpeg")

            with patch.object(remotion, "PROJECT", project), \
                    patch.object(remotion, "build_timeline", return_value=({"duration": 1.0}, [])), \
                    patch.object(remotion, "attach_beats"), patch.object(remotion, "build_audio"), \
                    patch.object(remotion, "run", side_effect=fake_run):
                remotion.Remotion().render(spec, workdir, lambda _: None)
            self.assertEqual(len(commands), 2)


class InstallerTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / ".venv" / "bin" / "python").exists(), "Factory venv required for startup integration")
    def test_web_starts_from_another_directory_and_serves_api(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen([sys.executable, ROOT / "chay-web.py", "--no-browser", "--port", str(port)],
                                       cwd="/tmp", stdout=log, stderr=log, start_new_session=True)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(50):
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/api/content", timeout=0.5) as response:
                            data = json.load(response)
                        self.assertIsInstance(data, list)
                        return
                    except OSError:
                        if process.poll() is not None:
                            log.seek(0)
                            self.fail(log.read())
                        time.sleep(0.1)
                self.fail("Web server did not become ready")
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=5)

    def test_all_python_entrypoints_have_help_without_dependencies(self):
        for filename in ["cai-dat.py", "chay-web.py", "cai-comfyui.py", "chay-comfyui.py"]:
            with self.subTest(filename=filename):
                result = subprocess.run([sys.executable, ROOT / filename, "--help"],
                                        cwd="/tmp", capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_mpt_config_preserves_other_settings_and_escapes_keys(self):
        from setup.install import sync_mpt_config
        with tempfile.TemporaryDirectory() as folder:
            mpt = Path(folder)
            (mpt / "config.example.toml").write_text('[app]\nllm_provider = "openai"\ngemini_api_key = ""\n'
                                                     'pexels_api_keys = []\nedge_tts_timeout = 30\n[ui]\n')
            sync_mpt_config(mpt, {"GEMINI_API_KEY": 'test"key', "PEXELS_API_KEY": "stock-test"})
            data = tomllib.loads((mpt / "config.toml").read_text())
            self.assertEqual(data["app"]["gemini_api_key"], 'test"key')
            self.assertEqual(data["app"]["llm_provider"], "gemini")
            self.assertEqual(data["app"]["edge_tts_timeout"], 120)
            self.assertEqual(data["ui"]["language"], "vi")
            sync_mpt_config(mpt, {"PEXELS_API_KEY": "new-stock"})
            data = tomllib.loads((mpt / "config.toml").read_text())
            self.assertEqual(data["app"]["gemini_api_key"], 'test"key')
            self.assertEqual(data["app"]["pexels_api_keys"], ["new-stock"])

    def test_check_mode_does_not_install_or_create_env(self):
        from setup import install
        with tempfile.TemporaryDirectory() as folder, patch.object(install, "ROOT", Path(folder)), \
                patch.object(install, "check_tools", return_value=True), patch.object(install, "show_status", return_value=1), \
                patch.object(install, "run") as run:
            self.assertEqual(install.main(["--check"]), 1)
            self.assertFalse((Path(folder) / ".env").exists())
            run.assert_not_called()

    def test_existing_engine_checkout_is_not_reset(self):
        from setup.install import ensure_repo
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / ".git").mkdir()
            with patch("setup.install.run") as run:
                ensure_repo(repo, "https://example.invalid/repo", "pinned-commit")
            self.assertFalse(any("checkout" in call.args[0] for call in run.call_args_list))

    def test_pixelle_sync_retries_moviepy_build_without_isolation(self):
        from setup.install import sync_engine_env
        with patch("setup.install.run", side_effect=[subprocess.CalledProcessError(1, "uv"), None]) as run:
            sync_engine_env(Path("pixelle"), "pixelle", "3.12", {})
        retry = run.call_args_list[1].args[0]
        self.assertIn("--no-install-project", retry)
        self.assertEqual(retry[-2:], ["--no-build-isolation-package", "moviepy"])

    def test_light_setup_only_installs_requested_engines(self):
        from setup import install
        with tempfile.TemporaryDirectory() as folder, patch.object(install, "ROOT", Path(folder)), \
                patch.object(install, "check_tools", return_value=True), patch.object(install, "show_status", return_value=0), \
                patch.object(install, "ensure_env"), patch.object(install, "run"), \
                patch.object(install, "install_node") as node, patch.object(install, "ensure_repo") as clone:
            self.assertEqual(install.main(["--engines", "hyperframes", "remotion", "broll"]), 0)
            clone.assert_not_called()
            self.assertEqual(len(node.call_args_list), 3)  # ELK + two local engines


class ComfyTests(unittest.TestCase):
    def test_existing_model_does_not_require_download_space(self):
        from setup.comfy import ensure_model
        with patch("setup.comfy.verified", return_value=True), patch("shutil.disk_usage") as space, \
                patch("setup.comfy.download_model") as download:
            ensure_model(Path("model.safetensors"))
        space.assert_not_called()
        download.assert_not_called()

    def test_model_space_check_accounts_for_partial_download(self):
        from setup.comfy import ensure_model
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "model.safetensors"
            target.with_suffix(".safetensors.part").write_bytes(b"x" * 990)
            with patch("setup.comfy.MODEL_SIZE", 1000), patch("setup.comfy.verified", return_value=False), \
                    patch("shutil.disk_usage", return_value=type("Space", (), {"free": 1024 ** 3 + 20})()), \
                    patch("setup.comfy.download_model") as download:
                ensure_model(target)
            download.assert_called_once_with(target)

    def test_download_checks_hash_and_resumes_when_server_ignores_range(self):
        from setup.comfy import download_model

        class Response(io.BytesIO):
            status = 200

        data = b"test checkpoint"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "model.safetensors"
            target.with_suffix(".safetensors.part").write_bytes(b"test")
            with patch("urllib.request.urlopen", return_value=Response(data)):
                download_model(target, "https://example.invalid/model", len(data), hashlib.sha256(data).hexdigest())
            self.assertEqual(target.read_bytes(), data)
            with patch("urllib.request.urlopen") as request:
                download_model(target, "unused", len(data), hashlib.sha256(data).hexdigest())
            request.assert_not_called()

    def test_bad_hash_does_not_replace_existing_checkpoint(self):
        from setup.comfy import download_model

        class Response(io.BytesIO):
            status = 200

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "model.safetensors"
            target.write_bytes(b"original")
            with patch("urllib.request.urlopen", return_value=Response(b"bad")):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    download_model(target, "https://example.invalid/model", 3, "0" * 64)
            self.assertEqual(target.read_bytes(), b"original")

    def test_cpu_launcher_passes_cpu_flag(self):
        from setup.comfy import launch_command
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "main.py").write_text("")
            (repo / ".factory-device").write_text("cpu")
            with patch("setup.comfy.venv_python", return_value=("native-python",)):
                command = launch_command(repo, 8188, None)
            self.assertEqual(command[0], "native-python")
            self.assertIn("--cpu", command)
            self.assertNotIn("--windows-standalone-build", command)


if __name__ == "__main__":
    unittest.main()
