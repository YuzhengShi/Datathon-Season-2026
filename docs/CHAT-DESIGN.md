# 聊天窗口（Find a match）的界面设计

目标：少读字、多看图。结果用紧凑卡片表达，右侧栏做摘要而不是重复卡片。接口、匹配状态和证据链接都沿用原来的，这里只描述界面。

## 布局

| 区域 | 内容 |
| --- | --- |
| 顶部 | 标题；连接状态胶囊（绿点 `AI connected`、橙点 `AI not configured`、灰点 `Preview`，悬停显示完整说明）；`New chat`；关闭 |
| 对话区 | 用户消息（右侧深绿气泡）；助手消息（头像 + 首句 + 结果卡片，无气泡）；等待时的打字动画；错误显示为琥珀色提示 |
| 输入区 | 自动增高的输入条（最多约 4 行）；建议问题胶囊（只在没有对话时出现）；隐私说明 |
| 右侧栏 | `Your profile`、`Where they apply`、`Sources`、信任说明与所用工具；还没有回答时显示空的 profile 和 `How it works` 三步 |

新的回答从它的第一行开始显示（卡片在其下方滚动），不会停在底部。重新打开对话框时回到最新的回答。

## 结果卡片

每条结果一张卡片，约 95 px 高：提供方头像（取提供方名称前两个有效词的首字母，颜色由名称固定哈希得到）、标题（最多两行，点击打开详情）、提供方名称、三个小标签、右侧的 ↗ 来源按钮（新窗口打开提供方页面）。

- 金额标签：已列金额为绿色，`Funding varies` 为灰色；悬停说明来源与确认提醒。
- 地区标签：写明地区的为实心，`Region not stated` 为虚线灰色。
- 匹配状态：`potential_fit` 显示绿色 `Conditions met`，`needs_information` 显示橙色 `Needs more info`；其他状态不显示标签，因为首句已经提醒 “Confirm current requirements with each provider”。完整原句 “Recorded conditions met; approval not guaranteed” 放在悬停提示里。
- 演示数据时，首句后会出现 `Example data` 标签。
- 所有来自记录的文字都经过转义（`scripts/qa-ui.cjs` 里有带恶意标题的用例）。

## 右侧栏

- `Your profile`：四行图标列表（Community、Level、Region、Goal），取自答案里的 `profile`；没说到的显示 `—`。
- `Where they apply`：本次结果按 全国 / 地区专属 / 未写地区 分段，与 Statistics 页是同一套三类定义（`province` 为 `all`、具体地区、`null`）。
- `Sources`：提供方头像与记录数，最多 3 行，其余折叠为 `+N more provider`。
- “Ask about the data” 模式显示 `The data`：记录总数、全国、地区专属三个数字，不显示 profile。
- 手机（≤ 680 px）隐藏右侧栏，改为在答案里显示一行 profile 标签，卡片占满宽度。`New chat` 在顶部，所以手机上也能用。

## 不再显示的内容

- `intent` 那句复述（例如 “A Métis high-school student in Smithers …”）。后端的 profile 只有省份，没有城市，所以城市名不再出现。
- 每张卡片上重复的三行小字（金额提醒、地区、匹配状态）和 “Provider source ↗” 文字链接（现在是带 `aria-label` 的图标按钮）。

## 文件与测试

| 文件 | 内容 |
| --- | --- |
| `dist/assistant.css` | 聊天窗口的全部样式 |
| `dist/insights.js` | 卡片、消息和侧栏的渲染（`recordCard`、`messageHTML`、`evidenceHTML`、`scrollThread`） |
| `dist/index.html` | 对话框标记与新增图标 |
| `scripts/qa-ui.cjs` | 共 63 项，其中 6 项是这次新增的聊天检查：状态胶囊（2 项）、卡片结构、侧栏摘要、转义、分析模式 |
| `tests/e2e/site.mjs` | 真实 Chrome：卡片紧凑、侧栏不重复卡片、对话框不溢出、手机的标签行、`New chat`（桌面与手机各 7 项；回答用真实记录模拟，不调用模型） |
