# 库街区自动签到 AstrBot 插件

自动完成库街区（kurobbs.com）每日签到，支持鸣潮/战双游戏签到 + 论坛任务。

## ✨ 功能

- 🎮 **鸣潮/战双游戏签到**（自动获取角色信息）
- 📝 **论坛每日任务**（签到、浏览、点赞、分享）
- 💰 金币查询
- 🤖 **GeeTest 滑块验证码自动解决**（无需手动过验证）

## 📋 命令

| 命令 | 说明 |
|------|------|
| `/库街区登录 <手机号>` | **一键登录**（自动过滑块→发短信→输入验证码→登录+签到） |
| `/库街区绑定 <token>` | 手动绑定 token |
| `/库街区签到` | 执行签到（游戏+论坛） |
| `/库街区状态` | 查看绑定状态 |
| `/库街区解绑` | 解绑 token |

## 🚀 快速开始

### 方式一：一键登录（推荐）

```
/库街区登录 177xxxxxxxx
```

Bot 会自动：
1. 解决 GeeTest 滑块验证码
2. 发送短信验证码到你的手机
3. 提示你回复验证码数字

你只需要：**看手机，把验证码数字发过来**。

### 方式二：手动绑定 Token

1. 浏览器登录 [库街区](https://www.kurobbs.com)
2. F12 → Application → Cookies → 找 `user_token`
3. 发送 `/库街区绑定 <token>`

## 📦 安装

### 1. 安装插件

将本仓库克隆到 AstrBot 插件目录：

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/huanxherta/astrbot_plugin_kuro_sign.git
```

### 2. 安装依赖

```bash
# AstrBot 的 Python 环境
pip install curl_cffi opencv-python-headless pycryptodome
```

> 如果 AstrBot 使用 venv，请在对应的 venv 中安装。

### 3. 重启 AstrBot

## ⚠️ 注意

- 仅供学习交流使用
- Token 保存在 AstrBot 本地，不会上传
- GeeTest 滑块解决依赖 [GeekedTest](https://github.com/xKiian/GeekedTest) 项目
