import http from './http'

export type LlmProviderType =
  | 'openai'
  | 'azure_openai'
  | 'deepseek'
  | 'claude'
  | 'ollama'
  | 'qwen'
  | 'custom'

export interface LlmProvider {
  id: number
  name: string
  provider: LlmProviderType
  model: string
  base_url?: string | null
  temperature: number
  max_tokens?: number | null
  is_default: boolean
  enabled: boolean
  has_api_key: boolean
  owner_id: number
}

export const llmApi = {
  list: () => http.get<unknown, LlmProvider[]>('/llm/providers'),
  create: (data: Partial<LlmProvider> & { api_key?: string }) =>
    http.post<unknown, LlmProvider>('/llm/providers', data),
  update: (id: number, data: Partial<LlmProvider> & { api_key?: string }) =>
    http.put<unknown, LlmProvider>(`/llm/providers/${id}`, data),
  remove: (id: number) => http.delete(`/llm/providers/${id}`),
  test: (id: number, prompt: string) =>
    http.post<unknown, { ok: boolean; output?: string; error?: string }>(
      `/llm/providers/${id}/test`,
      { prompt }
    )
}

export interface PromptTemplate {
  id: number
  name: string
  description?: string | null
  system_prompt: string
  keywords?: string[] | null
  filter_rules?: Record<string, unknown> | null
  output_schema?: Record<string, unknown> | null
  is_active: boolean
}

export const promptApi = {
  list: () => http.get<unknown, PromptTemplate[]>('/llm/prompts'),
  create: (data: Partial<PromptTemplate>) =>
    http.post<unknown, PromptTemplate>('/llm/prompts', data),
  update: (id: number, data: Partial<PromptTemplate>) =>
    http.put<unknown, PromptTemplate>(`/llm/prompts/${id}`, data),
  remove: (id: number) => http.delete(`/llm/prompts/${id}`)
}
