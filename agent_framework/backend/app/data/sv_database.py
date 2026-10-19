"""
SV 数据库连接实现

提供与鸡基因组 SV 数据库的连接：
- 支持多种数据库后端（CSV/SQLite/PostgreSQL/MySQL）
- 异步查询接口
- 连接池管理
- 查询缓存
"""

import json
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import pandas as pd
import os

from app.paths import data_dir
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Float, Text, select, and_, or_, func

logger = logging.getLogger(__name__)


def _normalize_chrom(value: str) -> str:
    chrom = str(value).strip()
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    return chrom


Base = declarative_base()


class SVType(Enum):
    """SV 类型"""
    DEL = "DEL"  # 缺失
    DUP = "DUP"  # 重复
    INS = "INS"  # 插入
    INV = "INV"  # 倒位
    BND = "BND"  # 断裂


class SVRecordDB(Base):
    """SV 记录数据库模型"""
    __tablename__ = "sv_records"
    
    id = Column(String(50), primary_key=True)
    chrom = Column(String(10), nullable=False, index=True)
    start = Column(Integer, nullable=False, index=True)
    end = Column(Integer, nullable=False, index=True)
    sv_type = Column(String(10), nullable=False, index=True)
    length = Column(Integer)
    
    # 基因信息
    gene_name = Column(String(50), index=True)
    gene_id = Column(String(50))
    
    # 频率信息
    freq_gushi = Column(Float, default=0.0)
    freq_other_breeds = Column(Text)  # JSON 格式存储其他品种频率
    
    # 功能注释
    annotation = Column(Text)
    impact = Column(String(20))
    
    # 元数据
    source = Column(String(50))
    quality = Column(Float)
    created_at = Column(String(30))


@dataclass
class SVRecord:
    """SV 记录数据类"""
    id: str
    chrom: str
    start: int
    end: int
    sv_type: str
    length: int
    
    # 基因信息
    gene_name: Optional[str] = None
    gene_id: Optional[str] = None
    
    # 频率信息
    freq_gushi: float = 0.0
    freq_other_breeds: Dict[str, float] = field(default_factory=dict)
    
    # 功能注释
    annotation: Optional[str] = None
    impact: Optional[str] = None
    
    # 元数据
    source: Optional[str] = None
    quality: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "chrom": self.chrom,
            "start": self.start,
            "end": self.end,
            "sv_type": self.sv_type,
            "length": self.length,
            "gene_name": self.gene_name,
            "gene_id": self.gene_id,
            "freq_gushi": self.freq_gushi,
            "freq_other_breeds": self.freq_other_breeds,
            "annotation": self.annotation,
            "impact": self.impact,
            "source": self.source,
            "quality": self.quality,
        }


@dataclass
class SVQuery:
    """SV 查询条件"""
    # 位置查询
    chrom: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    
    # 基因查询
    gene_name: Optional[str] = None
    gene_id: Optional[str] = None
    
    # ID查询
    sv_id: Optional[str] = None
    
    # 类型查询
    sv_type: Optional[str] = None
    
    # 频率查询
    min_freq: Optional[float] = None
    max_freq: Optional[float] = None
    breed: Optional[str] = None
    
    # 分页
    limit: int = 100
    offset: int = 0
    
    # 排序
    order_by: str = "start"
    order_desc: bool = False


@dataclass
class SVQueryResult:
    """SV 查询结果"""
    records: List[SVRecord]
    total: int
    page: int
    page_size: int
    has_more: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "records": [r.to_dict() for r in self.records],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "has_more": self.has_more,
        }


@dataclass
class SVDatabaseConfig:
    """SV 数据库配置"""
    # 连接配置
    db_type: str = "csv"  # csv, sqlite, postgresql, mysql
    host: str = "localhost"
    port: int = 5432
    database: str = "sv_database"
    username: Optional[str] = None
    password: Optional[str] = None

    # CSV 专用
    csv_path: str = field(default_factory=lambda: str(data_dir() / "2063_SV_frq.csv"))

    # SQLite 专用
    sqlite_path: str = "./data/sv_database.db"

    # 连接池配置
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30

    # 查询配置
    default_limit: int = 100
    max_limit: int = 1000

    # 缓存配置
    enable_cache: bool = True
    cache_ttl: int = 300


class SVDatabase:
    """
    SV 数据库连接管理器

    提供异步查询接口和连接池管理
    """

    def __init__(self, config: Optional[SVDatabaseConfig] = None):
        self.config = config or SVDatabaseConfig()
        self._engine = None
        self._session_maker = None
        self._csv_data: Optional[pd.DataFrame] = None

        # 统计
        self._query_count = 0
        self._cache_hits = 0

        logger.info(f"SVDatabase 初始化: type={self.config.db_type}")

    async def connect(self):
        """连接数据库"""
        if self.config.db_type == "csv":
            # CSV 数据加载
            if not os.path.exists(self.config.csv_path):
                raise FileNotFoundError(f"CSV文件不存在: {self.config.csv_path}")
            logger.info(f"加载CSV数据: {self.config.csv_path}")
            try:
                self._csv_data = pd.read_csv(self.config.csv_path, encoding="utf-8", low_memory=False)
            except UnicodeDecodeError:
                self._csv_data = pd.read_csv(self.config.csv_path, encoding="gbk", low_memory=False)
            logger.info(f"CSV数据加载完成: {len(self._csv_data)} 条记录, 列: {list(self._csv_data.columns)[:5]}...")
            return

        # 构建连接 URL
        if self.config.db_type == "sqlite":
            url = f"sqlite+aiosqlite:///{self.config.sqlite_path}"
        elif self.config.db_type == "postgresql":
            url = (
                f"postgresql+asyncpg://{self.config.username}:{self.config.password}"
                f"@{self.config.host}:{self.config.port}/{self.config.database}"
            )
        elif self.config.db_type == "mysql":
            url = (
                f"mysql+aiomysql://{self.config.username}:{self.config.password}"
                f"@{self.config.host}:{self.config.port}/{self.config.database}"
            )
        else:
            raise ValueError(f"不支持的数据库类型: {self.config.db_type}")
        
        # 创建引擎
        self._engine = create_async_engine(
            url,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            echo=False,
        )
        
        # 创建会话工厂
        self._session_maker = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 创建表
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info(f"SV 数据库已连接: {self.config.db_type}")
    
    async def disconnect(self):
        """断开数据库连接"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None
        self._csv_data = None
        logger.info("SV 数据库已断开")

    async def _query_csv(self, query: SVQuery) -> SVQueryResult:
        """CSV 数据查询实现"""
        if self._csv_data is None:
            raise RuntimeError("CSV数据未加载")

        df = self._csv_data
        col_map = {c.lower(): c for c in df.columns}

        filtered = df
        if query.chrom:
            chrom_col = col_map.get("chr") or col_map.get("chromosome")
            if chrom_col:
                query_chrom = _normalize_chrom(query.chrom)
                chrom_series = df[chrom_col].astype(str).map(_normalize_chrom)
                filtered = filtered[chrom_series == query_chrom]

        if query.start is not None:
            pos_col = col_map.get("pos") or col_map.get("start")
            if pos_col and "end" in col_map:
                filtered = filtered[filtered[col_map["end"]] >= query.start]

        if query.end is not None:
            pos_col = col_map.get("pos") or col_map.get("start")
            if pos_col and "end" in col_map:
                filtered = filtered[filtered[pos_col] <= query.end]

        if query.gene_name:
            gene_col = col_map.get("gene") or col_map.get("gene_name")
            if gene_col:
                mask = filtered[gene_col].astype(str).str.contains(query.gene_name, case=False, na=False)
                filtered = filtered[mask]

        if query.sv_id:
            id_col = col_map.get("id") or col_map.get("sv_id")
            if id_col:
                filtered = filtered[filtered[id_col].astype(str).str.lower() == query.sv_id.lower()]

        if query.sv_type:
            type_col = col_map.get("sv_type") or col_map.get("type")
            if type_col and query.sv_type in df[type_col].values:
                filtered = filtered[filtered[type_col] == query.sv_type]

        total = len(filtered)

        if query.order_desc:
            order_col = col_map.get(query.order_by, "start")
            if order_col in filtered.columns:
                filtered = filtered.sort_values(order_col, ascending=False)
        else:
            order_col = col_map.get(query.order_by, "start")
            if order_col in filtered.columns:
                filtered = filtered.sort_values(order_col, ascending=True)

        offset = query.offset
        limit = min(query.limit, self.config.max_limit)
        page_df = filtered.iloc[offset:offset + limit]

        records = []
        for _, row in page_df.iterrows():
            records.append(SVRecord(
                id=str(row.get("SV_ID", "")),
                chrom=str(row.get("Chr", "")),
                start=int(row.get("Start", 0)),
                end=int(row.get("End", 0)),
                sv_type=str(row.get("SV_type", "")),
                length=int(row.get("Length", 0)),
                gene_name=str(row.get("Gene", "")) if pd.notna(row.get("Gene")) else None,
                gene_id=str(row.get("Gene_ID", "")) if pd.notna(row.get("Gene_ID")) else None,
                freq_gushi=float(row.get("Mean_fre", 0)),
            ))

        return SVQueryResult(
            records=records,
            total=total,
            page=offset // limit + 1,
            page_size=limit,
            has_more=(offset + limit) < total
        )

    async def query(self, query: SVQuery) -> SVQueryResult:
        """
        查询 SV 记录

        Args:
            query: 查询条件

        Returns:
            查询结果
        """
        self._query_count += 1

        # CSV 数据查询
        if self.config.db_type == "csv":
            return await self._query_csv(query)

        if not self._session_maker:
            raise RuntimeError("数据库未连接")

        async with self._session_maker() as session:
            # 构建查询
            stmt = select(SVRecordDB)
            
            # 应用过滤条件
            filters = []
            
            if query.chrom:
                normalized_chrom = _normalize_chrom(query.chrom)
                filters.append(
                    or_(
                        func.lower(SVRecordDB.chrom) == normalized_chrom.lower(),
                        func.lower(SVRecordDB.chrom) == f"chr{normalized_chrom}".lower(),
                    )
                )
            
            if query.start is not None:
                filters.append(SVRecordDB.end >= query.start)
            
            if query.end is not None:
                filters.append(SVRecordDB.start <= query.end)
            
            if query.gene_name:
                filters.append(SVRecordDB.gene_name.ilike(f"%{query.gene_name}%"))
            
            if query.gene_id:
                filters.append(SVRecordDB.gene_id == query.gene_id)
            
            if query.sv_id:
                filters.append(SVRecordDB.id == query.sv_id)
            
            if query.sv_type:
                filters.append(SVRecordDB.sv_type == query.sv_type)
            
            if filters:
                stmt = stmt.where(and_(*filters))
            
            # 获取总数
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total_result = await session.execute(count_stmt)
            total = total_result.scalar()
            
            # 应用排序
            order_column = getattr(SVRecordDB, query.order_by, SVRecordDB.start)
            if query.order_desc:
                stmt = stmt.order_by(order_column.desc())
            else:
                stmt = stmt.order_by(order_column.asc())
            
            # 应用分页
            limit = min(query.limit, self.config.max_limit)
            stmt = stmt.offset(query.offset).limit(limit)
            
            # 执行查询
            result = await session.execute(stmt)
            db_records = result.scalars().all()
            
            # 转换为数据类
            records = [self._db_to_record(r) for r in db_records]
            
            return SVQueryResult(
                records=records,
                total=total,
                page=query.offset // limit + 1,
                page_size=limit,
                has_more=(query.offset + limit) < total
            )
    
    async def get_by_id(self, sv_id: str) -> Optional[SVRecord]:
        """根据 ID 获取 SV 记录"""
        if self.config.db_type == "csv":
            result = await self.query(SVQuery(sv_id=sv_id, limit=1))
            return result.records[0] if result.records else None
        
        if not self._session_maker:
            raise RuntimeError("数据库未连接")
        
        async with self._session_maker() as session:
            result = await session.execute(
                select(SVRecordDB).where(SVRecordDB.id == sv_id)
            )
            db_record = result.scalar_one_or_none()
            
            if db_record:
                return self._db_to_record(db_record)
            return None
    
    async def get_by_gene(self, gene_name: str) -> List[SVRecord]:
        """根据基因名获取 SV 记录"""
        result = await self.query(SVQuery(gene_name=gene_name, limit=1000))
        return result.records
    
    async def get_by_region(
        self,
        chrom: str,
        start: int,
        end: int
    ) -> List[SVRecord]:
        """根据区域获取 SV 记录"""
        result = await self.query(
            SVQuery(chrom=chrom, start=start, end=end, limit=1000)
        )
        return result.records
    
    async def get_frequency(
        self,
        sv_id: str,
        breed: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取 SV 频率信息"""
        record = await self.get_by_id(sv_id)
        
        if not record:
            return {"error": "SV not found"}
        
        if breed:
            if breed == "固始":
                return {
                    "sv_id": sv_id,
                    "breed": breed,
                    "frequency": record.freq_gushi,
                    "count": None,  # 可以从数据库计算
                    "total": None,
                }
            else:
                freq = record.freq_other_breeds.get(breed, 0.0)
                return {
                    "sv_id": sv_id,
                    "breed": breed,
                    "frequency": freq,
                }
        
        # 返回所有品种频率
        return {
            "sv_id": sv_id,
            "frequencies": {
                "固始": record.freq_gushi,
                **record.freq_other_breeds
            }
        }
    
    async def insert(self, record: SVRecord) -> bool:
        """插入 SV 记录"""
        if self.config.db_type == "csv":
            logger.warning("CSV 模式不支持插入操作")
            return False
        
        if not self._session_maker:
            raise RuntimeError("数据库未连接")
        
        try:
            async with self._session_maker() as session:
                db_record = self._record_to_db(record)
                session.add(db_record)
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"插入 SV 记录失败: {e}")
            return False
    
    async def bulk_insert(self, records: List[SVRecord]) -> int:
        """批量插入 SV 记录"""
        if self.config.db_type == "csv":
            logger.warning("CSV 模式不支持批量插入操作")
            return 0
        
        if not self._session_maker:
            raise RuntimeError("数据库未连接")
        
        try:
            async with self._session_maker() as session:
                db_records = [self._record_to_db(r) for r in records]
                session.add_all(db_records)
                await session.commit()
                return len(records)
        except Exception as e:
            logger.error(f"批量插入 SV 记录失败: {e}")
            return 0
    
    def _db_to_record(self, db_record: SVRecordDB) -> SVRecord:
        """数据库记录转数据类"""
        return SVRecord(
            id=db_record.id,
            chrom=db_record.chrom,
            start=db_record.start,
            end=db_record.end,
            sv_type=db_record.sv_type,
            length=db_record.length or (db_record.end - db_record.start),
            gene_name=db_record.gene_name,
            gene_id=db_record.gene_id,
            freq_gushi=db_record.freq_gushi or 0.0,
            freq_other_breeds=json.loads(db_record.freq_other_breeds) if db_record.freq_other_breeds else {},
            annotation=db_record.annotation,
            impact=db_record.impact,
            source=db_record.source,
            quality=db_record.quality,
        )
    
    def _record_to_db(self, record: SVRecord) -> SVRecordDB:
        """数据类转数据库记录"""
        return SVRecordDB(
            id=record.id,
            chrom=record.chrom,
            start=record.start,
            end=record.end,
            sv_type=record.sv_type,
            length=record.length,
            gene_name=record.gene_name,
            gene_id=record.gene_id,
            freq_gushi=record.freq_gushi,
            freq_other_breeds=json.dumps(record.freq_other_breeds),
            annotation=record.annotation,
            impact=record.impact,
            source=record.source,
            quality=record.quality,
            created_at=datetime.utcnow().isoformat(),
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计"""
        return {
            "query_count": self._query_count,
            "cache_hits": self._cache_hits,
            "config": {
                "db_type": self.config.db_type,
                "pool_size": self.config.pool_size,
            }
        }


# 全局数据库实例
_sv_database: Optional[SVDatabase] = None


def init_sv_database(config: Optional[SVDatabaseConfig] = None) -> SVDatabase:
    """初始化全局 SV 数据库"""
    global _sv_database
    _sv_database = SVDatabase(config)
    return _sv_database


def get_sv_database() -> Optional[SVDatabase]:
    """获取全局 SV 数据库实例，如果未初始化则创建默认实例"""
    global _sv_database
    if _sv_database is None:
        logger.warning("SV数据库未初始化，使用默认CSV数据源")
        _sv_database = SVDatabase(SVDatabaseConfig(
            db_type="csv",
            csv_path=str(data_dir() / "2063_SV_frq.csv")
        ))
    return _sv_database
