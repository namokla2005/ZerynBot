/**
 * emoji_picker_data.js — Dữ liệu emoji phổ biến cho bộ chọn Emoji (trang Reaction Roles).
 *
 * Tách riêng khỏi template để HTML gọn và có thể tái dùng cho các trang khác sau này.
 * Cấu trúc mỗi nhóm: { name, k (từ khóa nhóm), items: [[emoji, "từ khóa tìm kiếm"], ...] }
 * — từ khóa gồm cả tiếng Anh lẫn tiếng Việt để tìm kiếm nhanh.
 */
window.EMOJI_PICKER_DATA = [
  { name: "Mặt cười & cảm xúc", k: "smile face cười cảm xúc", items: [
    ["😀","grin vui"],["😁","beam"],["😂","joy cười khóc"],["🤣","rofl"],["😊","blush"],["😇","angel"],["🙂","slight smile"],["😉","wink nháy mắt"],["😍","heart eyes"],["🥰","love yêu"],["😘","kiss hôn"],["😜","wink tongue"],["🤪","zany"],["🤗","hug ôm"],["🤔","think suy nghĩ"],["😴","sleep ngủ"],["😭","cry khóc"],["😡","angry giận"],["🥺","pleading"],["😱","scream"],["🤯","mind blown"],["🥳","party tiệc"],["😎","cool ngầu"],["🤓","nerd"],
  ]},
  { name: "Cử chỉ & bàn tay", k: "hand gesture tay cử chỉ", items: [
    ["👍","like thích"],["👎","dislike chê"],["👌","ok"],["✌️","victory"],["🤞","fingers crossed"],["🤟","love you"],["👏","clap vỗ tay"],["🙌","raise"],["🙏","pray cầu nguyện"],["💪","muscle cơ bắp"],["👋","wave vẫy tay"],["🤝","handshake bắt tay"],["🫡","salute"],["✋","raised hand"],
  ]},
  { name: "Trái tim", k: "heart tim yêu", items: [
    ["❤️","red heart đỏ"],["🧡","orange cam"],["💛","yellow vàng"],["💚","green xanh"],["💙","blue"],["💜","purple tím"],["🖤","black đen"],["🤍","white trắng"],["🤎","brown nâu"],["💔","broken tan vỡ"],["💕","two hearts"],["💖","sparkling"],["💘","cupid"],
  ]},
  { name: "Động vật", k: "animal con vật động vật", items: [
    ["🐶","dog chó"],["🐱","cat mèo"],["🐭","mouse chuột"],["🐹","hamster"],["🐰","rabbit thỏ"],["🦊","fox cáo"],["🐻","bear gấu"],["🐼","panda"],["🐨","koala"],["🐯","tiger hổ"],["🦁","lion sư tử"],["🐮","cow bò"],["🐷","pig heo"],["🐸","frog ếch"],["🐵","monkey khỉ"],["🐔","chicken gà"],["🐧","penguin cánh cụt"],["🦉","owl cú mèo"],["🦄","unicorn"],["🐢","turtle rùa"],["🐍","snake rắn"],["🐙","octopus bạch tuộc"],["🐬","dolphin cá heo"],["🦈","shark cá mập"],
  ]},
  { name: "Đồ ăn & thức uống", k: "food drink ăn uống đồ ăn", items: [
    ["🍎","apple táo"],["🍊","orange cam"],["🍋","lemon chanh"],["🍌","banana chuối"],["🍉","watermelon dưa hấu"],["🍇","grapes nho"],["🍓","strawberry dâu"],["🍒","cherry anh đào"],["🥝","kiwi"],["🍕","pizza"],["🍔","burger"],["🍟","fries khoai tây"],["🌭","hotdog"],["🍿","popcorn bắp rang"],["🥗","salad"],["🍣","sushi"],["🍜","ramen mì"],["🍰","cake bánh"],["🎂","birthday sinh nhật"],["🍫","chocolate socola"],["🍬","candy kẹo"],["☕","coffee cà phê"],["🍵","tea trà"],["🧋","bubble tea trà sữa"],["🍺","beer bia"],
  ]},
  { name: "Đồ vật & Game", k: "object game đồ vật trò chơi", items: [
    ["🎮","game controller"],["🕹️","joystick"],["🎧","headphone tai nghe"],["🎤","mic"],["🎸","guitar"],["🥁","drum trống"],["🎬","movie phim"],["📸","camera"],["💻","laptop"],["⌨️","keyboard bàn phím"],["📱","phone điện thoại"],["⚙️","gear"],["🔧","wrench cờ lê"],["🔨","hammer búa"],["📌","pin ghim"],["📎","paperclip"],["🔑","key chìa khóa"],["🔒","lock ổ khóa"],["💡","idea ý tưởng"],["🔔","bell chuông"],["🎁","gift quà"],["🎈","balloon bóng bay"],["🎉","tada chúc mừng"],["🏆","trophy cúp"],["🥇","gold medal huy chương"],["⚽","soccer bóng đá"],["🏀","basketball bóng rổ"],["🎾","tennis"],["🎳","bowling"],["🎯","dart"],
  ]},
  { name: "Biểu tượng", k: "symbol biểu tượng ký hiệu", items: [
    ["✅","check đúng tick"],["❌","cross sai x"],["⛔","no entry cấm"],["🚫","prohibited cấm"],["⚠️","warning cảnh báo"],["❓","question hỏi"],["❗","exclamation"],["💯","100 điểm"],["🔥","fire lửa hot"],["⭐","star sao"],["🌟","glow star"],["✨","sparkles lấp lánh"],["⚡","zap sét"],["💥","boom nổ"],["🔴","red circle đỏ"],["🟢","green circle xanh"],["🔵","blue circle"],["🟡","yellow circle vàng"],["🟣","purple circle tím"],["⚫","black circle"],["⚪","white circle"],["🟠","orange circle"],["🔺","red triangle"],["♻️","recycle tái chế"],
  ]},
];
