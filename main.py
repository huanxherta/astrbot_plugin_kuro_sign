"""
库街区自动签到 AstrBot 插件
支持：鸣潮/战双游戏签到 + 论坛每日任务
"""

import asyncio
import time
import random
import string
import uuid
import json
import socket
from typing import Optional, Dict, Any, List
from datetime import datetime

import httpx
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

# ── API 端点 ──────────────────────────────────────────────

API_BASE = "https://api.kurobbs.com"

ENDPOINTS = {
    # 用户
    "user_mine": f"{API_BASE}/user/mineV2",
    "user_sign_in": f"{API_BASE}/user/signIn",
    "role_list": f"{API_BASE}/gamer/role/list",
    # 论坛
    "forum_list": f"{API_BASE}/forum/list",
    "post_detail": f"{API_BASE}/forum/getPostDetail",
    "forum_like": f"{API_BASE}/forum/like",
    # 任务
    "task_process": f"{API_BASE}/encourage/level/getTaskProcess",
    "task_share": f"{API_BASE}/encourage/level/shareTask",
    # 金币
    "gold_total": f"{API_BASE}/encourage/gold/getTotalGold",
    # 游戏签到
    "game_sign_in": f"{API_BASE}/encourage/signIn/v2",
    "game_sign_record": f"{API_BASE}/encourage/signIn/queryRecordV2",
    "game_sign_init": f"{API_BASE}/encourage/signIn/initSignInV2",
    "game_replenish_sign": f"{API_BASE}/encourage/signIn/repleSigInV2",
}

# 游戏类型  gameId=2 鸣潮, gameId=3 战双
GAMES = {
    "wuwa": {"id": "2", "name": "鸣潮", "server_id": "1000"},
    "pgr": {"id": "3", "name": "战双", "server_id": "7f574e49b1f24c4c915e74bb1dfd4e4d"},
}

# 错误码
ERR_SUCCESS = 200
ERR_ALREADY_SIGNED = 1511
ERR_USER_INFO_ERROR = 1513
ERR_LOGIN_EXPIRED = 220


def _random_str(length=32):
    return "".join(random.choices(string.hexdigits.lower(), k=length))


def _get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except socket.error:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# ── 请求头生成（H5 版本）────────────────────────────────────────────

def _h5_headers(token: str, devcode: str, distinct_id: str) -> dict:
    """H5 版请求头，配合 sdkLoginForH5 获取的 token 使用"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Host": "api.kurobbs.com",
        "Origin": "https://www.kurobbs.com",
        "Referer": "https://www.kurobbs.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (X11; Linux x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "sec-gpc": "1",
        "DNT": "1",
        "source": "h5",
        "version": "3.0.1",
        "devCode": devcode,
        "distinct_id": distinct_id,
        "token": token,
    }


# ── 核心签到逻辑 ──────────────────────────────────────────

class KuroClient:
    """库洛 API 异步客户端"""

    def __init__(self, token: str, devcode: str = "", distinct_id: str = "", ip: str = ""):
        self.token = token
        self.devcode = devcode or str(uuid.uuid4())
        self.distinct_id = distinct_id or str(uuid.uuid4())
        self.ip = ip or _get_ip()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def post(self, url: str, data: dict = None) -> dict:
        """统一 H5 POST 请求"""
        client = await self._get_client()
        headers = _h5_headers(self.token, self.devcode, self.distinct_id)
        resp = await client.post(url, headers=headers, data=data or {})
        return resp.json()

    async def get_user_id(self) -> Optional[str]:
        """获取库街区 userId"""
        try:
            result = await self.post(ENDPOINTS["user_mine"], {"size": "10"})
            if result.get("code") == 200 and result.get("data"):
                uid = result["data"].get("mine", {}).get("userId")
                if uid:
                    return str(uid)
        except Exception as e:
            logger.warning(f"获取userId失败: {e}")
        return None

    async def get_role_ids(self) -> Dict[str, Dict]:
        """获取游戏角色信息，返回 {gameId: {roleId, serverId}}"""
        roles = {}
        for game_key, game in GAMES.items():
            try:
                result = await self.post(ENDPOINTS["role_list"], {"gameId": game["id"]})
                if result.get("code") == 200 and result.get("data"):
                    role_list = result["data"]
                    if isinstance(role_list, list) and len(role_list) > 0:
                        r = role_list[0]
                        roles[game["id"]] = {
                            "roleId": str(r.get("roleId", "")),
                            "serverId": str(r.get("serverId", game["server_id"])),
                        }
            except Exception as e:
                logger.warning(f"获取{game['name']}角色信息失败: {e}")
        return roles


async def do_game_sign(client: KuroClient, game_key: str, role_info: dict = None, user_id: str = "") -> str:
    """执行单个游戏签到"""
    game = GAMES[game_key]
    role_info = role_info or {}
    data = {
        "gameId": game["id"],
        "serverId": role_info.get("serverId", game["server_id"]),
        "roleId": role_info.get("roleId", ""),
        "reqMonth": datetime.now().strftime("%m"),
    }

    try:
        result = await client.post(ENDPOINTS["game_sign_in"], data)
        code = result.get("code", -1)
        msg = result.get("msg", result.get("message", "未知"))

        if code == ERR_SUCCESS:
            reward = await _get_sign_reward(client, game, role_info, user_id)
            reward_str = f"，奖励: {reward}" if reward else ""
            return f"✅ {game['name']}签到成功{reward_str}"
        elif code == ERR_ALREADY_SIGNED:
            return f"ℹ️ {game['name']}今天已签到"
        elif code == ERR_LOGIN_EXPIRED:
            return f"❌ {game['name']}登录已过期，请重新绑定token"
        elif code == ERR_USER_INFO_ERROR:
            return f"❌ {game['name']}用户信息异常"
        else:
            return f"❌ {game['name']}签到失败: {msg} (code:{code})"
    except Exception as e:
        return f"❌ {game['name']}签到异常: {e}"


async def _get_sign_reward(client: KuroClient, game: dict, role_info: dict = None, user_id: str = "") -> Optional[str]:
    """获取签到奖励信息"""
    try:
        role_info = role_info or {}
        data = {
            "gameId": game["id"],
            "serverId": role_info.get("serverId", game["server_id"]),
            "roleId": role_info.get("roleId", ""),
        }
        result = await client.post(ENDPOINTS["game_sign_record"], data)
        if result.get("code") == ERR_SUCCESS and result.get("data"):
            records = result["data"]
            if isinstance(records, list) and len(records) > 0:
                return records[0].get("goodsName")
    except Exception:
        pass
    return None


async def do_forum_sign(client: KuroClient) -> str:
    """论坛签到"""
    try:
        result = await client.post(ENDPOINTS["user_sign_in"], {"gameId": "2"})
        code = result.get("code", -1)
        if code == ERR_SUCCESS or result.get("success"):
            return "✅ 论坛签到成功"
        msg = result.get("msg", result.get("message", "未知"))
        return f"ℹ️ 论坛签到: {msg} (code:{code})"
    except Exception as e:
        return f"❌ 论坛签到异常: {e}"


async def do_forum_tasks(client: KuroClient) -> List[str]:
    """执行论坛每日任务：浏览帖子、点赞、分享"""
    results = []

    # 获取帖子列表
    try:
        post_data = {
            "forumId": "9",
            "gameId": "3",
            "pageIndex": "1",
            "pageSize": "20",
            "searchType": "3",
            "timeType": "0",
        }
        resp = await client.post(ENDPOINTS["forum_list"], post_data)
        posts = []
        if resp.get("success") and resp.get("data"):
            posts = resp["data"].get("postList", [])
    except Exception:
        posts = []

    if not posts:
        results.append("⚠️ 获取帖子列表失败，跳过互动任务")
        return results

    # 浏览 3 篇帖子
    view_count = 0
    for post in posts[:3]:
        try:
            await client.post(ENDPOINTS["post_detail"], {
                "isOnlyPublisher": "0",
                "postId": str(post["postId"]),
                "showOrderTyper": "2",
            })
            view_count += 1
        except Exception:
            pass
        await asyncio.sleep(1)
    results.append(f"📖 浏览帖子 {view_count}/3")

    # 点赞 5 篇
    like_count = 0
    for post in posts[:5]:
        try:
            like_data = {
                "forumId": 11,
                "gameId": 3,
                "likeType": 1,
                "operateType": 1,
                "postCommentId": "",
                "postCommentReplyId": "",
                "postId": str(post["postId"]),
                "postType": 1,
                "toUserId": str(post.get("userId", "")),
            }
            resp = await client.post(ENDPOINTS["forum_like"], like_data)
            if resp.get("success") or resp.get("code") == ERR_SUCCESS:
                like_count += 1
        except Exception:
            pass
        await asyncio.sleep(1)
    results.append(f"👍 点赞 {like_count}/5")

    # 分享
    try:
        resp = await client.post(ENDPOINTS["task_share"], {"gameId": 3})
        if resp.get("success") or resp.get("code") == ERR_SUCCESS:
            results.append("🔗 分享成功")
        else:
            results.append("🔗 分享失败")
    except Exception:
        results.append("🔗 分享异常")

    return results


async def do_full_sign(token: str, devcode: str = "", distinct_id: str = "", ip: str = "") -> str:
    """完整签到流程，含重试"""
    max_retries = 3

    for attempt in range(max_retries + 1):
        client = KuroClient(token, devcode, distinct_id, ip)
        try:
            lines = []

            # 1. 获取 userId 和 roleId
            user_id = await client.get_user_id() or ""
            role_ids = await client.get_role_ids()

            # 2. 游戏签到
            for game_key in ["wuwa", "pgr"]:
                game = GAMES[game_key]
                role_info = role_ids.get(game["id"], {})
                result = await do_game_sign(client, game_key, role_info, user_id)
                lines.append(result)
                await asyncio.sleep(1)

            # 3. 论坛签到
            lines.append(await do_forum_sign(client))
            await asyncio.sleep(1)

            # 4. 论坛任务
            task_results = await do_forum_tasks(client)
            lines.extend(task_results)

            # 5. 查询金币
            try:
                resp = await client.post(ENDPOINTS["gold_total"])
                if resp.get("success") and resp.get("data"):
                    gold = resp["data"].get("goldNum", 0)
                    lines.append(f"💰 当前金币: {gold}")
            except Exception:
                pass

            return "\n".join(lines)

        except Exception as e:
            if attempt < max_retries:
                delay = random.uniform(5, 15)
                logger.warning(f"签到异常: {e}，{delay:.1f}秒后重试 ({attempt+1}/{max_retries})")
                await asyncio.sleep(delay)
            else:
                return f"❌ 签到失败（重试{max_retries}次）: {e}"
        finally:
            await client.close()

    return "❌ 签到未知错误"


# ── AstrBot 插件入口 ──────────────────────────────────────

import os

DATA_DIR = "/root/astrbot/data/plugin_data/astrbot_plugin_kuro_sign"

@register("astrbot_plugin_kuro_sign", "Hermes", "库街区自动签到（鸣潮/战双+论坛任务）", "1.0.0")
class KuroSignPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        os.makedirs(DATA_DIR, exist_ok=True)

    def _get_user_file(self, user_id: str) -> str:
        return os.path.join(DATA_DIR, f"{user_id}.json")

    def _get_user_data(self, user_id: str) -> dict:
        """获取用户绑定数据"""
        path = self._get_user_file(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_user_data(self, user_id: str, data: dict):
        """保存用户绑定数据"""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(self._get_user_file(user_id), "w") as f:
            json.dump(data, f, ensure_ascii=False)

    @filter.command("库街区绑定")
    async def bind_token(self, event: AstrMessageEvent):
        """绑定库街区 token"""
        msg = event.message_str.strip()
        # 去掉命令前缀
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result(
                "使用方法: /库街区绑定 <token>\n"
                "token 获取方式: 登录库街区网页版，F12 找 Cookie 中的 user_token"
            )
            return

        token = parts[1].strip()
        if len(token) < 10:
            yield event.plain_result("❌ token 格式不正确，请检查")
            return

        user_id = event.get_sender_id()
        data = self._get_user_data(user_id)
        data["token"] = token
        data["bind_time"] = datetime.now().isoformat()
        self._save_user_data(user_id, data)

        yield event.plain_result("✅ 库街区 token 绑定成功！发送 /库街区签到 即可签到")

    @filter.command("库街区签到")
    async def sign_in(self, event: AstrMessageEvent):
        """执行库街区签到"""
        user_id = event.get_sender_id()
        data = self._get_user_data(user_id)
        token = data.get("token")

        if not token:
            yield event.plain_result(
                "❌ 请先绑定 token\n"
                "发送: /库街区绑定 <token>"
            )
            return

        yield event.plain_result("⏳ 正在签到，请稍候...")

        devcode = data.get("devcode", "")
        distinct_id = data.get("distinct_id", "")
        ip = data.get("ip", "")

        result = await do_full_sign(token, devcode, distinct_id, ip)

        # 如果自动生成了 devcode/distinct_id，保存下来保持一致
        if not devcode or not distinct_id:
            client = KuroClient(token)
            data["devcode"] = client.devcode
            data["distinct_id"] = client.distinct_id
            data["ip"] = client.ip
            self._save_user_data(user_id, data)

        yield event.plain_result(f"📋 库街区签到结果:\n{result}")

    @filter.command("库街区解绑")
    async def unbind(self, event: AstrMessageEvent):
        """解绑库街区 token"""
        user_id = event.get_sender_id()
        self._save_user_data(user_id, {})
        yield event.plain_result("✅ 已解绑库街区 token")

    @filter.command("库街区状态")
    async def status(self, event: AstrMessageEvent):
        """查看绑定状态"""
        user_id = event.get_sender_id()
        data = self._get_user_data(user_id)
        token = data.get("token")

        if not token:
            yield event.plain_result("❌ 未绑定库街区 token")
            return

        masked = token[:6] + "****" + token[-4:]
        bind_time = data.get("bind_time", "未知")
        yield event.plain_result(
            f"📊 库街区状态:\n"
            f"Token: {masked}\n"
            f"绑定时间: {bind_time}"
        )
