/* ==========================================================================
   AI 桌宠「账小猪」
   - 它不是单独的入口页，而是常驻在窗口右下角的浮层，随时都能戳它；
   - 摸摸 / 喂食 / 跳舞：本地反应，点了立刻有反馈，手感不依赖网络；
   - 聊天 / 播报：走 /api/pet/chat，话术跟着真实账本走。
   ========================================================================== */
(() => {
  const $ = (selector) => document.querySelector(selector);

  // 心情决定脸和文案，脸挂在头顶的小气泡里
  const MOODS = {
    happy: { face: '😊', label: '开心' },
    curious: { face: '👀', label: '好奇' },
    proud: { face: '🥳', label: '得意' },
    worry: { face: '😰', label: '担心' },
  };

  // 本地互动台词：轮着说不重复
  const REACTIONS = {
    pet: ['呼噜呼噜～再摸摸！', '唔…舒服，我把账本都舔干净了。', '别闹啦，我在算这个月的账呢～'],
    feed: ['咔嚓咔嚓！这个苹果记在「餐饮」里了吗？', '好吃！谢谢投喂，我更有力气攒钱了。', '再来一个嘛，我帮你把花销也啃掉！'],
    dance: ['转圈圈～省下来的钱都进罐子！', '看我扭一扭，记账也可以很开心。', '啦啦啦～今天也是好好记账的一天！'],
  };

  const FLY_ICON = { pet: '💗', feed: '🍎', dance: '🎵' };
  const ANIM_CLASS = { pet: 'is-pet', feed: 'is-eat', dance: 'is-dance' };

  const state = { ready: false, busy: false, cursor: {} };

  function setMood(mood) {
    const key = MOODS[mood] ? mood : 'happy';
    $('#pet-mood').textContent = MOODS[key].face;
    $('#pet-mood-label').textContent = `心情：${MOODS[key].label}`;
    $('#pet-body').dataset.mood = key;
  }

  function say(text, options = {}) {
    const bubble = $('#pet-bubble');
    bubble.textContent = text;
    bubble.classList.remove('is-pop');
    void bubble.offsetWidth; // 强制重排，动画才会重新播一次
    bubble.classList.add('is-pop');
    if (options.mood) setMood(options.mood);
    if (options.source) $('#pet-source').textContent = options.source;
  }

  /** 飘一个小图标出去，让互动有"实物感" */
  function fly(icon) {
    const stage = $('.pet-stage');
    const node = document.createElement('span');
    node.className = 'pet-fly';
    node.textContent = icon;
    node.style.setProperty('--fly-x', `${Math.round(Math.random() * 90 - 45)}px`);
    stage.appendChild(node);
    setTimeout(() => node.remove(), 1500);
  }

  function react(action) {
    const lines = REACTIONS[action];
    if (!lines) return;

    const next = ((state.cursor[action] ?? -1) + 1) % lines.length;
    state.cursor[action] = next;

    const body = $('#pet-body');
    body.classList.remove('is-pet', 'is-eat', 'is-dance');
    void body.offsetWidth;
    body.classList.add(ANIM_CLASS[action]);

    // 动作放完就把类摘掉，否则它会顶掉漂浮动画、停在原地
    body.addEventListener('animationend', () => {
      body.classList.remove('is-pet', 'is-eat', 'is-dance');
    }, { once: true });

    fly(FLY_ICON[action]);
    say(lines[next]);
  }

  async function ask(message) {
    const text = String(message || '').trim();
    if (!text || state.busy) return;
    state.busy = true;

    const bubble = $('#pet-bubble');
    bubble.classList.add('is-thinking');
    bubble.textContent = '让我翻翻账本…';
    $('#pet-source').textContent = '思考中…';

    try {
      const reply = await api('/api/pet/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, month: currentMonth() }),
      });
      say(reply.text, {
        mood: reply.mood,
        source: reply.source === 'ai' ? 'AI 模式' : '规则模式',
      });
      if (reply.mood === 'proud') fly('🎉');
    } catch (err) {
      say(`😵 ${err.message}`, { mood: 'worry', source: '出错了' });
    } finally {
      bubble.classList.remove('is-thinking');
      state.busy = false;
    }
  }

  async function greet() {
    try {
      const data = await api(`/api/pet/greeting?month=${currentMonth()}`);
      say(data.text, { mood: data.mood, source: '规则模式' });
    } catch {
      say('我是账小猪，今天记了几笔啦？');
    }
  }

  /** 账本有变动时重新报一次数（正在打字 / 思考就先不打扰它） */
  function refresh() {
    if (!state.busy) greet();
  }

  function init() {
    if (state.ready) {
      refresh();
      return;
    }
    state.ready = true;

    $('#pet-body').addEventListener('click', () => {
      react('pet');
      // 触屏没有 hover，点一下小猪就把互动区展开
      $('#pet-dock')?.classList.add('is-open');
    });

    // 点到别处自动收起，省得一直挡着界面
    document.addEventListener('click', (event) => {
      const dock = $('#pet-dock');
      if (dock && !dock.contains(event.target)) dock.classList.remove('is-open');
    });

    document.querySelectorAll('[data-pet-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.petAction;
        if (action === 'report') ask('播报一下我这个月花了多少');
        else react(action);
      });
    });

    document.querySelectorAll('[data-pet-ask]').forEach((btn) => {
      btn.addEventListener('click', () => ask(btn.dataset.petAsk));
    });

    $('#pet-form').addEventListener('submit', (event) => {
      event.preventDefault();
      const input = $('#pet-input');
      const text = input.value;
      input.value = '';
      ask(text);
    });

    refresh();
  }

  window.PetView = { init, refresh };
})();
