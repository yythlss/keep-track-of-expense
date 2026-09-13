/* ==========================================================================
   小账本 · 个性化（头像 / 昵称 / 背景）
   偏好存后端 settings 表；图片先用 canvas 压到合理尺寸再上传，
   免得几 MB 的原图直接塞进 SQLite。
   依赖：app.js 里的 $ / api / toast / escapeHtml
   ========================================================================== */

// 背景主题：key 与后端 db.BG_PRESETS 保持一致，后端只校验取值合法性
const BG_PRESETS = {
  cream: { label: '奶油', css: 'radial-gradient(1100px 620px at 10% -10%, #ffe7b0 0%, #fff8ec 45%, #fdf6ee 100%)' },
  mint: { label: '薄荷', css: 'radial-gradient(1100px 620px at 12% -10%, #c9f2e0 0%, #f1fbf6 45%, #f2faf7 100%)' },
  sakura: { label: '樱花', css: 'radial-gradient(1100px 620px at 88% -6%, #ffd9e6 0%, #fff5f8 45%, #fdf2f5 100%)' },
  sky: { label: '晴空', css: 'radial-gradient(1100px 620px at 20% -12%, #d2e9ff 0%, #f3f9ff 45%, #f1f6fc 100%)' },
  latte: { label: '拿铁', css: 'radial-gradient(1100px 620px at 82% 0%, #e9dbc9 0%, #fbf6f0 45%, #f8f2ec 100%)' },
  dusk: { label: '薄暮', css: 'radial-gradient(1100px 620px at 50% -18%, #ddd6ff 0%, #f6f4ff 45%, #f3f1fb 100%)' },
};

const AVATAR_CHOICES = ['🐷', '🐱', '🐶', '🐰', '🦊', '🐼', '🐨', '🐻', '🐯', '🦁', '🐮', '🐸', '🐥', '🐧', '🦄', '🐙'];

const PROFILE_DEFAULTS = { nickname: '', avatar: '🐷', bg_preset: 'cream', bg_image: '' };

// 图片压缩规则：头像小、背景大，分别对应后端 400KB / 1.5MB 的长度上限
const IMAGE_RULES = {
  avatar: { maxEdge: 256, quality: 0.88, keepPng: true },
  background: { maxEdge: 1600, quality: 0.82, keepPng: false },
};

// 当前草稿：面板里点一下改的就是它，点「保存」才写回后端
let profileSettings = { ...PROFILE_DEFAULTS };

/* ------------------------------- 读取与应用 ------------------------------- */
async function loadProfile() {
  try {
    const data = await api('/api/settings');
    profileSettings = { ...PROFILE_DEFAULTS, ...data.settings };
    renderProfileForm();
    applyProfile();
  } catch (err) {
    // 后端没起来也要能用：保持默认皮肤，不打扰用户
  }
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

/** 把偏好刷到页面上：背景、头像、问候语 */
function applyProfile() {
  const { avatar, nickname, bg_preset, bg_image } = profileSettings;

  // 背景：自定义图片优先，否则用主题渐变
  // 只改 background-image 等单项，保留 CSS 里的兜底底色，避免大面积留白
  const layer = document.body.style;
  layer.backgroundImage = bg_image
    ? `url("${bg_image}")`
    : (BG_PRESETS[bg_preset] || BG_PRESETS.cream).css;
  layer.backgroundSize = bg_image ? 'cover' : 'auto';
  layer.backgroundPosition = bg_image ? 'center' : 'top left';
  layer.backgroundRepeat = 'no-repeat';
  layer.backgroundAttachment = 'fixed';

  // 头像：emoji 直接显示，上传的图片用 img 包一层
  const markup = avatar.startsWith('data:')
    ? `<img src="${avatar}" alt="头像" class="avatar-img" />`
    : escapeHtml(avatar);
  $('#avatar-view').innerHTML = markup;
  $('#brand-logo').innerHTML = markup;

  $('#brand-sub').textContent = nickname
    ? `${greeting()}，${nickname} · 记录每一笔，生活更有序`
    : '记录每一笔，生活更有序';

  const tip = $('#ov-tip');
  if (tip) tip.textContent = nickname ? `${nickname}，加油省钱！` : '加油省钱！';
}

/* ------------------------------- 面板渲染 ------------------------------- */
function renderProfileForm() {
  $('#set-nickname').value = profileSettings.nickname;
  renderAvatarPicker();
  renderBgPicker();
}

function renderAvatarPicker() {
  const usingImage = profileSettings.avatar.startsWith('data:');
  const choices = AVATAR_CHOICES.map((emoji) => `
    <button type="button" class="avatar-choice${!usingImage && profileSettings.avatar === emoji ? ' is-active' : ''}"
            data-avatar="${emoji}">${emoji}</button>`).join('');

  const custom = usingImage
    ? `<span class="avatar-choice is-active"><img src="${profileSettings.avatar}" alt="自定义头像" /></span>`
    : '';

  $('#avatar-picker').innerHTML = choices + custom;
}

function renderBgPicker() {
  const usingImage = Boolean(profileSettings.bg_image);
  $('#bg-picker').innerHTML = Object.entries(BG_PRESETS).map(([key, preset]) => `
    <button type="button" class="bg-choice${!usingImage && profileSettings.bg_preset === key ? ' is-active' : ''}"
            data-preset="${key}" style="background-image:${preset.css}" title="${preset.label}">
      <span>${preset.label}</span>
    </button>`).join('');
}

/* ------------------------------- 图片处理 ------------------------------- */
/** 用 canvas 把图片缩到指定长边并重新编码，再转成 data URL */
function compressImage(file, rule) {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      reject(new Error('请选择图片文件'));
      return;
    }

    const reader = new FileReader();
    reader.onerror = () => reject(new Error('图片读取失败'));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error('图片解析失败'));
      image.onload = () => {
        const scale = Math.min(1, rule.maxEdge / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);

        // 头像保留 PNG 的透明通道，背景一律转 JPEG 省体积
        const keepPng = rule.keepPng && file.type === 'image/png';
        resolve(canvas.toDataURL(keepPng ? 'image/png' : 'image/jpeg', rule.quality));
      };
      image.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

function bindUpload(inputId, kind) {
  $(inputId).addEventListener('change', async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = ''; // 清空后同一张图才能再次选择
    if (!file) return;

    try {
      const dataUrl = await compressImage(file, IMAGE_RULES[kind]);
      if (kind === 'avatar') {
        profileSettings.avatar = dataUrl;
        renderAvatarPicker();
      } else {
        profileSettings.bg_image = dataUrl;
        renderBgPicker();
      }
      applyProfile();
      toast('图片已就绪，记得点保存 💾');
    } catch (err) {
      toast(err.message, true);
    }
  });
}

/* ------------------------------- 交互 ------------------------------- */
function openSheet() {
  loadProfile(); // 每次打开都取最新，避免残留上次没保存的草稿
  $('#settings-mask').classList.remove('hidden');
  $('#settings-sheet').classList.remove('hidden');
  document.body.classList.add('sheet-open');
}

function closeSheet() {
  $('#settings-mask').classList.add('hidden');
  $('#settings-sheet').classList.add('hidden');
  document.body.classList.remove('sheet-open');
}

async function saveProfile() {
  const button = $('#save-settings');
  button.disabled = true;
  try {
    const data = await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(profileSettings),
    });
    profileSettings = { ...PROFILE_DEFAULTS, ...data.settings };
    applyProfile();
    renderProfileForm();
    closeSheet();
    toast('个性化已保存 ✨');
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
  }
}

function initProfile() {
  $('#set-nickname').addEventListener('input', (event) => {
    profileSettings.nickname = event.target.value;
  });

  // 头像和背景选择器内容会重建，统一用事件委托
  $('#avatar-picker').addEventListener('click', (event) => {
    const choice = event.target.closest('[data-avatar]');
    if (!choice) return;
    profileSettings.avatar = choice.dataset.avatar;
    renderAvatarPicker();
    applyProfile();
  });

  $('#bg-picker').addEventListener('click', (event) => {
    const choice = event.target.closest('[data-preset]');
    if (!choice) return;
    profileSettings.bg_preset = choice.dataset.preset;
    profileSettings.bg_image = ''; // 选主题就意味着放弃自定义图片
    renderBgPicker();
    applyProfile();
  });

  $('#bg-reset').addEventListener('click', () => {
    profileSettings.bg_image = '';
    profileSettings.bg_preset = PROFILE_DEFAULTS.bg_preset;
    renderBgPicker();
    applyProfile();
  });

  bindUpload('#avatar-upload', 'avatar');
  bindUpload('#bg-upload', 'background');

  $('#open-settings').addEventListener('click', openSheet);
  $('#close-settings').addEventListener('click', closeSheet);
  $('#settings-mask').addEventListener('click', closeSheet);
  $('#save-settings').addEventListener('click', saveProfile);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSheet();
  });

  loadProfile();
}

window.Profile = { init: initProfile, apply: applyProfile, open: openSheet };
