<template>
  <div class="home-view">
    <div class="dna-bg">
      <svg class="dna-helix dna-left" viewBox="0 0 200 800" xmlns="http://www.w3.org/2000/svg">
        <g class="helix-strand" opacity="0.12">
          <path d="M60,0 C60,50 140,100 140,150 C140,200 60,250 60,300 C60,350 140,400 140,450 C140,500 60,550 60,600 C60,650 140,700 140,750 C140,780 100,800 100,800" fill="none" stroke="#14B8A6" stroke-width="3"/>
          <path d="M140,0 C140,50 60,100 60,150 C60,200 140,250 140,300 C140,350 60,400 60,450 C60,500 140,550 140,600 C140,650 60,700 60,750 C60,780 100,800 100,800" fill="none" stroke="#06B6D4" stroke-width="3"/>
          <line x1="60" y1="25" x2="140" y2="25" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="75" x2="120" y2="75" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="125" x2="140" y2="125" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="175" x2="120" y2="175" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="225" x2="140" y2="225" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="275" x2="120" y2="275" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="325" x2="140" y2="325" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="375" x2="120" y2="375" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="425" x2="140" y2="425" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="475" x2="120" y2="475" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="525" x2="140" y2="525" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="575" x2="120" y2="575" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="625" x2="140" y2="625" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="675" x2="120" y2="675" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="725" x2="140" y2="725" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
        </g>
      </svg>
      <svg class="dna-helix dna-right" viewBox="0 0 200 800" xmlns="http://www.w3.org/2000/svg">
        <g class="helix-strand" opacity="0.08">
          <path d="M60,0 C60,50 140,100 140,150 C140,200 60,250 60,300 C60,350 140,400 140,450 C140,500 60,550 60,600 C60,650 140,700 140,750 C140,780 100,800 100,800" fill="none" stroke="#14B8A6" stroke-width="3"/>
          <path d="M140,0 C140,50 60,100 60,150 C60,200 140,250 140,300 C140,350 60,400 60,450 C60,500 140,550 140,600 C140,650 60,700 60,750 C60,780 100,800 100,800" fill="none" stroke="#06B6D4" stroke-width="3"/>
          <line x1="60" y1="25" x2="140" y2="25" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="75" x2="120" y2="75" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="125" x2="140" y2="125" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="175" x2="120" y2="175" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="225" x2="140" y2="225" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="275" x2="120" y2="275" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="325" x2="140" y2="325" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="375" x2="120" y2="375" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="425" x2="140" y2="425" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="475" x2="120" y2="475" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="525" x2="140" y2="525" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="575" x2="120" y2="575" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="625" x2="140" y2="625" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="80" y1="675" x2="120" y2="675" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="60" y1="725" x2="140" y2="725" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
        </g>
      </svg>
      <div class="sequence-strip sequence-top">
        <span v-for="(base, i) in sequenceTop" :key="i" :class="'base-' + base">{{ base }}</span>
      </div>
      <div class="sequence-strip sequence-bottom">
        <span v-for="(base, i) in sequenceBottom" :key="i" :class="'base-' + base">{{ base }}</span>
      </div>
      <div class="particle" v-for="n in 20" :key="'p'+n" :style="particleStyle(n)"></div>
    </div>

    <div class="hero-section">
      <div class="hero-badge">
        <svg width="16" height="16" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M10,4 C10,8 6,10 6,16 C6,22 10,24 10,28" stroke="#5EEAD4" stroke-width="2.5" stroke-linecap="round"/>
          <path d="M22,4 C22,8 26,10 26,16 C26,22 22,24 22,28" stroke="#22D3EE" stroke-width="2.5" stroke-linecap="round"/>
          <line x1="12" y1="8" x2="20" y2="8" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="10" y1="16" x2="22" y2="16" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
          <line x1="12" y1="24" x2="20" y2="24" stroke="#5EEAD4" stroke-width="1.5" opacity="0.6"/>
        </svg>
        Bioinformatics AI Platform
      </div>
      <h1 class="title">
        <span class="title-line">鸡结构变异知识库</span>
        <span class="title-accent">ChickenSV-Agent knowledge platform</span>
      </h1>
      <p class="subtitle">
        <span>基于大语言模型的基因组数据分析助手 · 结构变异查询 · 基因型填充</span>
        <span class="subtitle-en">LLM-powered genome data analysis assistant · SV query · genotype imputation</span>
      </p>
      <a class="start-link start-btn" href="#/chat">
        <el-icon><ChatDotRound /></el-icon>
        开始对话 · Start Chat
      </a>
    </div>
    
    <div class="features">
      <div class="feature-card" v-for="feature in features" :key="feature.title">
        <div class="feature-icon-wrap" :style="{ background: feature.iconBg }">
          <el-icon class="feature-icon" :style="{ color: feature.iconColor }">
            <component :is="feature.icon" />
          </el-icon>
        </div>
        <h3>{{ feature.title }}</h3>
        <p class="feature-title-en">{{ feature.titleEn }}</p>
        <p>{{ feature.desc }}</p>
        <p class="feature-desc-en">{{ feature.descEn }}</p>
        <div class="feature-tags">
          <span v-for="(tag, idx) in feature.tags" :key="tag" class="feature-tag">
            {{ tag }}<span v-if="feature.tagsEn?.[idx]" class="tag-en"> / {{ feature.tagsEn[idx] }}</span>
          </span>
        </div>
      </div>
    </div>

    <div class="footer-info">
      <span class="gene-decoration">A</span>
      <span class="gene-decoration">T</span>
      <span class="gene-decoration">C</span>
      <span class="gene-decoration">G</span>
      <span class="footer-text">Powered by LLM · ChickenSV-Agent v1.0</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Search, DataAnalysis, ChatLineRound } from '@element-plus/icons-vue'

const features = [
  {
    icon: Search,
    title: 'SV数据查询',
    titleEn: 'SV Data Query',
    desc: '快速查询结构变异数据，支持基因、区域、ID等多种查询方式',
    descEn: 'Query structural variants by gene, genomic region, or variant ID',
    iconBg: 'linear-gradient(135deg, rgba(13, 148, 136, 0.15) 0%, rgba(6, 182, 212, 0.15) 100%)',
    iconColor: '#0D9488',
    tags: ['基因查询', '区域检索', '变异ID'],
    tagsEn: ['Gene', 'Region', 'Variant ID']
  },
  {
    icon: DataAnalysis,
    title: '基因型填充',
    titleEn: 'Genotype Imputation',
    desc: '智能数据填充工作流，支持VCF和PLINK格式的高效处理',
    descEn: 'Imputation workflow for VCF and PLINK with Beagle reference panel',
    iconBg: 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(52, 211, 153, 0.15) 100%)',
    iconColor: '#10B981',
    tags: ['VCF', 'PLINK', 'Beagle'],
    tagsEn: ['VCF', 'PLINK', 'Beagle']
  },
  {
    icon: ChatLineRound,
    title: '智能对话',
    titleEn: 'AI Assistant',
    desc: '自然语言交互，实时响应，支持多轮对话与工具调用',
    descEn: 'Natural-language chat with streaming responses and tool integration',
    iconBg: 'linear-gradient(135deg, rgba(6, 182, 212, 0.15) 0%, rgba(34, 211, 238, 0.15) 100%)',
    iconColor: '#06B6D4',
    tags: ['多轮对话', '工具调用', '实时流式'],
    tagsEn: ['Multi-turn', 'Tools', 'Streaming']
  }
]

const bases = ['A', 'T', 'C', 'G']
const sequenceTop = ref(Array.from({ length: 60 }, () => bases[Math.floor(Math.random() * 4)]))
const sequenceBottom = ref(Array.from({ length: 60 }, () => bases[Math.floor(Math.random() * 4)]))

const particleStyle = (_n: number) => {
  const x = Math.random() * 100
  const y = Math.random() * 100
  const size = 2 + Math.random() * 4
  const delay = Math.random() * 8
  const duration = 6 + Math.random() * 10
  return {
    left: `${x}%`,
    top: `${y}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `${delay}s`,
    animationDuration: `${duration}s`
  }
}
</script>

<style scoped>
.home-view {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 40px;
  background: #ffffff;
  position: relative;
  overflow-x: hidden;
  overflow-y: auto;
}

.dna-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.dna-helix {
  position: absolute;
  width: 200px;
  height: 100%;
}

.dna-left {
  left: 5%;
  top: 0;
  animation: helixFloat 20s ease-in-out infinite;
}

.dna-right {
  right: 5%;
  top: 0;
  animation: helixFloat 25s ease-in-out infinite reverse;
}

@keyframes helixFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-30px); }
}

.sequence-strip {
  position: absolute;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: 4px;
  opacity: 0.08;
  user-select: none;
}

.sequence-top {
  top: 8%;
  left: 15%;
}

.sequence-bottom {
  bottom: 8%;
  right: 15%;
}

.base-A { color: #0D9488; }
.base-T { color: #F59E0B; }
.base-C { color: #8B5CF6; }
.base-G { color: #EF4444; }

.particle {
  position: absolute;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(94, 234, 212, 0.28) 0%, transparent 70%);
  animation: particleFloat 8s ease-in-out infinite;
}

@keyframes particleFloat {
  0%, 100% { transform: translateY(0) scale(1); opacity: 0.3; }
  50% { transform: translateY(-20px) scale(1.2); opacity: 0.6; }
}

.hero-section {
  text-align: center;
  color: #0F172A;
  margin-bottom: 60px;
  position: relative;
  z-index: 1;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  background: rgba(13, 148, 136, 0.15);
  border: 1px solid rgba(13, 148, 136, 0.3);
  border-radius: 20px;
  font-size: 13px;
  color: #0D9488;
  margin-bottom: 24px;
  letter-spacing: 0.5px;
}

.title {
  font-size: 56px;
  font-weight: 700;
  margin-bottom: 20px;
  line-height: 1.2;
  letter-spacing: -1px;
}

.title-line {
  display: block;
  color: #0F172A;
}

.title-accent {
  display: block;
  background: linear-gradient(135deg, #14B8A6 0%, #06B6D4 50%, #5EEAD4 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.subtitle {
  font-size: 17px;
  margin-bottom: 40px;
  color: #64748B;
  font-weight: 300;
  letter-spacing: 0.5px;
}

.subtitle span {
  display: block;
}

.subtitle-en {
  margin-top: 8px;
  font-size: 14px;
  color: #94A3B8;
  letter-spacing: 0.2px;
}

.start-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-decoration: none;
}

.start-btn {
  height: 52px;
  padding: 0 40px;
  font-size: 16px;
  font-weight: 500;
  border-radius: 26px;
  color: #ffffff !important;
  background: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%) !important;
  border: none !important;
  box-shadow: 0 10px 25px rgba(13, 148, 136, 0.16);
  transition: all 0.3s ease;
}

.start-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 30px rgba(13, 148, 136, 0.22);
}

.start-btn .el-icon {
  margin-right: 8px;
  color: #ffffff;
}

.start-btn:visited {
  color: #ffffff !important;
}

.features {
  width: 100%;
  max-width: 1200px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  position: relative;
  z-index: 1;
}

.feature-card {
  background: #ffffff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  border-radius: 16px;
  padding: 36px 28px;
  text-align: center;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.feature-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(13, 148, 136, 0.5), rgba(6, 182, 212, 0.45), transparent);
  opacity: 0;
  transition: opacity 0.4s;
}

.feature-card:hover {
  transform: translateY(-6px);
  border-color: rgba(13, 148, 136, 0.28);
  box-shadow: 0 10px 30px rgba(13, 148, 136, 0.08);
}

.feature-card:hover::before {
  opacity: 1;
}

.feature-icon-wrap {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 20px;
}

.feature-icon {
  font-size: 28px;
}

.feature-card h3 {
  font-size: 20px;
  color: #0F172A;
  margin-bottom: 4px;
  font-weight: 600;
}

.feature-title-en {
  font-size: 14px;
  color: #0D9488;
  font-weight: 500;
  margin: 0 0 12px 0;
}

.feature-card p {
  color: #64748B;
  line-height: 1.7;
  font-size: 14px;
  margin-bottom: 6px;
}

.feature-desc-en {
  color: #94A3B8;
  font-size: 13px;
  line-height: 1.6;
  margin-bottom: 16px;
}

.tag-en {
  opacity: 0.75;
  font-size: 11px;
}

.feature-tags {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}

.feature-tag {
  padding: 3px 10px;
  background: rgba(13, 148, 136, 0.06);
  border: 1px solid rgba(13, 148, 136, 0.14);
  border-radius: 12px;
  font-size: 12px;
  color: #0D9488;
}

.footer-info {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 1;
  margin-top: 28px;
  padding-bottom: 20px;
}

.gene-decoration {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
}

.gene-decoration:nth-child(1) { background: rgba(13, 148, 136, 0.2); color: #14B8A6; }
.gene-decoration:nth-child(2) { background: rgba(245, 158, 11, 0.2); color: #F59E0B; }
.gene-decoration:nth-child(3) { background: rgba(139, 92, 246, 0.2); color: #8B5CF6; }
.gene-decoration:nth-child(4) { background: rgba(239, 68, 68, 0.2); color: #EF4444; }

.footer-text {
  font-size: 12px;
  color: #64748B;
  margin-left: 8px;
}
</style>
