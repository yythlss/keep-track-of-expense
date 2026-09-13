/* ==========================================================================
   小账本 · 金库动效与音效
   --------------------------------------------------------------------------
   视觉：金币旋转坠落（纯 CSS keyframes，无图片、无精灵图）
   听觉：Web Audio 实时合成「叮—当—咚」，不加载任何音频文件
   两者都不依赖 CDN 与构建工具，断网也能出声、也能动 —— 与项目「零依赖」的
   前端约定保持一致，同时避免往仓库里塞二进制资源。
   ========================================================================== */
(function (window) {
  'use strict';

  var MUTE_KEY = 'money.coinSound';

  /* ------------------------------------------------------------------ 存储 */
  // 隐私模式下 localStorage 可能直接抛异常，这里统一兜住
  function readMuted() {
    try {
      return window.localStorage.getItem(MUTE_KEY) === 'off';
    } catch (err) {
      return false;
    }
  }

  function writeMuted(value) {
    try {
      window.localStorage.setItem(MUTE_KEY, value ? 'off' : 'on');
    } catch (err) {
      /* 存不下就算了，不影响本次会话内的开关 */
    }
  }

  var muted = readMuted();

  /* ------------------------------------------------------------------ 音频 */
  var audioCtx = null;

  function context() {
    if (audioCtx) {
      if (audioCtx.state === 'suspended') audioCtx.resume();
      return audioCtx;
    }
    var Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null; // 老浏览器/被禁用：静默降级成「只有动画、没有声音」
    try {
      audioCtx = new Ctor();
    } catch (err) {
      return null;
    }
    return audioCtx;
  }

  /**
   * 一个带指数衰减的音符。
   * 指数衰减是金属/打击类音色的关键：起音极快（6ms），余音平滑收干。
   */
  function tone(ctx, opts) {
    var at = opts.at;
    var dur = opts.dur;
    var osc = ctx.createOscillator();
    var amp = ctx.createGain();

    osc.type = opts.type || 'triangle';
    osc.frequency.setValueAtTime(opts.freq, at);
    if (opts.detune) osc.detune.setValueAtTime(opts.detune, at);

    // exponentialRamp 不能碰 0，所以从一个极小值起步
    amp.gain.setValueAtTime(0.0001, at);
    amp.gain.exponentialRampToValueAtTime(opts.gain || 0.12, at + 0.006);
    amp.gain.exponentialRampToValueAtTime(0.0001, at + dur);

    osc.connect(amp);
    amp.connect(ctx.destination);
    osc.start(at);
    osc.stop(at + dur + 0.03);
  }

  /** 一小段带通白噪声，用来模拟金属互撞的「沙」质感 */
  function noise(ctx, opts) {
    var dur = opts.dur || 0.07;
    var frames = Math.max(1, Math.floor(ctx.sampleRate * dur));
    var buffer = ctx.createBuffer(1, frames, ctx.sampleRate);
    var data = buffer.getChannelData(0);

    for (var i = 0; i < frames; i += 1) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / frames); // 自带衰减包络
    }

    var src = ctx.createBufferSource();
    src.buffer = buffer;

    var band = ctx.createBiquadFilter();
    band.type = 'bandpass';
    band.frequency.value = opts.freq || 2800;
    band.Q.value = opts.q || 1.2;

    var amp = ctx.createGain();
    amp.gain.value = opts.gain || 0.08;

    src.connect(band);
    band.connect(amp);
    amp.connect(ctx.destination);
    src.start(opts.at);
  }

  /**
   * 一枚硬币落进存钱罐，三段式：
   *   ①「叮」硬币在空中旋转，金属共鸣（两个略微失谐的三角波叠加泛音）
   *   ②「当」撞到罐壁的短促脆响（带通噪声）
   *   ③「咚」落到罐底的闷响（低频正弦）
   * @param {number} index 第几枚硬币，用来把多枚硬币的声音错开成「哗啦」一片
   */
  function coinDrop(index) {
    if (muted) return;
    var ctx = context();
    if (!ctx) return;

    // 最多错开 0.36s，否则一笔大额存钱要等半天才响完
    var t = ctx.currentTime + Math.min((index || 0) * 0.06, 0.36) + 0.02;
    var pitch = 0.9 + Math.random() * 0.35; // 音高微随机，避免听感像机器

    tone(ctx, { at: t, freq: 1180 * pitch, dur: 0.34, gain: 0.09 });
    tone(ctx, { at: t, freq: 1770 * pitch, dur: 0.26, gain: 0.045, detune: 14 });
    tone(ctx, { at: t + 0.004, freq: 2360 * pitch, dur: 0.16, gain: 0.025 });

    noise(ctx, { at: t + 0.13, freq: 2900 * pitch, q: 1.3, dur: 0.06, gain: 0.07 });
    tone(ctx, { at: t + 0.15, freq: 165, dur: 0.22, type: 'sine', gain: 0.1 });
  }

  /** 攒满目标：C-E-G-C 上行琶音，比单枚硬币更"值钱"的听感 */
  function celebrate() {
    if (muted) return;
    var ctx = context();
    if (!ctx) return;

    var t = ctx.currentTime + 0.06;
    var scale = [523.25, 659.25, 783.99, 1046.5];
    for (var i = 0; i < scale.length; i += 1) {
      tone(ctx, { at: t + i * 0.09, freq: scale[i], dur: 0.42, gain: 0.09, type: 'sine' });
    }
  }

  /* ------------------------------------------------------------------ 动画 */
  var GLYPHS = ['¥', '🪙', '💰'];
  var MAX_COINS = 12;
  var MAX_SOUNDS = 6; // 声音超过 6 枚就糊成一片，只留视觉继续掉

  function prefersReducedMotion() {
    return (
      window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    );
  }

  /**
   * 在 stage 里生成若干枚旋转坠落的金币。
   * @param {Object} opts
   * @param {HTMLElement} opts.stage 定位容器（需 position: relative）
   * @param {number} opts.count 金币数量，内部会夹到 1~12
   * @param {boolean} opts.sound 是否同时播放硬币入罐音效
   */
  function drop(opts) {
    opts = opts || {};
    var stage = opts.stage;
    if (!stage) return;

    var total = Math.max(1, Math.min(Math.round(opts.count || 5), MAX_COINS));
    var withSound = opts.sound !== false;
    var reduce = prefersReducedMotion();

    for (var i = 0; i < total; i += 1) {
      var coin = document.createElement('span');
      coin.className = 'coin';
      coin.textContent = GLYPHS[i % GLYPHS.length];
      coin.setAttribute('aria-hidden', 'true');

      var spread = 46;
      coin.style.setProperty('--dx', (Math.random() * spread - spread / 2).toFixed(1) + 'px');
      coin.style.setProperty('--dur', (0.68 + Math.random() * 0.24).toFixed(2) + 's');
      coin.style.setProperty('--delay', (i * 0.075).toFixed(2) + 's');

      if (reduce) {
        // 尊重系统「减弱动态效果」：不做位移与旋转
        coin.style.animation = 'none';
        coin.style.opacity = '0';
        (function (node) {
          window.setTimeout(function () {
            node.remove();
          }, 200);
        })(coin);
      } else {
        coin.addEventListener('animationend', function () {
          this.remove();
        });
      }

      stage.appendChild(coin);

      if (withSound && i < MAX_SOUNDS) coinDrop(i);
    }
  }

  /* -------------------------------------------------------------- 音效开关 */
  function setMuted(value) {
    muted = Boolean(value);
    writeMuted(muted);
    return muted;
  }

  function toggleSound() {
    return setMuted(!muted);
  }

  function isSoundOn() {
    return !muted;
  }

  /* 浏览器自动播放策略：首次点击时先把 AudioContext 建好，后续 await 之后再
     播放也不会被挂起。 */
  window.addEventListener(
    'click',
    function unlock() {
      context();
    },
    { once: true }
  );

  window.CoinFX = {
    drop: drop,
    coinDrop: coinDrop,
    celebrate: celebrate,
    toggleSound: toggleSound,
    isSoundOn: isSoundOn,
    setMuted: setMuted
  };
})(window);
