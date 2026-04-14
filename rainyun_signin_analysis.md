# Rainyun 每日签到流程分析

## 目标

脚本完整复现这条链路：

1. 登录 `https://app.rainyun.com/account/reward/earn`
2. 进入积分页并定位 `每日签到`
3. 点击 `领取奖励` 拉起腾讯点选验证码
4. 截取当前验证码完整区域
5. 调用 `TenVision/main.py` 识别点击顺序坐标
6. 在验证码 iframe 内完成点选
7. 直接走协议提交 `cap_union_new_verify`
8. 再调用雨云签到接口完成领取

主脚本：`rainyun_signin.py`

---

## 整体思路

### 1. 登录

脚本先进入雨云积分页，然后直接调用登录接口：

- `POST https://api.v2.rainyun.com/user/login`

登录成功后，浏览器上下文会持有：

- `rain-session`
- `X-CSRF-Token`

后续雨云接口继续复用当前浏览器上下文。

### 2. 读取每日签到状态

脚本请求：

- `GET https://api.v2.rainyun.com/user/reward/tasks`

然后找到：

- `Name == "每日签到"`

如果 `Status == 2`，说明今天已经签到，脚本直接结束。

### 3. 拉起验证码

优先走页面真实交互：

- 在 `每日签到` 卡片内点击 `领取奖励`

如果页面点击没有成功拉起验证码，再 fallback 到：

- `window.TencentCaptcha(...).show()`

验证码弹出后，会出现腾讯验证码 iframe，同时页面会请求：

- `GET https://turing.captcha.qcloud.com/cap_union_prehandle?...`

这里会拿到当前题目的关键参数：

- `sess`
- `dyn_show_info`
- `comm_captcha_cfg`
- `pow_cfg`
- `bg_elem_cfg.size_2d`

---

## Captcha 的 solve 方式

### 结论

这个项目里的点选验证码采用：

- **浏览器负责拉起并截图运行时验证码**
- **TenVision 负责识别点击坐标**
- **我们自己负责协议 verify**

### 为什么浏览器是必须的

因为 solve 依赖的是**当前运行时里真正渲染出来的验证码完整图**，不是简单抓一个固定接口就够了。

当前脚本会在验证码 iframe 内等待这些元素就绪：

- `#tcWrap`
- `#slideBg`
- `.tc-instruction-icon img`

然后直接对：

- `#tcWrap`

做截图。

这张图同时包含：

- 顶部题目区域
- 主图区域

然后把这张完整截图交给：

- `TenVision/main.py`

调用方式：

```bash
python TenVision/main.py <captcha.png> <captcha_out.png>
```

TenVision 的 stdout 中会输出：

```text
点击顺序坐标: [(x1, y1), (x2, y2), (x3, y3)]
```

脚本解析这 3 个点后，做两件事：

1. 把它们作为 `#tcWrap` 内的点击坐标，真实点进验证码
2. 把它们映射回背景图自然尺寸坐标，组装协议里的 `ans`

---

## 协议 verify

验证码点完之后，脚本不会走页面原始提交，而是直接请求：

- `POST https://turing.captcha.qcloud.com/cap_union_new_verify`

### verify 关键字段来源

这次不是去调用不存在的全局方法，而是直接从 iframe 运行时取：

- `window.TDC.getData(true)`
- `window.TDC.getInfo().info`

对应关系是：

- `collect = decodeURIComponent(window.TDC.getData(true))`
- `tlg = collect.length`
- `eks = window.TDC.getInfo().info`
- `sess = prehandle.sess`
- `ans = JSON.stringify([...])`

如果题目开启了 POW，再补：

- `pow_answer`
- `pow_calc_time`

如果运行时存在 `window.getVData`，脚本也会把它补进去。

### ans 格式

`ans` 的结构是：

```json
[
  {"elem_id":1,"type":"DynAnswerType_POS","data":"x,y"},
  {"elem_id":2,"type":"DynAnswerType_POS","data":"x,y"},
  {"elem_id":3,"type":"DynAnswerType_POS","data":"x,y"}
]
```

这里的 `x,y` 不是页面像素，而是映射回验证码背景自然尺寸后的坐标。

---

## 雨云签到提交

verify 成功后会返回：

- `ticket`
- `randstr`

然后脚本直接调用：

- `POST https://api.v2.rainyun.com/user/reward/tasks`

请求体：

```json
{
  "task_name": "每日签到",
  "verifyCode": "",
  "vticket": "<ticket>",
  "vrandstr": "<randstr>"
}
```

返回 `code == 200` 即表示签到完成。

---

## 代码结构

### `rainyun_signin.py`

核心函数：

- `login_via_protocol()`：协议登录
- `get_daily_task()`：读取每日签到状态
- `trigger_daily_signin()`：点击页面上的 `领取奖励`
- `wait_for_captcha_frame()`：等待验证码 iframe
- `solve_points_with_tenvision()`：截图并调用 `TenVision/main.py`
- `click_points()`：按识别结果在验证码内真实点击
- `build_verify_payload()`：从运行时拼出 verify 参数
- `post_verify()`：协议提交腾讯 verify
- `perform_signin()`：完成整个签到流程

### `TenVision/main.py`

不抽取内部算法，直接把它当外部识别器使用。

---

## 使用方式

### 1. 安装依赖

```bash
uv sync
```

### 2. 正常运行

```bash
uv run python rainyun_signin.py
```

### 3. 有头运行

```bash
uv run python rainyun_signin.py --headful
```

### 4. 指定账号文件

```bash
uv run python rainyun_signin.py --env .env
```

### 5. 离线测试 TenVision

输入一张完整验证码截图：

```bash
uv run python rainyun_signin.py --sample TenVision/images/6.png
```

脚本会在同目录生成标注结果图，并打印识别坐标。
