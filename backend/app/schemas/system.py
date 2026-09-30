"""画像与设置传输模型（接口文档 3.12；表结构见数据库设计 3.14 / 3.15）。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints, field_serializer

from app.models.enums import ExperienceType
from app.utils.datetime_utils import format_datetime

# 经历名称：必填、去首尾空格、1~100 字（空串 → 10001，接口文档 3.12）
ExperienceTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ProfileExperience(BaseModel):
    """画像经历条目（user_profile.experiences 数组元素，接口文档 3.12）：按需增删，最多 10 条。"""

    type: ExperienceType = Field(
        description="经历类型：PROJECT 项目 / INTERNSHIP 实习 / CAMPUS 校园（社团、竞赛、课程实践）"
    )
    title: ExperienceTitle = Field(description="经历名称（必填，如「校园租赁平台」「XX 公司暑期实习」），1~100 字")
    org: str | None = Field(default=None, max_length=100, description="组织 / 公司名，≤100 字，可空")
    role: str | None = Field(default=None, max_length=50, description="担任角色（如 后端开发），≤50 字，可空")
    period: str | None = Field(
        default=None, max_length=50, description="时间区间文本（如 2026.07-2026.09），≤50 字，可空"
    )
    description: str | None = Field(
        default=None, max_length=2000, description="经历描述 / 主要工作，≤2000 字，可空"
    )


class ProfileDTO(BaseModel):
    """用户画像 DTO（GET /profile、PUT /profile 响应 data）；每账号一份，按登录态隔离。"""

    name: str | None = Field(description="姓名")
    school: str | None = Field(description="学校")
    major: str | None = Field(description="专业")
    degree: str | None = Field(description="学历（本科/硕士）")
    gpa: str | None = Field(description="GPA 文本")
    english_level: str | None = Field(description="英语水平（如 CET-6 441）")
    experiences: list[ProfileExperience] | None = Field(
        description="结构化经历条目（项目 / 实习 / 校园，≤10 条）；未填写为 null（JD 分析与面试项目深挖的核心输入）"
    )
    target_position: str | None = Field(description="目标岗位")
    target_city: str | None = Field(description="目标城市")
    skills: str | None = Field(description="技能栈标签，逗号分隔")
    weaknesses: str | None = Field(description="弱项标签，逗号分隔")
    note: str | None = Field(description="备注")
    updated_at: datetime = Field(description="更新时间 YYYY-MM-DD HH:mm:ss")

    @field_serializer("updated_at")
    def _serialize_updated_at(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`（接口文档 1.1）。"""
        return format_datetime(value)


class ProfileUpdateRequest(BaseModel):
    """画像更新请求体（PUT /profile）：只提交需要变更的字段，未提交的保持原值（传 null 即清空）。"""

    name: str | None = Field(default=None, max_length=50, description="姓名，≤50 字")
    school: str | None = Field(default=None, max_length=100, description="学校，≤100 字")
    major: str | None = Field(default=None, max_length=100, description="专业，≤100 字")
    degree: str | None = Field(default=None, max_length=20, description="学历（本科/硕士），≤20 字")
    gpa: str | None = Field(default=None, max_length=20, description="GPA 文本（如 3.20/4.00），≤20 字")
    english_level: str | None = Field(default=None, max_length=50, description="英语水平（如 CET-6 441），≤50 字")
    experiences: list[ProfileExperience] | None = Field(
        default=None,
        max_length=10,
        description="结构化经历条目，按需增删、最多 10 条；传空数组或 null 即清空，未传保持原值（元素字段限制见 ProfileExperience）",
    )
    target_position: str | None = Field(default=None, max_length=100, description="目标岗位，≤100 字")
    target_city: str | None = Field(default=None, max_length=50, description="目标城市，≤50 字")
    skills: str | None = Field(default=None, description="技能栈标签，逗号分隔")
    weaknesses: str | None = Field(default=None, description="弱项标签，逗号分隔")
    note: str | None = Field(default=None, description="备注，不限长度")


class ResumeExtracted(BaseModel):
    """简历 AI 抽取结果（POST /profile/resume 响应的 `extracted`；未配 Key 或抽取失败时为 null）。"""

    name: str | None = Field(description="姓名")
    school: str | None = Field(description="学校")
    major: str | None = Field(description="专业")
    degree: str | None = Field(description="学历（本科/硕士/博士）")
    gpa: str | None = Field(description="GPA 文本")
    english_level: str | None = Field(description="英语水平（如 CET-6 441）")
    skills: list[str] | None = Field(description="技能关键词数组（前端填入时逗号拼接）")
    experiences: list[ProfileExperience] | None = Field(
        description="抽取出的结构化经历条目（≤10 条，title 缺失或类型非法的条目已丢弃）；简历里无可辨认经历时为 null"
    )


class ResumeParseData(BaseModel):
    """简历解析响应（POST /profile/resume）：**纯解析不落库**，用户核对修改后经 PUT /profile 保存。"""

    extracted: ResumeExtracted | None = Field(
        description="AI 抽取的画像字段（含经历条目）；未配 Key 或抽取失败为 null（原文本不返回、不落库）"
    )


class SettingsDTO(BaseModel):
    """设置响应（GET /settings）：账号级偏好 + 系统级抓取配置；**LLM 相关字段已全部迁至 `/llm-providers`**。"""

    tts_enabled: bool = Field(description="TTS 播报开关（账号级，默认 false）")
    voice_enabled: bool = Field(description="语音作答开关（账号级，默认 false）")
    default_question_count: int = Field(description="模拟面试默认题量（账号级，默认 8）")
    asr_provider: str = Field(description="ASR 供应商（账号级）：funasr = 本地模型（默认）/ xunfei = 云端备选")
    tts_voice: str = Field(description="TTS 音色名（账号级，默认 zh-CN-XiaoxiaoNeural 晓晓）")
    asr_key_set: bool = Field(description="是否已配置讯飞语音 Key（**不回显明文**；funasr 下恒为 false）")
    guide_done: bool = Field(description="新手指引是否已读（账号级，默认 false）")
    crawl_enabled: bool = Field(description="就业网抓取开关（**系统级**，任一账号修改全局生效）")


class SettingsUpdateRequest(BaseModel):
    """设置更新请求体（PUT /settings）：只提交需要变更的字段，未提交的保持原值。"""

    tts_enabled: StrictBool | None = Field(default=None, description="TTS 播报开关（非布尔值 → 10001）")
    voice_enabled: StrictBool | None = Field(default=None, description="语音作答开关（非布尔值 → 10001）")
    default_question_count: int | None = Field(default=None, ge=1, le=50, description="模拟面试默认题量，1~50")
    asr_provider: Literal["funasr", "xunfei"] | None = Field(default=None, description="ASR 供应商，仅 funasr / xunfei")
    tts_voice: str | None = Field(default=None, description="TTS 音色名（可选值见 GET /tts/voices）")
    guide_done: StrictBool | None = Field(default=None, description="新手指引已读标记（非布尔值 → 10001）")
    crawl_enabled: StrictBool | None = Field(default=None, description="就业网抓取开关（系统级，非布尔值 → 10001）")
    asr_app_id: str | None = Field(default=None, description="讯飞语音 AppID；传值则加密覆盖，传空串不修改")
    asr_api_key: str | None = Field(default=None, description="讯飞语音 Key；传值则加密覆盖，传空串不修改")
