/* ==========================================================================
   小账本 · 日历视图
   后端 /api/calendar 已经把整月每天（含空白日）算好并对齐到周一，
   这里只负责画格子、切口径、点某天看当天流水。
   依赖：app.js 里的 $ / api / money / toast / recordItem / removeRecord
   ========================================================================== */

// 顶部四个口径，对应格子里的数字怎么显示
const CAL_MODES = ['expense', 'income', 'both', 'balance'];

// 每天格子的底色（rgb 三通道），透明度再按当天金额大小算，花得越多颜色越深
const CAL_TINT = {
  expense: '255, 168, 100',
  income: '104, 205, 156',
  both: '104, 205, 156',
  balance: '147, 156, 255',
};

const WEEKDAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

const calState = { month: '', mode: 'expense', data: null, selected: '' };

/* ------------------------------- 日期工具 ------------------------------- */
function shiftMonth(month, delta) {
  const [year, mon] = month.split('-').map(Number);
  const moved = new Date(year, mon - 1 + delta, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, '0')}`;
}

function calMonthLabel(month) {
  const [year, mon] = month.split('-');
  return `${year}年${Number(mon)}月`;
}

/* ------------------------------- 渲染 ------------------------------- */
async function loadCalendar(month = calState.month) {
  calState.month = month;
  try {
    calState.data = await api(`/api/calendar?month=${month}`);
    renderCalendar();
  } catch (err) {
    toast(err.message, true);
  }
}

/** 记账之后调用：重画日历，并保持当前选中的那天仍然展开 */
async function reloadCalendar() {
  await loadCalendar();
  if (calState.selected) openDay(calState.selected);
}

function renderCalendar() {
  const data = calState.data;
  if (!data) return;

  $('#cal-month-label').textContent = calMonthLabel(data.month);

  const activeDays = data.days.filter((day) => day.count > 0).length;
  $('#cal-summary').innerHTML = `
    <span class="cal-pill">支出 <b class="expense">${money(data.expense)}</b></span>
    <span class="cal-pill">收入 <b class="income">${money(data.income)}</b></span>
    <span class="cal-pill">结余 <b>${money(data.balance)}</b></span>
    <span class="cal-pill cal-pill-soft">${activeDays} 天有记录</span>`;

  // 月首之前补空格，让 1 号落在正确的星期列
  const blanks = '<span class="cal-cell is-blank"></span>'.repeat(data.leading);
  const max = calendarMax(data);
  $('#cal-grid').innerHTML = blanks + data.days.map((day) => calCell(day, max)).join('');

  // 明细区保持展开状态，但内容要跟着新数据走
  if (calState.selected) highlightDay(calState.selected);
}

/** 当前口径下"最大的一天"，用来做颜色深浅的基准 */
function calendarMax(data) {
  switch (calState.mode) {
    case 'income':
      return data.max_income;
    case 'balance':
      return Math.max(...data.days.map((day) => Math.abs(day.balance)), 0);
    case 'both':
      return Math.max(data.max_expense, data.max_income);
    default:
      return data.max_expense;
  }
}

/** 当前口径下的代表金额，决定格子颜色深浅 */
function calendarValue(day) {
  switch (calState.mode) {
    case 'income':
      return day.income;
    case 'balance':
      return Math.abs(day.balance);
    case 'both':
      return Math.max(day.expense, day.income);
    default:
      return day.expense;
  }
}

function calCell(day, max) {
  const hasRecord = day.count > 0;
  const value = calendarValue(day);
  const alpha = hasRecord && max > 0 ? 0.16 + 0.74 * Math.min(value / max, 1) : 0;
  const tint = CAL_TINT[calState.mode] || CAL_TINT.both;

  const classes = ['cal-cell'];
  if (!hasRecord) classes.push('is-empty');
  if (day.is_today) classes.push('is-today');
  if (calState.selected === day.date) classes.push('is-active');

  // 没记录的日子不写 --cell-bg，交给 CSS 的浅灰底色
  const style = hasRecord ? ` style="--cell-bg: rgba(${tint}, ${alpha.toFixed(2)})"` : '';

  return `
    <button type="button" class="${classes.join(' ')}" data-day="${day.date}"${style}
            title="${day.date}">
      <span class="cal-num">${day.day}</span>
      <span class="cal-amounts">${calAmountLines(day)}</span>
    </button>`;
}

/** 每个格子里的金额：不同口径显示的内容不同 */
function calAmountLines(day) {
  const line = (kind, text) => `<span class="cal-amount ${kind}">${text}</span>`;
  const expense = line('expense', `-${money(day.expense)}`);
  const income = line('income', `+${money(day.income)}`);
  const balance = line(
    day.balance < 0 ? 'expense' : 'income',
    `${day.balance < 0 ? '-' : '+'}${money(Math.abs(day.balance))}`,
  );

  switch (calState.mode) {
    case 'income':
      return income;
    case 'both':
      return expense + income;
    case 'balance':
      return balance;
    default:
      return expense;
  }
}

/* ------------------------------- 当日明细 ------------------------------- */
function highlightDay(date) {
  document.querySelectorAll('#cal-grid [data-day]').forEach((cell) => {
    cell.classList.toggle('is-active', cell.dataset.day === date);
  });
}

async function openDay(date) {
  calState.selected = date;
  highlightDay(date);

  const detail = $('#cal-detail');
  detail.classList.remove('hidden');
  detail.innerHTML = '<p class="loading">加载中…</p>';

  try {
    const data = await api(`/api/records?date=${date}`);
    const [year, mon, day] = date.split('-').map(Number);
    const weekday = WEEKDAY_NAMES[new Date(year, mon - 1, day).getDay()];
    const expense = data.records
      .filter((record) => record.type === 'expense')
      .reduce((sum, record) => sum + record.amount, 0);
    const income = data.records
      .filter((record) => record.type === 'income')
      .reduce((sum, record) => sum + record.amount, 0);

    detail.innerHTML = `
      <div class="cal-detail-head">
        <span class="cal-detail-date">${mon}月${day}日 · ${weekday}</span>
        <span class="cal-detail-sum">
          支出 <b class="expense">${money(expense)}</b> · 收入 <b class="income">${money(income)}</b>
        </span>
        <button type="button" class="btn-icon" id="cal-detail-close" title="收起">✕</button>
      </div>
      ${data.records.length
        ? `<ul class="record-list">${data.records.map(recordItem).join('')}</ul>`
        : '<p class="empty">这天还没有记录 🍃</p>'}`;

    $('#cal-detail-close').addEventListener('click', closeDay);
    detail.querySelectorAll('[data-delete]').forEach((btn) => {
      btn.addEventListener('click', () => removeRecord(Number(btn.dataset.delete)));
    });
  } catch (err) {
    detail.innerHTML = `<p class="empty">😵 ${err.message}</p>`;
  }
}

function closeDay() {
  calState.selected = '';
  $('#cal-detail').classList.add('hidden');
  document.querySelectorAll('#cal-grid .is-active').forEach((cell) => cell.classList.remove('is-active'));
}

/* ------------------------------- 初始化 ------------------------------- */
function initCalendar() {
  calState.month = currentMonth();
  calState.mode = 'expense';
  calState.selected = '';

  $('#cal-prev').addEventListener('click', () => loadCalendar(shiftMonth(calState.month, -1)));
  $('#cal-next').addEventListener('click', () => loadCalendar(shiftMonth(calState.month, 1)));
  $('#cal-today').addEventListener('click', () => {
    closeDay();
    loadCalendar(currentMonth());
  });

  // 切换 支出 / 收入 / 收支 / 结余
  $('#cal-tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('.cal-tab');
    if (!tab || tab.dataset.mode === calState.mode) return;
    calState.mode = tab.dataset.mode;
    $('#cal-tabs').querySelectorAll('.cal-tab').forEach((el) => {
      el.classList.toggle('is-active', el === tab);
    });
    renderCalendar();
  });

  // 格子是动态生成的，用事件委托；再点同一天就收起明细
  $('#cal-grid').addEventListener('click', (event) => {
    const cell = event.target.closest('[data-day]');
    if (!cell) return;
    if (calState.selected === cell.dataset.day) closeDay();
    else openDay(cell.dataset.day);
  });

  loadCalendar();
}

window.CalendarView = { init: initCalendar, reload: reloadCalendar };
