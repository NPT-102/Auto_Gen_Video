import concurrent.futures
import asyncio
import http.server
import importlib.util
import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from factory import narration
from factory.spec import Spec


def script(**fields):
    return Spec.model_validate({
        "id": "test", "title": "Thử giọng",
        "scenes": [{"type": "next", "title": "Kết", "say": "Xin chào."}],
        **fields,
    })


class ProviderTests(unittest.TestCase):
    def test_old_scripts_keep_edge_voice(self):
        spec = script()
        self.assertEqual(spec.tts_provider, "edge")
        with patch.object(narration, "synthesize", return_value="edge audio") as synth:
            self.assertEqual(narration.synthesize_spec("Xin chào.", spec), "edge audio")
        synth.assert_called_once_with("Xin chào.", "vi-VN-HoaiMyNeural")

    def test_provider_is_validated(self):
        with self.assertRaises(ValidationError):
            script(tts_provider="unknown")

    def test_vieneu_selection_uses_separate_preset(self):
        spec = script(tts_provider="vieneu", vieneu_voice="Mai Anh")
        with patch("factory.vieneu.synthesize", return_value="vieneu audio") as synth:
            self.assertEqual(narration.synthesize_spec("Xin chào.", spec), "vieneu audio")
        synth.assert_called_once_with("Xin chào.", "Mai Anh")

    def test_timeline_uses_selected_audio_and_timings(self):
        spec = script(tts_provider="vieneu", vieneu_voice="Mai Anh")
        with patch.object(narration, "synthesize_spec", return_value=(Path("voice.mp3"), [
            {"text": "Xin", "start": 0.1, "end": 0.4}, {"text": "chào", "start": 0.4, "end": 0.9}], 1.0)) as synth:
            data, parts = narration.build_timeline(spec)
        synth.assert_called_once_with("Xin chào.", spec)
        self.assertEqual(parts[0][0], Path("voice.mp3"))
        self.assertEqual(data["words"][0]["start"], 0.35)
        self.assertEqual(data["words"][1]["display"], "chào.")


class EngineRoutingTests(unittest.TestCase):
    def test_mpt_stock_uses_selected_audio(self):
        from factory.engines import mpt
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            audio = workdir / "voice.mp3"
            with patch.object(mpt, "synthesize_spec", return_value=(audio, [], 1.0)) as synth, \
                    patch.object(mpt, "venv_python", return_value=("python",)), \
                    patch.object(mpt, "run", side_effect=mpt.EngineError("stop after manifest")):
                with self.assertRaises(mpt.EngineError):
                    mpt.MoneyPrinterTurbo().render(script(tts_provider="vieneu"), workdir, lambda _: None)
            task = json.loads((workdir / "mpt-manifest.json").read_text())[0]
            self.assertEqual(task["custom_audio_file"], str(audio))
            self.assertFalse(task["subtitle_enabled"])
            self.assertEqual(synth.call_args.args[0], "Xin chào.")

    def test_mpt_podcast_vieneu_takes_precedence_over_elevenlabs(self):
        from factory.engines import mpt
        spec = script(tts_provider="vieneu", podcast={"say": "Xin chào " * 12})
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            with patch.object(mpt, "synthesize_spec", return_value=(workdir / "voice.mp3", [], 1.0)) as synth, \
                    patch.object(mpt.eleven, "api_key", return_value="configured-key"), \
                    patch.object(mpt.eleven, "synthesize") as eleven, \
                    patch.object(mpt, "venv_python", return_value=("python",)), \
                    patch.object(mpt, "run", side_effect=mpt.EngineError("stop")):
                with self.assertRaises(mpt.EngineError):
                    mpt.MoneyPrinterTurbo().render(spec, workdir, lambda _: None)
            synth.assert_called_once_with(spec.podcast["say"], spec)
            eleven.assert_not_called()

    def test_uploaded_podcast_overrides_vieneu(self):
        from factory.engines import mpt
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            audio = workdir / "uploaded.mp3"
            audio.write_bytes(b"audio")
            spec = script(tts_provider="vieneu", podcast={"say": "Xin chào " * 12, "audio": str(audio)})
            with patch.object(mpt, "synthesize_spec") as synth, patch.object(mpt.eleven, "synthesize") as eleven, \
                    patch.object(mpt.align, "align", return_value=([], 1.0)), \
                    patch.object(mpt, "venv_python", return_value=("python",)), \
                    patch.object(mpt, "run", side_effect=mpt.EngineError("stop")):
                with self.assertRaises(mpt.EngineError):
                    mpt.MoneyPrinterTurbo().render(spec, workdir, lambda _: None)
            task = json.loads((workdir / "mpt-manifest.json").read_text())[0]
            self.assertEqual(task["custom_audio_file"], str(audio))
            synth.assert_not_called()
            eleven.assert_not_called()

    def test_aiauto_captions_use_selected_audio(self):
        from factory.engines import aiauto
        spec = script(tts_provider="vieneu")
        with patch.object(aiauto, "synthesize_spec", return_value=(Path("voice.mp3"), [
            {"text": "Xin", "start": 0.1, "end": 0.4}, {"text": "chào", "start": 0.4, "end": 0.9}], 1.0)) as synth:
            ass = aiauto.build_ass({"scenes": [{"voiceText": "Xin chào."}]}, spec)
        synth.assert_called_once_with("Xin chào.", spec)
        self.assertIn("chào.", ass)

    def test_pixelle_receives_prepared_audio_for_each_sentence(self):
        from factory.engines import pixelle
        spec = script(tts_provider="vieneu", scenes=[
            {"type": "next", "title": "Kết", "say": "Xin chào. Hẹn gặp lại!"}])
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            repo = workdir / "repo"
            repo.mkdir()
            (repo / "config.yaml").write_text("")
            with patch.object(pixelle, "REPO", repo), \
                    patch.object(pixelle, "sentence_photos", return_value=[None, None]), \
                    patch.object(pixelle, "_ensure_template"), patch.object(pixelle, "_background", return_value="bg.jpg"), \
                    patch.object(pixelle, "synthesize_spec", return_value=(workdir / "voice.mp3", [], 1.25)) as synth, \
                    patch.object(pixelle, "venv_python", return_value=("python",)), \
                    patch.object(pixelle, "run", side_effect=pixelle.EngineError("stop after job")):
                with self.assertRaises(pixelle.EngineError):
                    pixelle.PixelleVideo().render(spec, workdir, lambda _: None)
            job = json.loads((workdir / "pixelle-job.json").read_text())
            self.assertEqual(len(job["audio"]), 2)
            self.assertEqual(job["audio"][0]["duration"], 1.25)
            self.assertEqual([call.args[0] for call in synth.call_args_list], ["Xin chào.", "Hẹn gặp lại!"])

    def test_pixelle_driver_sets_audio_paths_and_rejects_frame_mismatch(self):
        # Stub only upstream classes: verify our driver against the pinned frame contract
        # without installing Pixelle's unrelated GPU/image dependencies.
        class StandardPipeline:
            def __init__(self, core):
                pass

            async def initialize_storyboard(self, ctx):
                ctx.storyboard = types.SimpleNamespace(frames=[types.SimpleNamespace()])

        stubs = {}
        for module_name, attr, value in [
            ("pixelle_video.pipelines.standard", "StandardPipeline", StandardPipeline),
            ("pixelle_video.service", "PixelleVideoCore", object),
            ("pixelle_video.services.frame_html", "HTMLFrameGenerator", object),
            ("pixelle_video.utils.template_util", "resolve_template_path", str),
        ]:
            module = types.ModuleType(module_name)
            setattr(module, attr, value)
            stubs[module_name] = module
        with patch.dict("sys.modules", stubs):
            loader = importlib.util.spec_from_file_location("pixelle_driver_test", "factory/engines/pixelle_driver.py")
            driver = importlib.util.module_from_spec(loader)
            loader.loader.exec_module(driver)
        ctx = types.SimpleNamespace()
        pipeline = driver.PhotoPipeline(None, [], [{"path": "voice.mp3", "duration": 1.25}])
        asyncio.run(pipeline.initialize_storyboard(ctx))
        self.assertEqual(ctx.storyboard.frames[0].audio_path, "voice.mp3")
        self.assertEqual(ctx.storyboard.frames[0].duration, 1.25)
        with self.assertRaises(ValueError):
            asyncio.run(driver.PhotoPipeline(None, [], []).initialize_storyboard(ctx))


class AlignmentTests(unittest.TestCase):
    def test_factory_launcher_workaround_is_preserved(self):
        from factory import align
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            venv = root / "factory-venv"
            venv.mkdir()
            (venv / "pyvenv.cfg").write_text("home = C:\\Python")
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps({"words": [], "duration": 1.0}), stderr="")
            with patch.object(align, "setting", return_value=""), patch.object(align, "MPT_DIR", root / "missing-mpt"), \
                    patch.object(align.sys, "prefix", str(venv)), patch.object(align, "CACHE", root / "align"), \
                    patch.object(align, "venv_python", return_value=("base-python", "-c", "bootstrap")) as command, \
                    patch.object(align.subprocess, "run", return_value=result) as run:
                align.whisper_words(audio)
            command.assert_called_once_with(venv)
            self.assertEqual(run.call_args.args[0][:3], ["base-python", "-c", "bootstrap"])

    def test_explicit_interpreter_is_used(self):
        from factory import align
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps({"words": [], "duration": 1.0}), stderr="")
            with patch.dict("os.environ", {"ALIGN_PYTHON": "custom-whisper-python"}), \
                    patch.object(align, "CACHE", root / "align"), \
                    patch.object(align.subprocess, "run", return_value=result) as run:
                align.whisper_words(audio)
            self.assertEqual(run.call_args.args[0][0], "custom-whisper-python")

    def test_factory_interpreter_without_mpt_is_used(self):
        from factory import align
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps({"words": [], "duration": 1.0}), stderr="")
            with patch.object(align, "setting", return_value=""), patch.object(align, "MPT_DIR", root / "missing-mpt"), \
                    patch.object(align, "CACHE", root / "align"), \
                    patch.object(align.subprocess, "run", return_value=result) as run:
                align.whisper_words(audio)
            self.assertEqual(run.call_args.args[0][0], align.sys.executable)


class VoiceDiscoveryTests(unittest.TestCase):
    def test_web_reports_unavailable_server(self):
        from fastapi.testclient import TestClient
        from factory.app import app
        with patch("factory.vieneu.voices", side_effect=RuntimeError("server offline")):
            response = TestClient(app).get("/api/tts/vieneu/voices")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ready"])
        self.assertEqual(response.json()["reason"], "server offline")


class SpeechAPITests(unittest.TestCase):
    def setUp(self):
        from factory import vieneu
        self.vieneu = vieneu
        self.requests = []
        self.status = 200
        self.audio = b"\0\0" * 48000  # one second of PCM s16le, as served by VieNeu
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append((self.path, None, self.headers.get("Authorization")))
                data = json.dumps({"object": "list", "data": [{"id": "Mai Anh", "name": "Mai Anh"}]}).encode()
                self.send_response(owner.status)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, body, self.headers.get("Authorization")))
                self.send_response(owner.status)
                self.end_headers()
                self.wfile.write(owner.audio)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.env = patch.dict("os.environ", {
            "VIENEU_URL": f"http://127.0.0.1:{self.server.server_port}",
            "VIENEU_API_KEY": "local-test-key", "VIENEU_VOICE": "Hải Đăng",
        })
        self.env.start()
        self.cache_patch = patch.object(vieneu, "TTS_CACHE", self.cache)
        self.cache_patch.start()
        from factory.align import align
        self.real_align = align
        self.align = patch("factory.align.align", return_value=(
            [{"text": "Xin", "start": 0.1, "end": 0.4}, {"text": "chào.", "start": 0.4, "end": 0.9}], 1.0))
        self.aligner = self.align.start()

    def tearDown(self):
        self.align.stop()
        self.cache_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_audio_is_mp3_aligned_cached_and_authenticated(self):
        audio, words, duration = self.vieneu.synthesize("Xin chào.", "Mai Anh")
        self.assertTrue(audio.exists())
        self.assertEqual(audio.suffix, ".mp3")
        self.assertGreater(duration, 0.9)
        self.assertEqual(words[1]["text"], "chào.")
        path, body, auth = self.requests[0]
        self.assertEqual(path, "/v1/audio/speech")
        self.assertEqual(body["voice"], "Mai Anh")
        self.assertEqual(body["input"], "Xin chào.")
        self.assertEqual(body["response_format"], "pcm")
        self.assertEqual(body["model"], "vieneu-v3-turbo")
        self.assertEqual(body["sample_rate"], 48000)
        self.assertEqual(auth, "Bearer local-test-key")
        self.assertEqual(self.vieneu.synthesize("Xin chào.", "Mai Anh")[0], audio)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.aligner.call_count, 1)
        self.vieneu.synthesize("Xin chào.", "Hải Đăng")
        self.assertEqual(len(self.requests), 2)

    def test_concurrent_engines_share_synthesis(self):
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda _: self.vieneu.synthesize("Xin chào."), range(3)))
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(all(r[0] == results[0][0] for r in results))

    def test_failed_request_does_not_publish_cache(self):
        self.status = 503
        with self.assertRaisesRegex(RuntimeError, "VieNeu"):
            self.vieneu.synthesize("Xin chào.")
        self.assertFalse(list(self.cache.glob("*.json")))

    def test_empty_audio_does_not_publish_cache(self):
        self.audio = b""
        with self.assertRaisesRegex(RuntimeError, "VieNeu"):
            self.vieneu.synthesize("Xin chào.")
        self.assertFalse(list(self.cache.glob("*.json")))

    def test_alignment_failure_can_be_retried(self):
        self.aligner.side_effect = RuntimeError("Whisper unavailable")
        with self.assertRaisesRegex(RuntimeError, "Whisper"):
            self.vieneu.synthesize("Xin chào.")
        self.assertFalse(list(self.cache.glob("*.json")))
        self.aligner.side_effect = None
        self.vieneu.synthesize("Xin chào.")
        self.assertEqual(len(self.requests), 2)

    def test_lists_server_presets(self):
        self.assertEqual(self.vieneu.voices(), [{"key": "Mai Anh", "label": "Mai Anh"}])
        self.assertEqual(self.requests[0][0], "/v1/voices")

    def test_base_url_can_already_include_v1(self):
        with patch.dict("os.environ", {"VIENEU_URL": f"http://127.0.0.1:{self.server.server_port}/v1/"}):
            self.vieneu.synthesize("Xin chào.")
        self.assertEqual(self.requests[0][0], "/v1/audio/speech")

    def test_alignment_uses_original_text_and_real_audio(self):
        from factory import align
        # This tests the actual transcript matching/interpolation, stubbing only model output.
        with patch("factory.align.align", wraps=self.real_align), patch.object(align, "whisper_words", return_value=(
            [{"w": "Xin", "a": 0.1, "b": 0.3}, {"w": "chào", "a": 0.5, "b": 0.9}], 1.0)):
            _, words, _ = self.vieneu.synthesize("Xin bạn chào.")
        self.assertEqual([w["text"] for w in words], ["Xin", "bạn", "chào."])
        self.assertAlmostEqual(words[1]["start"], 0.3)
        self.assertAlmostEqual(words[1]["end"], 0.5)


if __name__ == "__main__":
    unittest.main()
