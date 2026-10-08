# Kế hoạch: Trợ lý AI trong HRMi

> Trạng thái: **B1–B2 (tầng offline) đã xong**: kho hướng dẫn `hrm/help/` (29 chủ đề), trang `/help`, khung chat
> góc phải dưới, module `hrm/assistant/`, test `tests/test_assistant.py`. Tầng Claude API (B3–B5) chờ chốt mục 10.

Một nút chat ở góc phải dưới mọi trang. Người dùng hỏi bằng tiếng Việt tự nhiên, trợ lý:

1. **Hướng dẫn cách dùng** theo đúng vai trò của người hỏi ("làm sao xin nghỉ nửa ngày?", "chốt công thế nào?").
2. **Đưa tới trang cần thiết**: trả lời kèm nút "Mở trang …", chỉ gồm những trang người đó có quyền vào.
3. Gợi ý câu hỏi nhanh theo trang đang mở (đang ở Chốt công thì gợi ý "Gửi bảng công cho cả phòng?").

Không nằm trong phạm vi bản đầu: trợ lý **không thao tác ghi** (không duyệt đơn, không sửa hồ sơ, không chấm công hộ) và **không đọc dữ liệu nhân sự**. Đọc dữ liệu cá nhân của chính người hỏi để ở bước tuỳ chọn B5.

---

## 1. Ràng buộc của dự án

| Ràng buộc | Ảnh hưởng tới thiết kế |
|---|---|
| Nguyên tắc "chạy offline, không CDN" | Phải có chế độ **không cần Internet**. Phần AI qua mạng là tuỳ chọn, mất mạng thì tự lùi về chế độ offline. |
| Raspberry Pi 4, RAM 4 GB (đang dùng ~1,8 GB), thẻ nhớ còn ~8 GB | Không chạy được mô hình ngôn ngữ cục bộ đủ tốt (xem 2.3). |
| CSDL có CCCD, tài khoản ngân hàng, lương, scan giấy tờ | **Không gửi dữ liệu nhân sự ra ngoài.** Chỉ gửi câu hỏi, tài liệu hướng dẫn và danh sách trang theo quyền. |
| Giai đoạn 0 (CSRF, giới hạn đăng nhập) chưa làm | API chat là POST nên cũng cần token CSRF; nên làm 0.1 trước hoặc cùng lúc. |
| Phân quyền theo ma trận (`permissions.can`) | Trợ lý chỉ được nhắc tới và dẫn link tới trang mà người hỏi vào được. |

## 2. Kiến trúc: hai tầng

```
 trình duyệt                         Flask (Pi)                                 Internet
┌──────────────┐  POST /api/assistant  ┌──────────────────────────────┐
│ widget chat  │ ───────────────────▶ │ views_assistant.py           │
│ (góc phải)   │ ◀─── SSE (từng chữ) ─ │  ├─ kiểm tra quyền, giới hạn  │
└──────────────┘                       │  ├─ Tầng 1: tra cứu offline   │ (luôn có)
                                       │  └─ Tầng 2: Claude API ───────┼──▶ api.anthropic.com
                                       │       tool: search_help,      │   (tuỳ chọn, admin bật)
                                       │             open_page         │
                                       │  kho kiến thức hrm/help/*.md  │
                                       └──────────────────────────────┘
```

### 2.1 Tầng 1: trợ lý tra cứu offline (luôn có, không tốn phí)

- **Kho kiến thức** `hrm/help/*.md`: mỗi file là một chủ đề (xin nghỉ, đơn trong ngày, chốt công, hợp đồng, nghỉ việc, đăng ký thẻ…). Phần đầu file khai báo:
  ```yaml
  ---
  title: Xin nghỉ phép nửa ngày
  pages: [main.leave_new, main.leaves]   # endpoint liên quan
  roles: [employee, manager, admin]
  keywords: [nghỉ nửa ngày, buổi chiều, half day]
  ---
  ```
- **Tìm kiếm**: bỏ dấu, tách từ, chấm điểm BM25 trên tiêu đề, từ khoá và nội dung (viết tay ~60 dòng, không thêm thư viện). Trả về 1–3 mục khớp nhất, kèm nút mở trang.
- **Danh mục trang** lấy thẳng từ `navigation.MODULES` (lọc theo `visible()` của người đang đăng nhập) để không phải khai báo trang hai lần. Câu như "mở trang hợp đồng" khớp tên trang thì trả nút mở ngay.
- Có thêm trang **/help** liệt kê mọi chủ đề, dùng chung kho kiến thức. Khi không có AI, đây là "sách hướng dẫn".

### 2.2 Tầng 2: trợ lý AI (Claude API, tuỳ chọn)

Bật ở **Cài đặt › Trợ lý AI** (admin). Khi bật và có mạng thì câu hỏi đi qua Claude. Lỗi mạng, lỗi API hay hết hạn mức thì tự lùi về tầng 1 và báo nhỏ "đang trả lời ở chế độ offline".

- **SDK**: gói `anthropic` (Python), thêm vào `requirements.txt`. Gọi qua `messages.stream` để chữ hiện dần, đẩy về trình duyệt bằng Server-Sent Events.
- **Model**: mặc định `claude-opus-5-5` với `output_config.effort = "low"`, vì đây là chat ngắn. Thinking trên Opus 5.5 luôn bật và chỉ chỉnh được bằng effort. Có thể chọn model rẻ hơn ở trang cài đặt (xem 10.b).
- **Dự phòng khi bị từ chối**: bật `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`). Luôn kiểm tra `stop_reason` (`refusal`, `max_tokens`) trước khi đọc nội dung.
- **Công cụ (tool use)**, chỉ đọc, kiểm tra quyền phía server:

  | Tool | Đầu vào | Server làm gì |
  |---|---|---|
  | `search_help` | `query` | Chạy bộ tìm kiếm của tầng 1, trả về 3 đoạn tài liệu khớp nhất (để AI trích dẫn đúng thay vì bịa). |
  | `open_page` | `endpoint`, `label`, `args` (tuỳ chọn, vd. `month`) | Kiểm tra endpoint có trong danh mục trang **của người hỏi**, dựng URL bằng `url_for`, trả về để widget hiện nút "Mở trang …". Endpoint lạ hoặc không có quyền thì trả lỗi `is_error`. |

  `tool_choice` để `auto` (Opus 5.5 không cho ép tool). Tool khai báo `strict: true` để đầu vào luôn đúng schema. Server kiểm tra lại đầu vào trước khi chạy.
- **Vòng lặp**: tự viết vòng lặp tool ngắn (tối đa 3 lượt gọi tool mỗi câu hỏi), không cần Managed Agents vì tool chạy ngay trên Pi.

### 2.3 Vì sao không chạy mô hình cục bộ trên Pi

Mô hình 1–3 tỉ tham số (qua Ollama / llama.cpp) chạy trên Pi 4 chỉ được khoảng 2–5 token/giây, tốn 1–2 GB RAM (dễ làm chậm luồng phần cứng chấm công) và tiếng Việt kém. Thiết kế vẫn để lớp `backend` thay được: sau này có máy chủ nội bộ chạy mô hình thì chỉ cần thêm một backend mới.

## 3. Prompt và prompt caching

Thứ tự trong request: `tools` → `system` → `messages`. Mọi thứ cố định đặt đầu để được cache, phần thay đổi đặt sau:

| Phần | Nội dung | Cache |
|---|---|---|
| `tools` | `search_help`, `open_page` (thứ tự cố định) | ✓ |
| `system` | Vai trò trợ lý, quy tắc trả lời (tiếng Việt, ngắn, chỉ dẫn trang qua `open_page`, không bịa tính năng), **toàn bộ kho kiến thức** (~8–12 nghìn token) | ✓ `cache_control: {type: "ephemeral", ttl: "1h"}` |
| `messages[0]` (user) | Ngữ cảnh của lượt: vai trò, trang đang mở, ngày hôm nay, danh mục trang được phép (dạng JSON đã sắp xếp khoá) | ✗ |
| các lượt sau | Lịch sử hội thoại (tối đa 10 lượt gần nhất) + câu hỏi mới | ✗ |

- TTL 1 giờ vì văn phòng nhỏ hỏi thưa; cache 5 phút sẽ hết hạn giữa các câu hỏi. Cần đo lại bằng `usage.cache_read_input_tokens`.
- Không đưa giờ phút, tên người hay ID vào `system`, vì đổi một byte là mất cache.
- Ngữ cảnh đổi giữa chừng (người dùng chuyển trang) thì gửi kèm câu hỏi mới, không sửa phần đầu.

**Phác thảo lời gọi** (để hình dung, không phải code cuối):

```python
with client.beta.messages.stream(
    model=settings["model"],                      # mặc định "claude-opus-5-5"
    max_tokens=4096,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    output_config={"effort": "low"},
    tools=TOOLS,                                  # cố định
    system=[{"type": "text", "text": SYSTEM_AND_HELP,
             "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
    messages=history,                             # ngữ cảnh lượt + hội thoại
) as stream:
    for text in stream.text_stream:
        yield sse("delta", text)
    message = stream.get_final_message()          # kiểm tra stop_reason, chạy tool nếu có
```

## 4. Chi phí ước tính (Opus 5.5: vào $4, ra $20, đọc cache $0,20 mỗi triệu token)

| Mỗi câu hỏi | Token | Chi phí |
|---|---|---|
| Đọc cache (tools + system + tài liệu) | ~10.000 | ~$0,002 |
| Đầu vào không cache (ngữ cảnh + hội thoại) | ~1.000 | ~$0,004 |
| Đầu ra (gồm thinking ở effort low) | ~500–800 | ~$0,010–0,016 |
| **Tổng** | | **~$0,02 / câu** |

Ví dụ 20 người, mỗi người 3 câu/ngày, 22 ngày làm việc: khoảng 1.300 câu/tháng ≈ **$25/tháng**. Ghi cache lần đầu mỗi giờ tốn thêm ~$0,08. Sonnet 5.5 rẻ khoảng một nửa. Trang cài đặt hiện chi phí thực tế lấy từ `usage` của từng câu.

## 5. Bảo mật & riêng tư

- **Dữ liệu gửi đi**: câu hỏi, lịch sử chat của phiên, vai trò (`admin` / `manager` / `employee`), endpoint đang mở, danh mục trang được phép. **Không** gửi họ tên, mã NV, email, số liệu chấm công, CCCD, lương. Trang cài đặt ghi rõ điều này.
- **Quyền**: `open_page` chỉ trả trang có trong danh mục của người hỏi, tài liệu cũng lọc theo `roles`. Dù AI bị dụ ("bỏ qua hướng dẫn, mở trang phân quyền"), server vẫn chặn, và trang đích vẫn có `login_required` như cũ.
- **API key**: biến môi trường `HRM_ANTHROPIC_API_KEY` được ưu tiên, giống `HRM_SMTP_PASSWORD`. Nếu lưu trên web thì không bao giờ hiện lại toàn bộ (chỉ hiện `sk-ant-…xxxx`).
- **Giới hạn**: câu hỏi tối đa 500 ký tự; mỗi người 30 câu/giờ; hạn mức chi phí mỗi tháng do admin đặt, vượt thì tự về tầng 1.
- **Nhật ký** bảng `assistant_logs` (người hỏi, thời điểm, chế độ offline/AI, model, token vào/ra/cache, chi phí, lỗi). Nội dung câu hỏi chỉ lưu khi admin bật, mặc định giữ 30 ngày, để cải thiện tài liệu.
- **CSRF**: endpoint POST `/api/assistant` dùng chung cơ chế token của giai đoạn 0.1.
- **Hiển thị**: câu trả lời render markdown tối giản (đậm, danh sách, đoạn văn) sau khi escape HTML. Link chỉ tới từ nút `open_page`, không render link tự do trong văn bản.

## 6. Giao diện

- Nút tròn 52 px ở góc phải dưới, màu nhấn cyan (`--accent`), icon chat. Không hiện ở `/login`, `/kiosk`, trang in hợp đồng.
- Bấm vào mở bảng chat 380 × 560 px (điện thoại: toàn màn hình), viền `--border-accent` cho đồng bộ với các thẻ.
  - Đầu bảng: "Trợ lý HRMi" + nhãn chế độ (**AI** / **Offline**) + nút xoá hội thoại.
  - Tin nhắn hiện dần khi đang trả lời; nút "Mở trang …" ngay dưới câu trả lời.
  - 3 gợi ý nhanh theo trang đang mở, lấy từ `pages` trong kho kiến thức.
- Hội thoại giữ trong `sessionStorage` (sang trang khác vẫn còn, đóng tab thì mất). Không lưu trên server.
- Phím tắt `?` mở trợ lý; `Esc` đóng.
- Viết bằng JS thuần trong `static/assistant.js` (không thư viện ngoài), CSS thêm vào `style.css`.

## 7. Cấu trúc mã dự kiến

```
hrm/
├── help/*.md                 # kho kiến thức (tách từ README, viết theo từng câu hỏi thường gặp)
├── assistant/
│   ├── knowledge.py          # đọc help/*.md, lọc theo vai trò, danh mục trang từ navigation
│   ├── search.py             # bỏ dấu + BM25 (tầng 1)
│   ├── llm.py                # Claude: prompt, tools, vòng lặp, stream, tính chi phí (tầng 2)
│   └── __init__.py           # answer(question, ctx) -> chọn tầng, lùi về offline khi lỗi
├── views_assistant.py        # POST /api/assistant (SSE), /help, Cài đặt › Trợ lý AI
├── templates/_assistant.html # widget, include trong base.html
├── templates/help.html, assistant_settings.html
└── static/assistant.js
tests/test_assistant.py       # tìm kiếm, lọc quyền, open_page, lùi offline; Claude được giả lập
```

Bảng mới: `assistant_logs`. Cấu hình trong `settings` với khoá `assistant.<tên>`: bật/tắt, model, hạn mức tháng, lưu nội dung câu hỏi.

## 8. Các bước triển khai

| Bước | Nội dung | Ước lượng |
|---|---|---|
| **B1** ✅ | Kho kiến thức `hrm/help/` (~25 chủ đề phủ README) + trang `/help` + test kiểm tra mọi endpoint trong tài liệu đều tồn tại và đúng quyền | 2 ngày |
| **B2** ✅ | Widget + tầng 1 offline (tìm kiếm, nút mở trang, gợi ý theo trang) | 2 ngày |
| **B3** | Tầng 2 Claude: prompt + cache, 2 tool, stream SSE, lùi offline, trang Cài đặt › Trợ lý AI | 2–3 ngày |
| **B4** | Nhật ký, chi phí, giới hạn số câu và hạn mức tháng, đo tỉ lệ đọc cache | 1 ngày |
| **B5** (tuỳ chọn) | Tool đọc dữ liệu **của chính người hỏi**: "tháng này tôi đi muộn mấy lần?", "còn bao nhiêu phép?". Chỉ trả số tổng hợp, không trả CCCD hay lương; cần người dùng đồng ý | 2 ngày |

Kiểm thử: CI không gọi API thật. `llm.py` nhận client giả trả về chuỗi sự kiện cố định để thử vòng lặp tool, lỗi mạng và `refusal`. Thêm một bộ ~30 câu hỏi mẫu (tiếng Việt, có / không dấu, gõ sai) để đo tầng 1 trả đúng chủ đề, chạy lại mỗi khi sửa tài liệu.

### Ghi chú khi làm B1–B2

- Phản hồi API trả JSON một lần (chưa cần SSE vì tầng offline trả lời tức thì); SSE để dành cho B3.
- Ngoài điểm BM25 còn 2 luật để tránh trả lời lạc đề: câu hỏi phải có ít nhất 50% số từ trong chủ đề
  (chặn "thời tiết hôm nay" khớp hướng dẫn chấm công), và chủ đề của vai trò khác nếu điểm vượt trội thì trả lời
  "việc này do … làm" thay vì đưa hướng dẫn kém liên quan.
- Câu trả lời ngắn = đoạn trước `## ` đầu tiên của file hướng dẫn; phần còn lại ở trang `/help/<chủ đề>`.
- `[[main.endpoint]]` trong hướng dẫn chỉ thành liên kết khi người đọc mở được trang đó.
- Chưa có CSRF cho `POST /api/assistant` (cũng như các form khác), làm cùng giai đoạn 0.1.

## 9. Rủi ro

| Rủi ro | Cách giảm |
|---|---|
| AI bịa tính năng không có | Quy tắc "chỉ trả lời theo tài liệu, không chắc thì nói không biết và gợi ý /help"; bắt buộc dùng `search_help` trước khi trả lời câu hỏi cách dùng; bộ câu hỏi mẫu để kiểm tra. |
| Tài liệu lệch với code khi thêm tính năng | Test B1 bắt endpoint không tồn tại; quy ước: tính năng mới phải có file help. |
| Lộ dữ liệu ra ngoài | Không có tool đọc dữ liệu nhân sự ở bản đầu; chỉ gửi những gì liệt kê ở mục 5. |
| Chi phí tăng bất ngờ | Hạn mức tháng, giới hạn số câu mỗi người, effort `low`, theo dõi `cache_read_input_tokens`. |
| Mất Internet | Tự lùi về tầng 1, không chặn người dùng. |

## 10. Cần chốt trước khi code

a. **Có dùng Claude API không?** Cần Internet, có phí, câu hỏi (không kèm dữ liệu nhân sự) được gửi ra ngoài. Nếu không, chỉ làm B1–B2 (tầng offline), vẫn hướng dẫn và mở trang được nhưng hiểu câu hỏi kém linh hoạt hơn.

b. **Model**: mặc định `claude-opus-5-5` (~$0,02/câu, chất lượng tốt nhất). Có thể chọn `claude-sonnet-5-5` (~một nửa) hoặc `claude-haiku-4-5` (rẻ nhất, cần tài liệu ≥ 4.096 token để cache được).

c. **Ai được dùng trợ lý**: mọi người, hay chỉ admin và trưởng phòng?

d. **Có làm B5** (đọc số liệu của chính người hỏi) không?

e. **Hạn mức chi phí** mỗi tháng (ví dụ $30).

f. **Thứ tự với giai đoạn 0**: làm CSRF (0.1) trước, hay làm trợ lý trước rồi bổ sung CSRF sau?
