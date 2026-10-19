"""
配置管理模块

提供应用配置管理，支持环境变量和.env文件
"""

from typing import List, Optional
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

from app.paths import annotation_dir, data_dir, get_install_root, refpanel_dir, workspace_dir


def _resolve_env_file() -> str:
    """单一配置：优先 config/chickensv.env，其次 backend/.env"""
    root = get_install_root()
    unified = root / "config" / "chickensv.env"
    if unified.is_file():
        return str(unified)
    legacy = Path(__file__).resolve().parent.parent / ".env"
    return str(legacy)


class Settings(BaseSettings):
    """
    应用配置类
    
    所有配置项都可以通过环境变量设置，或者通过.env文件配置
    """
    
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # 应用基础配置
    app_name: str = Field(default="鸡基因组智能体框架", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    app_env: str = Field(default="development", description="运行环境")
    debug: bool = Field(default=True, description="调试模式")
    
    # 服务器配置
    host: str = Field(default="127.0.0.1", description="监听地址")
    port: int = Field(default=9801, description="监听端口")
    reload: bool = Field(default=True, description="热重载")
    
    # 认证配置
    auth_enabled: bool = Field(default=False, description="是否启用API认证")
    auth_api_key: Optional[str] = Field(default=None, description="API认证密钥")
    auth_exempt_paths: List[str] = Field(
        default=[
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/health",
            "/api/v1/public-config",
            "/api/v1/quota",
        ],
        description="免认证路径",
    )

    # 公网部署相关
    auth_users_enabled: bool = Field(
        default=False,
        description="是否要求用户进入 /chat 前先登录（仅前端路由级开关）",
    )
    persist_user_api_keys: bool = Field(
        default=False,
        description=(
            "是否允许把用户提交的 API Key 持久化到后端 llm_config.json。"
            "公网/多用户部署务必保持 False（默认），仅使用每次请求随 WebSocket 携带的 Key。"
            "仅单机自用且明确需要记住 Key 时才显式设为 True。"
        ),
    )
    public_default_model_enabled: bool = Field(
        default=True,
        description="后端是否提供默认模型 Key（来自环境变量），供未提供 BYOK 的用户使用",
    )

    # 限速 / 配额（公网防滥用）
    rate_limit_enabled: bool = Field(
        default=False,
        description="是否启用通用 HTTP/聊天 IP 限速（与平台默认 Key 配额独立）。",
    )
    rate_limit_http_per_minute: int = Field(
        default=60,
        description="非聊天 HTTP 接口每 IP 每分钟最多调用次数",
    )
    rate_limit_chat_per_minute: int = Field(
        default=20,
        description="通用聊天 IP 限速：每 IP 每分钟次数（RATE_LIMIT_ENABLED 时生效）",
    )
    default_model_limits_enabled: bool = Field(
        default=True,
        description="是否启用平台默认 Key 的 burst + 每日配额（BYOK 不受限）。",
    )
    default_model_burst_window_seconds: int = Field(
        default=300,
        description="平台默认 Key：滑动窗口秒数（默认 5 分钟）",
    )
    default_model_burst_limit: int = Field(
        default=20,
        description="平台默认 Key：窗口内最多对话次数",
    )
    default_model_daily_quota: int = Field(
        default=200,
        description="使用「平台默认 Key」的每 IP 每日最多对话轮次（0=不限制）",
    )
    rate_limit_storage_uri: str = Field(
        default="memory://",
        description="slowapi 存储后端：memory:// 或 redis://host:port/db",
    )
    trusted_proxy_hops: int = Field(
        default=1,
        description=(
            "本机反代（Nginx/serve-proxy）之外、还需跳过的可信反代层数，用于从 "
            "X-Forwarded-For 中解析真实客户端 IP，抵抗 XFF 伪造绕过限速。"
            "典型部署：本机 Nginx 之上还有 1 层高校外网反代 → 设为 1（默认）。"
            "若公网请求直达本机 Nginx（无额外反代）→ 设为 0。"
        ),
    )
    
    # CORS配置
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://localhost:9800",
            "http://127.0.0.1:9800",
            "http://localhost:9815",
            "http://127.0.0.1:9815"
        ],
        description="允许的跨域来源"
    )
    cors_origin_regex: str = Field(
        default=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?$",
        description="允许的跨域来源正则"
    )
    cors_allow_credentials: bool = Field(default=True, description="允许携带凭证")
    cors_allow_methods: List[str] = Field(default=["*"], description="允许的HTTP方法")
    cors_allow_headers: List[str] = Field(default=["*"], description="允许的HTTP头")
    
    # WebSocket配置
    ws_heartbeat_interval: int = Field(default=30, description="心跳检测间隔(秒)")
    ws_timeout: int = Field(default=60, description="连接超时时间(秒)")
    ws_max_connections: int = Field(default=1000, description="最大WebSocket连接数")
    ws_broadcast_batch_size: int = Field(default=100, description="广播批处理大小")
    ws_cleanup_interval: int = Field(default=60, description="连接清理间隔(秒)")
    
    # MCP服务器配置
    mcp_server_url: str = Field(
        default="http://localhost:9802",
        description="MCP服务器地址"
    )
    mcp_http_timeout_seconds: float = Field(
        default=300.0,
        description="MCP HTTP 客户端读超时（秒），需覆盖重型工具如全基因组扫描",
    )

    # Dify 知识库（Dataset API retrieve）
    dify_api_base: Optional[str] = Field(
        default="http://127.0.0.1/v1",
        description="Dify API 根路径，如 http://127.0.0.1/v1",
    )
    dify_api_key: Optional[str] = Field(default=None, description="Dify Dataset API Key")
    dify_http_timeout_seconds: float = Field(default=60.0, description="Dify HTTP 读超时（秒）")
    dify_default_search_method: str = Field(
        default="hybrid_search",
        description="默认检索方式：hybrid_search / full_text_search / semantic_search",
    )
    dify_default_top_k: int = Field(default=5, description="默认返回条数")
    dify_reranking_enable: bool = Field(default=True, description="retrieve 是否启用 rerank")
    dify_score_threshold_enabled: bool = Field(
        default=False,
        description="retrieve 是否启用分数阈值（迁移验证阶段建议 false）",
    )
    dify_score_threshold: Optional[float] = Field(default=0.5, description="分数阈值")
    dify_dataset_parent_qa: str = Field(
        default="",
        description="中文期刊-父子QA 知识库 dataset_id",
    )
    dify_dataset_pure_qa: str = Field(
        default="",
        description="中文期刊-纯QA 知识库 dataset_id",
    )
    dify_dataset_english_qa: str = Field(
        default="",
        description="英文期刊-QA 知识库 dataset_id",
    )
    
    # LLM配置（默认平台模型：DeepSeek V4 Flash）
    llm_provider: str = Field(default="deepseek", description="LLM提供商")
    qwen_api_key: Optional[str] = Field(default=None, description="通义千问API密钥")
    qwen_model: str = Field(default="qwen-max", description="通义千问模型")
    deepseek_api_key: Optional[str] = Field(default=None, description="DeepSeek API 密钥（平台默认模型）")
    deepseek_model: str = Field(default="deepseek-v4-flash", description="DeepSeek 默认模型")
    platform_default_max_tokens: int = Field(
        default=8192,
        description="平台默认模型单次回答 max_tokens（deepseek-v4 系列上限 8192，避免截断诱发编造）",
    )
    llm_config_admin_token: str = Field(
        default="",
        description=(
            "修改后端全局 LLM 配置（POST /api/v1/llm/config）所需的管理员令牌，"
            "通过请求头 X-Admin-Token 提供。为空（默认）时该接口不写入全局配置、仅返回成功："
            "无登录公网部署下，防止访客经网页设置面板互相覆盖平台默认模型。"
            "管理员需要调整平台默认模型时，在 chickensv.env 配置该令牌并携带请求头调用。"
        ),
    )
    empty_result_hard_block: bool = Field(
        default=True,
        description="数据工具全部返回空/未匹配时，代码强制改写为「未找到记录」模板，禁止模型续写特征描述",
    )
    session_persistence_enabled: bool = Field(
        default=True,
        description="是否将会话历史持久化到 SQLite，使服务重启/重连后仍可恢复上下文",
    )
    session_db_path: str = Field(
        default="./data/sessions.db",
        description="会话历史持久化 SQLite 文件路径",
    )
    session_ttl_days: int = Field(
        default=7,
        description="会话历史保留天数，超过则在启动时清理",
    )
    openrouter_api_key: Optional[str] = Field(default=None, description="OpenRouter API 密钥（可选）")
    kimi_api_key: Optional[str] = Field(default=None, description="Kimi API密钥（已弃用，仅兼容旧配置）")
    kimi_model: str = Field(default="moonshot-v1-8k", description="Kimi模型（已弃用）")
    
    # 存储配置
    storage_type: str = Field(default="memory", description="存储类型")
    redis_url: Optional[str] = Field(default=None, description="Redis连接URL")
    
    # 数据库配置
    database_url: Optional[str] = Field(
        default=None,
        description="数据库连接URL，默认使用 SQLite"
    )
    db_pool_size: int = Field(default=10, description="数据库连接池大小")
    db_max_overflow: int = Field(default=20, description="数据库最大溢出连接数")
    db_pool_timeout: int = Field(default=30, description="数据库连接超时时间(秒)")
    db_pool_recycle: int = Field(default=3600, description="数据库连接回收时间(秒)")
    
    # 日志配置
    log_level: str = Field(default="info", description="日志级别")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="日志格式"
    )
    
    # Agent Pool 配置
    agent_pool_max_size: int = Field(
        default=100,
        description="Agent Pool 最大实例数"
    )
    agent_pool_idle_timeout: int = Field(
        default=1800,
        description="Agent 空闲超时时间(秒)，默认30分钟"
    )
    agent_pool_max_age: int = Field(
        default=7200,
        description="Agent 最大存活时间(秒)，默认2小时"
    )
    agent_pool_cleanup_interval: int = Field(
        default=300,
        description="Agent Pool 清理间隔(秒)，默认5分钟"
    )
    agent_max_execution_time: int = Field(
        default=300,
        description="Agent 单次请求最大执行时间(秒)，默认5分钟"
    )
    agent_memory_max_tokens: int = Field(
        default=128_000,
        description=(
            "Agent 对话上下文 token 估算上限（裁剪阈值）。"
            "现代模型上下文可达 128K~1M，默认 128K；极端长对话仍会按轮次裁剪。"
        ),
    )
    agent_memory_preserve_min_messages: int = Field(
        default=8,
        description="裁剪时至少保留的消息条数，避免把当前轮次删光",
    )
    agent_tool_result_max_chars: int = Field(
        default=32_000,
        description="单个工具结果写入 memory 的最大字符数（超出则截断）",
    )
    agent_tool_result_gwas_max_chars: int = Field(
        default=48_000,
        description="GWAS 扫描结果写入 memory 的最大字符数",
    )
    
    # 响应缓存配置
    cache_enabled: bool = Field(default=True, description="是否启用响应缓存")
    cache_memory_max_size: int = Field(default=1000, description="内存缓存最大条目数")
    cache_memory_ttl: int = Field(default=300, description="内存缓存TTL(秒)")
    cache_persistent_enabled: bool = Field(default=True, description="是否启用持久化缓存")
    cache_persistent_path: str = Field(default="./data/cache.db", description="持久化缓存路径")
    cache_persistent_max_size: int = Field(default=10000, description="持久化缓存最大条目数")
    cache_persistent_ttl: int = Field(default=3600, description="持久化缓存TTL(秒)")
    
    # 对话压缩配置
    compression_enabled: bool = Field(default=True, description="是否启用对话压缩")
    compression_max_messages: int = Field(default=40, description="触发压缩的消息数阈值")
    compression_max_tokens: int = Field(default=64_000, description="触发压缩的token数阈值")
    compression_strategy: str = Field(default="summary", description="压缩策略: summary/extraction/hybrid")
    compression_preserve_recent: int = Field(default=8, description="保留最近N条消息")
    
    # 任务队列配置
    task_queue_enabled: bool = Field(default=True, description="是否启用任务队列")
    task_queue_db_path: str = Field(default="./data/tasks.db", description="任务队列数据库路径")
    task_queue_max_concurrent: int = Field(default=3, description="最大并发任务数")
    task_queue_num_workers: int = Field(default=3, description="工作器数量")
    
    # 数据文件路径配置
    csv_data_path: str = Field(
        default_factory=lambda: str(data_dir() / "2063_SV_frq.csv"),
        description="CSV数据文件路径",
    )
    phenotype_data_path: str = Field(
        default_factory=lambda: str(data_dir() / "鸡种表型-2024.csv"),
        description="表型数据文件路径",
    )
    annotation_gff3_path: str = Field(
        default_factory=lambda: str(
            annotation_dir()
            / "Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3"
        ),
        description="GFF3注释文件路径",
    )
    workspace_base_path: str = Field(
        default_factory=lambda: str(workspace_dir()),
        description="工作区基础目录",
    )
    workspace_max_upload_mb: int = Field(
        default=5,
        description="工作区单文件上传大小上限（MB）",
    )
    imputation_max_concurrent: int = Field(
        default=2,
        description=(
            "全局同时运行的 Beagle 填充进程上限（每个约占用数 GB 内存）。"
            "超过则拒绝新填充请求，防止资源被耗尽打崩整机。"
        ),
    )
    refpanel_path: str = Field(
        default_factory=lambda: str(refpanel_dir()),
        description="参考面板目录",
    )
    
    # SV数据库配置
    sv_db_enabled: bool = Field(default=True, description="是否启用SV数据库")
    sv_db_type: str = Field(default="csv", description="SV数据库类型: csv/sqlite/postgresql/mysql")
    sv_db_host: str = Field(default="localhost", description="SV数据库主机")
    sv_db_port: int = Field(default=5432, description="SV数据库端口")
    sv_db_name: str = Field(default="sv_database", description="SV数据库名")
    sv_db_user: Optional[str] = Field(default=None, description="SV数据库用户名")
    sv_db_password: Optional[str] = Field(default=None, description="SV数据库密码")
    sv_db_sqlite_path: str = Field(default="./data/sv_database.db", description="SQLite数据库路径")
    sv_db_csv_path: str = Field(
        default_factory=lambda: str(data_dir() / "2063_SV_frq.csv"),
        description="CSV数据文件路径",
    )
    
    # Beagle 填充（JAR 与参考面板在 refpanel_path 下；迁移时务必同步整个 refpanel/）
    beagle_jar_path: Optional[str] = Field(
        default=None,
        description="Beagle JAR 绝对路径；留空则自动查找 refpanel/beagle.jar 与 /usr/local、/opt",
    )

    def is_development(self) -> bool:
        """检查是否为开发环境"""
        return self.app_env.lower() == "development"
    
    @property
    def is_production(self) -> bool:
        """检查是否为生产环境"""
        return self.app_env.lower() == "production"


# 全局配置实例
settings = Settings()
