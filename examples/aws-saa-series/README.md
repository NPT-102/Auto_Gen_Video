# Series video AWS SAA-C03

31 tập ngắn (~1–1,5 phút, dọc 9:16) tạo bằng [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo).
Trong repo video-factory thư mục này nằm ở `examples/aws-saa-series` và MoneyPrinterTurbo ở
`engines/MoneyPrinterTurbo` (python3 cai-dat.py tự tải) — thay `../MoneyPrinterTurbo` trong các lệnh dưới bằng
`../../engines/MoneyPrinterTurbo`. Tập 5 cũng có bản cho video-factory: `content/aws-saa/ep05.json`.
Kịch bản và từ khoá tìm video nằm trong [`episodes.json`](episodes.json). Đã viết sẵn nên
không cần Gemini, chỉ cần key Pexels.

Nội dung bám đề SAA-C03 (đã đối chiếu exam guide của AWS 27/09/2026): 65 câu (50 tính điểm),
điểm đạt 720/1000, bốn mảng Secure 30% · Resilient 26% · High-Performing 24% · Cost 20%.

| Phần | Tập |
|---|---|
| Mở đầu | 1 Giới thiệu kỳ thi |
| Nền tảng | 2 Region, AZ, Edge Location |
| Bảo mật danh tính | 3 IAM · 4 Cross-account, Organizations, SCP |
| Mạng | 5 VPC, subnet, NAT · 6 Security Group vs NACL · 7 Peering, Transit Gateway, Endpoint · 8 VPN vs Direct Connect |
| Tính toán | 9 EC2 · 10 Cách mua EC2 · 12 ELB và Auto Scaling · 13 Lambda, API Gateway · 14 Container |
| Lưu trữ | 11 EBS, EFS, FSx · 15 S3 cơ bản · 16 Lớp lưu trữ S3 · 17 Bảo mật S3 · 18 Di chuyển dữ liệu |
| Cơ sở dữ liệu | 19 RDS, Aurora · 20 DynamoDB · 21 ElastiCache và DB chuyên dụng |
| Mạng toàn cầu | 22 Route 53 · 23 CloudFront, Global Accelerator |
| Tích hợp, phân tích | 24 SQS, SNS, EventBridge · 25 Kinesis, Athena, Glue |
| Bảo mật dịch vụ | 26 KMS, Secrets Manager · 27 WAF, Shield, GuardDuty… |
| Vận hành, phục hồi, chi phí | 28 CloudWatch, CloudTrail, Config · 29 Disaster Recovery · 30 Tối ưu chi phí |
| Tổng kết | 31 Chiến thuật làm bài |

## Cách 1: tạo hàng loạt (khuyên dùng)

Mở terminal ở thư mục này:

```bash
python3 ../../vf-python.py examples/aws-saa-series/make_series.py 1        # một tập
python3 ../../vf-python.py examples/aws-saa-series/make_series.py 2-10     # nhiều tập
python3 ../../vf-python.py examples/aws-saa-series/make_series.py all      # cả 31 tập
```

Video xong nằm ở `output/Tap-01 - ….mp4`. Mỗi tập mất vài phút. Pexels giới hạn khoảng
200 lượt gọi mỗi giờ, nên chạy `all` thì chia làm vài đợt, ví dụ `1-10`, `11-20`, `21-31`.
Giọng, font, khung hình… đổi ở `SETTINGS` đầu file `make_series.py`.

## Cách 2: làm từng tập trên WebUI

| Ô trên WebUI | Giá trị |
|---|---|
| Chủ đề video | `AWS SAA tập N: <title>` |
| Kịch bản video | dán `script` của tập |
| Từ khoá video | dán `terms`, cách nhau bằng dấu phẩy |
| Tỷ lệ khung hình | Dọc 9:16 |
| Thời lượng tối đa mỗi clip | 4 giây |
| Dịch vụ giọng nói / Giọng | Edge TTS · `vi-VN-HoaiMy` · tốc độ 1.0 |
| Nhạc nền | Không dùng (kho nhạc có sẵn của MoneyPrinterTurbo dính Content ID) |
| Phông chữ phụ đề | `BeVietnamPro-Bold.ttf`, cỡ 60, viền 2 |

Không bấm "Khôi phục cài đặt phụ đề", vì nó đưa font về loại thiếu dấu tiếng Việt.

## Sửa nội dung

Chỉ sửa `episodes.json`: `script` là lời đọc (cũng là phụ đề), `terms` là từ khoá tiếng Anh
để tìm video nền trên Pexels. Viết số và thuật ngữ như muốn thấy trên phụ đề. Tránh ký hiệu
`/ % &` vì giọng đọc có thể đọc sai.
