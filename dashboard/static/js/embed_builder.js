/* embed_builder.js — Live embed preview + save/load embeds */

const GUILD_ID = document.getElementById('embed-builder')?.dataset.guild;

// ─── State ────────────────────────────────────────────────────────────────────
let fields = [];

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const refs = {
  color:          () => document.getElementById('eb-color'),
  authorName:     () => document.getElementById('eb-author-name'),
  title:          () => document.getElementById('eb-title'),
  titleUrl:       () => document.getElementById('eb-title-url'),
  description:    () => document.getElementById('eb-description'),
  thumbnail:      () => document.getElementById('eb-thumbnail'),
  image:          () => document.getElementById('eb-image'),
  footerText:     () => document.getElementById('eb-footer'),
  footerIcon:     () => document.getElementById('eb-footer-icon'),
  embedName:      () => document.getElementById('eb-name'),

  // Preview
  prevBar:        () => document.getElementById('prev-bar'),
  prevAuthor:     () => document.getElementById('prev-author'),
  prevTitle:      () => document.getElementById('prev-title'),
  prevDesc:       () => document.getElementById('prev-desc'),
  prevFields:     () => document.getElementById('prev-fields'),
  prevThumbnail:  () => document.getElementById('prev-thumbnail'),
  prevImage:      () => document.getElementById('prev-image'),
  prevFooter:     () => document.getElementById('prev-footer'),
  prevFooterIcon: () => document.getElementById('prev-footer-icon'),
  prevFooterText: () => document.getElementById('prev-footer-text'),
};

// ─── Update preview in real time ──────────────────────────────────────────────
function updatePreview() {
  const color       = refs.color()?.value       || '#5865f2';
  const authorName  = refs.authorName()?.value  || '';
  const title       = refs.title()?.value       || '';
  const titleUrl    = refs.titleUrl()?.value    || '';
  const description = refs.description()?.value || '';
  const thumbnail   = refs.thumbnail()?.value   || '';
  const image       = refs.image()?.value       || '';
  const footerText  = refs.footerText()?.value  || '';
  const footerIcon  = refs.footerIcon()?.value  || '';

  // Color bar
  const bar = refs.prevBar();
  if (bar) bar.style.borderLeftColor = color;

  // Author
  const author = refs.prevAuthor();
  if (author) {
    author.style.display = authorName ? 'flex' : 'none';
    const nameEl = author.querySelector('.embed-author-name');
    if (nameEl) nameEl.textContent = authorName;
  }

  // Title
  const prevTitle = refs.prevTitle();
  if (prevTitle) {
    prevTitle.textContent = title;
    prevTitle.style.display = title ? 'block' : 'none';
    if (titleUrl) {
      prevTitle.innerHTML = `<a href="${titleUrl}" style="color:#00b0f4;text-decoration:none;">${title}</a>`;
    }
  }

  // Description
  const prevDesc = refs.prevDesc();
  if (prevDesc) {
    prevDesc.textContent = description;
    prevDesc.style.display = description ? 'block' : 'none';
  }

  // Thumbnail
  const prevThumb = refs.prevThumbnail();
  if (prevThumb) {
    if (thumbnail) {
      prevThumb.src = thumbnail;
      prevThumb.style.display = 'block';
      prevThumb.onerror = () => prevThumb.style.display = 'none';
    } else {
      prevThumb.style.display = 'none';
    }
  }

  // Image
  const prevImg = refs.prevImage();
  if (prevImg) {
    if (image) {
      prevImg.src = image;
      prevImg.style.display = 'block';
      prevImg.onerror = () => prevImg.style.display = 'none';
    } else {
      prevImg.style.display = 'none';
    }
  }

  // Footer
  const prevFooter = refs.prevFooter();
  if (prevFooter) {
    prevFooter.style.display = footerText ? 'flex' : 'none';
    const iconEl = refs.prevFooterIcon();
    const textEl = refs.prevFooterText();
    if (iconEl) {
      iconEl.src = footerIcon;
      iconEl.style.display = footerIcon ? 'block' : 'none';
    }
    if (textEl) textEl.textContent = footerText;
  }

  // Fields
  renderPreviewFields();
}

function renderPreviewFields() {
  const container = refs.prevFields();
  if (!container) return;
  container.innerHTML = '';
  if (fields.length === 0) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'grid';
  fields.forEach(f => {
    if (!f.name && !f.value) return;
    const div = document.createElement('div');
    div.className = 'preview-field';
    div.innerHTML = `
      ${f.name  ? `<div class="preview-field-name">${f.name}</div>`  : ''}
      ${f.value ? `<div class="preview-field-value">${f.value}</div>` : ''}
    `;
    container.appendChild(div);
  });
}

// ─── Field management ─────────────────────────────────────────────────────────
function addField(name = '', value = '', inline = false) {
  const idx = fields.length;
  fields.push({ name, value, inline });

  const container = document.getElementById('fields-container');
  if (!container) return;

  const row = document.createElement('div');
  row.className = 'field-row';
  row.dataset.idx = idx;
  row.innerHTML = `
    <div class="field-row-header">
      <span class="field-row-title">Field ${idx + 1}</span>
      <button class="remove-field-btn" onclick="removeField(${idx})" title="Xóa field">
        <i class="bi bi-x-lg"></i>
      </button>
    </div>
    <input class="form-control" placeholder="Tên field" value="${escHtml(name)}"
           oninput="fields[${idx}].name = this.value; updatePreview()">
    <textarea class="form-control" placeholder="Giá trị field" rows="2"
              oninput="fields[${idx}].value = this.value; updatePreview()">${escHtml(value)}</textarea>
    <label style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:var(--text-muted);cursor:pointer;">
      <input type="checkbox" ${inline ? 'checked' : ''} onchange="fields[${idx}].inline = this.checked; updatePreview()">
      Inline (hiển thị ngang hàng)
    </label>
  `;
  container.appendChild(row);
  updatePreview();
}

function removeField(idx) {
  fields.splice(idx, 1);
  // Re-render all field rows
  const container = document.getElementById('fields-container');
  if (!container) return;
  container.innerHTML = '';
  const saved = [...fields];
  fields = [];
  saved.forEach(f => addField(f.name, f.value, f.inline));
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Get current embed data ───────────────────────────────────────────────────
function getEmbedData() {
  return {
    color:       refs.color()?.value,
    author:      { name: refs.authorName()?.value || '' },
    title:       refs.title()?.value || '',
    url:         refs.titleUrl()?.value || '',
    description: refs.description()?.value || '',
    thumbnail:   refs.thumbnail()?.value || '',
    image:       refs.image()?.value || '',
    footer:      {
      text:     refs.footerText()?.value || '',
      icon_url: refs.footerIcon()?.value || '',
    },
    fields: fields.filter(f => f.name || f.value),
  };
}

// ─── Save embed ───────────────────────────────────────────────────────────────
async function saveEmbed() {
  const name = refs.embedName()?.value?.trim();
  if (!name) {
    showToast('⚠️ Nhập tên cho embed!', 'error');
    return;
  }
  const data = getEmbedData();
  try {
    const res = await fetch(`/api/guild/${GUILD_ID}/embeds`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, embed: data }),
    });
    if (!res.ok) throw new Error('Failed');
    showToast('✅ Đã lưu embed!', 'success');
    setTimeout(() => window.location.reload(), 1200);
  } catch {
    showToast('❌ Lỗi khi lưu embed', 'error');
  }
}

// ─── Delete saved embed ───────────────────────────────────────────────────────
async function deleteEmbed(embedId) {
  if (!confirm('Xóa embed này?')) return;
  try {
    const res = await fetch(`/api/guild/${GUILD_ID}/embeds/${embedId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
    const item = document.querySelector(`[data-embed-id="${embedId}"]`);
    if (item) {
      item.style.transition = 'opacity 0.3s, transform 0.3s';
      item.style.opacity = '0'; item.style.transform = 'translateX(20px)';
      setTimeout(() => item.remove(), 300);
    }
    showToast('🗑️ Đã xóa embed', 'success');
  } catch {
    showToast('❌ Lỗi khi xóa', 'error');
  }
}

// ─── Load embed into builder ──────────────────────────────────────────────────
function loadEmbed(embedData) {
  try {
    const e = typeof embedData === 'string' ? JSON.parse(embedData) : embedData;
    if (refs.color())       refs.color().value       = e.color       || '#5865f2';
    if (refs.authorName())  refs.authorName().value  = e.author?.name || '';
    if (refs.title())       refs.title().value       = e.title       || '';
    if (refs.titleUrl())    refs.titleUrl().value    = e.url         || '';
    if (refs.description()) refs.description().value = e.description  || '';
    if (refs.thumbnail())   refs.thumbnail().value   = e.thumbnail   || '';
    if (refs.image())       refs.image().value       = e.image       || '';
    if (refs.footerText())  refs.footerText().value  = e.footer?.text     || '';
    if (refs.footerIcon())  refs.footerIcon().value  = e.footer?.icon_url || '';

    // Clear and restore fields
    const container = document.getElementById('fields-container');
    if (container) container.innerHTML = '';
    fields = [];
    (e.fields || []).forEach(f => addField(f.name, f.value, f.inline));

    updatePreview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    showToast('📥 Đã tải embed vào editor', 'success');
  } catch {
    showToast('❌ Lỗi khi tải embed', 'error');
  }
}

// ─── Clear builder ────────────────────────────────────────────────────────────
function clearBuilder() {
  if (!confirm('Xóa toàn bộ nội dung editor?')) return;
  ['eb-color','eb-author-name','eb-title','eb-title-url','eb-description',
   'eb-thumbnail','eb-image','eb-footer','eb-footer-icon','eb-name'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = id === 'eb-color' ? '#5865f2' : '';
  });
  fields = [];
  const fc = document.getElementById('fields-container');
  if (fc) fc.innerHTML = '';
  updatePreview();
}

// ─── Send embed to a Discord channel ─────────────────────────────────────────
async function sendEmbedToChannel() {
  const channelId = document.getElementById('send-channel-select')?.value;
  if (!channelId) {
    showToast('⚠️ Vui lòng chọn kênh', 'error');
    document.getElementById('send-channel-select')?.focus();
    return;
  }

  const embedData = getEmbedData();
  const hasContent = embedData.title || embedData.description || embedData.author?.name
                  || (embedData.fields || []).length > 0;

  if (!hasContent) {
    showToast('⚠️ Embed trống! Nhập ít nhất tiêu đề hoặc mô tả', 'error');
    return;
  }

  const btn = document.getElementById('send-embed-btn');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Đang gửi...';

  try {
    const res = await fetch(`/api/guild/${GUILD_ID}/send-embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channelId, embed: embedData }),
    });
    const data = await res.json();

    if (data.ok) {
      // Success state on button
      btn.innerHTML = '<i class="bi bi-check-lg"></i> Đã gửi thành công!';
      btn.style.background = 'var(--success)';
      btn.style.color = 'white';
      showToast('✅ Đã gửi embed vào kênh!', 'success');
      setTimeout(() => {
        btn.innerHTML = original;
        btn.style.background = '';
        btn.style.color = '';
        btn.disabled = false;
      }, 2500);
      return;
    } else {
      showToast(`❌ ${data.error || 'Lỗi không xác định'}`, 'error');
    }
  } catch {
    showToast('❌ Lỗi kết nối đến server', 'error');
  }

  btn.innerHTML = original;
  btn.disabled = false;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('embed-builder')) return;

  // Bind all inputs to updatePreview
  ['eb-color','eb-author-name','eb-title','eb-title-url',
   'eb-description','eb-thumbnail','eb-image','eb-footer','eb-footer-icon']
    .forEach(id => {
      document.getElementById(id)?.addEventListener('input', updatePreview);
    });

  updatePreview();
});


