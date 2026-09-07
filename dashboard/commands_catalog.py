# -*- coding: utf-8 -*-
"""
Script to create dashboard/commands_catalog.py with full translations for:
- 87 commands
- syntax/usage parameters
- argument descriptions
- preview titles, descriptions, and fields
across all 6 languages (vi, en, zh, es, pt, fr).
"""

import sys, os, json, copy
sys.path.insert(0, '.')
from dashboard.app import _COMMANDS_DATA

# Dictionary of argument description translations across 6 languages
ARG_TRANS = {
    "Hình ảnh đính kèm để phân tích": {
        "vi": "Hình ảnh đính kèm để phân tích",
        "en": "Attached image for analysis",
        "zh": "供分析的附带图片",
        "es": "Imagen adjunta para análisis",
        "pt": "Imagem anexada para análise",
        "fr": "Image jointe pour analyse"
    },
    "Bật tra cứu Internet qua DuckDuckGo (True/False)": {
        "vi": "Bật tra cứu Internet qua DuckDuckGo (True/False)",
        "en": "Enable real-time DuckDuckGo web search (True/False)",
        "zh": "开启 DuckDuckGo 实时联网搜索 (True/False)",
        "es": "Activar búsqueda web DuckDuckGo en tiempo real (True/False)",
        "pt": "Ativar pesquisa na web via DuckDuckGo em tempo real (True/False)",
        "fr": "Activer la recherche web DuckDuckGo en temps réel (True/False)"
    },
    "Đường link URL bài viết cần tóm tắt": {
        "vi": "Đường link URL bài viết cần tóm tắt",
        "en": "Article URL to summarize",
        "zh": "需要提炼摘要的文章网址 URL",
        "es": "URL del artículo para resumir",
        "pt": "URL do artigo para resumir",
        "fr": "URL de l'article à résumer"
    },
    "Thành viên cần xem (mặc định: bạn)": {
        "vi": "Thành viên cần xem (mặc định: bạn)",
        "en": "Member to view (default: you)",
        "zh": "要查看的成员 (默认: 自己)",
        "es": "Miembro a consultar (por defecto: tú)",
        "pt": "Membro a consultar (padrão: você)",
        "fr": "Membre à consulter (par défaut : vous)"
    },
    "Thành viên cần xem (mặc định: bản thân)": {
        "vi": "Thành viên cần xem (mặc định: bản thân)",
        "en": "Member to view (default: yourself)",
        "zh": "要查看的成员 (默认: 自己)",
        "es": "Miembro a consultar (por defecto: tú)",
        "pt": "Membro a consultar (padrão: você)",
        "fr": "Membre à consulter (par défaut : vous)"
    },
    "Thành viên cần xem": {
        "vi": "Thành viên cần xem",
        "en": "Member to view",
        "zh": "要查看的成员",
        "es": "Miembro a consultar",
        "pt": "Membro a consultar",
        "fr": "Membre à consulter"
    },
    "Thành viên cần xem avatar (mặc định: bạn)": {
        "vi": "Thành viên cần xem avatar (mặc định: bạn)",
        "en": "Member to view avatar of (default: you)",
        "zh": "要查看头像的成员 (默认: 自己)",
        "es": "Miembro para ver su avatar (por defecto: tú)",
        "pt": "Membro para ver o avatar (padrão: você)",
        "fr": "Membre dont afficher l'avatar (par défaut : vous)"
    },
    "Thành viên cần xem số dư": {
        "vi": "Thành viên cần xem số dư",
        "en": "Member to check balance of",
        "zh": "要查看余额的成员",
        "es": "Miembro para consultar saldo",
        "pt": "Membro para ver o saldo",
        "fr": "Membre dont vérifier le solde"
    },
    "Thành viên nhận tiền": {
        "vi": "Thành viên nhận tiền",
        "en": "Recipient member",
        "zh": "收款成员",
        "es": "Miembro receptor",
        "pt": "Membro destinatário",
        "fr": "Membre destinataire"
    },
    "Thành viên bị cảnh cáo": {
        "vi": "Thành viên bị cảnh cáo",
        "en": "Member to warn",
        "zh": "要警告的成员",
        "es": "Miembro a advertir",
        "pt": "Membro a advertir",
        "fr": "Membre à avertir"
    },
    "Thành viên cần kick": {
        "vi": "Thành viên cần kick",
        "en": "Member to kick",
        "zh": "要踢出的成员",
        "es": "Miembro a expulsar",
        "pt": "Membro a expulsar",
        "fr": "Membre à expulser"
    },
    "Thành viên cần cấm": {
        "vi": "Thành viên cần cấm",
        "en": "Member to ban",
        "zh": "要封禁的成员",
        "es": "Miembro a banear",
        "pt": "Membro a banir",
        "fr": "Membre à bannir"
    },
    "Thành viên cần mute": {
        "vi": "Thành viên cần mute",
        "en": "Member to timeout/mute",
        "zh": "要禁言的成员",
        "es": "Miembro a silenciar",
        "pt": "Membro a silenciar",
        "fr": "Membre à exclure temporairement"
    },
    "Thành viên cần gỡ mute": {
        "vi": "Thành viên cần gỡ mute",
        "en": "Member to remove timeout from",
        "zh": "要解除禁言的成员",
        "es": "Miembro para quitar silencio",
        "pt": "Membro para remover silêncio",
        "fr": "Membre dont retirer l'exclusion"
    },
    "Người dùng": {
        "vi": "Người dùng",
        "en": "User",
        "zh": "用户",
        "es": "Usuario",
        "pt": "Usuário",
        "fr": "Utilisateur"
    },
    "Người dùng cần xem (mặc định: bạn)": {
        "vi": "Người dùng cần xem (mặc định: bạn)",
        "en": "User to view (default: you)",
        "zh": "要查看的用户 (默认: 自己)",
        "es": "Usuario a consultar",
        "pt": "Usuário a consultar",
        "fr": "Utilisateur à consulter"
    },
    "ID người dùng": {
        "vi": "ID người dùng",
        "en": "User ID",
        "zh": "用户 ID",
        "es": "ID de usuario",
        "pt": "ID do usuário",
        "fr": "ID de l'utilisateur"
    },
    "Người bạn muốn ôm": {
        "vi": "Người bạn muốn ôm",
        "en": "Person you want to hug",
        "zh": "想要拥抱的人",
        "es": "Persona a abrazar",
        "pt": "Pessoa que você quer abraçar",
        "fr": "Personne à enlacer"
    },
    "Người bạn muốn xoa đầu": {
        "vi": "Người bạn muốn xoa đầu",
        "en": "Person you want to pat",
        "zh": "想要摸头的人",
        "es": "Persona a acariciar",
        "pt": "Pessoa para fazer cafuné",
        "fr": "Personne à tapoter"
    },
    "Người bạn muốn hôn": {
        "vi": "Người bạn muốn hôn",
        "en": "Person you want to kiss",
        "zh": "想要亲吻的人",
        "es": "Persona a besar",
        "pt": "Pessoa que você quer beijar",
        "fr": "Personne à embrasser"
    },
    "Người bị tát": {
        "vi": "Người bị tát",
        "en": "Person to slap",
        "zh": "被拍打/扇耳光的人",
        "es": "Persona a abofetear",
        "pt": "Pessoa a estapear",
        "fr": "Personne à gifler"
    },
    "Người được đút ăn": {
        "vi": "Người được đút ăn",
        "en": "Person to feed",
        "zh": "被投喂的人",
        "es": "Persona a alimentar",
        "pt": "Pessoa a alimentar",
        "fr": "Personne à nourrir"
    },
    "Người bạn muốn cưng nựng": {
        "vi": "Người bạn muốn cưng nựng",
        "en": "Person you want to cuddle",
        "zh": "想要依偎依恋的人",
        "es": "Persona a acurrucar",
        "pt": "Pessoa para mimar/abraçar",
        "fr": "Personne à câliner"
    },
    "Người bị chọc": {
        "vi": "Người bị chọc",
        "en": "Person to poke",
        "zh": "被戳脸蛋的人",
        "es": "Persona a tocar/picar",
        "pt": "Pessoa a cutucar",
        "fr": "Personne à taquiner"
    },
    "Người đập tay cùng": {
        "vi": "Người đập tay cùng",
        "en": "Person to highfive",
        "zh": "一起击掌的人",
        "es": "Persona para chocar los cinco",
        "pt": "Pessoa para bater as mãos",
        "fr": "Personne à taper dans la main"
    },
    "Người thứ nhất": {
        "vi": "Người thứ nhất",
        "en": "First person",
        "zh": "第一个人",
        "es": "Primera persona",
        "pt": "Primeira pessoa",
        "fr": "Première personne"
    },
    "Người thứ hai (mặc định: bạn)": {
        "vi": "Người thứ hai (mặc định: bạn)",
        "en": "Second person (default: you)",
        "zh": "第二个人 (默认: 自己)",
        "es": "Segunda persona (por defecto: tú)",
        "pt": "Segunda pessoa (padrão: você)",
        "fr": "Deuxième personne (par défaut : vous)"
    },
    "Người bạn muốn cầu hôn": {
        "vi": "Người bạn muốn cầu hôn",
        "en": "Person you want to marry",
        "zh": "想要求婚的人",
        "es": "Persona a quien pedir matrimonio",
        "pt": "Pessoa que você quer pedir em casamento",
        "fr": "Personne à demander en mariage"
    },
    "Câu hỏi bình chọn": {
        "vi": "Câu hỏi bình chọn",
        "en": "Poll question",
        "zh": "投票问题",
        "es": "Pregunta de la encuesta",
        "pt": "Pergunta da votação",
        "fr": "Question du sondage"
    },
    "Câu hỏi cần giải đáp": {
        "vi": "Câu hỏi cần giải đáp",
        "en": "Question to ask AI",
        "zh": "向 AI 提出的问题",
        "es": "Pregunta para la IA",
        "pt": "Pergunta para a IA",
        "fr": "Question posée à l'IA"
    },
    "Các phương án (cách nhau bởi dấu phẩy)": {
        "vi": "Các phương án (cách nhau bởi dấu phẩy)",
        "en": "Options (separated by commas)",
        "zh": "候选选项（用逗号隔开）",
        "es": "Opciones (separadas por comas)",
        "pt": "Opções (separadas por vírgulas)",
        "fr": "Options (séparées par des virgules)"
    },
    "Số lớn nhất (mặc định: 100)": {
        "vi": "Số lớn nhất (mặc định: 100)",
        "en": "Maximum number (default: 100)",
        "zh": "最大数值 (默认: 100)",
        "es": "Número máximo (por defecto: 100)",
        "pt": "Número máximo (padrão: 100)",
        "fr": "Nombre maximum (par défaut : 100)"
    },
    "Thời gian nhắc (VD: 10m, 1h, 20:30)": {
        "vi": "Thời gian nhắc (VD: 10m, 1h, 20:30)",
        "en": "Reminder time (e.g. 10m, 1h, 20:30)",
        "zh": "提醒时间 (例如: 10m, 1h, 20:30)",
        "es": "Tiempo del recordatorio (ej. 10m, 1h, 20:30)",
        "pt": "Tempo do lembrete (ex: 10m, 1h, 20:30)",
        "fr": "Délai de rappel (ex : 10m, 1h, 20:30)"
    },
    "Nội dung cần nhắc": {
        "vi": "Nội dung cần nhắc",
        "en": "Reminder message",
        "zh": "提醒内容",
        "es": "Mensaje del recordatorio",
        "pt": "Conteúdo do lembrete",
        "fr": "Contenu du rappel"
    },
    "Gửi tin nhắn riêng qua DM": {
        "vi": "Gửi tin nhắn riêng qua DM",
        "en": "Send as private DM",
        "zh": "通过私信发送",
        "es": "Enviar por mensaje directo (DM)",
        "pt": "Enviar por DM privada",
        "fr": "Envoyer par message privé (DM)"
    },
    "ID của lời nhắc (xem qua /reminders)": {
        "vi": "ID của lời nhắc (xem qua /reminders)",
        "en": "Reminder ID (check via /reminders)",
        "zh": "提醒 ID (可通过 /reminders 查看)",
        "es": "ID del recordatorio (ver en /reminders)",
        "pt": "ID do lembrete (ver em /reminders)",
        "fr": "ID du rappel (voir via /reminders)"
    },
    "Số điểm XP mới": {
        "vi": "Số điểm XP mới",
        "en": "New XP amount",
        "zh": "新的经验值数值",
        "es": "Nueva cantidad de XP",
        "pt": "Nova quantia de XP",
        "fr": "Nouveau montant d'XP"
    },
    "Thời lượng (10m, 2h, 1d)": {
        "vi": "Thời lượng (10m, 2h, 1d)",
        "en": "Duration (10m, 2h, 1d)",
        "zh": "持续时间 (例如: 10m, 2h, 1d)",
        "es": "Duración (10m, 2h, 1d)",
        "pt": "Duração (10m, 2h, 1d)",
        "fr": "Durée (10m, 2h, 1d)"
    },
    "Thời gian (vd: 1m, 1h, 1d)": {
        "vi": "Thời gian (vd: 1m, 1h, 1d)",
        "en": "Duration (e.g. 1m, 1h, 1d)",
        "zh": "时长 (例如: 1m, 1h, 1d)",
        "es": "Tiempo (ej. 1m, 1h, 1d)",
        "pt": "Tempo (ex: 1m, 1h, 1d)",
        "fr": "Délai (ex : 1m, 1h, 1d)"
    },
    "Số người thắng": {
        "vi": "Số người thắng",
        "en": "Number of winners",
        "zh": "获胜者人数",
        "es": "Número de ganadores",
        "pt": "Número de vencedores",
        "fr": "Nombre de gagnants"
    },
    "Phần thưởng": {
        "vi": "Phần thưởng",
        "en": "Prize / Reward",
        "zh": "奖品 / 奖励",
        "es": "Premio",
        "pt": "Prêmio",
        "fr": "Prix / Récompense"
    },
    "ID của tin nhắn Giveaway": {
        "vi": "ID của tin nhắn Giveaway",
        "en": "Giveaway message ID",
        "zh": "抽奖消息 ID",
        "es": "ID del mensaje del sorteo",
        "pt": "ID da mensagem do sorteio",
        "fr": "ID du message du concours"
    },
    "Role cần xem thông tin": {
        "vi": "Role cần xem thông tin",
        "en": "Role to inspect",
        "zh": "要查看的身份组",
        "es": "Rol a consultar",
        "pt": "Cargo a consultar",
        "fr": "Rôle à inspecter"
    },
    "Kênh cần xem thông tin (mặc định: kênh hiện tại)": {
        "vi": "Kênh cần xem thông tin (mặc định: kênh hiện tại)",
        "en": "Channel to inspect (default: current)",
        "zh": "要查看的频道 (默认: 当前频道)",
        "es": "Canal a consultar (por defecto: actual)",
        "pt": "Canal a consultar (padrão: atual)",
        "fr": "Salon à inspecter (par défaut : actuel)"
    },
    "Tên bài hát để tìm kiếm, hoặc link YouTube": {
        "vi": "Tên bài hát để tìm kiếm, hoặc link YouTube",
        "en": "Song name or YouTube / Spotify link",
        "zh": "歌曲名称或 YouTube / Spotify 链接",
        "es": "Nombre de la canción o enlace",
        "pt": "Nome da música ou link",
        "fr": "Nom de la chanson ou lien"
    },
    "Tên bài hát cần tìm kiếm": {
        "vi": "Tên bài hát cần tìm kiếm",
        "en": "Song name to search",
        "zh": "要搜索的歌曲名称",
        "es": "Nombre de la canción a buscar",
        "pt": "Nome da música para buscar",
        "fr": "Nom de la chanson à rechercher"
    },
    "Hành động (name, add, play, show, remove, removesong)": {
        "vi": "Hành động (name, add, play, show, remove, removesong)",
        "en": "Action (name, add, play, show, remove, removesong)",
        "zh": "操作类型 (name, add, play, show, remove, removesong)",
        "es": "Acción (name, add, play, show, remove, removesong)",
        "pt": "Ação (name, add, play, show, remove, removesong)",
        "fr": "Action (name, add, play, show, remove, removesong)"
    },
    "Tên playlist": {
        "vi": "Tên playlist",
        "en": "Playlist name",
        "zh": "歌单名称",
        "es": "Nombre de la lista",
        "pt": "Nome da playlist",
        "fr": "Nom de la playlist"
    },
    "Link nhạc hoặc tên bài hát (dành cho add)": {
        "vi": "Link nhạc hoặc tên bài hát (dành cho add)",
        "en": "Song link or name (for add)",
        "zh": "歌曲链接或名称 (用于添加)",
        "es": "Enlace o nombre de canción",
        "pt": "Link ou nome da música",
        "fr": "Lien ou nom de la chanson"
    },
    "Số tiền cần nạp (hoặc gõ 'all' / 'max')": {
        "vi": "Số tiền cần nạp (hoặc gõ 'all' / 'max')",
        "en": "Amount to deposit (or 'all' / 'max')",
        "zh": "存款金额 (或输入 'all' / 'max')",
        "es": "Cantidad a depositar (o 'all')",
        "pt": "Quantia a depositar (ou 'all')",
        "fr": "Montant à déposer (ou 'all')"
    },
    "Số tiền cần rút (hoặc gõ 'all' / 'max')": {
        "vi": "Số tiền cần rút (hoặc gõ 'all' / 'max')",
        "en": "Amount to withdraw (or 'all' / 'max')",
        "zh": "取款金额 (或输入 'all' / 'max')",
        "es": "Cantidad a retirar (o 'all')",
        "pt": "Quantia a sacar (ou 'all')",
        "fr": "Montant à retirer (ou 'all')"
    },
    "Số tiền cần chuyển": {
        "vi": "Số tiền cần chuyển",
        "en": "Amount to transfer",
        "zh": "转账金额",
        "es": "Cantidad a transferir",
        "pt": "Quantia a transferir",
        "fr": "Montant à transférer"
    },
    "Số tiền cược": {
        "vi": "Số tiền cược",
        "en": "Bet amount",
        "zh": "下注金额",
        "es": "Cantidad apostada",
        "pt": "Quantia da aposta",
        "fr": "Montant de la mise"
    },
    "Chọn Mặt Ngửa (heads) hoặc Mặt Sấp (tails)": {
        "vi": "Chọn Mặt Ngửa (heads) hoặc Mặt Sấp (tails)",
        "en": "Pick Heads (heads) or Tails (tails)",
        "zh": "选择正面 (heads) 或反面 (tails)",
        "es": "Elige Cara (heads) o Cruz (tails)",
        "pt": "Escolha Cara (heads) ou Coroa (tails)",
        "fr": "Choisissez Pile (tails) ou Face (heads)"
    },
    "ID vật phẩm trong shop": {
        "vi": "ID vật phẩm trong shop",
        "en": "Shop item ID",
        "zh": "商店道具 ID",
        "es": "ID del artículo en la tienda",
        "pt": "ID do item na loja",
        "fr": "ID de l'article dans la boutique"
    },
    "Số người tối đa (0 = vô hạn)": {
        "vi": "Số người tối đa (0 = vô hạn)",
        "en": "Max user limit (0 = unlimited)",
        "zh": "最大人数上限 (0 = 无限制)",
        "es": "Límite de usuarios (0 = ilimitado)",
        "pt": "Limite de usuários (0 = ilimitado)",
        "fr": "Limite d'utilisateurs (0 = illimité)"
    },
    "Tên phòng mới": {
        "vi": "Tên phòng mới",
        "en": "New channel name",
        "zh": "新语音房名称",
        "es": "Nuevo nombre del canal",
        "pt": "Novo nome da sala",
        "fr": "Nouveau nom du salon"
    },
    "Từ khóa kích hoạt (VD: !ip)": {
        "vi": "Từ khóa kích hoạt (VD: !ip)",
        "en": "Trigger keyword (e.g. !ip)",
        "zh": "触发关键词 (例如: !ip)",
        "es": "Palabra clave activadora (ej. !ip)",
        "pt": "Palavra-chave ativadora (ex: !ip)",
        "fr": "Mot-clé déclencheur (ex : !ip)"
    },
    "Nội dung phản hồi (hỗ trợ {user}, {server})": {
        "vi": "Nội dung phản hồi (hỗ trợ {user}, {server})",
        "en": "Response content (supports {user}, {server})",
        "zh": "回复内容 (支持 {user}, {server})",
        "es": "Contenido de respuesta (admite {user}, {server})",
        "pt": "Conteúdo da resposta (suporta {user}, {server})",
        "fr": "Contenu de la réponse (supporte {user}, {server})"
    },
    "Từ khóa của lệnh cần xóa": {
        "vi": "Từ khóa của lệnh cần xóa",
        "en": "Trigger keyword of command to delete",
        "zh": "要删除的指令触发词",
        "es": "Palabra clave a eliminar",
        "pt": "Palavra-chave a excluir",
        "fr": "Mot-clé de la commande à supprimer"
    },
    "Số lượng tin nhắn cần tóm tắt (10-50)": {
        "vi": "Số lượng tin nhắn cần tóm tắt (10-50)",
        "en": "Number of messages to summarize (10-50)",
        "zh": "需要总结的消息数量 (10-50)",
        "es": "Número de mensajes a resumir (10-50)",
        "pt": "Número de mensagens a resumir (10-50)",
        "fr": "Nombre de messages à résumer (10-50)"
    },
    "Lý do": {
        "vi": "Lý do",
        "en": "Reason",
        "zh": "原因",
        "es": "Razón",
        "pt": "Motivo",
        "fr": "Raison"
    },
    "Lý do đuổi": {
        "vi": "Lý do đuổi",
        "en": "Kick reason",
        "zh": "踢出原因",
        "es": "Razón de expulsión",
        "pt": "Motivo da expulsão",
        "fr": "Raison de l'expulsion"
    },
    "Lý do cấm": {
        "vi": "Lý do cấm",
        "en": "Ban reason",
        "zh": "封禁原因",
        "es": "Razón de baneo",
        "pt": "Motivo do banimento",
        "fr": "Raison du bannissement"
    },
    "Lý do hủy cấm": {
        "vi": "Lý do hủy cấm",
        "en": "Unban reason",
        "zh": "解封原因",
        "es": "Razón de desbaneo",
        "pt": "Motivo do desbanimento",
        "fr": "Raison du débannissement"
    },
    "Lý do khóa chat": {
        "vi": "Lý do khóa chat",
        "en": "Timeout reason",
        "zh": "禁言原因",
        "es": "Razón de silencio",
        "pt": "Motivo do castigo",
        "fr": "Raison de l'exclusion"
    },
    "Lý do cảnh cáo": {
        "vi": "Lý do cảnh cáo",
        "en": "Warning reason",
        "zh": "警告原因",
        "es": "Razón de advertencia",
        "pt": "Motivo do aviso",
        "fr": "Raison de l'avertissement"
    },
    "Số ngày tin nhắn cần xóa (0-7)": {
        "vi": "Số ngày tin nhắn cần xóa (0-7)",
        "en": "Days of messages to delete (0-7)",
        "zh": "清除消息的天数 (0-7)",
        "es": "Días de mensajes a borrar (0-7)",
        "pt": "Dias de mensagens a apagar (0-7)",
        "fr": "Jours de messages à supprimer (0-7)"
    },
    "ID cảnh cáo cần xóa": {
        "vi": "ID cảnh cáo cần xóa",
        "en": "Warning ID to delete",
        "zh": "要删除的警告 ID",
        "es": "ID de advertencia a eliminar",
        "pt": "ID do aviso a excluir",
        "fr": "ID de l'avertissement à supprimer"
    },
    "Số tin nhắn cần xóa (1-100)": {
        "vi": "Số tin nhắn cần xóa (1-100)",
        "en": "Number of messages to delete (1-100)",
        "zh": "要删除的消息数量 (1-100)",
        "es": "Mensajes a borrar (1-100)",
        "pt": "Mensagens a apagar (1-100)",
        "fr": "Messages à supprimer (1-100)"
    },
    "Chỉ xóa tin của người này": {
        "vi": "Chỉ xóa tin của người này",
        "en": "Only delete messages from this user",
        "zh": "仅删除该用户的消息",
        "es": "Solo borrar mensajes de este usuario",
        "pt": "Apenas apagar mensagens deste usuário",
        "fr": "Supprimer uniquement les messages de cet utilisateur"
    },
    "Thời gian chờ (0 = tắt)": {
        "vi": "Thời gian chờ (0 = tắt)",
        "en": "Cooldown seconds (0 = disable)",
        "zh": "慢速模式等待秒数 (0 = 关闭)",
        "es": "Segundos de espera (0 = desactivar)",
        "pt": "Segundos de espera (0 = desativar)",
        "fr": "Délai en secondes (0 = désactiver)"
    },
    "Kênh áp dụng": {
        "vi": "Kênh áp dụng",
        "en": "Target channel",
        "zh": "目标频道",
        "es": "Canal objetivo",
        "pt": "Canal alvo",
        "fr": "Salon cible"
    },
    "Kênh cần khóa": {
        "vi": "Kênh cần khóa",
        "en": "Channel to lock",
        "zh": "要锁定的频道",
        "es": "Canal a bloquear",
        "pt": "Canal a trancar",
        "fr": "Salon à verrouiller"
    },
    "Kênh cần mở khóa": {
        "vi": "Kênh cần mở khóa",
        "en": "Channel to unlock",
        "zh": "要解锁的频道",
        "es": "Canal a desbloquear",
        "pt": "Canal a destrancar",
        "fr": "Salon à déverrouiller"
    },
    "Ngày (1-31)": {
        "vi": "Ngày (1-31)",
        "en": "Day (1-31)",
        "zh": "日期 (1-31)",
        "es": "Día (1-31)",
        "pt": "Dia (1-31)",
        "fr": "Jour (1-31)"
    },
    "Tháng (1-12)": {
        "vi": "Tháng (1-12)",
        "en": "Month (1-12)",
        "zh": "月份 (1-12)",
        "es": "Mes (1-12)",
        "pt": "Mês (1-12)",
        "fr": "Mois (1-12)"
    },
    "Năm sinh (tùy chọn)": {
        "vi": "Năm sinh (tùy chọn)",
        "en": "Birth year (optional)",
        "zh": "出生年份 (可选)",
        "es": "Año de nacimiento (opcional)",
        "pt": "Ano de nascimento (opcional)",
        "fr": "Année de naissance (facultatif)"
    }
}

# Parameter placeholder translations for usage strings
PARAM_BRACKETS = {
    "[câu hỏi]": {"en": "[question]", "zh": "[问题]", "es": "[pregunta]", "pt": "[pergunta]", "fr": "[question]"},
    "[các lựa chọn]": {"en": "[options]", "zh": "[选项列表]", "es": "[opciones]", "pt": "[opções]", "fr": "[options]"},
    "[số]": {"en": "[max]", "zh": "[最大值]", "es": "[máx]", "pt": "[máx]", "fr": "[max]"},
    "[thời gian]": {"en": "[time]", "zh": "[时间]", "es": "[tiempo]", "pt": "[tempo]", "fr": "[délai]"},
    "[nội dung]": {"en": "[content]", "zh": "[内容]", "es": "[contenido]", "pt": "[conteúdo]", "fr": "[message]"},
    "[thành viên]": {"en": "[member]", "zh": "[成员]", "es": "[miembro]", "pt": "[membro]", "fr": "[membre]"},
    "[số tiền]": {"en": "[amount]", "zh": "[金额]", "es": "[cantidad]", "pt": "[quantia]", "fr": "[montant]"},
    "[lý do]": {"en": "[reason]", "zh": "[原因]", "es": "[razón]", "pt": "[motivo]", "fr": "[raison]"},
    "[kênh]": {"en": "[channel]", "zh": "[频道]", "es": "[canal]", "pt": "[canal]", "fr": "[salon]"},
    "[bài hát]": {"en": "[song]", "zh": "[歌曲]", "es": "[canción]", "pt": "[música]", "fr": "[chanson]"},
    "[lựa chọn]": {"en": "[choice]", "zh": "[选项]", "es": "[elección]", "pt": "[escolha]", "fr": "[choix]"},
    "[ngày]": {"en": "[day]", "zh": "[日]", "es": "[día]", "pt": "[dia]", "fr": "[jour]"},
    "[tháng]": {"en": "[month]", "zh": "[月]", "es": "[mes]", "pt": "[mês]", "fr": "[mois]"},
    "[năm]": {"en": "[year]", "zh": "[年]", "es": "[año]", "pt": "[ano]", "fr": "[année]"},
    "[từ khóa]": {"en": "[keyword]", "zh": "[触发词]", "es": "[palabra_clave]", "pt": "[palavra_chave]", "fr": "[mot_clé]"},
    "[phần thưởng]": {"en": "[prize]", "zh": "[奖品]", "es": "[premio]", "pt": "[prêmio]", "fr": "[prix]"},
    "[số người thắng]": {"en": "[winners]", "zh": "[获胜人数]", "es": "[ganadores]", "pt": "[vencedores]", "fr": "[gagnants]"},
    "[câu hỏi cần hỏi]": {"en": "[question]", "zh": "[问题]", "es": "[pregunta]", "pt": "[pergunta]", "fr": "[question]"},
    "[số tin nhắn]": {"en": "[limit]", "zh": "[数量]", "es": "[límite]", "pt": "[limite]", "fr": "[limite]"},
    "[số tin]": {"en": "[amount]", "zh": "[数量]", "es": "[cantidad]", "pt": "[quantia]", "fr": "[quantité]"},
    "[giây]": {"en": "[seconds]", "zh": "[秒数]", "es": "[segundos]", "pt": "[segundos]", "fr": "[secondes]"},
    "[số người]": {"en": "[limit]", "zh": "[人数]", "es": "[límite]", "pt": "[limite]", "fr": "[limite]"},
    "[tên mới]": {"en": "[new_name]", "zh": "[新名称]", "es": "[nuevo_nombre]", "pt": "[novo_nome]", "fr": "[nouveau_nom]"},
    "[tên]": {"en": "[name]", "zh": "[名称]", "es": "[nombre]", "pt": "[nome]", "fr": "[nom]"},
    "[link/tên bài]": {"en": "[link/song]", "zh": "[链接/歌名]", "es": "[enlace/canción]", "pt": "[link/música]", "fr": "[lien/chanson]"},
    "[tên bài / link]": {"en": "[song / link]", "zh": "[歌名 / 链接]", "es": "[canción / enlace]", "pt": "[música / link]", "fr": "[chanson / lien]"},
    "[mặt]": {"en": "[side]", "zh": "[面]", "es": "[lado]", "pt": "[lado]", "fr": "[côté]"},
    "[item_id]": {"en": "[item_id]", "zh": "[道具ID]", "es": "[item_id]", "pt": "[item_id]", "fr": "[item_id]"},
    "[xp]": {"en": "[xp]", "zh": "[经验值]", "es": "[xp]", "pt": "[xp]", "fr": "[xp]"},
    "[id]": {"en": "[id]", "zh": "[ID]", "es": "[id]", "pt": "[id]", "fr": "[id]"},
    "[warn_id]": {"en": "[warn_id]", "zh": "[警告ID]", "es": "[warn_id]", "pt": "[warn_id]", "fr": "[warn_id]"},
    "[message_id]": {"en": "[message_id]", "zh": "[消息ID]", "es": "[message_id]", "pt": "[message_id]", "fr": "[message_id]"}
}

# Example translations
EXAMPLE_TRANS = {
    "/poll Tối nay ăn gì?": {
        "en": "/poll What should we play tonight?",
        "zh": "/poll 今晚吃什么？",
        "es": "/poll ¿Qué jugamos hoy?",
        "pt": "/poll O que vamos jogar hoje?",
        "fr": "/poll À quoi joue-t-on ce soir ?"
    },
    "/choose Pizza, Burger, Sushi": {
        "en": "/choose Pizza, Burger, Sushi",
        "zh": "/choose 披萨, 汉堡, 寿司",
        "es": "/choose Pizza, Hamburguesa, Sushi",
        "pt": "/choose Pizza, Hambúrguer, Sushi",
        "fr": "/choose Pizza, Burger, Sushi"
    },
    "/remindme 30m Đi họp": {
        "en": "/remindme 30m Join meeting",
        "zh": "/remindme 30m 参加会议",
        "es": "/remindme 30m Ir a la reunión",
        "pt": "/remindme 30m Ir para a reunião",
        "fr": "/remindme 30m Rejoindre la réunion"
    },
    "/ask Zeryn là ai?": {
        "en": "/ask Who is Zeryn?",
        "zh": "/ask Zeryn 是谁？",
        "es": "/ask ¿Quién es Zeryn?",
        "pt": "/ask Quem é Zeryn?",
        "fr": "/ask Qui est Zeryn ?"
    },
    "/warn @User Spam từ cấm": {
        "en": "/warn @User Banned words spam",
        "zh": "/warn @User 敏感词刷屏",
        "es": "/warn @User Spam de palabras prohibidas",
        "pt": "/warn @User Spam de palavras proibidas",
        "fr": "/warn @User Spam de mots interdits"
    }
}

# Category translations map
CAT_MAP = {
    "Tổng quan": {
        "vi": "Tổng quan", "en": "Overview", "zh": "概览", "es": "General", "pt": "Geral", "fr": "Général"
    },
    "Tổng quát": {
        "vi": "Tổng quát", "en": "Overview", "zh": "概览", "es": "General", "pt": "Geral", "fr": "Général"
    },
    "Reaction Roles": {
        "vi": "Reaction Roles", "en": "Reaction Roles", "zh": "反应身份组", "es": "Roles de Reacción", "pt": "Cargos por Reação", "fr": "Rôles par Réaction"
    },
    "Auto Roles": {
        "vi": "Tự động cấp Role", "en": "Auto Roles", "zh": "自动身份组", "es": "Auto Roles", "pt": "Auto Cargos", "fr": "Rôles Automatiques"
    },
    "Automods": {
        "vi": "Kiểm duyệt tự động", "en": "Automods", "zh": "自动审核", "es": "AutoMod", "pt": "AutoMod", "fr": "Modération Auto"
    },
    "Verify Gate": {
        "vi": "Xác thực thành viên", "en": "Verify Gate", "zh": "验证门禁", "es": "Puerta de Verificación", "pt": "Portão de Verificação", "fr": "Porte de Vérification"
    },
    "Leveling": {
        "vi": "Cấp bậc & XP", "en": "Leveling & XP", "zh": "等级与经验", "es": "Niveles y XP", "pt": "Níveis e XP", "fr": "Niveaux & XP"
    },
    "Giveaways": {
        "vi": "Phát quà Giveaway", "en": "Giveaways", "zh": "抽奖活动", "es": "Sorteos", "pt": "Sorteios", "fr": "Concours Giveaways"
    },
    "Tickets": {
        "vi": "Hỗ trợ Tickets", "en": "Support Tickets", "zh": "客服工单", "es": "Tickets de Soporte", "pt": "Tickets de Suporte", "fr": "Tickets de Support"
    },
    "Thông tin": {
        "vi": "Thông tin", "en": "Information", "zh": "信息", "es": "Información", "pt": "Informações", "fr": "Informations"
    },
    "Music 🎵": {
        "vi": "Âm nhạc 🎵", "en": "Music 🎵", "zh": "音乐 🎵", "es": "Música 🎵", "pt": "Música 🎵", "fr": "Musique 🎵"
    },
    "Kinh tế & Shop": {
        "vi": "Kinh tế & Shop", "en": "Economy & Shop", "zh": "经济与商店", "es": "Economía y Tienda", "pt": "Economia e Loja", "fr": "Économie & Boutique"
    },
    "Voice Tạm thời": {
        "vi": "Voice Tạm thời", "en": "Temp Voice Hub", "zh": "动态语音房", "es": "Voz Temporal", "pt": "Voz Temporária", "fr": "Salons Temporaires"
    },
    "Lệnh Tùy biến": {
        "vi": "Lệnh Tùy biến", "en": "Custom Commands", "zh": "自定义指令", "es": "Comandos Personalizados", "pt": "Comandos Personalizados", "fr": "Commandes Personnalisées"
    },
    "Trợ lý AI": {
        "vi": "Trợ lý AI", "en": "AI Assistant", "zh": "AI 智能助手", "es": "Asistente AI", "pt": "Assistente AI", "fr": "Assistant IA"
    },
    "Điều hành": {
        "vi": "Điều hành", "en": "Moderation", "zh": "管理", "es": "Moderación", "pt": "Moderação", "fr": "Modération"
    },
    "Vui vẻ & Tình cảm": {
        "vi": "Vui vẻ & Tình cảm", "en": "Fun & Social", "zh": "趣味与社交", "es": "Diversión y Social", "pt": "Diversão e Social", "fr": "Divertissement & Social"
    },
    "Sinh nhật": {
        "vi": "Sinh nhật", "en": "Birthday", "zh": "生日", "es": "Cumpleaños", "pt": "Aniversários", "fr": "Anniversaire"
    }
}

# Translate Discord preview content smartly per language
def localize_preview(preview, lang):
    if not preview:
        return preview
    p = copy.deepcopy(preview)
    ptype = p.get("type")
    
    if ptype == "text":
        t = p.get("text", "")
        # Common text translations
        if lang != "vi":
            # Translate common preview texts
            if "Đã xóa" in t:
                if lang == "en": t = t.replace("Đã xóa", "Deleted").replace("tin nhắn", "messages").replace("cảnh cáo", "warning").replace("ngày sinh của bạn", "your birthday")
                elif lang == "zh": t = t.replace("Đã xóa", "已删除").replace("tin nhắn", "条消息").replace("cảnh cáo", "警告").replace("ngày sinh của bạn", "您的生日设置")
                elif lang == "es": t = t.replace("Đã xóa", "Eliminado").replace("tin nhắn", "mensajes").replace("cảnh cáo", "advertencia").replace("ngày sinh của bạn", "tu fecha de cumpleaños")
                elif lang == "pt": t = t.replace("Đã xóa", "Apagado").replace("tin nhắn", "mensagens").replace("cảnh cáo", "aviso").replace("ngày sinh của bạn", "sua data de aniversário")
                elif lang == "fr": t = t.replace("Đã xóa", "Supprimé").replace("tin nhắn", "messages").replace("cảnh cáo", "avertissement").replace("ngày sinh của bạn", "votre date d'anniversaire")
            if "Tôi sẽ nhắc bạn" in t:
                if lang == "en": t = t.replace("Tôi sẽ nhắc bạn sau", "I will remind you in").replace("phút", "minutes")
                elif lang == "zh": t = t.replace("Tôi sẽ nhắc bạn sau", "我将在").replace("phút", "分钟后提醒您")
                elif lang == "es": t = t.replace("Tôi sẽ nhắc bạn sau", "Te recordaré en").replace("phút", "minutos")
                elif lang == "pt": t = t.replace("Tôi sẽ nhắc bạn sau", "Vou te lembrar em").replace("phút", "minutos")
                elif lang == "fr": t = t.replace("Tôi sẽ nhắc bạn sau", "Je vous rappellerai dans").replace("phút", "minutes")
            if "Đã gỡ khóa chat" in t:
                if lang == "en": t = t.replace("Đã gỡ khóa chat cho", "Removed timeout for")
                elif lang == "zh": t = t.replace("Đã gỡ khóa chat cho", "已解除禁言：")
                elif lang == "es": t = t.replace("Đã gỡ khóa chat cho", "Se quitó el silencio a")
                elif lang == "pt": t = t.replace("Đã gỡ khóa chat cho", "Silêncio removido para")
                elif lang == "fr": t = t.replace("Đã gỡ khóa chat cho", "Exclusion retirée pour")
            if "đã bị khóa chat" in t:
                if lang == "en": t = t.replace("đã bị khóa chat", "has been timed out")
                elif lang == "zh": t = t.replace("đã bị khóa chat", "已被禁言")
                elif lang == "es": t = t.replace("đã bị khóa chat", "ha sido silenciado")
                elif lang == "pt": t = t.replace("đã bị khóa chat", "foi castigado")
                elif lang == "fr": t = t.replace("đã bị khóa chat", "a été exclu")
            if "Đã kick" in t:
                if lang == "en": t = t.replace("Đã kick", "Kicked")
                elif lang == "zh": t = t.replace("Đã kick", "已踢出")
                elif lang == "es": t = t.replace("Đã kick", "Expulsado")
                elif lang == "pt": t = t.replace("Đã kick", "Expulso")
                elif lang == "fr": t = t.replace("Đã kick", "Expulsé")
            if "Đã ban" in t:
                if lang == "en": t = t.replace("Đã ban", "Banned")
                elif lang == "zh": t = t.replace("Đã ban", "已封禁")
                elif lang == "es": t = t.replace("Đã ban", "Baneado")
                elif lang == "pt": t = t.replace("Đã ban", "Banido")
                elif lang == "fr": t = t.replace("Đã ban", "Banni")
            if "Đã unban" in t:
                if lang == "en": t = t.replace("Đã unban", "Unbanned")
                elif lang == "zh": t = t.replace("Đã unban", "已解封")
                elif lang == "es": t = t.replace("Đã unban", "Desbaneado")
                elif lang == "pt": t = t.replace("Đã unban", "Desbanido")
                elif lang == "fr": t = t.replace("Đã unban", "Débanni")
            if "Đã bật slowmode" in t:
                if lang == "en": t = "🐌 Enabled slowmode: 5s."
                elif lang == "zh": t = "🐌 已开启慢速模式：5秒。"
                elif lang == "es": t = "🐌 Modo lento activado: 5s."
                elif lang == "pt": t = "🐌 Modo lento ativado: 5s."
                elif lang == "fr": t = "🐌 Mode lent activé : 5s."
            if "Kênh đã bị khóa" in t:
                if lang == "en": t = "🔒 Channel has been locked."
                elif lang == "zh": t = "🔒 频道已被锁定。"
                elif lang == "es": t = "🔒 El canal ha sido bloqueado."
                elif lang == "pt": t = "🔒 O canal foi trancado."
                elif lang == "fr": t = "🔒 Le salon a été verrouillé."
            if "Kênh đã được mở khóa" in t:
                if lang == "en": t = "🔓 Channel has been unlocked."
                elif lang == "zh": t = "🔓 频道已被解锁。"
                elif lang == "es": t = "🔓 El canal ha sido desbloqueado."
                elif lang == "pt": t = "🔓 O canal foi destrancado."
                elif lang == "fr": t = "🔓 Le salon a été déverrouillé."
            if "Bạn đã gieo được" in t:
                if lang == "en": t = t.replace("Bạn đã gieo được:", "You rolled:")
                elif lang == "zh": t = t.replace("Bạn đã gieo được:", "您掷出的点数：")
                elif lang == "es": t = t.replace("Bạn đã gieo được:", "Has obtenido:")
                elif lang == "pt": t = t.replace("Bạn đã gieo được:", "Você tirou:")
                elif lang == "fr": t = t.replace("Bạn đã gieo được:", "Vous avez obtenu :")
            if "Tôi chọn:" in t:
                if lang == "en": t = t.replace("Tôi chọn:", "I choose:")
                elif lang == "zh": t = t.replace("Tôi chọn:", "我的选择是：")
                elif lang == "es": t = t.replace("Tôi chọn:", "Yo elijo:")
                elif lang == "pt": t = t.replace("Tôi chọn:", "Eu escolho:")
                elif lang == "fr": t = t.replace("Tôi chọn:", "Je choisis :")
            if "ôm" in t:
                if lang == "en": t = "🤗 @User gives @Friend a warm hug!"
                elif lang == "zh": t = "🤗 @User 给了 @Friend 一个温暖的拥抱！"
                elif lang == "es": t = "🤗 ¡@User le da un cálido abrazo a @Friend!"
                elif lang == "pt": t = "🤗 @User dá um abraço caloroso em @Friend!"
                elif lang == "fr": t = "🤗 @User fait un gros câlin chaleureux à @Friend !"
            if "xoa đầu" in t:
                if lang == "en": t = "😊 @User pats @Friend on the head!"
                elif lang == "zh": t = "😊 @User 摸了摸 @Friend 的头！"
                elif lang == "es": t = "😊 ¡@User le acaricia la cabeza a @Friend!"
                elif lang == "pt": t = "😊 @User faz cafuné na cabeça de @Friend!"
                elif lang == "fr": t = "😊 @User tapote la tête de @Friend !"
            if "hôn" in t and "kiss" in t.lower() or "😘" in t:
                if lang == "en": t = "😘 @User kisses @Crush! 💋"
                elif lang == "zh": t = "😘 @User 亲吻了 @Crush！💋"
                elif lang == "es": t = "😘 ¡@User besa a @Crush! 💋"
                elif lang == "pt": t = "😘 @User beija @Crush! 💋"
                elif lang == "fr": t = "😘 @User embrasse @Crush ! 💋"
            if "tát" in t or "👋" in t:
                if lang == "en": t = "👋 @User slaps @Friend! Ouch!"
                elif lang == "zh": t = "👋 @User 拍打了 @Friend！哎呀！"
                elif lang == "es": t = "👋 ¡@User abofetea a @Friend! ¡Ay!"
                elif lang == "pt": t = "👋 @User dá um tapa em @Friend! Ai!"
                elif lang == "fr": t = "👋 @User donne une gifle à @Friend ! Aïe !"
            if "đút" in t or "🍙" in t:
                if lang == "en": t = "🍙 @User feeds @Friend! Delicious?"
                elif lang == "zh": t = "🍙 @User 正在投喂 @Friend！好吃吗？"
                elif lang == "es": t = "🍙 ¡@User alimenta a @Friend! ¿Delicioso?"
                elif lang == "pt": t = "🍙 @User alimenta @Friend! Gostoso?"
                elif lang == "fr": t = "🍙 @User donne à manger à @Friend ! C'est bon ?"
            if "cưng nựng" in t or "🧸" in t:
                if lang == "en": t = "🧸 @User cuddles @Friend sweetly!"
                elif lang == "zh": t = "🧸 @User 正在甜蜜依偎着 @Friend！"
                elif lang == "es": t = "🧸 ¡@User se acurruca dulcemente con @Friend!"
                elif lang == "pt": t = "🧸 @User abraça carinhosamente @Friend!"
                elif lang == "fr": t = "🧸 @User câline tendrement @Friend !"
            if "Chọc má" in t or "chọc" in t or "👉" in t:
                if lang == "en": t = "👉 @User pokes @Friend!"
                elif lang == "zh": t = "👉 @User 戳了戳 @Friend 的脸蛋！"
                elif lang == "es": t = "👉 ¡@User le pica los mofletes a @Friend!"
                elif lang == "pt": t = "👉 @User cutuca @Friend!"
                elif lang == "fr": t = "👉 @User taquine @Friend !"
            if "đập tay" in t or "✋" in t:
                if lang == "en": t = "✋ @User high-fives @Friend! 🎉"
                elif lang == "zh": t = "✋ @User 与 @Friend 欢呼击掌！🎉"
                elif lang == "es": t = "✋ ¡@User choca los cinco con @Friend! 🎉"
                elif lang == "pt": t = "✋ @User toca aqui com @Friend! 🎉"
                elif lang == "fr": t = "✋ @User tape dans la main de @Friend ! 🎉"
            if "khóc" in t or "😢" in t:
                if lang == "en": t = "😢 @User is crying... someone comfort them!"
                elif lang == "zh": t = "😢 @User 正在哭泣... 快去安慰一下吧！"
                elif lang == "es": t = "😢 @User está llorando... ¡que alguien le consuele!"
                elif lang == "pt": t = "😢 @User está chorando... alguém conforte ele(a)!"
                elif lang == "fr": t = "😢 @User est en train de pleurer... consolez-le !"
            if "nhảy múa" in t or "💃" in t:
                if lang == "en": t = "💃 @User is dancing joyfully!"
                elif lang == "zh": t = "💃 @User 正在欢快地跳舞！"
                elif lang == "es": t = "💃 ¡@User está bailando alegremente!"
                elif lang == "pt": t = "💃 @User está dançando alegremente!"
                elif lang == "fr": t = "💃 @User danse joyeusement !"
            if "ly hôn" in t or "💔" in t:
                if lang == "en": t = "💔 @User has successfully divorced."
                elif lang == "zh": t = "💔 @User 已成功办理离婚。"
                elif lang == "es": t = "💔 @User se ha divorciado con éxito."
                elif lang == "pt": t = "💔 @User se divorciou com sucesso."
                elif lang == "fr": t = "💔 @User a divorcé avec succès."
            if "Đã lưu ngày sinh" in t:
                if lang == "en": t = t.replace("Đã lưu ngày sinh của bạn:", "Saved your birthday:")
                elif lang == "zh": t = t.replace("Đã lưu ngày sinh của bạn:", "已保存您的生日：")
                elif lang == "es": t = t.replace("Đã lưu ngày sinh của bạn:", "Se guardó tu cumpleaños:")
                elif lang == "pt": t = t.replace("Đã lưu ngày sinh của bạn:", "Seu aniversário foi salvo:")
                elif lang == "fr": t = t.replace("Đã lưu ngày sinh của bạn:", "Date d'anniversaire enregistrée :")
        p["text"] = t

    elif ptype == "embed":
        title = p.get("title", "")
        desc = p.get("desc", "")
        if lang != "vi":
            if "Danh sách lệnh" in title:
                if lang == "en": title = "📖 Command List"
                elif lang == "zh": title = "📖 机器人指令列表"
                elif lang == "es": title = "📖 Lista de Comandos"
                elif lang == "pt": title = "📖 Lista de Comandos"
                elif lang == "fr": title = "📖 Liste des Commandes"
            if "Thành viên máy chủ" in title or "Thành viên server" in title:
                if lang == "en": title = "👥 Server Members"
                elif lang == "zh": title = "👥 服务器成员统计"
                elif lang == "es": title = "👥 Miembros del Servidor"
                elif lang == "pt": title = "👥 Membros do Servidor"
                elif lang == "fr": title = "👥 Membres du Serveur"
            if "Bình chọn" in title:
                if lang == "en": title = "📊 Quick Poll"
                elif lang == "zh": title = "📊 快速投票"
                elif lang == "es": title = "📊 Encuesta Rápida"
                elif lang == "pt": title = "📊 Votação Rápida"
                elif lang == "fr": title = "📊 Sondage Rapide"
            if "Cảnh Cáo" in title or "Cảnh báo" in title:
                if lang == "en": title = "⚠️ Member Warning"
                elif lang == "zh": title = "⚠️ 成员警告通知"
                elif lang == "es": title = "⚠️ Advertencia de Miembro"
                elif lang == "pt": title = "⚠️ Aviso de Membro"
                elif lang == "fr": title = "⚠️ Avertissement de Membre"
            if "Lời cầu hôn" in title:
                if lang == "en": title = "💍 Marriage Proposal"
                elif lang == "zh": title = "💍 求婚互动"
                elif lang == "es": title = "💍 Propuesta de Matrimonio"
                elif lang == "pt": title = "💍 Pedido de Casamento"
                elif lang == "fr": title = "💍 Demande en Mariage"
            if "Sinh nhật sắp tới" in title:
                if lang == "en": title = "🎂 Upcoming Birthdays"
                elif lang == "zh": title = "🎂 即将到来的生日"
                elif lang == "es": title = "🎂 Próximos Cumpleaños"
                elif lang == "pt": title = "🎂 Próximos Aniversários"
                elif lang == "fr": title = "🎂 Prochains Anniversaires"
            if "Số dư" in title:
                if lang == "en": title = "💰 Account Balance"
                elif lang == "zh": title = "💰 账户资产余额"
                elif lang == "es": title = "💰 Saldo de la Cuenta"
                elif lang == "pt": title = "💰 Saldo da Conta"
                elif lang == "fr": title = "💰 Solde du Compte"
            if "Trợ lý AI" in title or "AI Assistant" in title:
                if lang == "zh": title = "🤖 AI 智能助手解答"

            # Localize fields
            if "fields" in p:
                for f in p["fields"]:
                    fn = f.get("name", "")
                    if "Tên" in fn:
                        if lang == "en": f["name"] = "📋 Name"
                        elif lang == "zh": f["name"] = "📋 服务器名称"
                        elif lang == "es": f["name"] = "📋 Nombre"
                        elif lang == "pt": f["name"] = "📋 Nome"
                        elif lang == "fr": f["name"] = "📋 Nom"
                    elif "Chủ sở hữu" in fn:
                        if lang == "en": f["name"] = "👑 Owner"
                        elif lang == "zh": f["name"] = "👑 服务器拥有者"
                        elif lang == "es": f["name"] = "👑 Propietario"
                        elif lang == "pt": f["name"] = "👑 Dono"
                        elif lang == "fr": f["name"] = "👑 Propriétaire"
                    elif "Thành viên" in fn:
                        if lang == "en": f["name"] = "👥 Members"
                        elif lang == "zh": f["name"] = "👥 成员数"
                        elif lang == "es": f["name"] = "👥 Miembros"
                        elif lang == "pt": f["name"] = "👥 Membros"
                        elif lang == "fr": f["name"] = "👥 Membres"
                    elif "Ngày tạo" in fn:
                        if lang == "en": f["name"] = "📅 Created At"
                        elif lang == "zh": f["name"] = "📅 创建日期"
                        elif lang == "es": f["name"] = "📅 Fecha de Creación"
                        elif lang == "pt": f["name"] = "📅 Criado em"
                        elif lang == "fr": f["name"] = "📅 Créé le"
                    elif "Tham gia" in fn:
                        if lang == "en": f["name"] = "📅 Joined"
                        elif lang == "zh": f["name"] = "📅 加入时间"
                        elif lang == "es": f["name"] = "📅 Ingresó"
                        elif lang == "pt": f["name"] = "📅 Entrou em"
                        elif lang == "fr": f["name"] = "📅 Rejoint le"
                    elif "Tiền mặt" in fn or "Ví" in fn:
                        if lang == "en": f["name"] = "💵 Wallet Cash"
                        elif lang == "zh": f["name"] = "💵 钱包现金"
                        elif lang == "es": f["name"] = "💵 Billetera"
                        elif lang == "pt": f["name"] = "💵 Carteira"
                        elif lang == "fr": f["name"] = "💵 Portefeuille"
                    elif "Ngân hàng" in fn or "Bank" in fn:
                        if lang == "en": f["name"] = "🏦 Bank Account"
                        elif lang == "zh": f["name"] = "🏦 银行存款"
                        elif lang == "es": f["name"] = "🏦 Banco"
                        elif lang == "pt": f["name"] = "🏦 Banco"
                        elif lang == "fr": f["name"] = "🏦 Banque"
                    elif "Tổng tài sản" in fn:
                        if lang == "en": f["name"] = "💎 Net Worth"
                        elif lang == "zh": f["name"] = "💎 总资产"
                        elif lang == "es": f["name"] = "💎 Patrimonio Total"
                        elif lang == "pt": f["name"] = "💎 Patrimônio Total"
                        elif lang == "fr": f["name"] = "💎 Valeur Totale"
                    elif "Thành viên" in fn:
                        if lang == "en": f["name"] = "👤 Member"
                        elif lang == "zh": f["name"] = "👤 目标成员"
                    elif "Lý do" in fn:
                        if lang == "en": f["name"] = "📝 Reason"
                        elif lang == "zh": f["name"] = "📝 原因"
                        elif lang == "es": f["name"] = "📝 Razón"
                        elif lang == "pt": f["name"] = "📝 Motivo"
                        elif lang == "fr": f["name"] = "📝 Raison"
                    elif "Tổng cảnh cáo" in fn:
                        if lang == "en": f["name"] = "⚠️ Total Warns"
                        elif lang == "zh": f["name"] = "⚠️ 累计警告"
                        elif lang == "es": f["name"] = "⚠️ Advertencias"
                        elif lang == "pt": f["name"] = "⚠️ Total de Avisos"
                        elif lang == "fr": f["name"] = "⚠️ Total Avertissements"

            if "**Tổng quát:**" in desc:
                if lang == "en": desc = desc.replace("**Tổng quát:**", "**General:**")
                elif lang == "zh": desc = desc.replace("**Tổng quát:**", "**常规：**").replace("**Info:**", "**信息：**").replace("**Music:**", "**音乐：**")
                elif lang == "es": desc = desc.replace("**Tổng quát:**", "**General:**")
                elif lang == "pt": desc = desc.replace("**Tổng quát:**", "**Geral:**")
                elif lang == "fr": desc = desc.replace("**Tổng quát:**", "**Général :**")
            if "Thả cảm xúc bên dưới" in desc:
                if lang == "en": desc = "**What should we play tonight?**<br><br>React below to vote!"
                elif lang == "zh": desc = "**今晚玩什么游戏？**<br><br>点击下方表情参与投票！"
                elif lang == "es": desc = "**¿Qué jugamos hoy?**<br><br>¡Reacciona abajo para votar!"
                elif lang == "pt": desc = "**O que vamos jogar hoje?**<br><br>Reaja abaixo para votar!"
                elif lang == "fr": desc = "**À quoi joue-t-on ce soir ?**<br><br>Réagissez ci-dessous pour voter !"

        p["title"] = title
        p["desc"] = desc

    return p

# Master function to get localized commands data
def get_localized_commands_data(lang: str = "vi"):
    from i18n import t
    if lang not in ["vi", "en", "zh", "es", "pt", "fr"]:
        lang = "vi"

    localized_categories = []
    for cat in _COMMANDS_DATA:
        cat_title = cat.get("category", "")
        # Map category name
        trans_cat = CAT_MAP.get(cat_title, {}).get(lang, cat_title)
        
        commands_list = []
        for cmd in cat.get("commands", []):
            cmd_copy = dict(cmd)
            cmd_name = cmd["name"]
            cmd_key = f"cmd.{cmd_name.replace(' ', '_')}.desc"
            
            # 1. Localize description
            trans_desc = t(cmd_key, lang=lang)
            if trans_desc and trans_desc != cmd_key:
                cmd_copy["desc"] = trans_desc
            
            # 2. Localize usage syntax parameter brackets
            usage_str = cmd.get("usage", "")
            if lang != "vi" and usage_str:
                for brk, trans_map in PARAM_BRACKETS.items():
                    if brk in usage_str and lang in trans_map:
                        usage_str = usage_str.replace(brk, trans_map[lang])
            cmd_copy["usage"] = usage_str
            
            # 3. Localize example
            ex_str = cmd.get("example", "")
            if ex_str in EXAMPLE_TRANS and lang in EXAMPLE_TRANS[ex_str]:
                cmd_copy["example"] = EXAMPLE_TRANS[ex_str][lang]
            
            # 4. Localize arguments
            args_list = []
            for a in cmd.get("args", []):
                a_copy = dict(a)
                a_desc = a_copy.get("desc", "")
                if a_desc in ARG_TRANS and lang in ARG_TRANS[a_desc]:
                    a_copy["desc"] = ARG_TRANS[a_desc][lang]
                args_list.append(a_copy)
            cmd_copy["args"] = args_list
            
            # 5. Localize preview embed/text
            cmd_copy["preview"] = localize_preview(cmd.get("preview"), lang)
            
            commands_list.append(cmd_copy)
            
        localized_categories.append({
            "category": trans_cat,
            "icon": cat.get("icon", "📌"),
            "commands": commands_list
        })
        
    return localized_categories
