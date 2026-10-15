"""Vẽ overlay lên frame + giao diện HTML/CSS cho web stream."""
from __future__ import annotations

from typing import List

import cv2
import numpy as np

import config
from alert import AlertState
from detector import SKELETON, Person, PostureResult

# cv2.putText không hỗ trợ tiếng Việt có dấu -> overlay dùng nhãn tiếng Anh
OVERLAY_LABELS = {
    config.STATUS_GOOD: "GOOD POSTURE",
    config.STATUS_SLOUCH: "SLOUCHING!",
    config.STATUS_LEAN: "LEANING!",
    config.STATUS_HEAD_DOWN: "HEAD DOWN!",
    config.STATUS_NO_PERSON: "NO PERSON",
    config.STATUS_UNKNOWN: "KEYPOINTS NOT VISIBLE",
}
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _pt(p) -> tuple:
    return int(p[0]), int(p[1])


def draw_overlay(frame: np.ndarray, persons: List[Person], posture: PostureResult,
                 alert: AlertState, fps: float) -> np.ndarray:
    """Vẽ trực tiếp lên `frame` (được sở hữu bởi inference thread) và trả về."""
    h, w = frame.shape[:2]
    color = alert.color

    if persons:
        person = persons[0]
        kp = person.keypoints
        x1, y1, x2, y2 = person.box
        cv2.rectangle(frame, _pt((x1, y1)), _pt((x2, y2)), color, 1)
        for a, b in SKELETON:
            if kp[a, 2] >= config.KPT_CONF_THRESHOLD and kp[b, 2] >= config.KPT_CONF_THRESHOLD:
                cv2.line(frame, _pt(kp[a]), _pt(kp[b]), color, 2, cv2.LINE_AA)
        for i in range(17):
            if kp[i, 2] >= config.KPT_CONF_THRESHOLD:
                cv2.circle(frame, _pt(kp[i]), 4, (0, 255, 255), -1, cv2.LINE_AA)

        lm = posture.landmarks
        if lm:
            ear, sho, hip = lm["ear"], lm["shoulder"], lm["hip"]
            cv2.line(frame, _pt(ear), _pt(sho), (255, 200, 0), 3, cv2.LINE_AA)
            cv2.line(frame, _pt(sho), _pt(hip), (255, 200, 0), 3, cv2.LINE_AA)
            tx, ty = int(sho[0]) + 10, int(sho[1])
            for text in (f"E-S-H {posture.esh_angle:.0f} deg",
                         f"Neck {posture.neck_angle:.0f} deg",
                         f"Trunk {posture.trunk_angle:.0f} deg"):
                cv2.putText(frame, text, (min(tx, w - 170), max(ty, 15)), FONT, 0.5,
                            (255, 255, 255), 1, cv2.LINE_AA)
                ty += 18

    # Banner trạng thái
    label = OVERLAY_LABELS.get(posture.status, posture.status)
    if alert.is_alert:
        label += f" ({alert.bad_seconds:.0f}s)"
    cv2.rectangle(frame, (0, 0), (w, 36), color, -1)
    cv2.putText(frame, label, (10, 26), FONT, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, f"FPS {fps:.1f}", (10, h - 10), FONT, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if alert.is_alert:  # viền đỏ cảnh báo
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, 6)
    return frame


INDEX_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Posture Monitor</title>
<style>
  :root { --bg:#0f172a; --card:#1e293b; --text:#e2e8f0; --muted:#94a3b8;
          --good:#22c55e; --bad:#ef4444; --neutral:#64748b; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, sans-serif; background:var(--bg); color:var(--text); }
  header { padding:14px 20px; font-size:1.2rem; font-weight:600; }
  main { display:grid; grid-template-columns: minmax(0,2fr) minmax(260px,1fr); gap:16px;
         padding:0 20px 20px; max-width:1200px; margin:auto; }
  @media (max-width:800px) { main { grid-template-columns: 1fr; } }
  .card { background:var(--card); border-radius:12px; padding:14px; }
  .video img { width:100%; border-radius:8px; display:block; background:#000; }
  #badge { font-size:1.4rem; font-weight:700; padding:12px; border-radius:8px; text-align:center;
           background:var(--neutral); transition: background .2s; }
  #badge.good { background:var(--good); } #badge.bad { background:var(--bad); }
  table { width:100%; margin-top:12px; border-collapse:collapse; }
  td { padding:6px 0; border-bottom:1px solid #334155; } td:last-child { text-align:right; }
  .led { display:inline-block; width:14px; height:14px; border-radius:50%; background:#334155;
         margin-left:6px; vertical-align:middle; }
  .led.on { background:var(--bad); box-shadow:0 0 8px var(--bad); }
  .led.GOOD.on { background:var(--good); box-shadow:0 0 8px var(--good); }
  .muted { color:var(--muted); font-size:.85rem; margin-top:10px; }
</style>
</head>
<body>
<header>🪑 Posture Monitor</header>
<main>
  <section class="card video"><img src="/video_feed" alt="Video stream" decoding="async"></section>
  <section class="card">
    <div id="badge">Đang kết nối...</div>
    <table>
      <tr><td>Góc Tai-Vai-Hông</td><td id="esh">–</td></tr>
      <tr><td>Góc cổ (so với phương thẳng)</td><td id="neck">–</td></tr>
      <tr><td>Góc thân (so với phương thẳng)</td><td id="trunk">–</td></tr>
      <tr><td>Thời gian sai tư thế</td><td id="bad">–</td></tr>
      <tr><td>FPS / Suy luận</td><td id="fps">–</td></tr>
      <tr><td>LED Tốt / Gù / Nghiêng / Cúi</td><td><span class="led GOOD" id="led-GOOD"></span><span class="led" id="led-SLOUCH"></span><span class="led" id="led-LEAN"></span><span class="led" id="led-HEAD_DOWN"></span></td></tr>
    </table>
    <div class="muted">Cập nhật mỗi 500 ms từ /api/status</div>
  </section>
</main>
<script>
const LABELS = { GOOD:"Tư thế tốt", SLOUCH:"Ngồi gù!", LEAN:"Đang nghiêng!", HEAD_DOWN:"Cúi đầu!",
                 NO_PERSON:"Không thấy người", UNKNOWN:"Không thấy rõ tai/vai/hông" };
const f = (v, u="°") => (v === null || v === undefined) ? "–" : v.toFixed(0) + u;
async function tick() {
  try {
    const s = await (await fetch("/api/status", {cache:"no-store"})).json();
    const b = document.getElementById("badge");
    b.textContent = LABELS[s.status] || s.status;
    b.className = s.alert ? "bad" : (s.status === "GOOD" ? "good" : "");
    document.getElementById("esh").textContent = f(s.esh_angle);
    document.getElementById("neck").textContent = f(s.neck_angle);
    document.getElementById("trunk").textContent = f(s.trunk_angle);
    document.getElementById("bad").textContent = f(s.bad_seconds, " s");
    document.getElementById("fps").textContent = s.fps.toFixed(1) + " / " + s.inference_ms.toFixed(0) + " ms";
    for (const k of ["GOOD", "SLOUCH", "LEAN", "HEAD_DOWN"])
      document.getElementById("led-" + k).classList.toggle("on", !!s.led[k]);
  } catch (e) { document.getElementById("badge").textContent = "Mất kết nối"; }
}
setInterval(tick, 500); tick();
</script>
</body>
</html>
"""
