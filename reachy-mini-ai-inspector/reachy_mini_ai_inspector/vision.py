"""OpenCV features + an actually fitted/invoked One-Class SVM (not RGB-only)."""
import hashlib
import json
import time

import cv2
import numpy as np
from sklearn.svm import OneClassSVM

MIN_REFERENCES = 8


def extract(image, settings):
    h, w = image.shape[:2]
    r = settings.roi
    crop = image[int(r.y*h):int((r.y+r.height)*h), int(r.x*w):int((r.x+r.width)*w)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 65, 35), (179, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    significant = [c for c in contours if cv2.contourArea(c) > crop.shape[0]*crop.shape[1]*.012]
    issues = []
    if len(significant) != 1:
        return None, {}, ["対象を1個だけ検査範囲に入れてください。白や灰色の無地の台を使ってください"]
    contour = significant[0]
    x, y, bw, bh = cv2.boundingRect(contour)
    area = cv2.contourArea(contour)
    occupancy = area / (crop.shape[0]*crop.shape[1])
    if occupancy < .035 or occupancy > .75:
        issues.append("対象の大きさが不適切です")
    if min(x, y) < 3 or x+bw >= crop.shape[1]-3 or y+bh >= crop.shape[0]-3:
        issues.append("対象が検査枠からはみ出しています")
    object_mask = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(object_mask, [contour], -1, 255, -1)
    pixels = hsv[object_mask > 0]
    # A smoothed circular hue histogram is robust to hue wrapping at red.
    hist = cv2.calcHist([hsv], [0], object_mask, [18], [0, 180]).ravel()
    hist = (hist + np.roll(hist, 1)*.25 + np.roll(hist, -1)*.25)
    hist /= max(hist.sum(), 1)
    (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
    aspect = max(rw, rh) / max(min(rw, rh), 1)
    fill = area / max(rw*rh, 1)
    gray = cv2.cvtColor(crop[y:y+bh, x:x+bw], cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharpness < 12:
        issues.append("ピントや手ぶれを確認してください")
    if float(np.median(pixels[:, 2])) < 65:
        issues.append("照明が暗すぎます")
    vector = np.r_[hist*3, np.log(aspect)*1.5, np.log(max(occupancy, .001))*.5,
                   fill, np.mean(pixels[:, 1])/255, np.mean(pixels[:, 2])/255]
    measurements = {"hue_hist": hist.tolist(), "aspect": aspect, "occupancy": occupancy,
                    "sharpness": sharpness, "bbox": [x+int(r.x*w), y+int(r.y*h), bw, bh]}
    return vector, measurements, issues


class AnomalyModel:
    def __init__(self, references, profile):
        self.references = references
        self.model_id = hashlib.sha256(json.dumps({"profile": profile, "refs": references, "algorithm": "ocsvm-rbf-gamma1.2-nu0.08-v1"}, sort_keys=True).encode()).hexdigest()[:16]
        self.model = None
        if len(references) >= MIN_REFERENCES:
            x = np.array([r["features"] for r in references])
            # Fixed feature units avoid zero-variance StandardScaler exploding in tiny datasets.
            self.model = OneClassSVM(kernel="rbf", gamma=1.2, nu=.08).fit(x)
            scores = self.model.score_samples(x)
            self.baseline = max(float(np.median(scores)), 1e-6)
            self.center = np.median(x, axis=0)

    def predict(self, image, settings):
        started = time.perf_counter()
        features, measures, issues = extract(image, settings)
        base = {"model_id": self.model_id, "ai_executed": False, "ai_score": None,
                "svm_decision": None, "measurements": measures, "reasons": issues}
        if self.model is None:
            issues.append(f"異なる正解画像を{MIN_REFERENCES}枚以上登録してください")
        if features is None or self.model is None:
            return {**base, "verdict": "REVIEW", "inference_ms": 0.0}
        raw = float(self.model.score_samples([features])[0])
        decision = float(self.model.decision_function([features])[0])
        score = float(np.clip(1-raw/self.baseline, 0, 1))
        color_distance = float(np.abs(features[:18]-self.center[:18]).sum()/6)
        aspect_delta = abs(float(features[18]-self.center[18]))/1.5
        area_delta = abs(float(features[19]-self.center[19]))/.5
        shape_difference = max(aspect_delta, area_delta)
        if color_distance > settings.color_tolerance:
            issues.append("色違い：登録した正解画像と色が異なります")
        if shape_difference > settings.shape_tolerance:
            issues.append("形状違い：登録した正解画像と縦横比や見かけの大きさが異なります")
        # Rules explain discrepancies; only the learned AI score can produce NG.
        quality_bad = any(not s.startswith(("色違い", "形状違い")) for s in issues)
        if quality_bad:
            verdict = "REVIEW"
        elif score >= settings.ng_threshold:
            verdict = "NG"
            if not issues:
                issues.append("登録した正解画像の特徴と異なります")
        elif score <= settings.ok_threshold and not issues:
            verdict = "OK"
            issues.append("登録した正解画像の特徴範囲内です")
        else:
            verdict = "REVIEW"
            if not issues:
                issues.append("AIスコアが判定を保留する範囲にあります")
        return {**base, "verdict": verdict, "ai_executed": True, "ai_score": round(score, 6),
                "svm_decision": decision, "color_distance": color_distance,
                "shape_difference": shape_difference,
                "inference_ms": round((time.perf_counter()-started)*1000, 2)}
