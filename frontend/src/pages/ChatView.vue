<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->
<template>
  <div class="flex h-screen overflow-hidden">
    <!-- Sidebar (always visible: collapsed=icon strip, expanded=full) -->
    <div class="flex-shrink-0 transition-all duration-300 ease-in-out overflow-hidden">
      <Sidebar
        :conversations="conversations"
        :current-conversation="currentConversation"
        :sidebar-collapsed="sidebarCollapsed"
        :search-results="searchResults"
        :is-searching="isSearching"
        @new-chat="handleNewChat"
        @select-conversation="handleSelectConversation"
        @delete-conversation="handleDeleteConversation"
        @toggle-sidebar="toggleSidebar"
        @search="handleSearch"
      />
    </div>

    <!-- Main Chat Area -->
    <div class="flex-1 flex flex-col min-w-0">

      <!-- Connection lost banner (Phase 13A.3) -->
      <div
        v-if="showConnectionBanner"
        class="flex items-center justify-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-800 text-sm text-amber-800 dark:text-amber-200"
      >
        <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636a9 9 0 010 12.728M5.636 5.636a9 9 0 000 12.728M12 12h.01" />
        </svg>
        <span>Connection lost. Attempting to reconnect...</span>
      </div>

      <!-- Empty state: centered greeting + input -->
      <div
        v-if="hasNoMessages"
        class="flex-1 flex flex-col items-center justify-center px-4"
      >
        <div class="text-center mb-8">
          <img
            v-if="userInfo.avatar"
            :src="userInfo.avatar"
            :alt="userInfo.fullname || 'User'"
            class="w-24 h-24 rounded-full object-cover mx-auto mb-4"
          />
          <div
            v-else
            class="w-24 h-24 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 flex items-center justify-center text-3xl font-semibold mx-auto mb-4"
          >
            {{ greetingInitials }}
          </div>
          <h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
            Hello, {{ userInfo.fullname || 'there' }}!
          </h1>
          <p class="text-gray-500 dark:text-gray-400">How can I help you today?</p>
        </div>

        <div class="w-full max-w-2xl">
          <ChatInput
            :disabled="isLoading"
            :is-streaming="isStreaming"
            @send="handleSendMessage"
            @stop="handleStopGeneration"
            @voice-start="warmupTTS"
          />
        </div>
      </div>

      <!-- Conversation state: messages + bottom-pinned input -->
      <template v-else>
        <!-- Conversation action bar -->
        <div class="flex items-center justify-end px-4 py-2 border-b border-gray-200 dark:border-gray-700">
          <button
            v-if="currentConversation && messages.length > 0"
            @click="handleExportConversation"
            :disabled="isExportingConversation"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Export entire conversation as PDF"
          >
            <Loader2 v-if="isExportingConversation" :size="14" class="animate-spin" />
            <FileDown v-else :size="14" />
            <span>{{ isExportingConversation ? 'Exporting...' : 'Export Chat PDF' }}</span>
          </button>
        </div>

        <!-- Messages Area -->
        <div
          ref="messagesContainer"
          class="flex-1 overflow-y-auto px-4 py-6 space-y-4"
          @scroll="handleScroll"
        >
          <ChatMessage
            v-for="message in messages"
            :key="message.name || message._tempId"
            :message="message"
            :user-info="userInfo"
          />

          <!-- Streaming Message (live tokens) -->
          <div v-if="isStreaming && (streamingContent || agentPlan.length > 0 || streamToolCalls.length > 0)" class="flex justify-start">
            <div class="max-w-[85%] lg:max-w-5xl rounded-2xl px-6 py-4 shadow-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
              <div class="text-gray-800 dark:text-gray-200">
                <div class="flex items-start gap-3">
                  <img
                    :src="logoSvg"
                    alt="AI"
                    class="w-10 h-10 rounded-full flex-shrink-0"
                  />
                  <div class="flex-1">
                    <!-- Agent orchestration plan progress -->
                    <AgentThinking
                      :plan="agentPlan"
                      :auto-collapse="!!streamingContent"
                    />

                    <!-- Process step during streaming -->
                    <div v-if="processStep && agentPlan.length === 0" class="text-sm text-gray-500 dark:text-gray-400 mb-2 flex items-center gap-2">
                      <div class="w-3 h-3 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                      {{ processStep }}
                    </div>

                    <!-- Tool calls in progress (Phase 13A.2) -->
                    <ToolCallIndicator :tools="streamToolCalls" />

                    <!-- Streaming content -->
                    <div
                      v-if="streamingContent"
                      v-html="renderedStreamingContent"
                      class="markdown-body prose prose-sm max-w-none"
                    ></div>

                    <!-- Blinking caret cursor (Phase 13A.1) -->
                    <span class="streaming-cursor"></span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Typing indicator: shown while waiting for response (before streaming tokens, agent plan, or tool calls arrive) -->
          <div v-if="isLoading && !streamingContent && agentPlan.length === 0 && streamToolCalls.length === 0" class="flex justify-start">
            <div class="bg-white dark:bg-gray-800 rounded-2xl px-6 py-4 shadow-sm border border-gray-200 dark:border-gray-700 max-w-[85%] lg:max-w-5xl">
              <TypingIndicator :process-step="processStep" />
            </div>
          </div>

          <!-- Error message with retry button (Phase 13A.3) -->
          <div v-if="displayError" class="flex justify-start">
            <div class="max-w-[85%] lg:max-w-5xl rounded-2xl px-6 py-4 shadow-sm bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <div class="flex items-start gap-3">
                <div class="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-red-800/40 flex items-center justify-center">
                  <svg class="w-5 h-5 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                </div>
                <div class="flex-1">
                  <p class="text-sm font-medium text-red-800 dark:text-red-300">
                    {{ canRetry ? 'Response interrupted' : displayError }}
                  </p>
                  <p v-if="canRetry" class="text-xs text-red-600 dark:text-red-400 mt-0.5">
                    {{ displayError }}
                  </p>
                  <div class="flex items-center gap-3 mt-2">
                    <button
                      v-if="canRetry"
                      class="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors"
                      @click="handleRetry"
                    >
                      <RefreshCw :size="12" />
                      Retry
                    </button>
                    <button
                      class="text-xs text-red-600 dark:text-red-400 hover:underline"
                      @click="dismissError"
                    >Dismiss</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- "New content" pill (Phase 13A.4) -->
        <div class="relative">
          <Transition
            enter-active-class="transition duration-200 ease-out"
            enter-from-class="opacity-0 translate-y-2"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition duration-150 ease-in"
            leave-from-class="opacity-100 translate-y-0"
            leave-to-class="opacity-0 translate-y-2"
          >
            <button
              v-if="showNewContentPill"
              @click="scrollToBottomAndResume"
              class="absolute -top-12 left-1/2 -translate-x-1/2 z-10 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-full shadow-lg transition-colors"
            >
              <ArrowDown :size="12" />
              New content
            </button>
          </Transition>

          <!-- Gradient fade above input -->
          <div class="absolute -top-8 left-0 right-0 h-8 bg-gradient-to-t from-white dark:from-gray-900 to-transparent pointer-events-none"></div>
          <ChatInput
            :disabled="isLoading"
            :is-streaming="isStreaming"
            @send="handleSendMessage"
            @stop="handleStopGeneration"
            @voice-start="warmupTTS"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, provide, onMounted, onUnmounted, watch, nextTick } from 'vue'
import Sidebar from '../components/Sidebar.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import TypingIndicator from '../components/TypingIndicator.vue'
import AgentThinking from '../components/AgentThinking.vue'
import ToolCallIndicator from '../components/ToolCallIndicator.vue'
import { FileDown, Loader2, RefreshCw, ArrowDown } from 'lucide-vue-next'
import { chatAPI } from '../utils/api'
import { renderMarkdown } from '../utils/markdown'
import { useStreaming } from '../composables/useStreaming'
import { useSocket } from '../composables/useSocket'
import logoSvg from '../assets/ai_think.png'
import { useVoiceOutput } from '../composables/useVoiceOutput'

// Provide the assistant avatar to descendant components (ChatMessage,
// TypingIndicator, streaming preview). Sidebar uses its own logo.png.
provide('logoSvg', logoSvg)

const conversations = ref([])
const currentConversation = ref(null)
const messages = ref([])
const isLoading = ref(false)
const selectedProvider = ref('OpenAI')
const messagesContainer = ref(null)
const streamingEnabled = ref(true)

// Language state
const selectedLanguage = ref('')
const availableLanguages = ref([])

// Current user info (fullname + avatar)
const userInfo = ref({ fullname: '', avatar: '' })

// Sidebar toggle (persisted in localStorage)
const sidebarCollapsed = ref(localStorage.getItem('ai_chatbot_sidebar') !== 'expanded')

const toggleSidebar = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('ai_chatbot_sidebar', sidebarCollapsed.value ? 'collapsed' : 'expanded')
}

// PDF conversation export state
const isExportingConversation = ref(false)

// Error display state
const displayError = ref(null)

const dismissError = () => {
  displayError.value = null
  // Clean up streaming error state so canRetry doesn't linger
  resetStreaming()
}

// Search state
const searchResults = ref([])
const isSearching = ref(false)

const handleSearch = async (query) => {
  if (!query.trim()) {
    searchResults.value = []
    isSearching.value = false
    return
  }
  if (query.trim().length < 2) return
  isSearching.value = true
  try {
    const response = await chatAPI.searchConversations(query)
    if (response.success) {
      searchResults.value = response.conversations
    }
  } catch (error) {
    console.error('Search error:', error)
  } finally {
    isSearching.value = false
  }
}

// Voice output (TTS for auto-speak after voice input)
const { speak: speakResponse, isSupported: ttsSupported, warmup: warmupTTS } = useVoiceOutput()
const lastMessageWasVoice = ref(false)

// Empty state: no messages and not currently loading/streaming
const hasNoMessages = computed(() =>
  messages.value.length === 0 && !isLoading.value && !isStreaming.value
)

// User initials for greeting avatar fallback
const greetingInitials = computed(() => {
  const name = userInfo.value?.fullname || ''
  if (!name) return 'U'
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return parts[0][0].toUpperCase()
})

// Streaming composable
const {
  streamingContent,
  isStreaming,
  toolCalls: streamToolCalls,
  processStep,
  streamError,
  agentPlan,
  partialContent,
  canRetry,
  startListening,
  stopListening,
  reset: resetStreaming,
  destroy: destroyStreaming,
} = useStreaming()

// Socket connection
const { initSocket, isConnected, isOnline } = useSocket()

// --- Phase 13A.3: Connection lost banner ---
// Show the banner when EITHER the browser goes offline (instant) OR
// the Socket.IO connection drops (delayed by heartbeat timeout).
const showConnectionBanner = computed(() =>
  (!isConnected.value || !isOnline.value) && streamingEnabled.value && !hasNoMessages.value
)

// --- Phase 13A.4: Smart auto-scroll ---
// Track whether the user has manually scrolled away from the bottom
const userScrolledAway = ref(false)
const SCROLL_THRESHOLD = 100 // px from bottom

const handleScroll = () => {
  if (!messagesContainer.value) return
  const el = messagesContainer.value
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  userScrolledAway.value = distFromBottom > SCROLL_THRESHOLD
}

// Show the "New content" pill when streaming continues but user has scrolled up
const showNewContentPill = computed(() =>
  userScrolledAway.value && isStreaming.value && !!streamingContent.value
)

const scrollToBottomAndResume = () => {
  userScrolledAway.value = false
  scrollToBottom(true)
}

// --- Phase 13A.3: Retry handler ---
// Store the last user message for retry
const lastSentPayload = ref(null)

const handleRetry = async () => {
  if (!currentConversation.value || !lastSentPayload.value) return

  const payload = lastSentPayload.value
  const convId = currentConversation.value.name

  // Clear error UI
  displayError.value = null
  resetStreaming()

  // The user message is already persisted in the DB and loaded into messages[]
  // by the isStreaming watcher's loadMessages() call.  Do NOT push another
  // optimistic user message — just re-send the API request.

  isLoading.value = true
  userScrolledAway.value = false
  scrollToBottom(true)

  // Wait for socket to be ready if streaming is enabled.
  // After Wi-Fi restore, the online handler re-creates the socket with a 500ms delay
  // and the handshake may take another 1-2s.  We poll for up to 5s.
  const useStream = await _waitForStreamingReady()

  try {
    if (useStream) {
      startListening(convId)

      const response = await chatAPI.sendMessageStreaming(
        convId,
        payload.message,
        payload.attachments?.length ? payload.attachments : null,
        { isRetry: true }
      )

      if (!response.success) {
        stopListening()
        displayError.value = response.error || 'Failed to send message. Please try again.'
        isLoading.value = false
      }
      // isLoading stays true until streaming ends (handled by watcher)
    } else {
      // Non-streaming fallback
      const response = await chatAPI.sendMessage(
        convId,
        payload.message,
        false,
        payload.attachments?.length ? payload.attachments : null,
        { isRetry: true }
      )

      if (response.success) {
        const assistantContent = response.message
        messages.value.push({
          _tempId: `temp_resp_${Date.now()}`,
          role: 'assistant',
          content: assistantContent,
          timestamp: new Date().toISOString(),
          tokens_used: response.tokens_used,
        })
      } else {
        displayError.value = response.error || 'Failed to get a response. Please try again.'
      }

      isLoading.value = false
      await loadMessages(convId)
      await loadConversations()
    }
  } catch (error) {
    console.error('Error retrying message:', error)
    displayError.value = error?.message || 'An unexpected error occurred. Please try again.'
    isLoading.value = false
    stopListening()
  }
}

/**
 * Wait for the socket to be connected and streaming-ready.
 * Returns true if streaming should be used, false to fall back to non-streaming.
 * Polls every 200ms for up to 5s after Wi-Fi restore.
 */
async function _waitForStreamingReady() {
  if (!streamingEnabled.value) return false
  if (isConnected.value) return true

  // Socket may still be connecting after Wi-Fi restore — poll briefly
  const maxWait = 5000
  const interval = 200
  let waited = 0

  // Make sure socket init has been triggered
  initSocket()

  while (waited < maxWait) {
    await new Promise(r => setTimeout(r, interval))
    waited += interval
    if (isConnected.value) return true
  }

  console.warn('[AI Chatbot] Socket not ready after', maxWait, 'ms — falling back to non-streaming')
  return false
}

// Render streaming markdown content
const renderedStreamingContent = computed(() => {
  if (!streamingContent.value) return ''
  try {
    return renderMarkdown(streamingContent.value)
  } catch {
    return streamingContent.value
  }
})

onMounted(async () => {
  // Load settings and conversations in parallel
  const [settingsResult] = await Promise.all([
    chatAPI.getSettings().catch(() => null),
    loadConversations(),
  ])

  if (settingsResult?.success) {
    streamingEnabled.value = settingsResult.settings.enable_streaming ?? true
    if (settingsResult.settings.ai_provider) {
      selectedProvider.value = settingsResult.settings.ai_provider
    }
    if (settingsResult.user) {
      userInfo.value = settingsResult.user
    }
    if (settingsResult.settings.response_language !== undefined) {
      selectedLanguage.value = settingsResult.settings.response_language
    }
    if (settingsResult.settings.available_languages) {
      availableLanguages.value = settingsResult.settings.available_languages
    }
  }

  // Initialize Socket.IO connection if streaming is enabled
  if (streamingEnabled.value) {
    initSocket()
  }

  // Show greeting state (no conversation created yet — lazy creation on first message)
  currentConversation.value = null
  messages.value = []
  selectedLanguage.value = ''
})

onUnmounted(() => {
  destroyStreaming()
})

const loadConversations = async () => {
  try {
    const response = await chatAPI.getConversations()
    if (response.success) {
      conversations.value = response.conversations
    }
  } catch (error) {
    console.error('Error loading conversations:', error)
  }
}

const handleNewChat = () => {
  // Reset to greeting state — conversation is created lazily on first message
  stopListening()
  resetStreaming()
  currentConversation.value = null
  messages.value = []
  selectedLanguage.value = ''
}

const ensureConversation = async () => {
  if (currentConversation.value) return true
  try {
    const response = await chatAPI.createConversation(
      'New Chat',
      selectedProvider.value
    )
    if (response.success) {
      await loadConversations()
      const newConv = conversations.value.find(c => c.name === response.conversation_id)
      currentConversation.value = newConv || response.data || {
        name: response.conversation_id,
        title: 'New Chat',
        ai_provider: selectedProvider.value,
      }
      return true
    }
    return false
  } catch (error) {
    console.error('Error creating conversation:', error)
  }
  return false
}

const handleSelectConversation = async (conversation) => {
  // Stop any active streaming
  stopListening()
  resetStreaming()

  currentConversation.value = conversation
  await loadMessages(conversation.name)
}

const loadMessages = async (conversationId) => {
  try {
    const response = await chatAPI.getConversationMessages(conversationId)
    if (response.success) {
      messages.value = response.messages
      // Load conversation-level language preference from session context
      if (response.session_context?.response_language) {
        selectedLanguage.value = response.session_context.response_language
      } else {
        selectedLanguage.value = ''
      }
      await nextTick()
      scrollToBottom()
    }
  } catch (error) {
    console.error('Error loading messages:', error)
  }
}

const handleSendMessage = async (payload) => {
  // Accept structured payload: { message, attachments, voiceInput }
  const message = typeof payload === 'string' ? payload : payload.message
  const attachments = typeof payload === 'string' ? [] : (payload.attachments || [])
  const voiceInput = typeof payload === 'string' ? false : (payload.voiceInput || false)

  if (!message.trim() && attachments.length === 0) return

  // Lazily create conversation on first message
  if (!currentConversation.value) {
    const created = await ensureConversation()
    if (!created) {
      displayError.value = 'Failed to create conversation. Please try again.'
      return
    }
  }

  // Clear any previous error
  displayError.value = null

  // Store payload for retry (Phase 13A.3)
  lastSentPayload.value = { message, attachments, voiceInput }

  // Track whether this was a voice message (for auto-speak)
  lastMessageWasVoice.value = voiceInput

  // Upload files first (if any)
  let uploadedAttachments = null
  if (attachments.length > 0) {
    try {
      const uploadResults = await Promise.all(
        attachments.map((att) =>
          chatAPI.uploadFile(currentConversation.value.name, att.file)
        )
      )
      uploadedAttachments = uploadResults.filter((r) => r.success).map((r) => ({
        file_url: r.file_url,
        file_name: r.file_name,
        mime_type: r.mime_type,
        size: r.size,
        is_image: r.is_image,
      }))
    } catch (error) {
      console.error('File upload error:', error)
      // Continue sending message without attachments
    }
  }

  // Add user message optimistically
  const userMessage = {
    _tempId: `temp_${Date.now()}`,
    role: 'user',
    content: message,
    timestamp: new Date().toISOString(),
    attachments: uploadedAttachments,
  }
  messages.value.push(userMessage)
  await nextTick()
  userScrolledAway.value = false
  scrollToBottom(true)

  isLoading.value = true

  const useStream = streamingEnabled.value && isConnected.value

  try {
    if (useStream) {
      // Streaming mode: start listening before sending
      startListening(currentConversation.value.name)

      // HTTP response returns immediately with stream_id.
      // Tokens arrive via Socket.IO realtime events.
      const response = await chatAPI.sendMessageStreaming(
        currentConversation.value.name,
        message,
        uploadedAttachments
      )

      if (!response.success) {
        stopListening()
        console.error('Streaming request failed:', response.error)
        displayError.value = response.error || 'Failed to send message. Please try again.'
        isLoading.value = false
        return
      }

      // isLoading stays true until streaming ends (handled by watcher below)
    } else {
      // Non-streaming fallback
      const response = await chatAPI.sendMessage(
        currentConversation.value.name,
        message,
        false,
        uploadedAttachments
      )

      if (response.success) {
        const assistantContent = response.message
        messages.value.push({
          _tempId: `temp_resp_${Date.now()}`,
          role: 'assistant',
          content: assistantContent,
          timestamp: new Date().toISOString(),
          tokens_used: response.tokens_used,
        })

        // Auto-speak if this was a voice-initiated message
        if (lastMessageWasVoice.value && ttsSupported.value && assistantContent) {
          setTimeout(() => speakResponse(assistantContent), 100)
          lastMessageWasVoice.value = false
        }
      } else {
        displayError.value = response.error || 'Failed to get a response. Please try again.'
      }

      isLoading.value = false
      await loadMessages(currentConversation.value.name)
      await loadConversations()
    }
  } catch (error) {
    console.error('Error sending message:', error)
    displayError.value = error?.message || 'An unexpected error occurred. Please try again.'
    isLoading.value = false
    stopListening()
  }
}

const handleStopGeneration = () => {
  stopListening()
  isLoading.value = false
}

const handleDeleteConversation = async (conversationId) => {
  try {
    const response = await chatAPI.deleteConversation(conversationId)
    if (response.success) {
      await loadConversations()
      if (currentConversation.value?.name === conversationId) {
        currentConversation.value = null
        messages.value = []
      }
    }
  } catch (error) {
    console.error('Error deleting conversation:', error)
  }
}

const handleExportConversation = async () => {
  if (!currentConversation.value || isExportingConversation.value) return
  isExportingConversation.value = true
  try {
    const result = await chatAPI.exportConversationPdf(currentConversation.value.name)
    if (result.success && result.file_url) {
      const a = document.createElement('a')
      a.href = result.file_url
      a.download = ''
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } else {
      displayError.value = result.error || 'Failed to export conversation as PDF.'
    }
  } catch (error) {
    console.error('Conversation PDF export error:', error)
    displayError.value = 'Failed to export conversation as PDF.'
  } finally {
    isExportingConversation.value = false
  }
}

// --- Scroll logic (Phase 13A.4) ---

const scrollToBottom = (force = false) => {
  if (messagesContainer.value) {
    const el = messagesContainer.value
    if (force) {
      el.scrollTop = el.scrollHeight
      userScrolledAway.value = false
      return
    }
    // Only auto-scroll if user has NOT manually scrolled away
    if (!userScrolledAway.value) {
      el.scrollTop = el.scrollHeight
    }
  }
}

// When streaming ends, reload messages to get the persisted version.
// IMPORTANT: If the stream ended due to an error (_abortStream), do NOT call
// resetStreaming() — that would clear canRetry/streamError before the error
// watcher has a chance to display them.
watch(isStreaming, async (newVal, oldVal) => {
  if (oldVal && !newVal && currentConversation.value) {
    // Check if this was an error-triggered stop (streamError is already set)
    const wasError = !!streamError.value

    // Capture content before any resets — streamingContent may be cleared later
    const finalContent = streamingContent.value
    const wasVoice = lastMessageWasVoice.value

    // Bridge the visual gap: push a temporary assistant message so the user
    // doesn't see a flash of empty space while loadMessages() fetches from DB.
    if (finalContent) {
      messages.value.push({
        _tempId: `temp_stream_${Date.now()}`,
        role: 'assistant',
        content: finalContent,
        timestamp: new Date().toISOString(),
      })
    }

    isLoading.value = false
    await loadMessages(currentConversation.value.name)
    await loadConversations()

    // Only reset streaming state on normal completion, not on errors
    if (!wasError) {
      resetStreaming()
    }

    // Auto-speak after stream ends (voice input only, not on errors).
    if (!wasError && wasVoice && ttsSupported.value && finalContent) {
      setTimeout(() => {
        speakResponse(finalContent)
      }, 100)
      lastMessageWasVoice.value = false
    }

    // Force scroll after reload
    await nextTick()
    scrollToBottom(true)
    setTimeout(() => scrollToBottom(true), 300)
  }
})

// Auto-scroll during streaming (only if user hasn't scrolled away)
watch(streamingContent, () => {
  nextTick(() => scrollToBottom())
})

// Auto-scroll on new messages
watch(messages, () => {
  nextTick(() => scrollToBottom())
}, { deep: true })

// Handle stream errors — display in chat UI (Phase 13A.3 enhanced)
watch(streamError, (error) => {
  if (error) {
    console.error('Stream error:', error)
    isLoading.value = false
    displayError.value = error
    nextTick(() => scrollToBottom(true))
  }
})
</script>
