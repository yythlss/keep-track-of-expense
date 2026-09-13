/* ==========================================================================
   小账本 · 前端逻辑（原生 JS，零依赖）
   数据流：输入一句话 → /api/parse 解析 → 用户确认 → /api/records 落库 → 刷新看板
   ========================================================================== */

const EXPENSE_CATEGORIES = ['餐饮', '交通', '购物', '娱乐', '居住', '医疗', '学习', '人情', '其他'];
const INCOME_CATEGORIES = ['工资', '奖金', '兼职', '红包', '理财', '报销', '其他'];
const PALETTE = ['#f7b955', '#63b8f5', '#f79ac0', '#a98bf5', '#4fd2a8',
                 '#ffd66b', '#ff8f8f', '#79cfd6', '#c9b8a8'];
const CATEGORY_ICONS = {
  餐饮: '🍜', 交通: '🚕', 购物: '🛍️', 娱乐: '🎬', 居住: '🏠', 医疗: '💊',
  学习: '📚', 人情: '🎁', 工资: '💰', 奖金: '🏆', 兼职: '💼', 红包: '🧧',
  理财: '📈', 报销: '🧾', 其他: '📌',
};
// 分类图标的贴纸底色，和 CATEGORY_ICONS 一一对应
const CATEGORY_COLORS = {
  餐饮: '#ffeccd', 交通: '#dceeff', 购物: '#ffe0ec', 娱乐: '#ebe1ff', 居住: '#ddf5e4',
  医疗: '#ffe2dc', 学习: '#fff5cc', 人情: '#ffe6f4', 其他: '#f1e9df',
  工资: '#dcf7e9', 奖金: '#fff2c9', 兼职: '#e0efff', 红包: '#ffe0e0',
  理财: '#d9f2ec', 报销: '#eae4ff',
};

const $ = (selector) => document.querySelector(selector);

const state = {
  filterMonth: '',
  filterDate: '', // 从看板柱状条 / 日历点进来时，只看某一天
  boardMonth: '',
  view: '',
  calendarReady: false,
};

/* ------------------------------- 通用工具 ------------------------------- */
function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function todayStr() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

function money(value) {
  return Number(value || 0).toFixed(2);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败（${res.status}）`);
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast show${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 2200);
}

/** 根据类型填充分类下拉框 */
function fillCategories(select, type, selected) {
  const list = type === 'income' ? INCOME_CATEGORIES : EXPENSE_CATEGORIES;
  select.innerHTML = list.map((c) => `<option value="${c}">${c}</option>`).join('');
  if (selected && list.includes(selected)) select.value = selected;
}

/* ------------------------------- 健康检查 ------------------------------- */
async function loadHealth() {
  const badge = $('#llm-badge');
  try {
    const data = await api('/api/health');
    if (data.llm) {
      badge.textContent = `AI 已就绪 · ${data.model}`;
      badge.className = 'badge badge-ok';
    } else {
      badge.textContent = '规则模式（未配置大模型）';
      badge.className = 'badge badge-muted';
    }
  } catch (err) {
    badge.textContent = '服务异常';
    badge.className = 'badge badge-muted';
  }
}

/* ------------------------------- 一句话记账 ------------------------------- */
async function handleQuickParse(text) {
  const box = $('#parse-result');
  box.classList.remove('hidden');
  box.innerHTML = '<p class="loading">正在解析…</p>';
  try {
    const data = await api('/api/parse', { method: 'POST', body: JSON.stringify({ text }) });
    renderParseResult(data.parsed);
  } catch (err) {
    box.innerHTML = `<p class="loading">😵 ${err.message}</p>`;
  }
}

function renderParseResult(parsed) {
  const box = $('#parse-result');
  const sourceLabel = parsed.source === 'ai' ? 'AI 解析' : '规则解析';
  box.innerHTML = `
    <div class="parse-card">
      <div class="parse-head">识别结果 <span class="tag">${sourceLabel}</span></div>
      <div class="grid-form">
        <div class="field">
          <label for="p-type">类型</label>
          <select id="p-type">
            <option value="expense">支出</option>
            <option value="income">收入</option>
          </select>
        </div>
        <div class="field">
          <label for="p-amount">金额</label>
          <input id="p-amount" type="number" step="0.01" min="0" value="${parsed.amount}" />
        </div>
        <div class="field">
          <label for="p-category">分类</label>
          <select id="p-category"></select>
        </div>
        <div class="field">
          <label for="p-date">日期</label>
          <input id="p-date" type="date" value="${parsed.happened_on}" />
        </div>
        <div class="field field-wide">
          <label for="p-note">备注</label>
          <input id="p-note" type="text" value="${escapeAttr(parsed.note)}" />
        </div>
      </div>
      <div class="parse-actions">
        <button type="button" id="p-save" class="btn btn-primary">确认入账</button>
        <button type="button" id="p-cancel" class="btn btn-ghost">取消</button>
      </div>
    </div>`;

  const typeSelect = $('#p-type');
  typeSelect.value = parsed.type;
  fillCategories($('#p-category'), parsed.type, parsed.category);

  typeSelect.addEventListener('change', () => {
    fillCategories($('#p-category'), typeSelect.value, null);
  });
  $('#p-save').addEventListener('click', () => saveParsed());
  $('#p-cancel').addEventListener('click', () => box.classList.add('hidden'));
}

async function saveParsed() {
  const payload = {
    type: $('#p-type').value,
    amount: $('#p-amount').value,
    category: $('#p-category').value,
    happened_on: $('#p-date').value,
    note: $('#p-note').value,
  };
  try {
    await api('/api/records', { method: 'POST', body: JSON.stringify(payload) });
    $('#parse-result').classList.add('hidden');
    $('#quick-input').value = '';
    toast('记账成功 ✅');
    refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ------------------------------- 手动记账 ------------------------------- */
async function saveManual(event) {
  event.preventDefault();
  const payload = {
    type: $('#m-type').value,
    amount: $('#m-amount').value,
    category: $('#m-category').value,
    happened_on: $('#m-date').value,
    note: $('#m-note').value,
  };
  try {
    await api('/api/records', { method: 'POST', body: JSON.stringify(payload) });
    $('#manual-form').reset();
    $('#m-date').value = todayStr();
    $('#manual-form').classList.add('hidden');
    toast('已记一笔 ✅');
    refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ------------------------------- 账单流水 ------------------------------- */
async function loadRecords() {
  const list = $('#record-list');
  list.innerHTML = '<li class="empty">加载中…</li>';

  const params = new URLSearchParams();
  const category = $('#filter-category').value;
  const type = $('#filter-type').value;

  // 指定了具体某天就按天查，否则按整月
  if (state.filterDate) params.set('date', state.filterDate);
  else if (state.filterMonth) params.set('month', state.filterMonth);
  if (category) params.set('category', category);
  if (type) params.set('type', type);

  renderFilterScope(category, type);

  try {
    const data = await api(`/api/records?${params.toString()}`);
    if (!data.records.length) {
      list.innerHTML = '<li class="empty">还没有记录，用上面的一句话记账试试 👆</li>';
      return;
    }
    list.innerHTML = data.records.map(recordItem).join('');
    list.querySelectorAll('[data-delete]').forEach((btn) => {
      btn.addEventListener('click', () => removeRecord(Number(btn.dataset.delete)));
    });
  } catch (err) {
    list.innerHTML = `<li class="empty">😵 ${err.message}</li>`;
  }
}

function recordItem(record) {
  const isIncome = record.type === 'income';
  const icon = CATEGORY_ICONS[record.category] || '📌';
  const iconBg = CATEGORY_COLORS[record.category] || '#f3ece3';
  const note = record.note || '—';
  return `
    <li class="record-item">
      <span class="record-icon" style="background:${iconBg}">${icon}</span>
      <div class="record-main">
        <div class="record-top">
          <span class="record-category">${escapeHtml(record.category)}</span>
        </div>
        <div class="record-note">${escapeHtml(note)}</div>
      </div>
      <span class="record-date">${record.happened_on.slice(5)}</span>
      <span class="record-amount ${isIncome ? 'income' : 'expense'}">
        ${isIncome ? '+' : '-'}${money(record.amount)}
      </span>
      <button type="button" class="btn-icon" data-delete="${record.id}" title="删除">✕</button>
    </li>`;
}

/** 把"当前在看什么范围"写出来，并决定要不要显示「清除筛选」 */
function renderFilterScope(category, type) {
  const scope = $('#filter-scope');
  const clear = $('#filter-clear');

  const parts = [];
  if (state.filterDate) parts.push(`${state.filterDate.slice(5)} 当天`);
  if (category) parts.push(category);
  if (type) parts.push(type === 'income' ? '仅收入' : '仅支出');

  const active = parts.length > 0;
  scope.classList.toggle('hidden', !active);
  scope.textContent = active ? `当前筛选：${parts.join(' · ')}` : '';
  clear.classList.toggle('hidden', !active);
}

/** 清除筛选，回到"当月全部" */
function clearFilters() {
  state.filterDate = '';
  $('#filter-category').value = '';
  $('#filter-type').value = '';
  $('#filter-month').value = state.filterMonth;
  loadRecords();
}

/** 滚到流水卡片，点完图例/柱状条之后视线能跟上 */
function scrollToRecords() {
  $('#records-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** 只看某一天的流水（看板「最高支出日」和柱状条详情都走这里） */
function focusRecordsOn(date) {
  state.filterDate = date;
  state.filterMonth = date.slice(0, 7);
  $('#filter-month').value = state.filterMonth;
  $('#filter-category').value = '';
  $('#filter-type').value = '';
  loadRecords();
  scrollToRecords();
  toast(`只看 ${date.slice(5)} 的流水`);
}

/** 点分类图例：让流水只留这一类 */
function filterRecordsByCategory(category) {
  state.filterDate = '';
  $('#filter-category').value = category;
  loadRecords();
  scrollToRecords();
  toast(`只看「${category}」的流水`);
}

async function removeRecord(id) {
  try {
    await api(`/api/records/${id}`, { method: 'DELETE' });
    toast('已删除');
    refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ------------------------------- 月度看板 ------------------------------- */
async function loadSummary() {
  const params = new URLSearchParams();
  if (state.boardMonth) params.set('month', state.boardMonth);

  try {
    const data = await api(`/api/summary?${params.toString()}`);
    $('#stat-income').textContent = money(data.income);
    $('#stat-expense').textContent = money(data.expense);
    const balance = $('#stat-balance');
    balance.textContent = money(data.balance);
    balance.className = 'stat-value';
    balance.style.color = data.balance < 0 ? 'var(--expense)' : 'var(--ink)';

    renderDonut(data.categories, data.expense);
    renderTrend(data.recent_days);
    renderBoardMetrics(data);
    fillCategoryFilter(data.categories);
    renderOverview(data);
  } catch (err) {
    toast(err.message, true);
  }
}

/* ------------------------------- 首屏大数字 ------------------------------- */
/** 一句话记账右侧的大数字：本月总消费 + 和上个月的对比 */
async function renderOverview(data) {
  $('#ov-expense').textContent = money(data.expense);

  const compare = $('#ov-compare');
  try {
    const prev = await api(`/api/summary?month=${shiftMonth(currentMonth(), -1)}`);
    if (!prev.expense) {
      compare.textContent = '上个月还没有记录';
      compare.className = 'overview-sub';
      return;
    }
    const delta = (data.expense - prev.expense) / prev.expense;
    const up = delta > 0;
    compare.textContent = `较上月 ${up ? '↑' : '↓'} ${Math.abs(delta * 100).toFixed(0)}%`;
    compare.className = `overview-sub ${up ? 'is-up' : 'is-down'}`;
  } catch (err) {
    compare.textContent = '—';
  }
}

function renderDonut(categories, expense) {
  const svg = $('#donut');
  const legend = $('#legend');
  const NS = 'http://www.w3.org/2000/svg';
  const radius = 45;
  const circumference = 2 * Math.PI * radius;

  svg.innerHTML = '';
  legend.innerHTML = '';

  if (!categories.length) {
    svg.innerHTML = `<circle cx="60" cy="60" r="${radius}" fill="none" stroke="#eef1f3" stroke-width="14" />
      <text x="60" y="60" text-anchor="middle" dominant-baseline="middle" class="donut-total">暂无支出</text>`;
    return;
  }

  let offset = 0;
  categories.forEach((item, index) => {
    const color = PALETTE[index % PALETTE.length];
    const length = Math.max(item.ratio * circumference, 0.5);

    const circle = document.createElementNS(NS, 'circle');
    circle.setAttribute('cx', '60');
    circle.setAttribute('cy', '60');
    circle.setAttribute('r', String(radius));
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', color);
    circle.setAttribute('stroke-width', '14');
    circle.setAttribute('stroke-dasharray', `${length} ${circumference - length}`);
    circle.setAttribute('stroke-dashoffset', String(-offset));
    circle.setAttribute('transform', 'rotate(-90 60 60)');
    svg.appendChild(circle);
    offset += length;

    legend.insertAdjacentHTML('beforeend', `
      <li data-category="${escapeHtml(item.category)}" title="只看「${escapeHtml(item.category)}」的流水">
        <span class="legend-dot" style="background:${color}"></span>
        <span class="legend-name">${escapeHtml(item.category)}</span>
        <span class="legend-value">${money(item.amount)} · ${(item.ratio * 100).toFixed(0)}%</span>
      </li>`);
  });

  // 图例可以点：点了就让右边的流水只留这一类，省得手动去下拉框里找
  const picked = $('#filter-category').value;
  legend.querySelectorAll('[data-category]').forEach((item) => {
    item.classList.toggle('is-active', item.dataset.category === picked);
    item.addEventListener('click', () => filterRecordsByCategory(item.dataset.category));
  });

  const total = document.createElementNS(NS, 'text');
  total.setAttribute('x', '60');
  total.setAttribute('y', '56');
  total.setAttribute('text-anchor', 'middle');
  total.setAttribute('class', 'donut-total');
  total.textContent = '总支出';
  svg.appendChild(total);

  const amount = document.createElementNS(NS, 'text');
  amount.setAttribute('x', '60');
  amount.setAttribute('y', '70');
  amount.setAttribute('text-anchor', 'middle');
  amount.setAttribute('class', 'donut-amount');
  amount.textContent = money(expense);
  svg.appendChild(amount);
}

let trendDays = []; // 近 7 日数据，点柱子时直接从这里取，不用再请求

function renderTrend(days) {
  trendDays = days;
  const max = Math.max(...days.map((d) => d.expense), 1);

  $('#trend').innerHTML = days.map((d, index) => `
    <button type="button" class="trend-item" data-day="${index}"
            title="${d.date}｜支出 ${money(d.expense)}｜收入 ${money(d.income)}">
      <span class="trend-bar" style="height:${Math.max((d.expense / max) * 100, 4)}%"></span>
      <span class="trend-label">${d.date.slice(5)}</span>
    </button>`).join('');

  $('#trend').querySelectorAll('[data-day]').forEach((btn) => {
    btn.addEventListener('click', () => showTrendDay(Number(btn.dataset.day)));
  });

  hideTrendDetail();
}

/** 点柱状条：展开当天的收入 / 支出 / 结余 / 笔数 */
function showTrendDay(index) {
  const day = trendDays[index];
  if (!day) return;

  $('#trend').querySelectorAll('.trend-item').forEach((el, i) => {
    el.classList.toggle('is-active', i === index);
  });

  const detail = $('#trend-detail');
  detail.classList.remove('hidden');
  detail.innerHTML = `
    <div class="trend-detail-head">
      <span class="trend-detail-date">${day.date}</span>
      <span class="trend-detail-count">${day.count} 笔</span>
    </div>
    <div class="trend-detail-row"><span>支出</span><b class="expense">-${money(day.expense)}</b></div>
    <div class="trend-detail-row"><span>收入</span><b class="income">+${money(day.income)}</b></div>
    <div class="trend-detail-row"><span>结余</span><b>${money(day.balance)}</b></div>
    <button type="button" class="btn btn-ghost trend-detail-more" data-day-records="${day.date}">
      看这天的流水 ›
    </button>`;
  detail.querySelector('[data-day-records]').addEventListener('click', () => {
    focusRecordsOn(day.date);
  });
}

function hideTrendDetail() {
  const detail = $('#trend-detail');
  detail.classList.add('hidden');
  detail.innerHTML = '';
}

/** 看板的细口径：日均、笔均、有支出的天数、花得最多的一天（可点，直接跳到那天的流水） */
function renderBoardMetrics(data) {
  const box = $('#board-metrics');
  const pills = [
    `日均支出 ¥${money(data.daily_avg)}`,
    `笔均 ¥${money(data.per_record_avg)}`,
    `有支出 ${data.active_days} 天`,
  ];
  box.innerHTML = pills.map((text) => `<span class="metric-pill">${text}</span>`).join('');

  if (!data.top_day) return;
  const { date, amount } = data.top_day;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'metric-pill is-action';
  btn.textContent = `最高 ${date.slice(5)} ¥${money(amount)}`;
  btn.title = '看这一天的流水';
  btn.addEventListener('click', () => focusRecordsOn(date));
  box.appendChild(btn);
}

function fillCategoryFilter(categories) {
  const select = $('#filter-category');
  const current = select.value;
  const all = [...new Set(categories.map((c) => c.category))];
  select.innerHTML = '<option value="">全部分类</option>' +
    all.map((c) => `<option value="${c}">${c}</option>`).join('');
  select.value = current;
}

/* ------------------------------- 金库 · 攒钱罐 ------------------------------- */
const VAULT_ICONS = ['🏦', '🐷', '🎯', '✈️', '🏠', '🚗', '🎓', '💍', '🛡️', '🧳'];

/** coin.js 万一没加载成功，动效降级成空函数，但存钱本身照常工作 */
const fx = window.CoinFX || {
  drop() {}, coinDrop() {}, celebrate() {}, isSoundOn: () => false, toggleSound: () => false,
};

const vaultState = { list: [] };

async function loadVaults() {
  const list = $('#vault-list');
  list.innerHTML = '<li class="empty">加载中…</li>';
  try {
    const data = await api('/api/vaults');
    vaultState.list = data.vaults;
    renderVaults(data.vaults, data.total_saved);
  } catch (err) {
    list.innerHTML = `<li class="empty">😵 ${err.message}</li>`;
  }
}

function renderVaults(vaults, totalSaved) {
  const list = $('#vault-list');
  $('#vault-total').textContent = `已存 ${money(totalSaved)}`;

  if (!vaults.length) {
    list.innerHTML = '<li class="empty">还没有金库，点右上角「+ 新建金库」开一个 🏦</li>';
    return;
  }

  list.innerHTML = vaults.map(vaultItem).join('');
  list.querySelectorAll('[data-deposit-form]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      deposit(form);
    });
  });
  list.querySelectorAll('[data-del-vault]').forEach((btn) => {
    btn.addEventListener('click', () => removeVault(Number(btn.dataset.delVault)));
  });
}

function vaultItem(vault) {
  const hasGoal = vault.goal > 0;
  const percent = hasGoal ? Math.min(vault.saved / vault.goal, 1) * 100 : 0;
  const meta = vault.deposit_count
    ? `存了 ${vault.deposit_count} 次 · 最近 ${String(vault.last_deposit_at).slice(5, 10)}`
    : '还没存过钱';

  return `
    <li class="vault-item${vault.achieved ? ' achieved' : ''}" data-vault="${vault.id}"
        style="--vault-color:${escapeAttr(vault.color)}">
      <div class="vault-head">
        <span class="vault-icon">${vault.icon}</span>
        <div class="vault-title">
          <span class="vault-name" title="${escapeAttr(vault.note || vault.name)}">${escapeHtml(vault.name)}</span>
          <span class="vault-meta">${meta}</span>
        </div>
        <button type="button" class="btn-icon" data-del-vault="${vault.id}" title="删除金库">✕</button>
      </div>

      <div class="vault-stage">
        <div class="vault-float"></div>
        <div class="coin-stage"></div>
        <div class="vault-piggy">🐷</div>
      </div>

      <div class="vault-amount">
        <span class="vault-saved" data-value="${vault.saved}">${money(vault.saved)}</span>
        <span class="vault-goal">${hasGoal ? `/ ${money(vault.goal)}` : '不设目标'}</span>
      </div>
      <div class="vault-bar">
        <span class="vault-bar-fill" style="width:${percent}%"></span>
      </div>
      <div class="vault-progress-text">${vaultProgressText(vault)}</div>

      <form class="vault-deposit-form" data-deposit-form="${vault.id}">
        <input type="number" step="0.01" min="0.01" placeholder="存入金额" aria-label="存入金额" />
        <button type="submit" class="btn btn-primary">存钱</button>
      </form>
    </li>`;
}

function vaultProgressText(vault) {
  if (vault.goal <= 0) return '未设目标，积少成多';
  if (vault.achieved) return `已攒满目标 🎉 超出 ${money(vault.saved - vault.goal)}`;
  const percent = (vault.saved / vault.goal) * 100;
  return `还差 ${money(vault.goal - vault.saved)} · ${percent.toFixed(0)}%`;
}

async function deposit(form) {
  const vaultId = Number(form.dataset.depositForm);
  const input = form.querySelector('input');
  const button = form.querySelector('button');
  const amount = Number(input.value);

  if (!amount || amount <= 0) return toast('请输入要存入的金额', true);

  button.disabled = true;
  try {
    const data = await api(`/api/vaults/${vaultId}/deposit`, {
      method: 'POST',
      body: JSON.stringify({ amount }),
    });
    input.value = '';
    playDeposit(form.closest('.vault-item'), data.vault, amount);
    toast(`已存入 ${money(amount)} 💰`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
  }
}

/** 存钱成功的四连击：金币旋转坠落（带音效）→ 存钱罐弹跳 → 飘字 → 数字滚动 */
function playDeposit(item, vault, amount) {
  if (!item) return;

  const piggy = item.querySelector('.vault-piggy');
  const floater = item.querySelector('.vault-float');

  // 金额越大金币越多（3~10 枚），让"存得多"看得见
  const coins = Math.min(10, 3 + Math.floor(amount / 100));
  fx.drop({ stage: item.querySelector('.coin-stage'), count: coins, sound: true });

  restartAnimation(piggy, 'hit', 600);
  floater.textContent = `+${money(amount)}`;
  restartAnimation(floater, 'show', 1000);

  patchVault(item, vault);

  // 刚好攒满目标：等金币落完再补一段上行琶音
  if (vault.achieved) setTimeout(() => fx.celebrate(), 420);
}

/** 就地更新卡片，避免整列表重绘导致进度条与数字失去过渡动画 */
function patchVault(item, vault) {
  const savedEl = item.querySelector('.vault-saved');
  countUp(savedEl, Number(savedEl.dataset.value || 0), vault.saved);

  const percent = vault.goal > 0 ? Math.min(vault.saved / vault.goal, 1) * 100 : 0;
  item.querySelector('.vault-bar-fill').style.width = `${percent}%`;
  item.classList.toggle('achieved', vault.achieved);
  item.querySelector('.vault-meta').textContent =
    `存了 ${vault.deposit_count} 次 · 最近 ${String(vault.last_deposit_at).slice(5, 10)}`;
  item.querySelector('.vault-progress-text').textContent = vaultProgressText(vault);

  const index = vaultState.list.findIndex((v) => v.id === vault.id);
  if (index >= 0) vaultState.list[index] = vault;
  else vaultState.list.push(vault);
  refreshVaultTotal();
}

function refreshVaultTotal() {
  const total = vaultState.list.reduce((sum, v) => sum + v.saved, 0);
  $('#vault-total').textContent = `已存 ${money(total)}`;
}

/** 数字滚动，比直接跳变更能让人"感觉钱变多了" */
function countUp(el, from, to, duration = 700) {
  el.dataset.value = to;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || from === to) {
    el.textContent = money(to);
    return;
  }
  const started = performance.now();
  function frame(now) {
    const progress = Math.min((now - started) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    el.textContent = money(from + (to - from) * eased);
    if (progress < 1) requestAnimationFrame(frame);
    else el.textContent = money(to);
  }
  requestAnimationFrame(frame);
}

/** 先移除再强制重排，让同一个动画类可以被连续触发 */
function restartAnimation(el, className, duration) {
  el.classList.remove(className);
  void el.offsetWidth;
  el.classList.add(className);
  if (duration) setTimeout(() => el.classList.remove(className), duration);
}

async function createVault(event) {
  event.preventDefault();
  const payload = {
    name: $('#v-name').value,
    goal: $('#v-goal').value || 0,
    icon: $('#v-icon').value,
    note: $('#v-note').value,
  };

  try {
    await api('/api/vaults', { method: 'POST', body: JSON.stringify(payload) });
    $('#vault-form').reset();
    $('#v-icon').value = VAULT_ICONS[0];
    $('#vault-form').classList.add('hidden');
    toast('金库已开好 🏦');
    loadVaults();
  } catch (err) {
    toast(err.message, true);
  }
}

async function removeVault(id) {
  const vault = vaultState.list.find((v) => v.id === id);
  const label = vault ? `「${vault.name}」` : '';
  if (!window.confirm(`删除金库${label}？里边的存钱记录会一起删掉。`)) return;

  try {
    await api(`/api/vaults/${id}`, { method: 'DELETE' });
    toast('金库已删除');
    loadVaults();
  } catch (err) {
    toast(err.message, true);
  }
}

function fillVaultIcons() {
  const select = $('#v-icon');
  select.innerHTML = VAULT_ICONS
    .map((icon) => `<option value="${icon}">${icon}</option>`)
    .join('');
}

function bindSoundToggle() {
  const button = $('#sound-toggle');
  const sync = () => {
    const on = fx.isSoundOn();
    button.textContent = on ? '🔊' : '🔇';
    button.title = on ? '点击关闭金币音效' : '点击打开金币音效';
  };
  button.addEventListener('click', () => {
    fx.toggleSound();
    sync();
    if (fx.isSoundOn()) fx.coinDrop(0); // 打开时试听一声，确认真的会响
  });
  sync();
}

/* ------------------------------- 初始化 ------------------------------- */
function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
const escapeAttr = escapeHtml;

/* ------------------------------- 视图路由 -------------------------------
   首页只放「一句话记账」和功能入口，每个功能的细节都待在自己的视图里，
   点入口（或直接改 URL hash）才去拉那一份数据，首屏不会被一堆请求拖慢。
   桌宠不在此列：它常驻在界面旁边，随时都能互动。 */
const VIEWS = {
  // 看板与流水就在首页上，不需要单独的视图
  home: { load: () => loadHome() },
  calendar: { load: () => loadCalendarView() },
  vault: { load: () => loadVaults() },
};

function currentView() {
  const name = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  return Object.prototype.hasOwnProperty.call(VIEWS, name) ? name : 'home';
}

function switchView(name, force = false) {
  if (!VIEWS[name]) name = 'home';
  const changed = name !== state.view;

  document.querySelectorAll('.view').forEach((section) => {
    section.classList.toggle('hidden', section.id !== `view-${name}`);
  });
  state.view = name;

  if (changed || force) {
    window.scrollTo({ top: 0, behavior: changed ? 'smooth' : 'auto' });
    VIEWS[name].load();
  }
}

function navigate(name) {
  const hash = `#/${name}`;
  if (location.hash === hash) switchView(name, true);
  else location.hash = hash;
}

function initRouter() {
  window.addEventListener('hashchange', () => switchView(currentView()));
  // 所有带 data-nav 的元素都是导航入口（功能卡片、返回按钮、左上角 logo）
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-nav]');
    if (!trigger) return;
    event.preventDefault();
    navigate(trigger.dataset.nav);
  });
  switchView(currentView());
}

/** 首页：月度看板 + 账单流水同屏展示 */
function loadHome() {
  // 看板和流水同屏，两个请求一起发
  loadSummary();
  loadRecords();
}

function loadCalendarView() {
  if (state.calendarReady) window.CalendarView?.reload();
  else {
    window.CalendarView?.init();
    state.calendarReady = true;
  }
}

function refreshAll() {
  // 记账 / 删除之后：首页的看板与流水一起刷新，正开着的日历也跟着刷新
  loadHome();
  if (state.view === 'calendar' && state.calendarReady) window.CalendarView?.reload();
  window.PetView?.refresh(); // 桌宠的台词也跟着最新的账本走
}

function bindEvents() {
  // 一句话记账
  $('#quick-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const text = $('#quick-input').value.trim();
    if (!text) return toast('先输入点什么吧', true);
    handleQuickParse(text);
  });
  // 只绑一句话记账的示例词条；桌宠里也用 .chip，由 pet.js 自己处理
  document.querySelectorAll('.chip[data-example]').forEach((chip) => {
    chip.addEventListener('click', () => {
      $('#quick-input').value = chip.dataset.example;
      handleQuickParse(chip.dataset.example);
    });
  });

  // 手动记账
  $('#toggle-manual').addEventListener('click', () => {
    $('#manual-form').classList.toggle('hidden');
  });
  $('#m-type').addEventListener('change', (e) => fillCategories($('#m-category'), e.target.value, null));
  $('#manual-form').addEventListener('submit', saveManual);

  // 筛选：手改筛选条件时，先把"只看某一天"放开，否则会跟下拉框打架
  $('#filter-month').addEventListener('change', (e) => {
    state.filterMonth = e.target.value;
    state.filterDate = '';
    loadRecords();
  });
  $('#filter-category').addEventListener('change', () => {
    state.filterDate = '';
    loadRecords();
  });
  $('#filter-type').addEventListener('change', () => {
    state.filterDate = '';
    loadRecords();
  });
  $('#filter-clear').addEventListener('click', clearFilters);

  // 看板月份：换月之后，看板和上面的"本月总消费"一起更新
  $('#board-month').addEventListener('change', (e) => {
    state.boardMonth = e.target.value;
    loadSummary();
  });

  // 金库
  fillVaultIcons();
  bindSoundToggle();
  $('#toggle-vault-form').addEventListener('click', () => {
    const form = $('#vault-form');
    form.classList.toggle('hidden');
    if (!form.classList.contains('hidden')) $('#v-name').focus();
  });
  $('#vault-form').addEventListener('submit', createVault);
}

function init() {
  const month = currentMonth();
  state.filterMonth = month;
  state.boardMonth = month;

  $('#filter-month').value = month;
  $('#board-month').value = month;
  $('#m-date').value = todayStr();
  fillCategories($('#m-category'), 'expense', null);

  bindEvents();
  loadHealth();
  window.Profile?.init(); // 先把皮肤铺好，避免页面闪一下默认背景
  window.PetView?.init(); // 桌宠常驻在界面旁，跟首页一起上场
  initRouter();           // 打开首页，只拉首页要用的数据
}

document.addEventListener('DOMContentLoaded', init);
