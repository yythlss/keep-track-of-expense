# Hackathon 作品模板（小游戏合集）

> 一个**开箱即用**的 Hackathon 起手模板：Fork → 点「云原生开发」→ 改代码 → 提 PR 自动检查 → 一键预览。
>
> 内置**三款纯前端 Canvas 小游戏**（超级玛丽 / 坦克大战 / 贪吃蛇），点开即玩，你可以直接在它基础上改造成自己的作品。

---

## 内置游戏

| 游戏 | 玩法 | 操作 |
|------|------|------|
| 🍄 超级玛丽 | 横版跳跃闯关，踩扁小怪、收集金币、抵达旗帜过关，共 2 关 | ← → 移动，空格 / ↑ 跳跃 |
| 🚜 坦克大战 | 俯视角射击，消灭全部敌方坦克获胜，小心别被击中 | WASD / 方向键移动，空格开火 |
| 🐍 贪吃蛇 | 经典贪吃蛇，吃食物变长得分，撞墙或咬到自己结束 | 方向键控制 |

全部为**纯 HTML + Canvas + 原生 JS**，无任何前端依赖，单文件即可运行。

---

## 快速上手（3 步）

1. **Fork 本仓库**到你自己的命名空间，建议改成你项目的名字（如 `my-games`）。
2. 进入仓库，点右上角橙色 **「云原生开发」**，选 **WebIDE**，开始 Vibe Coding。
3. 在终端启动静态服务，用 PORTS 面板预览（开发时用 **8080**，不要用 8686）：

   ```bash
   python -m http.server 8080 --bind 0.0.0.0
   ```

   然后在底部 **PORTS** 面板打开 `8080` 的预览链接即可。

   > ⚠️ **云原生开发模式下 8686 已被 WebIDE（code-server）占用**，直接绑 8686 会报 `Address already in use`。开发调试请另用一个空闲端口（如 8080）。
   >
   > 8686 是**仅预览模式**专用的业务端口（CNB 强制要求），也是 `Dockerfile` 与检查流水线约定的端口——这些都在**容器里**跑，和开发终端的 code-server 不冲突，无需改动。
   >
   > ⚠️ 必须 `--bind 0.0.0.0`，否则端口预览访问不到。

也可以用 Docker 跑（容器内部仍用 8686，对外映射到宿主任意空闲端口，如 8080）：

```bash
docker build -t my-games .
docker run -d -p 8080:8686 my-games
# 在 PORTS 面板打开 8080
```

---

## 项目结构

```
.
├── index.html            # 游戏大厅 三张卡片进入各游戏
├── games/
│   ├── mario.html        # 超级玛丽
│   ├── tank.html         # 坦克大战
│   └── snake.html        # 贪吃蛇
├── Dockerfile            # python http.server 静态托管
├── .cnb.yml              # 开发环境 + 镜像构建推送 + include 中心 CI 的检查
└── .cnb/settings.yml     # 自定义启动按钮
```

---

## PR 自动检查

检查流水线**不在本仓库维护**，而是由 `.cnb.yml` 通过 `include` 从中心 CI 仓库引入：

```yaml
include:
  - https://cnb.cool/whut1/ai-engineering-exercise-ci/-/blob/main/hackathon.yml
```

检查逻辑集中在中心 CI 仓库维护、统一升级。向 `main` 提 PR 时会自动跑以下检查：

| 阶段 | 检查内容 | 是否阻断 |
|------|---------|---------|
| 1 提交规范 | `README.md` + `Dockerfile` 齐全，README 内容充实 | 是 |
| 2 提交规范 | PR 提交信息符合约定式提交格式（`type: 描述`，如 `feat: ...`） | 是 |
| 3 可构建 | `docker build` 成功 | 是 |
| 4 可运行 | 起容器 + 端口探活（服务须监听 `0.0.0.0`） | 是 |
| 5 AI 评审 | CNB 大模型对作品打分并给改进建议 | 否（仅参考） |

全绿即代表作品达到「可运行、可演示」的基本要求。

> 💡 你**可以自由编辑自己的 `.cnb.yml`**（例如开启下文的仅预览模式、改端口、定制构建），检查不会因此报错；只要**保留对检查流水线的 `include`** 即可。

---

## 进阶：让评委「Fork 即玩」（一键预览）

想让别人不进 IDE、点一下就直接看到效果？配置**仅预览模式**：

1. 推送到 `main`，`.cnb.yml` 的 `main.push` 会自动构建镜像并推送到 CNB 制品库（记得把制品库设为**公有**）。
2. 把 `.cnb.yml` 的 `$.vscode` 段换成仅预览配置（`onlyPreview: true` + `launch` 拉起镜像），`launch` 里镜像地址要写**完整常量**：

   ```yaml
   $:
     vscode:
       - runner:
           cpus: 16
         services:
           - docker
           - name: vscode
             options:
               onlyPreview: true
               launch: docker run -d --network host -e PORT=8686 \
                       docker.cnb.cool/your-org/your-repo:latest
               keepAliveTimeout: 3600000
               daemon: true
   ```

   > ⚠️ `onlyPreview: true` 后主分支就进不去 IDE 了。建议**新建 dev 分支**保留开发用配置，主分支专用于对外展示。
   >
   > ⚠️ `launch` 里镜像地址**必须是常量**，不能用 `${CNB_...}` 变量，否则评委 Fork 后会解析到他自己没构建过镜像的仓库导致启动失败。

3. `.cnb/settings.yml` 已配好启动按钮，推送后仓库右上角即出现「🎮 开始游戏」。

---

## 换个方向做别的作品？

模板默认是小游戏合集，你也可以自由改造成任何方向的作品，只要保证：

- 作品在容器里**必须监听 `0.0.0.0:8686`**（检查流水线固定探活此端口，学员改不了，所以 `Dockerfile` 的 `EXPOSE` / `PORT` 都要保持 8686）
- `Dockerfile` 能构建、能运行
- `README.md` 讲清楚你的作品是什么、怎么玩

再想加游戏也很简单：在 `games/` 下新建一个 HTML，再到 `index.html` 加一张卡片即可。

Happy Hacking 🎉
