export type ModelConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  apiType: "chat_completions" | "responses";
  temperature: number;
  offlineMode: boolean;
};

export type RoundProgress = {
  phase: string;
  round: number;
  currentChunk?: number;
  totalChunks?: number;
  chunkId?: string;
  paragraphIndex?: number;
  chunkIndex?: number;
  paragraphCount?: number;
  inputPath?: string;
  outputPath?: string;
};

export type TestConnectionResult = {
  ok: boolean;
  offlineMode: boolean;
  message: string;
  endpoint: string;
  model: string;
  apiType?: "chat_completions" | "responses";
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
  latestOutputPath: string;
  extractedFromDocx: boolean;
};

export type RoundResult = {
  round: number;
  outputPath: string;
  manifestPath: string;
  chunkLimit: number;
  inputSegmentCount: number;
  outputSegmentCount: number;
  paragraphCount: number;
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
