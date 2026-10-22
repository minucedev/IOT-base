"""Bốn nhóm lệnh từ model MediaPipe có sẵn; không huấn luyện thêm."""

import math

# Hai nhãn ngón cái của model cùng thuộc một nhóm điều khiển.
MODEL_TO_GESTURE = {
    "Open_Palm": "Open_Palm",
    "Closed_Fist": "Closed_Fist",
    "Pointing_Up": "Pointing_Up",
    "Thumb_Up": "Thumb",
    "Thumb_Down": "Thumb",
    # Mọi cử chỉ còn lại model nhận ra đều là lệnh tắt hết.
    "Victory": "Closed_Fist",
    "ILoveYou": "Closed_Fist",
}
GESTURE_NAMES = {
    "Open_Palm": "Xòe bàn tay (mở khóa)",
    "Closed_Fist": "Tắt hết",
    "Pointing_Up": "Ngón trỏ (bật đèn)",
    "Thumb": "Ngón cái (tắt quạt)",
}


def choose_gesture(recognition, threshold):
    """Chỉ dùng nhãn cao nhất, rồi mới kiểm tra có thuộc nhóm cho phép không.

    Không chọn nhãn hạng hai khi nhãn cao nhất là Victory/ILoveYou/None.
    Trả về (có tay, nhãn model, điểm, nhóm lệnh hoặc None).
    """
    has_hand = bool(recognition.hand_landmarks)
    if not has_hand or not recognition.gestures or not recognition.gestures[0]:
        return has_hand, "", 0.0, None
    top = max(recognition.gestures[0], key=lambda category: category.score)
    label = top.category_name or ""
    score = float(top.score)
    accepted = MODEL_TO_GESTURE.get(label)
    if not math.isfinite(score) or score < threshold:
        accepted = None
        if not math.isfinite(score):
            score = 0.0
    return has_hand, label, score, accepted


class StableGesture:
    """Yêu cầu cùng nhóm cử chỉ liên tục một khoảng thời gian trước khi ra lệnh."""

    def __init__(self, hold_seconds=0.4):
        self.hold_seconds = hold_seconds
        self.candidate = None
        self.since = 0.0
        self.last_time = None

    def update(self, gesture, now):
        gap = self.last_time is not None and now - self.last_time > 1.5
        self.last_time = now
        if gesture is None or gesture != self.candidate or gap:
            self.candidate = gesture
            self.since = now
        if gesture is not None and now - self.since >= self.hold_seconds:
            return gesture
        return None
