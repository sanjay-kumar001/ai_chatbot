<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->
<template>
  <!-- Collapsed sidebar: icon-only strip -->
  <div
    v-if="sidebarCollapsed"
    class="w-14 bg-gray-50 dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 flex flex-col h-full py-3 items-center gap-3"
  >
    <button
      @click="$emit('toggle-sidebar')"
      class="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
      title="Expand sidebar"
    >
      <PanelLeftOpen :size="20" class="text-gray-600 dark:text-gray-400" />
    </button>
    <button
      @click="$emit('new-chat')"
      class="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
      title="New chat"
    >
      <Plus :size="20" class="text-gray-600 dark:text-gray-400" />
    </button>
    <button
      @click="$emit('toggle-sidebar')"
      class="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
      title="Search conversations"
    >
      <Search :size="20" class="text-gray-600 dark:text-gray-400" />
    </button>
  </div>

  <!-- Expanded sidebar: full layout -->
  <div
    v-else
    class="w-64 bg-gray-50 dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 flex flex-col h-full"
  >
    <!-- Header Row: Logo (left) | Settings + Toggle (right) -->
    <div class="flex items-center justify-between px-3 py-3 border-b border-gray-200 dark:border-gray-800">
      <img :src="sidebarLogo" alt="AI Chatbot" class="w-8 h-8" />
      <div class="flex items-center gap-1">
        <button
          @click="openSettings"
          class="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
          title="Chatbot Settings"
        >
          <Settings :size="20" class="text-gray-600 dark:text-gray-400" />
        </button>
        <button
          @click="$emit('toggle-sidebar')"
          class="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
          title="Collapse sidebar"
        >
          <PanelLeftClose :size="20" class="text-gray-600 dark:text-gray-400" />
        </button>
      </div>
    </div>

    <!-- New Chat Button -->
    <div class="px-3 pt-3 pb-2">
      <button
        @click="$emit('new-chat')"
        class="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors font-medium text-sm"
      >
        <Plus :size="16" />
        New Chat
      </button>
    </div>

    <!-- Search Input -->
    <div class="px-3 pb-2">
      <div class="relative">
        <Search :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          v-model="localSearchQuery"
          @input="handleSearchInput"
          type="text"
          placeholder="Search conversations..."
          class="w-full pl-9 pr-8 py-2 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder-gray-400 dark:text-gray-200 transition-colors"
        />
        <button
          v-if="localSearchQuery"
          @click="clearSearch"
          class="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        >
          <X :size="14" />
        </button>
      </div>
    </div>

    <!-- Conversation List -->
    <div class="flex-1 overflow-y-auto px-3">
      <!-- Search Results -->
      <template v-if="localSearchQuery">
        <div v-if="isSearching" class="flex items-center justify-center py-8">
          <div class="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
        </div>
        <div v-else-if="searchResults.length === 0" class="text-center py-8 text-gray-400">
          <Search :size="32" class="mx-auto mb-2 opacity-50" />
          <p class="text-sm">No results found</p>
        </div>
        <div v-else class="space-y-1">
          <div
            v-for="conversation in searchResults"
            :key="conversation.name"
            :class="conversationItemClasses(conversation)"
            @click="handleSearchResultClick(conversation)"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex-1 min-w-0">
                <h3 class="text-sm text-gray-800 dark:text-gray-200 truncate">
                  {{ conversation.title || 'New Conversation' }}
                </h3>
              </div>
              <button
                @click.stop="$emit('delete-conversation', conversation.name)"
                class="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
              >
                <Trash2 :size="14" class="text-red-500" />
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Grouped Conversations -->
      <template v-else>
        <div v-if="conversations.length === 0" class="text-center py-8 text-gray-400">
          <MessageSquare :size="32" class="mx-auto mb-2 opacity-50" />
          <p class="text-sm">No conversations yet</p>
          <p class="text-xs mt-1">Start a new chat to begin</p>
        </div>

        <div v-else>
          <template v-for="(group, label) in groupedConversations" :key="label">
            <div v-if="group.length > 0" class="mb-3">
              <div class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider px-2 py-1.5">
                {{ label }}
              </div>
              <div class="space-y-0.5">
                <div
                  v-for="conversation in group"
                  :key="conversation.name"
                  :class="conversationItemClasses(conversation)"
                  @click="$emit('select-conversation', conversation)"
                >
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex-1 min-w-0">
                      <h3 class="text-sm text-gray-800 dark:text-gray-200 truncate">
                        {{ conversation.title || 'New Conversation' }}
                      </h3>
                    </div>
                    <button
                      @click.stop="$emit('delete-conversation', conversation.name)"
                      class="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                    >
                      <Trash2 :size="14" class="text-red-500" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- Bottom Panel -->
    <div class="px-3 py-3 border-t border-gray-200 dark:border-gray-800">
      <div class="text-xs text-gray-400 dark:text-gray-500 text-center">
        AI Chatbot
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  Plus, Search, Settings, Trash2, MessageSquare,
  PanelLeftOpen, PanelLeftClose, X,
} from 'lucide-vue-next'
import sidebarLogo from '../assets/logo.png'

const props = defineProps({
  conversations: {
    type: Array,
    default: () => [],
  },
  currentConversation: {
    type: Object,
    default: null,
  },
  sidebarCollapsed: {
    type: Boolean,
    default: false,
  },
  searchResults: {
    type: Array,
    default: () => [],
  },
  isSearching: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'new-chat', 'select-conversation', 'delete-conversation',
  'toggle-sidebar', 'search',
])

const localSearchQuery = ref('')

// Group conversations by date
const groupedConversations = computed(() => {
  const groups = {
    'Today': [],
    'Yesterday': [],
    'Last 7 Days': [],
    'Older': [],
  }

  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const lastWeek = new Date(today)
  lastWeek.setDate(lastWeek.getDate() - 7)

  for (const conv of props.conversations) {
    const date = new Date(conv.updated_at || conv.created_at || conv.creation)
    if (date >= today) {
      groups['Today'].push(conv)
    } else if (date >= yesterday) {
      groups['Yesterday'].push(conv)
    } else if (date >= lastWeek) {
      groups['Last 7 Days'].push(conv)
    } else {
      groups['Older'].push(conv)
    }
  }

  return groups
})

const conversationItemClasses = (conversation) => [
  'group relative px-3 py-2.5 rounded-lg cursor-pointer transition-all',
  conversation.name === props.currentConversation?.name
    ? 'bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800'
    : 'hover:bg-gray-100 dark:hover:bg-gray-800/50',
]

let searchTimer = null
const handleSearchInput = () => {
  clearTimeout(searchTimer)
  const query = localSearchQuery.value.trim()
  if (!query) {
    emit('search', '')
    return
  }
  searchTimer = setTimeout(() => {
    emit('search', query)
  }, 300)
}

const clearSearch = () => {
  localSearchQuery.value = ''
  emit('search', '')
}

const handleSearchResultClick = (conversation) => {
  emit('select-conversation', conversation)
  localSearchQuery.value = ''
  emit('search', '')
}

const openSettings = () => {
  window.open('/app/chatbot-settings', '_blank')
}
</script>
