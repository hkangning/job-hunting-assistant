"""业务异常与全量错误码：错误码只在本文档定义，禁止在别处散落魔法数字（项目结构文档 4）。"""

import logging
from enum import IntEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(IntEnum):
    """全量错误码，与接口文档 1.3 错误码表逐条对应（元组 = 码, HTTP 状态码, 默认文案）。"""

    def __new__(cls, value: int, http_status: int, default_message: str):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.http_status = http_status
        obj.default_message = default_message
        return obj

    SUCCESS = (0, 200, "ok")
    INTERNAL_ERROR = (10000, 500, "系统内部错误")
    PARAM_INVALID = (10001, 400, "参数校验失败")
    NOT_FOUND = (10002, 404, "资源不存在")
    CONFLICT = (10003, 409, "资源已存在")
    LLM_CALL_FAILED = (10010, 502, "AI 服务暂不可用，请重试或检查设置")
    LLM_OUTPUT_INVALID = (10011, 502, "AI 输出格式异常，请重试")
    LLM_KEY_MISSING = (10012, 400, "未配置 AI 密钥，请前往设置页配置")
    LLM_TEST_FAILED = (10013, 502, "AI 连通性测试失败")
    IMPORT_FILE_INVALID = (20001, 400, "导入文件格式错误")
    IMPORT_ROW_INVALID = (20002, 400, "导入文件中存在非法行")
    QUESTION_POOL_EMPTY = (30001, 404, "该方向暂无题目，请更换方向")
    WRONG_QUESTION_INVALID = (30002, 404, "错题不存在或已掌握")
    INTERVIEW_STATE_INVALID = (40001, 409, "面试会话状态非法")
    EXPERIENCE_EXTRACT_FAILED = (40002, 502, "面经结构化提取失败")
    AGENT_TOOL_ARGS_MISSING = (50001, 400, "工具参数不完整")
    ASR_FAILED = (60001, 502, "语音转写失败")
    CRAWL_FAILED = (70001, 502, "就业网抓取失败")
    # —— 8xxxx 账号与鉴权段（接口文档 1.3）——
    UNAUTHORIZED = (80001, 401, "登录状态已失效，请重新登录")
    TOKEN_EXPIRED = (80002, 401, "登录状态已失效，请重新登录")  # 与 80001 同款文案，不暴露失效原因
    USERNAME_EXISTS = (80003, 409, "用户名已存在")
    LOGIN_FAILED = (80004, 401, "用户名或密码错误")  # 统一文案，不区分账号不存在与密码错误（防枚举）
    ACCOUNT_LOCKED = (80005, 403, "账号已锁定，请稍后重试")
    PASSWORD_WEAK = (80006, 400, "密码强度不足，至少 6 位")
    OLD_PASSWORD_WRONG = (80007, 400, "原密码错误")


class BizException(Exception):
    """业务异常：服务层直接抛出，由全局处理器转成统一响应体；SSE 场景取 code/message 发 error 事件。

    `data` 用于错误响应需携带明细的场景（如导入全行非法时回传行级错误清单，错误码 20002）。
    """

    def __init__(self, code: ErrorCode, message: str | None = None, data: dict | None = None):
        self.code = code
        self.message = message or code.default_message
        self.data = data
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return self.code.http_status


def error_body(code: ErrorCode, message: str | None = None, data: dict | None = None) -> dict:
    """统一响应体的错误形态（结构与 schemas.common.ApiResponse 一致）。"""
    return {"code": int(code), "message": message or code.default_message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器：所有 HTTP 异常出口统一为 {code, message, data}（系统设计 3.3）。"""

    @app.exception_handler(BizException)
    async def _biz_handler(request: Request, exc: BizException) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=error_body(exc.code, exc.message, exc.data))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        err = exc.errors()[0]
        field = ".".join(str(x) for x in err["loc"] if x not in ("body", "query", "path")) or "参数"
        return JSONResponse(
            status_code=ErrorCode.PARAM_INVALID.http_status,
            content=error_body(ErrorCode.PARAM_INVALID, f"{field}: {err['msg']}"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未捕获异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=ErrorCode.INTERNAL_ERROR.http_status,
            content=error_body(ErrorCode.INTERNAL_ERROR),
        )
