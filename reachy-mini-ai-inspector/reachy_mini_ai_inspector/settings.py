from pydantic import BaseModel, Field, model_validator


class ROI(BaseModel):
    x: float = Field(.15, ge=0, le=.9)
    y: float = Field(.15, ge=0, le=.9)
    width: float = Field(.7, ge=.1, le=1)
    height: float = Field(.7, ge=.1, le=1)

    @model_validator(mode="after")
    def inside_frame(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("検査範囲は画像内に収めてください")
        return self


class Settings(BaseModel):
    roi: ROI = Field(default_factory=ROI)
    normal_name: str = Field("正常品", min_length=1, max_length=80)
    ok_threshold: float = Field(.38, ge=.01, le=.95)
    ng_threshold: float = Field(.68, ge=.05, le=.99)
    color_tolerance: float = Field(.30, ge=.05, le=1)
    shape_tolerance: float = Field(.28, ge=.05, le=1)

    @model_validator(mode="after")
    def thresholds(self):
        if self.ok_threshold >= self.ng_threshold:
            raise ValueError("OK閾値はNG閾値未満にしてください")
        return self

    def profile(self, criterion_id=None):
        profile = {"roi": self.roi.model_dump(), "features": "hsv-shape-v1"}
        if criterion_id is None:
            profile["normal_name"] = self.normal_name
        else:
            profile["criterion_id"] = criterion_id
        return profile
