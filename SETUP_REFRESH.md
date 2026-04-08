# 看板刷新功能配置指南

看板部署在 GitHub Pages，通过 **GitHub Actions** 自动/手动抓取数据。  
只需完成以下两步配置，即可使用「立即刷新」按钮。

---

## 第一步：在仓库中添加三个 Secrets

打开仓库页面：  
👉 `https://github.com/eightnrcn2025-create/gp-dashboard`

依次点击：**Settings → Secrets and variables → Actions → New repository secret**

添加以下三个 Secret：

| Name | Value（说明） |
|------|--------------|
| `GOOGLE_CREDENTIALS` | `credentials.json` 文件的**完整内容**（复制整个 JSON 文本粘贴） |
| `GAMEPARK_ACCOUNT`   | 后台登录账号（例：`eight`） |
| `GAMEPARK_PASSWORD`  | 后台登录密码（例：`eight123`） |

### GOOGLE_CREDENTIALS 获取方式

1. 打开本地项目目录 `~/Desktop/gp活动看板/`
2. 用文本编辑器打开 `credentials.json`
3. **全选复制**所有内容（包括花括号）
4. 粘贴到 GitHub Secret 的 Value 输入框中

---

## 第二步：创建 GitHub Personal Access Token（PAT）

GitHub Actions 工作流由 `GITHUB_TOKEN`（内置）自动触发推送，  
但**点击看板「立即刷新」按钮**需要你的个人 Token 来调用 API。

### 创建 Token

1. 打开：`https://github.com/settings/tokens`
2. 点击 **「Generate new token (classic)」**
3. 填写 Note（例：`gp-dashboard-refresh`）
4. 有效期：建议选 **1 year**（1年）
5. 勾选权限：**`repo`** 下的 **`workflow`**（仅需这一个）
6. 点击底部 **「Generate token」**
7. **立即复制** Token（离开页面后无法再查看）

### 在看板中输入 Token

1. 打开看板页面（GitHub Pages 地址）
2. 点击右上角「立即刷新」按钮
3. 弹窗中粘贴刚创建的 Token，点击确定
4. **Token 会保存在浏览器 localStorage 中，只需输入一次**

> 如需清除 Token（换号或 Token 过期），打开浏览器控制台执行：  
> `localStorage.removeItem('gh_pat')`

---

## 工作流说明

| 触发方式 | 说明 |
|---------|------|
| **每日自动** | 北京时间每天 00:05 自动运行，抓取昨日数据 |
| **手动触发** | 点击看板「立即刷新」按钮 → 调用 GitHub API 触发工作流 |

### 手动查看运行状态

`https://github.com/eightnrcn2025-create/gp-dashboard/actions`

---

## 常见问题

**Q：点击刷新后提示「Token 无效或无 workflow 权限」**  
A：重新创建 Token，确保勾选了 `workflow` 权限。

**Q：Actions 运行失败**  
A：查看 Actions 日志，常见原因：
- `GOOGLE_CREDENTIALS` 格式错误（需完整 JSON）
- `GAMEPARK_ACCOUNT` / `GAMEPARK_PASSWORD` 填写有误
- 后台网站结构变化导致 Playwright 抓取失败

**Q：Token 过期了**  
A：打开浏览器控制台输入 `localStorage.removeItem('gh_pat')`，然后重新输入新 Token。

**Q：数据更新后页面没有变化**  
A：GitHub Pages 有缓存，可以强制刷新（Cmd+Shift+R 或 Ctrl+Shift+R）。
