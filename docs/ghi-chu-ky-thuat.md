# Ghi chú kỹ thuật

Dành cho người muốn sửa hoặc mở rộng hệ thống. Cách cài và cách dùng nằm trong [README](../README.md).

## Kiến trúc

| File | Việc |
|---|---|
| [`factory/app.py`](../factory/app.py), [`factory/web/`](../factory/web/) | Server FastAPI (cổng 8600) và giao diện web |
| [`factory/jobs.py`](../factory/jobs.py) | Hàng đợi job: mỗi engine một tác vụ nền, chạy song song `FACTORY_PARALLEL` engine; *Chọn để đăng* chép sang `publish/<job>/` |
| [`factory/spec.py`](../factory/spec.py) | Định dạng kịch bản chung (pydantic) mà mọi engine cùng đọc |
| [`factory/llm.py`](../factory/llm.py) | Gemini: dàn ý → kịch bản → rà soát, chọn góc nhìn 3 vòng, bản podcast, soát ảnh |
| [`factory/narration.py`](../factory/narration.py) | Edge TTS có mốc từng từ, dòng thời gian cảnh, hiệu ứng âm thanh tự tổng hợp |
| [`factory/beats.py`](../factory/beats.py) | Ảnh theo từng câu / vế câu: Pexels, ComfyUI, Gemini, Wikimedia Commons |
| [`factory/captions.py`](../factory/captions.py) | Phụ đề karaoke (ASS, libass) |
| [`factory/flow.py`](../factory/flow.py) + [`tools/elk`](../tools/elk/) | Cảnh `flow`: sơ đồ tự dàn bố cục bằng ELK |
| [`factory/align.py`](../factory/align.py) | Căn mốc từng chữ cho file giọng làm sẵn bằng faster-whisper (venv của MoneyPrinterTurbo) |
| [`factory/eleven.py`](../factory/eleven.py) | API ElevenLabs (giọng podcast) |
| [`factory/pyrun.py`](../factory/pyrun.py), [`vf-python.cmd`](../vf-python.cmd) | Chạy Python của venv khi Smart App Control chặn launcher |
| [`factory/engines/`](../factory/engines/) | Mỗi engine một lớp `Engine`: `check()` (sẵn sàng chưa) và `render(spec, workdir, log)` trả về `video.mp4` |

Thêm engine mới: viết lớp con của `Engine` trong `factory/engines/`, thêm vào `ENGINES` ở `factory/engines/__init__.py`.
Kết quả mỗi lần tạo nằm ở `runs/<job>/<engine>/` (`video.mp4`, `log.txt`, `credits.txt` nếu có ảnh Commons…).

## Kịch bản chung

Mỗi cảnh có `say` (lời đọc) và phần hình theo loại: `title`, `bullets`, `compare`, `stat`, `flow`, `diagram`, `tip`,
`next`. `cue` là cụm từ trong lời đọc — thành phần tương ứng hiện đúng lúc cụm đó được đọc. Mỗi engine dùng phần nó
hiểu được: MoneyPrinterTurbo lấy lời đọc và `stock_terms`, Pixelle lấy từng câu, AI-auto-generate-video đổi cảnh sang
template của repo.

**`flow` — sơ đồ tự dàn bố cục** ([`factory/flow.py`](../factory/flow.py)): chỉ mô tả nhóm, nút, mũi tên và các bước hiện;
ELK tính toạ độ, sơ đồ dựng dần theo lời đọc, camera zoom vào phần đang giảng rồi lùi ra toàn cảnh. Icon: một emoji
bất kỳ, hoặc `aws:<tên>` (icon AWS chính thức lấy từ gói `diagrams`) — chỉ khi nút đúng là dịch vụ đó
(`spec._check_flow` bắt lỗi khi Gemini lấy icon AWS làm hình trang trí). **`diagram`** là sơ đồ toạ độ soạn tay.

**Stock khớp lời** ([`factory/engines/broll.py`](../factory/engines/broll.py)): MoneyPrinterTurbo tìm clip theo vài từ
khoá chung rồi xếp ngẫu nhiên (chế độ "khớp kịch bản" của nó chỉ xoay vòng từ khoá), nên hình hay lệch lời. Engine này
cho mỗi câu tìm clip bằng từ khoá riêng (trường `stock` của cảnh, Gemini tự viết; thiếu thì chia đều `stock_terms`),
cắt clip vừa khít thời lượng, đổi clip sớm hơn lời 0,35 giây, hiện nhãn, con số, ý chính đúng lúc được đọc. Từ khoá nên
bằng tiếng Anh; tiếng Việt chỉ đúng khi gửi kèm `locale=vi-VN` (engine tự thêm). Clip tải về giữ ở `.cache/stock/`;
nguồn ghi ở `sources.txt` trong thư mục job. Pexels thỉnh thoảng trả 500 với một từ khoá → thử lại rồi dùng từ khoá dự phòng.

## Ảnh theo từng câu ([`factory/beats.py`](../factory/beats.py))

- HyperFrames, Remotion, AI-auto, Pixelle: mỗi câu kể một ảnh nền dọc 1080×1920, đổi đúng lúc câu bắt đầu (sớm hơn lời
  0,35 giây), mờ chuyển và zoom chậm. Cảnh sơ đồ giữ nền sạch. Tắt cho một kịch bản: `"images": false`.
- Gemini đặt từ khoá (Pexels) hoặc viết mô tả cảnh (ComfyUI/Gemini) cho mọi câu trong **một** lần gọi, cache theo nội dung
  câu (`.cache/beats/`) — các engine chạy cùng kịch bản dùng chung một bộ ảnh. Mô tả lặp nhiều quá (dưới 60% khác nhau)
  thì hỏi lại.
- `image_mood` chỉ là ánh sáng / màu cho đồng bộ cả video, không phải chủ thể (bản đầu lấy mood từ `stock_terms` →
  Gemini vẽ "forest canopy looking up" cho cả 16 câu).
- **Hình hiện sớm hơn lời 0,3 giây** (`narration.REVEAL_LEAD`): thành phần hiện đúng lúc đọc thì mắt thấy chậm hơn tai.
- **AI-auto**: repo dựng mỗi template 5 giây rồi đứng hình tới hết lời đọc → engine tạo bản sao tạm của template cho từng
  cảnh (`templates/vf-…`, xoá sau render), kéo dài đúng thời lượng cảnh, lót lớp ảnh (base64 + CSS animation có độ trễ,
  runtime HyperFrames tua theo thời gian) dưới nội dung. Template gốc không bị sửa.
- **Pixelle**: template `image_modern`, ảnh gắn sẵn cho từng khung qua [`pixelle_driver.py`](../factory/engines/pixelle_driver.py)
  (chạy pipeline chuẩn của Pixelle trong venv của nó, bỏ bước viết mô tả ảnh / vẽ ảnh).

### MoneyPrinterTurbo với ảnh tự vẽ / ảnh Commons

Engine tự tạo giọng đọc (Edge TTS, có mốc từng từ) → băm lời theo **vế câu** (dấu phẩy, hai chấm; vế > 4 giây tách thêm
trước "và/nhưng/nên/còn"; vế < 1 giây gộp vào vế sau) → mỗi vế một mô tả cảnh, vế dài thêm cảnh cận/toàn → nhịp đổi
hình ~2,2 giây → dựng sẵn mỗi ảnh thành clip zoom dài đúng vế đó → MoneyPrinterTurbo nhận giọng làm sẵn
(`custom_audio_file`) + các clip (`video_source: local`, `sequential`; clip phải nằm trong
`MoneyPrinterTurbo/storage/local_videos/` — nó chặn tư liệu cục bộ ở chỗ khác) rồi ghép; phụ đề karaoke gắn sau.
Bản đầu (06/10) để MoneyPrinterTurbo tự cắt ảnh theo ô 4 giây và tự đọc giọng → hình lệch lời vài giây.

### SDXL-Lightning

Chạy 4 bước, euler / sgm_uniform, cfg 1 (theo hướng dẫn của ByteDance) nên **không có prompt phủ định** — thử cfg 1,5 +
phủ định cùng seed: vẫn không bỏ được thứ không muốn. Model hay tự vẽ lối mòn khi tả nền rừng / đồng cỏ. Kịch bản đặt
`"image_forbid"` thì Gemini soát cả loạt ảnh sau khi vẽ (một lần gọi, ảnh thu nhỏ): lượt 1 vẽ lại bằng seed khác, lượt
2–3 chuyển cảnh vi phạm sang cận cảnh (đặt "close-up" ở **đầu** mô tả — đặt cuối không có tác dụng). Gemini soát lúc quá
tải hơi thất thường — vẫn nên xem lại ảnh. Ảnh vẽ cache ở `.cache/beats/ai/` theo mô tả + seed.

### Wikimedia Commons

Chỉ có trong `sentence_clips` (engine MoneyPrinterTurbo); `attach` của các engine khác chưa hỗ trợ nguồn `commons` và
`image_forbid` (gặp `commons` thì lấy ảnh Pexels). Gemini đặt truy vấn ngắn + người phải có trong **tên** ảnh + năm sự kiện; lọc năm chụp ±1, xếp theo độ khớp tên, Gemini
duyệt thêm (từng lô 10 ảnh). Chỉ nhận giấy phép tự do (tài sản công, CC0, CC BY, CC BY-SA); `credits.txt` ghi tác giả +
giấy phép, tự nối vào caption khi chọn bản. Tự động đúng khoảng 85–90% → video thật nên ghim tay `image_pins`.
Wikimedia giới hạn tần suất (429): giãn cách ≥ 1 giây, chỉ xin ảnh thu nhỏ cỡ chuẩn 1280 px (cỡ khác hay bị 429); lấy
không đủ ảnh thì job **báo lỗi** chứ không lùi về clip Pexels (clip Pexels sẽ sai người, sai sự kiện).

## Bản podcast (chỉ MoneyPrinterTurbo)

Chủ đề tâm lý, tình yêu hợp kiểu **podcast tâm sự**: các video top TikTok dùng văn nói xưng "mình", tiếng đệm, một ý
cảm xúc, nói ~210 tiếng/phút, ngắt nghỉ ngắn, nhạc piano nhẹ. Chất podcast đến từ văn nói, không phải từ giọng chậm.
Nguồn giọng theo thứ tự: file giọng làm sẵn (`podcast.audio`, Whisper căn mốc từng chữ — lệch trung vị ~25 ms) → API
ElevenLabs (model `eleven_flash_v2_5`, model hiện hành duy nhất đọc tiếng Việt; gói Free bị API từ chối giọng thư viện,
HTTP 402) → giọng Edge mặc định. Không tự động bấm trên web ElevenLabs thay người dùng: điều khoản của họ cấm công cụ
tự động và lách giới hạn gói — web chỉ chép sẵn lời, mở trang và canh thư mục Downloads nhận file mp3.

## Âm thanh

HyperFrames và Remotion tự thêm hiệu ứng **pop** (thành phần hiện ra) và **whoosh** (chuyển cảnh), tổng hợp bằng ffmpeg
nên không vướng bản quyền. MoneyPrinterTurbo xuất giọng nhỏ (~-22,6 LUFS) → engine chuẩn hoá về -14 LUFS.
**Không dùng kho nhạc có sẵn của MoneyPrinterTurbo** (`resource/songs`, 29 bản không rõ nguồn): ngày 28/09/2026 một bản
("Relaxing Peaceful Piano…") bị Content ID nhận, YouTube chặn Short toàn cầu (Short dài hơn 1 phút có bất kỳ thông báo
bản quyền nào đều bị chặn). Nhạc chỉ lấy từ `assets/music/` (bản podcast ưu tiên `assets/music/podcast/`) do người dùng
tự bỏ vào, tự hạ âm lượng khi có giọng.

## Gemini miễn phí

Gói miễn phí hay quá tải (503) và giới hạn theo phút/ngày (429). Hệ thống tự chờ đúng thời gian Google yêu cầu, phân biệt
hết hạn mức theo phút (chờ) với theo ngày (đổi model), tự chuyển model dự phòng
(`gemini-flash-latest` → 3.7 → 3.5 → flash-lite); một nháp thường mất 1–3 phút. Rà soát bằng Google Search có hạn mức
riêng, hết thì rà soát bằng kiến thức của model. Nháp có thể sai kiến thức — luôn đọc lại trước khi tạo video.

## Từng engine

- **HyperFrames**: `template.html` sinh từ template studio của series AWS (`examples/aws-saa-series/studio`) bằng
  `engines/hyperframes-academic/build_template.py`; trang đăng ký `window.__timelines.main` bọc quanh `renderAt(t)` nên
  HyperFrames tua được từng khung. Dùng Chrome cài sẵn (`HYPERFRAMES_BROWSER_PATH`) — bản headless-shell hay crash
  trên Windows. Tắt telemetry bằng `HYPERFRAMES_NO_TELEMETRY`.
- **AI-auto-generate-video**: repo chỉ gọi OmniVoice (`POST /tts`) → engine dựng server giả lập dùng Edge TTS. Repo
  không gắn phụ đề → engine gắn phụ đề karaoke bằng ffmpeg/libass. Template gắn cứng thương hiệu tác giả
  ("Senior AI Engineer", "Bản tin") → `neutralize_branding()` ẩn đi trong bản clone (vì vậy `git status` của repo đó
  báo 2 file modified — bình thường).
- **Pixelle-Video**: chế độ `fixed` + tiêu đề có sẵn + ảnh gắn sẵn ⇒ không gọi LLM/model ảnh, không cần server API.
  Không có ảnh thì dùng template `static_factory.html` (tự sinh từ `static_default`, bỏ nhãn "Text-Only Template").
  Pixelle đọc nhanh 1,2 lần (mặc định `tts_speed` của pipeline) nên video ngắn hơn các bản kia.
  Trả video ở `output/<mã pipeline>/`.
- **Remotion**: giấy phép miễn phí cho cá nhân và công ty ≤ 3 người; công ty lớn hơn phải mua license. Engine cho Remotion
  chỉ xuất khung hình JPEG (`--sequence`, không kèm `<Audio>`) rồi ffmpeg của hệ thống ghép video và gắn giọng — vì Smart
  App Control chặn `avfilter-10.dll` của ffmpeg đi kèm Remotion (mã 3236495362 = 0xC0E90002).
- **MoneyPrinterTurbo**: chạy `cli.py --batch-file` (chế độ batch) trong venv của nó. Font phụ đề mặc định (YaHei) thiếu
  dấu tiếng Việt → `BeVietnamPro-Bold.ttf`. `edge_tts_timeout` mặc định 30 giây là tổng cho cả bài → nâng lên 120.
  Web của MoneyPrinterTurbo ghi đè `config.toml` (xoá chú thích) mỗi lần bấm lưu.

## Smart App Control (Windows 11)

Smart App Control ở chế độ bật chặn dần các file thực thi không ký số mà nó chưa "quen". Đã gặp trên máy dựng hệ thống:

| Ngày | Bị chặn | Cách xử lý trong repo |
|---|---|---|
| 28/09/2026 | Python tạm của uv khi build gói từ mã nguồn (moviepy 1.0.3 của Pixelle) | `uv sync --no-build-isolation-package moviepy` (build ngay trong `.venv`) |
| 01/10/2026 | `avfilter-10.dll` của ffmpeg đi kèm Remotion | Remotion chỉ xuất khung hình, ffmpeg hệ thống ghép |
| 06/10/2026 | `.venv\Scripts\uvicorn.exe` | gọi `python -m uvicorn` |
| 07/10/2026 | `.venv\Scripts\python.exe` của MoneyPrinterTurbo | [`factory/pyrun.py`](../factory/pyrun.py): chạy Python gốc + thư viện của venv |
| 09/10/2026 | `.venv\Scripts\python.exe` của web và Pixelle (cùng một file launcher của uv) | [`vf-python.cmd`](../vf-python.cmd) tự chuyển sang Python gốc |
| 09/10/2026 | `torch_cpu.dll` của PyTorch trong ComfyUI portable (05–07/10 còn chạy) | **Không né được** — thư viện bắt buộc, không có bản ký số. Tắt Smart App Control (quyết định của chủ máy), hoặc chạy ComfyUI ở WSL2 / máy khác và trỏ `COMFYUI_URL` tới đó |

Python gốc do uv cài (`%APPDATA%\uv\python\cpython-3.x…\python.exe`), Node.js, ffmpeg của Gyan, Chrome, Python nhúng
của ComfyUI đều có chữ ký số nên vẫn chạy. Ngoài PyTorch của ComfyUI, không cần tắt Smart App Control. Smart App
Control quyết định theo chữ ký số và độ tin cậy trên đám mây của từng file, nên một file chạy được hôm nay có thể bị
chặn vài hôm sau. Không chép file bị chặn sang chỗ khác để chạy lại — đó là lách cơ chế bảo vệ. Xem lý do bị chặn: Event Viewer →
Applications and Services Logs → Microsoft → Windows → CodeIntegrity → Operational.

## Đã thử nhưng không dùng

- Gemini vẽ ảnh: gói miễn phí không có hạn mức vẽ ảnh (cần bật thanh toán, ~0,04 USD/ảnh).
- Ảnh AI cho người có thật: ảnh chỉ "giống", dễ bị hiểu nhầm là ảnh thật → dùng Wikimedia Commons.
- Nhân bản giọng người thật (giọng của một podcaster nổi tiếng): không làm — dùng giọng tổng hợp trong thư viện ElevenLabs.
- Tự động bấm trên web ElevenLabs để né giới hạn gói Free: trái điều khoản → bán tự động (chép lời, canh Downloads).
