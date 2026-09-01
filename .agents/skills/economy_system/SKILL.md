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
