"""
SQLAlchemy数据库模型定义

定义所有数据库表结构
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, Float, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy基类"""
    pass


class SessionModel(Base):
    """会话表"""
    __tablename__ = "sessions"

    id = Column(String(128), primary_key=True)
    title = Column(String(256), nullable=False, default="新对话")
    user_id = Column(String(128), nullable=True, index=True)
    workspace_id = Column(String(128), nullable=True)
    workspace_type = Column(String(32), nullable=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")


class MessageModel(Base):
    """消息表"""
    __tablename__ = "messages"

    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    tool_call_id = Column(String(128), nullable=True)
    tool_name = Column(String(128), nullable=True)
    tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("SessionModel", back_populates="messages")


class WorkspaceModel(Base):
    """工作区表"""
    __tablename__ = "workspaces"

    id = Column(String(128), primary_key=True)
    workspace_type = Column(String(32), nullable=False)
    status = Column(String(32), default="created")
    description = Column(Text, nullable=True)
    directories = Column(JSON, default=dict)
    config = Column(JSON, default=dict)
    session_id = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserModel(Base):
    """应用用户（注册账号或公共体验账号）"""

    __tablename__ = "app_users"

    id = Column(String(36), primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(32), nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)


class PublicDemoDailyUsageModel(Base):
    """公共体验账号按日对话计数"""

    __tablename__ = "public_demo_daily_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_day = Column(String(10), nullable=False, index=True)
    chat_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("user_id", "usage_day", name="uq_public_demo_user_day"),)


class LLMConfigModel(Base):
    """LLM配置表"""
    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=True, index=True)
    provider = Column(String(32), nullable=False)
    model = Column(String(64), nullable=False)
    api_key_encrypted = Column(Text, nullable=True)
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=2048)
    top_p = Column(Float, default=0.95)
    frequency_penalty = Column(Float, default=0.0)
    presence_penalty = Column(Float, default=0.0)
    enable_online_search = Column(Boolean, default=False)
    enable_reasoning = Column(Boolean, default=False)
    system_prompt = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
