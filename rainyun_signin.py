#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Frame, Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright

REWARD_URL = "https://app.rainyun.com/account/reward/earn"
REWARD_URL_HASH = "https://app.rainyun.com/account/reward/earn#"
DASHBOARD_URL = "https://app.rainyun.com/dashboard"
LOGIN_API = "https://api.v2.rainyun.com/user/login"
TASKS_API = "https://api.v2.rainyun.com/user/reward/tasks"
VERIFY_API = "https://turing.captcha.qcloud.com/cap_union_new_verify"
QCAPTCHA_ORIGIN = "https://turing.captcha.qcloud.com"
GTIMG_ORIGIN = "https://turing.captcha.gtimg.com"
DEFAULT_TIMEOUT_MS = 30_000
BASE_DIR = Path(__file__).resolve().parent
TENVISION_MAIN = BASE_DIR / "TenVision" / "main.py"

SOLVER_JS = r"""
(() => {
  const API = {};

  async function loadImage(src) {
    return await new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });
  }

  function imageToData(img) {
    const canvas = document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    return ctx.getImageData(0, 0, canvas.width, canvas.height);
  }

  function binarize(imgData, mode = 'instruction') {
    const { data, width, height } = imgData;
    const bin = new Uint8Array(width * height);
    for (let i = 0; i < width * height; i++) {
      const r = data[i * 4];
      const g = data[i * 4 + 1];
      const b = data[i * 4 + 2];
      const a = data[i * 4 + 3];
      const lum = 0.299 * r + 0.587 * g + 0.114 * b;
      let v = 0;
      if (mode === 'instruction') {
        v = a > 20 && lum < 190 ? 1 : 0;
      } else if (mode === 'strictDark') {
        v = a > 20 && lum < 70 && r < 110 && g < 110 && b < 110 ? 1 : 0;
      } else if (mode === 'dark') {
        v = a > 20 && lum < 95 ? 1 : 0;
      } else if (mode === 'looseDark') {
        v = a > 20 && lum < 120 ? 1 : 0;
      }
      bin[i] = v;
    }
    return { bin, width, height };
  }

  function components(src, { minArea = 20, maxArea = 1e9, maxW = 1e9, maxH = 1e9 } = {}) {
    const { bin, width, height } = src;
    const seen = new Uint8Array(width * height);
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    const out = [];
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const idx = y * width + x;
        if (!bin[idx] || seen[idx]) continue;
        const q = [[x, y]];
        let qi = 0;
        seen[idx] = 1;
        let minX = x, maxX = x, minY = y, maxY = y, area = 0;
        while (qi < q.length) {
          const [cx, cy] = q[qi++];
          area++;
          if (cx < minX) minX = cx;
          if (cx > maxX) maxX = cx;
          if (cy < minY) minY = cy;
          if (cy > maxY) maxY = cy;
          for (const [dx, dy] of dirs) {
            const nx = cx + dx;
            const ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
            const ni = ny * width + nx;
            if (bin[ni] && !seen[ni]) {
              seen[ni] = 1;
              q.push([nx, ny]);
            }
          }
        }
        const w = maxX - minX + 1;
        const h = maxY - minY + 1;
        if (area >= minArea && area <= maxArea && w <= maxW && h <= maxH) {
          out.push({ x: minX, y: minY, w, h, area });
        }
      }
    }
    return out.sort((a, b) => a.x - b.x || a.y - b.y);
  }

  function holes(src, box) {
    const { bin, width } = src;
    const { x: x0, y: y0, w, h } = box;
    const seen = new Uint8Array(w * h);
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    let holesCount = 0;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const localIdx = y * w + x;
        const globalIdx = (y0 + y) * width + (x0 + x);
        if (bin[globalIdx] || seen[localIdx]) continue;
        const q = [[x, y]];
        let qi = 0;
        seen[localIdx] = 1;
        let touchesBorder = x === 0 || y === 0 || x === w - 1 || y === h - 1;
        while (qi < q.length) {
          const [cx, cy] = q[qi++];
          for (const [dx, dy] of dirs) {
            const nx = cx + dx;
            const ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
            const nLocal = ny * w + nx;
            const nGlobal = (y0 + ny) * width + (x0 + nx);
            if (bin[nGlobal] || seen[nLocal]) continue;
            seen[nLocal] = 1;
            if (nx === 0 || ny === 0 || nx === w - 1 || ny === h - 1) touchesBorder = true;
            q.push([nx, ny]);
          }
        }
        if (!touchesBorder) holesCount++;
      }
    }
    return holesCount;
  }

  function feature(src, box) {
    return {
      holes: holes(src, box),
      aspect: box.w / box.h,
      fill: box.area / (box.w * box.h),
    };
  }

  function cropMask(src, box, size = 32, pad = 1) {
    const { bin, width, height } = src;
    const x0 = Math.max(0, box.x - pad);
    const y0 = Math.max(0, box.y - pad);
    const x1 = Math.min(width, box.x + box.w + pad);
    const y1 = Math.min(height, box.y + box.h + pad);
    const w = x1 - x0;
    const h = y1 - y0;
    const arr = new Uint8Array(size * size);
    for (let yy = 0; yy < size; yy++) {
      for (let xx = 0; xx < size; xx++) {
        const sx = Math.min(width - 1, Math.max(0, Math.floor(x0 + ((xx + 0.5) / size) * w)));
        const sy = Math.min(height - 1, Math.max(0, Math.floor(y0 + ((yy + 0.5) / size) * h)));
        arr[yy * size + xx] = bin[sy * width + sx];
      }
    }
    return arr;
  }

  function iou(a, b) {
    let inter = 0;
    let uni = 0;
    for (let i = 0; i < a.length; i++) {
      const av = a[i];
      const bv = b[i];
      if (av && bv) inter++;
      if (av || bv) uni++;
    }
    return uni ? inter / uni : 0;
  }

  function featureScore(insFeat, bgFeat) {
    let score = 0;
    score += 1 - Math.min(1, Math.abs(insFeat.holes - bgFeat.holes) / 6);
    score += 1 - Math.min(1, Math.abs(insFeat.aspect - bgFeat.aspect) / 2);
    score += 1 - Math.min(1, Math.abs(insFeat.fill - bgFeat.fill) / 0.8);
    return score / 3;
  }

  function projection(mask, size = 32) {
    const rows = [];
    const cols = [];
    for (let y = 0; y < size; y++) {
      let sum = 0;
      for (let x = 0; x < size; x++) sum += mask[y * size + x];
      rows.push(sum / size);
    }
    for (let x = 0; x < size; x++) {
      let sum = 0;
      for (let y = 0; y < size; y++) sum += mask[y * size + x];
      cols.push(sum / size);
    }
    return { rows, cols };
  }

  function projectionScore(a, b) {
    let diff = 0;
    for (let i = 0; i < a.rows.length; i++) {
      diff += Math.abs(a.rows[i] - b.rows[i]);
      diff += Math.abs(a.cols[i] - b.cols[i]);
    }
    return 1 - diff / (a.rows.length * 2);
  }

  function candidateScore(insItem, bgBin, bgBox) {
    const minWidth = Math.max(insItem.box.w * 1.05, insItem.box.w + 2);
    const minHeight = Math.max(insItem.box.h * 1.05, insItem.box.h + 2);
    if (bgBox.w < minWidth || bgBox.h < minHeight) return -1e9;
    const mask = cropMask(bgBin, bgBox);
    const scaleBonus = Math.min(bgBox.w / insItem.box.w, bgBox.h / insItem.box.h);
    return (
      projectionScore(insItem.proj, projection(mask)) * 0.58 +
      iou(insItem.mask, mask) * 0.22 +
      featureScore(insItem.feat, feature(bgBin, bgBox)) * 0.15 +
      Math.min(scaleBonus, 3) / 3 * 0.05
    );
  }

  API.solveByUrls = async function solveByUrls(instUrl, bgUrl) {
    const [instImg, bgImg] = await Promise.all([loadImage(instUrl), loadImage(bgUrl)]);
    const instData = imageToData(instImg);
    const bgData = imageToData(bgImg);

    const insBin = binarize(instData, 'instruction');
    const insComps = components(insBin, { minArea: 40, maxW: 80, maxH: 80 })
      .filter((c) => c.w > 8 && c.h > 8)
      .slice(0, 3);

    if (insComps.length !== 3) {
      throw new Error(`instruction component count mismatch: ${insComps.length}`);
    }

    const insItems = insComps.map((box) => {
      const mask = cropMask(insBin, box);
      return { box, mask, feat: feature(insBin, box), proj: projection(mask) };
    });

    let best = null;
    for (const mode of ['strictDark', 'dark', 'looseDark']) {
      const bgBin = binarize(bgData, mode);
      let cands = components(bgBin, { minArea: 100, maxArea: 12000, maxW: 140, maxH: 140 })
        .filter((c) => c.w > 20 && c.h > 20)
        .filter((c) => c.area / (c.w * c.h) < 0.72);

      if (cands.length < 3) continue;

      let modeBest = null;
      for (let a = 0; a < cands.length; a++) {
        for (let b = 0; b < cands.length; b++) {
          if (b === a) continue;
          for (let c = 0; c < cands.length; c++) {
            if (c === a || c === b) continue;
            const combo = [cands[a], cands[b], cands[c]];
            let score = 0;
            for (let i = 0; i < 3; i++) {
              score += candidateScore(insItems[i], bgBin, combo[i]);
            }
            if (!modeBest || score > modeBest.score) {
              modeBest = { score, combo };
            }
          }
        }
      }

      if (modeBest && (!best || modeBest.score > best.score)) {
        best = { mode, score: modeBest.score, combo: modeBest.combo };
      }
    }

    if (!best) {
      throw new Error('no candidate combination matched');
    }

    return {
      mode: best.mode,
      score: best.score,
      points: best.combo.map((box) => ({
        x: Math.round(box.x + box.w / 2),
        y: Math.round(box.y + box.h / 2),
        box,
      })),
    };
  };

  window.__rainyunSolver = API;
})();
"""


@dataclass
class Credentials:
    username: str
    password: str


class SignInError(RuntimeError):
    pass


def read_credentials(env_path: Path) -> Credentials:
    data: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            continue
        data[key.strip()] = value.strip()
    username = data.get("username") or data.get("field")
    password = data.get("password")
    if not username or not password:
        raise SignInError(f"未在 {env_path} 中读取到 username/password")
    return Credentials(username=username, password=password)


def parse_jsonp(payload: str) -> dict[str, Any]:
    match = re.search(r"^[^(]+\((.*)\)\s*$", payload, re.S)
    if not match:
        raise SignInError("prehandle 返回不是 JSONP")
    return json.loads(match.group(1))


def solve_pow(prefix: str, md5_hex: str, limit: int = 2_000_000) -> tuple[str, int]:
    start = time.perf_counter()
    for i in range(limit):
        candidate = f"{prefix}{i}"
        if hashlib.md5(candidate.encode()).hexdigest() == md5_hex:
            elapsed = int((time.perf_counter() - start) * 1000)
            return candidate, max(elapsed, 1)
    raise SignInError("pow 未命中，超过搜索上限")


def wait_for_captcha_frame(page: Page, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Frame:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for frame in page.frames:
            if "drag_ele.html" in frame.url:
                return frame
        page.wait_for_timeout(200)
    raise SignInError("未等到腾讯验证码 iframe")


def install_solver(frame: Frame) -> None:
    frame.evaluate(SOLVER_JS)


def build_data_url(path: Path) -> str:
    mime = "image/jpeg"
    if path.suffix.lower() == ".png":
        mime = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{encoded}"


def solve_points(frame: Frame, inst_url: str, bg_url: str) -> dict[str, Any]:
    install_solver(frame)
    result = frame.evaluate(
        "({instUrl, bgUrl}) => window.__rainyunSolver.solveByUrls(instUrl, bgUrl)",
        {"instUrl": inst_url, "bgUrl": bg_url},
    )
    if not result or len(result.get("points", [])) != 3:
        raise SignInError("验证码识别结果异常")
    return result


def wait_for_captcha_assets(frame: Frame) -> None:
    frame.wait_for_function(
        """
        () => {
          const wrap = document.querySelector('#tcWrap');
          const bg = document.querySelector('#slideBg');
          const inst = document.querySelector('.tc-instruction-icon img');
          if (!wrap || !bg || !inst) return false;
          const bgStyle = getComputedStyle(bg).backgroundImage;
          const instSrc = inst.getAttribute('src') || '';
          return wrap.clientWidth > 0 && wrap.clientHeight > 0 && bg.clientWidth > 0 && bg.clientHeight > 0 && bgStyle !== 'none' && instSrc.length > 0;
        }
        """,
        timeout=DEFAULT_TIMEOUT_MS,
    )
    frame.page.wait_for_timeout(800)


def parse_tenvision_points(stdout: str) -> list[tuple[int, int]]:
    match = re.search(r"点击顺序坐标:\s*(\[[^\n]+\])", stdout)
    if not match:
        raise SignInError(f"TenVision 输出中没有点击坐标: {stdout}")
    raw_points = ast.literal_eval(match.group(1))
    if not isinstance(raw_points, list) or len(raw_points) != 3:
        raise SignInError(f"TenVision 点击坐标数量异常: {raw_points}")
    points: list[tuple[int, int]] = []
    for item in raw_points:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise SignInError(f"TenVision 点击坐标格式异常: {raw_points}")
        points.append((int(item[0]), int(item[1])))
    return points


def run_tenvision_solver(captcha_path: Path, output_path: Path) -> dict[str, Any]:
    if not TENVISION_MAIN.exists():
        raise SignInError(f"未找到 TenVision 入口文件: {TENVISION_MAIN}")
    proc = subprocess.run(
        [sys.executable, str(TENVISION_MAIN), str(captcha_path), str(output_path)],
        cwd=str(TENVISION_MAIN.parent),
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit={proc.returncode}"
        raise SignInError(f"TenVision 识别失败: {detail}")
    return {
        "points": parse_tenvision_points(stdout),
        "stdout": stdout,
        "stderr": stderr,
    }


def solve_points_with_tenvision(frame: Frame, bg_size: list[int]) -> dict[str, Any]:
    wait_for_captcha_assets(frame)
    wrap = frame.locator("#tcWrap")
    bg = frame.locator("#slideBg")
    wrap_box = wrap.bounding_box()
    bg_box = bg.bounding_box()
    if not wrap_box or not bg_box:
        raise SignInError("未找到验证码截图区域")

    with tempfile.TemporaryDirectory(prefix="rainyun-tenvision-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        captcha_path = tmpdir_path / "captcha.png"
        output_path = tmpdir_path / "captcha_out.png"
        wrap.screenshot(path=str(captcha_path))
        solver = run_tenvision_solver(captcha_path, output_path)

    natural_w, natural_h = bg_size
    bg_offset_x = bg_box["x"] - wrap_box["x"]
    bg_offset_y = bg_box["y"] - wrap_box["y"]
    points: list[dict[str, Any]] = []
    for screen_x, screen_y in solver["points"]:
        bg_x = screen_x - bg_offset_x
        bg_y = screen_y - bg_offset_y
        if bg_x < 0 or bg_y < 0 or bg_x > bg_box["width"] or bg_y > bg_box["height"]:
            raise SignInError(
                f"TenVision 返回坐标不在主图内: {(screen_x, screen_y)} / bg_offset=({bg_offset_x:.2f}, {bg_offset_y:.2f})"
            )
        points.append(
            {
                "x": round(bg_x / bg_box["width"] * natural_w),
                "y": round(bg_y / bg_box["height"] * natural_h),
                "screen_x": round(screen_x),
                "screen_y": round(screen_y),
            }
        )
    return {
        "mode": "tenvision",
        "points": points,
        "stdout": solver["stdout"],
    }


def login_via_protocol(page: Page, creds: Credentials) -> None:
    page.goto(REWARD_URL, wait_until="load", timeout=DEFAULT_TIMEOUT_MS)
    page.evaluate(
        """
        async ({field, password, loginApi}) => {
          const resp = await fetch(loginApi, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'content-type': 'application/json',
              'origin': 'https://app.rainyun.com',
              'referer': 'https://app.rainyun.com/'
            },
            body: JSON.stringify({field, password})
          });
          return await resp.json();
        }
        """,
        {"field": creds.username, "password": creds.password, "loginApi": LOGIN_API},
    )
    page.goto(DASHBOARD_URL, wait_until="load", timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    page.goto(REWARD_URL_HASH, wait_until="load", timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(5000)
    if "auth/login" in page.url:
        raise SignInError("登录后仍停留在登录页")


def auth_fetch(page: Page, url: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    return page.evaluate(
        """
        async ({url, method, body}) => {
          const match = document.cookie.match(/(?:^|; )X-CSRF-Token=([^;]+)/);
          const csrf = match ? decodeURIComponent(match[1]) : '';
          const headers = { 'x-csrf-token': csrf };
          if (body !== null) headers['content-type'] = 'application/json';
          const resp = await fetch(url, {
            method,
            credentials: 'include',
            headers,
            body: body === null ? undefined : JSON.stringify(body)
          });
          const text = await resp.text();
          try {
            return JSON.parse(text);
          } catch (err) {
            return { status: resp.status, text };
          }
        }
        """,
        {"url": url, "method": method, "body": body},
    )


def get_daily_task(page: Page) -> dict[str, Any]:
    tasks = auth_fetch(page, TASKS_API, "GET")
    if tasks.get("code") != 200:
        raise SignInError(f"读取任务列表失败: {tasks}")
    for item in tasks.get("data", []):
        if item.get("Name") == "每日签到":
            return item
    raise SignInError("任务列表中没有“每日签到”")


def trigger_daily_signin(page: Page) -> str:
    try:
        page.get_by_role("tab", name=re.compile(r"每日签到")).get_by_role("link", name="领取奖励").click(timeout=5_000)
        return "dom_click"
    except Exception:
        open_captcha(page)
        return "js_fallback"


def open_captcha(page: Page) -> None:
    opened = page.evaluate(
        """
        () => {
          if (!window.TencentCaptcha) return { ok: false, reason: 'TencentCaptcha 未加载' };
          window.__rainyunCapCb = [];
          window.__rainyunCap = new window.TencentCaptcha(
            '2039519451',
            (res) => { window.__rainyunCapCb.push(res); },
            {}
          );
          window.__rainyunCap.show();
          return { ok: true };
        }
        """
    )
    if not opened.get("ok"):
        raise SignInError(f"打开验证码失败: {opened}")


def maybe_capture_prehandle(holder: dict[str, Any]):
    def handler(resp: Response) -> None:
        try:
            if "cap_union_prehandle" not in resp.url:
                return
            holder["prehandle"] = parse_jsonp(resp.text())
        except Exception:
            pass

    return handler


def build_verify_payload(frame: Frame, sess: str, ans: list[dict[str, Any]], pow_answer: str | None, pow_calc_time: int | None) -> dict[str, Any]:
    data = frame.evaluate(
        """
        ({sess, ans, powAnswer, powCalcTime}) => {
          const rawCollect = window.TDC && typeof window.TDC.getData === 'function' ? (window.TDC.getData(true) || '---') : '---';
          let collect = rawCollect;
          try {
            collect = decodeURIComponent(rawCollect);
          } catch (err) {}
          const info = window.TDC && typeof window.TDC.getInfo === 'function' ? (window.TDC.getInfo() || {}) : {};
          const payload = {
            collect,
            tlg: collect.length,
            eks: info.info || '',
            sess,
            ans: JSON.stringify(ans)
          };
          const order = ['collect', 'tlg', 'eks', 'sess', 'ans'];
          if (powAnswer) {
            payload.pow_answer = powAnswer;
            payload.pow_calc_time = powCalcTime;
            order.push('pow_answer', 'pow_calc_time');
          }
          if (typeof window.getVData === 'function') {
            const vData = window.getVData(order.map((key) => `${key}=${payload[key]}`).join('&'));
            if (vData) payload.vData = vData;
          }
          return payload;
        }
        """,
        {
            "sess": sess,
            "ans": ans,
            "powAnswer": pow_answer,
            "powCalcTime": pow_calc_time,
        },
    )
    return data


def post_verify(context: BrowserContext, payload: dict[str, Any]) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload)
    resp = context.request.post(
        VERIFY_API,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": GTIMG_ORIGIN,
            "Referer": f"{GTIMG_ORIGIN}/",
        },
    )
    return resp.json()


def click_points(frame: Frame, points: list[dict[str, Any]], bg_size: list[int] | None = None) -> None:
    if points and "screen_x" in points[0] and "screen_y" in points[0]:
        wrap = frame.locator("#tcWrap")
        box = wrap.bounding_box()
        if not box:
            raise SignInError("未找到 #tcWrap")
        for point in points:
            x = max(2, min(box["width"] - 2, point["screen_x"]))
            y = max(2, min(box["height"] - 2, point["screen_y"]))
            wrap.click(position={"x": x, "y": y})
            frame.page.wait_for_timeout(250)
        return

    bg = frame.locator("#slideBg")
    box = bg.bounding_box()
    if not box or bg_size is None:
        raise SignInError("未找到 #slideBg")
    natural_w, natural_h = bg_size
    for point in points:
        x = max(2, min(box["width"] - 2, point["x"] / natural_w * box["width"]))
        y = max(2, min(box["height"] - 2, point["y"] / natural_h * box["height"]))
        bg.click(position={"x": x, "y": y})
        frame.page.wait_for_timeout(250)


def perform_signin(page: Page) -> dict[str, Any]:
    daily = get_daily_task(page)
    if daily.get("Status") in (2, "2"):
        return {"status": "already_done", "task": daily}
    if daily.get("Status") not in (1, "1"):
        raise SignInError(f"每日签到当前不是可领取状态: {daily}")

    with page.expect_response(lambda resp: "cap_union_prehandle" in resp.url, timeout=15_000) as prehandle_resp:
        trigger = trigger_daily_signin(page)
    frame = wait_for_captcha_frame(page)
    prehandle = parse_jsonp(prehandle_resp.value.text())

    captcha_data = prehandle["data"]
    show_info = captcha_data["dyn_show_info"]
    comm_cfg = captcha_data["comm_captcha_cfg"]
    bg_size = show_info["bg_elem_cfg"]["size_2d"]

    solved = solve_points_with_tenvision(frame, bg_size)
    points = solved["points"]
    click_points(frame, points)
    frame.page.wait_for_timeout(500)

    ans = [
        {
            "elem_id": index + 1,
            "type": "DynAnswerType_POS",
            "data": f"{point['x']},{point['y']}",
        }
        for index, point in enumerate(points)
    ]

    pow_cfg = comm_cfg.get("pow_cfg") or {}
    pow_answer = None
    pow_calc_time = None
    if pow_cfg.get("prefix") and pow_cfg.get("md5"):
        pow_answer, pow_calc_time = solve_pow(pow_cfg["prefix"], pow_cfg["md5"])

    verify_payload = build_verify_payload(frame, prehandle["sess"], ans, pow_answer, pow_calc_time)
    verify_result = post_verify(page.context, verify_payload)
    if verify_result.get("errorCode") != "0":
        raise SignInError(f"验证码校验失败: {verify_result}")

    sign_result = auth_fetch(
        page,
        TASKS_API,
        "POST",
        {
            "task_name": "每日签到",
            "verifyCode": "",
            "vticket": verify_result["ticket"],
            "vrandstr": verify_result["randstr"],
        },
    )
    if sign_result.get("code") != 200:
        raise SignInError(f"签到接口失败: {sign_result}")

    page.goto(REWARD_URL_HASH, wait_until="load", timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    after = get_daily_task(page)
    return {
        "status": "signed",
        "task_before": daily,
        "task_after": after,
        "trigger": trigger,
        "solver": {"mode": solved.get("mode"), "score": solved.get("score"), "points": points},
        "verify": {"randstr": verify_result.get("randstr")},
        "sign": sign_result,
    }


def run_sample_mode(captcha_path: Path, output_path: Path) -> int:
    result = run_tenvision_solver(captcha_path, output_path)
    print(
        json.dumps(
            {
                "input": str(captcha_path),
                "output": str(output_path),
                "points": [{"screen_x": x, "screen_y": y} for x, y in result["points"]],
                "stdout": result["stdout"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def run_signin_mode(env_path: Path, headless: bool) -> int:
    creds = read_credentials(env_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            login_via_protocol(page, creds)
            result = perform_signin(page)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rainyun 每日签到自动化")
    parser.add_argument("--env", default=".env", help="账号文件路径")
    parser.add_argument("--headful", action="store_true", help="以有界面模式运行")
    parser.add_argument("--sample", metavar="CAPTCHA", help="离线测试完整验证码截图")
    args = parser.parse_args()

    headless = not args.headful
    try:
        if args.sample:
            captcha_path = Path(args.sample).resolve()
            output_path = captcha_path.with_name(f"{captcha_path.stem}_tenvision{captcha_path.suffix or '.png'}")
            return run_sample_mode(captcha_path, output_path)
        return run_signin_mode(Path(args.env).resolve(), headless)
    except SignInError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except PlaywrightTimeoutError as exc:
        print(f"页面等待超时: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
