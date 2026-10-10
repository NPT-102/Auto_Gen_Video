import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from factory import beats
from factory.engines import broll
from factory.spec import Spec


class PixabayTests(unittest.TestCase):
    def test_pixabay_images_are_attached_without_pexels_key(self):
        spec = Spec.model_validate({"id": "test", "title": "Flowers", "image_source": "pixabay",
                                    "scenes": [{"type": "next", "title": "End", "say": "Flowers."}]})
        data = {"scenes": [{"type": "next", "start": 0, "end": 3}],
                "words": [{"display": "Flowers.", "start": 0, "end": 3}]}
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "pixabay-1.jpg"
            photo.write_bytes(b"image")
            photo.with_suffix('.json').write_text(json.dumps({"page": "https://pixabay.com/photos/1/"}))
            with patch("factory.config.setting", side_effect=lambda name, default="": "test-key" if name == "PIXABAY_API_KEY" else default), \
                    patch.object(beats, "pexels_api_key", return_value=None), \
                    patch.object(beats, "_queries", return_value=["flowers"]), \
                    patch("factory.pixabay.photo", return_value=photo, create=True):
                count = beats.attach(spec, data, Path(folder) / "output", "/photos/", lambda _: None)
            self.assertEqual(count, 1)
            self.assertEqual((Path(folder) / "output/b00.jpg").read_bytes(), b"image")
            self.assertIn("https://pixabay.com/photos/1/", (Path(folder) / "credits.txt").read_text())

    def test_pixabay_search_caches_and_preserves_source_page(self):
        from factory import pixabay
        calls = []
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, json={"hits": [{"id": 7, "largeImageURL": "https://cdn.example/photo.jpg",
                                                       "pageURL": "https://pixabay.com/photos/7/"}]})
        with tempfile.TemporaryDirectory() as folder, patch.object(pixabay, "CACHE", Path(folder)), \
                patch("factory.pixabay.httpx.get", side_effect=get):
            first = pixabay.search("hoa sen", "secret", "photos")
            self.assertEqual(pixabay.search("hoa sen", "secret", "photos"), first)
            self.assertEqual(first[0]["page"], "https://pixabay.com/photos/7/")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]["params"]["lang"], "en")
            self.assertNotIn("secret", next(Path(folder).glob("*.json")).read_text())

    def test_api_errors_do_not_expose_key(self):
        from factory import pixabay
        request = httpx.Request("GET", "https://pixabay.com/api/?key=secret")
        with tempfile.TemporaryDirectory() as folder, patch.object(pixabay, "CACHE", Path(folder)), \
                patch("factory.pixabay.httpx.get", return_value=httpx.Response(401, request=request)):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
                pixabay.search("flowers", "secret", "photos")
            self.assertNotIn("secret", str(error.exception))
            self.assertEqual(list(Path(folder).glob("*.json")), [])

    def test_pixabay_video_filters_orientation_and_selects_resolution(self):
        from factory import pixabay
        hit = {"id": 3, "duration": 9, "pageURL": "https://pixabay.com/videos/3/", "videos": {
            "large": {"url": "https://cdn.example/large.mp4", "width": 1920, "height": 1080},
            "small": {"url": "https://cdn.example/small.mp4", "width": 960, "height": 540}}}
        with tempfile.TemporaryDirectory() as folder, patch.object(pixabay, "CACHE", Path(folder)), \
                patch("factory.pixabay.httpx.get", return_value=httpx.Response(200, json={"hits": [hit]})):
            self.assertEqual(pixabay.search("flowers", "test", "videos", "portrait"), [])
            clips = pixabay.search("flowers", "test", "videos", "landscape")
            self.assertEqual(clips[0]["url"], "https://cdn.example/large.mp4")
            self.assertEqual(clips[0]["provider"], "pixabay")

    def test_broll_is_ready_with_pixabay_only(self):
        with patch("factory.config.setting", side_effect=lambda name, default="":
                   {"IMAGE_SOURCE": "pixabay", "PIXABAY_API_KEY": "test"}.get(name, default)):
            self.assertTrue(broll.StockBRoll().check()[0])

    def test_mpt_sentence_clips_support_pixabay_photos(self):
        spec = Spec.model_validate({"id": "test", "title": "Flowers", "image_source": "pixabay",
                                    "stock_terms": ["flowers"],
                                    "scenes": [{"type": "next", "title": "End", "say": "Flowers."}]})
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "photo.jpg"
            photo.write_bytes(b"image")
            with patch.object(beats, "_queries", return_value=["flowers"]), \
                    patch("factory.config.setting", side_effect=lambda name, default="": "test" if name == "PIXABAY_API_KEY" else default), \
                    patch("factory.pixabay.photo", return_value=photo), \
                    patch.object(beats, "_zoom_clip", side_effect=lambda img, duration, out: out.write_bytes(b"clip")):
                clips = beats.sentence_clips(spec, [{"display": "Flowers.", "start": 0, "end": 3}],
                                              3, Path(folder) / "clips", lambda _: None)
            self.assertTrue(clips)
            self.assertEqual(clips[0].read_bytes(), b"clip")

    def test_broll_downloads_use_provider_specific_cache(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(broll, "STOCK", Path(folder)):
            target = Path(folder) / "videos/pixabay-3.mp4"
            target.parent.mkdir()
            target.write_bytes(b"cached")
            self.assertEqual(broll.download({"provider": "pixabay", "id": 3, "url": "unused"}), target)

    def test_broll_readiness_allows_script_specific_provider(self):
        with patch("factory.config.setting", side_effect=lambda name, default="":
                   {"IMAGE_SOURCE": "pexels", "PIXABAY_API_KEY": "test"}.get(name, default)), \
                patch("factory.config.pexels_api_key", return_value=None):
            self.assertTrue(broll.StockBRoll().check()[0])

    def test_mpt_pixabay_with_photos_disabled_uses_video_materials(self):
        from factory.engines import mpt
        spec = Spec.model_validate({"id": "test", "title": "Flowers", "image_source": "pixabay", "images": False,
                                    "stock_terms": ["flowers"],
                                    "scenes": [{"type": "next", "title": "End", "say": "Flowers."}]})
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            video = directory / "clip.mp4"
            video.write_bytes(b"clip")
            with patch.object(mpt, "LOCAL", directory / "local"), \
                    patch("factory.config.setting", return_value="test-key"), \
                    patch.object(broll, "search", return_value=[{"id": 1, "page": "https://pixabay.com/videos/1/"}]), \
                    patch.object(broll, "download", return_value=video), \
                    patch.object(mpt, "synthesize_spec", return_value=(directory / "voice.mp3", [], 1.0)), \
                    patch.object(mpt, "venv_python", return_value=("python",)), \
                    patch.object(mpt, "run", side_effect=mpt.EngineError("stop")):
                with self.assertRaises(mpt.EngineError):
                    mpt.MoneyPrinterTurbo().render(spec, directory, lambda _: None)
            task = json.loads((directory / "mpt-manifest.json").read_text())[0]
            self.assertEqual(task["video_source"], "local")
            self.assertEqual(task["video_materials"][0]["provider"], "local")


if __name__ == "__main__":
    unittest.main()
