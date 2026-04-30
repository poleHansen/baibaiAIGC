export type ApiType = "chat_completions" | "responses";
export type PromptProfile = "cn" | "en";
export type RoundProgressPhase =
  | "chunking-ready"
  | "chunk-skipped"
  | "processing-chunk"
  | "chunk-error"
  | "chunk-complete"
  | "restoring-output"
  | "stopped";

export type ModelConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  apiType: ApiType;
  temperature: number;
  offlineMode: boolean;
  promptProfile: PromptProfile;
};

export const DEFAULT_MODEL_CONFIG: ModelConfig = {
  baseUrl: "",
  apiKey: "",
  model: "",
  apiType: "chat_completions",
  temperature: 0.7,
  offlineMode: false,
  promptProfile: "cn",
};

export function normalizeModelConfig(config?: Partial<ModelConfig> | null): ModelConfig {
  return {
    baseUrl: String(config?.baseUrl ?? DEFAULT_MODEL_CONFIG.baseUrl),
    apiKey: String(config?.apiKey ?? DEFAULT_MODEL_CONFIG.apiKey),
    model: String(config?.model ?? DEFAULT_MODEL_CONFIG.model),
    apiType: config?.apiType === "responses" ? "responses" : "chat_completions",
    temperature: typeof config?.temperature === "number" && Number.isFinite(config.temperature)
      ? config.temperature
      : DEFAULT_MODEL_CONFIG.temperature,
    offlineMode: Boolean(config?.offlineMode),
    promptProfile: config?.promptProfile === "en" ? "en" : "cn",
  };
}

export type RoundProgress = {
  phase: RoundProgressPhase;
  round: number;
  currentChunk?: number;
  totalChunks?: number;
  completedChunks?: number;
  remainingChunks?: number;
  chunkId?: string;
  paragraphIndex?: number;
  chunkIndex?: number;
  paragraphCount?: number;
  inputPath?: string;
  outputPath?: string;
  manifestPath?: string;
  progressPath?: string;
  resumed?: boolean;
  error?: string;
  message?: string;
};

export type TestConnectionResult = {
  ok: boolean;
  offlineMode: boolean;
  message: string;
  endpoint: string;
  model: string;
  apiType?: ApiType;
  status?: number;
};

export type DocumentStatus = {
  docId: string;
  sourcePath: string;
  sourceKind: string;
  completedRounds: number[];
  nextRound: number | null;
  maxRounds: number;
  hasNextRound: boolean;
  isComplete: boolean;
  currentInputPath: string;
  currentOutputPath: string;
  manifestPath: string;
  progressPath: string;
  progressStatus: string;
  completedChunkCount: number;
  totalChunkCount: number;
  lastError: string;
  lastErrorChunkId: string;
  stopRequested: boolean;
  stopReason: string;
  latestOutputPath: string;
  extractedFromDocx: boolean;
};

export type RoundResult = {
  round: number;
  outputPath: string;
  manifestPath: string;
  progressPath: string;
  chunkLimit: number;
  inputSegmentCount: number;
  outputSegmentCount: number;
  completedChunkCount: number;
  paragraphCount: number;
  resumed: boolean;
  offlineMode: boolean;
  docEntry: Record<string, unknown>;
  skillContext: Record<string, unknown>;
};

export type HistoryRound = {
  round: number;
  prompt: string;
  inputPath: string;
  outputPath: string;
  manifestPath: string;
  progressPath: string;
  progressStatus: string;
  completedChunkCount: number;
  totalChunkCount: number;
  lastError: string;
  lastErrorChunkId: string;
  stopRequested: boolean;
  stopReason: string;
  scoreTotal: number | null;
  chunkLimit: number | null;
  inputSegmentCount: number | null;
  outputSegmentCount: number | null;
  timestamp: string;
};

export type DocumentHistory = {
  docId: string;
  sourcePath: string;
  rounds: HistoryRound[];
};

export type HistoryDocumentSummary = {
  docId: string;
  sourcePath: string;
  originPath: string;
  completedRounds: number[];
  latestOutputPath: string;
  lastTimestamp: string;
  rounds: HistoryRound[];
};

export type HistoryListResponse = {
  items: HistoryDocumentSummary[];
  total: number;
};

export type DeleteHistoryResult = {
  docId: string;
  deletedRounds: number[];
  remainingRounds: number[];
  removedDocument: boolean;
  deletedFiles: string[];
};

export type ExportResult = {
  format: "txt" | "docx";
  path: string;
};
