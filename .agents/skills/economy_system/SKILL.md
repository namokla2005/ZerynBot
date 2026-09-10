---
name: economy_system
description: >
  Guide and architectural reference for ZerynBot V2 dual-tier Economy System,
  Wallet vs Bank separation, mini-games, and Role Shop.
---

# Skill: Dual-Tier Economy & Banking System

## 🎯 1. Nguyên Tắc Cốt Lõi (Architecture Rules)

ZerynBot V2 áp dụng mô hình kinh tế **2 tầng phân tách nghiêm ngặt**:

```
                  ┌─────────────────────────────────────────┐
                  │              Người Dùng                 │
                  └──────────────┬───────────────────┬──────┘
                                 │                   │
                     Nạp tiền    │                   │ Rút tiền
                   /deposit <N>  ▼                   ▼ /withdraw <N>
                  ┌────────────────────┐       ┌────────────────────┐
                  │     VÍ (Wallet)    │       │   NGÂN HÀNG (Bank) │
                  │  Tiền mặt lưu động │       │   Két sắt an toàn  │
                  └─────────┬──────────┘       └─────────┬──────────┘
                            │                            │
             ┌──────────────┴──────────────┐             │ Thanh toán Role
             ▼                             ▼             ▼ /buy <item_id>
       Chuyển tiền                Mini-Games Cược      Cửa Hàng Role
       /pay @user <N>             /coinflip, /slots,   /shop
                                  /blackjack
```

---

## 🔒 2. Quy Tắc Giao Dịch & Cược Bắt Buộc

1. **Mini-Games (`/coinflip`, `/slots`, `/blackjack`)**:
   - **Chỉ cược bằng tiền VÍ (Wallet)**.
   - Tuyệt đối không tự động trừ tiền trong Ngân hàng khi chơi game để bảo vệ tài sản người dùng.
   - Thắng cược ➔ Cộng trực tiếp vào Ví.
2. **Cửa Hàng Server (`/shop`, `/buy`)**:
   - **Thanh toán bằng tiền NGÂN HÀNG (Bank)**.
   - Khi mua Role, trừ tiền Bank. Nếu tiền Bank không đủ ➔ Báo lỗi và nhắc người dùng `/deposit` thêm vào Bank.
3. **Nạp & Rút Tiền (`/deposit`, `/withdraw`)**:
   - Hỗ trợ số tiền cụ thể (`/deposit 5000`) hoặc từ khóa linh hoạt (`all`, `max`, `toàn bộ`).
4. **Điểm Danh Hàng Ngày (`/daily`)**:
   - Nhận tiền cơ bản + thưởng chuỗi ngày (Streak bonus).
   - Tiền thưởng được cộng trực tiếp vào **Ví (Wallet)**.

---

## 🗄️ 3. Cấu Trúc Bảng CSDL SQLite

| Bảng | Cột Chính | Mục Đích |
|:-----|:----------|:---------|
| `economy_settings` | `guild_id`, `daily_amount`, `streak_bonus`, `starting_balance`, `currency_symbol`, `currency_name` | Cấu hình kinh tế máy chủ |
| `economy_users` | `guild_id`, `user_id`, `wallet`, `bank`, `daily_streak`, `last_daily_at` | Số dư & chuỗi điểm danh thành viên |
| `economy_shop` | `id`, `guild_id`, `role_id`, `name`, `price`, `stock` | Danh mục Role đăng bán trên Shop |

---

## ⚡ 4. Quy Chuẩn Concurrency & Giao Dịch Nguyên Tử (Atomic Transactions)

Để loại trừ triệt để lỗi đua lệnh (Race Condition) và deadlock SQLite khi nhiều người dùng hoặc tiến trình thực hiện giao dịch cùng lúc:

1. **Cập nhật có điều kiện nguyên tử (Atomic Conditional Updates)**:
   - Tuyệt đối **không** dùng cơ chế "Kiểm tra số dư trong Python rồi mới trừ tiền" (Check-then-Act / TOCTOU).
   - Mọi thao tác nạp, rút hoặc mua hàng phải dùng mệnh đề `WHERE` để kiểm tra điều kiện ngay cấp CSDL:
     ```sql
     -- Nạp tiền (Deposit)
     UPDATE economy_users
     SET wallet = wallet - ?, bank = bank + ?
     WHERE guild_id = ? AND user_id = ? AND wallet >= ?;

     -- Rút tiền (Withdraw)
     UPDATE economy_users
     SET bank = bank - ?, wallet = wallet + ?
     WHERE guild_id = ? AND user_id = ? AND bank >= ?;

     -- Mua vật phẩm có giới hạn kho (Shop Purchase)
     UPDATE economy_shop
     SET stock = stock - 1
     WHERE id = ? AND guild_id = ? AND (stock = -1 OR stock > 0);
     ```
   - Sau khi thực thi lệnh `cursor.execute()`, kiểm tra `cursor.rowcount == 1`. Nếu `rowcount == 0`, giao dịch bị từ chối do số dư không đủ hoặc hàng đã hết, hoàn toàn an toàn và không bao giờ xảy ra số dư âm.

2. **Giao dịch đơn kết nối triệt tiêu Deadlock (`async_transfer_money`)**:
   - Khi chuyển tiền giữa 2 người dùng (`/pay`), **bắt buộc** thực hiện toàn bộ thao tác trong duy nhất 1 kết nối `aiosqlite.connect`:
     - Khởi tạo người nhận qua `INSERT OR IGNORE INTO economy_users` ngay trên cùng connection trước khi trừ tiền.
     - Trừ tiền người gửi bằng lệnh nguyên tử `WHERE wallet >= ?`.
     - Cộng tiền người nhận.
     - Commit transaction `await db.commit()`.
   - Tuyệt đối không gọi các hàm trợ giúp mở kết nối con lồng nhau (nested connections) khi đang giữ lock transaction, đảm bảo thời gian giữ lock dưới 3ms và không bị lỗi `sqlite3.OperationalError: database is locked`.

