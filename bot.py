<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AWM OS</title>
  <meta name="description" content="AWM OS — AI-ассистент маркетинга в Telegram" />
  <style>
    :root{
      --bg1:#f3efff;
      --bg2:#ffffff;
      --text:#14141a;
      --muted:#6b6b78;
      --card:#ffffffcc;
      --stroke:rgba(30, 14, 66, .08);
      --shadow: 0 20px 60px rgba(40, 10, 90, .10);
      --shadow2: 0 12px 24px rgba(40, 10, 90, .10);
      --purple:#6D28D9;
      --purple2:#8B5CF6;
    }
    *{box-sizing:border-box}
    html,body{height:100%}

    /* ✅ animated background (pink-purple flowing) */
    body{
      margin:0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      color:var(--text);
      min-height:100vh;
      display:flex;
      justify-content:center;
      padding:24px 16px 92px;

      background: linear-gradient(180deg, var(--bg1), var(--bg2));
      position: relative;
      overflow-x: hidden;
    }
    body::before,
    body::after{
      content:"";
      position: fixed;
      inset: -30%;
      z-index: -1;
      background:
        radial-gradient(40% 35% at 20% 30%, rgba(168,85,247,.78), transparent 60%),
        radial-gradient(45% 40% at 70% 20%, rgba(236,72,153,.70), transparent 62%),
        radial-gradient(55% 45% at 60% 75%, rgba(109,40,217,.74), transparent 60%);
      filter: blur(42px) saturate(150%);
      opacity: .95;
      transform: translate3d(0,0,0);
      animation: glowMove 8.5s ease-in-out infinite;
    }
    body::after{
      background:
        radial-gradient(45% 40% at 30% 75%, rgba(236,72,153,.75), transparent 60%),
        radial-gradient(40% 35% at 80% 60%, rgba(139,92,246,.80), transparent 62%),
        radial-gradient(55% 45% at 50% 20%, rgba(109,40,217,.65), transparent 60%);
      opacity: .78;
      filter: blur(58px) saturate(160%);
      animation: glowMove2 10.5s ease-in-out infinite;
    }
    @keyframes glowMove{
      0%   { transform: translate(-3%, -2%) scale(1.03); }
      25%  { transform: translate(4%, -2%)  scale(1.08); }
      50%  { transform: translate(2%, 4%)   scale(1.04); }
      75%  { transform: translate(-4%, 2%)  scale(1.09); }
      100% { transform: translate(-3%, -2%) scale(1.03); }
    }
    @keyframes glowMove2{
      0%   { transform: translate(3%, 2%)   scale(1.07); }
      25%  { transform: translate(-3%, 4%)  scale(1.03); }
      50%  { transform: translate(-4%, -3%) scale(1.10); }
      75%  { transform: translate(4%, -2%)  scale(1.05); }
      100% { transform: translate(3%, 2%)   scale(1.07); }
    }
    @media (prefers-reduced-motion: reduce){
      body::before, body::after{ animation: none; }
    }

    .phone{
      width:min(420px, 100%);
    }

    /* Top badge */
    .icon-wrap{
      width:88px;height:88px;
      margin:18px auto 10px;
      border-radius:28px;
      background:
        radial-gradient(70px 70px at 30% 20%, rgba(255,255,255,.92), rgba(255,255,255,.35)),
        linear-gradient(135deg, rgba(109,40,217,.95), rgba(236,72,153,.82));
      box-shadow: 0 16px 30px rgba(109,40,217,.22);
      display:grid;place-items:center;
      position:relative;
    }
    .spark{
      width:42px;height:42px;
      filter: drop-shadow(0 8px 14px rgba(0,0,0,.20));
    }
    .bolt{
      position:absolute;
      right:-10px; bottom:10px;
      width:34px;height:34px;
      border-radius:999px;
      background:#fff;
      box-shadow: 0 10px 18px rgba(0,0,0,.12);
      display:grid;place-items:center;
      border:1px solid var(--stroke);
    }
    .bolt svg{width:18px;height:18px; color: var(--purple);}

    h1{
      text-align:center;
      margin:10px 0 4px;
      font-size:34px;
      letter-spacing:.5px;
    }
    .subtitle{
      text-align:center;
      margin:0;
      font-size:18px;
      line-height:1.35;
      color:var(--purple);
      font-weight:700;
    }
    .submuted{
      text-align:center;
      margin:10px 0 18px;
      color:var(--muted);
      font-weight:600;
    }

    /* Buttons */
    .btn{
      width:100%;
      display:flex;
      align-items:center;
      justify-content:center;
      gap:10px;
      padding:18px 18px;
      border-radius:20px;
      border:1px solid var(--stroke);
      text-decoration:none;
      font-weight:800;
      font-size:18px;
      box-shadow: var(--shadow2);
      user-select:none;
      backdrop-filter: blur(10px);
    }
    .btn.primary{
      background: linear-gradient(90deg, rgba(109,40,217,.98), rgba(236,72,153,.95));
      color:#fff;
      border:0;
      box-shadow: 0 18px 34px rgba(109,40,217,.25);
    }
    .btn.secondary{
      background: rgba(255,255,255,.75);
      color:var(--text);
      margin-top:12px;
    }
    .btn:active{transform: translateY(1px);}

    .section-title{
      text-align:center;
      margin:26px 0 10px;
      letter-spacing:.18em;
      color: rgba(109,40,217,.70);
      font-size:12px;
      font-weight:900;
    }

    /* Cards list */
    .list{
      display:flex;
      flex-direction:column;
      gap:14px;
      margin-top:10px;
    }
    .card{
      background: var(--card);
      border:1px solid var(--stroke);
      border-radius:22px;
      padding:14px 14px;
      display:flex;
      align-items:center;
      gap:12px;
      box-shadow: var(--shadow2);
      backdrop-filter: blur(12px);
    }
    .ic{
      width:46px;height:46px;
      border-radius:16px;
      background: rgba(109,40,217,.08);
      display:grid; place-items:center;
      border:1px solid rgba(109,40,217,.10);
      flex: 0 0 auto;
    }
    .ic svg{width:22px;height:22px;color:var(--purple);}
    .card h3{
      margin:0;
      font-size:16px;
      font-weight:900;
    }
    .card p{
      margin:2px 0 0;
      font-size:13px;
      color:var(--muted);
      font-weight:600;
    }
    .arrow{
      margin-left:auto;
      width:34px;height:34px;
      border-radius:12px;
      display:grid;place-items:center;
      color: rgba(20,20,26,.55);
      font-size:20px;
      line-height:1;
    }

    /* Bottom nav */
    .bottom{
      position:fixed;
      left:50%;
      transform:translateX(-50%);
      bottom:18px;
      width:min(420px, calc(100% - 32px));
      background: rgba(255,255,255,.72);
      border:1px solid var(--stroke);
      border-radius:24px;
      padding:12px 14px;
      display:flex;
      justify-content:space-around;
      align-items:center;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }
    .navbtn{
      width:46px;height:46px;
      border-radius:999px;
      display:grid;
      place-items:center;
      text-decoration:none;
      border:1px solid rgba(109,40,217,.10);
      background: rgba(109,40,217,.07);
    }
    .navbtn svg{width:22px;height:22px;color:var(--purple);}
    .foot{
      text-align:center;
      margin:18px 0 0;
      color: rgba(20,20,26,.35);
      font-weight:800;
      font-size:12px;
    }
  </style>
</head>
<body>
  <main class="phone">
    <div class="icon-wrap" aria-hidden="true">
      <!-- Spark icon -->
      <svg class="spark" viewBox="0 0 24 24" fill="none">
        <path d="M12 2l1.2 4.3a2 2 0 0 0 1.4 1.4L19 9l-4.4 1.3a2 2 0 0 0-1.4 1.4L12 16l-1.2-4.3a2 2 0 0 0-1.4-1.4L5 9l4.4-1.3a2 2 0 0 0 1.4-1.4L12 2Z" fill="white" opacity=".95"/>
        <path d="M19.5 12.5l.7 2.5a1.2 1.2 0 0 0 .8.8l2.5.7-2.5.7a1.2 1.2 0 0 0-.8.8l-.7 2.5-.7-2.5a1.2 1.2 0 0 0-.8-.8l-2.5-.7 2.5-.7a1.2 1.2 0 0 0 .8-.8l.7-2.5Z" fill="white" opacity=".9"/>
      </svg>
      <div class="bolt" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="currentColor">
          <path d="M13 2L3 14h7l-1 8 12-14h-7l-1-6Z"/>
        </svg>
      </div>
    </div>

    <h1>AWM OS</h1>
    <p class="subtitle">AI-ассистент маркетинга<br/>в Telegram</p>
    <p class="submuted">Контент • реклама • отчёты 24/7</p>

    <!-- Two links only: Bot + Website -->
    <a class="btn primary" href="https://t.me/AWMOS_bot" target="_blank" rel="noopener">
      Открыть AI-ассистента в Telegram
      <span aria-hidden="true">›</span>
    </a>

    <a class="btn secondary" href="https://awm-os.vercel.app" target="_blank" rel="noopener">
      Открыть сайт
    </a>

    <div class="section-title">НАШИ РЕШЕНИЯ</div>

    <div class="list">
      <div class="card">
        <div class="ic" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19V5" />
            <path d="M4 19h16" />
            <path d="M7 14l3-3 3 2 4-5" />
          </svg>
        </div>
        <div>
          <h3>AI Аналитика</h3>
          <p>Глубокий анализ вашей аудитории</p>
        </div>
        <div class="arrow" aria-hidden="true">›</div>
      </div>

      <div class="card">
        <div class="ic" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="6" width="16" height="12" rx="3"/>
            <path d="M8 10h8"/>
            <path d="M10 14h4"/>
          </svg>
        </div>
        <div>
          <h3>Telegram Автоматизация</h3>
          <p>Умные боты и воронки продаж</p>
        </div>
        <div class="arrow" aria-hidden="true">›</div>
      </div>

      <div class="card">
        <div class="ic" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 12h16"/>
            <path d="M7 8l-3 4 3 4"/>
            <path d="M17 8l3 4-3 4"/>
          </svg>
        </div>
        <div>
          <h3>Smart Трафик</h3>
          <p>Оптимизация рекламного бюджета</p>
        </div>
        <div class="arrow" aria-hidden="true">›</div>
      </div>
    </div>

    <div class="foot">AWM OS © 2026</div>
  </main>

  <!-- Bottom nav: quick access to the same 2 links -->
  <nav class="bottom" aria-label="Навигация">
    <a class="navbtn" href="https://t.me/AWMOS_bot" target="_blank" rel="noopener" aria-label="Telegram Bot">
      <svg viewBox="0 0 24 24" fill="currentColor">
        <path d="M21.8 4.6 2.9 11.9c-1.3.5-1.3 1.2-.2 1.5l4.9 1.5 1.9 5.8c.2.6.1.9.7.9.5 0 .7-.2 1-.5l2.8-2.7 5.8 4.3c1.1.6 1.8.3 2.1-1l3.4-16c.4-1.6-.6-2.3-1.5-1.7ZM9.8 14.5l9.9-6.2c.5-.3.9.1.5.5l-8 7.2-.3 3.7-1.7-5.2-.4-.1Z"/>
      </svg>
    </a>

    <a class="navbtn" href="https://awm-os.vercel.app" target="_blank" rel="noopener" aria-label="Website">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--purple);">
        <circle cx="12" cy="12" r="9"/>
        <path d="M3 12h18"/>
        <path d="M12 3c3 3 3 15 0 18"/>
        <path d="M12 3c-3 3-3 15 0 18"/>
      </svg>
    </a>

    <a class="navbtn" href="https://t.me/AWMOS_bot" target="_blank" rel="noopener" aria-label="Open Bot">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--purple);">
        <path d="M12 21s7-4.4 7-11a7 7 0 0 0-14 0c0 6.6 7 11 7 11Z"/>
        <circle cx="12" cy="10" r="2.2"/>
      </svg>
    </a>
  </nav>
</body>
</html>
