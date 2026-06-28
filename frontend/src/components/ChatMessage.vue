<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->
<template>
  <div
    class="flex chat-message"
    :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
  >
    <div
      class="rounded-2xl px-6 py-4 shadow-sm"
      :class="[messageClasses, message.role === 'user' ? 'max-w-3xl' : 'max-w-[85%] lg:max-w-5xl']"
    >
      <!-- User Message -->
      <div v-if="message.role === 'user'" class="text-gray-800 dark:text-gray-100">
        <div class="flex items-start gap-3">
          <div class="flex-1">
            <p class="whitespace-pre-wrap">{{ message.content }}</p>

            <!-- Attachment chips -->
            <div v-if="parsedAttachments.length > 0" class="mt-2 flex flex-wrap gap-2">
              <div
                v-for="(att, idx) in parsedAttachments"
                :key="idx"
                class="flex items-center gap-2 px-3 py-1.5 bg-white dark:bg-gray-600 rounded-lg text-xs border border-gray-200 dark:border-gray-500"
              >
                <img
                  v-if="att.is_image && att.file_url"
                  :src="att.file_url"
                  :alt="att.file_name"
                  class="w-8 h-8 rounded object-cover"
                />
                <FileText v-else :size="16" />
                <span class="truncate max-w-[120px]">{{ att.file_name }}</span>
              </div>
            </div>
          </div>
          <img
            v-if="userInfo?.avatar"
            :src="userInfo.avatar"
            :alt="userInfo.fullname || 'User'"
            class="w-10 h-10 rounded-full object-cover flex-shrink-0"
          />
          <div
            v-else
            class="w-10 h-10 rounded-full bg-gray-300 dark:bg-gray-500 text-gray-700 dark:text-gray-200 flex items-center justify-center text-sm font-semibold flex-shrink-0"
          >
            {{ userInitials }}
          </div>
        </div>
      </div>

      <!-- Assistant Message -->
      <div v-else class="text-gray-800 dark:text-gray-200">
        <div class="flex items-start gap-3">
          <img
            :src="logoSvg"
            alt="AI"
            class="w-6 h-6 rounded-full flex-shrink-0"
          />
          <div class="flex-1">
            <!-- Markdown Content -->
            <div
              v-html="renderedContent"
              class="markdown-body prose prose-sm max-w-none"
            ></div>

            <!-- Safety net: avoid a fully blank bubble when content strips to
                 nothing and no visual section will render either. -->
            <div
              v-if="!hasAnyVisibleSection"
              class="text-sm italic text-gray-500 dark:text-gray-400"
            >
              No response content was generated. Please try rephrasing your question or check the Error Log.
            </div>

            <!-- BI Cards from tool results -->
            <BiCards
              v-for="(bi, idx) in biCardsData"
              :key="'bi-' + idx"
              :cards="bi.cards"
              :currency="bi.currency"
            />

            <!-- Charts from tool results -->
            <ChartMessage
              v-for="(chart, idx) in chartData"
              :key="'chart-' + idx"
              :echart-option="chart.echart_option"
              :raw-data="chart.data"
            />

            <!-- Hierarchical Tables from tool results -->
            <HierarchicalTable
              v-for="(table, idx) in hierarchicalTables"
              :key="'htable-' + idx"
              :headers="table.headers"
              :rows="table.rows"
            />

            <!-- Confirmation Cards from propose_* tool results (Phase 13B) -->
            <ConfirmationCard
              v-for="(conf, idx) in confirmationData"
              :key="'conf-' + idx"
              :confirmation-id="conf.confirmation_id"
              :action="conf.action"
              :doctype="conf.doctype"
              :name="conf.name"
              :display-fields="conf.display_fields || []"
              :child-tables="conf.child_tables || []"
              :warnings="conf.warnings || []"
              :errors="conf.errors || []"
              :is-submittable="conf.is_submittable || false"
              :prerequisites="conf.prerequisites || null"
              :item-mapping="conf.item_mapping || []"
              :expires-at="conf.expires_at || null"
              :initial-state="getConfirmationInitialState(conf.confirmation_id)"
              :initial-result="getConfirmationInitialResult(conf.confirmation_id)"
              :initial-undo-token="getConfirmationUndoToken(conf.confirmation_id)"
              :initial-undo-expires="getConfirmationUndoExpires(conf.confirmation_id)"
            />

            <!-- Read-Only Tool Calls Display -->
            <div v-if="readToolCalls.length > 0" class="mt-4">
              <div class="flex items-start gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                <Wrench :size="16" class="text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm font-medium text-blue-900 dark:text-blue-300 mb-1">
                    Used ERPNext Tools
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <span
                      v-for="(tool, index) in readToolCalls"
                      :key="index"
                      class="inline-flex items-center px-2 py-1 bg-blue-100 dark:bg-blue-800/40 text-blue-700 dark:text-blue-300 rounded text-xs font-medium"
                    >
                      {{ getToolName(tool) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Write Operation Tool Calls Display -->
            <div v-if="writeToolCalls.length > 0" class="mt-4">
              <div class="flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                <PenSquare :size="16" class="text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm font-medium text-amber-900 dark:text-amber-300 mb-1">
                    Document Operations Performed
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <span
                      v-for="(tool, index) in writeToolCalls"
                      :key="index"
                      class="inline-flex items-center px-2 py-1 bg-amber-100 dark:bg-amber-800/40 text-amber-700 dark:text-amber-300 rounded text-xs font-medium"
                    >
                      {{ getToolName(tool, true) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Token Usage, Voice & PDF Export -->
            <div class="mt-3 flex items-center gap-3">
              <span v-if="message.tokens_used" class="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded text-xs">
                {{ message.tokens_used }} tokens
              </span>
              <button
                v-if="voiceOutput.isSupported.value"
                @click="voiceOutput.toggle(message.content)"
                class="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded transition-colors"
                :title="voiceOutput.isSpeaking.value ? 'Stop speaking' : 'Read aloud'"
              >
                <VolumeX v-if="voiceOutput.isSpeaking.value" :size="14" class="text-blue-600" />
                <Volume2 v-else :size="14" />
                <span>{{ voiceOutput.isSpeaking.value ? 'Stop' : 'Listen' }}</span>
              </button>
              <button
                v-if="message.name"
                @click="handleDownloadPdf"
                :disabled="isExporting"
                class="inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Download as PDF"
              >
                <Loader2 v-if="isExporting" :size="14" class="animate-spin" />
                <Download v-else :size="14" />
                <span>{{ isExporting ? 'Exporting...' : 'PDF' }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, inject } from 'vue'
import { Wrench, PenSquare, Volume2, VolumeX, FileText, Download, Loader2 } from 'lucide-vue-next'
import { renderMarkdown } from '../utils/markdown'
import { useVoiceOutput } from '../composables/useVoiceOutput'
import { chatAPI } from '../utils/api'
import ChartMessage from './charts/ChartMessage.vue'
import BiCards from './charts/BiCards.vue'
import HierarchicalTable from './charts/HierarchicalTable.vue'
import ConfirmationCard from './ConfirmationCard.vue'

const logoSvg = inject('logoSvg')

const voiceOutput = useVoiceOutput()
const isExporting = ref(false)

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
  userInfo: {
    type: Object,
    default: () => ({ fullname: '', avatar: '' }),
  },
})

// Compute user initials from fullname (e.g. "Sanjay Kumar" → "SK")
const userInitials = computed(() => {
  const name = props.userInfo?.fullname || ''
  if (!name) return 'U'
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return parts[0][0].toUpperCase()
})

// Parse attachments from message (JSON string or array)
const parsedAttachments = computed(() => {
  if (!props.message.attachments) return []
  let atts = props.message.attachments
  if (typeof atts === 'string') {
    try {
      atts = JSON.parse(atts)
    } catch {
      return []
    }
  }
  return Array.isArray(atts) ? atts : []
})

const messageClasses = computed(() => {
  if (props.message.role === 'user') {
    return 'bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600'
  }
  return 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700'
})

const renderedContent = computed(() => {
  if (props.message.role === 'assistant') {
    try {
      // Get content and ensure it's a string
      let content = props.message.content || ''
      if (typeof content !== 'string') {
        content = String(content)
      }

      // Remove any tool_calls JSON that might have leaked into content
      // This regex removes JSON-like structures that shouldn't be in the content
      content = content.replace(/\[?\s*\{\s*["']type["']:\s*["']function["']/g, '')

      // Strip markdown image tags — charts are rendered by EChartRenderer, not inline images
      content = content.replace(/!\[[^\]]*\]\([^)]+\)/g, '')

      // Strip HTML <img> tags
      content = content.replace(/<img\s[^>]*>/gi, '')

      // Strip markdown tables when HierarchicalTable component renders the data
      // (avoids duplicate table display — the component version is more compact and elegant)
      if (hierarchicalTables.value.length > 0) {
        content = content.replace(/\n*\|[^\n]+\|\n\|[-:| ]+\|\n(\|[^\n]+\|\n?)*/g, '')
      }

      // Strip fallback confirmation text when ConfirmationCard renders the interactive card
      // (avoids redundant text + card overlap)
      if (confirmationData.value.length > 0) {
        content = content
          .replace(/A confirmation card has been generated for your review\.[^\n]*/g, '')
          .replace(/Please check the details and click Save Draft or Submit to proceed\./g, '')
          .replace(/I've prepared.*?(?:review|confirm|proceed)\./gi, '')
          .trim()
      }

      return renderMarkdown(content)
    } catch (error) {
      console.error('Markdown rendering error:', error)
      return props.message.content
    }
  }
  return props.message.content
})

// Detect "fully blank bubble" — content strips to nothing AND no visual section
// will render. Used to show a graceful fallback notice instead of an empty card.
const hasAnyVisibleSection = computed(() => {
  if (props.message.role !== 'assistant') return true

  const rendered = renderedContent.value
  const hasText = typeof rendered === 'string' && rendered.replace(/<[^>]*>/g, '').trim().length > 0

  return (
    hasText
    || chartData.value.length > 0
    || biCardsData.value.length > 0
    || hierarchicalTables.value.length > 0
    || confirmationData.value.length > 0
    || readToolCalls.value.length > 0
    || writeToolCalls.value.length > 0
  )
})

// Extract chart data from tool_results
const chartData = computed(() => {
  if (!props.message.tool_results) return []

  let results = props.message.tool_results
  if (typeof results === 'string') {
    try {
      results = JSON.parse(results)
    } catch {
      return []
    }
  }

  if (!Array.isArray(results)) results = [results]

  // Extract echart_option from successful tool results
  return results
    .filter(r => r && r.success !== false && r.data?.echart_option)
    .map(r => ({
      echart_option: r.data.echart_option,
      data: r.data,
    }))
})

// Extract BI cards from tool_results
const biCardsData = computed(() => {
  if (!props.message.tool_results) return []

  let results = props.message.tool_results
  if (typeof results === 'string') {
    try {
      results = JSON.parse(results)
    } catch {
      return []
    }
  }

  if (!Array.isArray(results)) results = [results]

  return results
    .filter(r => r && r.success !== false && r.data?.bi_cards?.length > 0)
    .map(r => ({
      cards: r.data.bi_cards,
      currency: r.data.currency || '',
    }))
})

// Extract hierarchical tables from tool_results
const hierarchicalTables = computed(() => {
  if (!props.message.tool_results) return []

  let results = props.message.tool_results
  if (typeof results === 'string') {
    try {
      results = JSON.parse(results)
    } catch {
      return []
    }
  }

  if (!Array.isArray(results)) results = [results]

  return results
    .filter(r => r && r.success !== false && r.data?.hierarchical_table?.headers?.length > 0)
    .map(r => r.data.hierarchical_table)
})

// Extract confirmation card data from tool_results (Phase 13B)
const confirmationData = computed(() => {
  if (!props.message.tool_results) return []

  let results = props.message.tool_results
  if (typeof results === 'string') {
    try {
      results = JSON.parse(results)
    } catch {
      return []
    }
  }

  if (!Array.isArray(results)) results = [results]

  // Deduplicate by confirmation_id (same tool can be called in multiple rounds)
  const seen = new Set()
  return results
    .filter(r => r && r.data?.confirmation_required)
    .map(r => r.data)
    .filter(conf => {
      const key = conf.confirmation_id || `${conf.action}:${conf.doctype}:${conf.name || ''}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
})

// Parse persisted confirmation_state for page reloads (Phase 13B)
const parsedConfirmationState = computed(() => {
  if (!props.message.confirmation_state) return null
  let state = props.message.confirmation_state
  if (typeof state === 'string') {
    try {
      state = JSON.parse(state)
    } catch {
      return null
    }
  }
  return state
})

// Check if tool_calls is valid and has items
const hasValidToolCalls = computed(() => {
  const toolCalls = props.message.tool_calls
  if (!toolCalls) return false
  
  // Handle string that needs parsing
  if (typeof toolCalls === 'string') {
    try {
      const parsed = JSON.parse(toolCalls)
      return Array.isArray(parsed) && parsed.length > 0
    } catch {
      return false
    }
  }
  
  return Array.isArray(toolCalls) && toolCalls.length > 0
})

// Get valid tool calls (filter out any invalid entries and deduplicate)
const validToolCalls = computed(() => {
  if (!hasValidToolCalls.value) return []
  
  let toolCalls = props.message.tool_calls
  
  // Parse if string
  if (typeof toolCalls === 'string') {
    try {
      toolCalls = JSON.parse(toolCalls)
    } catch {
      return []
    }
  }
  
  if (!Array.isArray(toolCalls)) return []
  
  // Filter valid tools and deduplicate by name
  const validTools = toolCalls.filter(tool => 
    tool && typeof tool === 'object' && (tool.function?.name || tool.name)
  )
  
  // Deduplicate by tool name
  const seen = new Set()
  return validTools.filter(tool => {
    const name = tool.function?.name || tool.name
    if (seen.has(name)) return false
    seen.add(name)
    return true
  })
})

// Check if a tool call is a write operation (create/update/delete/propose/submit/cancel)
const isWriteOperation = (tool) => {
  const name = tool?.function?.name || tool?.name || ''
  return /^(create_|update_|delete_|propose_|submit_|cancel_)/.test(name)
}

// Split tool calls into read-only and write operations
const readToolCalls = computed(() => {
  return validToolCalls.value.filter(tool => !isWriteOperation(tool))
})

const writeToolCalls = computed(() => {
  return validToolCalls.value.filter(tool => isWriteOperation(tool))
})

// Extract tool name from tool call object
const getToolName = (tool, keepPrefix = false) => {
  if (!tool) return 'Unknown'

  // OpenAI format: tool.function.name
  if (tool.function?.name) {
    return formatToolName(tool.function.name, keepPrefix)
  }

  // Claude format: tool.name
  if (tool.name) {
    return formatToolName(tool.name, keepPrefix)
  }

  return 'Unknown Tool'
}

// Format tool name for display (e.g., "get_sales_analytics" -> "Sales Analytics")
// For write ops with keepPrefix=true: "create_lead" -> "Create Lead"
const formatToolName = (name, keepPrefix = false) => {
  if (!name || typeof name !== 'string') return 'Unknown'

  if (!keepPrefix) {
    // Remove read-only prefixes
    name = name.replace(/^(get_|search_|list_)/, '')
  }

  return name
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

// Confirmation state helpers for page reload persistence (Phase 13B)
// Supports both old single-confirmation format and new multi-key format
const _getConfirmationEntry = (confirmationId) => {
  const cs = parsedConfirmationState.value
  if (!cs) return null

  // New multi-key format: { "uuid1": { state, result, ... }, "uuid2": { ... } }
  if (cs[confirmationId]) return cs[confirmationId]

  // Old single-confirmation format: { confirmation_id, state, result, ... }
  if (cs.confirmation_id === confirmationId) return cs

  return null
}

const getConfirmationInitialState = (confirmationId) => {
  const entry = _getConfirmationEntry(confirmationId)
  if (entry?.state) {
    return entry.state === 'confirmed' ? 'success' : entry.state
  }
  return 'pending'
}

const getConfirmationInitialResult = (confirmationId) => {
  const entry = _getConfirmationEntry(confirmationId)
  return entry?.result || null
}

const getConfirmationUndoToken = (confirmationId) => {
  const entry = _getConfirmationEntry(confirmationId)
  return entry?.undo_token || null
}

const getConfirmationUndoExpires = (confirmationId) => {
  const entry = _getConfirmationEntry(confirmationId)
  return entry?.undo_expires || null
}

// PDF export handler
const handleDownloadPdf = async () => {
  if (!props.message.name || isExporting.value) return
  isExporting.value = true
  try {
    const result = await chatAPI.exportMessagePdf(props.message.name)
    if (result.success && result.file_url) {
      // Trigger browser download
      const a = document.createElement('a')
      a.href = result.file_url
      a.download = ''
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } else {
      console.error('PDF export failed:', result.error)
    }
  } catch (error) {
    console.error('PDF export error:', error)
  } finally {
    isExporting.value = false
  }
}
</script>

