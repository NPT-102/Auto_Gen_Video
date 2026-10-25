# Engine Whiteboard — video bàn tay cầm bút vẽ

Một bàn tay cầm bút dạ vẽ từng hình lên bảng trắng, đúng lúc lời đọc nhắc tới. Bút đi theo từng nét: vẽ viền trước,
tô màu sau, chữ viết từng dòng và từng chữ cái từ trái sang phải. Vẽ xong một hình, tay lướt sang hình kế tiếp. Hết
một ý thì bảng lia sang trang mới. Âm thanh chỉ có giọng đọc (và nhạc nền nếu có trong `assets/music`).

## Chạy thử

```bash
python cai-dat.py                                                              # cài cả bộ vẽ engines/whiteboard-lab
python -m factory.try_engine whiteboard content/demo/whiteboard-timed-pages.json
python -m factory.try_engine whiteboard content/demo/whiteboard-2fa.json
```

Video ra ở `.cache/try/whiteboard/video.mp4`. Mỗi video ~35 giây mất khoảng 3–5 phút trên máy Windows CPU 32 luồng
(phần lớn là Remotion render khung hình). Trên web: tick engine **Whiteboard** như các engine khác.

## Kịch bản

Kịch bản thường có thêm trường `whiteboard_plan`, mỗi cảnh (theo thứ tự `scenes`) một mục:

```json
"whiteboard_plan": [
  {"page": 1, "objects": [
    {"kind": "text", "text": "MỘT MẬT KHẨU", "x": 0.10, "y": 0.13, "scale": 0.62, "at": 0.05},
    {"kind": "person", "x": 0.12, "y": 0.37, "scale": 1.12, "at": 0.25},
    {"kind": "lock", "x": 0.62, "y": 0.37, "scale": 1.16, "color": "orange", "at": 0.48},
    {"kind": "arrow", "x": 0.37, "y": 0.56, "to_x": 0.60, "to_y": 0.56, "color": "orange", "at": 0.66}
  ]}
]
```

| Trường | Ý nghĩa |
|---|---|
| `kind` | phone, laptop, lock, shield, warning, code, checklist, arrow, star, bulb, chart, coin, cloud, server, text, stat, formula, person, books, document, explosion, atom |
| `x`, `y` | Góc trên-trái của hình, 0–1 theo khung 1080×1920 (mũi tên: điểm đầu; `to_x`, `to_y`: điểm cuối) |
| `scale` | Cỡ hình (chữ: `scale` 0,6 ≈ 67 px) |
| `color` | blue, orange, green, red, pink hoặc mã màu |
| `text`, `label`, `value` | Chữ của `text` / `stat` / `formula`; nhãn dưới số của `stat`; dãy số của `code` |
| `checked`, `broken` | Khiên có dấu tích; ổ khoá bị phá |
| `at` | Lúc bắt đầu vẽ: 0–1 là phần của cảnh, lớn hơn 1 là giây. Không có thì vẽ lần lượt |
| `page` | Các cảnh liên tiếp cùng `page` vẽ tiếp trên cùng một bảng; đổi `page` thì sang bảng mới |

Không cần đặt toạ độ thật khéo. Mỗi trang được tự co giãn và đặt giữa vùng an toàn của khung dọc, phóng tối đa 1,5
lần. Hình đè lên hình trước thì được đẩy sang chỗ trống gần nhất. Hình tràn ra ngoài mép thì cả trang được thu lại.
Gemini tự viết `whiteboard_plan` khi viết nháp. Không có trường này thì `factory/whiteboard_planner.py` chọn hình theo
nội dung câu.

Tuỳ chọn khác: `whiteboard_captions: true` (phụ đề), `whiteboard_header: true` (thanh tiến độ và tên series).

## Cách hoạt động

```
kịch bản ──► tools/render_whiteboard_plan.py ──► mỗi hình một lớp PNG (nền giấy + bản trong suốt .rgba.png)
                                                    │
                    engines/whiteboard-lab ◄────────┘  (python -m lab.module, mỗi lớp một lần)
                    khung PNG trong suốt + đường đầu bút từng khung
                                                    │
                    engines/remotion-whiteboard ◄───┘  xếp lớp theo trang, vẽ bàn tay theo đường bút, lật trang
                                                    │
                    ffmpeg: khung hình + giọng đọc ──► video.mp4
```

### Bộ vẽ (`engines/whiteboard-lab`)

1. **Tách nét và mảng tô theo độ dày.** Phần mảnh (viền mực, chữ, mũi tên màu) là nét. Phần dày là mảng tô.
2. **Làm mảnh nét thành đường xương** (OpenCV thinning) rồi cho đầu bút đi dọc đường xương. Mỗi điểm ảnh của nét hiện ra
   đúng lúc đầu bút đi qua điểm xương gần nó nhất, nên nét lộ ra như được kéo bằng bút.
3. **Thứ tự như người viết:**
   - Chữ viết từng dòng, trên trước dưới sau ("XÁC THỰC" xong mới xuống "HAI LỚP"). Trong dòng, từng chữ cái từ trái
     sang phải; dấu thanh, dấu chấm, dấu móc viết ngay sau chữ cái của nó.
   - Hình vẽ theo thứ tự đọc: các mảng rời xếp thành hàng, hàng trên trước, trong hàng mảng bên trái trước (dãy ô
     8-4-2-1 vẽ từ ô số 8, ổ khoá vẽ quai rồi tới thân).
4. **Nhịp tay người:** nhanh trên đoạn thẳng, chậm tới 0,4 lần ở góc ngoặt, tăng tốc đầu nét và hãm cuối nét. Nhấc bút
   giữa hai chữ cái chỉ ~0,03 giây. Cả hình được co giãn (0,75–1,7 lần) để lấp khoảng thời gian dành cho nó.
5. **Tô màu** bằng vệt quét zig-zag sau khi vẽ xong nét. Mảng trắng (lòng ô, màn hình) hiện ngay khi viền khép lại.

Dòng lệnh giữ đúng giao diện của Whiteboard Lab gốc (`--image`, `--output`, `--duration`, `--mode`,
`--split-objects`) và có thêm ba tuỳ chọn, khai báo trong `lab/capabilities.json`:

- `--frames-dir`: khung PNG trong suốt, chỉ có nét vẽ, không có bàn tay;
- `--pen-json`: vị trí đầu bút từng khung `[x, y, trạng thái]` (0 nhấc bút, 1 vẽ nét, 2 tô màu);
- `--natural`: vẽ theo tốc độ tay, tối đa bằng `--duration`.

Thêm `--order writing` thì lớp được vẽ như chữ viết. Engine tự đặt tuỳ chọn này cho các hình text, stat, formula.

`factory/config.py` chọn bộ vẽ theo thứ tự: `WHITEBOARD_LAB_DIR` → thư mục `whiteboard-lab` nằm cạnh repo (Lab gốc) →
`engines/whiteboard-lab`. Với Lab gốc (không có `capabilities.json`), engine chạy như trước: clip MP4 có bàn tay, tách
nền thành khung trong suốt.

### Bàn tay

`assets/whiteboard/hand-marker.svg` là bàn tay phải cầm bút kiểu ba ngón, vẽ bằng vector nên không vướng bản quyền.
`tools/whiteboard_hand.py` xuất SVG thành PNG trong suốt bằng Chrome, ghi toạ độ đầu bút vào `hand-marker.json`. Script
cũng chép cả hai file sang `engines/whiteboard-lab/lab/` và `engines/remotion-whiteboard/public/whiteboard/`. Muốn
thay bằng ảnh tay khác: PNG nền trong suốt khoảng 900×900, sửa `tip` trong `hand-marker.json` cho đúng đầu bút.

Trong Remotion (`src/Academic.tsx`), mỗi trang có **một** bàn tay đi theo đường bút của từng lớp:

- vẽ xong một hình mà hình sau tới trong vòng 1,6 giây thì tay lướt thẳng sang;
- phải chờ lâu hơn thì tay rời khung về góc dưới bên phải, rồi quay lại đúng lúc vẽ tiếp;
- nhấc bút giữa các nét thì tay nhích lên một chút, làm mượt qua 5 khung để không rung;
- đổi trang thì bảng cũ trượt ra trái, bảng mới trượt vào từ phải trong 0,45 giây.

## Thay đổi so với nhánh `feat/whiteboard-video-engine`

Nhánh gốc gọi Whiteboard Lab, một project riêng không có trên GitHub, nên không dựng ra video được trên máy khác.
Nhánh này đóng gói bộ vẽ vào repo và sửa những chỗ thấy được khi xem video:

| Phần | Trước | Sau |
|---|---|---|
| Bộ vẽ | Cần Whiteboard Lab ở `../whiteboard-lab` (không có trên GitHub) | `engines/whiteboard-lab` trong repo, `cai-dat.py` tự cài; Lab gốc vẫn được ưu tiên nếu có |
| Clip vẽ | MP4 nền giấy, tách nền theo màu ra khung trong suốt; mảng trắng trong hình bị trong suốt | Khung PNG trong suốt vẽ thẳng từ lớp `.rgba.png`, giữ nguyên mảng trắng |
| Bàn tay | Nằm trong từng clip, hiện / mất theo từng hình | Một bàn tay vector cho cả trang, lướt giữa các hình, rời khung khi chờ lâu |
| Thứ tự nét | Theo Lab gốc | Chữ theo dòng → chữ cái → dấu; hình theo thứ tự đọc; nhịp tay nhanh – chậm như người |
| Tốc độ | Mỗi hình kéo dài cho hết khoảng thời gian của nó | Tốc độ tay thật, co giãn vừa phải để không phải chờ lâu |
| Bố cục | Đúng toạ độ trong kịch bản, có hình tràn mép (chữ "BỊ LỘ?" ở y = 0,99) | Tự co giãn, căn giữa từng trang, tự tách hình đè nhau |
| Chữ | 51 px ở `scale` 0,62; xuống dòng để lẻ một chữ | ~67 px; xuống dòng cân ("XÁC THỰC / HAI LỚP") |
| Mũi tên chéo | Đầu mũi tên ngang / dọc nên thành dấu ">" | Đầu mũi tên theo đúng hướng thân |
| Nét bút | Đầu nét vuông | Đầu nét bo tròn như bút dạ |
| Đổi trang | Xoá trắng trong một khung hình | Bảng cũ trượt ra, bảng mới trượt vào |
| Âm thanh | Tiếng pop / whoosh của template, lệch với hình đang vẽ | Chỉ giọng đọc |
| Nền | Màu phẳng | Hơi tối dần ra mép, cho có chiều sâu |

File chính: `engines/whiteboard-lab/lab/module.py` (mới), `assets/whiteboard/` và `tools/whiteboard_hand.py` (mới),
`tools/render_whiteboard_plan.py`, `tools/make_transparent_layer.py`, `factory/engines/whiteboard.py`,
`factory/config.py`, `engines/remotion-whiteboard/src/Academic.tsx`, `src/lib.tsx`, `setup/install.py`, `.gitignore`.

## Giới hạn

- Bàn tay là hình minh hoạ phẳng, không phải ảnh tay thật.
- Engine render Remotion với nhiều tab Chrome (`WHITEBOARD_CONCURRENCY`, mặc định theo số nhân CPU), nhưng trên máy thử
  chưa thấy nhanh hơn rõ; nút thắt có lẽ ở khâu nạp ảnh PNG từng khung.
- Hai test trong `tests/test_linux.py` (`test_engine_python_paths_are_linux_paths`,
  `test_posix_venv_runs_with_its_own_packages`) lỗi trên Windows, giống hệt trên nhánh gốc.
