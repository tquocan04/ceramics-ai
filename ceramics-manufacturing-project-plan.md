# Hệ Thống Điều Phối & Giám Sát Quy Trình Sản Xuất Xưởng Gốm
## Ceramics Manufacturing Pipeline — Phân tích nghiệp vụ & Kế hoạch triển khai MVP

> Tài liệu này tổng hợp yêu cầu từ đề bài kỹ thuật và mở rộng thành một kế hoạch triển khai thực tế cho MVP.  
> Trọng tâm: **Core Logic + AI Integration + Multi-step Workflow + Notification + Realtime Monitoring**.

---

# 1. Mục tiêu dự án

Xây dựng một hệ thống giúp xưởng gốm:

1. Tiếp nhận mô tả đơn hàng bằng ngôn ngữ tự nhiên.
2. Dùng AI để bóc tách thông số kỹ thuật thành JSON chuẩn.
3. Khởi tạo một mẻ sản xuất từ đơn hàng đã được xác nhận.
4. Tự động tạo quy trình sản xuất nhiều công đoạn.
5. Theo dõi trạng thái từng công đoạn.
6. Kiểm soát thứ tự chuyển trạng thái giữa các công đoạn.
7. Ghi nhận QC và lỗi sản phẩm.
8. Gửi thông báo/cảnh báo qua Telegram, Slack hoặc Zalo.
9. Theo dõi tiến độ bằng Dashboard/Kanban và event logs.
10. Xử lý các tình huống lỗi như AI trả JSON sai, chuyển trạng thái không hợp lệ hoặc notification gửi thất bại.

---

# 2. Phạm vi theo đề bài

Theo đề bài, quy trình sản xuất gốm gồm:

```text
Tạo hình mộc
    ↓
Phơi/Sấy & Sửa mộc
    ↓
Vẽ họa tiết
    ↓
Tráng men
    ↓
Nung lò
    ↓
Kiểm định chất lượng (QC)
    ↓
Đóng gói
```

Bốn thành phần bắt buộc của hệ thống:

- Web Frontend.
- Automation Logic.
- AI / LLM / Agent.
- Chat Notification.

Trọng tâm đánh giá:

| Hạng mục | Điểm | Ý nghĩa đối với implementation |
|---|---:|---|
| Core Logic | 40 | Workflow phải chạy end-to-end và xử lý được ngoại lệ |
| AI Integration | 30 | Prompt tốt, output JSON chuẩn, phân tích hữu ích |
| Presentation | 15 | README và demo rõ ràng |
| UI | 15 | Gọn, trực quan, hỗ trợ thao tác và theo dõi |

Vì vậy dự án nên ưu tiên logic hơn UI.

---

# 3. Định hình hệ thống

Hệ thống nên được xem như một **workflow orchestration system cho xưởng gốm**, không phải ERP đầy đủ.

Luồng tổng thể:

```text
User nhập mô tả đơn hàng
        ↓
AI Analysis
        ↓
Structured JSON
        ↓
JSON Schema Validation
        ↓
User Review / Confirm
        ↓
Create Production Batch
        ↓
Generate Production Workflow
        ↓
FORMING
        ↓
DRYING
        ↓
DECORATING
        ↓
GLAZING
        ↓
FIRING
        ↓
QUALITY CHECK
   ┌────┴─────┐
 PASS        FAIL
  ↓            ↓
PACKAGING    REWORK / BLOCKED
  ↓
COMPLETED
```

Mỗi thay đổi trạng thái có thể tạo:

```text
Workflow Event
      ├── Activity Log
      ├── Realtime Dashboard Update
      └── Notification
```

---

# 4. Các actor nghiệp vụ

## 4.1. Manager

Có thể:

- Tạo đơn hàng.
- Xem kết quả AI.
- Xác nhận thông số sản xuất.
- Theo dõi toàn bộ các mẻ.
- Theo dõi cảnh báo.
- Xử lý các trường hợp stage bị fail/blocked.
- Xem tiến độ và deadline.

## 4.2. Worker

Có thể:

- Xem các mẻ tại công đoạn mình phụ trách.
- Start công đoạn.
- Complete công đoạn.
- Thêm note.
- Báo lỗi công đoạn.

## 4.3. QC Operator

Có thể:

- Nhập kết quả QC.
- Khai báo defect.
- Xác định PASS / FAIL.
- Yêu cầu rework.

> Với MVP, authentication/RBAC có thể được đơn giản hóa. Có thể chỉ thiết kế role ở mức domain mà chưa cần hoàn thiện hệ thống phân quyền phức tạp.

---

# 5. Nghiệp vụ 1 — Production Order Management

## 5.1. Mục tiêu

Tiếp nhận mô tả đơn hàng và lưu lại input gốc trước khi AI phân tích.

Ví dụ:

```text
Đơn 200 Bình gốm họa tiết sen men lam cao 35cm,
yêu cầu nung nhiệt độ cao 1280°C,
hoàn thành trong 10 ngày.
```

## 5.2. Entity đề xuất

```text
ProductionOrder
├── id
├── order_code
├── raw_description
├── status
├── requested_deadline
├── created_at
└── updated_at
```

## 5.3. Order Status

```text
DRAFT
AI_ANALYZING
AI_ANALYSIS_FAILED
PENDING_CONFIRMATION
CONFIRMED
IN_PRODUCTION
COMPLETED
CANCELLED
```

## 5.4. Chức năng cần có

### Must-have

- Create Order.
- List Orders.
- Get Order Detail.
- Analyze Order bằng AI.
- Confirm AI Result.
- Cancel Order trước khi production bắt đầu.

### Optional

- Edit Order.
- Duplicate Order.
- Search/filter theo status.

---

# 6. Nghiệp vụ 2 — AI Order Analysis

## 6.1. Vai trò AI

AI không chỉ chat mà phải chuyển natural language thành dữ liệu nghiệp vụ có cấu trúc.

Pipeline:

```text
Raw Description
      ↓
LLM Prompt
      ↓
Structured JSON
      ↓
Schema Validation
      ↓
Save AIAnalysis
      ↓
Human Review
```

## 6.2. Dữ liệu AI cần bóc tách

Ví dụ:

```json
{
  "product": {
    "name": "Bình gốm",
    "quantity": 200,
    "dimensions": {
      "height_cm": 35
    }
  },
  "decoration": {
    "pattern": "Hoa sen"
  },
  "glaze": {
    "type": "Men lam",
    "estimated_amount_kg": 12
  },
  "clay": {
    "estimated_amount_kg": 180
  },
  "firing": {
    "temperature_c": 1280,
    "estimated_duration_hours": 10
  },
  "deadline_days": 10,
  "priority": "HIGH",
  "priority_reason": "Large quantity with short requested lead time"
}
```

## 6.3. Những trường AI nên phân tích

- Product name.
- Quantity.
- Dimensions.
- Decoration/pattern.
- Glaze type.
- Estimated clay amount.
- Estimated glaze amount.
- Firing temperature.
- Estimated firing duration.
- Deadline.
- Priority.
- Reasoning ngắn gọn cho priority/recommendation.

## 6.4. Business rule

Không nên để AI trực tiếp tạo production batch.

Nên dùng:

```text
AI Result
   ↓
Validate
   ↓
Human Review
   ↓
Confirm
   ↓
Create Batch
```

## 6.5. AI error handling

Các case cần xử lý:

- Timeout.
- Provider unavailable.
- Invalid JSON.
- Missing required fields.
- Wrong data type.
- Temperature bất hợp lý.
- Quantity <= 0.
- AI hallucination.

Flow:

```text
AI Request
    ↓
Response
    ↓
Schema Valid?
 ┌────┴────┐
Yes        No
 ↓          ↓
Save      Retry
            ↓
        Still fail?
            ↓
    AI_ANALYSIS_FAILED
```

## 6.6. Acceptance criteria

- Output phải parse được thành JSON.
- JSON phải match schema.
- Backend phải validate lại các field quan trọng.
- User phải xem được input gốc và AI result.
- AI failure không được làm mất Order.

---

# 7. Nghiệp vụ 3 — Production Batch

## 7.1. Khái niệm

Order và Batch nên là hai entity khác nhau.

```text
ProductionOrder
       ↓
ProductionBatch
       ↓
ProductionStage[]
```

`ProductionOrder` đại diện yêu cầu của khách hàng.

`ProductionBatch` đại diện mẻ gốm thực tế đang được sản xuất.

## 7.2. Entity đề xuất

```text
ProductionBatch
├── id
├── batch_code
├── order_id
├── quantity
├── current_stage
├── status
├── priority
├── deadline
├── started_at
├── completed_at
├── created_at
└── updated_at
```

Ví dụ:

```json
{
  "batch_code": "GOM-0088",
  "order_id": "ORD-2026-001",
  "quantity": 200,
  "status": "IN_PRODUCTION",
  "current_stage": "DRYING",
  "priority": "HIGH",
  "deadline": "2026-09-01T23:59:59+07:00"
}
```

## 7.3. Batch Status

```text
PENDING
IN_PRODUCTION
BLOCKED
REWORK_REQUIRED
COMPLETED
CANCELLED
```

---

# 8. Nghiệp vụ 4 — Workflow Engine

Đây là phần quan trọng nhất của bài.

## 8.1. Workflow mặc định

```text
FORMING
    ↓
DRYING
    ↓
DECORATING
    ↓
GLAZING
    ↓
FIRING
    ↓
QUALITY_CHECK
    ↓
PACKAGING
    ↓
COMPLETED
```

## 8.2. Stage Status

```text
PENDING
IN_PROGRESS
COMPLETED
FAILED
BLOCKED
REWORK_REQUIRED
```

## 8.3. ProductionStage entity

```text
ProductionStage
├── id
├── batch_id
├── stage_type
├── sequence
├── status
├── started_at
├── completed_at
├── note
├── metadata
└── updated_at
```

## 8.4. Business rules quan trọng

### Rule 1 — Không skip stage

Không được:

```text
DRYING → GLAZING
```

nếu:

```text
DECORATING != COMPLETED
```

### Rule 2 — Chỉ một stage active

Một batch không nên có hai stage `IN_PROGRESS` cùng lúc trong workflow tuần tự.

### Rule 3 — Start stage

Một stage chỉ được start khi:

```text
status == PENDING
AND
previous_stage == COMPLETED
```

Ngoại lệ:

```text
FORMING
```

không có previous stage.

### Rule 4 — Complete stage

Chỉ được complete nếu:

```text
status == IN_PROGRESS
```

### Rule 5 — Fail stage

Nếu stage fail:

```text
Batch → BLOCKED
Stage → FAILED
```

Manager phải xử lý trước khi workflow tiếp tục.

### Rule 6 — QC fail

QC có workflow riêng:

```text
QUALITY_CHECK
     ↓
   PASS?
 ┌────┴─────┐
YES          NO
 ↓            ↓
PACKAGING   REWORK_REQUIRED
```

---

# 9. State Machine đề xuất

```text
                 ┌──────────────┐
                 │   PENDING    │
                 └──────┬───────┘
                        │ start
                        ▼
                 ┌──────────────┐
                 │ IN_PROGRESS  │
                 └───┬─────┬────┘
                     │     │
              complete     fail
                     │     │
                     ▼     ▼
              ┌─────────┐ ┌────────┐
              │COMPLETED│ │ FAILED │
              └─────────┘ └────┬───┘
                               │
                               ▼
                            BLOCKED
```

Backend phải là nơi enforce state machine, không phụ thuộc frontend.

---

# 10. Nghiệp vụ 5 — Quality Control

QC nên được coi là một module riêng vì đây là nơi dễ phát sinh exception nghiệp vụ.

## 10.1. Input QC

Ví dụ:

```text
Total inspected: 200
Passed:          190
Defective:        10
```

Defect:

```text
GLAZE_CRACK:     6
DEFORMATION:     2
WRONG_COLOR:     2
```

## 10.2. QCReport entity

```text
QCReport
├── id
├── batch_id
├── inspected_quantity
├── passed_quantity
├── defective_quantity
├── defect_rate
├── severity
├── result
├── note
├── created_at
└── updated_at
```

## 10.3. QCDefect

```text
QCDefect
├── id
├── qc_report_id
├── defect_type
├── quantity
└── note
```

## 10.4. QC Result

```text
PASS
FAIL
REWORK_REQUIRED
```

## 10.5. Severity

```text
LOW
MEDIUM
HIGH
CRITICAL
```

## 10.6. Business logic

Ví dụ:

```text
QC completed
   ↓
Defective > threshold?
   ├── No  → PASS → PACKAGING
   └── Yes → FAIL → REWORK_REQUIRED + Alert
```

Threshold có thể:

- Config cứng cho MVP.
- Hoặc được tính từ defect rate.

Ví dụ đơn giản:

```text
defect_rate <= 5%  → PASS
defect_rate > 5%   → FAIL
```

Nếu muốn tránh business rule giả định, có thể để QC operator chọn PASS/FAIL và chỉ dùng defect rate cho cảnh báo.

---

# 11. Nghiệp vụ 6 — Notification & Alert

## 11.1. Channel

Ưu tiên cho MVP:

```text
Telegram
```

Lý do:

- Setup nhanh.
- Bot API đơn giản.
- Dễ demo.
- Hỗ trợ inline buttons nếu muốn lấy điểm cộng.

## 11.2. Event cần notification

```text
BATCH_CREATED
STAGE_STARTED
STAGE_COMPLETED
STAGE_FAILED
QC_WARNING
QC_CRITICAL
REWORK_REQUIRED
BATCH_COMPLETED
DEADLINE_WARNING
```

## 11.3. Ví dụ notification

### Stage completed

```text
✅ Mẻ GOM-0088

Đã hoàn thành: Tráng men
Công đoạn tiếp theo: Nung lò

Số lượng: 200
Priority: HIGH
```

### Firing started

```text
🔥 Mẻ GOM-0088 đã vào lò

Nhiệt độ: 1280°C
Thời gian dự kiến: 10 giờ
```

### QC alert

```text
🔴 CẢNH BÁO QC

Mẻ: GOM-0088
Phát hiện: 10 sản phẩm lỗi
Defect rate: 5%

Yêu cầu quản lý kiểm tra.
```

## 11.4. Kiến trúc notification

Không nên:

```text
WorkflowService → gọi Telegram trực tiếp
```

Nên:

```text
WorkflowService
      ↓
Create Event
      ↓
NotificationService
      ↓
Telegram Adapter
```

## 11.5. Notification entity

```text
Notification
├── id
├── event_id
├── channel
├── status
├── payload
├── retry_count
├── error_message
├── sent_at
└── created_at
```

Status:

```text
PENDING
SENT
FAILED
```

## 11.6. Error rule

Nếu Telegram fail:

```text
Stage vẫn COMPLETED
Notification → FAILED
```

Không được rollback nghiệp vụ sản xuất.

---

# 12. Nghiệp vụ 7 — Event / Activity Log

Mọi thay đổi quan trọng nên tạo event.

## 12.1. WorkflowEvent entity

```text
WorkflowEvent
├── id
├── batch_id
├── event_type
├── stage
├── message
├── metadata
├── created_by
└── created_at
```

## 12.2. Event example

```json
{
  "batch_id": "GOM-0088",
  "event_type": "STAGE_COMPLETED",
  "stage": "GLAZING",
  "message": "Glazing completed",
  "metadata": {
    "next_stage": "FIRING"
  }
}
```

## 12.3. Lợi ích

- Audit trail.
- Realtime feed.
- Debug workflow.
- Demo trực quan.
- Trigger notification.
- Dễ tích hợp analytics sau này.

---

# 13. Nghiệp vụ 8 — Realtime Dashboard

## 13.1. Kanban

Một hướng UI phù hợp:

```text
FORMING        DRYING       DECORATING      GLAZING       FIRING       QC

GOM-001        GOM-005      GOM-008         GOM-013       GOM-018      GOM-021
GOM-002        GOM-006                      GOM-014
GOM-003
```

## 13.2. Batch Detail

```text
GOM-0088
Bình gốm men lam
Quantity: 200
Priority: HIGH

✓ FORMING
✓ DRYING
✓ DECORATING
✓ GLAZING
● FIRING
○ QUALITY CHECK
○ PACKAGING
```

## 13.3. Realtime Event Feed

```text
10:32:18  GOM-088  FIRING started
10:31:50  GOM-088  GLAZING completed
09:43:12  GOM-092  DRYING completed
09:15:22  GOM-075  QC critical alert
```

## 13.4. Realtime technology

Có thể chọn:

```text
SSE
```

hoặc:

```text
WebSocket
```

Với MVP, SSE là lựa chọn đơn giản nếu chỉ cần server → client update.

---

# 14. Priority & Deadline

AI có thể đề xuất priority:

```text
LOW
NORMAL
HIGH
URGENT
```

Ví dụ:

```json
{
  "priority": "HIGH",
  "reason": "Số lượng 200 sản phẩm và deadline 10 ngày"
}
```

Backend không nên tin tuyệt đối AI.

Có thể:

- Cho user override priority.
- Validate deadline.
- Hiển thị deadline risk trên dashboard.

Optional:

```text
deadline_remaining < estimated_remaining_time
                ↓
        DEADLINE_WARNING
```

---

# 15. Data Model tổng thể

```text
ProductionOrder
      │
      │ 1
      ▼
AIAnalysis
      │
      │ confirmed
      ▼
ProductionBatch
      │
      ├───────────────┐
      │               │
      ▼               ▼
ProductionStage[]   QCReport
      │               │
      │               ▼
      │            QCDefect[]
      │
      ├──────────────→ WorkflowEvent[]
      │
      └──────────────→ Notification[]
```

## Entity tối thiểu cho MVP

1. `ProductionOrder`
2. `AIAnalysis`
3. `ProductionBatch`
4. `ProductionStage`
5. `QCReport`
6. `QCDefect`
7. `WorkflowEvent`
8. `Notification`

---

# 16. API Design đề xuất

Không cần CRUD cho mọi entity.

Ưu tiên command API theo nghiệp vụ.

## 16.1. Order APIs

```http
POST /api/orders
GET  /api/orders
GET  /api/orders/:id

POST /api/orders/:id/analyze
POST /api/orders/:id/confirm
POST /api/orders/:id/cancel
```

## 16.2. Batch APIs

```http
GET /api/batches
GET /api/batches/:id
```

Nếu batch tự tạo sau confirm thì không nhất thiết cần public endpoint create riêng.

## 16.3. Stage APIs

```http
POST /api/batches/:batchId/stages/:stage/start
POST /api/batches/:batchId/stages/:stage/complete
POST /api/batches/:batchId/stages/:stage/fail
```

## 16.4. QC APIs

```http
POST /api/batches/:batchId/qc
GET  /api/batches/:batchId/qc
```

## 16.5. Event APIs

```http
GET /api/batches/:batchId/events
GET /api/events
```

## 16.6. Dashboard APIs

```http
GET /api/dashboard/summary
GET /api/dashboard/kanban
```

## 16.7. Realtime

```text
GET /api/events/stream
```

hoặc:

```text
WS /ws/events
```

---

# 17. Backend module structure đề xuất

```text
src/
├── orders/
│   ├── domain
│   ├── service
│   ├── repository
│   └── handler
│
├── ai/
│   ├── provider
│   ├── prompt
│   ├── schema
│   └── service
│
├── batches/
│   ├── domain
│   ├── service
│   └── repository
│
├── workflow/
│   ├── state-machine
│   ├── transitions
│   └── service
│
├── qc/
│   ├── domain
│   └── service
│
├── events/
│   ├── publisher
│   └── repository
│
├── notifications/
│   ├── telegram
│   ├── service
│   └── retry
│
└── dashboard/
    └── query
```

Không bắt buộc phải dùng đúng cấu trúc này; điều quan trọng là tách rõ domain.

---

# 18. Service boundaries

## OrderService

Chịu trách nhiệm:

```text
Create Order
Request AI Analysis
Confirm Specification
Create Production Batch
```

## AIService

```text
Build Prompt
Call Provider
Parse Response
Validate Schema
Persist Analysis
```

## WorkflowService

```text
Create stages
Validate transition
Start stage
Complete stage
Fail stage
Update current stage
```

## QCService

```text
Create QC report
Calculate defect rate
Determine outcome
Trigger rework/next stage
```

## EventService

```text
Create immutable workflow event
Publish realtime event
```

## NotificationService

```text
Consume event
Format message
Send Telegram
Retry failure
```

---

# 19. Transaction boundaries

Các nghiệp vụ cần transaction:

## Confirm Order

```text
BEGIN

Update order → CONFIRMED

Create ProductionBatch

Create:
- FORMING
- DRYING
- DECORATING
- GLAZING
- FIRING
- QUALITY_CHECK
- PACKAGING

Create BATCH_CREATED event

COMMIT
```

Nếu fail giữa chừng:

```text
ROLLBACK
```

## Complete Stage

```text
BEGIN

Validate transition

Stage → COMPLETED

Next Stage remains PENDING

Update batch current_stage

Create STAGE_COMPLETED event

COMMIT
```

Notification gửi sau transaction.

---

# 20. Error Handling cần triển khai

## 20.1. AI errors

```text
AI_TIMEOUT
AI_PROVIDER_ERROR
AI_INVALID_JSON
AI_SCHEMA_VALIDATION_FAILED
```

## 20.2. Workflow errors

```text
INVALID_STAGE_TRANSITION
STAGE_ALREADY_COMPLETED
STAGE_NOT_STARTED
PREVIOUS_STAGE_NOT_COMPLETED
BATCH_BLOCKED
```

## 20.3. QC errors

```text
INVALID_QC_QUANTITY
QC_ALREADY_SUBMITTED
DEFECT_QUANTITY_MISMATCH
```

## 20.4. Notification errors

```text
NOTIFICATION_SEND_FAILED
NOTIFICATION_RETRY_EXHAUSTED
```

---

# 21. Idempotency

Một số action có thể bị user double-click.

Ví dụ:

```text
Complete FIRING
Complete FIRING
```

Backend phải tránh duplicate action.

Có thể xử lý tối thiểu:

```text
if stage.status == COMPLETED:
    return existing state
```

Tương tự:

```text
Confirm Order
```

không được tạo hai ProductionBatch.

---

# 22. Validation rules

## Production Order

```text
raw_description != empty
```

## AI result

```text
quantity > 0
deadline_days > 0
firing_temperature_c > 0
```

## QC

```text
inspected_quantity >= 0
passed_quantity >= 0
defective_quantity >= 0

passed_quantity + defective_quantity
    == inspected_quantity
```

## Stage

```text
Cannot complete before start.
Cannot skip previous stage.
Cannot operate on cancelled batch.
```

---

# 23. MVP Scope đề xuất

## P0 — Bắt buộc phải hoàn thành

### Order

- [ ] Create Order bằng natural language.
- [ ] List/Get Order.

### AI

- [ ] AI extraction.
- [ ] Structured JSON.
- [ ] Schema validation.
- [ ] AI error handling.
- [ ] User confirm AI result.

### Batch

- [ ] Confirm Order → Create Batch.
- [ ] Auto-generate production stages.

### Workflow

- [ ] Start stage.
- [ ] Complete stage.
- [ ] Fail stage.
- [ ] Validate transition.
- [ ] Prevent skipping.
- [ ] Track current stage.

### QC

- [ ] Submit QC result.
- [ ] Record defects.
- [ ] PASS → Packaging.
- [ ] FAIL → Block/Rework.

### Notification

- [ ] Telegram integration.
- [ ] Stage completed notification.
- [ ] QC alert.
- [ ] Batch completed notification.

### Dashboard

- [ ] Batch list/Kanban.
- [ ] Batch detail.
- [ ] Progress visualization.
- [ ] Activity log.

### Reliability

- [ ] AI retry/error state.
- [ ] Notification failure không rollback workflow.
- [ ] Basic idempotency.

---

# 24. P1 — Nên làm nếu còn thời gian

- [ ] SSE/WebSocket realtime.
- [ ] Deadline warning.
- [ ] Priority filter.
- [ ] Notification retry worker.
- [ ] Dashboard statistics.
- [ ] QC severity.
- [ ] Rework workflow.
- [ ] Telegram inline buttons.

---

# 25. P2 — Future Scope

Không nên ưu tiên trong bài test:

- Full inventory.
- Supplier management.
- Customer CRM.
- Accounting.
- Warehouse management.
- IoT kiln temperature sensor.
- Machine management.
- Worker scheduling.
- Complex RBAC.
- Full ERP.
- ML forecasting.
- Multi-factory support.

---

# 26. Suggested Development Plan

## Phase 0 — Project Setup

Mục tiêu:

- Khởi tạo project.
- Database.
- Environment config.
- Basic frontend/backend skeleton.

Deliverables:

- [ ] Repository.
- [ ] `.env.example`.
- [ ] DB migration.
- [ ] Basic API health endpoint.
- [ ] Frontend skeleton.

---

## Phase 1 — Domain & Database

Implement:

- `ProductionOrder`
- `AIAnalysis`
- `ProductionBatch`
- `ProductionStage`
- `WorkflowEvent`

Deliverables:

- [ ] Migration.
- [ ] Models/entities.
- [ ] Repository layer.
- [ ] Seed/demo data nếu cần.

---

## Phase 2 — AI Analysis

Implement:

```text
Order Description
    ↓
Prompt
    ↓
LLM
    ↓
JSON
    ↓
Schema Validate
```

Deliverables:

- [ ] Prompt template.
- [ ] JSON schema.
- [ ] Provider adapter.
- [ ] Retry/error handling.
- [ ] Analyze endpoint.
- [ ] Review UI.

---

## Phase 3 — Workflow Engine

Implement:

```text
FORMING
→ DRYING
→ DECORATING
→ GLAZING
→ FIRING
→ QUALITY_CHECK
→ PACKAGING
```

Deliverables:

- [ ] Generate stages.
- [ ] State machine.
- [ ] Start command.
- [ ] Complete command.
- [ ] Fail command.
- [ ] Transition validation.
- [ ] Event logging.

Đây là phase cần ưu tiên test kỹ nhất.

---

## Phase 4 — QC

Deliverables:

- [ ] QC form.
- [ ] Defect types.
- [ ] QC report.
- [ ] PASS flow.
- [ ] FAIL/Rework flow.
- [ ] Critical alert event.

---

## Phase 5 — Telegram Notification

Deliverables:

- [ ] Bot setup.
- [ ] Message formatter.
- [ ] Stage event notification.
- [ ] QC warning.
- [ ] Batch completed.
- [ ] Error/retry handling.

---

## Phase 6 — Dashboard

Deliverables:

- [ ] Kanban/list.
- [ ] Order detail.
- [ ] Batch detail.
- [ ] Stage progress.
- [ ] Activity feed.
- [ ] Filter by status/priority.

---

## Phase 7 — Realtime

Nếu đủ thời gian:

- [ ] SSE/WebSocket.
- [ ] Dashboard auto-refresh.
- [ ] Live activity events.

---

## Phase 8 — Testing & Hardening

Test:

- [ ] Normal happy path.
- [ ] AI invalid JSON.
- [ ] AI timeout.
- [ ] Skip stage.
- [ ] Complete stage twice.
- [ ] QC fail.
- [ ] Telegram fail.
- [ ] Concurrent request.
- [ ] Invalid quantities.
- [ ] Cancelled batch.

---

# 27. Testing Strategy

## Unit Tests

Ưu tiên:

```text
Workflow transition
AI schema validation
QC calculation
Priority validation
Notification formatting
```

## Integration Tests

Test flow:

```text
Create Order
    ↓
Analyze
    ↓
Confirm
    ↓
Batch created
    ↓
Stages generated
    ↓
Complete workflow
    ↓
QC
    ↓
Packaging
    ↓
Completed
```

## Failure Integration Tests

```text
AI failure
Invalid transition
QC failure
Notification failure
```

---

# 28. Acceptance Criteria cho MVP

MVP được coi là hoàn thành khi demo được:

## Scenario A — Happy Path

1. User tạo order.
2. AI parse thành JSON.
3. User confirm.
4. System tạo batch.
5. System tự tạo 7 stages.
6. User chạy lần lượt các stage.
7. QC PASS.
8. Packaging complete.
9. Batch → COMPLETED.
10. Telegram nhận notification.
11. Dashboard hiển thị toàn bộ event.

## Scenario B — Invalid Workflow

User cố:

```text
DRYING → GLAZING
```

System phải reject.

## Scenario C — QC Failure

QC phát hiện lỗi nghiêm trọng.

System:

```text
QC → FAIL
Batch → REWORK_REQUIRED/BLOCKED
Create CRITICAL event
Send Telegram alert
```

## Scenario D — AI Failure

AI trả invalid JSON.

System:

- Không crash.
- Order vẫn tồn tại.
- Hiển thị `AI_ANALYSIS_FAILED`.
- Cho retry.

## Scenario E — Notification Failure

Telegram fail.

System:

- Stage vẫn completed.
- Notification status = failed.
- Có thể retry sau.

---

# 29. Dashboard Screens đề xuất

Không cần quá nhiều màn hình.

## Screen 1 — Orders

```text
Orders
├── New Order
├── Pending AI
├── Pending Confirmation
└── In Production
```

## Screen 2 — New Order

```text
Order description textarea
Analyze with AI button
```

## Screen 3 — AI Review

```text
Original description

AI Result
├── Product
├── Quantity
├── Clay
├── Glaze
├── Firing
├── Deadline
└── Priority

[Confirm]
[Retry Analysis]
```

## Screen 4 — Production Board

```text
Kanban by stage
```

## Screen 5 — Batch Detail

```text
Batch Info
Progress
Stages
QC
Activity Log
```

Đây là đủ cho MVP.

---

# 30. Demo Script 2–3 phút

## 0:00 – 0:20

Giới thiệu:

```text
Hệ thống nhận đơn sản xuất gốm bằng ngôn ngữ tự nhiên,
AI bóc tách thông số,
sau đó tự động khởi tạo và điều phối workflow sản xuất.
```

## 0:20 – 0:45

Tạo order:

```text
200 Bình gốm...
```

Bấm:

```text
Analyze
```

Show JSON AI.

## 0:45 – 1:10

Confirm.

Show:

```text
GOM-0088 created
7 stages generated
```

## 1:10 – 1:40

Complete vài stages.

Show:

```text
Kanban moving
Activity events
Telegram notification
```

## 1:40 – 2:10

Đưa đến QC.

Submit defect.

Show:

```text
QC alert
Batch blocked/rework
Telegram red alert
```

## 2:10 – 2:30

Giải thích nhanh:

```text
State machine
Event-driven notification
AI schema validation
Error handling
```

## 2:30 – 3:00

Show README/architecture và kết luận.

---

# 31. README cần có

README nên bao gồm:

## Introduction

- Bài toán.
- Mục tiêu.

## Features

- AI Order Analysis.
- Production Workflow.
- QC.
- Notification.
- Realtime Dashboard.

## Architecture

```text
Frontend
Backend
Database
LLM Provider
Telegram
```

## Workflow Diagram

```text
Order → AI → Confirm → Batch → Stages → QC → Complete
```

## AI

- Prompt strategy.
- JSON schema.
- Validation.
- Failure handling.

## Run Locally

```text
install
env
database
start backend
start frontend
```

## Demo

- Demo account nếu có.
- Example order.
- Screenshot/GIF.
- Video link.

## Limitations

Nói rõ những phần chưa làm.

## Future Improvements

Tách biệt khỏi MVP.

---

# 32. Kiến trúc mức cao đề xuất

```text
                        ┌───────────────┐
                        │   Frontend    │
                        │ Dashboard UI  │
                        └───────┬───────┘
                                │ HTTP / SSE
                                ▼
                    ┌──────────────────────┐
                    │       Backend        │
                    │                      │
                    │ Order Service        │
                    │ AI Service           │
                    │ Workflow Service     │
                    │ QC Service           │
                    │ Event Service        │
                    │ Notification Service │
                    └───┬─────────┬────────┘
                        │         │
                        │         └───────────────┐
                        ▼                         ▼
                ┌─────────────┐           ┌─────────────┐
                │  Database   │           │ LLM Provider│
                └─────────────┘           └─────────────┘
                        │
                        │ events
                        ▼
                ┌────────────────┐
                │ Notification   │
                │ Telegram       │
                └────────────────┘
```

---

# 33. Event-driven design tối thiểu

Không cần Kafka/RabbitMQ cho bài test.

Có thể implement:

```text
Domain action
   ↓
DB transaction
   ↓
WorkflowEvent persisted
   ↓
Notification job/service
```

Nếu backend framework hỗ trợ background task:

```text
after commit → async notification
```

Điều quan trọng là business transaction không phụ thuộc Telegram.

---

# 34. AI Prompt Strategy

Prompt nên yêu cầu AI:

1. Chỉ trả JSON.
2. Theo đúng schema.
3. Không thêm Markdown.
4. Không tự invent field ngoài schema.
5. Nếu thiếu thông tin, trả `null`.
6. Không giả định quá mức.
7. Có recommendation riêng với estimated fields.

Concept:

```text
Extract only information supported by the order description.
For estimated manufacturing values, clearly mark them as estimates.
If information cannot be inferred reliably, use null.
Return JSON only.
```

Nên tách:

```text
extracted_data
estimated_data
```

Ví dụ:

```json
{
  "extracted": {
    "quantity": 200,
    "height_cm": 35,
    "firing_temperature_c": 1280
  },
  "estimated": {
    "clay_kg": 180,
    "glaze_kg": 12,
    "firing_duration_hours": 10
  }
}
```

Cách này giúp phân biệt thông tin khách hàng cung cấp với thông tin AI suy luận.

---

# 35. Những điểm có thể giúp bài nổi bật

Nếu còn thời gian, ưu tiên theo thứ tự:

## 1. Realtime events

Thể hiện system thực sự là monitoring pipeline.

## 2. QC failure branch

Thể hiện exception handling.

## 3. AI schema validation

Thể hiện AI Integration thực chiến.

## 4. Telegram inline action

Ví dụ:

```text
[Complete Stage]
[Report Issue]
```

## 5. Deadline risk

Hiển thị:

```text
ON_TRACK
AT_RISK
OVERDUE
```

---

# 36. Những điểm nên tránh

## Over-engineering

Không cần:

```text
Microservices
Kafka
Kubernetes
Event sourcing
Complex DDD
```

trừ khi bạn đã có sẵn infrastructure.

## UI quá nhiều

Không dành quá nhiều thời gian cho:

- animation.
- chart phức tạp.
- design system.
- role management.

## AI không validate

Không nên:

```text
LLM output → Database
```

mà phải:

```text
LLM output → Parse → Validate → Persist
```

## Workflow chỉ là dropdown status

Không nên cho frontend tự chọn tùy ý:

```text
PENDING
FIRING
QC
COMPLETED
```

Backend phải enforce sequence.

---

# 37. Thứ tự ưu tiên effort

Khuyến nghị:

```text
45% Workflow / Core Business Logic
30% AI Integration
15% Notification + Reliability + Realtime
10% UI Polish
```

---

# 38. Definition of Done

Project được coi là đủ tốt để nộp khi:

- [ ] Có repository sạch.
- [ ] Có README.
- [ ] App chạy được từ đầu đến cuối.
- [ ] AI parse được order.
- [ ] Output AI được validate.
- [ ] Confirm tạo batch.
- [ ] 7 stages được tạo tự động.
- [ ] Stage transition được enforce.
- [ ] QC có PASS và FAIL path.
- [ ] Telegram notification chạy.
- [ ] Dashboard hiển thị tiến độ.
- [ ] Có event logs.
- [ ] Error không làm crash workflow.
- [ ] Có ít nhất unit test cho workflow.
- [ ] Có demo data.
- [ ] Có video 2–3 phút.

---

# 39. Checklist trước khi code

## Domain

- [ ] Chốt entities.
- [ ] Chốt stage enum.
- [ ] Chốt status enum.
- [ ] Chốt state transition.
- [ ] Chốt QC behavior.

## AI

- [ ] Chốt JSON schema.
- [ ] Chốt extracted vs estimated.
- [ ] Chốt validation.
- [ ] Chốt retry strategy.

## Backend

- [ ] Chốt API.
- [ ] Chốt transaction boundary.
- [ ] Chốt error format.
- [ ] Chốt event model.

## Notification

- [ ] Tạo Telegram bot.
- [ ] Lưu bot token trong env.
- [ ] Chốt event nào gửi message.

## Frontend

- [ ] Order screen.
- [ ] AI review screen.
- [ ] Kanban.
- [ ] Batch detail.
- [ ] QC form.
- [ ] Activity feed.

---

# 40. Kế hoạch triển khai rút gọn

Nếu thời gian rất ngắn, làm theo thứ tự:

```text
1. Database/domain models
2. Create Order
3. AI Analyze + JSON Schema
4. Confirm → Batch + Stages
5. Workflow State Machine
6. QC
7. Event Log
8. Telegram
9. Kanban Dashboard
10. Error Handling
11. Tests
12. README + Demo
```

Đừng bắt đầu bằng UI.

---

# 41. Final MVP Flow

Flow tối thiểu nên demo được:

```text
Create Order
    ↓
AI Analyze
    ↓
Validate JSON
    ↓
Review / Confirm
    ↓
Create Batch
    ↓
FORMING
    ↓
DRYING
    ↓
DECORATING
    ↓
GLAZING
    ↓
FIRING
    ↓
QUALITY_CHECK
   ┌───────┴────────┐
 PASS              FAIL
  ↓                  ↓
PACKAGING       REWORK/BLOCKED
  ↓
COMPLETED
```

Song song:

```text
Every important action
        ↓
WorkflowEvent
   ┌────┼─────────────┐
   ↓    ↓             ↓
Logs  Realtime    Notification
```

---

# 42. Kết luận

Điểm cốt lõi của dự án không nằm ở việc xây dựng một hệ thống quản lý xưởng gốm đầy đủ.

Một MVP tốt nên chứng minh được ba năng lực:

## 1. Workflow Engineering

```text
Multi-step process
State transitions
Validation
Failure branches
```

## 2. AI Engineering

```text
Natural Language
      ↓
Structured JSON
      ↓
Schema Validation
      ↓
Useful Business Recommendation
```

## 3. System Integration

```text
Frontend
Backend
Database
Realtime Events
Telegram Notification
```

Nếu ba phần trên chạy end-to-end ổn định, dự án đã đáp ứng rất sát trọng tâm đánh giá của đề bài và có đủ chiều sâu để thể hiện tư duy Software Engineer thay vì chỉ là một CRUD application có gắn LLM.

---

# 43. Scope cuối cùng nên chốt

```text
Ceramics Manufacturing Pipeline MVP

├── Order Management
│   ├── Create Order
│   ├── AI Analysis
│   └── Confirm
│
├── AI
│   ├── Structured Extraction
│   ├── Estimation
│   ├── Priority Recommendation
│   └── JSON Validation
│
├── Production Batch
│   ├── Batch Creation
│   ├── Priority
│   └── Deadline
│
├── Workflow Engine
│   ├── Forming
│   ├── Drying
│   ├── Decorating
│   ├── Glazing
│   ├── Firing
│   ├── Quality Check
│   └── Packaging
│
├── QC
│   ├── Inspection
│   ├── Defects
│   ├── Pass / Fail
│   └── Rework
│
├── Event System
│   ├── Audit Log
│   ├── Activity Feed
│   └── Realtime Update
│
├── Notification
│   ├── Stage Completed
│   ├── QC Alert
│   ├── Batch Completed
│   └── Retry
│
└── Dashboard
    ├── Orders
    ├── Kanban
    ├── Batch Detail
    ├── Progress
    └── Event Logs
```

---

**Recommended implementation principle:**

> **Build the workflow first, make AI structured and validated, then add notification and UI around a reliable core.**
