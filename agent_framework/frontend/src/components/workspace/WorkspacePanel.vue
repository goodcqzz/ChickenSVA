<template>
  <div class="workspace-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        <el-icon v-if="workspaceType === 'query'"><Search /></el-icon>
        <el-icon v-else-if="workspaceType === 'imputation'"><DataAnalysis /></el-icon>
        <el-icon v-else><FolderOpened /></el-icon>
        {{ panelTitle }}
      </h3>
      <el-tag v-if="workspaceType === 'imputation'" size="small" type="info">Single file ≤ 5MB</el-tag>
    </div>

    <div class="panel-content">
      <!-- 工作区信息 -->
      <div class="workspace-info">
        <el-tag type="info" size="small">ID: {{ workspaceId }}</el-tag>
        <el-tag :type="workspaceType === 'imputation' ? 'warning' : 'success'" size="small">
          {{ workspaceType === 'imputation' ? 'Imputation' : 'Data Query' }}
        </el-tag>
      </div>

      <!-- 数据查询工作区 -->
      <template v-if="workspaceType === 'query'">
        <div class="query-workspace">
          <div class="workspace-intro">
            <el-icon class="intro-icon"><Search /></el-icon>
            <h4>SV Data Query</h4>
            <p>Query structural variants by gene, genomic region, or variant ID</p>
          </div>

          <div class="query-form">
            <el-form label-position="top">
              <el-form-item label="Query Type">
                <el-radio-group v-model="queryType">
                  <el-radio-button label="gene">Gene</el-radio-button>
                  <el-radio-button label="region">Region</el-radio-button>
                  <el-radio-button label="id">Variant ID</el-radio-button>
                </el-radio-group>
              </el-form-item>

              <el-form-item :label="queryTypeLabel">
                <el-input v-model="queryValue" :placeholder="queryPlaceholder" clearable />
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="executeQuery" :loading="queryLoading">
                  <el-icon><Search /></el-icon>
                  Run Query
                </el-button>
              </el-form-item>
            </el-form>
          </div>

          <div v-if="queryExecuted" class="query-results">
            <div class="results-header">
              <h5>Results (showing {{ queryResults.length }} / {{ queryTotal }} total)</h5>
              <el-tag v-if="queryHasMore" size="small" type="warning">Large result set — paginated</el-tag>
            </div>

            <el-empty v-if="queryResults.length === 0" description="No matches — check your query" />

            <el-table
              v-else
              :data="queryResults"
              height="300"
              highlight-current-row
              :row-class-name="getQueryRowClass"
              @row-click="handleQueryRowClick"
            >
              <el-table-column prop="id" label="ID" width="180" />
              <el-table-column prop="chr" label="Chr" width="90" />
              <el-table-column prop="pos" label="Start" width="110" />
              <el-table-column prop="type" label="Type" width="90" />
              <el-table-column prop="mean_frequency" label="Mean Freq." width="100" />
              <el-table-column prop="gene" label="Gene" min-width="150" />
            </el-table>

            <div v-if="queryBreedFrequencies.length > 0" class="query-frequency-detail">
              <div class="query-summary-header">
                <h5>Breed Frequency Details</h5>
                <span class="summary-note">Selected: {{ querySelectedVariantLabel }}</span>
              </div>
              <el-table :data="queryBreedFrequencies" size="small" height="240">
                <el-table-column prop="breed" label="Breed" min-width="180" />
                <el-table-column prop="frequency" label="Frequency" width="100" :formatter="formatFrequency" />
              </el-table>
              <p class="summary-observation query-selection-tip">Click any row in the results table above to view breed frequencies for that SV.</p>
            </div>

            <div v-if="queryDefaultSummary" class="query-summary">
              <h5>Summary by Domestication Level</h5>
              <p class="summary-observation">{{ queryDefaultSummary.observation || 'No grouped observation available' }}</p>
              <el-table :data="queryDefaultSummary.groups || []" size="small" stripe>
                <el-table-column prop="category" label="Category" width="110" />
                <el-table-column prop="breed_count" label="Breeds" width="90" />
                <el-table-column prop="mean_frequency" label="Mean Freq." width="100" />
                <el-table-column prop="high_frequency_breed_count" label="High-Freq. Breeds" width="110" />
              </el-table>
            </div>
          </div>
        </div>
      </template>

      <!-- 数据填充工作区 -->
      <template v-else-if="workspaceType === 'imputation'">
        <div class="imputation-workspace">
          <!-- 步骤1: 上传 -->
          <div v-if="currentStep === 0" class="step-content">
            <div class="upload-area">
              <el-upload
                drag
                :action="uploadUrl"
                :on-success="handleUploadSuccess"
                :on-error="handleUploadError"
                :before-upload="beforeUpload"
                accept=".vcf,.vcf.gz,.bed,.bim,.fam"
                :auto-upload="true"
                :data="{ description: 'Genotype data' }"
                name="file"
              >
                <el-icon class="upload-icon"><Upload /></el-icon>
                <div class="upload-text">
                  Drop file here or <em>click to upload</em>
                </div>
                <template #tip>
                  <div class="upload-tip">
                    <p>Supports VCF / PLINK — <strong>single file up to 5MB</strong> (demo-sized samples)</p>
                  </div>
                </template>
              </el-upload>
            </div>

            <div v-if="uploadedFiles.length > 0" class="uploaded-files">
              <h5>Uploaded Files</h5>
              <div v-for="file in uploadedFiles" :key="file.filename" class="file-item">
                <el-icon><Document /></el-icon>
                <span class="file-name">{{ file.filename }}</span>
                <span class="file-size">{{ formatFileSize(file.file_size) }}</span>
                <el-tag type="success" size="small">Uploaded</el-tag>
              </div>
              <el-button type="primary" size="small" @click="currentStep = 1" style="margin-top: 12px">
                Next: Validate File
              </el-button>
            </div>

            <div class="upload-info">
              <el-alert title="Note" type="info" :closable="false">
                <p>One conversation maps to one workspace. After submitting an imputation job, ask the Agent about workspace status in chat to check results.</p>
              </el-alert>
            </div>
          </div>

          <!-- 步骤2: 验证 -->
          <div v-else-if="currentStep === 1" class="step-content">
            <div v-if="validating" class="validating-state">
              <el-icon class="thinking-icon"><Loading /></el-icon>
              <span>Validating file...</span>
            </div>
            <el-result
              v-else
              :icon="validationResult.is_valid ? 'success' : 'error'"
              :title="validationResult.is_valid ? 'Validation passed' : 'Validation failed'"
              :sub-title="validationResult.is_valid ? 'Ready to submit imputation job' : 'Check file format and re-upload'"
            >
              <template #extra>
                <el-button v-if="validationResult.is_valid" type="primary" :loading="submitting" @click="startImputation">
                  Submit Imputation Job
                </el-button>
                <el-button @click="currentStep = 0">Re-upload</el-button>
              </template>
              <template v-if="validationResult.errors.length > 0 || validationResult.warnings.length > 0" #sub-title>
                <div class="validation-details">
                  <div v-for="err in validationResult.errors" :key="err" class="validation-error">
                    <el-icon color="#f56c6c"><CircleClose /></el-icon> {{ err }}
                  </div>
                  <div v-for="warn in validationResult.warnings" :key="warn" class="validation-warning">
                    <el-icon color="#e6a23c"><Warning /></el-icon> {{ warn }}
                  </div>
                </div>
              </template>
            </el-result>
          </div>

          <!-- 步骤3: 已提交 -->
          <div v-else-if="currentStep === 2" class="step-content">
            <el-result
              :icon="imputeStatus === 'failed' ? 'error' : imputeStatus === 'completed' ? 'success' : 'info'"
              :title="imputeStatusTitle"
              :sub-title="imputeStatusDetail"
            >
              <template #extra>
                <el-button v-if="imputeStatus === 'completed'" type="primary" @click="downloadResult">
                  <el-icon><Download /></el-icon>
                  Download Results
                </el-button>
                <el-button @click="resetImputation">Re-upload</el-button>
              </template>
            </el-result>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import {
  Search, DataAnalysis, FolderOpened, Upload,
  Download, Document, Loading, CircleClose, Warning
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

interface Props {
  workspaceId: string
  workspaceType: 'query' | 'imputation' | null
  workspaceAction?: string
}

const props = defineProps<Props>()

defineEmits<{
  close: []
}>()

const panelTitle = computed(() => {
  const titles: Record<string, string> = {
    query: 'Data Query Workspace',
    imputation: 'Imputation Workspace'
  }
  return titles[props.workspaceType || ''] || 'Workspace'
})

const uploadUrl = computed(() => {
  return `/api/v1/workspaces/${props.workspaceId}/upload`
})

watch(() => props.workspaceAction, (action) => {
  if (action === 'request_upload' && props.workspaceType === 'imputation') {
    currentStep.value = 0
    nextTick(() => {
      const uploadEl = document.querySelector('.upload-area .el-upload')
      if (uploadEl) {
        uploadEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
    ElMessage({
      message: 'Please upload your data file in the workspace panel on the right',
      type: 'warning',
      duration: 5000,
      showClose: true,
    })
  }
})

watch(() => props.workspaceId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    resetImputationState()
    if (props.workspaceType === 'imputation') {
      loadWorkspaceSnapshot()
    }
  }
})

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

// ========== 数据查询 ==========
const queryType = ref('gene')
const queryValue = ref('')
const queryLoading = ref(false)
const queryResults = ref<any[]>([])
const queryTotal = ref(0)
const queryHasMore = ref(false)
const queryExecuted = ref(false)
const queryDefaultSummary = ref<any | null>(null)
const queryBreedFrequencies = ref<{ breed: string; frequency: number }[]>([])
const selectedQueryIndex = ref(0)
const querySelectedVariantLabel = computed(() => {
  const selected = queryResults.value[selectedQueryIndex.value]
  if (!selected) {
    return 'No SV selected'
  }
  const parts = [`${selected.id}`]
  if (selected.chr) {
    parts.push(`Chr${selected.chr}`)
  }
  if (selected.pos !== '' && selected.pos !== undefined && selected.pos !== null) {
    parts.push(String(selected.pos))
  }
  if (selected.type) {
    parts.push(selected.type)
  }
  return parts.join(' · ')
})

const formatFrequency = (_row: any, _column: any, cellValue: any) => {
  const value = Number(cellValue)
  return Number.isFinite(value) ? value.toFixed(4) : cellValue ?? '-'
}

const syncQueryBreedFrequencies = (index: number) => {
  selectedQueryIndex.value = index
  const selected = queryResults.value[index]
  const breedFrequencies = selected?.breed_frequencies
  if (breedFrequencies && typeof breedFrequencies === 'object') {
    queryBreedFrequencies.value = Object.entries(breedFrequencies)
      .map(([breed, frequency]) => ({
        breed,
        frequency: typeof frequency === 'number' ? frequency : Number(frequency),
      }))
      .filter((item) => Number.isFinite(item.frequency))
      .sort((left, right) => right.frequency - left.frequency)
    return
  }
  queryBreedFrequencies.value = []
}

const handleQueryRowClick = (row: any) => {
  const index = typeof row.__index === 'number' ? row.__index : 0
  syncQueryBreedFrequencies(index)
}

const getQueryRowClass = ({ row }: { row: any }) => {
  return row.__index === selectedQueryIndex.value ? 'is-selected-query-row' : ''
}

const queryTypeLabel = computed(() => {
  const labels: Record<string, string> = { gene: 'Gene Name', region: 'Genomic Region', id: 'Variant ID' }
  return labels[queryType.value]
})

const queryPlaceholder = computed(() => {
  const placeholders: Record<string, string> = {
    gene: 'e.g. BRCA1, TP53',
    region: 'e.g. chr27:3000000-3500000 or 27:3000000-3500000',
    id: 'e.g. 27_3284400_INS'
  }
  return placeholders[queryType.value]
})

const executeQuery = async () => {
  const value = queryValue.value.trim()
  if (!value) {
    ElMessage.warning('Please enter a query value')
    return
  }

  queryLoading.value = true
  queryExecuted.value = true
  queryDefaultSummary.value = null
  queryBreedFrequencies.value = []
  selectedQueryIndex.value = 0

  try {
    const resp = await axios.post(`/api/v1/workspaces/${props.workspaceId}/query`, {
      query_type: queryType.value,
      query_value: value,
      limit: 50,
    })

    const data = resp.data || {}
    const rows = Array.isArray(data.results) ? data.results : []

    queryResults.value = rows.map((row: any, index: number) => ({
      __index: index,
      id: row.id || '',
      chr: row.chr || '',
      pos: row.pos ?? '',
      type: row.type || '',
      gene: row.gene || '-',
      mean_frequency: row.mean_frequency ?? '-',
      breed_frequencies: row.breed_frequencies || null,
    }))

    queryTotal.value = Number(data.total ?? queryResults.value.length)
    queryHasMore.value = Boolean(data.has_more)

    syncQueryBreedFrequencies(0)

    const defaultSummary = data.default_summary?.content
    if (defaultSummary && typeof defaultSummary === 'object') {
      queryDefaultSummary.value = defaultSummary
    }

    if (queryResults.value.length === 0) {
      ElMessage.warning('No matches — check your query')
    } else {
      ElMessage.success(`Query complete — ${queryTotal.value} match(es)`)
    }
  } catch (e: any) {
    queryResults.value = []
    queryTotal.value = 0
    queryHasMore.value = false
    queryDefaultSummary.value = null
    queryBreedFrequencies.value = []
    selectedQueryIndex.value = 0
    ElMessage.error('Query failed: ' + (e.response?.data?.detail || e.message))
  } finally {
    queryLoading.value = false
  }
}

// ========== 数据填充 ==========
const currentStep = ref(0)
const uploadedFiles = ref<{ filename: string; file_size: number; file_path: string }[]>([])
const validating = ref(false)
const submitting = ref(false)
const imputeStatus = ref<'submitted' | 'completed' | 'failed'>('submitted')
const imputeStatusDetail = ref('')
const validationResult = ref<{ is_valid: boolean; errors: string[]; warnings: string[] }>({
  is_valid: false,
  errors: [],
  warnings: [],
})

const imputeStatusTitle = computed(() => {
  if (imputeStatus.value === 'completed') return 'Imputation complete'
  if (imputeStatus.value === 'failed') return 'Imputation failed'
  return 'Imputation job submitted'
})

const resetImputationState = () => {
  uploadedFiles.value = []
  currentStep.value = 0
  submitting.value = false
  imputeStatus.value = 'submitted'
  imputeStatusDetail.value = ''
  validationResult.value = { is_valid: false, errors: [], warnings: [] }
  queryResults.value = []
  queryTotal.value = 0
  queryHasMore.value = false
  queryExecuted.value = false
  queryDefaultSummary.value = null
  queryBreedFrequencies.value = []
}

const loadWorkspaceSnapshot = async () => {
  try {
    const resp = await axios.get(`/api/v1/workspaces/${props.workspaceId}/status`)
    const data = resp.data || {}
    const inputFiles: string[] = data.input_files || []
    if (inputFiles.length > 0) {
      uploadedFiles.value = inputFiles.map((name: string) => ({
        filename: name,
        file_size: 0,
        file_path: '',
      }))
      if (data.status === 'completed') {
        currentStep.value = 2
        imputeStatus.value = 'completed'
        imputeStatusDetail.value = 'Output files detected — results ready to download.'
      } else if (data.status === 'failed') {
        currentStep.value = 2
        imputeStatus.value = 'failed'
        imputeStatusDetail.value = 'Previous imputation failed. Try a smaller test file.'
      } else if (data.status === 'data_uploaded' || data.status === 'running') {
        currentStep.value = uploadedFiles.value.length > 0 ? 1 : 0
      }
    }
  } catch {
    // ignore
  }
}

const beforeUpload = (file: File) => {
  const validExts = ['.vcf', '.vcf.gz', '.bed', '.bim', '.fam']
  const fileName = file.name.toLowerCase()
  const isValid = validExts.some(ext => fileName.endsWith(ext))
  if (!isValid) {
    ElMessage.error('Unsupported format — upload VCF or PLINK files')
    return false
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    ElMessage.error('File size cannot exceed 5MB')
    return false
  }
  return true
}

const handleUploadSuccess = (response: any) => {
  if (response.success) {
    uploadedFiles.value.push({
      filename: response.filename,
      file_size: response.file_size,
      file_path: response.file_path,
    })
    ElMessage.success(`File ${response.filename} uploaded`)
  } else {
    ElMessage.error('Upload failed')
  }
}

const handleUploadError = (error: any) => {
  const detail = error?.message || 'Upload failed — please retry'
  ElMessage.error(detail)
  console.error('上传错误:', error)
}

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

const validateFiles = async () => {
  validating.value = true
  try {
    const resp = await axios.post(`/api/v1/workspaces/${props.workspaceId}/validate`)
    const data = resp.data
    validationResult.value = {
      is_valid: data.validation_result.is_valid,
      errors: data.validation_result.errors || [],
      warnings: data.validation_result.warnings || [],
    }
  } catch (e) {
    validationResult.value = {
      is_valid: false,
      errors: ['Validation request failed'],
      warnings: [],
    }
  } finally {
    validating.value = false
  }
}

watch(currentStep, (newStep) => {
  if (newStep === 1) {
    validateFiles()
  }
})

const startImputation = async () => {
  submitting.value = true
  try {
    const resp = await axios.post(`/api/v1/workspaces/${props.workspaceId}/impute`, null, {
      params: { ref_panel: 'default', nthreads: 2 },
    })

    currentStep.value = 2
    if (resp.data.success === false || resp.data.status === 'error') {
      imputeStatus.value = 'failed'
      imputeStatusDetail.value = resp.data.detail || resp.data.error || resp.data.message || 'Failed to start'
      return
    }

    imputeStatus.value = 'submitted'
    imputeStatusDetail.value =
      'Job is running in the background. Ask about workspace status in chat — no need to wait here.'
    ElMessage.success('Imputation job submitted')
  } catch (e: any) {
    currentStep.value = 2
    imputeStatus.value = 'failed'
    imputeStatusDetail.value = e.response?.data?.detail || e.message
  } finally {
    submitting.value = false
  }
}

const downloadResult = async () => {
  try {
    const statusResp = await axios.get(`/api/v1/workspaces/${props.workspaceId}/status`)
    const outputFiles = statusResp.data.output_files || []
    if (outputFiles.length === 0) {
      ElMessage.warning('No result files available for download')
      return
    }
    for (const filename of outputFiles) {
      const link = document.createElement('a')
      link.href = `/api/v1/workspaces/${props.workspaceId}/download/${encodeURIComponent(filename)}`
      link.download = filename
      link.click()
    }
    ElMessage.success(`Downloading ${outputFiles.length} result file(s)`)
  } catch (e: any) {
    ElMessage.error('Download failed: ' + (e.response?.data?.detail || e.message))
  }
}

const resetImputation = () => {
  resetImputationState()
}

onMounted(() => {
  if (props.workspaceType === 'imputation' && props.workspaceId) {
    loadWorkspaceSnapshot()
  }
})
</script>

<style scoped>
.workspace-panel {
  width: 420px;
  background: rgba(15, 23, 42, 0.95);
  backdrop-filter: blur(12px);
  border-left: 1px solid rgba(13, 148, 136, 0.15);
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(13, 148, 136, 0.15);
  background: linear-gradient(135deg, #0D9488 0%, #06B6D4 100%);
  color: white;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.workspace-info {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.query-workspace {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.workspace-intro {
  text-align: center;
  padding: 20px;
  background: rgba(13, 148, 136, 0.08);
  border: 1px solid rgba(13, 148, 136, 0.15);
  border-radius: 12px;
}

.intro-icon {
  font-size: 48px;
  color: #14B8A6;
  margin-bottom: 12px;
}

.workspace-intro h4 { margin: 0 0 8px 0; color: #E2E8F0; }
.workspace-intro p { margin: 0; color: #94A3B8; font-size: 14px; }

.query-form {
  padding: 16px;
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(30, 58, 95, 0.5);
  border-radius: 10px;
}

.query-form :deep(.el-form-item__label) {
  color: #94A3B8;
}

.query-form :deep(.el-input__wrapper) {
  background: rgba(15, 23, 42, 0.8);
  border-color: rgba(30, 58, 95, 0.5);
  box-shadow: none;
}

.query-form :deep(.el-input__inner) {
  color: #E2E8F0;
}

.query-results { margin-top: 20px; }
.results-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.results-header h5 { margin: 0; color: #E2E8F0; }

.query-summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.query-summary-header h5 {
  margin: 0;
  color: #99F6E4;
}

.summary-note {
  font-size: 12px;
  color: #94A3B8;
}

.query-frequency-detail {
  margin-top: 16px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid rgba(13, 148, 136, 0.18);
  border-radius: 10px;
}

.query-summary {
  margin-top: 16px;
  padding: 12px;
  background: rgba(13, 148, 136, 0.08);
  border: 1px solid rgba(13, 148, 136, 0.2);
  border-radius: 10px;
}

.query-summary h5 {
  margin: 0 0 8px 0;
  color: #99F6E4;
}

.summary-observation {
  margin: 0 0 10px 0;
  color: #CBD5E1;
  font-size: 13px;
}

.query-selection-tip {
  margin-top: 10px;
}

.query-results :deep(.el-table) {
  --el-table-bg-color: rgba(15, 23, 42, 0.6);
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(13, 148, 136, 0.15);
  --el-table-row-hover-bg-color: rgba(20, 184, 166, 0.08);
  --el-table-border-color: rgba(30, 58, 95, 0.5);
  --el-table-text-color: #E2E8F0;
  --el-table-header-text-color: #5EEAD4;
}

.query-results :deep(.el-table__body tr > td.el-table__cell) {
  background-color: rgba(15, 23, 42, 0.72);
  color: #E2E8F0;
  border-bottom-color: rgba(30, 58, 95, 0.35);
}

.query-results :deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: rgba(20, 184, 166, 0.08) !important;
}

.query-results :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background-color: rgba(20, 184, 166, 0.18) !important;
  color: #F8FAFC !important;
}

.query-results :deep(.el-table__body tr.current-row > td.el-table__cell .cell) {
  color: #F8FAFC !important;
}

.imputation-workspace { display: flex; flex-direction: column; gap: 20px; }
.step-content { padding: 20px 0; }

.upload-area { margin-bottom: 20px; }
.upload-icon { font-size: 48px; color: #14B8A6; margin-bottom: 16px; }
.upload-text { color: #94A3B8; font-size: 14px; }
.upload-text em { color: #14B8A6; font-style: normal; }

.upload-tip {
  margin-top: 16px;
  padding: 12px;
  background: rgba(13, 148, 136, 0.06);
  border: 1px solid rgba(13, 148, 136, 0.15);
  border-radius: 8px;
  font-size: 13px;
  color: #94A3B8;
}
.upload-tip ul { margin: 8px 0 0 0; padding-left: 20px; }
.upload-tip li { margin: 4px 0; }

.uploaded-files {
  margin-top: 16px;
  padding: 12px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 8px;
}
.uploaded-files h5 { margin: 0 0 10px 0; color: #34D399; font-size: 14px; }
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  color: #CBD5E1;
}
.file-name { flex: 1; color: #E2E8F0; }
.file-size { color: #64748B; font-size: 12px; }

.upload-info { margin-top: 16px; }

.validating-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: #14B8A6;
  font-size: 16px;
}
.thinking-icon { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.validation-details { text-align: left; margin-top: 8px; }
.validation-error { color: #FCA5A5; font-size: 13px; margin: 4px 0; display: flex; align-items: center; gap: 4px; }
.validation-warning { color: #FCD34D; font-size: 13px; margin: 4px 0; display: flex; align-items: center; gap: 4px; }

.progress-area { text-align: center; padding: 20px; }
.progress-area h4 { margin-bottom: 20px; color: #E2E8F0; }
.progress-detail { margin-top: 12px; color: #94A3B8; }

.progress-log {
  margin-top: 24px;
  text-align: left;
  border: 1px solid rgba(30, 58, 95, 0.5);
  border-radius: 8px;
  overflow: hidden;
}
.log-header {
  background: rgba(13, 148, 136, 0.1);
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  color: #5EEAD4;
  border-bottom: 1px solid rgba(30, 58, 95, 0.5);
}
.log-content { max-height: 200px; overflow-y: auto; padding: 12px; background: rgba(15, 23, 42, 0.6); }
.log-item { margin: 6px 0; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.log-time { color: #475569; margin-right: 12px; }
.log-message { color: #94A3B8; }
</style>
